"""Bind versioned trajectory templates to a query's authored source roles."""

from __future__ import annotations

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
from .enterprise_queries import PlannedEnterpriseQuery
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


def compatible_shapes(row: dict[str, str], requested: tuple[str, ...]) -> tuple[str, ...]:
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
        if name == "write_chain" and not _admits_update(row["destination"], row["destination_entity"], row["output_format"]):
            continue
        if name == "delete_chain" and not _admits_delete(row["destination"], row["destination_entity"], row["output_format"]):
            continue
        compatible.append(name)
    return tuple(compatible)


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
        transform("identifiers", (result,), "project", ("id",))
        transform("titles", (result,), "project", ("title",))
        transform("joined", ("identifiers", "titles"), "collect")
        result = "joined"
    elif control == "deep_chain":
        transform("identifiers", (result,), "project", ("id",))
        transform("deduplicated", ("identifiers",), "unique")
        result = "deduplicated"

    def write(identifier: str, condition: ResultCondition | None = None) -> None:
        # What the write carries from the reads. A message carries the result
        # as its body; a record write carries it as evidence fields; a delete
        # or move carries nothing, because its tool takes only the record id
        # (and a parent), and an argument the tool does not accept is a row
        # the compiler refuses.
        if mutation.operation in {"reply", "forward", "comment"}:
            bindings = {"body": ResultReference(node=result, select="all", encoding="json")}
        elif mutation.operation in {"delete", "move"}:
            bindings = {}
        else:
            bindings = {"fields.evidence": ResultReference(node=result, select="all"),
                        "fields.evidence_count": ResultReference(node=result, select="count")}
        parents = (result,)
        if mutation.operation in {"delete", "move"}:
            # A destructive write addresses a record the run has read: the
            # trajectory law `destructive_without_read` demands it of every
            # agent, so the reference reads the target first and the write
            # takes its id from that read, never from a source record.
            nodes.append(EnterpriseDagNode(
                id=f"target-{identifier}", kind="verify", operation="read",
                connector=mutation.connector, entity=mutation.entity,
                depends_on=(result,), condition=condition,
            ))
            parents = (f"target-{identifier}",)
            bindings = {"id": ResultReference(node=f"target-{identifier}", path=("id",))}
        nodes.append(EnterpriseDagNode(
            id=identifier, kind="write", operation=mutation.operation,
            connector=mutation.connector, entity=mutation.entity,
            depends_on=parents, condition=condition,
            bindings=bindings,
        ))
        nodes.append(EnterpriseDagNode(
            id=f"verify-{identifier}", kind="verify", operation="read",
            connector=mutation.connector, entity=mutation.entity,
            depends_on=(identifier,), condition=condition,
            bindings={"id": ResultReference(node=identifier, path=("id",))},
        ))

    if control == "conditional":
        reference = ResultReference(node=read_ids[0], select="count")
        write("write-primary", ResultCondition(reference=reference, operator="gte", value=2))
        write("write-fallback", ResultCondition(reference=reference, operator="lt", value=2))
    else:
        write("write")
        if control == "fan_out":
            write("write-copy")
        elif control == "write_chain":
            nodes.extend((
                EnterpriseDagNode(
                    id="write-marker", kind="write", operation="update",
                    connector=mutation.connector, entity=mutation.entity,
                    depends_on=("verify-write",), arguments={"fields": {"verified": True}},
                    bindings={"id": ResultReference(node="verify-write", path=("id",))},
                ),
                EnterpriseDagNode(
                    id="verify-marker", kind="verify", operation="read",
                    connector=mutation.connector, entity=mutation.entity,
                    depends_on=("write-marker",),
                    bindings={"id": ResultReference(node="write-marker", path=("id",))},
                ),
            ))
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


__all__ = ["apply_dag_shape", "compatible_shapes"]
