"""Gate A step 3: the generators are deterministic and cannot produce nonsense.

The exit gate has two halves. The same seed must reproduce a world exactly, and
*any* seed must produce a coherent one. The second is the harder claim, so it is
tested as a property over many seeds rather than on one happy path.
"""

from __future__ import annotations

import pytest

from worldloom import Authority, EvaluationType, World
from worldloom.retail import BASE_INCIDENT_LIKELIHOOD, MonthEndClose, RetailWorld
from worldloom.scenarios import likelihood_multiplier

PERIOD = "2026-03"


def build(seed: int, *, incident: bool | None = True, period: str = PERIOD) -> World:
    return RetailWorld(seed=seed).build().run(
        MonthEndClose(period=period, include_operational_incident=incident)
    )


def snapshot(world: World) -> tuple:
    """Everything a seed is supposed to determine."""
    return (
        world.company.model_dump(mode="json"),
        tuple(p.model_dump(mode="json") for p in world.people),
        tuple(s.model_dump(mode="json") for s in world.services),
        tuple(f.model_dump(mode="json") for f in world.facts),
        tuple(e.model_dump(mode="json") for e in world.events),
        tuple(i.model_dump(mode="json") for i in world.artifact_intents),
        tuple(c.model_dump(mode="json") for c in world.evaluations),
    )


@pytest.fixture(scope="module")
def world() -> World:
    return build(8128)


# -- the exit gate -----------------------------------------------------------


def test_the_same_seed_reproduces_the_world_exactly(world: World) -> None:
    assert snapshot(build(8128)) == snapshot(world)


def test_a_different_seed_produces_a_different_world(world: World) -> None:
    other = build(9001)
    assert snapshot(other) != snapshot(world)
    assert other.company.name != world.company.name


@pytest.mark.parametrize("seed", range(1, 31))
def test_every_seed_produces_a_coherent_world(seed: int) -> None:
    """The property that matters: no seed can generate an incoherent corpus."""
    report = build(seed, incident=None).validate()
    assert report.ok, f"seed {seed}:\n" + "\n".join(str(v) for v in report.violations)


@pytest.mark.parametrize("seed", [3, 17, 42, 8128, 99_991])
def test_invariants_hold_whatever_the_seed_changes(seed: int) -> None:
    generated = build(seed)
    company = generated.company.id

    # Units sum to group, on both measures.
    for kind in ("financial.revenue.actual", "financial.gross_profit.actual"):
        units = generated.facts.where(kind=kind).filter(lambda f: f.subject.startswith("BU-"))
        group = generated.facts.where(kind=kind, subject=company).one()
        assert sum(f.value.amount for f in units) == group.value.amount

    # Variance is a difference, never an independent draw.
    for stem in ("financial.revenue", "financial.gross_profit"):
        for subject in (*[u.id for u in generated.business_units], company):
            actual = generated.facts.where(kind=f"{stem}.actual", subject=subject).one()
            budget = generated.facts.where(kind=f"{stem}.budget", subject=subject).one()
            variance = generated.facts.where(kind=f"{stem}.variance", subject=subject).one()
            assert variance.value.amount == actual.value.amount - budget.value.amount

    # Percentages match the amounts they describe.
    for subject in (*[u.id for u in generated.business_units], company):
        profit = generated.facts.where(kind="financial.gross_profit.actual", subject=subject).one()
        revenue = generated.facts.where(kind="financial.revenue.actual", subject=subject).one()
        stated = generated.facts.where(kind="financial.gross_margin_pct.actual", subject=subject).one()
        assert abs(profit.value.amount / revenue.value.amount * 100 - stated.value.amount) < 0.01


# -- determinism mechanics ---------------------------------------------------


def test_streams_are_independent_of_each_other(world: World) -> None:
    """Deriving a stream by name, not by draw order.

    If generators shared one stream, an extra draw in one would shift every value
    in the others and a seed would stop meaning anything across versions.
    """
    from worldloom.rng import Rng

    root = Rng(8128)
    finance_first = [root.derive("finance").integer(0, 10_000) for _ in range(3)]
    root_again = Rng(8128)
    root_again.derive("organisation").integer(0, 10_000)  # burn draws elsewhere
    finance_after = [root_again.derive("finance").integer(0, 10_000) for _ in range(3)]
    assert finance_first == finance_after


def test_ids_are_minted_in_a_stable_order(world: World) -> None:
    assert world.people.ids() == sorted(world.people.ids())
    assert world.facts.ids()[0] == "FACT-0001"
    assert world.company.id == "CO-0001"


