"""The cohort check group, shown failing.

Every check in ``worldloom.cohorts`` is tamper-tested here, following the
banking suite's convention and for its reason: a check that has never failed
proves only that it compiles. Each test breaks one thing about a grid that is
otherwise correct — a cell that does not roll up, a hole, a duplicate, a cell
off the declared axis, a cohort the valuation could not have seen — and asserts
the group names it.

The grids are built by hand rather than run through ``episodes.run``, which is
deliberate. A tamper test needs to produce a *defective* grid, and the runner
cannot: it allocates by largest remainder, mints one cell per declared cohort
and derives the cohort periods from the axis, so every defect these checks
exist to catch is one the runner is structurally incapable of making. Building
the facts directly is what lets the defect exist at all.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from worldloom import cohorts, episodes
from worldloom.models import Authority, CanonicalFact, Company, Quantity
from worldloom.world import World

MONEY = "AUD_millions"
VALUATION = "2026-03"
NEXT_VALUATION = "2026-06"

#: The shipped insurer's own axis: four accident quarters, three months apart,
#: the newest a quarter behind the valuation. At a 2026-03 valuation it
#: resolves to 2025-03/06/09/12 — the grid `insurance_scenarios` computes by
#: hand, which is what makes these tests about the real shape.
AXIS = episodes.CohortSpec(
    name="accident_quarter", count=4, spacing_months=3, lag_months=3
)

PARENT = "reserves.central_estimate_total"
CELL = "reserves.ultimate"
PRIOR = "reserves.ultimate_at_prior_valuation"

SPEC = episodes.EpisodeSpec(
    name="TriangleProof",
    domain="insurance",
    period="quarter",
    cohorts=[AXIS],
    fact_kinds=[
        episodes.FactKindSpec(
            kind=PARENT, value_type="money", unit=MONEY,
            invariants=[episodes.Invariant(kind="holds-at")],
        ),
        episodes.FactKindSpec(
            kind=CELL, value_type="money", unit=MONEY, cohort=AXIS.name,
            derive=f"allocation_of({PARENT})",
            invariants=[
                episodes.Invariant(kind="holds-at"),
                episodes.Invariant(kind="rolls-up-to", operands=[PARENT]),
            ],
        ),
        # A cohort kind with no parent, so the grid checks are exercised on a
        # kind the roll-up never reaches — `prior_in_cohort`'s shape, which is
        # a real column of the reserving triangle and owes nobody a sum.
        episodes.FactKindSpec(
            kind=PRIOR, value_type="money", unit=MONEY, cohort=AXIS.name,
            derive=f"prior_in_cohort({CELL})",
            invariants=[episodes.Invariant(kind="holds-at")],
        ),
    ],
)

SUBJECT = "CO-0001"
#: The allocation of 1,000 across four cohorts, oldest first. Whole units and
#: summing exactly, because that is what largest remainder produces and the
#: point of the tamper tests is to move one of them.
CELLS = (400.0, 300.0, 200.0, 100.0)


def _at(valuation: str, *, hours: int) -> datetime:
    """A moment inside *valuation*'s run — a week after the quarter ends."""
    year, month = (int(part) for part in valuation.split("-"))
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return datetime(year, month, 7, tzinfo=UTC) + timedelta(hours=hours)


def _fact(fact_id, kind, period, amount, at, *, supersedes=None):
    return CanonicalFact(
        id=fact_id, kind=kind, subject=SUBJECT, period=period,
        value=Quantity(amount=amount, unit=MONEY),
        valid_from=at, authority=Authority.CONFIRMED, supersedes=supersedes,
    )


def grid(valuation: str = VALUATION, *, run: int = 0, parent_first: bool = False):
    """One correct valuation: the parent total and the four cells under it.

    ``parent_first`` mints the total ahead of its cells — the ordering the
    reserving episode does *not* use (it freezes the booked total last) and
    which a check anchored on "the latest cell at or before the parent" would
    read as an empty grid.
    """
    ids = iter(f"FACT-{run}{n:03d}" for n in range(1, 99))
    parent_at = _at(valuation, hours=9 if parent_first else 11)
    cells_at = _at(valuation, hours=10)
    facts = [_fact(next(ids), PARENT, valuation, sum(CELLS), parent_at)]
    for cohort, amount in zip(episodes.cohort_periods(valuation, AXIS), CELLS):
        facts.append(_fact(next(ids), CELL, cohort, amount, cells_at))
    return facts


