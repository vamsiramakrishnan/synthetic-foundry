"""Structural estate size is temporal, exact and recipe-replayable."""

from __future__ import annotations

from worldloom.recipe import rebuild
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose, StructuralChange
from worldloom.timeline import Estate, EstateSize


def test_estate_trajectory_interpolates_growth_and_contraction_exactly() -> None:
    growing = Estate(EstateSize(3, 10, 5, 4), EstateSize(7, 6, 9, 12))
    assert growing.sizes(3) == (
        EstateSize(3, 10, 5, 4),
        EstateSize(5, 8, 7, 8),
        EstateSize(7, 6, 9, 12),
    )


def test_structural_changes_keep_history_and_replay() -> None:
    world = RetailWorld(seed=8128).build()
    base = EstateSize(
        len(world.business_units), len(world.sites), len(world.systems), len(world.services)
    )
    world = world.run(MonthEndClose("2026-01", include_operational_incident=False))
    world = world.run(StructuralChange(
        "2026-01", base.business_units + 2, base.sites + 3,
        base.systems + 2, base.services + 4,
    ))
    after_growth = "2026-02-28T00:00:00+00:00"
    assert tuple(map(len, (
        world.business_units_at(after_growth), world.sites_at(after_growth),
        world.systems_at(after_growth), world.services_at(after_growth),
    ))) == (base.business_units + 2, base.sites + 3, base.systems + 2, base.services + 4)

    world = world.run(MonthEndClose("2026-02", include_operational_incident=False))
    world = world.run(StructuralChange(
        "2026-02", base.business_units, base.sites, base.systems, base.services,
    ))
    after_contraction = "2026-03-31T00:00:00+00:00"
    assert tuple(map(len, (
        world.business_units_at(after_contraction), world.sites_at(after_contraction),
        world.systems_at(after_contraction), world.services_at(after_contraction),
    ))) == (base.business_units, base.sites, base.systems, base.services)
    assert len(world.business_units) == base.business_units + 2, "closed entities remain historical"
    assert world.validate().ok

    replayed = rebuild(world.recipe)
    assert replayed.recipe == world.recipe
    assert replayed.facts == world.facts
    assert replayed.events == world.events


def test_role_bound_estate_is_an_explicit_contraction_floor() -> None:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose("2026-01", include_operational_incident=False)
    )
    try:
        world.run(StructuralChange("2026-01", 0, 0, 0, 0))
    except ValueError as exc:
        assert "safe floor" in str(exc) or "role-bound" in str(exc)
    else:  # pragma: no cover - the contract is refusal, never silent narrowing
        raise AssertionError("a role-bound estate was retired")