def test_building_does_no_scenario_work() -> None:
    """Lazy: constructing and building yields an organisation, not an episode."""
    base = RetailWorld(seed=8128).build()
    assert len(base.people) > 0
    assert len(base.events) == 0
    assert len(base.facts) == 0
    assert len(base.evaluations) == 0


def test_running_a_scenario_does_not_mutate_the_source() -> None:
    base = RetailWorld(seed=8128).build()
    first = base.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    assert len(base.facts) == 0, "the built world must be untouched"
    assert len(first.facts) > 0


def test_a_loaded_corpus_cannot_be_advanced() -> None:
    """A corpus is a result. Advancing it needs a rebuild from its seed."""
    loaded = World.load("retail-close")
    with pytest.raises(ValueError, match="cannot be advanced"):
        loaded.run(MonthEndClose(period="2026-04"))


# -- lore drives generation --------------------------------------------------


def test_lore_raises_the_incident_likelihood(world: World) -> None:
    """Not decoration: the 2024 mapping decision is why closes go wrong."""
    multiplier = likelihood_multiplier(world, "data_quality_incident/inventory")
    assert multiplier == 2.5
    assert BASE_INCIDENT_LIKELIHOOD * multiplier > BASE_INCIDENT_LIKELIHOOD


def test_incidents_happen_sometimes_and_not_always() -> None:
    """A corpus where every period is a crisis is not a realistic one."""
    outcomes = [bool(build(seed, incident=None).facts.superseded()) for seed in range(1, 41)]
    assert 5 <= sum(outcomes) <= 35, f"incident rate looks degenerate: {sum(outcomes)}/40"


def test_lore_attaches_traits_to_individuals_not_to_personas(world: World) -> None:
    """A commitment that makes one manager defensive must not make everyone defensive."""
    marked = [person for person in world.people if person.traits]
    assert marked, "persona_trait constraints should reach someone"

    merch_lead = next(p for p in marked if p.title == "Head of Merchandising Systems")
    assert merch_lead.traits["defensive_about_ownership"] == 0.3

    peers = world.people.where(persona_id=merch_lead.persona_id).filter(
        lambda p: p.id != merch_lead.id
    )
    for peer in peers:
        assert "defensive_about_ownership" not in peer.traits


def test_generated_facts_cite_the_lore_that_shaped_them(world: World) -> None:
    cause = world.facts.where(kind="ops.cause").current().one()
    assert cause.lore_ids, "the confirmed cause should cite the mapping decision"

    lore_kinds = {world.lore.by_id(lid).kind.value for lid in cause.lore_ids}
    assert "decision" in lore_kinds


def test_a_close_without_an_incident_gets_no_rca() -> None:
    """The artifact plan follows the episode, not a template."""
    quiet = build(8128, incident=False)
    types = {intent.artifact_type for intent in quiet.artifact_intents}
    assert "incident_rca" not in types
    assert "finance_workbook" in types

    noisy = build(8128, incident=True)
    assert "incident_rca" in {intent.artifact_type for intent in noisy.artifact_intents}
    assert len(noisy.artifact_intents) > len(quiet.artifact_intents)


# -- the supersession chain --------------------------------------------------


def test_the_wrong_first_answer_is_generated_and_then_superseded(world: World) -> None:
    causes = world.facts.where(kind="ops.cause")
    assert len(causes) == 2

    hypothesis = causes.superseded().one()
    confirmed = causes.current().one()

    assert hypothesis.authority is Authority.INITIAL_HYPOTHESIS
    assert confirmed.authority is Authority.CONFIRMED
    assert confirmed.supersedes == hypothesis.id
    assert hypothesis.valid_to == confirmed.valid_from or hypothesis.valid_to < confirmed.valid_from


def test_a_cutoff_inside_the_hypothesis_window_returns_the_wrong_answer(world: World) -> None:
    hypothesis = world.facts.where(kind="ops.cause").superseded().one()
    midpoint = hypothesis.valid_from + (hypothesis.valid_to - hypothesis.valid_from) / 2

    held = world.as_of(midpoint).where(kind="ops.cause").one()
    assert held.id == hypothesis.id
    assert world.authoritative("ops.cause", held.subject).id != hypothesis.id


def test_close_status_is_superseded_not_overwritten(world: World) -> None:
    statuses = world.facts.where(kind="close.status")
    assert {s.text_value for s in statuses} == {"delayed", "final"}
    assert statuses.current().one().text_value == "final"


# -- generated evaluations ---------------------------------------------------


