"""Tests for the history evaluation families.

Five families over the corpus's own past: who led a business unit at a
moment, who replaced whom, when a founding milestone happened, who signed a
document before versus after a succession, and the abstentions a history
question can trip into once the corpus has one.

Three of the five — org state, succession, milestone provenance — depend on
facts (`org.unit_leader_changed`, `org.departed`, `org.role_changed`,
`lore.milestone`) that `Hire`/`Departure`/`Reorganisation` and
`organisation.generate` mint the moment the event happens, but that nothing
in the pipeline plans a document to require. `validate.py`'s
`unreachable_answer` check rejects a case whose expected facts no artifact
carries, correctly — a fact that cannot be rendered into anything a
retriever could find is not an answerable question. So `generators/
evaluation.py`'s new families check this themselves (`_reachable_fact_ids`)
and stay silent until it holds, which this module tests directly by
building a world both ways: once as the real pipeline leaves it (a
departure that happened but that nothing documents), and once with a
minimal hand-built `ArtifactIntent` bridging that gap — the same technique
`test_lifetimes.py`'s `_chained_intents` uses to exercise a capability nothing
upstream wires up yet, via `World`'s own public `extend`.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.evaluate import score
from worldloom.models import ArtifactIntent, EvaluationType
from worldloom.narrative import DeterministicProvider
from worldloom.scenarios import Departure, Reorganisation

SEED = 8128

#: Substrings that uniquely identify a question from one of the five new
#: families, used instead of tracking ids — the families are additive, so an
#: id would shift as soon as an earlier family grows, and a question's own
#: text does not.
_NEW_FAMILY_MARKERS = (
    "replaced",  # succession
    "Who led ",  # org state
    "own history",  # milestone provenance
    "signed the cfo variance memo",  # authorship over time
    "Marketing Officer",  # history abstention: nonexistent role
    "in 1995",  # history abstention: before the corpus begins
)

#: The families a lexical baseline still has no purchase on. Milestone
#: provenance left this set the day the company timeline landed: its questions
#: quote the milestone's own words and the timeline states those words beside
#: the date, so a keyword retriever passing them is the corpus working, not a
#: regression. What remains genuinely hard is state-at-a-moment — who led,
#: who replaced, who signed *then* — where the right document and the wrong
#: one share all their vocabulary and differ only in validity.
_STILL_HARD_MARKERS = tuple(m for m in _NEW_FAMILY_MARKERS if m != "own history")


def _is_new(case) -> bool:
    return any(marker in case.question for marker in _NEW_FAMILY_MARKERS)


def _history_world() -> World:
    """A controller's departure, and a reorganisation of Food's leadership,
    both landing in the same period — the shape every positive test in this
    module needs: a real succession *and* a real leadership change."""
    world = RetailWorld(seed=SEED).build()
    world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    world = world.run(Departure(period="2026-03", role_key="controller"))
    world = world.run(Reorganisation(period="2026-03", unit_key="food", new_leader_role="food_buyer"))
    return world


def _bridged(world: World) -> World:
    """Attach one intent requiring every org-change fact the world carries.

    Nothing in `scenarios.py` plans a document for a personnel change —
    `Hire`/`Departure`/`Reorganisation` extend the roster and the fact
    ledger but mint no `ArtifactIntent`. That is a gap in what plans
    artifacts, not in what asks questions about them, so it is bridged here
    with the minimum needed to make the fact citable, not fixed upstream.

    Founding milestones used to be bridged here too, and no longer are:
    `planning.artifact_intents` now plans the company timeline that carries
    every `MFACT-`, so bridging them again would just be requiring the same
    facts twice. The bridge is exactly the remaining gap, nothing more.
    """
    org_ids = [f.id for f in world.facts if f.kind.startswith("org.")]
    bridge = ArtifactIntent(
        id="ART-TEST-HISTORY-BRIDGE",
        artifact_type="working_note",
        domain="finance",
        audience="all_staff",
        author_id=world.people[0].id,
        required_fact_ids=org_ids,
    )
    return world.extend(artifact_intents=(bridge,))


@pytest.fixture(scope="module")
def bridged_world() -> World:
    """A departure and a reorganisation, both documented — the corpus the
    new families were designed against."""
    return _bridged(_history_world()).run(MonthEndClose(period="2026-04"))


@pytest.fixture(scope="module")
def undocumented_world() -> World:
    """The same history, left exactly as the real pipeline produces it
    today — nothing bridges the gap. Exercises the reachability guard."""
    return _history_world().run(MonthEndClose(period="2026-04"))


@pytest.fixture(scope="module")
def stable_world() -> World:
    """No departure, no reorganisation — the contrast case."""
    world = RetailWorld(seed=SEED).build()
    world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    return world.run(MonthEndClose(period="2026-04"))


# ---------------------------------------------------------------------------
# 1. Fires only when the world supports it
# ---------------------------------------------------------------------------


def test_a_documented_departure_generates_succession_and_authorship_cases(
    bridged_world: World,
) -> None:
    assert any("replaced" in c.question for c in bridged_world.evaluations)
    assert any(
        c.evaluation_type is EvaluationType.TEMPORAL_STATE and "signed the cfo variance memo" in c.question
        for c in bridged_world.evaluations
    )


def test_no_departure_generates_neither(stable_world: World) -> None:
    assert not any("replaced" in c.question for c in stable_world.evaluations)
    assert not any("signed the cfo variance memo" in c.question for c in stable_world.evaluations)
    assert not any(c.question.startswith("Who led ") for c in stable_world.evaluations)


def test_a_departure_is_documented_and_therefore_askable(
    undocumented_world: World,
) -> None:
    """The event happening and the event being *citable* are two different facts.

    This test previously asserted the opposite — that `succession` and
    `org_state_over_time` must stay silent, because a real `Departure` minted
    real facts and nothing planned a document requiring them. That was an
    accurate description of a defect, not a property worth keeping: a corpus
    with a history no document records is coherent and unaskable, which is the
    same as the history not existing. `Departure` now issues a personnel notice,
    which is the document a company actually produces when somebody leaves and
    the only one naming both the leaver and the successor.

    The fixture name is kept: what it builds is a world nobody hand-bridged, and
    the point is that it no longer needs bridging.
    """
    questions = [c.question for c in undocumented_world.evaluations]
    assert any("replaced" in q for q in questions), "no succession question was posed"
    assert any(q.startswith("Who led ") for q in questions), "no org-state question was posed"
    assert any("signed the cfo variance memo" in q for q in questions)
    assert undocumented_world.validate().ok


# ---------------------------------------------------------------------------
# 2. Every case is grounded, and holds at its cut-off
# ---------------------------------------------------------------------------


def test_every_case_is_grounded_and_holds_at_its_cutoff(bridged_world: World) -> None:
    for case in bridged_world.evaluations:
        if case.expects_abstention:
            continue
        for fact_id in case.expected_fact_ids:
            fact = bridged_world.facts.by_id(fact_id)  # raises if the id does not exist
            if case.temporal_cutoff is not None:
                assert fact.holds_at(case.temporal_cutoff), (case.id, fact_id, case.temporal_cutoff)


# ---------------------------------------------------------------------------
# 3. Milestone provenance cites MFACT ids carrying lore_ids
# ---------------------------------------------------------------------------


def test_milestone_provenance_cites_mfact_ids_with_lore(bridged_world: World) -> None:
    milestone_cases = [c for c in bridged_world.evaluations if "own history" in c.question]
    # One per dated lore commitment — `retail.lore()` states five.
    assert len(milestone_cases) == 5
    for case in milestone_cases:
        assert case.evaluation_type is EvaluationType.CITATION_REQUIRED
        assert case.expected_fact_ids
        for fact_id in case.expected_fact_ids:
            assert fact_id.startswith("MFACT-"), fact_id
            fact = bridged_world.facts.by_id(fact_id)
            assert fact.lore_ids, f"{fact_id} carries no lore_ids"


# ---------------------------------------------------------------------------
# 4. History abstentions are unanswerable by construction
# ---------------------------------------------------------------------------


def test_history_abstentions_are_unanswerable_by_construction(bridged_world: World) -> None:
    cmo_case = next(c for c in bridged_world.evaluations if "Marketing Officer" in c.question)
    assert cmo_case.expects_abstention
    assert not cmo_case.expected_fact_ids
    # No fact in the world could answer it: no modelled function or title
    # names marketing, at any world size — the archetype's role table simply
    # never includes one.
    assert not any(
        "marketing" in p.function.casefold() or "marketing" in p.title.casefold()
        for p in bridged_world.people
    )

    old_case = next(c for c in bridged_world.evaluations if "in 1995" in c.question)
    assert old_case.expects_abstention
    assert not old_case.expected_fact_ids
    # No employee's `joined` can fall this early — `organisation._joined_date`'s
    # tenure ceiling is fixed regardless of seed, so this is false by
    # construction rather than by this particular world's roster.
    assert all(p.joined is None or p.joined.year > 1995 for p in bridged_world.people)


# ---------------------------------------------------------------------------
# 5. validate() accepts a documented history, with the new cases live
# ---------------------------------------------------------------------------


def test_validate_accepts_a_documented_multi_period_history(bridged_world: World) -> None:
    report = bridged_world.validate()
    assert report.ok, report.violations
    assert any("replaced" in c.question for c in bridged_world.evaluations)
    assert any(c.question.startswith("Who led ") for c in bridged_world.evaluations)
    assert any("own history" in c.question for c in bridged_world.evaluations)


# ---------------------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------------------


def test_same_seed_same_cases_same_ids(bridged_world: World) -> None:
    rebuilt = _bridged(_history_world()).run(MonthEndClose(period="2026-04"))
    assert [c.id for c in rebuilt.evaluations] == [c.id for c in bridged_world.evaluations]
    assert list(rebuilt.evaluations) == list(bridged_world.evaluations)


# ---------------------------------------------------------------------------
# 7. The baseline should do badly on these
# ---------------------------------------------------------------------------


def test_the_baseline_does_badly_on_the_new_families(bridged_world: World) -> None:
    """A keyword retriever with no notion of a validity window should not be
    able to say who led Food in March, who replaced the controller, or when
    the checkout stack was replatformed — none of that is stated in any
    close document, and BM25 has no concept of "the record for this
    specific moment" versus "a page that happens to share vocabulary".

    Measured (not assumed) at 2 of 13 passing — both from the
    authorship-over-time pair, whose passages are literally titled "CFO
    Variance Memo" and so let BM25 correctly separate the two periods' own
    documents even though it has no notion of authorship at all. Every org
    state, succession, milestone-provenance, and history-abstention case
    fails. The bound below leaves headroom for run-to-run noise in exactly
    which of the two easy cases pass without hiding a real regression if the
    corpus gets meaningfully easier.
    """
    scored = bridged_world.narrate(DeterministicProvider()).render("markdown")
    card = score(scored)

    by_case = {c.id: c for c in scored.evaluations}

    def outcomes_for(marker: str):  # type: ignore[no-untyped-def]
        found = [o for o in card.outcomes if marker in by_case[o.case_id].question]
        assert found, f"no case for marker {marker!r}"
        return found

    # The claims are per family, not a blended pass rate — a blend let one
    # family quietly flip from impossible to trivial while the average stayed
    # respectable, which is exactly what happened when the timeline landed.
    #
    # State-at-a-moment must fail: the right document and the wrong one share
    # all their vocabulary and differ only in validity, which BM25 cannot see.
    for outcome in outcomes_for("Who led "):
        assert not outcome.passed, "an org-state case passed — the moment question got easy"
    # An abstention must fail against every baseline: a lexical retriever
    # always returns *something*, and something is the wrong answer here.
    for marker in ("Marketing Officer", "in 1995"):
        for outcome in outcomes_for(marker):
            assert not outcome.passed, f"an abstention case passed ({marker})"
    # Succession and authorship may pass — their evidence documents name the
    # people involved, and finding those documents is retrieval working, not a
    # hole. No assertion either way: their pass/fail is corpus-shape noise.

    # Milestone provenance is the deliberate exception: the timeline document
    # states each milestone in the question's own words, dated, so the lexical
    # baseline is *expected* to find it. Zero here would mean the timeline
    # regressed out of the index, which is the defect this family spent its
    # whole life in.
    milestone_ids = {c.id for c in scored.evaluations if "own history" in c.question}
    assert milestone_ids, "the milestone family must mint against the real pipeline"
    milestone_passed = sum(1 for o in card.outcomes if o.case_id in milestone_ids and o.passed)
    assert milestone_passed > 0, (
        "the baseline found no milestone at all — the company timeline is not reaching"
        " the retrieval index"
    )
