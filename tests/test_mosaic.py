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


# ---------------------------------------------------------------------------
# Every engine, and the invariants its physics must respect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", sorted(mosaic.ENGINES))
def test_every_engine_produces_distinct_buildable_shapes(engine: str) -> None:
    variants = mosaic.field(4, engine=engine)
    assert len({(v.headcount, v.span, v.levels) for v in variants}) == 4
    for variant in variants:
        variant.role_table()          # must not raise for any engine


@pytest.mark.parametrize("engine", sorted(mosaic.ENGINES))
def test_an_engine_only_varies_physics_it_actually_reads(engine: str) -> None:
    """A mosaic that moved `retail.margin.erosion` through a bank would report
    varying something it had not."""
    prefixes = {"retail": ("retail.", "ops."), "banking": ("capital.",),
                "insurance": ("reserves.",)}[engine]
    for axis in mosaic.ENGINES[engine]:
        if axis.parameter is not None:
            assert axis.parameter.startswith(prefixes), (engine, axis.name)


def test_only_the_engine_that_reads_a_trading_year_varies_one() -> None:
    """`finance.generate` is the one generator that reads seasonality and only
    the retail engine runs it."""
    assert any(a.name == "calendar" for a in mosaic.ENGINES["retail"])
    for engine in ("banking", "insurance"):
        assert not any(a.name == "calendar" for a in mosaic.ENGINES[engine])
        assert "calendar" not in mosaic.spread(mosaic.field(3, engine=engine))


@pytest.mark.parametrize("engine", sorted(mosaic.ENGINES))
def test_no_axis_generates_a_span_its_generator_would_refuse(engine: str) -> None:
    """The test that was missing.

    A physics axis carries the engine's own *width* across, so an axis whose
    low end sits within half a width of a hard bound generates an illegal span.
    `reserves.decision.movement_multiple` must stay strictly above 1.0 — the
    held-versus-central gap the insurance vertical exists to pose stops opening
    at or below it — and the first version of that axis put its low end at 1.05
    against a width of 0.4, so every insurance mosaic died on the guard.

    Walking the extremes rather than the sampled points: a mosaic that happens
    not to select the bad corner today would select it tomorrow.
    """
    from worldloom.parameters import DEFAULT

    for axis in mosaic.ENGINES[engine]:
        if axis.parameter is None:
            continue
        engine_span = DEFAULT.span(axis.parameter)
        half = (engine_span.high - engine_span.low) / 2.0
        for centre in (axis.low, axis.high):
            low = centre - half
            if axis.parameter.startswith("reserves.decision."):
                assert low > 1.0, (
                    f"{axis.name} at {centre} generates [{low}, ...], and"
                    " `triangles.generate` refuses a multiple at or below 1.0"
                )
            assert low < centre + half


@pytest.mark.parametrize("engine", sorted(mosaic.ENGINES))
def test_an_engines_extremes_actually_build(engine: str) -> None:
    """Walking the corners of the space, not the middle of it. A guard that
    only fires at an extreme is a guard that fires in production."""
    from worldloom import archetypes, domains
    from dataclasses import replace

    names = {"retail": "omnichannel_retailer", "banking": "midsize_adi",
             "insurance": "midsize_general_insurer"}
    shape = archetypes.get(names[engine])
    domain = domains.for_archetype(shape.key)
    assert domain is not None

    for corner in (0.0, 1.0):
        coordinates = [corner] * len(mosaic.ENGINES[engine])
        variant = mosaic._candidate(0, coordinates, seed=8128, engine=engine)
        if variant is None:
            continue          # an infeasible shape at that corner is legitimate
        spec = replace(domain.world(seed=variant.seed, archetype=shape),
                       physics=variant.physics)
        world = spec.build()
        episode = (domain.single_episode("2026-03") if domain.single_episode
                   else None)
        if episode is not None:
            world = world.run(replace(episode, physics=variant.physics))
        assert world.validate().ok


def test_an_unknown_engine_says_which_exist() -> None:
    with pytest.raises(KeyError, match="banking"):
        mosaic.field(3, engine="logistics")


def test_the_estate_axis_changes_the_size_of_the_graph() -> None:
    """Otherwise the axis is a label on a field that never moves."""
    assert len({v.estate for v in mosaic.field(6)}) > 1
