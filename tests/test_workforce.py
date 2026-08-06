"""Workforce scale is causal, temporal, and recipe-replayable."""

from __future__ import annotations

from collections import Counter

import pytest
from typer.testing import CliRunner

from worldloom import (
    BankingWorld,
    InsuranceWorld,
    ProcureToPayWorld,
    RetailWorld,
    World,
    timeline,
)
from worldloom.cli import app
from worldloom.recipe import rebuild


@pytest.mark.parametrize(
    "builder",
    (RetailWorld, BankingWorld, InsuranceWorld, ProcureToPayWorld),
)
def test_stated_headcount_reaches_every_engine(builder) -> None:  # type: ignore[no-untyped-def]
    world = builder(seed=8128, employees=54_321).build()
    assert world.company.employees_total == 54_321
    assert len(world.people) < world.company.employees_total


def test_stated_headcount_cannot_contradict_the_named_roster() -> None:
    with pytest.raises(ValueError, match="smaller than the .* people the organisation must model"):
        RetailWorld(seed=8128, employees=10).build()


@pytest.mark.parametrize(
    ("initial", "final", "periods", "expected"),
    (
        (90_000, 96_000, 3, (90_000, 93_000, 96_000)),
        (100, 80, 4, (100, 93, 87, 80)),
        (777, 777, 5, (777, 777, 777, 777, 777)),
    ),
)
def test_workforce_interpolation_is_exact_and_bidirectional(
    initial: int, final: int, periods: int, expected: tuple[int, ...],
) -> None:
    assert timeline.Workforce(initial, final).headcounts(periods) == expected


def test_one_period_cannot_hide_a_workforce_move() -> None:
    with pytest.raises(ValueError, match="one-period trajectory cannot move"):
        timeline.Workforce(100, 101).headcounts(1)


def test_workforce_change_is_documented_valid_and_replayable() -> None:
    initial = RetailWorld(seed=8128, employees=90_000).build()
    workforce = timeline.Workforce(90_000, 96_000)
    history = timeline.sample(
        roster=timeline.Roster.of(initial),
        start="2026-03",
        periods=3,
        seed=8128,
        density=timeline.QUIET,
        workforce=workforce,
    )

    assert history.outline() == (
        ("2026-03", "MonthEndClose"),
        ("2026-03", "WorkforceChange"),
        ("2026-04", "MonthEndClose"),
        ("2026-04", "WorkforceChange"),
        ("2026-05", "MonthEndClose"),
    )

    world = history.run(initial)
    assert world.company.employees_total == 96_000
    assert [fact.value.amount for fact in world.facts if fact.kind == "org.headcount"] == [
        93_000,
        96_000,
    ]
    assert [fact.value.amount for fact in world.facts if fact.kind == "org.headcount.delta"] == [
        3_000,
        3_000,
    ]
    assert sum(intent.artifact_type == "personnel_notice" for intent in world.artifact_intents) >= 2
    world.validate().raise_if_failed()

    replayed = rebuild(world.recipe)
    assert replayed.company.employees_total == world.company.employees_total
    assert replayed.recipe == world.recipe
    assert replayed.facts == world.facts


def test_large_workforces_create_more_sampled_episodes_not_linear_explosion() -> None:
    def shape(total: int) -> Counter[str]:
        world = RetailWorld(seed=8128, employees=total).build()
        sampled = timeline.sample(
            roster=timeline.Roster.of(world),
            start="2026-01",
            periods=12,
            seed=8128,
            density=timeline.STEADY,
            workforce=timeline.Workforce(total, total),
        )
        return Counter(type(step).__name__ for step in sampled)

    small = shape(800)
    large = shape(80_000)
    assert large["MonthEndClose"] == small["MonthEndClose"] == 12
    assert large["Departure"] > small["Departure"]
    assert large["Reorganisation"] > small["Reorganisation"]
    assert sum(large.values()) < 24


def test_cli_build_records_the_exact_workforce_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "workforce"
    result = CliRunner().invoke(app, [
        "build",
        "--seed", "8128",
        "--employees", "90000",
        "--headcount-end", "96000",
        "--periods", "3",
        "--no-incident",
        "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert "90,000 → 93,000 → 96,000" in result.output

    world = World.load(out)
    assert world.company.employees_total == 96_000
    assert [
        step["headcount"] for step in world.recipe["steps"]
        if step["scenario"] == "WorkforceChange"
    ] == [93_000, 96_000]
