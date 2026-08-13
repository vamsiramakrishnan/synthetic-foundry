"""What a MAP-Elites archive promises, asserted.

The central claim is `test_a_shuffled_population_builds_an_identical_archive`
and its exhaustive sibling: the archive is a pure function of the *set* of
candidates considered, never of the order they arrived in. Everything else here
is either the arithmetic that claim rests on (the tie rule, the grid) or the
refusals that keep the claim true (NaN fitness, mis-binned coordinates).
"""

from __future__ import annotations

import math
from itertools import permutations

import pytest

from worldloom.archive import Archive, Axis, Coordinates, Elite
from worldloom.rng import Rng

DENSITY = Axis("density", ("sparse", "balanced", "dense"))
SCOPE = Axis("scope", ("unit", "group"))
STORYLINE = Axis(
    "storyline",
    ("supply_shock", "margin_erosion", "outage", "restatement", "reorganisation", "steady"),
)

Candidate = tuple[str, Coordinates, float]


def _filled(candidates: list[Candidate], axes: list[Axis]) -> tuple[Archive, int]:
    """An archive over *axes* holding *candidates*, and how many were rejected."""
    archive = Archive(axes)
    rejected = sum(0 if archive.consider(*candidate) else 1 for candidate in candidates)
    return archive, rejected


def _population(count: int, *, seed: int = 8128) -> list[Candidate]:
    """A synthetic population over DENSITY x SCOPE x STORYLINE.

    Drawn through `Rng` rather than an index formula on purpose: index
    arithmetic over three axes lands on a periodic subset of the grid — strides
    of 3, 2 and 6 revisit six cells forever — which would make every fill
    reading below a property of my modular arithmetic rather than of a
    population. A seeded draw clumps the way a real generate-and-test loop
    clumps, which is the case the archive exists for, and stays reproducible.

    Fitness is a small integer, deliberately: that is what fitness looks like
    here (a rule count, a bounded score), and it is what makes ties the common
    case rather than the corner the tie rule is written for.
    """
    rng = Rng(seed, "archive-population")
    return [
        (
            f"cand-{index:03d}",
            (rng.choice(DENSITY.buckets), rng.choice(SCOPE.buckets), rng.choice(STORYLINE.buckets)),
            float(rng.integer(0, 3)),
        )
        for index in range(count)
    ]


def _champion(candidates: list[Candidate], cell: Coordinates) -> Elite | None:
    """The winner of *cell*, computed independently of the archive: the
    candidate minimising ``(-fitness, key)`` over everything offered to it."""
    contenders = [c for c in candidates if c[1] == cell]
    if not contenders:
        return None
    key, coordinates, fitness = min(contenders, key=lambda c: (-c[2], c[0]))
    return Elite(key=key, coordinates=coordinates, fitness=fitness)


# -- the tie rule, which is the whole mechanism ---------------------------


def test_a_better_candidate_takes_the_niche() -> None:
    archive = Archive([DENSITY])
    assert archive.consider("first", ("sparse",), 1.0) is True
    assert archive.consider("second", ("sparse",), 2.0) is True
    assert archive.consider("third", ("sparse",), 0.5) is False
    assert archive.elites() == (Elite("second", ("sparse",), 2.0),)


def test_a_tie_is_broken_by_the_lexicographically_smaller_key() -> None:
    # Both orders, because a tie broken by arrival is exactly the defect: the
    # incumbent keeps the niche in one order and loses it in the other.
    ascending = Archive([DENSITY])
    ascending.consider("aaa", ("dense",), 3.0)
    assert ascending.consider("bbb", ("dense",), 3.0) is False

    descending = Archive([DENSITY])
    descending.consider("bbb", ("dense",), 3.0)
    assert descending.consider("aaa", ("dense",), 3.0) is True

    assert ascending.elites() == descending.elites()


def test_reconsidering_the_installed_elite_changes_nothing() -> None:
    archive = Archive([DENSITY])
    assert archive.consider("only", ("balanced",), 1.0) is True
    assert archive.consider("only", ("balanced",), 1.0) is False
    assert archive.occupied == 1


def test_fitness_still_outranks_the_key() -> None:
    # The key breaks ties; it does not decide contests. A worse candidate with
    # an alphabetically earlier key must lose.
    archive = Archive([DENSITY])
    archive.consider("zzz", ("sparse",), 9.0)
    assert archive.consider("aaa", ("sparse",), 8.0) is False
    assert archive.elites()[0].key == "zzz"


