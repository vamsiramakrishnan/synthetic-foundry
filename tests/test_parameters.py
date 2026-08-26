"""The world-physics registry: the contract, and the byte-identity it rests on."""

from __future__ import annotations

import json

import pytest

from worldloom import recipe as recipe_module
from worldloom.parameters import (
    DEFAULT,
    DEFAULTS,
    Parameters,
    Span,
    overrides_document,
    overrides_from,
    publish,
)
from worldloom.retail import BASE_INCIDENT_LIKELIHOOD, RetailWorld
from worldloom.rng import Rng
from worldloom.scenarios import MonthEndClose

# ---------------------------------------------------------------------------
# The registry itself
# ---------------------------------------------------------------------------


def test_every_parameter_says_what_it_decides() -> None:
    """A range with no sentence is a range nobody can responsibly override."""
    silent = sorted(name for name, span in DEFAULTS.items() if not span.about.strip())
    assert not silent, f"parameters with no `about`: {silent}"


def test_every_parameter_is_namespaced_by_domain() -> None:
    """`tests/test_thin_waist.py` forbids engine vocabulary in core, and a flat
    namespace would put every industry's physics in one undifferentiated table."""
    for name in DEFAULTS:
        assert name.count(".") >= 2, f"{name} is not <domain>.<subject>.<measure>"


def test_the_engine_s_own_defaults_carry_no_source() -> None:
    """They were chosen to make one plausible episode work, not calibrated
    against anything, and labelling them otherwise would launder that."""
    assert not [name for name, span in DEFAULTS.items() if span.source]


def test_a_chance_is_a_single_probability() -> None:
    with pytest.raises(ValueError, match="single probability"):
        Span(0.2, 0.4, "chance")
    with pytest.raises(ValueError, match="single probability"):
        Span(1.4, 1.4, "chance")


def test_an_inverted_range_is_refused() -> None:
    with pytest.raises(ValueError, match="inverted"):
        Span(0.9, 0.1)


def test_an_integer_draw_has_no_decimal_places() -> None:
    with pytest.raises(ValueError, match="no decimal places"):
        Span(1, 10, "integer", places=2)


def test_the_published_registry_is_json_and_sorted() -> None:
    registry = publish()
    assert list(registry) == sorted(registry)
    json.dumps(registry, allow_nan=False)


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_an_unknown_parameter_is_refused_rather_than_ignored() -> None:
    """A pack with `retail.margin.budgt` in it builds a perfectly plausible
    company at the engine's own margin and gives the author no way to notice."""
    with pytest.raises(KeyError, match="budgt"):
        DEFAULT.with_overrides({"retail.margin.budgt": Span(0.5, 0.6)})


def test_an_override_keeps_the_engine_s_kind_and_rounding() -> None:
    # A pack states what range a figure lives in. How many decimals it is
    # rounded to is a property of the fact's own unit, and a figure that
    # started arriving at full float precision would change every document
    # that prints it.
    physics = DEFAULT.with_overrides({"retail.margin.budget": Span(0.50, 0.58, places=9)})
    span = physics.span("retail.margin.budget")
    assert span.places == DEFAULTS["retail.margin.budget"].places
    assert (span.low, span.high) == (0.50, 0.58)


def test_overriding_a_probability_with_a_range_is_refused() -> None:
    with pytest.raises(ValueError, match="single probability"):
        DEFAULT.with_overrides({"ops.incident.likelihood": Span(0.1, 0.9)})


def test_asking_a_probability_of_a_range_parameter_is_a_type_error() -> None:
    with pytest.raises(TypeError, match="not a probability"):
        DEFAULT.probability("retail.margin.budget")


def test_a_generator_asking_for_an_unknown_parameter_says_whose_bug_it_is() -> None:
    with pytest.raises(KeyError, match="bug in the generator"):
        DEFAULT.span("retail.margin.nonexistent")


def test_parameters_are_hashable_so_scenarios_stay_hashable() -> None:
    # A frozen dataclass wrapping a Mapping gets a generated __hash__ that
    # raises; every scenario carrying physics would have to opt out of
    # comparing it, which makes two scenarios with different physics compare
    # equal.
    assert hash(DEFAULT) == hash(Parameters(DEFAULTS))
    assert len({MonthEndClose(period="2026-03"), MonthEndClose(period="2026-03")}) == 1


