"""What holds, and what stops meaning anything, as a corpus gets large.

Everything measured in this project has only ever been measured on a corpus of
fifteen artifacts. Two things go wrong on the way to ten thousand, and neither
is "it gets slow" — one is an accidental quadratic that a correctness test
cannot see because the answer is right either way, and the other is a *statistic*
that keeps returning a plausible number after it has stopped distinguishing
anything. Both are pinned here rather than left to a benchmark nobody runs.
"""

from __future__ import annotations

import dataclasses

import pytest

from worldloom import RetailWorld, similarity, stats, validate
from worldloom.collections import Collection
from worldloom.evaluate.index import passages
from worldloom.models import CanonicalFact
from worldloom.narrative import DeterministicProvider
from worldloom.scenarios import MonthEndClose
from worldloom.world import World

#: Accessors `validate` resolves ids against while looping over some *other*
#: collection. Each read of one of these is a fresh `Collection`, so a read
#: inside a loop is a fresh index — see the counting test below.
RESOLVED_IN_LOOPS = ("facts", "events", "people", "artifacts", "artifact_intents")


def _world(periods: int) -> World:
    world = RetailWorld(seed=8128).build()
    for month in range(1, periods + 1):
        world = world.run(
            MonthEndClose(period=f"2026-{month:02d}", include_operational_incident=(month == 1))
        )
    return world


# ---------------------------------------------------------------------------
# The accidental quadratic
# ---------------------------------------------------------------------------


def test_a_collection_is_immutable_so_binding_one_once_cannot_change_an_answer() -> None:
    """The premise the hoisting in `_Validator.__init__` rests on.

    Two reads of `world.facts` are equal collections and *different objects*,
    and `Collection` has no mutator — so a check that binds one before its loop
    sees exactly what a check that re-read it inside the loop would have seen.
    If either half of that ever stops being true, the hoisting becomes a
    behaviour change rather than a speed-up, and this is the test that says so.
    """
    world = _world(1)
    first, second = world.facts, world.facts
    assert first is not second, "the accessor mints a new Collection per read"
    assert first == second
    assert list(first) == list(second)
    for name in ("append", "extend", "add", "remove", "insert", "pop", "clear"):
        assert not hasattr(Collection, name), f"Collection.{name} would make binding unsafe"


def test_validate_reads_each_world_accessor_a_bounded_number_of_times() -> None:
    """The pin against the quadratic, stated as a count rather than a stopwatch.

    `Collection.by_id` builds its index lazily and caches it, which makes an id
    lookup constant time — but only for the lifetime of that Collection, and
    `World.facts` hands back a new one every read. So
    ``for fact in w.facts: w.events.get(fact.event_id)`` rebuilds the entire
    event index once per fact. It is invisible to every correctness test in this
    suite, because the answer is identical; it showed up only as a 48-period
    corpus taking 1.7s to validate where the work is 0.6s.

    Asserting a *constant* bound rather than a ratio is deliberate: a ratio
    would still pass if the count grew with the corpus by a factor of two, and
    the defect is growth of any kind. Each accessor is read a handful of times —
    once per check that needs it — and never per member of anything.
    """
    small, large = _world(1), _world(4)
    assert len(large.facts) > 3 * len(small.facts), "the two worlds must differ in size"

    def reads_during_validate(world: World) -> dict[str, int]:
        counted = {name: 0 for name in RESOLVED_IN_LOOPS}
        originals = {name: getattr(World, name).fget for name in RESOLVED_IN_LOOPS}

        def install(name: str) -> None:
            original = originals[name]

            def counting(self):  # type: ignore[no-untyped-def]
                counted[name] += 1
                return original(self)

            setattr(World, name, property(counting))

        try:
            for name in RESOLVED_IN_LOOPS:
                install(name)
            validate.validate(world)
        finally:
            for name, original in originals.items():
                setattr(World, name, property(original))
        return counted

    for name, count in reads_during_validate(large).items():
        assert count <= 32, f"validate read World.{name} {count} times"

    assert reads_during_validate(small) == reads_during_validate(large), (
        "how many times validate reads an accessor must not depend on corpus size"
    )


