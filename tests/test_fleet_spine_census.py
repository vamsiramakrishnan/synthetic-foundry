"""The spine census `fleet._survey` takes must be reachability's own count.

`_survey` used to call `validate.reachability(world)` per member and read
`checks_run` off the verdict — a second full validator per world, for findings
`world.validate()` had already filed as advisories. It now reads the advisories
and takes the *declared* count directly off `validate.REACHABLE_KINDS`, which
is a duplicate of the group's own counting: one check per entity of every
reachable kind, only when the corpus has compiled documents.

A duplicate computation is a computation that can drift — a kind added to the
group, a filter moved above the `checks += 1` — and the fleet spine share would
then quietly disagree with the reading `tests/test_reachability.py` ratchets.
This pin makes the drift loud: the census and the verdict's `checks_run` are
asserted equal on both shapes the census branches on (compiled and plan-only),
on two engines, so whichever side moves first fails here by name.
"""

from __future__ import annotations

from worldloom import validate
from worldloom.banking import BankingWorld
from worldloom.banking_scenarios import QuarterlyCapitalReturn
from worldloom.narrative import DeterministicProvider
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _census(world) -> int:  # type: ignore[no-untyped-def]
    """Exactly the expression `fleet._survey` uses for its `declared` count."""
    if world.artifact_irs:
        return sum(
            len(list(getattr(world, kind))) for kind in validate.REACHABLE_KINDS
        )
    return 0


def test_the_census_is_reachabilitys_own_count_on_a_compiled_retail_world() -> None:
    world = (
        RetailWorld(seed=8128).build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True))
        .narrate(DeterministicProvider())
    )
    verdict = validate.reachability(world)
    assert _census(world) == verdict.checks_run
    assert verdict.checks_run > 0  # a vacuous equality would pin nothing


def test_the_census_is_reachabilitys_own_count_on_a_second_engine() -> None:
    world = (
        BankingWorld(seed=8128).build()
        .run(QuarterlyCapitalReturn(period="2026-03"))
        .narrate(DeterministicProvider())
    )
    assert _census(world) == validate.reachability(world).checks_run


def test_a_plan_only_world_is_checked_zero_times_and_counted_zero() -> None:
    """The group's early return is the census's `if world.artifact_irs` guard."""
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    assert not world.artifact_irs
    assert _census(world) == 0
    assert validate.reachability(world).checks_run == 0