def codes(facts) -> set[str]:
    found, _ = cohorts.check(facts, [SPEC])
    return {v.code for v in found}


def detail(facts, code: str) -> str:
    found, _ = cohorts.check(facts, [SPEC])
    return next(v.detail for v in found if v.code == code)


# ---------------------------------------------------------------------------
# The correct grid, and the group's cost on a world that has none
# ---------------------------------------------------------------------------


def test_a_correct_grid_passes_and_is_actually_checked() -> None:
    found, checks = cohorts.check(grid(), [SPEC])
    assert found == []
    # Nine: four cohorts against the declared grid, four period comparisons,
    # one roll-up. Pinned because "no violations" is also what a group that
    # never ran returns, and those two have to be distinguishable.
    assert checks == 9


def test_the_group_costs_nothing_on_a_world_that_never_ran_the_episode() -> None:
    unrelated = [
        _fact("FACT-9001", "financial.revenue.actual", VALUATION, 12.0, _at(VALUATION, hours=9))
    ]
    assert cohorts.check(unrelated, [SPEC]) == ([], 0)
    assert cohorts.check([], [SPEC]) == ([], 0)


def test_a_spec_with_no_cohort_axis_is_skipped_entirely() -> None:
    """Every episode shipped before the axis existed declares no cohorts, and
    this group must be a strict no-op on all of them."""
    flat = SPEC.model_copy(update={"cohorts": []})
    assert cohorts.check(grid(), [flat]) == ([], 0)


# ---------------------------------------------------------------------------
# rolls-up-to
# ---------------------------------------------------------------------------


def test_a_cell_that_does_not_roll_up_is_caught() -> None:
    facts = grid()
    facts[1] = facts[1].model_copy(update={"value": Quantity(amount=399.99, unit=MONEY)})
    assert "cohort_rollup_short" in codes(facts)
    # To the cent, and the shortfall is reported rather than left to be
    # worked out — a reconciliation failure that does not say by how much
    # sends the reader back to the ledger to subtract two numbers.
    assert "0.01" in detail(facts, "cohort_rollup_short")


def test_a_cent_is_a_defect_and_float_noise_is_not() -> None:
    facts = grid()
    noise = facts[1].model_copy(
        update={"value": Quantity(amount=400.0 + 1e-9, unit=MONEY)}
    )
    assert "cohort_rollup_short" not in codes([*facts[:1], noise, *facts[2:]])


def test_a_valuation_whose_grid_was_never_minted_is_caught() -> None:
    """The whole-grid case: the per-cohort hole check has no column to look in,
    so without this the second valuation's parent reconciles against nothing
    and reports success."""
    facts = [*grid(), *grid(NEXT_VALUATION, run=1)]
    kept = [f for f in facts if not (f.kind == CELL and f.valid_from > _at(VALUATION, hours=23))]
    assert "cohort_grid_absent" in codes(kept)
    assert NEXT_VALUATION in detail(kept, "cohort_grid_absent")


def test_the_second_valuation_does_not_double_count_the_first() -> None:
    """Two valuations, the second superseding the first cell by cell and
    leaving the predecessor's window open — which `episodes.run` does, and
    which makes both versions ``holds_at`` the later parent. A roll-up that
    summed what holds would find twice the grid."""
    first = grid()
    second = grid(NEXT_VALUATION, run=1)
    assert cohorts.check([*first, *second], [SPEC])[0] == []


def test_the_total_may_be_minted_before_its_own_cells() -> None:
    assert cohorts.check(grid(parent_first=True), [SPEC])[0] == []


# ---------------------------------------------------------------------------
# Grid completeness
# ---------------------------------------------------------------------------


def test_a_hole_in_the_grid_is_caught() -> None:
    facts = [f for f in grid() if f.period != "2025-09"]
    found = codes(facts)
    assert "cohort_grid_hole" in found
    # And the roll-up over it fails too, which is the argument for the check:
    # a hole is not a smaller grid, it is a total nobody can reconcile.
    assert "cohort_rollup_short" in found
    assert "2025-09" in detail(facts, "cohort_grid_hole")


