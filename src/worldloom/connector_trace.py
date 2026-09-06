"""Trace-as-graph grading for definition-driven connector evals.

The grader consumes tool spans, not prose answers. Expected DAG assertions come
from the eval row; payload-efficiency assertions are also derivable directly
from EvalSpec.shape, so large-record evaluation cannot drift from the shape that
built the candidate world.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

from .connector_emulator import ConnectorSpan
from .eval_design import EvalShape

_READ_OPS = frozenset({"read", "extract", "search", "get"})


def _span_dict(span: ConnectorSpan | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(span, Mapping):
        return dict(span)
    if is_dataclass(span):
        return asdict(span)
    raise TypeError(f"unsupported connector span {type(span)!r}")


def _values(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _values(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _values(item)
    else:
        yield value


def executed_dag(
    spans: Iterable[ConnectorSpan | Mapping[str, Any]],
) -> dict[str, Any]:
    """Infer data-flow edges from explicit consumption and record references."""

    materialized = [_span_dict(span) for span in spans]
    producers: dict[str, str] = {}
    for span in materialized:
        for record_id in (*span.get("reads", ()), *span.get("writes", ())):
            producers.setdefault(str(record_id), str(span["id"]))
    edges: set[tuple[str, str]] = set()
    for span in materialized:
        span_id = str(span["id"])
        for parent in span.get("consumed_from", ()):
            edges.add((str(parent), span_id))
        for value in _values(span.get("args", {})):
            if isinstance(value, str) and value in producers and producers[value] != span_id:
                edges.add((producers[value], span_id))
    return {
        "nodes": [
            {"id": span["id"], "tool": span["tool"], "error": span.get("error")}
            for span in materialized
        ],
        "edges": [list(edge) for edge in sorted(edges)],
    }


def shape_assertions(shape: EvalShape) -> tuple[dict[str, Any], ...]:
    """Compile efficiency assertions from the same shape that builds the eval."""

    assertions: list[dict[str, Any]] = []
    for record_requirement in shape.records:
        if record_requirement.projection_required:
            assertions.append(
                {
                    "type": "projection_used",
                    "connector": record_requirement.connector,
                    "entity": record_requirement.entity,
                    "max_bytes": record_requirement.maximum_read_bytes,
                }
            )
    for thread_requirement in shape.threads:
        if thread_requirement.pagination_required:
            assertions.append(
                {
                    "type": "pagination_used",
                    "connector": thread_requirement.connector,
                    "entity": thread_requirement.entity,
                }
            )
    return tuple(assertions)


def _spans_by_node(spans: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        node = span.get("node")
        if node:
            grouped.setdefault(str(node), []).append(span)
    return grouped


def _assert_projection(
    assertion: Mapping[str, Any],
    spans: list[dict[str, Any]],
    by_node: Mapping[str, list[dict[str, Any]]],
    fails: list[str],
) -> None:
    target = by_node.get(str(assertion.get("node")), []) if assertion.get("node") else spans
    connector = assertion.get("connector")
    if connector:
        target = [span for span in target if str(span.get("tool", "")).startswith(f"{connector}.")]
    entity = assertion.get("entity")
    if entity:
        target = [
            span
            for span in target
            if span.get("args", {}).get("entity") in (None, entity)
        ]
    read_like = [span for span in target if not span.get("writes")]
    if not read_like:
        return
    max_bytes = int(assertion.get("max_bytes") or (1 << 60))
    if not all(span.get("args", {}).get("fields") or int(span.get("bytes", 0)) <= max_bytes for span in read_like):
        suffix = f":{assertion['node']}" if assertion.get("node") else ""
        fails.append(f"no_projection{suffix}")


def _assert_pagination(
    assertion: Mapping[str, Any],
    spans: list[dict[str, Any]],
    fails: list[str],
) -> None:
    connector = assertion.get("connector")
    target = [
        span
        for span in spans
        if (not connector or str(span.get("tool", "")).startswith(f"{connector}."))
        and not span.get("writes")
    ]
    if not target:
        return
    used = len(target) > 1 and any(
        int(span.get("args", {}).get("start_at", 0) or 0) > 0 for span in target
    )
    if not used:
        fails.append(f"no_pagination:{connector or 'connector'}")


def grade_trace(
    spans: Iterable[ConnectorSpan | Mapping[str, Any]],
    row: Mapping[str, Any],
    *,
    post_state: Mapping[str, Mapping[str, Any]] | None = None,
    behaviors: Iterable[str] = (),
    shape: EvalShape | None = None,
) -> dict[str, Any]:
    """Grade one execution trace against a row's DAG and behavior assertions."""

    materialized = [_span_dict(span) for span in spans]
    behavior_set = set(behaviors)
    expected = row.get("expected_dag", {})
    nodes = list(expected.get("nodes", ()))
    edges = list(expected.get("edges", ()))
    nodes_by_id = {str(node["id"]): node for node in nodes}
    tool_of = {
        str(node["id"]): f"{node['server']}.{node['tool']}"
        for node in nodes
        if node.get("server") and node.get("tool")
    }
    by_node = _spans_by_node(materialized)
    order_pos = {str(span["id"]): index for index, span in enumerate(materialized)}
    errors = {
        str(span["id"]): span["error"]
        for span in materialized
        if span.get("error")
    }
    fails: list[str] = []
    adversarial = (row.get("adversarial") or {}).get("type")
    ground_truth = row.get("ground_truth", {})
    assertions = list(row.get("assertions", ()))
    if shape is not None:
        assertions.extend(shape_assertions(shape))

    branch = next(
        (assertion for assertion in assertions if assertion.get("type") == "branch_exclusive"),
        None,
    )
    groups = branch.get("groups") if branch else None
    skipped: set[str] = set()
    if groups and adversarial != "idempotency":
        condition = next(iter(ground_truth.get("conditions", {}).values()), None)
        selected = (
            groups[condition["branch"]]
            if condition
            and condition.get("value") is not None
            and condition["branch"] < len(groups)
            else groups[0]
        )
        for group in groups:
            if group is not selected:
                skipped.update(str(value) for value in group)

    stopped = {
        node_id
        for node_id in nodes_by_id
        if "clarify" in behavior_set
        or ("report_not_found" in behavior_set and adversarial == "missing_entity")
    }

    for assertion in assertions:
        kind = assertion.get("type")
        if kind == "tool_called":
            node_id = str(assertion["node"])
            node = nodes_by_id[node_id]
            if node_id in skipped or "gated" in node.get("flags", ()) or node.get("optional"):
                continue
            node_spans = by_node.get(node_id, ())
            if not node_spans and node_id in stopped:
                continue
            if node.get("op") == "create" and "updated_existing" in behavior_set and node_spans:
                continue
            if not any(span["tool"] == tool_of.get(node_id) for span in node_spans):
                fails.append(f"tool_not_called:{node_id}")
        elif kind == "order":
            before = by_node.get(str(assertion["before"]), ())
            after = by_node.get(str(assertion["after"]), ())
            if before and after and min(order_pos[str(span["id"])] for span in before) > min(
                order_pos[str(span["id"])] for span in after
            ):
                fails.append(f"order_violated:{assertion['before']}>{assertion['after']}")
        elif kind == "artifact_created":
            node_id = str(assertion["node"])
            if node_id in skipped or node_id in stopped:
                continue
            successful_spans = [
                span for span in by_node.get(node_id, ()) if not span.get("error")
            ]
            if not successful_spans and "updated_existing" not in behavior_set:
                fails.append(f"artifact_missing:{node_id}")
        elif kind == "per_item":
            node_id = str(assertion["node"])
            if node_id in skipped or node_id in stopped:
                continue
            expected_count = ground_truth.get("for_each", {}).get(node_id, {}).get("count")
            actual_count = len(by_node.get(node_id, ()))
            if expected_count is not None and actual_count != expected_count:
                fails.append(f"per_item_count:{node_id}:{actual_count}!={expected_count}")
        elif kind == "branch_exclusive" and groups and adversarial != "idempotency":
            ran = [group for group in groups if any(by_node.get(str(node)) for node in group)]
            if len(ran) != 1:
                fails.append("branch_not_exclusive")
        elif kind == "state_equals" and post_state is not None:
            node_id = str(assertion["node"])
            if node_id in skipped or node_id in stopped:
                continue
            targets = [
                write
                for span in by_node.get(node_id, ())
                for write in span.get("writes", ())
            ]
            expected_state = str(assertion["state"]).casefold()
            for target in targets:
                record = post_state.get(str(target))
                if record is None:
                    continue
                states = {
                    str(record.get("state", "")).casefold(),
                    str(record.get("status", "")).casefold(),
                    str(record.get("state_label", "")).casefold(),
                }
                if expected_state not in states:
                    fails.append(f"state_mismatch:{node_id}")
                    break
        elif kind == "deleted" and post_state is not None:
            node_id = str(assertion["node"])
            if node_id not in skipped and node_id not in stopped and not assertion.get("per_item"):
                if str(assertion["fixture"]) in post_state:
                    fails.append(f"not_deleted:{node_id}")
        elif kind == "denial_surfaced":
            if not any(error.get("code") == 403 for error in errors.values()) and "denial_surfaced" not in behavior_set:
                fails.append("no_denial")
        elif kind == "report_not_found":
            if not any(error.get("code") == 404 for error in errors.values()) and "report_not_found" not in behavior_set:
                fails.append("not_found_not_reported")
        elif kind == "clarify_before_write":
            if adversarial in {"ambiguity", "wrong_system"} and "clarify" not in behavior_set:
                fails.append("no_clarify")
            if "clarify" in behavior_set and any(
                span.get("writes") for span in materialized if not span.get("error")
            ):
                fails.append("write_after_clarify")
        elif kind == "no_write":
            if adversarial in {
                "ambiguity",
                "wrong_system",
                "missing_entity",
                "invalid_op",
                "contradiction",
            } and any(span.get("writes") for span in materialized if not span.get("error")):
                fails.append("unexpected_write")
        elif kind == "continue_on_branch_failure":
            hub = next((node for node in nodes if node.get("op") not in _READ_OPS), None)
            if hub and not by_node.get(str(hub["id"])):
                fails.append("hub_not_executed_after_branch_failure")
        elif kind == "confirm_before":
            if "confirm_before" not in behavior_set and "surface_archived" not in behavior_set:
                fails.append("no_confirm")
        elif kind == "surface_archived":
            if "surface_archived" not in behavior_set:
                fails.append("archived_not_surfaced")
        elif kind == "existence_check_first":
            if not by_node.get(str(assertion.get("node"))):
                fails.append("no_existence_check")
        elif kind == "projection_used":
            _assert_projection(assertion, materialized, by_node, fails)
        elif kind == "pagination_used":
            _assert_pagination(assertion, materialized, fails)
        elif kind == "no_retry_storm":
            denied_count = sum(
                1 for error in errors.values() if error.get("code") == 403
            )
            if denied_count > int(assertion.get("max_attempts", 2)):
                fails.append("retry_storm")

    successful_count = sum(1 for span in materialized if not span.get("error"))
    status = "fail" if fails else ("behavior" if behavior_set else "ok")
    return {
        "status": status,
        "fails": fails,
        "executed": successful_count,
        "errors": len(errors),
        "dag": executed_dag(materialized),
        "expected_edges": edges,
    }


__all__ = ["executed_dag", "grade_trace", "shape_assertions"]
