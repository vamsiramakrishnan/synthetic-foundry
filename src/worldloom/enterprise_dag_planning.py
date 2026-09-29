"""Bind versioned trajectory templates to a query's authored source roles."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Literal

from .enterprise_dag import (
    GRAMMAR_VERSION,
    EnterpriseDag,
    EnterpriseDagNode,
    ResultCondition,
    ResultIteration,
    ResultReference,
    shape_catalogue,
)
from .enterprise_queries import MutationRequirement, PlannedEnterpriseQuery
from .evidence_placement import (
    CONTENTLESS_OPERATIONS,
    MESSAGE_OPERATIONS,
    carries_evidence,
    document_arguments,
    placement,
    plannable,
)
from .ids import content_key


@lru_cache(maxsize=128)
def _admits_update(connector: str, entity: str, output_format: str) -> bool:
    from .connector_definition import load_connector_definition
    try:
        definition = load_connector_definition(connector)
        concrete = output_format if output_format in definition.entity_members(entity) else entity
        definition.tool_for(concrete, "update")
    except (KeyError, ValueError):
        return False
    return True


@lru_cache(maxsize=128)
def _admits_delete(connector: str, entity: str, output_format: str) -> bool:
    from .connector_definition import load_connector_definition
    try:
        definition = load_connector_definition(connector)
        concrete = output_format if output_format in definition.entity_members(entity) else entity
        definition.tool_for(concrete, "delete")
    except (KeyError, ValueError):
        return False
    return True


@lru_cache(maxsize=128)
def _reads_target_first(connector: str, entity: str, output_format: str, operation: str) -> bool:
    """The safety law ``destructive_without_read`` holds this write: plan a read of its target first.

    Asked of the grader's own classification (``evalrun.safety``), so the
    gold plan and the law it is graded under cannot disagree: a delete, a
    reply and a forward address a record that must have been read; a send
    that names no record, a create and an update do not. A connector the
    planner cannot load keeps the one case it always planned: a delete.
    """
    from .connector_definition import load_connector_definition
    from .evalrun.safety import classify_tool
    try:
        definition = load_connector_definition(connector)
        concrete = output_format if output_format in definition.entity_members(entity) else entity
        name = definition.tool_for(concrete, operation)
    except (KeyError, ValueError):
        return operation == "delete"
    return classify_tool(connector, name, definition.tool(name)).reads_first


def _shape_grounds(template: dict[str, Any], row: dict[str, str], inventory: Mapping[tuple[str, str], int]) -> bool:
    """The world holds the evidence a shape demands of each source beyond the role's minimum.

    ``apply_dag_shape`` raises a source's minimum to two for a mapped read
    (every source) and for a conditional (its first source, by a draw on the
    query id that lands on two half the time). A world with one evidence
    record for that source would then materialise a filler and fail at
    validate, so the shape is not decided for the row. The conditional draw
    cannot be reproduced from a stub row, so a conditional asks for both
    witnesses.
    """
    sources = row["source_entities"].split("+")
    if template["reads"] == "map":
        demands = [2] * len(sources)
    elif template["control"] == "conditional":
        demands = [2, *[1] * (len(sources) - 1)]
    else:
        return True
    return all(
        inventory.get((source.split(":", 1)[0], source.split(":", 1)[1]), 0) >= demand
        for source, demand in zip(sources, demands, strict=True)
    )


def compatible_shapes(
    row: dict[str, str], requested: tuple[str, ...], *, inventory: Mapping[tuple[str, str], int] | None = None,
) -> tuple[str, ...]:
    catalogue = shape_catalogue()
    names = tuple(sorted(catalogue)) if requested == ("*",) else requested
    if len(names) != len(set(names)):
        raise ValueError("duplicate DAG shape selection")
    unknown = set(names) - catalogue.keys()
    if unknown:
        raise ValueError(f"unknown DAG shapes: {sorted(unknown)}")
    if row.get("failure", "none") not in {"none", "permission_denied", "missing_stable_id", "version_conflict", "partial_write"}:
        return ()
    compatible = []
    for name in names:
        if name == "read_chain" and "+" not in row["source_entities"]:
            continue
        if name == "fan_out" and row["operation"] not in {"create", "draft", "send"}:
            continue
        if name == "write_chain" and not (
                _admits_update(row["destination"], row["destination_entity"], row["output_format"])
                and plannable(row["destination"], row["destination_entity"], "update")):
            # The marker is an update of the evidence's place: a place no
            # update can reach on the contract surface cannot be marked.
            continue
        if name == "delete_chain" and not _admits_delete(row["destination"], row["destination_entity"], row["output_format"]):
            continue
        if inventory is not None and not _shape_grounds(catalogue[name], row, inventory):
            continue
        compatible.append(name)
    return tuple(compatible)


#: The diamond after ``collect``: two views of the same records (identifiers,
#: and identifiers with titles), joined back on the record: a ``unique`` keyed
#: on ``id`` over both views keeps one entry per record, because a record read
#: through both views is still one piece of evidence. Concatenating the views
#: counted every record twice, and the output stage, which counts distinct
#: evidence records, refused the reference's own write. Each entry is (node,
#: parents, transform, fields).
DIAMOND_JOIN: tuple[tuple[str, tuple[str, ...], str, tuple[str, ...]], ...] = (
    ("identifiers", ("collect",), "project", ("id",)),
    ("titles", ("collect",), "project", ("id", "title")),
    ("joined", ("identifiers", "titles"), "unique", ("id",)),
)


#: The line a verification marker adds to the evidence document it rewrites.
VERIFIED_NOTE = "Verified against the saved record."


def _outline(identifier: str, parent: str, arguments: dict[str, Any]) -> EnterpriseDagNode:
    return EnterpriseDagNode.model_validate({
        "id": identifier, "kind": "transform", "operation": "outline",
        "connector": "model", "entity": "resultset", "depends_on": (parent,), "transform": "outline",
        "arguments": arguments,
    })


def write_body(mutation: MutationRequirement, result: str,
               sections: tuple[str, ...]) -> tuple[list[EnterpriseDagNode], ResultReference]:
    """The transform a write's content needs, and the reference it binds.

    A message write (a reply, a forward, a comment) carries its output as the
    body, and when the case names the sections its output must have, the
    body is an outline of those sections over the evidence (the ``outline``
    transform), never the raw result set, which carries none of them.

    A record write carries its evidence where its connector declares it is
    kept (``evidence_placement``): a document over the evidence, in the
    place's format, under the case's sections or one ``Evidence`` section,
    bound to that one field. A connector that declares no place keeps the
    raw result set in the generic fields, which only the emulator takes.
    """
    if mutation.operation in MESSAGE_OPERATIONS and sections:
        return [_outline("document", result, {"sections": sections, "format": mutation.output_format or "markdown"})], \
            ResultReference(node="document")
    found = placement(mutation.connector, mutation.entity) if carries_evidence(mutation.operation) else None
    if found is not None:
        return [_outline("document", result, document_arguments(sections, found.format))], ResultReference(node="document")
    return [], ResultReference(node=result, select="all", encoding="json")


#: The name ``write_body`` had while a message's body was the only content a write carried.
message_body = write_body


def _evidence_bindings(mutation: MutationRequirement, result: str, body: ResultReference) -> dict[str, ResultReference]:
    """What a record write binds: the evidence document at the declared place, else the generic fields."""
    found = placement(mutation.connector, mutation.entity)
    if found is not None and body.node != result:
        return {f"fields.{found.field}": body}
    return {"fields.evidence": ResultReference(node=result, select="all"),
            "fields.evidence_count": ResultReference(node=result, select="count")}


def _restates_record(mutation: MutationRequirement) -> bool:
    """The place's write restates an existing record (``read_first``), so a client reads it first."""
    found = placement(mutation.connector, mutation.entity) if carries_evidence(mutation.operation) else None
    return (found is not None and found.read_first and mutation.preexisting_record
            and mutation.operation in {"update", "patch", "upsert"})


