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

#: Every assertion kind `grade_trace` decides. Kept beside the chain that
#: implements them and checked before it, because that chain has no else: an
#: unrecognised kind used to fall through and grade clean, so a typo passed.
#:
#: Adding a branch below without adding its name here makes the assertion
#: unreachable, which is the failure this set is shaped to make loud rather
#: than silent.
_KNOWN_ASSERTIONS = frozenset(
    {
        "execution_contract",
        "tool_called",
        "order",
        "artifact_created",
        "failure_at",
        "per_item",
        "branch_exclusive",
        "state_equals",
        "per_record_state",
        "deleted",
        "denial_surfaced",
        "report_not_found",
        "clarify_before_write",
        "question_required",
        "no_write",
        "continue_on_branch_failure",
        "confirm_before",
        "surface_archived",
        "existence_check_first",
        "projection_used",
        "fields_used",
        "pagination_used",
        "no_retry_storm",
        "reads_contain",
    }
)


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


def _assert_fields_used(
    assertion: Mapping[str, Any], row: Mapping[str, Any],
    by_node: Mapping[str, list[dict[str, Any]]], fails: list[str],
) -> None:
    from .connector_definition import ConnectorDefinition, load_connector_definition
    from .connector_query import parse_native
    from .predicates import Predicate

    node_id = str(assertion["node"])
    required = set(assertion.get("fields", ()))
    projected = set(assertion.get("payload_fields", required))
    successful = [span for span in by_node.get(node_id, ()) if not span.get("error") and span.get("reads")]
    used: set[str] = set()
    seen_projection: set[str] = set()
    for span in successful:
        args = span.get("args", {})
        active = args.get("predicate")
        try:
            if active is not None:
                predicate = active if isinstance(active, Predicate) else Predicate.model_validate(active)
            elif args.get("query"):
                connector = str(span["tool"]).split(".", 1)[0]
                raw = row.get("connector_definitions", {}).get(connector)
                definition = ConnectorDefinition.model_validate(raw) if raw else load_connector_definition(connector)
                predicate = parse_native(definition, str(args["query"]), entity=args.get("entity"))
            else:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        used.update(item.field for item in predicate.where)
        seen_projection.update(args.get("fields") or ())
    if not required or not required <= used or not projected <= seen_projection:
        fails.append(f"fields_not_used:{node_id}")


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

    expected_failures = {
        str(assertion.get("node")): str(assertion.get("kind"))
        for assertion in assertions if assertion.get("type") == "failure_at"
    }
    failure_stopped: set[str] = set()
    # Nodes an observed designed failure blocked, apart from the failing node
    # itself: an expected error on one of them cannot be observed either.
    failure_blocked: set[str] = set()
    for assertion in assertions:
        if assertion.get("type") != "failure_at":
            continue
        node_id = str(assertion.get("node"))
        if any((span.get("error") or {}).get("kind") == assertion.get("kind") for span in by_node.get(node_id, ())):
            if not assertion.get("writes_persist"):
                failure_stopped.add(node_id)
            failure_stopped.update(str(value) for value in assertion.get("blocked_nodes", ()))
            failure_blocked.update(str(value) for value in assertion.get("blocked_nodes", ()))
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
        if kind not in _KNOWN_ASSERTIONS:
            # The chain below has no else, so an unrecognised kind used to fall
            # straight through and grade clean. A typo in an assertion type is
            # then indistinguishable from a passing check, which is the worst
            # way for a grader to be wrong: it reports success for a rule it
            # never applied.
            fails.append(f"unknown_assertion:{kind}")
            continue
        if kind in {"artifact_created", "state_equals", "per_record_state", "deleted", "reads_contain", "fields_used", "fact_coverage"} and str(assertion.get("node")) in failure_stopped:
            continue
        if kind == "execution_contract":
            from .enterprise_dag_trace import grade_execution_contract
            fails.extend(grade_execution_contract(materialized, row, post_state))
        elif kind == "tool_called":
            node_id = str(assertion["node"])
            node = nodes_by_id.get(node_id)
            if node is None:
                # An assertion naming a node the DAG does not contain used to
                # raise KeyError out of the grader. A malformed row should fail
                # its own grade, not abort the run that was grading it.
                fails.append(f"unknown_node:{node_id}")
                continue
            if node_id in skipped or "gated" in node.get("flags", ()) or node.get("optional"):
                continue
            node_spans = by_node.get(node_id, ())
            if not node_spans and node_id in stopped:
                continue
            if node.get("op") == "create" and "updated_existing" in behavior_set and node_spans:
                continue
            if not any(
                span["tool"] == tool_of.get(node_id)
                and (not span.get("error") or span["error"].get("kind") == expected_failures.get(node_id))
                for span in node_spans
            ):
                fails.append(f"tool_not_called:{node_id}")
        elif kind == "failure_at":
            node_id = str(assertion.get("node"))
            if node_id not in nodes_by_id:
                fails.append(f"unknown_node:{node_id}")
                continue
            if node_id in failure_blocked:
                # A delete chain expects `not_found` on its last readback; when
                # the write before it met its own designed failure, the chain
                # never reached the readback and there is no error to observe.
                continue
            node_spans = by_node.get(node_id, ())
            if not node_spans and nodes_by_id[node_id].get("condition") and any(item.get("type") == "execution_contract" for item in assertions):
                # The grammar grader reconstructs the condition from bound
                # evidence and requires a call exactly on its selected branch.
                continue
            matching = [span for span in node_spans if (span.get("error") or {}).get("kind") == assertion.get("kind")]
            if not matching:
                fails.append(f"failure_not_observed:{node_id}:{assertion.get('kind')}")
            if any(span.get("writes") for span in matching) != bool(assertion.get("writes_persist")):
                fails.append(f"failure_side_effect_mismatch:{node_id}")
            if any(span.get("error") and span["error"].get("kind") != assertion.get("kind") for span in node_spans):
                fails.append(f"unexpected_error:{node_id}")
            if any(not span.get("error") for span in node_spans):
                fails.append(f"unexpected_success:{node_id}")
            if assertion.get("writes_persist") and post_state is None:
                fails.append(f"failure_post_state_missing:{node_id}")
            declared = assertion.get("fixture")
            if declared and assertion.get("writes_persist") and any(set(span.get("writes", ())) != {str(declared)} for span in matching):
                fails.append(f"failure_target_mismatch:{node_id}")
            if declared and assertion.get("writes_persist") and nodes_by_id[node_id].get("op") != "delete" and str(declared) not in (post_state or {}):
                fails.append(f"failure_post_state_missing:{node_id}")
            created = assertion.get("created_record")
            if isinstance(created, Mapping) and assertion.get("writes_persist"):
                for span in matching:
                    for fid in span.get("writes", ()):
                        created_record = (post_state or {}).get(str(fid), {})
                        if not created_record or any(value is not None and created_record.get(key) != value for key, value in created.items()):
                            fails.append(f"failure_target_mismatch:{node_id}")
            for blocked_id in assertion.get("blocked_nodes", ()):
                if by_node.get(str(blocked_id)):
                    fails.append(f"executed_after_failure:{blocked_id}")
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
                span for span in by_node.get(node_id, ())
                if not span.get("error") or (
                    expected_failures.get(node_id) == "partial_write"
                    and span.get("error", {}).get("kind") == "partial_write"
                    and span.get("writes")
                )
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
        elif kind == "state_equals":
            node_id = str(assertion["node"])
            if node_id in skipped or node_id in stopped:
                continue
            if post_state is None:
                fails.append(f"state_unavailable:{node_id}")
                continue
            # The record the row says should end in this state, when it names
            # one. Anchoring on the row rather than on the trace matters more
            # than it looks: resolving the target from what the agent wrote
            # lets the agent choose what it is graded on, so writing to some
            # other record passed. `deleted` already anchors on its declared
            # `fixture`; this is the same rule for the same reason. Observed
            # writes stay as the fallback, because a row that names no fixture
            # is the shape every existing caller emits.
            declared = assertion.get("fixture") or nodes_by_id.get(node_id, {}).get(
                "fixture"
            )
            targets = (
                [declared]
                if declared
                else [
                    write
                    for span in by_node.get(node_id, ())
                    for write in span.get("writes", ())
                ]
            )
            if not targets:
                # Nothing was written, so there is no state to compare and the
                # loop below never ran: `state_equals` graded `ok` for a run
                # that never executed the node at all, and for one that
                # executed it and wrote nothing. "The system was updated"
                # passing on a system that was never updated is the exact
                # failure an outcome grader exists to catch.
                #
                # `skipped` and `stopped` are already handled above, so
                # reaching here means the node was expected to write.
                node = nodes_by_id.get(node_id) or {}
                if not ("gated" in node.get("flags", ()) or node.get("optional")):
                    fails.append(f"state_not_written:{node_id}")
                continue
            expected_state = str(assertion["state"]).casefold()
            persisted_writes = {
                str(write) for span in by_node.get(node_id, ())
                if not span.get("error") or (
                    expected_failures.get(node_id) == "partial_write"
                    and span.get("error", {}).get("kind") == "partial_write"
                )
                for write in span.get("writes", ())
            }
            for target in targets:
                record = post_state.get(str(target))
                if record is None:
                    # Written, then absent from the post-state. Distinct from a
                    # mismatch and previously silent.
                    fails.append(f"state_missing:{node_id}")
                    break
                states = {str(record.get(str(assertion["field"]), "")).casefold()} if assertion.get("field") else {
                    str(record.get("state", "")).casefold(),
                    str(record.get("status", "")).casefold(),
                    str(record.get("state_label", "")).casefold(),
                }
                if expected_state not in states:
                    fails.append(f"state_mismatch:{node_id}")
                    break
                if str(target) not in persisted_writes:
                    # A preexisting matching state proves no side effect. The
                    # successful write must address the row's declared record.
                    fails.append(f"state_not_written:{node_id}")
                    break
        elif kind == "deleted":
            node_id = str(assertion["node"])
            if node_id not in skipped and node_id not in stopped:
                if post_state is None:
                    fails.append(f"deletion_unverified:{node_id}")
                elif assertion.get("created_by"):
                    # The record to be gone is whichever the named write
                    # created in this run: every successful write of that
                    # node must be absent afterwards, and a write that never
                    # happened leaves nothing that could have been deleted.
                    created = [str(fid) for span in by_node.get(str(assertion["created_by"]), ())
                               if not span.get("error") for fid in span.get("writes", ())]
                    if not created or any(fid in post_state for fid in created):
                        fails.append(f"not_deleted:{node_id}")
                elif assertion.get("records"):
                    # A mapped delete names every record it must remove.
                    for fid in assertion["records"]:
                        if str(fid) in post_state:
                            fails.append(f"not_deleted:{node_id}:{fid}")
                elif not assertion.get("per_item") and str(assertion["fixture"]) in post_state:
                    fails.append(f"not_deleted:{node_id}")
        elif kind == "per_record_state":
            # Every record a mapped write iterates must end with the stated
            # fields, by fid: the assertion anchors on the row's own list,
            # never on what the agent wrote (`state_equals`'s rule).
            node_id = str(assertion["node"])
            if node_id in skipped or node_id in stopped:
                continue
            if post_state is None:
                fails.append(f"state_unavailable:{node_id}")
                continue
            for fid in assertion.get("records", ()):
                record = post_state.get(str(fid))
                if record is None:
                    fails.append(f"record_missing:{node_id}:{fid}")
                    continue
                for field, value in dict(assertion.get("fields", {})).items():
                    if record.get(field) != value:
                        fails.append(f"record_state_mismatch:{node_id}:{fid}:{field}")
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
                span.get("writes") for span in materialized
            ):
                fails.append("write_after_clarify")
        elif kind == "question_required":
            # The service records the questions a run asked and matches each
            # to the row's points; a matched point arrives here as the
            # behaviour `question:<id>`. The trajectory axis grades timing
            # and the reply; this decides only that the question was asked.
            point_id = str(assertion.get("id") or "")
            if point_id and f"question:{point_id}" not in behavior_set:
                fails.append(f"no_question:{point_id}")
        elif kind == "no_write":
            if adversarial in {
                "ambiguity",
                "wrong_system",
                "missing_entity",
                "invalid_op",
                "contradiction",
            } and any(span.get("writes") for span in materialized):
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
        elif kind == "fields_used":
            if str(assertion["node"]) not in skipped | stopped:
                _assert_fields_used(assertion, row, by_node, fails)
        elif kind == "projection_used":
            _assert_projection(assertion, materialized, by_node, fails)
        elif kind == "pagination_used":
            _assert_pagination(assertion, materialized, fails)
        elif kind == "reads_contain":
            # The resultset outcome: not merely that a read happened, but that
            # it returned the records the case names. Every other kind here
            # grades the trajectory or a side effect; nothing graded what came
            # back, so "find the open incidents for this change" could pass by
            # reading any record at all.
            node_id = str(assertion["node"])
            if node_id in skipped or node_id in stopped:
                continue
            wanted = {str(rid) for rid in assertion.get("records", ())}
            if not wanted:
                continue
            seen = {
                str(read)
                for span in by_node.get(node_id, ())
                for read in span.get("reads", ())
            }
            missing = sorted(wanted - seen)
            if missing:
                fails.append(f"reads_missing:{node_id}:{','.join(missing)}")
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