def test_a_hole_is_caught_in_a_kind_with_no_parent_to_reconcile_against() -> None:
    facts = grid()
    for cohort, amount in zip(episodes.cohort_periods(VALUATION, AXIS)[:3], CELLS):
        facts.append(_fact(f"FACT-2{cohort[-2:]}", PRIOR, cohort, amount, _at(VALUATION, hours=10)))
    assert "cohort_grid_hole" in codes(facts)


def test_two_cells_for_one_cohort_are_caught() -> None:
    facts = grid()
    twin = facts[1].model_copy(update={"id": "FACT-9902"})
    assert "cohort_cell_duplicated" in codes([*facts, twin])


def test_a_cell_off_the_declared_axis_is_caught() -> None:
    facts = grid()
    stray = facts[1].model_copy(update={"id": "FACT-9903", "period": "2025-04"})
    found = codes([*facts, stray])
    assert "cohort_off_grid" in found
    assert "2025-04" in detail([*facts, stray], "cohort_off_grid")


def test_a_cell_carrying_no_cohort_at_all_is_caught() -> None:
    """A cohort kind is lint-refused from being period-scoped precisely so this
    cannot happen; the check is what says so about the facts."""
    facts = grid()
    unkeyed = facts[1].model_copy(update={"id": "FACT-9904", "period": None})
    found = codes([*facts, unkeyed])
    assert "cohort_off_grid" in found
    assert "no cohort at all" in detail([*facts, unkeyed], "cohort_off_grid")


# ---------------------------------------------------------------------------
# Cohort-period sanity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cohort", ["2026-03", "2026-06"])
def test_a_cohort_at_or_after_its_valuation_is_caught(cohort: str) -> None:
    facts = grid()
    ahead = facts[1].model_copy(update={"id": "FACT-9905", "period": cohort})
    found = codes([*facts, ahead])
    assert "cohort_after_valuation" in found


def test_the_newest_declared_cohort_is_not_flagged() -> None:
    """The lag is what keeps the newest cohort behind the valuation, and a
    check that failed it would fail every correct grid the axis produces."""
    assert "cohort_after_valuation" not in codes(grid())


# ---------------------------------------------------------------------------
# The registration, end to end
# ---------------------------------------------------------------------------


def test_the_registered_group_reaches_the_validator(monkeypatch) -> None:
    """Through `world.validate()` rather than `cohorts.check`, because the
    registration is the half that decides whether any of this ever runs — a
    check group nobody registered passes on every machine."""
    monkeypatch.setattr(cohorts, "_specs", lambda: (SPEC,))
    facts = grid()
    facts[1] = facts[1].model_copy(update={"value": Quantity(amount=1.0, unit=MONEY)})
    world = World(
        company=Company(
            id=SUBJECT, name="Rheinmark", industry="General insurance",
            headquarters="Munich", fiscal_year_start_month=1, employees_total=1,
        ),
        _facts=tuple(facts),
    )
    report = world.validate()
    assert "cohort_rollup_short" in {v.code for v in report.violations}
    assert {v.group for v in report.violations if v.code == "cohort_rollup_short"} == {"cohort"}


def test_the_group_is_registered_under_a_name_of_its_own() -> None:
    from worldloom import validate as validate_module

    assert validate_module._DOMAIN_CHECKS["cohorts"] is cohorts._checks


def test_installed_specs_are_read_in_a_fixed_order(monkeypatch) -> None:
    """The registry is a dict, and two processes installed in either order have
    to produce the same report."""
    other = SPEC.model_copy(update={"name": "AnotherProof"})
    monkeypatch.setattr(episodes, "_LOADED", {"TriangleProof": SPEC, "AnotherProof": other})
    assert [spec.name for spec in cohorts._specs()] == ["AnotherProof", "TriangleProof"]


def test_replace_keeps_the_world_shape(monkeypatch) -> None:
    """`dataclasses.replace` on a World is how every other tamper test builds
    its defect; this pins that the cohort group sees the replaced facts."""
    monkeypatch.setattr(cohorts, "_specs", lambda: (SPEC,))
    world = World(
        company=Company(
            id=SUBJECT, name="Rheinmark", industry="General insurance",
            headquarters="Munich", fiscal_year_start_month=1, employees_total=1,
        ),
        _facts=tuple(grid()),
    )
    assert "cohort_grid_hole" not in {v.code for v in world.validate().violations}
    holed = replace(world, _facts=tuple(f for f in world._facts if f.period != "2025-06"))
    assert "cohort_grid_hole" in {v.code for v in holed.validate().violations}