# -- order independence: the claim ----------------------------------------


def test_every_permutation_of_a_tie_heavy_population_agrees() -> None:
    # Exhaustive rather than sampled, over a population small enough to be:
    # 6 candidates, 720 orders, two niches, and fitness drawn from {1.0, 2.0}
    # so that ties are unavoidable. If any ordering could matter, one of these
    # 720 finds it.
    candidates: list[Candidate] = [
        ("c", ("sparse",), 2.0),
        ("a", ("sparse",), 2.0),
        ("e", ("sparse",), 1.0),
        ("d", ("dense",), 1.0),
        ("b", ("dense",), 1.0),
        ("f", ("dense",), 2.0),
    ]
    expected = _filled(list(candidates), [DENSITY])[0].elites()
    for order in permutations(candidates):
        assert _filled(list(order), [DENSITY])[0].elites() == expected
    # And it is the independently computed champion of each niche, not merely
    # a stable wrong answer.
    assert expected == (
        Elite("a", ("sparse",), 2.0),
        Elite("f", ("dense",), 2.0),
    )


def test_a_shuffled_population_builds_an_identical_archive() -> None:
    candidates = _population(120)
    axes = [DENSITY, SCOPE, STORYLINE]
    reference, rejected = _filled(list(candidates), axes)

    shuffler = Rng(4, "shuffles")
    seen_rejections = {rejected}
    for _ in range(25):
        archive, shuffled_rejected = _filled(shuffler.shuffled(candidates), axes)
        assert archive.elites() == reference.elites()
        assert archive.holes() == reference.holes()
        assert archive.fill() == reference.fill()
        # The one thing about `consider`'s return value that holds in every
        # order: nothing can be rejected that had to be accepted to become a
        # champion. See the test below for what does *not* hold.
        assert shuffled_rejected <= len(candidates) - archive.occupied
        seen_rejections.add(shuffled_rejected)

    # And the finding this test refuses to hide: the archive is a pure function
    # of the set, the accept/reject *stream* is not. A candidate that takes a
    # niche and is displaced later answered True, so the count moves with the
    # order while `elites()` above does not.
    assert len(seen_rejections) > 1


def test_considering_the_same_population_twice_is_idempotent() -> None:
    candidates = _population(60)
    axes = [DENSITY, SCOPE]
    once, _ = _filled([(k, c[:2], f) for k, c, f in candidates], axes)
    twice, _ = _filled([(k, c[:2], f) for k, c, f in candidates] * 2, axes)
    assert once.elites() == twice.elites()


def test_every_elite_is_its_niche_champion() -> None:
    # The property the archive claims, checked against a brute-force answer
    # computed from the population rather than from the archive's own rule.
    candidates = _population(120)
    archive, _ = _filled(list(candidates), [DENSITY, SCOPE, STORYLINE])
    held = {elite.coordinates: elite for elite in archive.elites()}
    for cell in (
        (density, scope, storyline)
        for density in DENSITY.buckets
        for scope in SCOPE.buckets
        for storyline in STORYLINE.buckets
    ):
        assert held.get(cell) == _champion(candidates, cell)


# -- the grid: capacity, fill, holes ---------------------------------------


def test_holes_and_elites_partition_the_grid() -> None:
    archive, _ = _filled(_population(40), [DENSITY, SCOPE, STORYLINE])
    occupied = tuple(elite.coordinates for elite in archive.elites())
    assert len(occupied) + len(archive.holes()) == archive.capacity()
    assert set(occupied).isdisjoint(archive.holes())
    assert archive.occupied == len(occupied)
    assert archive.fill() == archive.occupied / archive.capacity()


def test_capacity_is_the_product_of_the_axes() -> None:
    assert Archive([DENSITY]).capacity() == 3
    assert Archive([DENSITY, SCOPE]).capacity() == 6
    assert Archive([DENSITY, SCOPE, STORYLINE]).capacity() == 36


