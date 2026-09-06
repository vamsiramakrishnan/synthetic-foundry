from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.ids import content_key
from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.narrative import handshake, programs, reader_checks, references
from worldloom.narrative.providers import UnreachableProvider
from worldloom.narrative.requests import NarrativeRequest
from worldloom.recipe import locale_of, presentation_of, rebuild


@pytest.fixture(scope="module")
def world():  # type: ignore[no-untyped-def]
    return RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()


def test_authoring_budget_counts_families_not_instances(world) -> None:  # type: ignore[no-untyped-def]
    plan = programs.plan(world, budget=programs.Budget(model_calls=2))
    assert len(plan.author_requests()) == 2
    assert sum(len(f.request_ids) for f in plan.families) > 2
    assert not programs.plan(world, budget=programs.Budget(model_calls=0)).author_requests()


@pytest.mark.parametrize("template", ["Profit is 400.", "Profit is $value as of 2026.", "{{fact:F-1}}", "$value.__class__ $missing", "${__import__('os')}", "The result is $unknown.", "No binding."])
def test_unsafe_programs_are_rejected_before_expansion(template: str) -> None:
    with pytest.raises(ValueError):
        programs.ProgramClause(id="bad", kind="*", alternatives=(template,))


def test_expansion_is_deterministic_cached_and_provenance_bound(world) -> None:  # type: ignore[no-untyped-def]
    plan = programs.plan(world, budget=programs.Budget(model_calls=0, near_dup_rate=1))
    first = programs.expand(world, plan)
    second = programs.expand(world, plan, cache={s.input_key: s for s in first.sections})
    assert first.sections == second.sections
    assert second.cache_hits == len(first.sections)
    for section in first.sections:
        assert section.dependencies
        assert section.output_digest == content_key(section.narrative.model_dump(mode="json"))
        assert {fid for dep in section.dependencies for fid in dep.fact_ids} == {
            fid for claim in section.narrative.claims for fid in claim.supporting_fact_ids
        }


def test_programs_commit_through_existing_validator_and_replay_offline(world) -> None:  # type: ignore[no-untyped-def]
    plan = programs.plan(world, budget=programs.Budget(model_calls=0, near_dup_rate=1))
    expansion = programs.expand(world, plan)
    narrated = programs.commit(world, expansion)
    assert any(entry.call_site == "narration.program" for entry in narrated.ledger)
    assert any(entry.call_site == "narration.dependencies" for entry in narrated.ledger)
    ids = {entry.model_id for entry in narrated.ledger}
    assert len(ids) == 1
    rebuilt = rebuild(narrated.recipe, ledger=tuple(narrated.ledger))
    replayed = rebuilt.narrate(UnreachableProvider(id=ids.pop()), ledger=tuple(narrated.ledger))
    assert tuple(replayed.artifact_irs) == tuple(narrated.artifact_irs)
    assert tuple(replayed.ledger) == tuple(narrated.ledger)
    assert replayed.recipe == narrated.recipe
    assert replayed._narration[0] == 0


def test_unknown_families_and_unbudgeted_variants_are_findings(world) -> None:  # type: ignore[no-untyped-def]
    plan = programs.plan(world, budget=programs.Budget(model_calls=0))
    program = programs.fallback(plan.families[0])
    assert programs.accept_programs(plan, [program])[0].code == "budget_exceeded"
    assert programs.accept_programs(plan, [program.model_copy(update={"family": "nope"})])[0].code == "unknown_family"


def test_stale_plan_and_corrupt_cache_refuse(world) -> None:  # type: ignore[no-untyped-def]
    plan = programs.plan(world, budget=programs.Budget(model_calls=0, near_dup_rate=1))
    expansion = programs.expand(world, plan)
    section = expansion.sections[0]
    broken = section.model_copy(update={"output_digest": "wrong"})
    with pytest.raises(ValueError, match="corrupt"):
        programs.expand(world, plan, cache={section.input_key: broken})
    with pytest.raises(ValueError, match="stale"):
        programs.expand(replace(world, _facts=world._facts[:-1]), plan)