def write_nodes(mutation: MutationRequirement, result: str, body: ResultReference, identifier: str,
                condition: ResultCondition | None = None) -> list[EnterpriseDagNode]:
    """One planned write: the read of its target when it needs one, the write, and its readback.

    What the write carries from the reads: a message carries *body*; a
    record write carries the evidence document at its connector's declared
    place (``write_body``); a delete or move carries nothing, because its
    tool takes only the record id (and a parent), and an argument the tool
    does not accept is a row the compiler refuses.

    A move takes its record's id from a read, as a delete does. A write the
    law ``destructive_without_read`` holds (a delete, a reply, a forward:
    ``_reads_target_first`` asks the grader's own classification) reads what
    it acts on first, because the law demands it of every agent and the
    reference is one; the write takes the id from that read, never from a
    source record. A write whose place restates the record (a page ``PUT``
    carries the page's title and next version) reads it first as well, and
    still addresses its own destination. The read of the target does not
    wait on the evidence (an agent may open the thread before or after
    gathering it); a conditional one waits only on the read its condition
    inspects.
    """
    out: list[EnterpriseDagNode] = []
    bindings: dict[str, ResultReference]
    if mutation.operation in MESSAGE_OPERATIONS:
        bindings = {"body": body}
    elif mutation.operation in CONTENTLESS_OPERATIONS:
        bindings = {}
    else:
        bindings = _evidence_bindings(mutation, result, body)
    feed = body.node if mutation.operation in MESSAGE_OPERATIONS or body.node != result else result
    parents: tuple[str, ...] = (feed,)
    addressed = mutation.operation == "move" or _reads_target_first(
        mutation.connector, mutation.entity, mutation.output_format, mutation.operation)
    if addressed or _restates_record(mutation):
        out.append(EnterpriseDagNode(
            id=f"target-{identifier}", kind="verify", operation="read",
            connector=mutation.connector, entity=mutation.entity,
            depends_on=(condition.reference.node,) if condition is not None else (),
            condition=condition,
        ))
        parents = (feed, f"target-{identifier}")
        if addressed:
            bindings = {**bindings, "id": ResultReference(node=f"target-{identifier}", path=("id",))}
    out.append(EnterpriseDagNode(
        id=identifier, kind="write", operation=mutation.operation,
        connector=mutation.connector, entity=mutation.entity,
        depends_on=parents, condition=condition, bindings=bindings,
    ))
    out.append(EnterpriseDagNode(
        id=f"verify-{identifier}", kind="verify", operation="read",
        connector=mutation.connector, entity=mutation.entity,
        depends_on=(identifier,), condition=condition,
        bindings={"id": ResultReference(node=identifier, path=("id",))},
    ))
    return out


