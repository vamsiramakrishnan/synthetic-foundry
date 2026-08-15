"""Noise, and the invariant that makes it safe: `build --distractors`.

A distractor is supposed to make retrieval harder without making the corpus
lie or making a question unanswerable. That is not a property you can eyeball
from a handful of examples, so this file states it structurally and checks it
on every distractor a real build produces, not on a couple of hand-picked
ones.

The central claim, proved three different ways below: **a distractor can never
become the only passage carrying an evaluation case's expected fact, and can
never make an ``expected_abstention`` case answerable.**

1. ``test_distractors_never_add_facts`` — the generator only ever rearranges
   which *documents* exist; the fact ledger itself (`world._facts`) is
   byte-for-byte unchanged. An abstention case is unanswerable because a fact
   is simply not in the ledger; if the ledger cannot grow, no distractor can
   ever manufacture an answer to one.
2. ``test_every_distractor_fact_is_a_subset_of_a_real_document`` — every fact
   a superseded draft or a derived copy cites was already required by the real
   document it drafts or copies, by construction (`_superseded_draft` and
   `_derived_copy` both slice `final.required_fact_ids`). A routine notice's
   facts are checked against the wider pool independently.
3. ``test_removing_every_distractor_answers_every_case_the_same_way`` — the
   direct version of the claim: for every non-abstention evaluation case, the
   facts it needs are still reachable through the artifact intents that are
   *not* distractors, with every distractor intent deleted from the plan.
"""

from __future__ import annotations

import pytest

from worldloom import (
    BankingWorld,
    MonthEndClose,
    QuarterlyCapitalReturn,
    RetailWorld,
    World,
)
from worldloom.generators import distractors
from worldloom.models import ArtifactIntent, Lifecycle


def _retail_before() -> World:
    return (
        RetailWorld(seed=8128)
        .build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True))
    )


def _banking_before() -> World:
    return BankingWorld(seed=8128).build().run(QuarterlyCapitalReturn(period="2026-03"))


@pytest.fixture(scope="module")
def before() -> World:
    return _retail_before()


@pytest.fixture(scope="module")
def after(before: World) -> World:
    return distractors.apply(before, count=20)


def _distractor_ids(before: World, after: World) -> set[str]:
    """The ids `apply` minted, as opposed to the ids of a real document it
    only attached a `revises` edge to. See `World.extend`'s note on why
    `artifact_intents` merges by id: a superseded draft's final keeps its
    original id, so anything with an id `before` never had is new noise."""
    return {i.id for i in after.artifact_intents} - {i.id for i in before.artifact_intents}


# ---------------------------------------------------------------------------
# 0: the flag is a no-op below one
# ---------------------------------------------------------------------------


def test_zero_distractors_is_a_complete_no_op(before: World) -> None:
    untouched = distractors.apply(before, count=0)
    assert untouched.artifact_intents == before.artifact_intents
    assert untouched.recipe == before.recipe


def test_negative_distractors_is_also_a_no_op(before: World) -> None:
    untouched = distractors.apply(before, count=-3)
    assert untouched.artifact_intents == before.artifact_intents


# ---------------------------------------------------------------------------
# 1: no new fact, ever — the abstention guarantee
# ---------------------------------------------------------------------------


def test_distractors_never_add_facts(before: World, after: World) -> None:
    """If the ledger cannot grow, an `expected_abstention` case cannot be
    answered by anything this module produces — the fact it would need simply
    is not there, exactly as it was not there before distractors ran."""
    assert after._facts == before._facts


def test_distractors_invent_no_entity(before: World, after: World) -> None:
    for collection in ("_people", "_business_units", "_systems", "_services",
                       "_categories", "_sites", "_cost_centres", "_events"):
        assert getattr(after, collection) == getattr(before, collection), collection


# ---------------------------------------------------------------------------
# 2: every distractor fact is already carried by a real document
# ---------------------------------------------------------------------------


def _finals(before: World, after: World) -> dict[str, ArtifactIntent]:
    """id -> the (possibly revised) intent, for everything `before` already had."""
    return {i.id: i for i in after.artifact_intents if i.id in {b.id for b in before.artifact_intents}}


def test_every_distractor_fact_is_a_subset_of_a_real_document(before: World, after: World) -> None:
    noise = _distractor_ids(before, after)
    assert noise, "the fixture should have minted at least one distractor"
    finals = _finals(before, after)
    by_id = {i.id: i for i in after.artifact_intents}
    real_fact_pool = {
        fact_id
        for intent in after.artifact_intents
        if intent.id not in noise
        for fact_id in intent.required_fact_ids
    }

    for distractor_id in noise:
        distractor = by_id[distractor_id]
        if distractor.derived_from:
            # Family (b): a derived personal copy. Its parent must be a real,
            # non-distractor document, and every fact it cites must already be
            # required by that parent.
            parent_id = distractor.derived_from[0]
            assert parent_id not in noise, f"{distractor_id} copies another distractor, not a real document"
            parent = finals[parent_id]
            assert set(distractor.required_fact_ids) <= set(parent.required_fact_ids)
        elif distractor.artifact_type == "routine_notice":
            # Family (c): every cited fact is reachable via some real document.
            assert set(distractor.required_fact_ids) <= real_fact_pool
        else:
            # Family (a): a superseded draft. Some real, revised final must
            # point `revises` back at it, and the draft's facts must be a
            # strict subset of that final's.
            revising = [f for f in finals.values() if f.revises == distractor_id]
            assert len(revising) == 1, f"{distractor_id} should be revised by exactly one real document"
            final = revising[0]
            assert set(distractor.required_fact_ids) < set(final.required_fact_ids)
            assert distractor.size_profile == final.size_profile, (
                "a draft has fewer facts, not a smaller document grammar;"
                " relabelling a long RCA as small makes its required sections"
                " impossible to compose"
            )


