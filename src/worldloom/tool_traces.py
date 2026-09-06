"""Deterministic tool traces and projection checks, independent of answer prose."""
from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from .evidence_locators import EvidenceRef, FieldLocator
from .models import Model


class ToolSpan(Model):
    id: str
    sequence: int = Field(ge=0)
    operation: str
    connector: str
    entity: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()
    effect_ids: tuple[str, ...] = ()
    requested_fields: tuple[str, ...] | None = None
    returned_fields: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    record_ids: dict[str, str] = Field(default_factory=dict)
    record_digests: dict[str, str] = Field(default_factory=dict)
    bytes_returned: int = Field(default=0, ge=0)
    error: str | None = None


class TraceGraph(Model):
    spans: tuple[ToolSpan, ...]
    edges: tuple[tuple[str, str], ...]


class TraceFinding(Model):
    code: str
    passed: bool
    detail: str


def trace_graph(spans: Sequence[ToolSpan]) -> TraceGraph:
    """Declared consumption edges must point backwards, so cycles cannot pass."""
    seen: dict[str, ToolSpan] = {}
    previous = -1
    edges: list[tuple[str, str]] = []
    for span in spans:
        if span.id in seen or span.sequence <= previous:
            raise ValueError("trace IDs and sequence numbers must be unique and ordered")
        if set(span.parents) - seen.keys() or len(span.parents) != len(set(span.parents)):
            raise ValueError("trace parents must be unique prior spans")
        for parent in span.parents:
            source = seen[parent]
            if source.error or not set(source.outputs).intersection(span.inputs):
                raise ValueError("dependency edge must consume a successful parent's output")
            edges.append((parent, span.id))
        seen[span.id] = span
        previous = span.sequence
    return TraceGraph(spans=tuple(spans), edges=tuple(edges))


def projection_used(span: ToolSpan, evidence: EvidenceRef, *, max_bytes: int,
                    needed_fields: Sequence[str] = ()) -> TraceFinding:
    """Check actual content version and projection, not merely a fields argument.

    This proves read shape/efficiency, not answer correctness. Grading an answer
    or write effect remains a separate oracle assertion.
    """
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    loc = evidence.locator
    if not isinstance(loc, FieldLocator):
        raise ValueError("field projection grading requires a field locator")
    needed = set(needed_fields) | {loc.field}
    fields = set(span.returned_fields.get(loc.external_id, ()))
    passed = (
        span.error is None and span.operation in {"read", "search"}
        and span.connector == loc.connector and span.entity == loc.entity
        and loc.external_id in span.outputs
        and span.record_ids.get(loc.external_id) == evidence.artifact_id
        and span.requested_fields is not None
        and needed <= set(span.requested_fields) and needed <= fields
        and span.record_digests.get(loc.external_id) == evidence.content_digest
        and span.bytes_returned <= max_bytes
    )
    return TraceFinding(code="projection_used", passed=passed,
                        detail=f"returned={span.bytes_returned}; budget={max_bytes}; fields={sorted(fields)}")


__all__ = ["ToolSpan", "TraceFinding", "TraceGraph", "projection_used", "trace_graph"]
