"""Check grammar semantics from observable connector spans, not executor claims."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .enterprise_dag import condition_matches, transform_results
from .enterprise_dag_rows import normalized_result, program_for
from .enterprise_dag_runtime import bound_arguments


def grade_execution_contract(
    spans: Sequence[Mapping[str, Any]], row: Mapping[str, Any],
    post_state: Mapping[str, Mapping[str, Any]] | None,
) -> list[str]:
    """Verify control flow, exact argument bindings, iteration identities and effects.

    Search/get results are reconstructed from the row's bound source snapshots
    and the trace's returned record ids. A fabricated branch flag cannot select
    a branch. Missing source records fail before they can change the branch.
    """
    fails: list[str] = []
    try:
        program = program_for(row)
    except (KeyError, TypeError, ValueError) as error:
        return [f"invalid_execution_contract:{error}"]
    wire = {node["id"]: node for node in row["expected_dag"]["nodes"]}
    by_node: dict[str, list[Mapping[str, Any]]] = {}
    positions = {str(span["id"]): index for index, span in enumerate(spans)}
    if len(positions) != len(spans):
        fails.append("duplicate_span_id")
    for span in spans:
        identifier = str(span.get("node"))
        if identifier not in wire:
            fails.append(f"unknown_node:{identifier}")
        by_node.setdefault(identifier, []).append(span)
    if len(spans) > program.max_calls:
        fails.append(f"execution_budget_exceeded:{program.max_calls}")
    failures_by_node = {str(assertion["node"]): assertion for assertion in row.get("assertions", ()) if assertion.get("type") == "failure_at"}
    matched_failures = {
        node_id for node_id, assertion in failures_by_node.items()
        if any(span.get("error", {}).get("kind") == assertion["kind"] for span in by_node.get(node_id, ()) if span.get("error"))
    }
    blocked = {str(node_id) for failed in matched_failures for node_id in failures_by_node[failed].get("blocked_nodes", ())}
    outputs: dict[str, list[Any]] = {}
    producers: dict[str, list[str]] = {}
    final_fields: dict[str, dict[str, Any]] = {}
    # Records a planned delete removed in this run: absent from the post-state
    # by design, so their entity is not read from it.
    removed = {
        str(fid) for node in program.nodes if node.operation == "delete"
        for span in by_node.get(node.id, ()) if not span.get("error") for fid in span.get("writes", ())
    }
    for node in program.nodes:
        outputs[node.id] = []
        producers[node.id] = []
        observed = by_node.get(node.id, [])
        if node.id in blocked:
            if observed:
                fails.append(f"executed_after_failure:{node.id}")
            continue
        try:
            selected = node.condition is None or condition_matches(node.condition, outputs)
        except ValueError as error:
            fails.append(f"invalid_condition:{node.id}:{error}")
            continue
        if not selected:
            if observed:
                fails.append(f"branch_not_selected:{node.id}")
            continue
        parent_spans = {identifier for parent in node.depends_on for identifier in producers[parent]}
        if node.kind == "transform":
            if observed:
                fails.append(f"unexpected_transform_call:{node.id}")
            try:
                outputs[node.id] = transform_results(node, outputs, max_items=program.max_result_items)
            except ValueError as error:
                fails.append(f"transform_failed:{node.id}:{error}")
            producers[node.id] = sorted(parent_spans)
            continue
        producers[node.id] = [str(span["id"]) for span in observed]
        iterations = outputs[node.for_each.node][:node.for_each.limit] if node.for_each else [None]
        expected_count = len(iterations)
        search = node.operation == "search"
        if (not search and len(observed) != expected_count) or (search and not observed):
            fails.append(f"per_item_count:{node.id}:{len(observed)}!={expected_count}")
        for index, span in enumerate(observed):
            if span.get("tool") != f"{node.connector}.{wire[node.id]['tool']}":
                fails.append(f"wrong_tool:{node.id}")
            if span.get("error"):
                expected_failure = failures_by_node.get(node.id)
                if expected_failure is None or span["error"].get("kind") != expected_failure["kind"]:
                    fails.append(f"node_failed:{node.id}")
                    continue
                if not expected_failure.get("writes_persist"):
                    continue
            consumed = {str(value) for value in span.get("consumed_from", ())}
            if not parent_spans <= consumed:
                fails.append(f"dataflow_missing:{node.id}")
            if any(positions[parent] >= positions[str(span["id"])] for parent in parent_spans):
                fails.append(f"order_violated:{node.id}")
            try:
                args = bound_arguments(node, outputs, iterations[index] if node.for_each and index < len(iterations) else None)
            except (ValueError, IndexError) as error:
                fails.append(f"invalid_binding:{node.id}:{error}")
                continue
            actual = span.get("args", {})
            for key, value in args.items():
                if key in {"id", "start_at", "max_results"}:
                    continue
                if actual.get(key) != value:
                    fails.append(f"argument_mismatch:{node.id}:{key}")
            identities = tuple(str(value) for value in (span.get("writes") or span.get("reads") or ()))
            if args.get("id") is not None:
                target = str(args["id"])
                aliases = {target}
                record = (post_state or {}).get(target, {})
                aliases.update(str(record[key]) for key in ("ident", "external_id", "key", "number", "name", "title") if record.get(key) is not None)
                for snapshots_by_fid in row.get("input_snapshots", {}).values():
                    snapshot = snapshots_by_fid.get(target, {}).get("payload", {})
                    aliases.update(str(snapshot[key]) for key in ("id", "Id", "sys_id", "key", "number", "name", "title") if snapshot.get(key) is not None)
                # A record the run created and then deleted is in no snapshot
                # and no post-state; the native identifiers it answered to are
                # in the results the trace recorded for it.
                for produced in outputs.values():
                    for entry in produced:
                        if isinstance(entry, Mapping) and str(entry.get("id")) == target and isinstance(entry.get("payload"), Mapping):
                            native = entry["payload"]
                            aliases.update(str(native[key]) for key in ("id", "Id", "sys_id", "key", "number", "name", "title") if native.get(key) is not None)
                if str(actual.get("id")) not in aliases:
                    fails.append(f"argument_mismatch:{node.id}:id")
            if node.operation in {"create", "send", "post", "upload"}:
                if actual.get("entity") != node.entity:
                    fails.append(f"entity_mismatch:{node.id}")
                if any(fid not in removed and (post_state or {}).get(fid, {}).get("entity") != node.entity for fid in identities):
                    fails.append(f"entity_mismatch:{node.id}")
            target_ids = tuple(str(value) for value in span.get("reads", ())) if node.operation in {"reply", "forward"} else identities
            if args.get("id") is not None and node.operation not in {"create", "send", "post", "upload", "search"}:
                if str(args["id"]) not in target_ids:
                    fails.append(f"target_mismatch:{node.id}")
            if node.kind == "write":
                if not span.get("writes"):
                    fails.append(f"state_not_written:{node.id}")
                if wire[node.id].get("fixture") and wire[node.id]["fixture"] not in target_ids:
                    fails.append(f"target_mismatch:{node.id}")
                for fid in span.get("writes", ()):
                    if node.operation == "delete":
                        # Nothing written earlier can be checked on a record
                        # the plan then removes; its absence is the check.
                        final_fields.pop(str(fid), None)
                        continue
                    fields = final_fields.setdefault(str(fid), {})
                    fields.update(args.get("fields", {}))
                    if node.operation in {"reply", "forward"}:
                        fields["body"] = args.get("body", "")
                        fields["reply_to" if node.operation == "reply" else "forwarded_from"] = args.get("id")
            snapshots = row.get("input_snapshots", {}).get(node.id, {})
            receipt = span.get("result")
            returned = receipt.get("items", ()) if search and isinstance(receipt, Mapping) else [receipt]
            if receipt is not None and len(returned) != len(identities):
                fails.append(f"result_cardinality:{node.id}")
            for result_index, fid in enumerate(identities):
                response = returned[result_index] if result_index < len(returned) else None
                if isinstance(response, Mapping):
                    normalized = normalized_result(response, fid)
                    if fid in snapshots and normalized != snapshots[fid]:
                        fails.append(f"result_mismatch:{node.id}:{fid}")
                    elif node.kind not in {"write", "verify"} and fid not in snapshots:
                        fails.append(f"unexpected_read:{node.id}:{fid}")
                    outputs[node.id].append(normalized)
                elif fid in snapshots:
                    outputs[node.id].append(snapshots[fid])
                elif node.kind in {"write", "verify"}:
                    held_record = (post_state or {}).get(fid)
                    if held_record is None:
                        fails.append(f"state_missing:{node.id}:{fid}")
                    else:
                        outputs[node.id].append(normalized_result({"name": held_record.get("name") or held_record.get("title")}, fid))
                else:
                    fails.append(f"unexpected_read:{node.id}:{fid}")
        if node.id in matched_failures:
            continue
        expected_reads = wire[node.id].get("expected_reads")
        if expected_reads is not None:
            observed_reads = [str(value) for span in observed for value in span.get("reads", ())]
            if sorted(observed_reads) != sorted(expected_reads):
                fails.append(f"reads_mismatch:{node.id}")
        if node.for_each:
            expected_ids = [str(item["id"]) for item in iterations if isinstance(item, Mapping)]
            observed_ids = [str(value) for span in observed for value in span.get("reads", ())]
            if node.kind in {"read", "verify"} and sorted(expected_ids) != sorted(observed_ids):
                fails.append(f"per_item_targets:{node.id}")
    if final_fields and post_state is None:
        fails.append("post_state_required")
    for fid, fields in sorted(final_fields.items()):
        record = (post_state or {}).get(fid, {})
        for key, value in sorted(fields.items()):
            if record.get(key) != value:
                fails.append(f"field_mismatch:{fid}:{key}")
    return list(dict.fromkeys(fails))


__all__ = ["grade_execution_contract"]
