"""Scripted readers exercise the wire/check boundary, not model comprehension."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.eval_instances import EvalInstance, EvalOracle
from worldloom.models import ArtifactIR
from worldloom.narrative import handshake, programs
from worldloom.narrative import reader_checks as readers
from worldloom.narrative.providers import ResponseProvider, UnreachableProvider
from worldloom.narrative.requests import GeneratedClaim, GeneratedNarrative
from worldloom.recipe import rebuild


def _reader(request: readers.ReaderRequest) -> readers.ReaderResponse:
    """Uses only the public passage; no corpus, fact IDs, or expected answers."""
    claims = []
    for line in request.text.splitlines():
        found = re.fullmatch(r"Subject (.+); aspect ([^;]+); value (.+)\.", line)
        if found:
            subject, kind, value = found.groups()
            claims.append(readers.RecoveredClaim(kind=kind, subject=subject, value=value, quote=line))
    return readers.ReaderResponse(
        id=request.id, request_id=request.request_id, reader_id=request.reader_id,
        text_digest=request.text_digest, contract_version=request.contract_version, claims=tuple(claims),
    )


@pytest.fixture(scope="module")
def authored() -> World:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
    facts = {fact.id: fact for fact in world.facts}
    responses = {}
    for request in handshake.pending(world):
        sentences = [(fid, "Subject " + request.subjects.get(fid, facts[fid].subject)
                      + "; aspect " + facts[fid].kind + "; value {{fact:" + fid + "}}.")
                     for fid in request.allowed_fact_ids]
        responses[f"{request.artifact_id}/{request.section}"] = GeneratedNarrative(
            text="\n".join(sentence for _, sentence in sentences),
            claims=[GeneratedClaim(text=sentence, supporting_fact_ids=[fid]) for fid, sentence in sentences],
        )
    return world.narrate(ResponseProvider(responses, model_id="scripted-author"))


def _critical(world: World, count: int = 5) -> tuple[str, ...]:
    section = next(section for ir in world.artifact_irs for section in ir.sections
                   if section.body and len(section.fact_ids) >= count)
    return tuple(section.fact_ids[:count])


def _instance(world: World, facts: tuple[str, ...], *, artifacts: tuple[str, ...] = ()) -> EvalInstance:
    return EvalInstance(id="eval-reader", spec_id="spec-reader", candidate_seed=world.seed or 0,
                        design_digest="test-design", capability="read", persona="analyst", request="Read evidence",
                        difficulty="medium", steps=(), assertions=(),
                        oracle=EvalOracle(fact_ids=facts, artifact_ids=artifacts, evidence_by_requirement={}))


def _change_body(world: World, suffix: str = " Changed prose.") -> World:
    irs: list[ArtifactIR] = []
    for ir in world.artifact_irs:
        irs.append(ir.model_copy(update={"sections": [
            section.model_copy(update={"body": section.body + suffix}) if section.body else section
            for section in ir.sections
        ]}))
    return replace(world, _artifact_irs=tuple(irs))


def test_all_critical_targets_exceed_writer_three_fact_budget(authored: World) -> None:
    critical = _critical(authored)
    instance = _instance(authored, critical)
    planned = readers.plan(authored, reader_id="independent-reader", instances=(instance,), share=0)
    assert set(planned.critical_fact_ids) == set(critical)
    assert not planned.issues
    assert max(Counter(target.request_id for target in planned.targets).values()) > 3
    assert set(target.fact.id for target in planned.targets if target.critical) == set(critical)
    result = readers.run(authored, planned, _reader)
    assert result.review.passed
    assert result.reader_calls == len(planned.requests)
    assert readers.verified_review(result.world, result.review, instances=(instance,)).passed


def test_public_payload_contains_no_oracle_targets(authored: World) -> None:
    planned = readers.plan(authored, reader_id="independent-reader", critical_fact_ids=_critical(authored), share=0)
    payload = planned.requests_document()
    wire = str(payload)
    for forbidden in ("targets_digest", "expected_value", "critical_fact_ids", "{{fact:"):
        assert forbidden not in wire
    assert all(fid not in wire for fid in planned.critical_fact_ids)
    assert "targets" not in payload and "plan" not in payload
    assert set(planned.requests[0].model_dump()) == {
        "id", "request_id", "text_digest", "text", "aspects", "reader_id", "contract_version",
    }


def test_zero_sample_unknown_missing_and_hidden_targets_refuse(authored: World) -> None:
    assert readers.plan(authored, reader_id="r", share=0).issues[0].code == "empty_reader_sample"
    unknown = readers.plan(authored, reader_id="r", critical_fact_ids=("FACT-MISSING",), share=0)
    assert {issue.code for issue in unknown.issues} == {"unknown_critical_fact", "empty_reader_sample"}
    assert not readers.run(authored, unknown, lambda _: pytest.fail("must not call reader")).review.passed
    hidden = replace(authored, _artifact_irs=tuple(ir.model_copy(update={"sections": [
        section.model_copy(update={"hidden": True}) for section in ir.sections
    ]}) for ir in authored.artifact_irs))
    planned = readers.plan(hidden, reader_id="r", critical_fact_ids=_critical(authored), share=0)
    assert "critical_evidence_missing" in {issue.code for issue in planned.issues}
    result = readers.accept(hidden, planned)
    assert not result.review.passed and len(result.world.ledger) > len(hidden.ledger)
    with pytest.raises(readers.ReaderRejected) as raised:
        result.raise_if_failed()
    assert raised.value.result == result


def test_eval_world_and_artifact_witness_constraints(authored: World) -> None:
    instance = _instance(authored, _critical(authored), artifacts=("ART-NONEXISTENT",))
    planned = readers.plan(authored, reader_id="r", instances=(instance,), share=0)
    assert "critical_evidence_missing" in {issue.code for issue in planned.issues}
    wrong = instance.model_copy(update={"candidate_seed": 99})
    assert "wrong_eval_world" in {issue.code for issue in readers.plan(authored, reader_id="r", instances=(wrong,)).issues}


@pytest.mark.parametrize("corruption", ["value", "subject", "quote", "kind", "reader", "id", "text", "version", "legacy"])
def test_wrong_claims_and_contract_bindings_fail(authored: World, corruption: str) -> None:
    planned = readers.plan(authored, reader_id="r", critical_fact_ids=_critical(authored, 1), share=0)
    replies = [_reader(request) for request in planned.requests]
    response = replies[0]
    if corruption in {"value", "subject", "quote", "kind"}:
        response = response.model_copy(update={"claims": tuple(
            claim.model_copy(update={corruption: "fabricated"}) for claim in response.claims
        )})
    elif corruption == "legacy":
        response = readers.ReaderResponse(request_id=response.request_id, text_digest=response.text_digest,
                                          claims=response.claims)
    else:
        key = {"reader": "reader_id", "id": "id", "text": "text_digest", "version": "contract_version"}[corruption]
        response = response.model_copy(update={key: "wrong"})
    result = readers.accept(authored, planned, [response, *replies[1:]])
    assert not result.review.passed
    assert not readers.verified_review(result.world, result.review).passed


def test_duplicate_unrequested_missing_and_subject_value_locality(authored: World) -> None:
    planned = readers.plan(authored, reader_id="r", critical_fact_ids=_critical(authored, 1), share=0)
    replies = tuple(_reader(request) for request in planned.requests)
    assert not readers.check_plan(authored, planned, (*replies, replies[0])).passed
    assert not readers.check_plan(authored, planned, (*replies, replies[0].model_copy(update={"request_id": "missing"}))).passed
    assert not readers.check_plan(authored, planned, ()).passed
    claim = readers.RecoveredClaim(kind="margin", subject="North", value="11", quote="North failed. South posted 11.")
    assert not readers._quoted(claim, claim.quote)
    assert not readers._quoted(claim.model_copy(update={"quote": "North posted 111."}), "North posted 111.")


def test_unchanged_acceptance_replays_without_calls_but_changed_text_does_not(authored: World) -> None:
    planned = readers.plan(authored, reader_id="r", critical_fact_ids=_critical(authored), share=0)
    accepted = readers.run(authored, planned, _reader)
    assert accepted.review.passed
    cached = readers.run(accepted.world, planned, lambda _: pytest.fail("replay called reader"))
    assert cached.replayed and cached.reader_calls == 0 and cached.world == accepted.world
    changed = _change_body(accepted.world)
    stale = readers.run(changed, planned, lambda _: pytest.fail("stale plan called reader"))
    assert not stale.review.passed
    assert "stale_reader_plan" in {issue.code for issue in stale.review.issues}
    with pytest.raises(ValueError, match="stale"):
        readers.verified_review(changed, accepted.review)
    new = readers.plan(changed, reader_id="r", critical_fact_ids=planned.critical_fact_ids, share=0)
    assert new.id != planned.id
    old_replies = tuple(_reader(request) for request in planned.requests)
    assert not readers.check_plan(changed, new, old_replies).passed


def test_changed_targets_subjects_and_plan_tampering_invalidate(authored: World) -> None:
    planned = readers.plan(authored, reader_id="r", critical_fact_ids=_critical(authored), share=0)
    accepted = readers.run(authored, planned, _reader)
    fact_id = planned.targets[0].fact.id
    changed = replace(accepted.world, _facts=tuple(
        fact.model_copy(update={"source_system": "new source"}) if fact.id == fact_id else fact
        for fact in accepted.world.facts
    ))
    assert not readers.accept(changed, planned).review.passed
    forged = planned.model_copy(update={"targets": ()})
    assert not readers.accept(accepted.world, forged, tuple(_reader(r) for r in planned.requests)).review.passed
    with pytest.raises(ValueError, match="no matching"):
        readers.verified_review(authored, accepted.review)
    with pytest.raises(ValueError, match="omits"):
        readers.verified_review(accepted.world, accepted.review, critical_fact_ids=("FACT-MISSING",))


def test_reader_cannot_identify_as_author(authored: World) -> None:
    planned = readers.plan(authored, reader_id="scripted-author", critical_fact_ids=_critical(authored), share=0)
    assert "reader_is_author" in {issue.code for issue in planned.issues}


def test_review_survives_export_rebuild_and_offline_narration(authored: World, tmp_path: Path) -> None:
    planned = readers.plan(authored, reader_id="r", critical_fact_ids=_critical(authored), share=0)
    result = readers.run(authored, planned, _reader)
    assert result.review.passed
    result.world.export(tmp_path / "original")
    loaded = World.load(tmp_path / "original")
    rebuilt = rebuild(loaded.recipe, ledger=tuple(loaded.ledger))
    narrated = rebuilt.narrate(UnreachableProvider(id="scripted-author"), ledger=tuple(loaded.ledger))
    cached = readers.run(narrated, planned, lambda _: pytest.fail("reader called during offline replay"))
    assert cached.replayed and cached.reader_calls == 0
    cached.world.export(tmp_path / "replayed")
    for directory in (tmp_path / "original", tmp_path / "replayed"):
        assert (directory / "generation-ledger.jsonl").exists()
    assert {p.relative_to(tmp_path / "original"): p.read_bytes() for p in (tmp_path / "original").rglob("*") if p.is_file()} == {
        p.relative_to(tmp_path / "replayed"): p.read_bytes() for p in (tmp_path / "replayed").rglob("*") if p.is_file()
    }


def test_program_expansion_uses_same_check_and_replays_as_ordinary_prose() -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
    planned_programs = programs.plan(world, budget=programs.Budget(model_calls=1000, variants_per_family=1, near_dup_rate=1))
    authored_programs = tuple(programs.NarrativeProgram(family=family.id, clauses=(programs.ProgramClause(
        id="record", kind="*", maximum=256,
        alternatives=("Subject $subject; aspect $kind; value $value.",),
    ),)) for family in planned_programs.families)
    expansion = programs.expand(world, planned_programs, authored_programs)
    # Program kind literals use human spelling; the adapter normalizes only the
    # aspect label advertised by the request, never an expected answer.
    def program_reader(request: readers.ReaderRequest) -> readers.ReaderResponse:
        normalized = request
        for aspect in request.aspects:
            normalized = normalized.model_copy(update={"text": normalized.text.replace(
                "; aspect " + aspect.replace("_", " ").replace(".", " ") + ";", "; aspect " + aspect + ";",
            )})
        found = _reader(normalized)
        return found.model_copy(update={"claims": tuple(claim.model_copy(update={"quote": claim.quote.replace(
            "; aspect " + claim.kind + ";", "; aspect " + claim.kind.replace("_", " ").replace(".", " ") + ";",
        )}) for claim in found.claims)})
    critical = tuple(handshake.pending(world)[0].required_fact_ids)
    planned = readers.plan(world, reader_id="r", critical_fact_ids=critical, share=0, expansion=expansion)
    # Expansion joins clauses with spaces; let the scripted wire reader split
    # only the explicit synthetic sentence delimiter.
    def callback(request: readers.ReaderRequest) -> readers.ReaderResponse:
        return program_reader(request.model_copy(update={"text": request.text.replace(". Subject ", ".\nSubject ")}))
    replies = tuple(callback(request) for request in planned.requests)
    assert readers.check_plan(world, planned, replies, expansion=expansion).passed
    committed = programs.commit(world, expansion, reader_plan=planned, reader_responses=replies)
    review = readers.accept(committed, planned)
    assert review.replayed and review.review.passed
    assert readers.verified_review(committed, review.review).passed
    with pytest.raises(readers.ReaderRejected):
        programs.commit(world, expansion, reader_plan=planned)


def test_background_budget_and_legacy_wire_are_explicit(authored: World) -> None:
    planned = readers.plan(authored, reader_id="r", share=.1)
    assert planned.requests and planned.targets
    assert not planned.critical_fact_ids
    assert readers.run(authored, planned, _reader).review.passed
    legacy = readers.ReaderRequest(id="id", request_id="request", text_digest="digest", text="prose", aspects=())
    assert set(legacy.model_dump()) == {"id", "request_id", "text_digest", "text", "aspects"}
    assert set(readers.ReaderResponse(request_id="id", text_digest="text", claims=()).model_dump()) == {
        "request_id", "text_digest", "claims",
    }


def test_observer_change_and_private_plan_tampering_refuse_without_reader_calls(authored: World) -> None:
    planned = readers.plan(authored, reader_id="r", critical_fact_ids=_critical(authored), share=0)
    accepted = readers.run(authored, planned, _reader)
    target_id = planned.targets[0].fact.id
    changed = replace(accepted.world, _facts=tuple(
        fact.model_copy(update={"observer": "a different observer"}) if fact.id == target_id else fact
        for fact in authored.facts
    ))
    refused = readers.run(changed, planned, lambda _: pytest.fail("stale plan must not invoke reader"))
    assert not refused.review.passed
    assert any(issue.code == "stale_reader_plan" for issue in refused.review.issues)
    bad_plan = planned.model_copy(update={"targets_digest": "modified"})
    assert not readers.accept(accepted.world, bad_plan).review.passed


def test_forged_ledger_success_is_rechecked(authored: World) -> None:
    planned = readers.plan(authored, reader_id="r", critical_fact_ids=_critical(authored), share=0)
    failed = readers.accept(authored, planned)
    forged = failed.review.model_copy(update={"passed": True, "missing_critical_fact_ids": ()})
    with pytest.raises(ValueError, match="no matching"):
        readers.verified_review(failed.world, forged)
    entry = next(entry for entry in failed.world.ledger if entry.call_site == readers.CALL_SITE)
    tampered = entry.model_copy(update={"output": {**entry.output, "review": forged.model_dump(mode="json")}})
    changed = replace(failed.world, _ledger=tuple(tampered if prior.key == entry.key else prior for prior in failed.world.ledger))
    with pytest.raises(ValueError, match="corrupt"):
        readers.run(changed, planned, lambda _: pytest.fail("corrupt cache must not invoke reader"))


def test_reader_configuration_binds_identity_without_disclosing_prompt(authored: World) -> None:
    kwargs = {"reader_id": "r", "critical_fact_ids": _critical(authored), "share": 0}
    one = readers.plan(authored, **kwargs, reader_config={"model": "same-reader", "prompt": "private prompt"})
    two = readers.plan(authored, **kwargs, reader_config={"model": "same-reader", "prompt": "revised prompt"})
    assert one.id != two.id and one.requests[0].id != two.requests[0].id
    assert "private prompt" not in str(one.requests_document())
    accepted = readers.run(authored, one, _reader)
    assert accepted.review.passed
    stale_replies = tuple(_reader(request) for request in one.requests)
    assert not readers.accept(accepted.world, two, stale_replies).review.passed
    for invalid in ({"temperature": float("nan")}, {"limit": float("inf")}, {"callback": object()}):
        with pytest.raises(ValueError, match="finite JSON"):
            readers.plan(authored, **kwargs, reader_config=invalid)


@pytest.mark.parametrize("quote", ["North failed. south posted 11.", "North failed. 2026 result was 11."])
def test_locality_cannot_join_lowercase_or_numeric_sentences(quote: str) -> None:
    assert not readers._quoted(readers.RecoveredClaim(kind="margin", subject="North", value="11", quote=quote), quote)
    decimal = "North reported 3.14."
    assert readers._quoted(readers.RecoveredClaim(kind="margin", subject="North", value="3.14", quote=decimal), decimal)


@pytest.mark.parametrize("success", [True, False])
def test_identical_offline_response_resubmission_is_idempotent(authored: World, success: bool) -> None:
    planned = readers.plan(authored, reader_id="r", critical_fact_ids=_critical(authored), share=0)
    replies = tuple(_reader(request) for request in planned.requests) if success else ()
    first = readers.accept(authored, planned, replies)
    assert first.review.passed is success
    second = readers.accept(first.world, planned, replies)
    third = readers.accept(second.world, planned, replies)
    assert second.replayed and third.replayed
    assert first.world == second.world == third.world
    assert first.world.recipe == second.world.recipe == third.world.recipe
    assert tuple(first.world.ledger) == tuple(third.world.ledger)


def test_identical_displayed_claims_cannot_recover_distinct_period_facts(authored: World) -> None:
    source_id = _critical(authored, 1)[0]
    source = authored.facts.by_id(source_id)
    duplicate = source.model_copy(update={"id": "FACT-DUPLICATE-READER", "period": "2025-12"})
    altered = []
    for ir in authored.artifact_irs:
        sections = []
        for section in ir.sections:
            if section.body and source_id in section.fact_ids:
                line = next(line for line in section.body.splitlines() if "{{fact:" + source_id + "}}" in line)
                sections.append(section.model_copy(update={
                    "body": section.body + "\n" + line.replace(source_id, duplicate.id),
                    "fact_ids": [*section.fact_ids, duplicate.id],
                }))
            else:
                sections.append(section)
        altered.append(ir.model_copy(update={"sections": sections}))
    world = replace(authored, _facts=(*authored._facts, duplicate), _artifact_irs=tuple(altered))
    planned = readers.plan(world, reader_id="r", critical_fact_ids=(source_id, duplicate.id), share=0)
    assert "ambiguous_reader_targets" in {issue.code for issue in planned.issues}
    result = readers.run(world, planned, lambda _: pytest.fail("ambiguous targets must not invoke reader"))
    assert not result.review.passed
