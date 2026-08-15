"""Gate A tests: the golden episode is coherent, and it round-trips."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from worldloom import Authority, World
from worldloom.corpus import CorpusError


@pytest.fixture(scope="module")
def world() -> World:
    return World.load("retail-close")


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# -- Gate A: coherence -------------------------------------------------------


def test_golden_episode_is_coherent(world: World) -> None:
    """The exit gate for Gate A. Every other test is detail."""
    report = world.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)
    assert report.checks_run > 500, "validator should be doing real work"


def test_fixture_has_the_shape_the_build_order_specifies(world: World) -> None:
    assert len(world.business_units) == 3
    assert len(world.people) == 20
    assert len(world.systems) == 5
    assert len(world.services) == 4
    assert len(world.cost_centres) == 2
    assert 3 <= len(world.lore) <= 6
    assert 10 <= len(world.events) <= 15
    assert 8 <= len(world.artifacts) <= 12
    assert 20 <= len(world.evaluations) <= 30


def test_no_llm_was_involved(world: World) -> None:
    """Step 1 is hand-authored. An empty generation ledger is the proof."""
    assert len(world.ledger) == 0


# -- Financial reconciliation ------------------------------------------------


def test_business_unit_revenue_sums_to_group(world: World) -> None:
    units = world.facts.where(kind="financial.revenue.actual").filter(
        lambda f: f.subject.startswith("BU-")
    )
    group = world.facts.where(kind="financial.revenue.actual", subject="CO-0001").one()
    assert sum(f.value.amount for f in units) == group.value.amount == 630_000


def test_variance_equals_actual_less_budget(world: World) -> None:
    for subject in ("BU-FOOD", "BU-GM", "BU-DIGITAL", "CO-0001"):
        actual = world.facts.where(kind="financial.revenue.actual", subject=subject).one()
        budget = world.facts.where(kind="financial.revenue.budget", subject=subject).one()
        variance = world.facts.where(kind="financial.revenue.variance", subject=subject).one()
        assert variance.value.amount == actual.value.amount - budget.value.amount


def test_a_broken_total_is_caught(world: World) -> None:
    """The reconciliation check must actually fail on bad data.

    A validator that cannot fail is decoration, so corrupt a total and confirm
    the corpus stops being coherent.
    """
    facts = list(world._facts)
    index = next(i for i, f in enumerate(facts) if f.id == "FACT-0004")
    facts[index] = facts[index].model_copy(
        update={"value": facts[index].value.model_copy(update={"amount": 999_999})}
    )
    broken = World(**{**world.__dict__, "_facts": tuple(facts)})

    report = broken.validate()
    assert not report.ok
    codes = {v.code for v in report.violations}
    assert "does_not_reconcile" in codes
    assert "variance_mismatch" in codes


# -- Temporal behaviour ------------------------------------------------------


def test_supersession_preserves_both_states(world: World) -> None:
    hypothesis = world.facts.by_id("FACT-0041")
    confirmed = world.facts.by_id("FACT-0043")

    assert hypothesis.authority is Authority.INITIAL_HYPOTHESIS
    assert confirmed.authority is Authority.CONFIRMED
    assert confirmed.supersedes == hypothesis.id
    assert hypothesis.is_superseded and not confirmed.is_superseded


def test_the_same_question_has_different_answers_at_different_cutoffs(world: World) -> None:
    """The property that makes a temporal cut-off meaningful."""
    at_ten = world.as_of(utc("2026-04-01T10:00:00")).where(kind="ops.cause").one()
    at_two = world.as_of(utc("2026-04-01T14:00:00")).where(kind="ops.cause").one()

    assert at_ten.text_value == "Overnight Helios ERP outage"
    assert "hierarchy mapping" in at_two.text_value
    assert at_ten.id != at_two.id


def test_close_status_resolves_by_authority_and_time(world: World) -> None:
    assert world.as_of(utc("2026-04-02T12:00:00")).where(kind="close.status").one().text_value == "delayed"
    assert world.authoritative("close.status", "CO-0001", period="2026-03").text_value == "final"


def test_no_artifact_cites_a_fact_from_its_own_future(world: World) -> None:
    for artifact in world.artifacts:
        for fact_id in artifact.supporting_fact_ids:
            fact = world.facts.by_id(fact_id)
            assert fact.valid_from <= artifact.created_at, f"{artifact.id} cites future {fact_id}"


# -- Lore --------------------------------------------------------------------


def test_every_lore_commitment_constrains_something(world: World) -> None:
    """Consequence density, the first acceptance metric from docs/lore.md."""
    for commitment in world.lore:
        assert commitment.constrains, f"{commitment.id} is decoration"


def test_the_episode_explains_itself_through_lore(world: World) -> None:
    """The stale mapping is a consequence, not authorial fiat."""
    cause = world.facts.by_id("FACT-0043")
    assert "LORE-0001" in cause.lore_ids

    restructure = world.lore.by_id("LORE-0001")
    assert "LORE-0002" in restructure.scars
    assert any(c.kind.value == "event_likelihood" for c in restructure.constrains)


# -- Provenance and access ---------------------------------------------------


def test_provenance_runs_in_both_directions(world: World) -> None:
    workbook = world.provenance("ART-XLSX-001")
    assert "ART-CFO-001" in workbook["children"]

    memo = world.provenance("ART-CFO-001")
    assert memo["parents"] == ["ART-XLSX-001"]
    assert "ART-EXEC-001" in memo["children"]


def test_labelled_imperfections_are_traceable(world: World) -> None:
    omission = world.inconsistencies().where(artifact_id="ART-EXEC-001").first()
    assert omission is not None
    assert omission.canonical_fact_id == "FACT-0049"
    assert omission.detectable


def test_permissions_partition_the_corpus_by_function(world: World) -> None:
    analyst = world.visible_to("PERSON-0015").ids()  # service desk
    controller = world.visible_to("PERSON-0007").ids()  # group financial controller
    cfo = world.visible_to("PERSON-0002").ids()

    # Service operations sees the incident trail but no financials or board material.
    assert "ART-SNOW-001" in analyst and "ART-RCA-001" in analyst
    assert "ART-XLSX-001" not in analyst
    assert "ART-EXEC-001" not in analyst

    # Finance sees the numbers but not the technology-only knowledge base.
    assert "ART-XLSX-001" in controller and "ART-CFO-001" in controller
    assert "ART-KB-001" not in controller

    # Everyone sees all-staff pages.
    assert "ART-CONF-001" in analyst and "ART-CONF-001" in controller

    # And an author can always see what they wrote.
    assert "ART-EXEC-001" in cfo


def test_every_author_can_see_their_own_artifact(world: World) -> None:
    """A policy written in terms of function can accidentally exclude the author."""
    for artifact in world.artifacts:
        visible = world.visible_to(artifact.author_id).ids()
        assert artifact.id in visible, f"{artifact.author_id} cannot see {artifact.id}"


# -- Evaluation set ----------------------------------------------------------


def test_every_answer_is_derived_from_facts_not_invented(world: World) -> None:
    for case in world.evaluations:
        if case.expects_abstention:
            assert not case.expected_fact_ids
        else:
            assert case.expected_fact_ids, f"{case.id} has no grounding"


def test_every_cited_fact_is_reachable_from_an_artifact(world: World) -> None:
    for case in world.evaluations:
        for fact_id in case.expected_fact_ids:
            assert world.artifacts.citing(fact_id), f"{case.id}: {fact_id} is in no artifact"


def test_all_eight_question_types_are_exercised(world: World) -> None:
    from worldloom import EvaluationType

    present = {case.evaluation_type for case in world.evaluations}
    assert present == set(EvaluationType)


def test_abstention_cases_exist_and_are_ungrounded(world: World) -> None:
    abstentions = world.evaluations.where(expects_abstention=True)
    assert len(abstentions) >= 3
    for case in abstentions:
        assert not case.required_artifact_ids


# -- Round trip --------------------------------------------------------------


def test_export_round_trips_without_loss(world: World, tmp_path) -> None:
    destination = world.export(tmp_path / "out")
    reloaded = World.load(destination)

    assert reloaded.company == world.company
    assert reloaded.facts.ids() == world.facts.ids()
    assert reloaded.events.ids() == world.events.ids()
    assert reloaded.artifacts.ids() == world.artifacts.ids()
    assert reloaded.evaluations.ids() == world.evaluations.ids()
    assert reloaded.lore.ids() == world.lore.ids()
    assert reloaded.intentional_errors.ids() == world.intentional_errors.ids()
    assert reloaded.people.ids() == world.people.ids()
    assert reloaded.validate().ok


def test_export_refuses_to_clobber_by_default(world: World, tmp_path) -> None:
    destination = tmp_path / "out"
    world.export(destination)
    with pytest.raises(FileExistsError):
        world.export(destination)
    world.export(destination, overwrite=True)  # explicit is fine


def test_loading_something_that_is_not_a_corpus_is_a_clear_error() -> None:
    with pytest.raises(CorpusError, match="no corpus at"):
        World.load("no-such-world")