def test_the_public_base_likelihood_is_the_registry_s() -> None:
    """Two copies of a load-bearing probability is one copy that can quietly
    stop being the one the engine draws with."""
    assert BASE_INCIDENT_LIKELIHOOD == DEFAULT.probability("ops.incident.likelihood")


# ---------------------------------------------------------------------------
# Byte-identity — the whole contract
# ---------------------------------------------------------------------------


def _close(physics: Parameters):  # type: ignore[no-untyped-def]
    world = RetailWorld(seed=8128, physics=physics).build()
    return world.run(MonthEndClose(
        period="2026-03", include_operational_incident=True, physics=physics,
    ))


def _fingerprint(world) -> list[tuple]:  # type: ignore[no-untyped-def]
    return [
        (f.id, f.kind, f.period, getattr(f.value, "amount", None), getattr(f.value, "unit", None))
        for f in world.facts
    ]


def test_a_default_build_is_identical_to_one_with_no_physics_argument() -> None:
    """The registry forwards to `Rng` with exactly the arguments each literal
    it replaced used — same stream, same order, same rounding — so an
    un-overridden build is not close to the build before this existed, it is
    the same bytes."""
    assert _fingerprint(_close(DEFAULT)) == _fingerprint(_close(Parameters(DEFAULTS)))


def test_restating_a_default_changes_nothing() -> None:
    # The strongest available statement of the forwarding contract without a
    # pre-change tree to diff against: an override that happens to equal the
    # engine's own must be indistinguishable from no override at all.
    restated = DEFAULT.with_overrides({
        name: Span(span.low, span.high) for name, span in DEFAULTS.items()
        if span.kind != "chance"
    })
    assert _fingerprint(_close(restated)) == _fingerprint(_close(DEFAULT))


@pytest.mark.parametrize(
    ("name", "span", "kind"),
    [
        ("retail.margin.erosion", Span(0.10, 0.15), "metric.promotional_depth_margin_impact"),
        ("retail.revenue.miss_pct", Span(-0.30, -0.20), "financial.revenue.variance"),
    ],
)
def test_an_override_actually_moves_the_figure_it_names(name: str, span: Span, kind: str) -> None:
    """The other half of byte-identity: a registry that changed nothing would
    pass every identity test in this file and be useless."""
    before = {f.id: f.value.amount for f in _close(DEFAULT).facts if f.kind == kind}
    after = {f.id: f.value.amount for f in _close(DEFAULT.with_overrides({name: span})).facts
             if f.kind == kind}
    assert before, f"no {kind} facts — this test is not measuring anything"
    assert before != after


def test_the_incident_tempo_is_reachable() -> None:
    """Four literals decided how long every Worldloom organisation took to find
    a cause. This is the parameter set that argument was made about."""
    faster = DEFAULT.with_overrides({
        "ops.incident.hypothesis_minutes": Span(10, 20),
        "ops.incident.rule_out_minutes": Span(15, 25),
        "ops.incident.confirm_minutes": Span(10, 20),
    })
    def confirmed(world):  # type: ignore[no-untyped-def]
        return [e.occurred_at for e in world.events if "confirm" in e.kind]

    assert confirmed(_close(faster)) != confirmed(_close(DEFAULT))


def test_a_fast_hypothesis_never_predates_the_incident_it_depends_on() -> None:
    """Independent mosaic axes once let a fast hypothesis beat ticket raising.

    Seed 8138 reaches that draw in its fourth close: 12 minutes from detection
    to a hypothesis and 18 minutes to an opened incident.  The dependency must
    remain chronological without narrowing the caller's authored physics span.
    """
    physics = DEFAULT.with_overrides({
        "ops.incident.hypothesis_minutes": Span(2, 28),
    })
    world = RetailWorld(seed=8138, physics=physics).build()
    for period in ("2026-03", "2026-04", "2026-05", "2026-06"):
        world = world.run(MonthEndClose(
            period=period, include_operational_incident=True, physics=physics,
        ))

    events = {event.id: event for event in world.events}
    assert all(
        events[cause].occurred_at <= event.occurred_at
        for event in world.events
        for cause in event.caused_by
    )
    assert world.validate().ok


# ---------------------------------------------------------------------------
# Carriage: the recipe, and replay
# ---------------------------------------------------------------------------


def test_a_default_build_writes_no_physics_key_at_all() -> None:
    """The same rule `estate` and `eval_density` follow: a key that appears
    unconditionally puts a new field in every recipe ever written for a value
    that changes nothing, and the default-build byte diff is what catches it."""
    assert "physics" not in RetailWorld(seed=8128).build().recipe


