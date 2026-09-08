"""Blind reader requests and deterministic evidence checks.

The authoring library performs no model calls. Expected values stay with the
checker, never in the reader's request. Quotes must be copied from the section.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from ..eval_instances import EvalInstance
from ..ids import content_key
from ..models import CanonicalFact, GenerationLedgerEntry, Model
from ..recipe import locale_of, presentation_of, with_step
from ..world import World
from . import handshake, references
from .programs import Expansion, _world_digest


class ReaderRequest(Model):
    id: str
    request_id: str
    text_digest: str
    text: str
    aspects: tuple[str, ...]
    reader_id: str = ""
    contract_version: str = "reader/v1"

    @model_serializer(mode="wrap")
    def _legacy_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if self.contract_version == "reader/v1" and not self.reader_id:
            data.pop("reader_id", None)
            data.pop("contract_version", None)
        return data


class RecoveredClaim(Model):
    kind: str
    subject: str
    value: str
    quote: str = Field(min_length=1)


class ReaderResponse(Model):
    request_id: str
    text_digest: str
    claims: tuple[RecoveredClaim, ...]
    id: str = ""
    reader_id: str = ""
    contract_version: str = "reader/v1"

    @model_serializer(mode="wrap")
    def _legacy_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if self.contract_version == "reader/v1" and not self.reader_id and not self.id:
            for name in ("id", "reader_id", "contract_version"):
                data.pop(name, None)
        return data


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


CONTRACT: Literal["reader/v2"] = "reader/v2"
CALL_SITE = "narration.reader"


class ReaderIssue(Model):
    code: str
    detail: str
    request_id: str = ""
    fact_ids: tuple[str, ...] = ()


class ReaderTarget(Model):
    """Checker-only evidence. Never serialize this object to a reader."""

    request_id: str
    fact: CanonicalFact
    subject: str
    expected_value: str
    critical: bool
    temporal_cutoff: str | None
    observer: str


class ReaderPlan(Model):
    """Private check plan; only ``requests`` is an external-reader payload."""

    id: str
    reader_id: str
    reader_config: dict[str, Any] = Field(default_factory=dict)
    contract_version: Literal["reader/v2"] = CONTRACT
    critical_fact_ids: tuple[str, ...]
    instances: tuple[EvalInstance, ...]
    share: float = Field(ge=0, le=1)
    source: Literal["world", "expansion"]
    context_digest: str
    targets_digest: str
    requests: tuple[ReaderRequest, ...]
    targets: tuple[ReaderTarget, ...]
    issues: tuple[ReaderIssue, ...]

    def requests_document(self) -> dict[str, object]:
        return {
            "contract_version": CONTRACT,
            "reader_id": self.reader_id,
            "instructions": (
                "Read each passage independently. Recover claims for the named aspects. "
                "Copy the subject and displayed value exactly from the passage and provide "
                "a verbatim quote containing both in the same sentence. Do not infer missing "
                "claims. Return each request's id, request_id, text_digest, reader_id and "
                "contract_version unchanged. No answer key is supplied."
            ),
            "requests": [request.model_dump(mode="json") for request in self.requests],
            "response_schema": ReaderResponse.model_json_schema(),
        }


class ReaderReview(Model):
    plan_id: str
    reader_id: str
    contract_version: Literal["reader/v2"] = CONTRACT
    findings: tuple[ReaderFinding, ...]
    issues: tuple[ReaderIssue, ...]
    critical_fact_ids: tuple[str, ...]
    recovered_critical_fact_ids: tuple[str, ...]
    missing_critical_fact_ids: tuple[str, ...]
    passed: bool


@dataclass(frozen=True)
class ReaderAcceptance:
    world: World
    review: ReaderReview
    reader_calls: int = 0
    replayed: bool = False

    def raise_if_failed(self) -> ReaderAcceptance:
        if not self.review.passed:
            raise ReaderRejected(self)
        return self


class ReaderRejected(ValueError):
    """Carries the world with the failed review, so rejection loses no evidence."""

    def __init__(self, result: ReaderAcceptance):
        super().__init__("reader checks missing or failed; inspect review findings before repair")
        self.result = result


@dataclass(frozen=True)
class _Section:
    request_id: str
    text: str
    allowed: frozenset[str]
    required: frozenset[str]
    subjects: dict[str, str]
    cutoff: str | None
    observer: str
    artifact_id: str
    author: str


def _sections(world: World, expansion: Expansion | None) -> tuple[_Section, ...]:
    from .compiler import _request_for

    staged = world if world.artifact_irs else world.compile()
    facts = {fact.id: fact for fact in staged.facts}
    expanded = {section.request_id: section for section in expansion.sections} if expansion else {}
    if expansion is not None:
        if _world_digest(staged) != expansion.plan.world_digest:
            raise ValueError("stale expansion for reader check")
        pending = {f"{r.artifact_id}/{r.section}" for r in handshake.pending(staged)}
        if pending != set(expanded) or len(expanded) != len(expansion.sections):
            raise ValueError("reader checks require the expansion's original un-narrated world")
        if any(s.output_digest != content_key(s.narrative.model_dump(mode="json"))
               for s in expansion.sections):
            raise ValueError("corrupt expansion output")
    out: list[_Section] = []
    seen: set[str] = set()
    for ir in staged.artifact_irs:
        intent = staged.artifact_intents.by_id(ir.intent_id)
        for section in ir.sections:
            rid = f"{ir.id}/{section.heading}"
            if rid in seen:
                raise ValueError(f"ambiguous reader section identity: {rid}")
            seen.add(rid)
            if section.hidden:
                continue
            body = expanded[rid].narrative.text if rid in expanded else section.body
            if not body:
                continue
            request = _request_for(staged, ir, section, facts)
            cited = frozenset(references.referenced(body))
            if cited - set(request.allowed_fact_ids):
                raise ValueError(f"{rid}: reader prose cites unknown or unavailable evidence")
            text = references.substitute(body, facts, locale=locale_of(world.recipe),
                                         presentation=presentation_of(world.recipe))
            if references.REFERENCE_SHAPED.search(text):
                raise ValueError(f"{rid}: unresolved fact reference in reader prose")
            out.append(_Section(
                rid, text, cited, frozenset(request.required_fact_ids), request.subjects,
                request.temporal_cutoff.isoformat() if request.temporal_cutoff else None,
                intent.author_id, ir.id, ir.metadata.get("narrated_by", ""),
            ))
    return tuple(sorted(out, key=lambda section: section.request_id))


def plan(world: World, *, reader_id: str, critical_fact_ids: Sequence[str] = (),
         instances: Sequence[EvalInstance] = (), share: float = .05,
         expansion: Expansion | None = None,
         reader_config: Mapping[str, Any] | None = None) -> ReaderPlan:
    """Cover every eval-critical fact, then sample a bounded background share.

    The three required facts in a writer brief are a writing budget, not a limit
    on evaluation evidence. Mandatory targets come from the full oracle and are
    joined to actual visible prose references. Missing evidence is a refusal.
    """
    if not reader_id.strip():
        raise ValueError("reader_id must be non-empty")
    if not 0 <= share <= 1:
        raise ValueError("reader sample share must be in [0,1]")
    share = float(share)
    try:
        configuration = json.loads(json.dumps(dict(reader_config or {}), sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("reader_config must be a finite JSON object") from exc
    instances = tuple(sorted(instances, key=lambda instance: instance.id))
    if len({instance.id for instance in instances}) != len(instances):
        raise ValueError("duplicate eval instances in reader plan")
    critical = tuple(sorted(set(critical_fact_ids) | {
        fid for instance in instances for fid in instance.oracle.fact_ids
    }))
    issues: list[ReaderIssue] = []
    facts = {fact.id: fact for fact in world.facts}
    for instance in instances:
        if instance.candidate_seed != world.seed:
            issues.append(ReaderIssue(code="wrong_eval_world", detail=instance.id,
                                      fact_ids=instance.oracle.fact_ids))
    unknown = set(critical) - set(facts)
    if unknown:
        issues.append(ReaderIssue(code="unknown_critical_fact", detail="not in the world's fact ledger",
                                  fact_ids=tuple(sorted(unknown))))
    sections = _sections(world, expansion)
    bindings: dict[str, set[str]] = {}
    for fid in critical:
        if fid not in facts:
            continue
        # A fact may support several evals with different artifact witnesses.
        # Each distinct witness constraint earns a target; an unrelated memo
        # cannot stand in for the document the eval actually retrieves.
        constraints = [set(instance.oracle.artifact_ids) for instance in instances
                       if fid in instance.oracle.fact_ids and instance.oracle.artifact_ids]
        constraints = constraints or [set()]
        for artifacts in constraints:
            eligible = [section for section in sections if fid in section.allowed
                        and (not artifacts or section.artifact_id in artifacts)]
            if not eligible:
                issues.append(ReaderIssue(code="critical_evidence_missing",
                                          detail="no visible cited prose in the required artifact witnesses",
                                          fact_ids=(fid,)))
                continue
            chosen = min(eligible, key=lambda section: (section.request_id not in bindings,
                                                       content_key("critical-reader", fid, section.request_id)))
            bindings.setdefault(chosen.request_id, set()).add(fid)
    background = [section for section in sections if section.request_id not in bindings
                  and section.allowed]
    count = math.ceil(share * len(background))
    for section in sorted(background, key=lambda s: content_key("background-reader/v2", s.request_id))[:count]:
        # Sampling a section creates a real obligation even when its writing
        # brief happened to require no facts; an empty answer must never pass.
        bindings[section.request_id] = set(section.required & section.allowed or section.allowed)
    targets: list[ReaderTarget] = []
    selected = {section.request_id: section for section in sections if section.request_id in bindings}
    for rid in sorted(bindings):
        section = selected[rid]
        if section.author == reader_id:
            issues.append(ReaderIssue(code="reader_is_author", detail="reader identity must differ from author",
                                      request_id=rid))
        identities: dict[tuple[str, str, str], list[str]] = {}
        for fid in sorted(section.allowed):
            identity = (facts[fid].kind, section.subjects.get(fid, facts[fid].subject),
                        references.render_value(facts[fid], locale=locale_of(world.recipe),
                                                presentation=presentation_of(world.recipe)))
            identities.setdefault(identity, []).append(fid)
        for _identity, fact_ids in sorted(identities.items()):
            if len(fact_ids) > 1 and bindings[rid].intersection(fact_ids):
                # Equal displayed values can belong to different periods or
                # authority records. The current reader response names neither;
                # one copied claim cannot prove which canonical fact it read.
                issues.append(ReaderIssue(
                    code="ambiguous_reader_targets",
                    detail="distinct cited facts share kind, subject and displayed value; period or authority is not recoverable",
                    request_id=rid, fact_ids=tuple(fact_ids),
                ))
        for fid in sorted(bindings[rid]):
            targets.append(ReaderTarget(
                request_id=rid, fact=facts[fid], subject=section.subjects.get(fid, facts[fid].subject),
                expected_value=references.render_value(facts[fid], locale=locale_of(world.recipe),
                                                       presentation=presentation_of(world.recipe)),
                critical=fid in critical, temporal_cutoff=section.cutoff, observer=section.observer,
            ))
    if not targets:
        issues.append(ReaderIssue(code="empty_reader_sample", detail="no evidence targets were selected"))
    targets_digest = content_key(CONTRACT, tuple(target.model_dump(mode="json") for target in targets))
    context_digest = content_key(
        world.seed, configuration, asdict(locale_of(world.recipe)),
        asdict(presentation_of(world.recipe)),
        tuple((s.request_id, s.text, sorted(s.allowed), sorted(s.required), s.subjects,
               s.cutoff, s.observer) for s in sections),
        tuple(instance.model_dump(mode="json") for instance in instances), critical,
    )
    identifier = content_key(CONTRACT, reader_id, context_digest, targets_digest, share,
                             tuple(issue.model_dump(mode="json") for issue in issues))
    requests_ = tuple(ReaderRequest(
        # The opaque correlation address binds the private check context. No
        # target records, expected values or oracle digest are disclosed.
        id=content_key(CONTRACT, identifier, rid), request_id=rid,
        text_digest=content_key(selected[rid].text), text=selected[rid].text,
        aspects=tuple(sorted({facts[fid].kind for fid in bindings[rid]})),
        reader_id=reader_id, contract_version=CONTRACT,
    ) for rid in sorted(bindings))
    return ReaderPlan(id=identifier, reader_id=reader_id, reader_config=configuration, critical_fact_ids=critical,
                      instances=instances, share=share, source="expansion" if expansion else "world",
                      context_digest=context_digest, targets_digest=targets_digest, requests=requests_,
                      targets=tuple(targets), issues=tuple(issues))


def _current(world: World, planned: ReaderPlan, expansion: Expansion | None) -> bool:
    if planned.source == "world" and expansion is not None:
        return False
    try:
        rebuilt = plan(world, reader_id=planned.reader_id, critical_fact_ids=planned.critical_fact_ids,
                       instances=planned.instances, share=planned.share, expansion=expansion,
                       reader_config=planned.reader_config)
    except (ValueError, KeyError):
        # A changed observer/cutoff may make formerly valid prose unavailable.
        # Keep that stale check inspectable instead of losing the review while
        # attempting to reconstruct its now-invalid request.
        return False
    # Once a program is committed, its expanded prose is ordinary World prose.
    # The check identity is the content, not the transport that produced it.
    return rebuilt.model_copy(update={"source": planned.source}) == planned


def _phrase(phrase: str, text: str) -> bool:
    return bool(phrase and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))


def _quoted(claim: RecoveredClaim, text: str) -> bool:
    if claim.quote not in text:
        return False
    # Lexical evidence locality, deliberately not a semantic entailment model.
    # Whole-section quotes must not associate one sentence's subject with a
    # different sentence's value. Decimal punctuation is not a sentence break.
    return any(_phrase(claim.value, sentence) and _phrase(claim.subject, sentence)
               for sentence in re.split(r"(?<=[.!?])\s+|\n", claim.quote))


def _evaluate(planned: ReaderPlan, responses: Sequence[ReaderResponse], *,
              extra_issues: Sequence[ReaderIssue] = ()) -> ReaderReview:
    issues = list(planned.issues) + list(extra_issues)
    submitted: dict[str, ReaderResponse] = {}
    requested = {request.request_id for request in planned.requests}
    for incoming in responses:
        if incoming.request_id in submitted:
            issues.append(ReaderIssue(code="duplicate_reader_response", detail="one response per section",
                                      request_id=incoming.request_id))
        if incoming.request_id not in requested:
            issues.append(ReaderIssue(code="unrequested_reader_response", detail="not in this plan",
                                      request_id=incoming.request_id))
        submitted[incoming.request_id] = incoming
    findings: list[ReaderFinding] = []
    for request in planned.requests:
        response = submitted.get(request.request_id)
        expected = tuple(target for target in planned.targets if target.request_id == request.request_id)
        recovered: set[str] = set()
        invalid = 0
        bound = response is not None
        if response is not None:
            if response.id != request.id or response.text_digest != request.text_digest:
                issues.append(ReaderIssue(code="stale_reader_response", detail="request identity or prose changed",
                                          request_id=request.request_id))
                bound = False
            if response.reader_id != planned.reader_id or response.contract_version != CONTRACT:
                issues.append(ReaderIssue(code="wrong_reader_contract", detail="reader identity or contract differs",
                                          request_id=request.request_id))
                bound = False
            if bound:
                for claim in response.claims:
                    if not _quoted(claim, request.text):
                        invalid += 1
                        continue
                    for target in expected:
                        if (claim.kind == target.fact.kind and claim.subject == target.subject
                                and claim.value == target.expected_value):
                            recovered.add(target.fact.id)
        missing = {target.fact.id for target in expected} - recovered
        passed = bool(bound and expected and not missing and not invalid)
        findings.append(ReaderFinding(request_id=request.request_id, recovered_fact_ids=tuple(sorted(recovered)),
                                      missing_fact_ids=tuple(sorted(missing)), invalid_quotes=invalid, passed=passed))
    by_request = {finding.request_id: finding for finding in findings}
    recovered_critical = {
        fid for fid in planned.critical_fact_ids
        if any(target.fact.id == fid and target.critical for target in planned.targets)
        and all(by_request[target.request_id].passed and fid in by_request[target.request_id].recovered_fact_ids
                for target in planned.targets if target.fact.id == fid and target.critical)
    }
    missing_critical = set(planned.critical_fact_ids) - recovered_critical
    return ReaderReview(
        plan_id=planned.id, reader_id=planned.reader_id, findings=tuple(findings), issues=tuple(issues),
        critical_fact_ids=planned.critical_fact_ids, recovered_critical_fact_ids=tuple(sorted(recovered_critical)),
        missing_critical_fact_ids=tuple(sorted(missing_critical)),
        passed=bool(findings and not issues and not missing_critical and all(f.passed for f in findings)),
    )


def check_plan(world: World, planned: ReaderPlan, responses: Sequence[ReaderResponse], *,
               expansion: Expansion | None = None) -> ReaderReview:
    """Check actual quote recovery; failures remain structured and inspectable."""
    issues = () if _current(world, planned, expansion) else (
        ReaderIssue(code="stale_reader_plan", detail="text, targets, locale, cutoff or plan changed"),
    )
    return _evaluate(planned, responses, extra_issues=issues)


def _entry(planned: ReaderPlan, responses: Sequence[ReaderResponse], review: ReaderReview,
           seed: int, prior_keys: Sequence[str]) -> GenerationLedgerEntry:
    output = {"plan": planned.model_dump(mode="json"),
              "responses": [response.model_dump(mode="json") for response in responses],
              "review": review.model_dump(mode="json"), "prior_ledger_keys": list(prior_keys)}
    key = content_key(CONTRACT, seed, output)
    return GenerationLedgerEntry(
        id="READER-" + key[:20], key=key, call_site=CALL_SITE, ordinal=0,
        world_seed=seed, input_facts_digest=planned.targets_digest, model_id=planned.reader_id,
        prompt_version=CONTRACT, output=output,
    )


def _read_entry(entry: GenerationLedgerEntry) -> tuple[ReaderPlan, tuple[ReaderResponse, ...], ReaderReview]:
    planned = ReaderPlan.model_validate(entry.output.get("plan"))
    responses = tuple(ReaderResponse.model_validate(row) for row in entry.output.get("responses", ()))
    review = ReaderReview.model_validate(entry.output.get("review"))
    prior = entry.output.get("prior_ledger_keys", ())
    if not isinstance(prior, list) or any(not isinstance(key, str) for key in prior) or len(set(prior)) != len(prior):
        raise ValueError("corrupt reader ledger predecessors")
    if entry != _entry(planned, responses, review, entry.world_seed, prior):
        raise ValueError("corrupt reader ledger identity")
    # A previously stale plan remains a rejected record even if its submitted
    # answers happened to recover every target. It can never become a cache hit.
    extras = tuple(issue for issue in review.issues if issue.code == "stale_reader_plan")
    if review != _evaluate(planned, responses, extra_issues=extras):
        raise ValueError("corrupt reader ledger findings")
    return planned, responses, review


def replay(world: World, *, keys: Sequence[str], ledger: Sequence[GenerationLedgerEntry]) -> World:
    """Restore review records; a later check still validates current prose."""
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate reader ledger keys")
    available = {entry.key: entry for entry in ledger}
    if len(available) != len(ledger):
        raise ValueError("duplicate generation ledger keys")
    entries = {entry.key: entry for entry in world.ledger}
    for key in keys:
        entry = available.get(key)
        if entry is None or entry.call_site != CALL_SITE or entry.world_seed != (world.seed or 0):
            raise ValueError("missing or wrong-world reader ledger entry")
        _read_entry(entry)
        # A review made after ordinary narration must replay after those same
        # entries. Merely appending the review during recipe rebuild moved it
        # before prose and broke byte identity despite identical check results.
        for predecessor_key in entry.output["prior_ledger_keys"]:
            predecessor = available.get(predecessor_key) or entries.get(predecessor_key)
            if predecessor is None or predecessor.world_seed != entry.world_seed:
                raise ValueError("missing reader ledger predecessor")
            previous = entries.get(predecessor_key)
            if previous is not None and previous != predecessor:
                raise ValueError("conflicting reader ledger predecessor")
            entries[predecessor_key] = predecessor
        prior = entries.get(key)
        if prior is not None and prior != entry:
            raise ValueError("conflicting reader ledger entry")
        entries[key] = entry
    return replace(world, _ledger=tuple(entries.values()),
                   _recipe=with_step(world.recipe, "NarrationReaders", keys=list(keys)))


def _cached(world: World, planned: ReaderPlan) -> ReaderAcceptance | None:
    for entry in world.ledger:
        if entry.call_site != CALL_SITE:
            continue
        recorded, _, review = _read_entry(entry)
        if recorded == planned and review.passed and entry.world_seed == (world.seed or 0):
            return ReaderAcceptance(world, review, replayed=True)
    return None


def accept(world: World, planned: ReaderPlan, responses: Sequence[ReaderResponse] = (), *,
           expansion: Expansion | None = None) -> ReaderAcceptance:
    """Persist accepted and rejected reviews; unchanged acceptance replays offline."""
    current = _current(world, planned, expansion)
    if current and not responses:
        cached = _cached(world, planned)
        if cached is not None:
            return cached
    ordered = tuple(sorted(responses, key=lambda response: (response.request_id, response.model_dump_json())))
    review = _evaluate(planned, ordered, extra_issues=() if current else (
        ReaderIssue(code="stale_reader_plan", detail="text, targets, locale, cutoff or plan changed"),
    ))
    # Retrying the same offline response file must retain its original receipt.
    # Including the current predecessors in a fresh receipt before this lookup
    # otherwise makes every retry depend on the previous retry's new key.
    for existing in world.ledger:
        if existing.call_site == CALL_SITE and existing.world_seed == (world.seed or 0):
            recorded_plan, recorded_responses, recorded_review = _read_entry(existing)
            if (recorded_plan, recorded_responses, recorded_review) == (planned, ordered, review):
                return ReaderAcceptance(world, review, replayed=True)
    entry = _entry(planned, ordered, review, world.seed or 0, tuple(entry.key for entry in world.ledger))
    updated = replay(world, keys=(entry.key,), ledger=(*world.ledger, entry))
    return ReaderAcceptance(updated, review)


def run(world: World, planned: ReaderPlan, reader: Callable[[ReaderRequest], ReaderResponse], *,
        expansion: Expansion | None = None) -> ReaderAcceptance:
    """External callback convenience; cache misses alone reach the reader."""
    if not _current(world, planned, expansion):
        return accept(world, planned, expansion=expansion)
    cached = _cached(world, planned)
    if cached is not None:
        return cached
    if planned.issues:
        return accept(world, planned, expansion=expansion)
    responses = tuple(reader(request) for request in planned.requests)
    return replace(accept(world, planned, responses, expansion=expansion), reader_calls=len(responses))


def verified_review(world: World, review: ReaderReview, *, instances: Sequence[EvalInstance] = (),
                    critical_fact_ids: Sequence[str] = (), expansion: Expansion | None = None) -> ReaderReview:
    """Verify a persisted review before a controller promotes its returned World.

    Checks the original replies again, binds them to the current prose and fact
    records, and requires every supplied eval instance and critical target to be
    present in that check. A caller-created ``passed=True`` is not evidence.
    Rejected but authentic reviews are returned with ``passed=False``.
    """
    for entry in world.ledger:
        if entry.call_site != CALL_SITE:
            continue
        planned, responses, recorded = _read_entry(entry)
        if recorded != review:
            continue
        if entry.world_seed != (world.seed or 0) or not _current(world, planned, expansion):
            raise ValueError("stale or wrong-world reader review")
        required = set(critical_fact_ids) | {fid for instance in instances for fid in instance.oracle.fact_ids}
        if required - set(planned.critical_fact_ids):
            raise ValueError("reader review omits required critical targets")
        available = {instance.id: instance for instance in planned.instances}
        if any(available.get(instance.id) != instance for instance in instances):
            raise ValueError("reader review is not bound to the supplied eval instances")
        if _evaluate(planned, responses) != recorded:
            raise ValueError("reader review findings no longer match the evidence")
        return recorded
    raise ValueError("reader review has no matching generation ledger evidence")


__all__ = [
    "ReaderAcceptance", "ReaderFinding", "ReaderIssue", "ReaderPlan", "ReaderRejected", "ReaderRequest",
    "ReaderResponse", "ReaderReview", "ReaderTarget", "RecoveredClaim", "accept", "check", "check_plan",
    "plan", "replay", "requests", "run", "verified_review",
]
