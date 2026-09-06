"""Blind reader requests and deterministic evidence checks.

The authoring library performs no model calls. Expected values stay with the
checker, never in the reader's request. Quotes must be copied from the section.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import Field

from ..ids import content_key
from ..models import Model
from ..recipe import locale_of, presentation_of
from ..world import World
from . import handshake, references
from .programs import Expansion, _world_digest


class ReaderRequest(Model):
    id: str
    request_id: str
    text_digest: str
    text: str
    aspects: tuple[str, ...]


class RecoveredClaim(Model):
    kind: str
    subject: str
    value: str
    quote: str = Field(min_length=1)


class ReaderResponse(Model):
    request_id: str
    text_digest: str
    claims: tuple[RecoveredClaim, ...]


class ReaderFinding(Model):
    request_id: str
    recovered_fact_ids: tuple[str, ...]
    missing_fact_ids: tuple[str, ...]
    invalid_quotes: int
    passed: bool


def requests(world: World, expansion: Expansion, *, share: float = .05) -> tuple[ReaderRequest, ...]:
    if not 0 <= share <= 1:
        raise ValueError("reader sample share must be in [0,1]")
    staged = world if world.artifact_irs else world.compile()
    if _world_digest(staged) != expansion.plan.world_digest:
        raise ValueError("stale expansion for reader check")
    bounded = {f"{r.artifact_id}/{r.section}": r for r in handshake.pending(staged)}
    if set(bounded) != {s.request_id for s in expansion.sections}:
        raise ValueError("reader checks require the expansion's original un-narrated world")
    scores = {rid: family.salience for family in expansion.plan.families for rid in family.request_ids}
    count = math.ceil(share * len(expansion.sections))
    chosen = sorted(expansion.sections, key=lambda section: (-scores[section.request_id], content_key(section.input_key, "reader")))[:count]
    facts = {fact.id: fact for fact in world.facts}
    out: list[ReaderRequest] = []
    for section in chosen:
        text = references.substitute(section.narrative.text, facts, locale=locale_of(world.recipe), presentation=presentation_of(world.recipe))
        digest = content_key(text)
        original = bounded[section.request_id]
        out.append(ReaderRequest(id=content_key("reader/v1", section.request_id, digest), request_id=section.request_id,
                                 text_digest=digest, text=text,
                                 aspects=tuple(sorted({facts[fid].kind for fid in original.required_fact_ids}))))
    return tuple(out)


def check(world: World, expansion: Expansion, responses: Sequence[ReaderResponse], *, share: float = .05) -> tuple[ReaderFinding, ...]:
    planned = {request.request_id: request for request in requests(world, expansion, share=share)}
    submitted = {response.request_id: response for response in responses}
    if len(submitted) != len(responses) or set(submitted) - set(planned):
        raise ValueError("duplicate or unrequested reader results")
    staged = world if world.artifact_irs else world.compile()
    bounded = {f"{r.artifact_id}/{r.section}": r for r in handshake.pending(staged)}
    facts = {fact.id: fact for fact in world.facts}
    findings: list[ReaderFinding] = []
    for rid, request in planned.items():
        response = submitted.get(rid)
        original = bounded[rid]
        recovered: set[str] = set()
        invalid = 0
        if response is not None:
            if response.text_digest != request.text_digest:
                raise ValueError(f"{rid}: stale reader result")
            for claim in response.claims:
                if claim.quote not in request.text or claim.value not in claim.quote:
                    invalid += 1
                    continue
                for fid in original.required_fact_ids:
                    fact = facts[fid]
                    expected = references.render_value(fact, locale=locale_of(world.recipe), presentation=presentation_of(world.recipe))
                    if (claim.kind == fact.kind and claim.subject == original.subjects.get(fid, fact.subject)
                            and claim.value == expected):
                        recovered.add(fid)
        missing = set(original.required_fact_ids) - recovered
        findings.append(ReaderFinding(request_id=rid, recovered_fact_ids=tuple(sorted(recovered)),
                                      missing_fact_ids=tuple(sorted(missing)), invalid_quotes=invalid,
                                      passed=response is not None and not missing and not invalid))
    return tuple(findings)


__all__ = ["ReaderFinding", "ReaderRequest", "ReaderResponse", "RecoveredClaim", "check", "requests"]