def test_clause_cache_ignores_unused_facts_and_tracks_used_facts() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    def fact(id_: str) -> CanonicalFact:
        return CanonicalFact(id=id_, kind="metric", subject="group", value=Quantity(amount=1, unit="units"), valid_from=now, authority=Authority.CONFIRMED)
    facts = {id_: fact(id_) for id_ in ("used", "unused")}
    request = NarrativeRequest(artifact_id="a", artifact_type="memo", section="summary", persona_id="p", voice="plain", audience="finance", author_title="controller", temporal_cutoff=now, allowed_fact_ids=["used", "unused"], required_fact_ids=["used"])
    program = programs.NarrativeProgram(family="test", clauses=(programs.ProgramClause(id="metric", kind="metric", maximum=1, alternatives=("The value is $value.",)),))
    key = programs._expansion_key(program, request, facts)
    facts["unused"] = facts["unused"].model_copy(update={"value": Quantity(amount=2, unit="units")})
    assert key == programs._expansion_key(program, request, facts)
    facts["used"] = facts["used"].model_copy(update={"value": Quantity(amount=2, unit="units")})
    assert key != programs._expansion_key(program, request, facts)
    wrong = program.model_copy(update={"clauses": (programs.ProgramClause(id="wrong", kind="missing", alternatives=("The value is $value.",)),)})
    with pytest.raises(ValueError, match="required_fact_omitted"):
        programs._expand_one(wrong, request, facts, frozenset())


def test_program_metadata_survives_export_and_reload(world, tmp_path) -> None:  # type: ignore[no-untyped-def]
    plan = programs.plan(world, budget=programs.Budget(model_calls=0, near_dup_rate=1))
    original = programs.commit(world, programs.expand(world, plan))
    original.export(tmp_path / "original")
    loaded = World.load(tmp_path / "original")
    rebuilt = rebuild(loaded.recipe, ledger=tuple(loaded.ledger))
    provider_id = next(ir.metadata["narrated_by"] for ir in loaded.artifact_irs)
    replayed = rebuilt.narrate(UnreachableProvider(id=provider_id), ledger=tuple(loaded.ledger))
    replayed.export(tmp_path / "replayed")
    original_files = {p.relative_to(tmp_path / "original"): p.read_bytes()
                      for p in (tmp_path / "original").rglob("*") if p.is_file()}
    replayed_files = {p.relative_to(tmp_path / "replayed"): p.read_bytes()
                      for p in (tmp_path / "replayed").rglob("*") if p.is_file()}
    assert original_files == replayed_files


def test_reader_receives_only_rendered_section_and_aspects(world) -> None:  # type: ignore[no-untyped-def]
    expansion = programs.expand(world, programs.plan(world, budget=programs.Budget(model_calls=0, near_dup_rate=1)))
    requests = reader_checks.requests(world, expansion, share=.1)
    assert 0 < len(requests) < len(expansion.sections)
    for request in requests:
        assert "{{fact:" not in request.text
        assert "expected" not in request.model_dump()
    assert all(not finding.passed for finding in reader_checks.check(world, expansion, [], share=.1))
    assert requests == reader_checks.requests(world, expansion, share=.1)


def test_stale_reader_and_fabricated_quote_refuse(world) -> None:  # type: ignore[no-untyped-def]
    expansion = programs.expand(world, programs.plan(world, budget=programs.Budget(model_calls=0, near_dup_rate=1)))
    request = reader_checks.requests(world, expansion)[0]
    response = reader_checks.ReaderResponse(request_id=request.request_id, text_digest="wrong", claims=())
    with pytest.raises(ValueError, match="stale"):
        reader_checks.check(world, expansion, [response])
    invalid = response.model_copy(update={"text_digest": request.text_digest, "claims": (
        reader_checks.RecoveredClaim(kind="metric", subject="group", value="wrong", quote="never in the section"),
    )})
    finding = reader_checks.check(world, expansion, [invalid])[0]
    assert not finding.passed and finding.invalid_quotes == 1


def test_reader_budget_blocks_commit_without_readings(world) -> None:  # type: ignore[no-untyped-def]
    plan = programs.plan(world, budget=programs.Budget(model_calls=0, near_dup_rate=1, reader_check_share=.1))
    with pytest.raises(ValueError, match="reader checks"):
        programs.commit(world, programs.expand(world, plan))


def test_reader_recovers_required_values_with_copied_evidence(world) -> None:  # type: ignore[no-untyped-def]
    expansion = programs.expand(world, programs.plan(world, budget=programs.Budget(model_calls=0, near_dup_rate=1)))
    bounded = {f"{r.artifact_id}/{r.section}": r for r in handshake.pending(world)}
    facts = {fact.id: fact for fact in world.facts}
    replies = []
    for request in reader_checks.requests(world, expansion, share=1):
        original = bounded[request.request_id]
        replies.append(reader_checks.ReaderResponse(
            request_id=request.request_id, text_digest=request.text_digest,
            claims=tuple(reader_checks.RecoveredClaim(
                kind=facts[fid].kind, subject=original.subjects.get(fid, facts[fid].subject),
                value=references.render_value(facts[fid], locale=locale_of(world.recipe), presentation=presentation_of(world.recipe)),
                quote=request.text,
            ) for fid in original.required_fact_ids),
        ))
    assert all(finding.passed for finding in reader_checks.check(world, expansion, replies, share=1))
