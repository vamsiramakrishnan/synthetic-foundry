"""The cross-corpus reading, and the finding it exists to make unarguable.

`test_evaluate.py` asserts one corpus is hard. This asserts things about a
*set* of corpora — which is a different claim, and the one `worldloom mosaic`
actually makes.

The headline test here is deliberately written to fail if the mosaic ever stops
repeating itself: `test_the_mosaic_asks_one_worlds_worth_of_questions` pins the
unflattering measurement rather than asserting a threshold that could be
loosened. If the evaluation generator is opened up so that a 30-person world
with a large estate asks questions a 16-person world cannot, that test is the
one that says so.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.evaluate import across
from worldloom.evaluate.across import MosaicWorld
from worldloom.evaluate.score import ABSTENTION_FRACTION, RETRIEVERS
from worldloom.narrative import DeterministicProvider

PERIOD = "2026-03"


def _world(seed: int) -> World:
    return (
        RetailWorld(seed=seed)
        .build()
        .run(MonthEndClose(period=PERIOD, include_operational_incident=True))
        .narrate(DeterministicProvider())
        .render("markdown")
    )


@pytest.fixture(scope="module")
def worlds() -> tuple[MosaicWorld, ...]:
    """Three worlds from three seeds — the *weakest* form of the claim.

    A real mosaic varies headcount, span, depth, estate and physics as well, so
    if even these three differ in nothing the mosaic's extra axes are what has
    to carry the whole difference. See the disk-backed test below, which runs
    the same readings over worlds that do differ in shape.
    """
    return tuple(
        MosaicWorld(f"world-{index:02d}", _world(seed))
        for index, seed in enumerate((8128, 496, 6), start=1)
    )


def test_load_needs_more_than_one_corpus(tmp_path) -> None:
    """A "cross-corpus" reading over one corpus is not a reading, it is a typo."""
    _world(8128).export(tmp_path / "world-01")
    with pytest.raises(ValueError, match="at least two"):
        across.load(tmp_path)


def test_load_is_ordered_by_name(tmp_path) -> None:
    """`world-05` must be the fifth entry on every machine — filesystem order is
    not an ordering, and every finding below names a world."""
    for index, seed in ((3, 6), (1, 8128), (2, 496)):
        _world(seed).export(tmp_path / f"world-{index:02d}")
    loaded = across.load(tmp_path)
    assert [entry.name for entry in loaded] == ["world-01", "world-02", "world-03"]
    assert all(entry.world.artifact_irs for entry in loaded)


def test_the_transplanted_floor_is_the_scorers_own(worlds) -> None:
    """`_calibrate` is a copy of six lines inside `score()`, kept honest here.

    If the scorer's calibration changes and this does not, the transfer
    experiment silently starts transplanting a quantity `score()` no longer
    uses — which would still produce a plausible-looking matrix of zeroes.
    """
    from worldloom.evaluate.index import passages

    entry = worlds[0]
    pool = passages(entry.world)
    index = RETRIEVERS["bm25"]([passage.text for passage in pool])
    cases = list(entry.world.evaluations)
    tops = sorted(
        ranked[0][1]
        for case in cases
        if not case.expects_abstention and (ranked := index.rank(case.question, limit=1))
    )
    expected = tops[len(tops) // 2] * ABSTENTION_FRACTION
    assert across._calibrate(index, cases) == pytest.approx(expected)


def test_transfer_reports_a_floor_and_a_flip_matrix(worlds) -> None:
    reading = across.transfer(worlds)
    names = [entry.name for entry in worlds]
    assert set(reading.cards) == set(names)
    assert set(reading.floors) == set(names)
    # The diagonal is zero by construction: a world's own floor applied to
    # itself cannot change a verdict. Kept in the table so a hole never reads
    # as a missing measurement.
    assert all(reading.floor_flips[name][name] == 0 for name in names)


def test_the_mosaic_asks_one_worlds_worth_of_questions(worlds) -> None:
    """The finding. Every question is asked in every world, word for word.

    Not a threshold — the exact counts, because the point of this measurement
    is that it cannot be read charitably. Three worlds, forty-two questions
    each, forty-two distinct strings between them.
    """
    reading = across.overlap(worlds)
    assert reading.questions == 46 * len(worlds)
    assert reading.distinct_questions == 46
    assert reading.identical_in_every_world == 46
    # `redundancy` is rounded to four places, so the tolerance is the rounding.
    assert reading.redundancy == pytest.approx(1 - 1 / len(worlds), abs=1e-4)
    # Every question sits in a group that spans every world, and each such
    # group is a clique: C(n, 2) pairs per distinct question.
    assert reading.questions_in_a_cross_world_group == reading.questions
    assert reading.cross_world_pairs == 46 * len(worlds) * (len(worlds) - 1) // 2


def test_the_answers_are_where_the_variety_is(worlds) -> None:
    """The other half of the same finding, and the reason it is a generator
    problem rather than a mosaic problem: the facts genuinely differ."""
    reading = across.overlap(worlds)
    assert reading.distinct_with_answers > reading.distinct_questions


def test_survey_states_the_unflattering_verdict(worlds) -> None:
    reading = across.survey(worlds)
    assert reading.transfers["bm25"].identical
    assert "the variety is in the facts, not in the questions" in reading.verdict
    assert reading.difficulty.concentration == pytest.approx(reading.difficulty.even_share)
    assert "cross-world duplicate group" in str(reading)


def test_the_reading_is_deterministic(worlds) -> None:
    """Two runs over the same worlds must agree exactly — this is the measure
    half of a measure-then-iterate loop, and a number that moves on its own
    cannot be iterated against."""
    assert across.survey(worlds).as_dict() == across.survey(worlds).as_dict()


def test_a_family_that_fails_for_want_of_prose_says_so() -> None:
    """The reading that went unnoticed for five worlds and eight commits.

    `citation_required 0/3 ← no spread` in every world of a mosaic looked like
    a hard family and was three cases citing an incident RCA nobody had
    written: an un-narrated corpus compiles fifteen artifacts and only three of
    them carry a retrievable passage, so eleven of forty-two cases could not be
    passed by any retriever at all. Both readings print the same digit, which
    is why this has to be asserted rather than looked at.
    """
    from worldloom import archetypes
    from worldloom.evaluate.score import score
    from worldloom.retail import RetailWorld
    from worldloom.scenarios import MonthEndClose

    world = (RetailWorld(seed=8128, archetype=archetypes.get("omnichannel_retailer"))
             .build()
             .run(MonthEndClose(period="2026-03", include_operational_incident=True))
             .compile())
    card = score(world)
    assert card.unreachable, "an un-narrated corpus has evidence nothing carries"
    blocked = card.unreachable_by_type()
    # The families whose cases rest on prose rather than on a table.
    assert any(kind.value == "citation_required" for kind in blocked)
    # And it is said where a reader is looking at the number, not only in a
    # field they would have to know to ask for.
    assert "no passage carries" in str(card)

    # An abstention case expects no evidence, so none of it can be missing —
    # otherwise every corpus would report its whole abstention family as
    # unanswerable, which is both true and useless.
    assert all(outcome.reachable for outcome in card.outcomes
               if outcome.evaluation_type.value == "expected_abstention")