def marker_nodes(mutation: MutationRequirement, result: str, sections: tuple[str, ...]) -> list[EnterpriseDagNode]:
    """``write_chain``'s tail: mark the record the readback returned as verified, then read it back again.

    The marker goes where the evidence went: the evidence document again,
    with a line saying it was verified, at the declared place, so the
    evidence the first write left is still there after it. A connector that
    declares no place keeps the generic ``verified`` field, which only the
    emulator takes.
    """
    out: list[EnterpriseDagNode] = []
    arguments: dict[str, Any] = {}
    bindings = {"id": ResultReference(node="verify-write", path=("id",))}
    parents: tuple[str, ...] = ("verify-write",)
    found = placement(mutation.connector, mutation.entity)
    if found is not None:
        out.append(_outline("document-verified", result,
                            document_arguments(sections, found.format, note=VERIFIED_NOTE)))
        bindings[f"fields.{found.field}"] = ResultReference(node="document-verified")
        parents = ("verify-write", "document-verified")
    else:
        arguments = {"fields": {"verified": True}}
    out.extend((
        EnterpriseDagNode(
            id="write-marker", kind="write", operation="update",
            connector=mutation.connector, entity=mutation.entity,
            depends_on=parents, arguments=arguments, bindings=bindings,
        ),
        EnterpriseDagNode(
            id="verify-marker", kind="verify", operation="read",
            connector=mutation.connector, entity=mutation.entity,
            depends_on=("write-marker",),
            bindings={"id": ResultReference(node="write-marker", path=("id",))},
        ),
    ))
    return out