# ---------------------------------------------------------------------------
# 3: deleting every distractor changes no evaluation case's answerability
# ---------------------------------------------------------------------------


def test_removing_every_distractor_answers_every_case_the_same_way(before: World, after: World) -> None:
    """The direct statement of the grading-safety invariant: strip every
    distractor intent back out, and every non-abstention case the corpus asks
    is still answerable from what remains. A distractor is additive noise —
    removing it must not remove an answer, which is the same thing as saying
    it was never the *only* carrier of one.
    """
    world = after.compile()
    noise = _distractor_ids(before, after)
    assert noise

    reachable_with_noise = {
        fact_id
        for intent in world.artifact_intents
        for fact_id in intent.required_fact_ids
    }
    reachable_without_noise = {
        fact_id
        for intent in world.artifact_intents
        if intent.id not in noise
        for fact_id in intent.required_fact_ids
    }
    assert reachable_with_noise == reachable_without_noise, (
        "a distractor cited a fact no real document also carries — that fact "
        "would stop being reachable if the distractor were removed, which is "
        "exactly the ONLY-carrier failure this generator must not produce"
    )

    for case in world.evaluations:
        if case.expects_abstention:
            continue
        assert set(case.expected_fact_ids) <= reachable_without_noise, (
            f"{case.id} would become unanswerable without its distractors"
        )


# ---------------------------------------------------------------------------
# 4: relationships point the right way, and the corpus still agrees with itself
# ---------------------------------------------------------------------------


def test_superseded_drafts_are_marked_superseded_after_compile(before: World, after: World) -> None:
    world = after.compile()
    noise = _distractor_ids(before, after)
    drafts = [
        a for a in world.artifacts
        if a.id in noise and any(f.revises == a.id for f in world.artifact_intents)
    ]
    assert drafts, "expected at least one superseded-draft distractor"
    for draft in drafts:
        assert draft.lifecycle is Lifecycle.SUPERSEDED
        reviser = world.artifacts.by_id(next(
            f.id for f in world.artifact_intents if f.revises == draft.id
        ))
        assert reviser.version > draft.version
        assert reviser.created_at >= draft.created_at


def test_derived_copies_do_not_predate_their_parent(before: World, after: World) -> None:
    world = after.compile()
    noise = _distractor_ids(before, after)
    copies = [a for a in world.artifacts if a.id in noise and a.derived_from]
    assert copies, "expected at least one derived-copy distractor"
    for copy in copies:
        parent = world.artifacts.by_id(copy.derived_from[0])
        assert copy.created_at >= parent.created_at
        assert copy.artifact_type != parent.artifact_type


def test_the_corpus_still_validates_with_distractors_live(after: World) -> None:
    world = after.compile()
    report = world.validate()
    assert report.ok, report.violations[:10]


def test_a_narrated_and_rendered_corpus_with_distractors_validates(before: World) -> None:
    """Distractor sections must go through the ordinary narration pipeline —
    no separate prose path — and the rendered corpus must still validate."""
    from worldloom.narrative import DeterministicProvider

    world = distractors.apply(before, count=20)
    world = world.narrate(DeterministicProvider())
    _calls, _replayed, rejected = world._narration
    assert rejected == 0, "the deterministic provider rejected a distractor's own request"
    world = world.render("markdown")
    report = world.validate()
    assert report.ok, report.violations[:10]


# ---------------------------------------------------------------------------
# 5: determinism
# ---------------------------------------------------------------------------


def test_distractors_are_deterministic() -> None:
    def signature() -> list[tuple]:
        world = distractors.apply(_retail_before(), count=20)
        return sorted(
            (i.id, i.artifact_type, tuple(i.required_fact_ids), i.revises, tuple(i.derived_from))
            for i in world.artifact_intents
        )

    assert signature() == signature()


def test_the_flag_rides_the_recipe(before: World, after: World) -> None:
    steps = after.recipe["steps"]
    assert steps[-1] == {"scenario": "Distractors", "count": 20}
    # Absent entirely when the flag was never used, so a corpus built without
    # distractors carries no trace of this module in its recipe.
    assert all(step.get("scenario") != "Distractors" for step in before.recipe.get("steps", ()))


# ---------------------------------------------------------------------------
# 6: works across verticals — no retail-only assumption
# ---------------------------------------------------------------------------


def test_distractors_apply_to_the_banking_vertical_too() -> None:
    world = distractors.apply(_banking_before(), count=15)
    report = world.compile().validate()
    assert report.ok, report.violations[:10]
