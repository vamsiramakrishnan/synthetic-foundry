"""Compile the public DAG grammar using the existing enterprise row bindings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .connector_definition import ConnectorDefinition, builtin_connector_definitions
from .connector_payload import shape_payload
from .enterprise_corpus import QueryFixture
from .enterprise_dag import (
    GRAMMAR_VERSION,
    EnterpriseDag,
    EnterpriseDagNode,
    dag_metrics,
)
from .enterprise_queries import PlannedEnterpriseQuery


def program_for(row: Mapping[str, Any]) -> EnterpriseDag:
    return EnterpriseDag(nodes=tuple(EnterpriseDagNode.model_validate({
        "id": node["id"], "kind": node["node_kind"], "connector": node["server"],
        "entity": node["entity"], "operation": node["op"],
        "depends_on": tuple(source for source, target in row["expected_dag"]["edges"] if target == node["id"]),
        "arguments": node.get("payload", {}), "bindings": node.get("bindings", {}),
        "condition": node.get("condition"), "for_each": node.get("for_each"),
        "transform": node.get("transform"),
    }) for node in row["expected_dag"]["nodes"]), max_calls=int(row.get("max_calls", 1000)), max_result_items=int(row.get("max_result_items", 10000)))


def normalized_result(payload: Mapping[str, Any], fid: str) -> dict[str, Any]:
    """A stable identity plus the actual projected native result, never hidden fields."""
    nested = payload.get("fields")
    summary = nested.get("summary") if isinstance(nested, Mapping) else None
    return {
        **payload, "id": fid,
        "title": payload.get("title") or payload.get("name") or payload.get("short_description")
        or payload.get("Name") or summary or fid,
        "payload": dict(payload),
    }


def compile_dag_row(
    query: PlannedEnterpriseQuery,
    fixture: QueryFixture,
    records: Iterable[Mapping[str, Any]],
    *,
    definitions: Mapping[str, ConnectorDefinition] | None = None,
) -> dict[str, Any]:
    from .enterprise_rows import RowError, _tool_name, compile_row, create_payload

    if fixture.query_id != query.id:
        raise RowError(query.id, f"fixture belongs to query {fixture.query_id!r}")
    unsupported_failures = sorted({override.kind for override in fixture.overrides} - {"permission_denied", "missing_stable_id", "version_conflict", "partial_write"})
    if unsupported_failures:
        raise RowError(query.id, f"enterprise-dag@1 has no grading policy for {unsupported_failures}")
    available = dict(definitions or builtin_connector_definitions())
    materialized = tuple(dict(record) for record in records)
    try:
        dag = EnterpriseDag(nodes=tuple(EnterpriseDagNode.model_validate(node) for node in query.expected_dag))
    except ValueError as error:
        raise RowError(query.id, str(error)) from error
    # The legacy compiler owns source fields, vocabulary and destination state.
    # Reuse that binding once; the grammar changes control/data flow around it.
    mutation = query.generation.mutation
    reads = tuple({"id": f"read-{index}", "kind": "read", "connector": source.connector,
                   "entity": source.entity, "depends_on": []}
                  for index, source in enumerate(query.generation.source_requirements))
    baseline = query.model_copy(update={
        "dimensions": {key: value for key, value in query.dimensions.items() if key != "dag_grammar"},
        "expected_dag": reads + (
            {"id": "write", "kind": mutation.operation, "connector": mutation.connector,
             "entity": mutation.entity, "depends_on": [node["id"] for node in reads]},
            {"id": "verify", "kind": "readback", "connector": mutation.connector,
             "entity": mutation.entity, "depends_on": ["write"]},
        ),
    })
    base = compile_row(baseline, fixture, materialized, definitions=available)
    for name, definition in base.get("connector_definitions", {}).items():
        available[name] = ConnectorDefinition.model_validate(definition)
    templates = {node["id"]: node for node in base["expected_dag"]["nodes"]}
    by_fid = {str(record["fid"]): record for record in materialized}
    by_external = {str(record.get("id", record["fid"])): str(record["fid"]) for record in materialized}
    nodes: list[dict[str, Any]] = []
    snapshots: dict[str, dict[str, Any]] = {}
    assertions: list[dict[str, Any]] = [{"type": "execution_contract"}]
    for spec in dag.nodes:
        node: dict[str, Any] = {
            "id": spec.id, "server": spec.connector, "entity": spec.entity,
            "node_kind": spec.kind, "op": spec.operation,
            "bindings": {key: ref.model_dump(mode="json") for key, ref in sorted(spec.bindings.items())},
            "payload": dict(spec.arguments),
        }
        if spec.condition:
            node["condition"] = spec.condition.model_dump(mode="json")
        if spec.for_each:
            node["for_each"] = spec.for_each.model_dump(mode="json")
        if spec.kind == "transform":
            node.update(tool=spec.transform, transform=spec.transform)
            nodes.append(node)
            continue
        definition = available.get(spec.connector)
        if definition is None:
            raise RowError(query.id, f"connector {spec.connector!r} has no definition")
        destination = spec.kind in {"write", "verify"}
        template_key = "write" if spec.kind == "write" else "verify" if spec.kind == "verify" else f"read-{spec.source_index}"
        template = templates.get(template_key, {})
        tool, concrete = _tool_name(
            definition, spec.entity, spec.operation, query.id,
            mutation.output_format if destination else None,
            preexisting_record=mutation.preexisting_record if spec.operation == "upsert" else None,
        )
        payload = {**template.get("payload", {}), **spec.arguments}
        if definition.tool(tool).op in {"create", "send", "post", "upload"}:
            fresh = create_payload(definition, concrete, query.id, spec.id)
            fields = {**template.get("payload", {}).get("fields", {}), **fresh.get("fields", {}), **spec.arguments.get("fields", {})}
            payload = {**payload, **fresh, **spec.arguments, "fields": fields}
        if "id" not in spec.bindings and template.get("fixture"):
            node["fixture"] = template["fixture"]
            payload.setdefault("id", template["fixture"])
        elif "id" in spec.bindings:
            payload.pop("id", None)
        if definition.tool(tool).op in {"create", "send", "post", "upload"}:
            node.pop("fixture", None)
            payload.pop("id", None)
        if spec.source_index is not None:
            try:
                requirement = query.generation.source_requirements[spec.source_index]
            except IndexError as error:
                raise RowError(query.id, f"{spec.id}: source_index is outside source requirements") from error
            if (requirement.connector, requirement.entity) != (spec.connector, spec.entity):
                raise RowError(query.id, f"{spec.id}: source_index names a different connector/entity")
            key = f"{requirement.connector}:{requirement.entity}"
            selected = [by_external.get(rid, rid) for rid in fixture.input_record_ids.get(key, ())]
            if len(selected) < requirement.minimum:
                raise RowError(query.id, f"{spec.id}: insufficient bound source records")
            if spec.kind == "search":
                # Intersect exact fixture identities with authored field filters.
                predicate = payload.get("predicate") or {}
                if "where" in predicate:
                    predicate = {**predicate, "where": [*predicate["where"], {"field": "id", "op": "in", "value": selected}]}
                else:
                    predicate = {**predicate, "id": ["in", selected]}
                payload.update(predicate=predicate, max_results=min(len(selected), 100))
                payload.pop("id", None)
                node["expected_reads"] = selected[:100]
            else:
                node["expected_reads"] = selected[:1]
            for fid in selected:
                if fid not in by_fid:
                    raise RowError(query.id, f"{spec.id}: missing bound fixture {fid!r}")
                record = by_fid[fid]
                if record.get("server") != spec.connector or not (record.get("entity") == spec.entity or definition.entity_matches(spec.entity, str(record.get("entity")))):
                    raise RowError(query.id, f"{spec.id}: fixture {fid!r} belongs to a different connector/entity")
                snapshots.setdefault(spec.id, {})[fid] = normalized_result(
                    shape_payload(definition, by_fid[fid], payload.get("fields")), fid
                )
            for assertion in base.get("assertions", ()):
                if assertion.get("node") == template_key and assertion["type"] == "fields_used":
                    assertions.append({**assertion, "node": spec.id})
        # A mapped fetch consumes only its search results, not the whole fixture pool.
        if spec.for_each:
            bound_ids = sorted({by_external.get(rid, rid)
                                for key, rids in fixture.input_record_ids.items()
                                if key.split(":", 1)[0] == spec.connector for rid in rids})
            snapshots[spec.id] = {
                fid: normalized_result(shape_payload(definition, by_fid[fid], payload.get("fields")), fid)
                for fid in bound_ids if fid in by_fid
            }
        admitted = set(definition.tool(tool).params)
        explicit = set(spec.arguments) | {key.split(".", 1)[0] for key in spec.bindings}
        if explicit - admitted:
            raise RowError(query.id, f"{spec.id}: tool {tool!r} does not accept arguments {sorted(explicit - admitted)}")
        # A later update can reuse the destination binding, but it cannot carry
        # the create tool's name/parent parameters through a real MCP schema.
        payload = {key: value for key, value in payload.items() if key in admitted}
        node.update(tool=tool, entity=concrete, op=definition.tool(tool).op, payload=payload)
        nodes.append(node)
    assertions.extend(_delete_assertions(query.id, dag, nodes))
    row = {
        **base, "grammar": GRAMMAR_VERSION, "shape": query.dimensions.get("dag_shape", "authored"),
        "expected_dag": {"nodes": nodes, "edges": [[parent, node.id] for node in dag.nodes for parent in node.depends_on]},
        "assertions": assertions, "input_snapshots": snapshots,
        "max_calls": dag.max_calls, "max_result_items": dag.max_result_items, "metrics": dag_metrics(dag),
        "state_overrides": [override.model_dump(mode="json") for override in fixture.overrides],
    }
    try:
        bound_program = program_for(row)
        # Available fixture snapshots make unknown source-result paths a compile
        # refusal, before an earlier write could run.
        from .enterprise_dag import resolve_reference
        known_outputs = {identifier: list(values.values()) for identifier, values in snapshots.items()}
        for planned_node in bound_program.nodes:
            refs = list(planned_node.bindings.values())
            if planned_node.condition:
                refs.append(planned_node.condition.reference)
            for reference in refs:
                if reference.node in known_outputs and reference.select != "count":
                    examples = known_outputs[reference.node]
                    resolve_reference(reference, known_outputs, item=examples[0] if examples else None)
    except ValueError as error:
        raise RowError(query.id, str(error)) from error
    from .enterprise_failures import compile_failure_contract
    return compile_failure_contract(row)


def _binding_origin(spec: EnterpriseDagNode, by_id: Mapping[str, EnterpriseDagNode]) -> str:
    """The node whose record an ``id`` binding chain ultimately addresses."""
    seen = {spec.id}
    current = spec
    while "id" in current.bindings and current.bindings["id"].node in by_id:
        current = by_id[current.bindings["id"].node]
        if current.id in seen:
            break
        seen.add(current.id)
    return current.id


def _delete_assertions(query_id: str, dag: EnterpriseDag, nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A planned delete is graded on what is gone, and its readback on failing.

    The delete's target is found by following its ``id`` binding back to the
    node that produced the record: a fixture the plan read, or a write the
    plan made. ``deleted`` then names one or the other, and any verify bound
    to the delete's result is expected to meet ``not_found``, stated as a
    ``failure_at`` so the execution contract can demand the error rather
    than excuse it.
    """
    by_id = {spec.id: spec for spec in dag.nodes}
    wire = {str(node["id"]): node for node in nodes}
    out: list[dict[str, Any]] = []
    for spec in dag.nodes:
        if spec.kind == "write" and spec.operation == "delete":
            origin = _binding_origin(spec, by_id)
            assertion: dict[str, Any] = {"type": "deleted", "node": spec.id}
            if wire.get(origin, {}).get("fixture"):
                assertion["fixture"] = wire[origin]["fixture"]
            elif origin != spec.id and by_id[origin].kind == "write":
                assertion["created_by"] = origin
            else:
                from .enterprise_rows import RowError
                raise RowError(query_id, f"{spec.id}: delete addresses neither a fixture nor a record the plan creates")
            out.append(assertion)
        elif spec.kind == "verify" and "id" in spec.bindings and by_id.get(spec.bindings["id"].node, spec).operation == "delete":
            out.append({"type": "failure_at", "node": spec.id, "kind": "not_found", "writes_persist": False, "blocked_nodes": []})
    return out


__all__ = ["compile_dag_row"]
