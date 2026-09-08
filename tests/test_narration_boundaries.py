"""Authoring reuse must preserve the complete evidence and request boundary."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.compiler import handshake as plans
from worldloom.narrative import compiler, handshake, prompts, references
from worldloom.narrative.providers import DeterministicProvider, UnreachableProvider
from worldloom.narrative.requests import GeneratedNarrative


@pytest.fixture(scope="module")
def world() -> World:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True),
    ).compile()


def target(world: World):  # type: ignore[no-untyped-def]
    request = next(r for r in handshake.pending(world) if len(r.allowed_fact_ids) > 1)
    assert request.temporal_cutoff is not None
    fact = world.facts.by_id(request.allowed_fact_ids[0])
    return request, fact


@pytest.mark.parametrize("boundary", ["valid", "recorded", "withdrawn", "observer", "latent"])
def test_both_authoring_requests_withhold_inaccessible_facts(world: World, boundary: str) -> None:
    request, fact = target(world)
    cutoff = request.temporal_cutoff
    later = cutoff + timedelta(days=1)
    updates = {
        "valid": {"valid_from": later, "tx_from": fact.valid_from},
        "recorded": {"tx_from": later},
        "withdrawn": {"tx_to": cutoff},
        "observer": {"observer": "a-different-author"},
        "latent": {"source": "latent"},
    }[boundary]
    changed = replace(world, _facts=tuple(
        f.model_copy(update=updates) if f.id == fact.id else f for f in world.facts
    ))
    prose = next(r for r in handshake.pending(changed)
                 if (r.artifact_id, r.section) == (request.artifact_id, request.section))
    shape = next(r for r in plans.requests(changed) if r.artifact_id == request.artifact_id)
    assert fact.id not in prose.allowed_fact_ids
    assert fact.id not in prose.required_fact_ids
    assert fact.id not in {f["id"] for f in shape.available_facts}
    assert fact.id not in shape.required_fact_ids


def test_a_superseded_hypothesis_remains_available_as_history(world: World) -> None:
    request, fact = target(world)
    changed = replace(world, _facts=tuple(
        f.model_copy(update={"valid_to": request.temporal_cutoff}) if f.id == fact.id else f
        for f in world.facts
    ))
    for document, field in ((handshake.requests_document(changed), "facts"),
                            (plans.requests_document(changed), "available_facts")):
        row = next(r for r in document["requests"] if r["artifact_id"] == request.artifact_id
                   and fact.id in {f["id"] for f in r[field]})
        supplied = next(f for f in row[field] if f["id"] == fact.id)
        assert supplied["superseded"] is True


def test_providers_receive_only_their_allowed_fact_records(world: World) -> None:
    class ScopedProvider(DeterministicProvider):
        def complete(self, request, prompt, facts, *, feedback=""):  # type: ignore[no-untyped-def]
            assert set(facts) == set(request.allowed_fact_ids)
            return super().complete(request, prompt, facts, feedback=feedback)

    provider = ScopedProvider()
    result = world.narrate(provider)
    assert result.ledger and provider.calls


@pytest.mark.parametrize("change", ["purpose", "author", "cutoff", "authority", "superseded"])
def test_changed_writing_contract_cannot_hit_recorded_prose(world: World, change: str) -> None:
    request, fact = target(world)
    recorded = world.narrate(DeterministicProvider())
    ir = next(ir for ir in world.artifact_irs if ir.id == request.artifact_id)
    if change == "purpose":
        changed_ir = ir.model_copy(update={"sections": [
            s.model_copy(update={"purpose": "Explain the revised evidence carefully."})
            if s.heading == request.section else s for s in ir.sections
        ]})
        changed = replace(world, _artifact_irs=tuple(changed_ir if r.id == ir.id else r
                                                  for r in world.artifact_irs))
    elif change == "author":
        intent = world.artifact_intents.by_id(ir.intent_id)
        changed = replace(world, _people=tuple(
            p.model_copy(update={"title": "Revised controller"}) if p.id == intent.author_id else p
            for p in world.people
        ))
    elif change == "cutoff":
        changed = replace(world, _artifacts=tuple(
            a.model_copy(update={"created_at": a.created_at + timedelta(minutes=1)}) if a.id == ir.id else a
            for a in world.artifacts
        ))
    else:
        updates = {"valid_to": request.temporal_cutoff} if change == "superseded" else {"authority": "working_document"}
        changed = replace(world, _facts=tuple(
            f.__class__.model_validate({**f.model_dump(mode="json"), **updates}) if f.id == fact.id else f
            for f in world.facts
        ))
    provider = DeterministicProvider()
    result = compiler.narrate(changed, provider, ledger=tuple(recorded.ledger))
    assert result.provider_calls > 0
    assert result.replayed < len(recorded.ledger)
    replay = compiler.narrate(changed, UnreachableProvider(), ledger=result.ledger)
    assert replay.irs == result.irs
    assert replay.provider_calls == 0


def test_both_writer_surfaces_carry_terminology_and_fact_history(world: World) -> None:
    request, _ = target(world)
    request = request.model_copy(update={"terminology": {"run rate": "Use only for recurring revenue."}})
    facts = {f.id: f for f in world.facts}
    payload = handshake.request_payload(request, facts)
    brief = prompts.SECTION_PROSE.render(request, facts)
    assert payload["terminology"] == request.terminology
    assert payload["facts"][0]["recorded_at"]
    assert "Use only for recurring revenue." in brief
    assert "superseded:" in brief


@pytest.mark.parametrize("parser,field", [(handshake.parse_responses, "responses"), (plans.parse_responses, "plans")])
def test_duplicate_ids_cannot_overwrite_a_response(parser, field: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="duplicate"):
        parser({field: [{"id": "same"}, {"id": "same"}]})


def test_unknown_response_ids_are_reported(world: World) -> None:
    result = handshake.review(world, {"unknown/request": GeneratedNarrative(text="")})
    assert result["unknown/request"].violations[0].code == "unexpected_response"


@pytest.mark.parametrize("loaded", [False, True])
def test_narration_invalidates_earlier_rendered_files(world: World, tmp_path, loaded: bool) -> None:
    rendered = world.render("markdown")
    destination = tmp_path / "corpus"
    if loaded:
        rendered.export(destination)
        rendered = World.load(destination)
    narrated = rendered.narrate(DeterministicProvider())
    assert not narrated._rendered
    assert all(not artifact.path for artifact in narrated.artifacts)
    narrated.export(destination, overwrite=loaded)
    assert not (destination / "artifacts").exists()
    refreshed = narrated.render("markdown")
    refreshed.export(destination, overwrite=True)
    ir = next(ir for ir in refreshed.artifact_irs if any(s.body for s in ir.sections)
              and refreshed.artifacts.by_id(ir.id).path.endswith(".md"))
    body = next(s.body for s in ir.sections if s.body)
    expected = references.substitute(body, {f.id: f for f in refreshed.facts})
    assert expected in (destination / refreshed.artifacts.by_id(ir.id).path).read_text()
    unchanged = refreshed.narrate(DeterministicProvider())
    assert unchanged._rendered == refreshed._rendered
