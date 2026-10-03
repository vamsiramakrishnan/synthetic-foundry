"""Checked policies for the two source defects legacy completion could not grade.

`enterprise_failures` injects two source-side defects. An ``ambiguous_join``
adds a second record that is indistinguishable from the bound one except for
its identity. A ``stale_source`` rolls the bound record back one version.
Their requests already state the policy ("put ambiguous matches in a review
section; do not guess"; "prefer the authoritative current version"). Their
gold was still the legacy single write, and a run that ignored the policy
graded clean. The DAG grammar refuses both kinds for that reason.

This module states one gold outcome for each defect. ``grade_outcomes`` checks
it from what the run produced:

- **clarify the join**: the bound record and its duplicate are both
  candidates. The gold reads both, asks which one is meant while naming both,
  declines to proceed, and writes nothing. Picking one candidate and writing
  is the failure, ``outcomes.clarification_missing``.
- **use the authoritative replacement**: the stale record names its
  replacement in ``superseded_by``, and the replacement is materialised beside
  it (``authoritative_replacement`` on the override). The gold reads both and
  cites the replacement. Citing the stale record without the replacement
  produces ``outcomes.stale_source_used``. Citing neither produces
  ``outcomes.authoritative_source_missing``. Naming the stale record *as*
  stale beside its replacement is what the request asks for.

The rewrite is opt-in (``cases_from_corpus(..., source_policy=True)`` or
``with_source_policies``). An unchanged case set keeps its legacy gold and
bytes, and an existing ledger keeps its grades.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from ..enterprise_failures import ambiguous_duplicate_id, authoritative_replacement_id
from .contract import EvalCase, case_from_row

#: The policy each source defect is graded under.
POLICY_FOR_FAILURE: dict[str, str] = {
    "ambiguous_join": "clarify_ambiguous_join",
    "stale_source": "authoritative_replacement",
}

_READ_OPS = frozenset({"get", "read", "search", "extract", "download", "list"})


def _keys(record: Mapping[str, Any] | None, fid: str) -> list[str]:
    """What an agent can see a record called: its vendor key first, then its internal id."""
    if record is None:
        return [fid]
    keys = [str(record[name]) for name in ("external_id", "ident") if record.get(name) not in (None, "")]
    return list(dict.fromkeys([*keys, fid]))


def _is_source_read(node: Mapping[str, Any]) -> bool:
    # A verify resolves to a get too; its own spelling, or its reference to
    # the write it checks, is what separates it from evidence.
    if str(node.get("op") or "") in {"readback", "cross_system"} or node.get("reference_from"):
        return False
    return str(node.get("resolved_operation") or node.get("op") or "") in _READ_OPS


def source_policy_row(row: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The row rewritten to its source policy's gold, or ``None`` when it injects neither defect.

    A row with both defects, or a defect without a bound read of its record,
    is refused rather than given a gold the reference could not meet.
    """
    overrides = [dict(item) for item in row.get("state_overrides", ())
                 if str(item.get("kind")) in POLICY_FOR_FAILURE]
    if not overrides:
        return None
    if len(overrides) != 1 or not overrides[0].get("record_id"):
        raise ValueError(f"row {row.get('id')!r}: a source policy needs exactly one source defect on a named record")
    override = overrides[0]
    kind, record_id, query_id = str(override["kind"]), str(override["record_id"]), str(row.get("id", ""))
    by_fid = {str(record.get("fid")): record for record in records if record.get("fid")}
    nodes = [dict(node) for node in (row.get("expected_dag") or {}).get("nodes", ())]
    read = next((node for node in nodes if node.get("fixture") == record_id and _is_source_read(node)), None)
    if read is None:
        raise ValueError(f"row {query_id!r}: no read of the {kind} record {record_id}")
    rewritten = deepcopy(dict(row))
    assertions = [dict(item) for item in row.get("assertions", ())]
    edges = [list(edge) for edge in (row.get("expected_dag") or {}).get("edges", ())]
    bound = _keys(by_fid.get(record_id), record_id)
    if kind == "ambiguous_join":
        other = ambiguous_duplicate_id(query_id, record_id)
        second = {**read, "id": "read-candidate", "fixture": other}
        if isinstance(second.get("payload"), dict) and "id" in second["payload"]:
            second["payload"] = {**second["payload"], "id": other}
        # The write and its verify stay on the row, gated, so their tools are
        # still offered: declining to use them is the policy. They leave the
        # plan, and a run that writes anyway is collateral on a no-write case.
        reads = {str(node["id"]) for node in nodes if _is_source_read(node)}
        gated = [node if str(node["id"]) in reads
                 else {**node, "flags": sorted({*node.get("flags", ()), "gated"})} for node in nodes]
        rewritten["expected_dag"] = {"nodes": [*gated, second], "edges": edges}
        kept_ids = reads | {"read-candidate"}
        assertions = [item for item in assertions
                      if all(str(item[key]) in kept_ids for key in ("node", "before", "after") if key in item)]
        assertions.extend([
            {"type": "tool_called", "node": "read-candidate"},
            {"type": "reads_contain", "node": "read-candidate", "records": [other]},
            {"type": "question_required", "id": "which-record", "reason": "ambiguous_request",
             "about": [record_id, other], "must_mention": [bound[0], other],
             "answer": "Do not choose one. Hold both for review.", "blocks_nodes": [], "proceed": False},
        ])
        rewritten["source_policy"] = {"kind": POLICY_FOR_FAILURE[kind],
                                      "candidates": [bound, [other]]}
        rewritten["expected_answer"] = (f"Two records match and nothing in them says which one is meant: "
                                        f"{bound[0]} and {other}. Held both for review; nothing was written.")
    else:
        replacement = authoritative_replacement_id(query_id, record_id)
        override["details"] = {**override.get("details", {}), "authoritative_replacement": True}
        rewritten["state_overrides"] = [override if str(item.get("kind")) == kind else dict(item)
                                        for item in row.get("state_overrides", ())]
        current = {**read, "id": "read-authoritative", "fixture": replacement}
        if isinstance(current.get("payload"), dict) and "id" in current["payload"]:
            current["payload"] = {**current["payload"], "id": replacement}
        position = nodes.index(read) + 1
        consumers = [str(target) for source, target in edges if str(source) == str(read["id"])]
        rewritten["expected_dag"] = {
            "nodes": [*nodes[:position], current, *nodes[position:]],
            "edges": [*edges, [str(read["id"]), "read-authoritative"],
                      *(["read-authoritative", target] for target in consumers)],
        }
        assertions.extend([
            {"type": "tool_called", "node": "read-authoritative"},
            {"type": "reads_contain", "node": "read-authoritative", "records": [replacement]},
            *({"type": "order", "before": "read-authoritative", "after": target} for target in consumers),
        ])
        rewritten["source_policy"] = {"kind": POLICY_FOR_FAILURE[kind], "stale": bound,
                                      "authoritative": [replacement]}
        rewritten["expected_answer"] = (f"Used the authoritative {replacement}; {bound[0]} is stale and "
                                        f"superseded by it.")
    rewritten["assertions"] = assertions
    return rewritten


def with_source_policies(cases: Iterable[EvalCase], records: Sequence[Mapping[str, Any]]) -> tuple[EvalCase, ...]:
    """Each case with a source defect recompiled under its policy; every other case unchanged."""
    out: list[EvalCase] = []
    for case in cases:
        row = source_policy_row(case.row, records)
        if row is None:
            out.append(case)
            continue
        unstructured = case.outcomes.unstructured
        out.append(case_from_row(
            row, query=case.query, persona=case.persona, principal=case.principal,
            dimensions={**case.dimensions, "source_policy": row["source_policy"]["kind"]},
            output_format=unstructured.format if unstructured is not None else None,
            answer=case.outcomes.answer,
            sections=unstructured.sections if unstructured is not None else (),
        ))
    return tuple(out)


__all__ = ["POLICY_FOR_FAILURE", "source_policy_row", "with_source_policies"]
