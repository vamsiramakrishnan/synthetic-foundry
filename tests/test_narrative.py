"""Step 6: the LLM as a constrained narrative compiler.

Three claims have been in the docs since the design rounds and were never exercised
in code. This module is where they become true:

1. Determinism survives the model — a world regenerates byte-identical with the
   provider unreachable.
2. The model references numbers and never restates them.
3. Generation proposes; the deterministic layer accepts or rejects.

The centrepiece is ``test_a_world_replays_with_the_provider_unreachable``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.narrative import (
    DeterministicProvider,
    GeneratedClaim,
    GeneratedNarrative,
    NarrationError,
    NarrativeRequest,
    ProviderError,
    UnreachableProvider,
    ViolatingProvider,
    ledger_key,
    prompts,
    references,
    validate,
)

PERIOD = "2026-03"


def fresh() -> World:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )


@pytest.fixture(scope="module")
def narrated() -> World:
    return fresh().narrate(DeterministicProvider())


def prose_of(world: World) -> dict[str, str]:
    """Every narrated section body, keyed by artifact and heading."""
    return {
        f"{ir.id}/{section.heading}": section.body
        for ir in world.artifact_irs
        for section in ir.sections
        if section.body
    }


# ---------------------------------------------------------------------------
# Determinism survives the model
# ---------------------------------------------------------------------------


def test_narration_records_every_call_in_the_ledger(narrated: World) -> None:
    assert len(narrated.ledger) > 0
    assert len(narrated.ledger) == len(prose_of(narrated))

    for entry in narrated.ledger:
        assert entry.world_seed == 8128
        assert entry.model_id == "deterministic-fake-1"
        assert entry.prompt_version == prompts.SECTION_PROSE.key
        assert len(entry.key) == 32
        assert entry.output["text"]


def test_a_world_replays_with_the_provider_unreachable(narrated: World) -> None:
    """The promise the design rests on, finally demonstrated.

    Rebuild the world from its seed, hand it a provider that refuses to answer, and
    give it the recorded ledger. Every call must be served from the ledger, and the
    prose must come back identical.
    """
    replayed = fresh().narrate(UnreachableProvider(), ledger=narrated.ledger)

    assert prose_of(replayed) == prose_of(narrated)
    provider_calls, replays, _ = replayed._narration
    assert provider_calls == 0, "a replay must not call the provider at all"
    assert replays == len(narrated.ledger)


def test_an_exported_corpus_replays_byte_for_byte(narrated: World, tmp_path) -> None:
    """The end-to-end promise: same seed plus ledger, no model, identical files.

    Compares the written bytes rather than the in-memory objects, because the
    artifact a user hands to someone else is the file.
    """
    formats = ("markdown", "jira", "confluence", "servicenow", "xlsx")
    first = narrated.render(*formats).export(tmp_path / "first")

    replayed = fresh().narrate(UnreachableProvider(), ledger=World.load(first)._ledger)
    second = replayed.render(*formats).export(tmp_path / "second")

    written = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert written == sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
    for relative in written:
        assert (first / relative).read_bytes() == (second / relative).read_bytes(), relative


def test_replay_fails_loudly_when_the_ledger_is_incomplete(narrated: World) -> None:
    """Silence would be worse: a corpus half-replayed and half-invented."""
    with pytest.raises(ProviderError, match="Replay is incomplete"):
        fresh().narrate(UnreachableProvider(), ledger=narrated.ledger[:-3])


def test_narration_is_reproducible_without_a_ledger() -> None:
    assert prose_of(fresh().narrate(DeterministicProvider())) == prose_of(
        fresh().narrate(DeterministicProvider())
    )


def test_the_ledger_survives_export_and_reload(narrated: World, tmp_path) -> None:
    destination = narrated.render("markdown").export(tmp_path / "out")
    reloaded = World.load(destination)

    assert len(reloaded.ledger) == len(narrated.ledger)
    assert {e.key for e in reloaded.ledger} == {e.key for e in narrated.ledger}

    # And the reloaded ledger is enough to replay offline.
    replayed = fresh().narrate(UnreachableProvider(), ledger=reloaded.ledger)
    assert prose_of(replayed) == prose_of(narrated)


# ---------------------------------------------------------------------------
# The ledger key
# ---------------------------------------------------------------------------


def _key(**overrides) -> str:  # type: ignore[no-untyped-def]
    base = dict(
        seed=8128, call_site="ART-0001/Position", ordinal=0,
        fact_digest="abc", model_id="m-1", prompt_version="p@1",
    )
    return ledger_key(**{**base, **overrides})


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", 9001),
        ("call_site", "ART-0001/Recommendation"),
        ("ordinal", 1),
        ("fact_digest", "def"),
        ("model_id", "m-2"),
        ("prompt_version", "p@2"),
    ],
)
def test_every_component_of_the_key_is_load_bearing(field: str, value) -> None:  # type: ignore[no-untyped-def]
    """Drop any one and a stale replay becomes possible."""
    assert _key() != _key(**{field: value})


def test_changing_the_model_yields_a_different_world(narrated: World) -> None:
    """Explicitly, not silently: a different model is a different corpus."""
    class OtherModel(DeterministicProvider):
        id = "deterministic-fake-2"

    # Same recorded ledger, different model id, so no key hits.
    with pytest.raises(ProviderError):
        fresh().narrate(
            type("Unreachable2", (UnreachableProvider,), {"id": "deterministic-fake-2"})(),
            ledger=narrated.ledger,
        )

    # And generating with it works, producing its own ledger.
    other = fresh().narrate(OtherModel())
    assert {e.model_id for e in other.ledger} == {"deterministic-fake-2"}


def test_correcting_a_fact_invalidates_its_prose(narrated: World) -> None:
    """The fact digest is in the key so a changed figure regenerates, not replays."""
    world = fresh()
    facts = list(world._facts)
    # A group-level figure, because only those reach a narrative section. A
    # category or store revenue fact is in the corpus and on the workbook, but no
    # prose cites it, so corrupting one would change no ledger key and the replay
    # would legitimately succeed.
    index = next(
        i
        for i, f in enumerate(facts)
        if f.value and f.kind.endswith("revenue.actual") and f.subject == world.company.id
    )
    facts[index] = facts[index].model_copy(
        update={"value": facts[index].value.model_copy(update={"amount": 123_456})}
    )
    changed = World(**{**world.__dict__, "_facts": tuple(facts)})

    # Some keys no longer match, so a pure replay cannot serve every call.
    with pytest.raises(ProviderError):
        changed.narrate(UnreachableProvider(), ledger=narrated.ledger)


# ---------------------------------------------------------------------------
# The model references numbers, never restates them
# ---------------------------------------------------------------------------


def test_no_generated_prose_contains_a_bare_number(narrated: World) -> None:
    """The arithmetic rule, checked over the whole corpus."""
    for label, body in prose_of(narrated).items():
        assert not references.bare_numbers(body), f"{label} restated a figure: {body!r}"


def test_every_figure_arrives_by_reference(narrated: World) -> None:
    referenced = [r for body in prose_of(narrated).values() for r in references.referenced(body)]
    assert referenced, "prose that mentions no facts is not carrying any"
    for fact_id in referenced:
        narrated.facts.by_id(fact_id)


def test_substitution_resolves_every_reference_at_render_time(narrated: World) -> None:
    rendered = narrated.render("markdown")
    for item in rendered._rendered:
        if item.media_type != "text/markdown":
            continue
        assert "{{fact:" not in item.text, f"{item.path} shipped an unsubstituted reference"
        assert "[missing " not in item.text, f"{item.path} shipped an unresolvable reference"


def test_a_figure_reads_identically_wherever_it_appears(narrated: World) -> None:
    """Two documents referencing one fact cannot disagree, because neither holds it."""
    facts = {f.id: f for f in narrated.facts}
    revenue = narrated.facts.where(
        kind="financial.revenue.actual", subject=narrated.company.id
    ).one()
    expected = references.render_value(revenue)

    appearances = [
        references.substitute(body, facts)
        for body in prose_of(narrated).values()
        if revenue.id in references.referenced(body)
    ]
    assert appearances, "the group revenue figure should appear somewhere"
    for text in appearances:
        assert expected in text


def test_an_unresolvable_reference_is_left_visible() -> None:
    """A hole you can see beats a document that silently omits a number."""
    assert references.substitute("was {{fact:FACT-9999}}", {}) == "was [missing FACT-9999]"


# ---------------------------------------------------------------------------
# Generation proposes; the deterministic layer decides
# ---------------------------------------------------------------------------


def test_the_validation_loop_actually_rejects() -> None:
    """A loop that has never rejected anything is a pass-through."""
    provider = ViolatingProvider(violations=1)
    world = fresh().narrate(provider)

    _, _, rejected = world._narration
    assert rejected > 0, "the violating provider's first attempt should have been rejected"
    assert provider.calls > len(world.ledger), "a rejection means an extra call"

    for label, body in prose_of(world).items():
        assert not references.bare_numbers(body), f"{label} kept a rejected figure"


def test_giving_up_is_an_error_not_a_silent_pass() -> None:
    with pytest.raises(NarrationError, match="still invalid"):
        fresh().narrate(ViolatingProvider(violations=99), retries=2)


def _request(**overrides) -> NarrativeRequest:  # type: ignore[no-untyped-def]
    base = dict(
        artifact_id="ART-0001", artifact_type="cfo_variance_memo", section="Position",
        persona_id="PERSONA-CFO", voice="plain", audience="group_cfo",
        author_title="Group Financial Controller",
        allowed_fact_ids=["FACT-0001"], required_fact_ids=[],
    )
    return NarrativeRequest(**{**base, **overrides})


def test_a_restated_figure_is_rejected(narrated: World) -> None:
    facts = {f.id: f for f in narrated.facts}
    fact = narrated.facts.first()
    verdict = validate(
        _request(allowed_fact_ids=[fact.id]),
        GeneratedNarrative(
            text="Revenue was 639,100 thousand.",
            claims=[GeneratedClaim(text="Revenue was 639,100 thousand.", supporting_fact_ids=[fact.id])],
        ),
        facts,
    )
    assert not verdict.accepted
    assert any(v.code == "bare_number" for v in verdict.violations)


def test_a_claim_citing_a_fact_it_was_not_given_is_rejected(narrated: World) -> None:
    facts = {f.id: f for f in narrated.facts}
    verdict = validate(
        _request(allowed_fact_ids=["FACT-0001"]),
        GeneratedNarrative(
            text="Something happened.",
            claims=[GeneratedClaim(text="Something happened.", supporting_fact_ids=["FACT-0002"])],
        ),
        facts,
    )
    assert not verdict.accepted
    assert any(v.code == "unsupported_claim" for v in verdict.violations)


def test_omitting_a_required_fact_is_rejected(narrated: World) -> None:
    facts = {f.id: f for f in narrated.facts}
    fact = narrated.facts.first()
    verdict = validate(
        _request(allowed_fact_ids=[fact.id], required_fact_ids=[fact.id]),
        GeneratedNarrative(
            text="Nothing of note.",
            claims=[GeneratedClaim(text="Nothing of note.", supporting_fact_ids=[fact.id])],
        ),
        facts,
    )
    # The claim cites it, so it counts as used — omission means absent from both.
    assert verdict.accepted

    empty = validate(
        _request(allowed_fact_ids=[fact.id], required_fact_ids=[fact.id]),
        GeneratedNarrative(text="Nothing of note.", claims=[]),
        facts,
    )
    assert not empty.accepted
    assert any(v.code == "required_fact_omitted" for v in empty.violations)


def test_citing_something_not_yet_known_is_rejected(narrated: World) -> None:
    facts = {f.id: f for f in narrated.facts}
    fact = narrated.facts.sort_by("valid_from")[-1]
    cutoff = fact.valid_from - timedelta(hours=1)

    verdict = validate(
        _request(allowed_fact_ids=[fact.id], temporal_cutoff=cutoff),
        GeneratedNarrative(
            text=f"The position was {{{{fact:{fact.id}}}}}.",
            claims=[GeneratedClaim(text="The position.", supporting_fact_ids=[fact.id])],
        ),
        facts,
    )
    assert not verdict.accepted
    assert any(v.code == "not_yet_known" for v in verdict.violations)


def test_a_forbidden_claim_is_rejected(narrated: World) -> None:
    facts = {f.id: f for f in narrated.facts}
    fact = narrated.facts.first()
    verdict = validate(
        _request(allowed_fact_ids=[fact.id], forbidden_claims=["root cause"]),
        GeneratedNarrative(
            text="The root cause is understood.",
            claims=[GeneratedClaim(text="The root cause is understood.", supporting_fact_ids=[fact.id])],
        ),
        facts,
    )
    assert not verdict.accepted
    assert any(v.code == "forbidden_claim" for v in verdict.violations)


def test_an_invented_entity_is_rejected(narrated: World) -> None:
    facts = {f.id: f for f in narrated.facts}
    fact = narrated.facts.first()
    verdict = validate(
        _request(allowed_fact_ids=[fact.id]),
        GeneratedNarrative(
            text="Northgate Logistics was responsible.",
            claims=[GeneratedClaim(text="Northgate Logistics was responsible.", supporting_fact_ids=[fact.id])],
        ),
        facts,
        entity_names=frozenset({narrated.company.name}),
    )
    assert not verdict.accepted
    assert any(v.code == "unknown_entity" for v in verdict.violations)


def test_a_claim_must_cite_something() -> None:
    """A claim with no support is invalid, not merely weak."""
    with pytest.raises(ValueError):
        GeneratedClaim(text="Trust me.", supporting_fact_ids=[])


def test_required_facts_must_be_within_the_allowed_set() -> None:
    with pytest.raises(ValueError, match="not in the allowed set"):
        _request(allowed_fact_ids=["FACT-0001"], required_fact_ids=["FACT-0002"])


# ---------------------------------------------------------------------------
# The temporal cut-off does real work
# ---------------------------------------------------------------------------


def test_a_triage_page_reports_the_guess_and_the_rca_reports_the_cause(narrated: World) -> None:
    """The corpus's most important property, now visible in prose.

    Both documents are correct. They disagree because they were written at
    different times, which is exactly what a system reasoning over enterprise
    documents has to cope with.
    """
    hypothesis = narrated.facts.where(kind="ops.cause").superseded().one()
    confirmed = narrated.facts.where(kind="ops.cause").current().one()

    def prose_for(artifact_type: str) -> str:
        intent = narrated.artifact_intents.where(artifact_type=artifact_type).first()
        ir = next(r for r in narrated.artifact_irs if r.intent_id == intent.id)
        return " ".join(s.body for s in ir.sections if s.body)

    triage = prose_for("confluence_page")
    rca = prose_for("incident_rca")

    assert hypothesis.id in references.referenced(triage)
    assert confirmed.id not in references.referenced(triage), (
        "a page written during triage cannot cite a cause confirmed hours later"
    )
    assert confirmed.id in references.referenced(rca)


def test_a_later_document_may_discuss_a_superseded_belief(narrated: World) -> None:
    """Knowability, not currency.

    An RCA is largely *about* a belief that turned out wrong. Testing
    ``holds_at(cutoff)`` would have made that unwritable.
    """
    hypothesis = narrated.facts.where(kind="ops.cause").superseded().one()
    intent = narrated.artifact_intents.where(artifact_type="incident_rca").first()
    ir = next(r for r in narrated.artifact_irs if r.intent_id == intent.id)
    prose = " ".join(s.body for s in ir.sections if s.body)

    assert hypothesis.id in references.referenced(prose)
    assert "later superseded" in prose, "a past belief must read as past, not as current"


def test_no_document_cites_a_fact_from_after_it_was_written(narrated: World) -> None:
    for ir in narrated.artifact_irs:
        manifest = narrated.artifacts.get(ir.id)
        if manifest is None:
            continue
        for section in ir.sections:
            if not section.body:
                continue
            for fact_id in references.referenced(section.body):
                fact = narrated.facts.by_id(fact_id)
                assert fact.valid_from <= manifest.created_at, (
                    f"{ir.id}/{section.heading} cites {fact_id} from its own future"
                )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_narrating_does_not_mutate_the_source() -> None:
    world = fresh().compile()
    world.narrate(DeterministicProvider())
    assert all(s.awaiting_prose or s.table for ir in world.artifact_irs for s in ir.sections)
    assert len(world.ledger) == 0


def test_narration_marks_the_artifact_as_narrated(narrated: World) -> None:
    for ir in narrated.artifact_irs:
        if any(s.body for s in ir.sections):
            assert "awaiting_prose" not in ir.metadata
            assert ir.metadata["narrated_by"] == "deterministic-fake-1"
            assert ir.metadata["prompt_version"] == prompts.SECTION_PROSE.key


def test_sections_partition_the_facts_rather_than_repeating_them(narrated: World) -> None:
    """An outline whose every section says the same thing is not an outline."""
    intent = narrated.artifact_intents.where(artifact_type="cfo_variance_memo").first()
    ir = next(r for r in narrated.artifact_irs if r.intent_id == intent.id)
    bodies = [s.body for s in ir.sections if s.body]

    assert len(bodies) > 1
    assert len(set(bodies)) == len(bodies), "two sections produced identical prose"

    group = next(s for s in ir.sections if s.heading == "Position")
    units = next(s for s in ir.sections if s.heading == "By business unit")
    assert not set(references.referenced(group.body)) & set(references.referenced(units.body))


def test_a_narrated_world_still_validates(narrated: World) -> None:
    report = narrated.render("markdown", "xlsx").validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_narration_needs_something_to_narrate() -> None:
    world = RetailWorld(seed=8128).build()
    with pytest.raises(ValueError, match="run a scenario first"):
        world.narrate(DeterministicProvider())


def test_prompts_are_versioned() -> None:
    assert prompts.versions() == {"section_prose": "2"}
    assert prompts.SECTION_PROSE.key == "section_prose@2"
    with pytest.raises(KeyError, match="unknown prompt"):
        prompts.get("nope")


def test_the_prompt_names_the_facts_and_the_rules(narrated: World) -> None:
    facts = {f.id: f for f in narrated.facts}
    fact = narrated.facts.first()
    text = prompts.SECTION_PROSE.render(_request(allowed_fact_ids=[fact.id]), facts)

    assert fact.id in text
    assert "never write a figure out" in text
    assert "{{fact:ID}}" in text