def test_validate_still_finds_a_defect_after_the_collections_are_bound_once() -> None:
    """A speed-up that stops catching things is not a speed-up.

    The check that paid the most for the quadratic is `fact_precedes_event`,
    which resolves an event id once per fact. Bind the collection once and it
    must still fire.
    """
    world = _world(1)
    assert validate.validate(world).ok, "the unmodified world is clean"

    fact = next(f for f in world.facts if f.event_id)
    event = world.events.get(fact.event_id)
    assert event is not None
    broken = CanonicalFact.model_validate(
        {**fact.model_dump(mode="python"), "valid_from": event.occurred_at.replace(year=2000)}
    )

    # `World` is frozen and holds its facts in a private tuple, so the defect is
    # injected by rebuilding that tuple rather than through a mutator that does
    # not exist — which is the same fact about the model that makes binding a
    # collection once safe in the first place.
    damaged = dataclasses.replace(
        world, _facts=tuple(broken if f.id == fact.id else f for f in world.facts)
    )
    codes = {v.code for v in validate.validate(damaged).violations}
    assert "fact_precedes_event" in codes


# ---------------------------------------------------------------------------
# The statistic that stops distinguishing anything
# ---------------------------------------------------------------------------


def _templated_pool(templates: int, copies: int) -> list[frozenset[str]]:
    """*templates* distinct documents, each stamped out *copies* times.

    Shingle sets directly rather than passages: the arithmetic in
    `Stats.near_duplicate_share` is about set similarity, and routing it through
    a generator would be testing the generator.
    """
    return [
        frozenset(f"t{t}-w{w}" for w in range(20))
        for t in range(templates)
        for _ in range(copies)
    ]


@pytest.mark.parametrize("templates", [4, 8])
def test_the_near_duplicate_rate_cannot_see_how_hard_a_template_repeats(templates: int) -> None:
    """The claim `Stats.near_duplicate_share` is documented on, as arithmetic.

    With *K* templates each repeated *m* times the qualifying pairs are the
    within-template ones, ``K·m(m-1)/2``, against ``n(n-1)/2`` total — so the
    rate is ``(m-1)/(K·m-1)``, which saturates at ``1/K``. The repetition is
    quadratic in *m* and so is the denominator; they cancel, and the reading has
    a ceiling it reaches almost immediately.
    """
    ceiling = 1 / templates
    rates = {}
    for copies in (4, 96):
        sets = _templated_pool(templates, copies)
        pairs = similarity.near_duplicate_pairs(sets, stats.NEAR_DUPLICATE_THRESHOLD)
        total = len(sets) * (len(sets) - 1) // 2
        rates[copies] = len(pairs) / total
        assert rates[copies] == pytest.approx((copies - 1) / (templates * copies - 1))
        assert rates[copies] < ceiling
        groups = similarity.clusters(pairs, len(sets))
        assert len(groups) == templates
        assert max(len(g) for g in groups) == copies

    # Twenty-four times the repetition; the number a reader is shown moves by
    # less than a third of the ceiling it was already most of the way to.
    assert rates[96] - rates[4] < ceiling / 3


def test_the_group_readings_move_when_the_rate_does_not() -> None:
    """The companion readings, on the same synthetic pool. These do contain *m*."""
    sets_few = _templated_pool(8, 4)
    sets_many = _templated_pool(8, 96)

    def share_and_largest(sets: list[frozenset[str]]) -> tuple[float, int]:
        groups = similarity.clusters(
            similarity.near_duplicate_pairs(sets, stats.NEAR_DUPLICATE_THRESHOLD), len(sets)
        )
        return sum(len(g) for g in groups) / len(sets), max(len(g) for g in groups)

    share_few, largest_few = share_and_largest(sets_few)
    share_many, largest_many = share_and_largest(sets_many)

    assert share_few == share_many == 1.0, "every passage is a copy of something"
    assert largest_many == 24 * largest_few


def test_stats_reports_the_groups_from_the_same_join_as_the_rate() -> None:
    """`compute` runs the join once and both readings come out of it.

    The two would be free to disagree about a corpus if each ran its own join,
    which is the sort of drift a reader has no way to notice.
    """
    world = _world(3).compile().narrate(DeterministicProvider()).render("markdown")
    pool = list(passages(world))
    report = stats.compute(world)

    groups = stats.near_duplicate_clusters(pool)
    assert report.near_duplicate_groups == len(groups)
    assert report.near_duplicate_grouped_passages == sum(len(g) for g in groups)
    assert report.largest_near_duplicate_group == max((len(g) for g in groups), default=0)
    assert report.near_duplicate_share == pytest.approx(
        report.near_duplicate_grouped_passages / report.passage_count
    )
    assert report.as_dict()["near_duplicate"]["largest_group"] == report.largest_near_duplicate_group


def test_a_corpus_with_nothing_to_compare_reports_no_share_rather_than_dividing_by_zero() -> None:
    assert stats._near_duplicate_reading([]) == ((), ())
