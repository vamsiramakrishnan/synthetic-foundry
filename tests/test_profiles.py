"""The trading year: the invariant that makes it a type, and what it reaches."""

from __future__ import annotations

import json
import pathlib

import pytest

from worldloom import packs, profiles, recipe as recipe_module
from worldloom.generators import finance
from worldloom.profiles import MONTHS, Seasonality
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(profiles.PROFILES))
def test_every_shipped_profile_averages_one(name: str) -> None:
    """The whole reason this is a type.

    The index multiplies each month's budget, so the shape decides what the
    year looks like and the mean decides how big the company is. A profile
    averaging 1.05 does not make a business more seasonal — it makes it five
    per cent bigger, and an author would see only that revenue "looked high".
    """
    profile = profiles.PROFILES[name]
    assert sum(profile[month] for month in MONTHS) / 12 == pytest.approx(1.0, abs=1e-9)


def test_a_profile_that_would_resize_the_business_is_refused() -> None:
    with pytest.raises(ValueError, match="resize the whole business"):
        Seasonality(dict.fromkeys(MONTHS, 1.05))


def test_the_error_names_the_escape_hatch() -> None:
    """An author who meant the shape needs to be told how to say so."""
    with pytest.raises(ValueError, match="normalised"):
        Seasonality(dict.fromkeys(MONTHS, 0.9))


def test_normalising_keeps_the_shape_and_fixes_the_level() -> None:
    raw = [2.0, 1.0] * 6
    profile = Seasonality.normalised(raw)
    assert sum(profile[m] for m in MONTHS) / 12 == pytest.approx(1.0)
    assert profile[1] / profile[2] == pytest.approx(2.0)


def test_a_missing_month_is_refused() -> None:
    with pytest.raises(ValueError, match="all twelve months"):
        Seasonality({m: 1.0 for m in range(1, 12)})


def test_a_month_that_is_not_a_month_is_refused() -> None:
    with pytest.raises(ValueError, match="not calendar months"):
        Seasonality({**dict.fromkeys(MONTHS, 1.0), 13: 1.0})


def test_a_month_of_zero_trading_is_refused_as_a_closure() -> None:
    index = dict.fromkeys(MONTHS, 12 / 11)
    index[6] = 0.0
    with pytest.raises(ValueError, match="closure, not a season"):
        Seasonality(index)


# ---------------------------------------------------------------------------
# What it replaced
# ---------------------------------------------------------------------------


def test_the_engine_profile_is_the_literal_it_replaced_verbatim() -> None:
    assert profiles.RETAIL_CHRISTMAS.index == {
        1: 0.96, 2: 0.88, 3: 0.97, 4: 0.98, 5: 0.99, 6: 0.99,
        7: 1.00, 8: 0.99, 9: 0.98, 10: 1.01, 11: 1.04, 12: 1.21,
    }


def test_the_public_seasonality_name_still_works() -> None:
    """`series.py`'s docstring cites it and it was a public name."""
    assert finance.SEASONALITY == dict(profiles.RETAIL_CHRISTMAS.index)


def test_the_shipped_profiles_are_actually_unlike_each_other() -> None:
    """A menu of near-identical curves is a menu, not a decision."""
    amplitudes = sorted(round(p.amplitude, 2) for p in profiles.PROFILES.values())
    assert amplitudes[0] == 1.0, "one profile must be genuinely flat"
    assert amplitudes[-1] > 1.8, "one must be genuinely seasonal"
    assert len(set(amplitudes)) == len(amplitudes)


def test_an_unknown_profile_name_lists_the_known_ones() -> None:
    with pytest.raises(KeyError, match="known:"):
        profiles.named("christmas")


# ---------------------------------------------------------------------------
# Reach: pack, world, recipe
# ---------------------------------------------------------------------------


def _company_budget(world) -> float:  # type: ignore[no-untyped-def]
    return next(f.value.amount for f in world.facts
                if f.kind == "financial.revenue.budget" and f.subject == world.company.id)


def _built(pack_extra: dict, period: str = "2026-12"):  # type: ignore[no-untyped-def]
    raw = json.loads((pathlib.Path(__file__).resolve().parents[1]
                      / "examples/packs/regional-insurer.json").read_text())
    pack = packs.load({**raw, **pack_extra})
    spec = RetailWorld.from_pack(pack, seed=8128)
    return spec, spec.build().run(MonthEndClose(period=period, seasonality=spec.seasonality))


def test_a_pack_stops_being_a_grocer() -> None:
    """The finding this whole module exists for.

    `base` may only be `retail` or `banking`, so every industry that is neither
    runs the retail engine and inherited its trading calendar. This repository's
    own general-insurer pack therefore shipped a written-premium book that
    peaked 21% at Christmas. Nobody decided that.
    """
    _, seasonal = _built({})
    _, flat = _built({"seasonality": "flat"})

    december = profiles.RETAIL_CHRISTMAS[12]
    assert _company_budget(seasonal) / _company_budget(flat) == pytest.approx(december, rel=1e-4)


def test_a_pack_may_supply_twelve_months_of_its_own() -> None:
    own = {str(m): (1.5 if m in (6, 7, 8) else 0.8333333333333334) for m in MONTHS}
    spec, _ = _built({"seasonality": own})
    assert spec.seasonality is not None
    assert spec.seasonality[7] == pytest.approx(1.5)


def test_a_pack_whose_year_would_resize_the_business_is_refused() -> None:
    with pytest.raises(ValueError, match="resize the whole business"):
        _built({"seasonality": {str(m): 1.2 for m in MONTHS}})


def test_a_pack_naming_an_unknown_profile_is_refused() -> None:
    with pytest.raises(KeyError, match="known:"):
        _built({"seasonality": "wintertide"})


def test_a_default_build_records_no_trading_year() -> None:
    """A key that appears unconditionally puts a new field in every recipe ever
    written for a value that changes nothing."""
    assert "seasonality" not in RetailWorld(seed=8128).build().recipe


def test_a_chosen_trading_year_rides_the_recipe_and_replays() -> None:
    spec = RetailWorld(seed=8128, seasonality=profiles.named("harvest"))
    built = spec.build()
    assert built.recipe["seasonality"]["index"]["7"] == pytest.approx(
        profiles.named("harvest")[7])
    rebuilt = recipe_module.rebuild(built.recipe)
    assert [p.title for p in rebuilt.people] == [p.title for p in built.people]


def test_a_recipe_whose_trading_year_does_not_load_is_refused_not_defaulted() -> None:
    built = RetailWorld(seed=8128).build()
    broken = {**built.recipe, "seasonality": {"index": {"1": 1.0}}}
    with pytest.raises(recipe_module.RecipeError, match="trading year does not load"):
        recipe_module.rebuild(broken)


def test_the_published_registry_is_json() -> None:
    published = profiles.publish()
    assert list(published) == sorted(published)
    json.dumps(published, allow_nan=False)
    assert published["flat"]["amplitude"] == 1.0