def test_the_grid_is_ordered_by_bucket_position_not_alphabet() -> None:
    # `sorted` on the raw strings would give balanced, dense, sparse — which is
    # not the scale the caller declared. Both accessors must read down the axis.
    archive = Archive([DENSITY])
    assert archive.holes() == (("sparse",), ("balanced",), ("dense",))
    for bucket in ("dense", "sparse", "balanced"):
        archive.consider(f"k-{bucket}", (bucket,), 1.0)
    assert tuple(e.coordinates[0] for e in archive.elites()) == ("sparse", "balanced", "dense")


def test_an_empty_archive_reports_an_empty_archive() -> None:
    archive = Archive([DENSITY, SCOPE])
    assert archive.elites() == ()
    assert archive.occupied == 0
    assert archive.fill() == 0.0
    assert len(archive.holes()) == archive.capacity() == 6


def test_a_single_axis_and_a_single_candidate() -> None:
    archive = Archive([SCOPE])
    assert archive.consider("lonely", ("unit",), 0.0) is True
    assert archive.fill() == 0.5
    assert archive.holes() == (("group",),)


# -- refusals ---------------------------------------------------------------


def test_coordinates_of_the_wrong_length_name_the_offending_axis() -> None:
    archive = Archive([DENSITY, SCOPE])
    with pytest.raises(ValueError, match="scope"):
        archive.consider("short", ("sparse",), 1.0)
    with pytest.raises(ValueError, match="scope"):
        archive.consider("long", ("sparse", "unit", "extra"), 1.0)


def test_an_unknown_bucket_names_its_axis_and_the_alternatives() -> None:
    archive = Archive([DENSITY, SCOPE])
    with pytest.raises(ValueError, match="'density'"):
        archive.consider("wrong", ("medium", "unit"), 1.0)
    # Right bucket, wrong axis: 'unit' is a scope, not a density, and a
    # positional check is the only thing that catches it.
    with pytest.raises(ValueError, match="'density'"):
        archive.consider("swapped", ("unit", "sparse"), 1.0)
    assert archive.occupied == 0


def test_a_nan_fitness_is_refused_rather_than_ordered() -> None:
    archive = Archive([DENSITY])
    archive.consider("incumbent", ("sparse",), 1.0)
    with pytest.raises(ValueError, match="NaN"):
        archive.consider("nan", ("sparse",), math.nan)
    assert archive.elites()[0].key == "incumbent"


def test_infinite_fitness_is_ordered_normally() -> None:
    # Infinity is refused nowhere: it compares totally, so it breaks nothing.
    archive = Archive([DENSITY])
    archive.consider("finite", ("sparse",), 1e9)
    assert archive.consider("infinite", ("sparse",), math.inf) is True


def test_an_axis_must_be_a_dimension() -> None:
    with pytest.raises(ValueError, match="at least 2 buckets"):
        Axis("flat", ("only",))
    with pytest.raises(ValueError, match="duplicate"):
        Axis("repeated", ("a", "b", "a"))


def test_an_archive_needs_axes_and_distinct_ones() -> None:
    with pytest.raises(ValueError, match="at least one axis"):
        Archive([])
    with pytest.raises(ValueError, match="distinct names"):
        Archive([DENSITY, Axis("density", ("x", "y"))])


# -- the measured claim -----------------------------------------------------


def test_the_archive_spans_what_keeping_the_best_n_converges_on() -> None:
    """The reason the module exists, as a number.

    120 candidates over a 36-niche space. Taking the best 36 by fitness — the
    "overgenerate and keep the best n" policy, given the *same* generation
    budget and the same tie rule — lands on 20 distinct niches, because a
    ranking has no reason to spread and a clumped population stays clumped.
    The archive reaches 33, by construction, and names the 3 it did not.
    """
    candidates = _population(120)
    archive, rejected = _filled(list(candidates), [DENSITY, SCOPE, STORYLINE])

    assert archive.capacity() == 36
    assert archive.occupied == 33
    assert archive.fill() == pytest.approx(33 / 36)  # 92%
    assert len(archive.holes()) == 3
    # Order-dependent (see the shuffle test) — pinned here only because this
    # population is considered in a stated order.
    assert rejected == 71

    best_n = sorted(candidates, key=lambda c: (-c[2], c[0]))[:36]
    niches_of_best_n = len({cell for _, cell, _ in best_n})
    assert niches_of_best_n == 20
    # The comparison, stated rather than implied: the same 120 candidates span
    # 33 niches through the archive and 20 through a ranking of equal size.
    assert archive.occupied > niches_of_best_n
