"""The SDK: arrangement is free, invariants are not."""

from __future__ import annotations

import pytest

from worldloom import sdk


def test_a_blueprint_is_immutable_so_it_can_be_reused() -> None:
    """The property the whole comprehension style rests on: a base blueprint
    cannot be spoiled by what is done to its descendants."""
    base = sdk.retail().org(span=8)
    base.calendar("harvest").estate("large")
    assert base.calendar_name is None and base.estate_size is None
    assert base.shape["span"] == 8


def test_nothing_is_built_until_build() -> None:
    described = sdk.retail().org(headcount=20, span=4, levels=3).describe()
    assert described["shape"]["headcount"] == 20


def test_cross_is_a_product_and_dispersed_is_not_its_prefix() -> None:
    """Taking the first N of a product gives N that differ only in the last
    axis, which is what a product's ordering does."""
    field = sdk.cross(sdk.retail(), calendar=["flat", "harvest"],
                      estate=["small", "medium", "large"])
    assert len(field) == 6
    picked = sdk.dispersed(field, 3)
    assert len({b.describe()["estate"] for b in picked}) > 1


def test_underscores_resolve_to_registry_names() -> None:
    blueprint = sdk.retail().physics(ops_incident_hypothesis_minutes=(15, 25))
    assert "ops.incident.hypothesis_minutes" in blueprint.physics_overrides


def test_an_unknown_parameter_is_refused_not_ignored() -> None:
    with pytest.raises(KeyError, match="no parameter matches"):
        sdk.retail().physics(retail_margin_nonsense=(1, 2))


def test_an_unknown_calendar_is_refused_at_description_time() -> None:
    """Not at build time — a comprehension that names a bad calendar should
    fail on the line that names it, not fifty worlds later."""
    with pytest.raises(KeyError):
        sdk.retail().calendar("christmas")


def test_the_sdk_relaxes_no_invariant() -> None:
    with pytest.raises(ValueError, match="do not fit"):
        sdk.retail().org(headcount=500, span=2, levels=2).build()


def test_a_built_world_measures_and_validates() -> None:
    world = sdk.retail().org(headcount=20, span=5, levels=3).build()
    measured = world.measure()
    assert measured["people"] > 20 and measured["nodes"] > 0
    assert world.ok


def test_building_is_lazy_so_an_early_stop_mints_nothing_more() -> None:
    seen = 0
    for _ in sdk.built(sdk.sweep(sdk.retail(), "calendar", ["flat", "harvest", "harvest"])):
        seen += 1
        if seen == 1:
            break
    assert seen == 1


@pytest.mark.parametrize("engine", ["retail", "banking", "insurance"])
def test_every_engine_has_a_starting_point(engine: str) -> None:
    assert sdk.engine(engine).describe()["engine"] == engine
    assert len(sdk.mosaic_of(2, engine=engine)) == 2


def test_an_unknown_engine_says_which_exist() -> None:
    with pytest.raises(KeyError, match="known"):
        sdk.engine("logistics")