def apply_dag_shape(query: PlannedEnterpriseQuery, shape: str) -> PlannedEnterpriseQuery:
    try:
        template = shape_catalogue()[shape]
    except KeyError as error:
        raise ValueError(f"unknown DAG shape {shape!r}") from error
    requirements = query.generation.source_requirements
    if template["reads"] == "map":
        requirements = tuple(source.model_copy(update={"minimum": max(source.minimum, 2)}) for source in requirements)
    elif template["control"] == "conditional" and requirements:
        # Both branches need deterministic witnesses in a generated campaign.
        minimum = 1 + int(content_key(query.id)[:2], 16) % 2
        requirements = (requirements[0].model_copy(update={"minimum": max(requirements[0].minimum, minimum)}), *requirements[1:])
    mutation = query.generation.mutation
    nodes: list[EnterpriseDagNode] = []
    read_ids: list[str] = []
    for index, source in enumerate(requirements):
        identifier = f"read-{index}"
        parents = (read_ids[-1],) if read_ids and template["reads"] == "chain" else ()
        mode: Literal["read", "search"] = "search" if template["reads"] in {"map", "search"} or source.minimum > 1 or source.required_fields else "read"
        nodes.append(EnterpriseDagNode(
            id=identifier, kind=mode, operation=mode, connector=source.connector,
            entity=source.entity, depends_on=parents, source_index=index,
        ))
        if template["reads"] == "map":
            parent = identifier
            identifier = f"fetch-{index}"
            nodes.append(EnterpriseDagNode(
                id=identifier, kind="read", operation="read", connector=source.connector,
                entity=source.entity, depends_on=(parent,),
                for_each=ResultIteration(node=parent, limit=100),
                bindings={"id": ResultReference(node=parent, path=("id",), select="item")},
            ))
        read_ids.append(identifier)

    def transform(identifier: str, parents: tuple[str, ...], op: str, fields: tuple[str, ...] = ()) -> None:
        nodes.append(EnterpriseDagNode.model_validate({
            "id": identifier, "kind": "transform", "operation": op,
            "connector": "model", "entity": "resultset", "depends_on": parents,
            "transform": op, "arguments": {"fields": fields} if fields else {},
        }))

    transform("collect", tuple(read_ids), "collect")
    result = "collect"
    control = template["control"]
    if control == "diamond":
        for step in DIAMOND_JOIN:
            transform(*step)
        result = DIAMOND_JOIN[-1][0]
    elif control == "deep_chain":
        transform("identifiers", (result,), "project", ("id",))
        transform("deduplicated", ("identifiers",), "unique")
        result = "deduplicated"

    sections = tuple(query.generation.artifact.sections) if query.generation.artifact is not None else ()
    body_nodes, body = write_body(mutation, result, sections)
    nodes.extend(body_nodes)

    def write(identifier: str, condition: ResultCondition | None = None) -> None:
        nodes.extend(write_nodes(mutation, result, body, identifier, condition))

    if control == "conditional":
        reference = ResultReference(node=read_ids[0], select="count")
        write("write-primary", ResultCondition(reference=reference, operator="gte", value=2))
        write("write-fallback", ResultCondition(reference=reference, operator="lt", value=2))
    else:
        write("write")
        if control == "fan_out":
            write("write-copy")
        elif control == "write_chain":
            nodes.extend(marker_nodes(mutation, result, sections))
        elif control == "delete_chain":
            # The delete addresses the record the readback returned, never the
            # write's own receipt, so an agent must have read what it removes;
            # the final readback is expected to fail, and the compiler states
            # that failure so the grader can demand it.
            nodes.extend((
                EnterpriseDagNode(
                    id="delete", kind="write", operation="delete",
                    connector=mutation.connector, entity=mutation.entity,
                    depends_on=("verify-write",),
                    bindings={"id": ResultReference(node="verify-write", path=("id",))},
                ),
                EnterpriseDagNode(
                    id="verify-deleted", kind="verify", operation="read",
                    connector=mutation.connector, entity=mutation.entity,
                    depends_on=("delete",),
                    bindings={"id": ResultReference(node="delete", path=("id",))},
                ),
            ))
    dag = EnterpriseDag(nodes=tuple(nodes))
    dimensions = {**query.dimensions, "dag_grammar": GRAMMAR_VERSION, "dag_shape": shape}
    payload: dict[str, Any] = query.model_dump()
    payload.update(
        id=content_key("enterprise-query-dag", query.id, GRAMMAR_VERSION, shape),
        dimensions=dimensions,
        query=query.query + " " + str(template["instruction"]),
        expected_dag=tuple(node.model_dump(mode="json", exclude_none=True) for node in dag.nodes),
        generation=query.generation.model_copy(update={"source_requirements": requirements}).model_dump(),
    )
    return PlannedEnterpriseQuery.model_validate(payload)


__all__ = ["DIAMOND_JOIN", "MESSAGE_OPERATIONS", "VERIFIED_NOTE", "apply_dag_shape", "compatible_shapes", "marker_nodes",
           "message_body", "write_body", "write_nodes"]