def test_answers_are_read_from_facts_not_invented(world: World) -> None:
    for case in world.evaluations:
        if case.expects_abstention:
            assert not case.expected_fact_ids
            continue
        assert case.expected_fact_ids
        for fact_id in case.expected_fact_ids:
            world.facts.by_id(fact_id)  # raises if the answer is ungrounded


def test_expected_answers_name_things_a_reader_would_recognise(world: World) -> None:
    """An expected answer citing 'BU-0001' cannot be graded against prose."""
    unit_case = world.evaluations.filter(
        lambda c: "largest revenue variance" in c.question
    ).one()
    unit_names = {unit.name for unit in world.business_units}
    assert any(name in unit_case.expected_answer for name in unit_names)
    assert "BU-" not in unit_case.expected_answer


def test_abstention_cases_are_generated_too(world: World) -> None:
    abstentions = world.evaluations.where(expects_abstention=True)
    assert len(abstentions) >= 3
    for case in abstentions:
        assert case.evaluation_type is EvaluationType.EXPECTED_ABSTENTION


def test_a_temporal_case_is_answerable_at_its_own_cutoff(world: World) -> None:
    for case in world.evaluations:
        if case.temporal_cutoff is None:
            continue
        for fact_id in case.expected_fact_ids:
            assert world.facts.by_id(fact_id).holds_at(case.temporal_cutoff)


# -- planning and round trip -------------------------------------------------


def test_a_generated_world_plans_artifacts_but_renders_none(world: World) -> None:
    """Bodies are step 5, prose is step 6. Step 3 stops at the plan."""
    assert len(world.artifact_intents) > 0
    assert len(world.artifacts) == 0
    assert len(world.ledger) == 0, "no generative calls have been made"


def test_every_planned_artifact_has_an_eligible_author(world: World) -> None:
    for intent in world.artifact_intents:
        world.people.by_id(intent.author_id)


def test_every_persona_is_used_by_someone(world: World) -> None:
    """An unused persona is a modelling gap, not a spare part."""
    assigned = {person.persona_id for person in world.people}
    assert not set(world.personas.ids()) - assigned


def test_a_generated_world_is_a_clean_corpus(world: World) -> None:
    """Two modes, and step 3 only produces the first.

    Deliberate mess is step 11, and mixing it in earlier makes every coherence
    bug indistinguishable from a feature. The hand-authored episode is the
    realistic corpus; a generated one is clean.
    """
    assert len(world.inconsistencies()) == 0
    assert len(World.load("retail-close").inconsistencies()) > 0


def test_the_generated_org_matches_the_fixture_in_shape(world: World) -> None:
    """Structural equivalence, not byte equality.

    The generator is not asked to reproduce hand-authored names — that would
    encode arbitrary authored choices to satisfy a test. It is asked to produce
    the same kind of world.
    """
    fixture = World.load("retail-close")
    assert len(world.business_units) == len(fixture.business_units)
    assert len(world.systems) == len(fixture.systems)
    assert len(world.services) == len(fixture.services)
    assert len(world.lore) == len(fixture.lore)
    assert world.company.name != fixture.company.name

    # Headcount is a floor, not an equality: the generator mints a role table the
    # fixture predates — every unit now has a head of buying, because a category
    # P&L needs someone accountable for a category. The fixture's roles must all
    # still be there, which is what "same kind of world" means.
    assert len(world.people) >= len(fixture.people)
    assert {p.function for p in fixture.people} <= {p.function for p in world.people}


def test_a_generated_world_round_trips(world: World, tmp_path) -> None:
    destination = world.export(tmp_path / "generated")
    reloaded = World.load(destination)

    assert reloaded.facts.ids() == world.facts.ids()
    assert reloaded.artifact_intents.ids() == world.artifact_intents.ids()
    assert reloaded.evaluations.ids() == world.evaluations.ids()
    assert reloaded.seed == 8128
    assert reloaded.validate().ok


def test_multiple_periods_accumulate_without_colliding() -> None:
    """Append-only: a second close adds to the ledger, it does not replace it."""
    base = RetailWorld(seed=8128).build()
    march = base.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    april = march.run(MonthEndClose(period="2026-04", include_operational_incident=False))

    assert len(april.facts) > len(march.facts)
    assert len(set(april.facts.ids())) == len(april.facts), "IDs must stay unique across periods"
    assert april.period == "2026-04"
    assert april.validate().ok

    periods = {f.period for f in april.facts if f.period}
    assert periods == {"2026-03", "2026-04"}
