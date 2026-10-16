"""Grade evaluator-owned controlled-retrieval receipts on the trajectory axis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..models import Model
from .retrieval import RetrievalContract, RetrievalReceipt


class RetrievalGrade(Model):
    searches: int
    sufficient: int
    insufficient: int
    recovered: int
    repeated_without_progress: int
    missing_receipts: int
    unsupported_queries: int = 0
    transport_faults: int = 0
    findings: tuple[str, ...] = ()
    passed: bool


def retrieval_receipt(row: Mapping[str, Any], span: Mapping[str, Any]) -> RetrievalReceipt | None:
    """An annotation counts only for this contract, tool and observed span.

    This runs on service-owned spans. Responses, programs, notes and other
    agent-authored objects are never a source of evaluator receipts.
    """
    if not row.get("controlled_retrieval") or not span.get("retrieval"):
        return None
    try:
        contract = RetrievalContract.model_validate(row["controlled_retrieval"])
        receipt = RetrievalReceipt.model_validate(span["retrieval"])
    except (TypeError, ValueError):
        return None
    expected_tool = f"{contract.connector}.{contract.tool}"
    if (receipt.contract_id != contract.id or receipt.span_id != span.get("id")
            or receipt.ordinal != span.get("ordinal") or receipt.tool != expected_tool
            or span.get("tool") != expected_tool):
        return None
    if tuple(item.record_id for item in receipt.returned) != tuple(span.get("reads", ())):
        return None
    return receipt


def is_retrieval_attempt(row: Mapping[str, Any], span: Mapping[str, Any]) -> bool:
    receipt = retrieval_receipt(row, span)
    return receipt is not None and receipt.intent_status != "sufficient" and not span.get("writes")


def grade_retrieval(row: Mapping[str, Any], spans: Sequence[Mapping[str, Any]]) -> RetrievalGrade | None:
    raw = row.get("controlled_retrieval")
    if raw is None:
        return None
    try:
        contract = RetrievalContract.model_validate(raw)
    except (TypeError, ValueError):
        return RetrievalGrade(searches=0, sufficient=0, insufficient=0, recovered=0,
                              repeated_without_progress=0, missing_receipts=0,
                              findings=("invalid_retrieval_contract",), passed=False)
    relevant = [span for span in spans if span.get("tool") == f"{contract.connector}.{contract.tool}"]
    findings: list[str] = []
    sufficient = insufficient = recovered = missing = repeats = unsupported = faults = 0
    pending: list[RetrievalReceipt] = []
    previous: RetrievalReceipt | None = None
    for span in relevant:
        receipt = retrieval_receipt(row, span)
        if receipt is None:
            missing += 1
            findings.append(f"missing_retrieval_receipt:{span.get('id')}")
            continue
        transient_retry = previous is not None and previous.intent_status == "transport_fault"
        decision_status = receipt.intent_status in {"sufficient", "insufficient", "invalid_query"}
        if decision_status and (receipt.progress == "no_progress" or (receipt.progress == "retry" and not transient_retry)):
            repeats += 1
            findings.append(f"query_without_progress:{receipt.span_id}")
        if receipt.intent_status == "sufficient" and not span.get("error"):
            sufficient += 1
            if pending:
                # A successful retry of a transient fault is valid recovery;
                # an insufficient query requires changed query semantics.
                changed = all(item.query_digest != receipt.query_digest
                              for item in pending if item.intent_status not in {"transport_fault", "unsupported_query"})
                if changed:
                    recovered += 1
                    pending.clear()
                else:
                    findings.append(f"unchanged_insufficient_query:{receipt.span_id}")
        else:
            if receipt.intent_status == "unsupported_query":
                unsupported += 1
            elif receipt.intent_status == "transport_fault":
                faults += 1
            else:
                insufficient += 1
            pending.append(receipt)
        previous = receipt
    if sufficient == 0:
        findings.append("no_sufficient_query")
    if pending:
        findings.append("unresolved_retrieval")
    if previous is not None and previous.intent_status == "sufficient" and not previous.is_last:
        findings.append("incomplete_pagination")
    return RetrievalGrade(searches=len(relevant), sufficient=sufficient, insufficient=insufficient,
                          recovered=recovered, repeated_without_progress=repeats, missing_receipts=missing,
                          unsupported_queries=unsupported, transport_faults=faults,
                          findings=tuple(dict.fromkeys(findings)), passed=not findings)


__all__ = ["RetrievalGrade", "retrieval_receipt", "is_retrieval_attempt", "grade_retrieval"]
