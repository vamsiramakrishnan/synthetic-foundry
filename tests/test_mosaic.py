"""Many companies from one command, and the measurement that says they differ."""

from __future__ import annotations

import itertools
import json

import pytest

from worldloom import mosaic
from worldloom.dispersion import manhattan
from worldloom.retail import RetailWorld


def titles(world) -> frozenset[str]:  # type: ignore[no-untyped-def]
    return frozenset(person.title for person in world.people)


def built(variant: mosaic.Variant):  # type: ignore[no-untyped-def]
    return RetailWorld(
        seed=variant.seed, physics=variant.physics,
        role_table=variant.role_table(), seasonality=variant.seasonality,
    ).build()


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------


def test_varying_the_seed_alone_produces_one_company() -> None:
    """The baseline this exists to fix, asserted rather than remembered.

    A seed decides names, figures, and which month the incident lands in. It
    does not decide headcount, span, depth, or trading calendar — so five seeds
    are five samples of one enterprise, which is a fine corpus and a poor
    dataset.
    """
    shapes = {titles(RetailWorld(seed=seed).build()) for seed in range(8128, 8133)}
    assert len(shapes) == 1


def test_a_mosaic_produces_a_different_company_every_time() -> None:
    variants = mosaic.field(5)
    assert len({titles(built(variant)) for variant in variants}) == 5


def test_every_world_in_a_mosaic_is_coherent() -> None:
    """Unlike each other *and* individually true. Either alone is worthless —
    varied incoherent worlds are noise, identical coherent ones are one world."""
    for variant in mosaic.field(4):
        report = built(variant).validate()
        assert report.ok, (variant.summary(), [str(v) for v in report.violations[:3]])


def test_the_shapes_are_genuinely_distinct_not_merely_reordered() -> None:
    variants = mosaic.field(5)
    assert len({(v.headcount, v.span, v.levels) for v in variants}) == 5


# ---------------------------------------------------------------------------
# Cover, then choose
# ---------------------------------------------------------------------------


def test_dispersion_beats_taking_the_first_candidates() -> None:
    """The whole reason for the traversal.

    Generating N and hoping they differ is what this deliberately does not do,
    and the test has to show the choosing earns its keep rather than assert the
    algorithm's name.

    The baseline has to be the first N *feasible candidates in generation
    order*, not `field(40)[:5]` — a farthest-first traversal is greedy and
    therefore prefix-stable, so that would compare a dispersed selection with
    itself and pass while measuring nothing.
    """
    from worldloom.dispersion import halton

    def closest(points) -> float:  # type: ignore[no-untyped-def]
        return min(manhattan(a, b) for a, b in itertools.combinations(points, 2))

    naive: list[tuple[float, ...]] = []
    for coordinates in halton(len(mosaic.AXES), 512):
        if mosaic._candidate(len(naive), coordinates, seed=8128) is not None:
            naive.append(tuple(coordinates))
        if len(naive) == 5:
            break

    chosen = [variant.coordinates for variant in mosaic.field(5)]
    # Measured at 2.46x when this was written. Asserted loosely because the
    # exact ratio moves whenever an axis does, and the claim being defended is
    # "the choosing is worth its cost", not a particular number.
    assert closest(chosen) > 1.5 * closest(naive)


def test_an_infeasible_shape_is_discarded_rather_than_nudged() -> None:
    """Nudging would pile candidates onto the boundary of the feasible region
    and the dispersion would then be over a distorted space."""
    for variant in mosaic.field(8):
        table = variant.role_table()          # must not raise
        assert len(table) >= variant.headcount - 1


def test_asking_for_more_worlds_than_are_buildable_says_which_constraint_binds() -> None:
    with pytest.raises(ValueError, match="name pools"):
        mosaic.field(500)


def test_a_mosaic_of_none_is_empty_rather_than_an_error() -> None:
    assert mosaic.field(0) == ()


def test_a_negative_count_is_refused() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        mosaic.field(-1)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_request_gives_the_same_mosaic() -> None:
    first = [v.as_dict() for v in mosaic.field(5)]
    for _ in range(3):
        assert [v.as_dict() for v in mosaic.field(5)] == first


def test_a_worlds_seed_follows_its_position_not_the_filtering() -> None:
    """So a mosaic's third world is reproducible without rebuilding the first
    two, and two mosaics of different sizes agree on the worlds they share."""
    variants = mosaic.field(6, seed=42)
    assert [v.seed for v in variants] == [42, 43, 44, 45, 46, 47]
    assert [v.index for v in variants] == [1, 2, 3, 4, 5, 6]


def test_a_smaller_mosaic_is_a_prefix_of_a_larger_one() -> None:
    larger = mosaic.field(6)
    smaller = mosaic.field(3)
    assert [v.as_dict() for v in smaller] == [v.as_dict() for v in larger[:3]]


def test_a_mosaic_plan_is_json() -> None:
    document = {"spread": mosaic.spread(mosaic.field(4)),
                "worlds": [v.as_dict() for v in mosaic.field(4)]}
    json.dumps(document, allow_nan=False)


# ---------------------------------------------------------------------------
# What it varies, and what it reports
# ---------------------------------------------------------------------------


def test_every_axis_says_what_it_decides() -> None:
    """A user deciding whether five worlds are worth generating should be able
    to see what makes them five, without generating five."""
    for axis in mosaic.AXES:
        assert axis.about.strip(), axis.name
        assert axis.low < axis.high, axis.name


def test_every_physics_axis_names_a_real_parameter() -> None:
    from worldloom.parameters import DEFAULTS

    for axis in mosaic.AXES:
        if axis.parameter is not None:
            assert axis.parameter in DEFAULTS, axis.name


def test_an_axis_moves_the_parameter_it_names() -> None:
    variants = mosaic.field(5)
    erosion = {v.physics.span("retail.margin.erosion").low for v in variants}
    assert len(erosion) > 1, "the mosaic is not actually moving the physics"


def test_a_span_never_collapses_to_a_constant() -> None:
    """A world whose every figure is the same number is not a world. The
    engine's own width is carried across so variation *within* a corpus stays
    what the engine intended while the level moves."""
    for variant in mosaic.field(6):
        for name, span in variant.overrides.items():
            assert span.high > span.low, (variant.index, name)


def test_the_spread_report_measures_rather_than_claims() -> None:
    spread = mosaic.spread(mosaic.field(5))
    assert spread["worlds"] == 5
    assert spread["distinct_shapes"] == 5
    assert len(spread["headcounts"]) > 1
    assert spread["closest_pair"] > 0.0


def test_describe_builds_nothing() -> None:
    document = mosaic.describe()
    assert len(document["axes"]) == len(mosaic.AXES)
    assert document["calendars"]
    json.dumps(document, allow_nan=False)


def test_a_small_company_does_not_get_every_department() -> None:
    """Ten functions over fourteen people is ten people who each *are* a
    department, which is not a small company — it is a spreadsheet."""
    small = mosaic.Variant(1, 8128, headcount=14, span=3, levels=2,
                           calendar="flat", overrides={}, coordinates=())
    large = mosaic.Variant(2, 8128, headcount=31, span=9, levels=5,
                           calendar="flat", overrides={}, coordinates=())
    assert len(small.functions) < len(large.functions)
