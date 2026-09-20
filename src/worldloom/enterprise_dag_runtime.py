"""Interpret bounded DAG control flow over the shared connector emulator.

Only scheduling and value binding live here. Product operations, native query
semantics, paging, state changes and failures remain in ConnectorEmulator.
Local transforms are pure functions; they need no pretend connector tool span.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from .connector_definition import ConnectorDefinition, builtin_connector_definitions
from .connector_emulator import ConnectorError, ConnectorSpan
from .connector_results import record_connector_result
from .enterprise_dag import condition_matches, resolve_reference, transform_results
from .enterprise_dag_rows import normalized_result, program_for


def bound_arguments(node: Any, outputs: Mapping[str, list[Any]], item: Any = None) -> dict[str, Any]:
    arguments = copy.deepcopy(node.arguments)
    for key, reference in sorted(node.bindings.items()):
        value = resolve_reference(reference, outputs, item=item)
        parts = key.split(".")
        target = arguments
        for part in parts[:-1]:
            held = target.setdefault(part, {})
            if not isinstance(held, dict):
                raise ValueError(f"{node.id}: binding traverses scalar argument {key!r}")
            target = held
        target[parts[-1]] = value
    return arguments


def run_grammar_row(
    row: Mapping[str, Any], records: Iterable[Any], *,
    acl: Mapping[str, Mapping[str, Any]] | None = None,
    definitions: Mapping[str, ConnectorDefinition] | None = None,
    shape: Any = None,
) -> Any:
    from .connector_eval_runtime import EvalRuntimeResult, _record_dict
    from .connector_trace import grade_trace
    from .enterprise_failures import build_query_emulator

    program = program_for(row)
    nodes = {node["id"]: node for node in row["expected_dag"]["nodes"]}
    available = dict(builtin_connector_definitions())
    available.update({key: ConnectorDefinition.model_validate(value) for key, value in row.get("connector_definitions", {}).items()})
    available.update(definitions or {})
    servers = {node.connector for node in program.nodes if node.kind != "transform"}
    if servers - available.keys():
        raise ValueError(f"eval row references connectors with no definition: {sorted(servers - available.keys())}")
    for node in program.nodes:
        if node.kind == "transform":
            continue
        definition = available[node.connector]
        tool = definition.tool(str(nodes[node.id]["tool"]))
        if tool.op != node.operation:
            raise ValueError(f"{node.id}: tool operation disagrees with compiled grammar")
        if not set(definition.entity_members(node.entity)) & set(tool.entities):
            raise ValueError(f"{node.id}: tool does not admit entity {node.entity!r}")
    materialized = tuple(_record_dict(record) for record in records)
    emulators = {
        server: build_query_emulator(available[server], materialized, acl=acl,
                                     overrides=row.get("state_overrides", ()), mutation_nodes=nodes.values(),
                                     query_id=str(row.get("id", "")))
        for server in sorted(servers)
    }
    outputs: dict[str, list[Any]] = {}
    span_ids: dict[str, list[str]] = {}
    failed: set[str] = set()
    spans: list[ConnectorSpan] = []
    behaviors: list[str] = []
    calls = 0
    for node in program.nodes:
        outputs[node.id] = []
        span_ids[node.id] = []
        if any(parent in failed for parent in node.depends_on):
            failed.add(node.id)
            behaviors.append(f"blocked_dependency:{node.id}")
            continue
        if node.condition is not None:
            matches = condition_matches(node.condition, outputs)
            behaviors.append(f"condition:{node.id}:{str(matches).lower()}")
            if not matches:
                continue
        if node.kind == "transform":
            outputs[node.id] = transform_results(node, outputs, max_items=program.max_result_items)
            span_ids[node.id] = [identifier for parent in node.depends_on for identifier in span_ids[parent]]
            continue
        emulator = emulators[node.connector]
        wire = nodes[node.id]
        tool_name = str(wire["tool"])
        tool = emulator.definition.tool(tool_name)
        if tool.op != node.operation:
            raise ValueError(f"{node.id}: tool operation disagrees with compiled grammar")
        consumed = tuple(dict.fromkeys(identifier for parent in node.depends_on for identifier in span_ids[parent]))
        iterations = outputs[node.for_each.node][:node.for_each.limit] if node.for_each else [None]
        for item in iterations:
            arguments = bound_arguments(node, outputs, item)
            if tool.op == "search":
                requested = int(arguments.get("max_results", 100))
                if not 1 <= requested <= min(tool.max_results, 1000):
                    raise ValueError(f"{node.id}: search requires max_results in [1, {min(tool.max_results, 1000)}]")
                start = int(arguments.get("start_at", 0))
            else:
                requested, start = 1, 0
            emitted = 0
            while emitted < requested:
                if calls >= program.max_calls:
                    raise ValueError(f"execution_budget_exceeded:{program.max_calls}")
                calls += 1
                kwargs = {**arguments, "_node": node.id, "_consumed": consumed}
                if tool.op == "search":
                    kwargs.update(entity=node.entity, start_at=start, max_results=min(tool.page_size, requested - emitted))
                elif tool.op in {"create", "send", "post", "upload"}:
                    kwargs["entity"] = node.entity
                try:
                    result = emulator.call(tool_name, **kwargs)
                except ConnectorError as error:
                    failed.add(node.id)
                    behaviors.append(f"connector_error:{node.id}:{error.kind}")
                    local = emulator.trace[-1]
                    global_id = f"s{len(spans) + 1}"
                    spans.append(replace(local, id=global_id))
                    span_ids[node.id].append(global_id)
                    break
                local = emulator.trace[-1]
                global_id = f"s{len(spans) + 1}"
                spans.append(record_connector_result(replace(local, id=global_id), result))
                span_ids[node.id].append(global_id)
                fids = local.writes or local.reads
                if tool.op == "search":
                    items = result.get("items", ())
                    if len(items) != len(fids):
                        raise ValueError(f"{node.id}: connector result/identity cardinality mismatch")
                    outputs[node.id].extend(normalized_result(value, fid) for value, fid in zip(items, fids, strict=True))
                    emitted += len(items)
                    if result.get("is_last") or not items:
                        break
                    start += int(result.get("max_results") or len(items))
                else:
                    if isinstance(result, Mapping) and fids:
                        outputs[node.id].append(normalized_result(result, fids[-1]))
                    break
            if node.id in failed:
                break
    post_state: dict[str, Mapping[str, Any]] = {}
    for emulator in emulators.values():
        post_state.update(emulator.records)
    return EvalRuntimeResult(
        grade=grade_trace(spans, row, post_state=post_state, behaviors=behaviors, shape=shape),
        spans=tuple(spans), behaviors=tuple(behaviors), post_state=post_state,
    )


__all__ = ["run_grammar_row", "observed_outputs", "observed_flow", "bound_arguments"]


def observed_flow(row: Mapping[str, Any], spans: Iterable[Any]) -> tuple[dict[str, list[Any]], dict[str, list[str]]]:
    """Reconstruct delivered values for external call attribution.

    Only recorded native responses become connector outputs. Missing nodes stay
    absent, so a not-yet-run search cannot be mistaken for an empty resultset.
    This does not declare a partial trace valid; grade_trace owns that decision.
    """
    from dataclasses import asdict

    program = program_for(row)
    observed: dict[str, list[Mapping[str, Any]]] = {}
    for raw in spans:
        held = dict(raw) if isinstance(raw, Mapping) else asdict(raw)
        observed.setdefault(str(held.get("node")), []).append(held)
    outputs: dict[str, list[Any]] = {}
    producers: dict[str, list[str]] = {}
    failed: set[str] = set()
    for node in program.nodes:
        if any(parent in failed for parent in node.depends_on):
            failed.add(node.id)
            continue
        if node.condition and node.condition.reference.node in outputs and not condition_matches(node.condition, outputs):
            outputs[node.id], producers[node.id] = [], []
            continue
        if node.for_each and node.for_each.node in outputs and not outputs[node.for_each.node]:
            outputs[node.id], producers[node.id] = [], []
            continue
        if node.kind == "transform":
            if all(parent in outputs for parent in node.depends_on):
                outputs[node.id] = transform_results(node, outputs, max_items=program.max_result_items)
                producers[node.id] = list(dict.fromkeys(identifier for parent in node.depends_on for identifier in producers[parent]))
            continue
        delivered = observed.get(node.id)
        if not delivered:
            continue
        values: list[Any] = []
        for span in delivered:
            if span.get("error"):
                failed.add(node.id)
                continue
            result = span.get("result")
            identities = span.get("writes") or span.get("reads") or ()
            # A page of items is a page whichever node it was attributed to:
            # an agent may read a `get` node's record through a search, and
            # the receipt then carries one item per record it read.
            page = result.get("items") if isinstance(result, Mapping) else None
            paged = isinstance(page, list) and (node.operation == "search" or len(page) == len(identities))
            items = page if isinstance(page, list) and paged else [result]
            if len(items) != len(identities) or any(not isinstance(item, Mapping) for item in items):
                raise ValueError(f"missing_result_receipt:{node.id}")
            values.extend(normalized_result(value, str(fid)) for value, fid in zip(items, identities, strict=True))
        outputs[node.id] = values
        producers[node.id] = [str(span["id"]) for span in delivered]
    return outputs, producers


def observed_outputs(row: Mapping[str, Any], spans: Iterable[Any]) -> dict[str, list[Any]]:
    """Delivered node results; use observed_flow when lineage is also needed."""
    return observed_flow(row, spans)[0]