def test_a_recipe_records_only_what_differs_from_the_engine() -> None:
    physics = DEFAULT.with_overrides({"retail.margin.erosion": Span(0.10, 0.15)})
    recipe = RetailWorld(seed=8128, physics=physics).build().recipe
    assert list(recipe["physics"]) == ["retail.margin.erosion"]


def test_a_probed_corpus_rebuilds_from_its_own_recipe() -> None:
    physics = DEFAULT.with_overrides({
        "retail.margin.erosion": Span(0.10, 0.15),
        "ops.incident.hypothesis_minutes": Span(15, 25),
    })
    built = _close(physics)
    rebuilt = recipe_module.rebuild(built.recipe)
    assert _fingerprint(rebuilt) == _fingerprint(built)


def test_a_recipe_whose_physics_does_not_load_is_refused_not_defaulted() -> None:
    """Falling back to the engine's would rebuild a *different world* while
    reporting success, which is the one failure a recipe exists to prevent."""
    recipe = RetailWorld(seed=8128).build().recipe
    broken = {**recipe, "physics": {"retail.margin.erosion": {"low": 0.1}}}
    with pytest.raises(recipe_module.RecipeError, match="does not load"):
        recipe_module.rebuild(broken)

    unknown = {**recipe, "physics": {"retail.margin.nope": {"low": 0.1, "high": 0.2}}}
    with pytest.raises(recipe_module.RecipeError, match="does not load"):
        recipe_module.rebuild(unknown)


def test_overrides_round_trip_through_json() -> None:
    physics = DEFAULT.with_overrides({
        "retail.margin.erosion": Span(0.10, 0.15, source="a sector prior"),
    })
    document = json.loads(json.dumps(overrides_document(physics), allow_nan=False))
    restored = DEFAULT.with_overrides(overrides_from(document))
    assert restored.span("retail.margin.erosion").low == 0.10
    assert "sector prior" in restored.span("retail.margin.erosion").source


def test_an_integer_span_survives_the_round_trip_it_is_recorded_by() -> None:
    """A mosaic axis hands `Span` Python ints, so `as_dict` wrote `"high": 34`
    while `overrides_from`'s `float(...)` read it back as `34.0` — and a mosaic
    world therefore did not rebuild byte-for-byte from its own recipe. Only
    `world.json` differed, which is exactly the kind of divergence that looks
    like nothing and means the recipe is not the world.

    Through `with_overrides`, because that is the path a rebuild takes and the
    only one where `kind` is meaningful: `overrides_from` deliberately drops it
    and the engine's own is put back. What has to survive is the *pair of
    bounds*.
    """
    physics = DEFAULT.with_overrides({"ops.incident.hypothesis_minutes": Span(10, 34)})
    document = json.loads(json.dumps(overrides_document(physics), allow_nan=False))
    replayed = DEFAULT.with_overrides(overrides_from(document))
    assert (replayed.span("ops.incident.hypothesis_minutes").as_dict()
            == physics.span("ops.incident.hypothesis_minutes").as_dict())


def test_a_malformed_override_names_the_parameter() -> None:
    with pytest.raises(ValueError, match=r"retail\.margin\.erosion"):
        overrides_from({"retail.margin.erosion": {"low": 0.1}})


# ---------------------------------------------------------------------------
# The invariants a pack may not override away
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["reserves.decision.margin_release_multiple", "reserves.decision.movement_multiple"],
)
def test_a_reserving_multiple_may_be_tuned_and_not_tuned_away(name: str) -> None:
    """`triangles.generate` sizes margin, then release, then movement in
    dependency order so the held-versus-central gap is guaranteed to open. That
    guarantee rests entirely on both multiples staying above 1.0."""
    from worldloom.generators import triangles

    periods = ("2025-03", "2025-06", "2025-09", "2025-12")
    with pytest.raises(ValueError, match=r"strictly above 1\.0"):
        triangles.generate(
            Rng(8128), accident_periods=periods, risk_margin_policy_pct=6.0,
            physics=DEFAULT.with_overrides({name: Span(0.9, 1.4)}),
        )

    # Tuning the severity is allowed, and must still open the gap.
    tuned = triangles.generate(
        Rng(8128), accident_periods=periods, risk_margin_policy_pct=6.0,
        physics=DEFAULT.with_overrides({name: Span(1.05, 1.10)}),
    )
    assert tuned is not None
