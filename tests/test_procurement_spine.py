"""The contracting group's organisation, held to being load-bearing.

The measured problem these tests exist to keep closed. A one-period build of
this vertical produced 52 facts across six documents, and its whole
organisational spine reached none of them: three business units, eighty-one
depots, project offices and materials yards, and both cost centres were named
by no fact and carried by no document. Six of eight spend categories were in
the same state. The estate was declared, validated, rendered — and scenery.

So the properties here are the two halves of "load-bearing", and neither is
sufficient alone:

* **it reconciles** — every site sums to its division and every division to the
  group, *exactly*, because both decompositions are allocated from one drawn
  total by largest remainder rather than drawn and hoped over; and

* **it reaches the page** — the figures land in cells of a workbook that is
  actually rendered. Minting facts nobody reports would reproduce the exact
  defect this work closes, one layer along, and the reachability assertions
  here read the **rendered bytes** rather than the IR for that reason.

Tamper tests follow the convention ``tests/test_procurement.py`` sets: every
new check is shown firing, because a check that has never failed proves only
that it compiles.
"""

from __future__ import annotations

import io
from dataclasses import replace

import pytest

from worldloom import ProcureToPayWorld, PurchaseToPayCycle, World
from worldloom.generators.procurement_estate import (
    COMMITMENT,
    COMMITMENT_ROLES,
    MATERIALS,
    MATERIALS_ROLES,
    OPENING,
    PLACED,
    SPEND,
    SPEND_ROLES,
    role_of,
)

SEED = 8128
PERIOD = "2026-03"
ESTATE_KINDS = (SPEND, COMMITMENT, MATERIALS)


@pytest.fixture(scope="module")
def world() -> World:
    return ProcureToPayWorld(seed=SEED).build().run(PurchaseToPayCycle(period=PERIOD))


@pytest.fixture(scope="module")
def compiled(world: World) -> World:
    return world.compile()


@pytest.fixture(scope="module")
def history() -> World:
    """Three consecutive months, which is what `--periods 3` builds."""
    built = ProcureToPayWorld(seed=SEED).build()
    for period in ("2026-03", "2026-04", "2026-05"):
        built = built.run(PurchaseToPayCycle(period=period))
    return built.compile()


def figures(world: World, kind: str, period: str = PERIOD) -> dict[str, float]:
    return {
        fact.subject: fact.value.amount
        for fact in world.facts
        if fact.kind == kind and fact.period == period and fact.value is not None
    }


def codes(world: World) -> set[str]:
    return {v.code for v in world.validate().violations}


def retyped(world: World, fact_id: str, **update: object) -> World:
    return replace(world, _facts=tuple(
        f.model_copy(update=update) if f.id == fact_id else f for f in world._facts
    ))


# ---------------------------------------------------------------------------
# Nothing declared reaches nothing
# ---------------------------------------------------------------------------


def test_every_division_site_category_and_cost_centre_is_named_by_a_fact(world: World) -> None:
    """The measurement this work exists to move, as an assertion.

    Written over the world's own declared entities rather than over a count, so
    widening the archetype — more divisions, a bigger estate — keeps the claim
    true instead of keeping the number true.
    """
    named = {fact.subject for fact in world.facts}
    for label, declared in (
        ("business unit", [unit.id for unit in world.business_units]),
        ("site", [site.id for site in world.sites]),
        ("spend category", [category.id for category in world.categories]),
        ("cost centre", [centre.id for centre in world.cost_centres]),
    ):
        missing = [entity for entity in declared if entity not in named]
        assert not missing, (
            f"{len(missing)} of {len(declared)} {label}(s) are named by no fact:"
            f" {', '.join(missing[:5])}"
        )


def test_the_estate_reaches_the_rendered_workbook(compiled: World) -> None:
    """Not "a document was planned to carry it" — the bytes on disk carry it.

    ``validate.carried_evidence`` already compares a plan against a compiled IR
    per intent; this goes one step further and reads the workbook openpyxl
    parses, because a corpus's deliverable is the file somebody opens. Every
    division, every depot, project office and yard, every spend category and
    both cost centres must appear as a *labelled row with a number on it*.
    """
    openpyxl = pytest.importorskip("openpyxl")

    rendered = compiled.render("xlsx")
    item = next(r for r in rendered._rendered if "spend-and-commitment" in r.path)
    book = openpyxl.load_workbook(io.BytesIO(item.payload))

    # A row whose label is the entity and whose remaining cells are not all
    # empty. "Appears in the workbook" is not enough — the defect this closes is
    # a sheet that cites and states nothing, so the row has to carry a figure.
    labelled = {
        str(row[0])
        for sheet in book.worksheets
        for row in sheet.iter_rows(values_only=True)
        if row and row[0] is not None and any(cell is not None for cell in row[1:])
    }

    for label, names in (
        ("business unit", [unit.name for unit in compiled.business_units]),
        ("site", [site.name for site in compiled.sites]),
        ("cost centre", [centre.name for centre in compiled.cost_centres]),
    ):
        missing = [name for name in names if name not in labelled]
        assert not missing, (
            f"{len(missing)} of {len(names)} {label}(s) have no row in the rendered"
            f" workbook: {', '.join(missing[:5])}"
        )
    # Categories are labelled "Division · Category", so they are matched on the
    # suffix rather than on the bare name — the workbook says which division a
    # category belongs to, which is the whole reason the row is worth reading.
    for category in compiled.categories:
        assert any(row.endswith(f"· {category.name}") for row in labelled), (
            f"spend category {category.name!r} has no row in the rendered workbook"
        )


# ---------------------------------------------------------------------------
# It reconciles, exactly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ESTATE_KINDS)
def test_divisions_sum_to_the_group_exactly(world: World, kind: str) -> None:
    """Exactly, not within a tolerance.

    ``finance.allocate`` is largest-remainder over integers, so the parts add to
    the whole with no residual — and asserting equality rather than
    ``RECONCILIATION_TOLERANCE`` is what would catch a later change to
    round-and-hope, which the validator's own tolerance would absorb.
    """
    stated = figures(world, kind)
    group = stated[world.company.id]
    divisions = [stated[unit.id] for unit in world.business_units if unit.id in stated]
    assert divisions, f"{kind} is stated at group level and at no division"
    assert sum(divisions) == group


@pytest.mark.parametrize("kind", ESTATE_KINDS)
def test_sites_sum_to_their_own_division_exactly(world: World, kind: str) -> None:
    stated = figures(world, kind)
    checked = 0
    for unit in world.business_units:
        if unit.id not in stated:
            continue
        estate = [
            stated[site.id] for site in world.sites
            if site.business_unit_id == unit.id and site.id in stated
        ]
        if not estate:
            continue
        assert sum(estate) == stated[unit.id], f"{unit.name} does not equal its estate"
        checked += 1
    assert checked, f"no division decomposes {kind} by site"


def test_a_divisions_categories_and_its_depots_reach_the_same_total(world: World) -> None:
    """Two decompositions of one figure, which is the point of having both.

    A retail month is cut by merchandise category *and* by store, and both
    reach the unit; this is that, for what a contractor buys in. Two cuts that
    both reconcile are a cross-check — two that were drawn independently would
    be two contradictions, which is why neither is drawn.
    """
    stated = figures(world, SPEND)
    for unit in world.business_units:
        if unit.id not in stated:
            continue
        by_category = sum(
            stated[c.id] for c in world.categories
            if c.business_unit_id == unit.id and c.id in stated
        )
        by_site = sum(
            stated[s.id] for s in world.sites
            if s.business_unit_id == unit.id and s.id in stated
        )
        assert by_category == stated[unit.id] == by_site, unit.name


def test_the_cost_centres_carry_the_whole_commitment(world: World) -> None:
    stated = figures(world, COMMITMENT)
    centres = [stated[centre.id] for centre in world.cost_centres if centre.id in stated]
    assert len(centres) == len(list(world.cost_centres))
    assert sum(centres) == stated[world.company.id]


def test_no_rate_is_stated_at_two_levels(world: World) -> None:
    """The rule this repository has paid for twice: a margin or a rate never sums.

    The estate carries three measures and every one of them is an amount, so
    there is nothing here for a subtotal to average — asserted rather than
    assumed, because the cheapest way to make this workbook "richer" would be to
    add a spend-per-depot percentage and quietly break every roll-up above.
    """
    for kind in ESTATE_KINDS:
        units = {fact.value.unit for fact in world.facts if fact.kind == kind and fact.value}
        assert units == {f"{world._archetype.currency}_{world._archetype.currency_unit}"}, kind


# ---------------------------------------------------------------------------
# Three kinds of place, three different measures
# ---------------------------------------------------------------------------


def test_a_project_office_commits_and_takes_no_delivery(world: World) -> None:
    offices = [site for site in world.sites if role_of(site) == "commits"]
    assert offices, "the archetype declares project offices"
    spend, commitment = figures(world, SPEND), figures(world, COMMITMENT)
    for office in offices:
        assert office.id in commitment
        assert office.id not in spend


def test_a_materials_yard_holds_stock_and_buys_nothing_in(world: World) -> None:
    """The one the archetype states structurally: a yard's revenue weight is
    zero, so an estate allocated on that weight alone would drop it — which is
    exactly how the yards came to reach nothing."""
    yards = [site for site in world.sites if role_of(site) == "holds"]
    assert yards, "the archetype declares materials yards"
    assert all(yard.revenue_weight == 0.0 for yard in yards)
    spend, commitment, materials = (
        figures(world, SPEND), figures(world, COMMITMENT), figures(world, MATERIALS)
    )
    for yard in yards:
        assert yard.id in materials
        assert yard.id not in spend and yard.id not in commitment


def test_every_site_carries_at_least_one_measure(world: World) -> None:
    """The property that makes this close the gap rather than move it."""
    stated = set()
    for kind in ESTATE_KINDS:
        stated |= set(figures(world, kind))
    missing = [site.name for site in world.sites if site.id not in stated]
    assert not missing, f"{len(missing)} site(s) carry nothing: {', '.join(missing[:5])}"


def test_the_roles_and_the_measures_they_own_agree(world: World) -> None:
    """The generator's table and the validator's are the same table."""
    for kind, owning in ((SPEND, SPEND_ROLES), (COMMITMENT, COMMITMENT_ROLES),
                         (MATERIALS, MATERIALS_ROLES)):
        for site in world.sites:
            if site.id in figures(world, kind):
                assert role_of(site) in owning, f"{site.name} states {kind}"


# ---------------------------------------------------------------------------
# The checks, firing
# ---------------------------------------------------------------------------


def test_a_depot_figure_that_breaks_its_division_trips_the_check(compiled: World) -> None:
    depot = next(
        site for site in compiled.sites
        if site.id in figures(compiled, SPEND)
    )
    fact = next(
        f for f in compiled.facts
        if f.kind == SPEND and f.subject == depot.id and f.period == PERIOD
    )
    tampered = retyped(compiled, fact.id,
                       value=fact.value.model_copy(update={"amount": fact.value.amount + 500}))
    assert "estate_does_not_reconcile" in codes(tampered)


def test_a_division_that_is_not_part_of_the_group_trips_the_check(compiled: World) -> None:
    unit = next(iter(compiled.business_units))
    fact = next(
        f for f in compiled.facts
        if f.kind == COMMITMENT and f.subject == unit.id and f.period == PERIOD
    )
    # Both decompositions under it move with it, so the failure named is the
    # group's — which is the report a reader wants: the division still agrees
    # with its own depots and no longer agrees with the company.
    tampered = retyped(compiled, fact.id,
                       value=fact.value.model_copy(update={"amount": fact.value.amount * 2}))
    assert "estate_does_not_reconcile" in codes(tampered)


def test_a_cost_centre_that_does_not_carry_the_commitment_trips_the_check(
    compiled: World,
) -> None:
    centre = next(iter(compiled.cost_centres))
    fact = next(
        f for f in compiled.facts
        if f.kind == COMMITMENT and f.subject == centre.id and f.period == PERIOD
    )
    tampered = retyped(compiled, fact.id,
                       value=fact.value.model_copy(update={"amount": 1.0}))
    assert "estate_does_not_reconcile" in codes(tampered)


def test_a_yard_billed_for_a_month_of_subcontract_spend_trips_the_check(
    compiled: World,
) -> None:
    """The check the arithmetic cannot make: a roll-up closes just as well on a
    corpus that gave every site every measure, so "a yard books no spend" has to
    be its own claim."""
    yard = next(site for site in compiled.sites if role_of(site) == "holds")
    fact = next(
        f for f in compiled.facts
        if f.kind == MATERIALS and f.subject == yard.id and f.period == PERIOD
    )
    tampered = retyped(compiled, fact.id, kind=SPEND)
    assert "site_states_a_measure_its_format_cannot_own" in codes(tampered)


# ---------------------------------------------------------------------------
# The commitment movement
# ---------------------------------------------------------------------------
#
# The increment `procurement_estate`'s docstring deferred, held to the same two
# halves as the estate itself: the movement *closes exactly* (the stock-flow
# grammar, with `==` and never a tolerance — the validator's own tolerance
# would absorb a slide back to round-and-hope, so these assertions must not
# borrow it), and it *reaches the rendered page* as a sheet a reader opens.


def test_the_movement_closes_exactly_in_every_month(history: World) -> None:
    """closing == opening + placed − received, to the unit, every period."""
    company = history.company.id
    for period in ("2026-03", "2026-04", "2026-05"):
        opening = figures(history, OPENING, period)[company]
        placed = figures(history, PLACED, period)[company]
        received = figures(history, SPEND, period)[company]
        closing = figures(history, COMMITMENT, period)[company]
        assert closing == opening + placed - received, period


def test_the_opening_balance_is_last_months_closing(history: World) -> None:
    """The carry that makes three months one account rather than three
    photographs — the whole reason the movement exists."""
    company = history.company.id
    for earlier, later in (("2026-03", "2026-04"), ("2026-04", "2026-05")):
        assert figures(history, OPENING, later)[company] \
            == figures(history, COMMITMENT, earlier)[company], (earlier, later)


def test_the_first_month_on_record_still_states_an_opening(world: World) -> None:
    """A single-period world is not exempt from the grammar: the opening is
    drawn (there is no earlier close to inherit from), the movement still
    closes, and only the carry clause is vacuously clean — correctly, because
    continuity is a claim about two observations and this world holds one.
    `test_stockflow.py` proves that vacuity is not a hole: the identity is
    still checked, and breaking it in a one-period world still fires."""
    company = world.company.id
    opening = figures(world, OPENING)[company]
    placed = figures(world, PLACED)[company]
    assert opening > 0
    assert placed >= 0
    assert figures(world, COMMITMENT)[company] \
        == opening + placed - figures(world, SPEND)[company]
    assert "stock_tears_between_periods" not in codes(world)


def test_the_movement_reaches_the_rendered_workbook(compiled: World) -> None:
    """The estate's own bar, applied to the movement: not planned, rendered.
    Every movement line must be a labelled row with a figure on it in the
    workbook openpyxl parses back off the bytes."""
    openpyxl = pytest.importorskip("openpyxl")

    rendered = compiled.render("xlsx")
    item = next(r for r in rendered._rendered if "spend-and-commitment" in r.path)
    book = openpyxl.load_workbook(io.BytesIO(item.payload))

    labelled = {
        str(row[0]): [cell for cell in row[1:] if cell is not None]
        for sheet in book.worksheets
        for row in sheet.iter_rows(values_only=True)
        if row and row[0] is not None
    }
    for label in (
        "Open commitment brought forward",
        "Orders placed in the period",
        "Receipts against orders in the period",
        "Open commitment carried forward",
    ):
        assert labelled.get(label), f"movement row {label!r} has no figure in the workbook"


def test_a_movement_that_does_not_close_trips_the_check(compiled: World) -> None:
    """The stock-flow clause, firing through `worldloom validate` itself —
    tampered at the *opening*, deliberately: the opening sits in no roll-up,
    so nothing but the movement identity can be what catches it. (Tampering
    the closing fires `estate_does_not_reconcile` too, which would prove the
    old checks rather than the new one.)"""
    company = compiled.company.id
    fact = next(
        f for f in compiled.facts
        if f.kind == OPENING and f.subject == company and f.period == PERIOD
    )
    tampered = retyped(compiled, fact.id,
                       value=fact.value.model_copy(update={"amount": fact.value.amount + 100}))
    assert "movement_does_not_close" in codes(tampered)


def test_a_book_that_tears_between_months_trips_the_check(history: World) -> None:
    """April opening at a balance March never closed at — the discontinuity
    the carry exists to refuse. The tamper moves opening and placed together
    so April's own movement still closes; only the tear can fire."""
    company = history.company.id
    opening = next(
        f for f in history.facts
        if f.kind == OPENING and f.subject == company and f.period == "2026-04"
    )
    placed = next(
        f for f in history.facts
        if f.kind == PLACED and f.subject == company and f.period == "2026-04"
    )
    tampered = retyped(history, opening.id,
                       value=opening.value.model_copy(update={"amount": opening.value.amount + 100}))
    tampered = retyped(tampered, placed.id,
                       value=placed.value.model_copy(update={"amount": placed.value.amount - 100}))
    found = codes(tampered)
    assert "stock_tears_between_periods" in found
    assert "movement_does_not_close" not in found


def test_a_book_too_heavy_for_the_target_runs_down_rather_than_cancelling(
    world: World,
) -> None:
    """The movement's one corner, held as a claim: when the opening book is
    heavier than the drawn target could reach without *negative* placing — an
    order-cancellation workflow this vertical does not model, the same posture
    as the over-receipt refusal — the group places nothing and the book runs
    down to opening less receipts, still closing exactly. Exercised by seed
    8128 at twelve periods (one month places zero) and pinned here directly so
    it does not depend on which seed happens to reach the branch."""
    from datetime import datetime, timezone

    from worldloom.generators import procurement_estate
    from worldloom.generators.stockflow import close
    from worldloom.ids import Minter
    from worldloom.rng import Rng

    roles = dict(world._roles)
    archetype = world._archetype
    heavy = 10**9  # far above anything the cover band can draw
    position = procurement_estate.generate(
        Rng(1).derive("estate"), Minter(),
        period="2030-01",
        company_id=world.company.id,
        unit_ids={unit.key: roles[f"unit_{unit.key}"] for unit in archetype.units},
        unit_shares={unit.key: unit.share for unit in archetype.units},
        categories=list(world.categories),
        sites=list(world.sites),
        commercial_cost_centre_id=roles["cc_commercial"],
        finance_cost_centre_id=roles["cc_finance"],
        annual_revenue=world._annual_revenue,
        money_unit="AUD_thousands",
        at=datetime(2030, 2, 4, tzinfo=timezone.utc),
        event_id="EV-0001",
        procure_system_id=roles["sys_procure"],
        receipting_system_id=roles["sys_receipting"],
        general_ledger_id=roles["sys_general_ledger"],
        opening_commitment=heavy,
    )
    assert position.placed_total == 0
    assert position.commitment_total == heavy - position.spend_total
    assert position.commitment_total == close(
        position.opening_total, [position.placed_total], [position.spend_total]
    )
    assert position.commitment_total > 0


def test_a_dropped_opening_is_a_violation_not_a_silence(compiled: World) -> None:
    """The decoration hazard: a verifier whose population is 'whoever states
    an opening' goes vacuously clean when the opening facts vanish. The check
    group pins the company, so the gap is loud."""
    company = compiled.company.id
    fact = next(
        f for f in compiled.facts
        if f.kind == OPENING and f.subject == company and f.period == PERIOD
    )
    tampered = replace(compiled, _facts=tuple(
        f for f in compiled._facts if f.id != fact.id
    ))
    assert "movement_has_no_opening" in codes(tampered)


# ---------------------------------------------------------------------------
# A history, and determinism
# ---------------------------------------------------------------------------


def test_three_months_validate(history: World) -> None:
    report = history.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_each_month_states_its_own_position(history: World) -> None:
    """Not one month photocopied: the position is drawn per period, so three
    closes carry three different committed balances."""
    totals = {
        period: figures(history, COMMITMENT, period)[history.company.id]
        for period in ("2026-03", "2026-04", "2026-05")
    }
    assert len(set(totals.values())) == 3, totals


def test_the_estate_reconciles_in_every_month(history: World) -> None:
    for period in ("2026-03", "2026-04", "2026-05"):
        for kind in ESTATE_KINDS:
            stated = figures(history, kind, period)
            assert stated, f"{kind} is stated nowhere in {period}"
            divisions = [
                stated[unit.id] for unit in history.business_units if unit.id in stated
            ]
            assert sum(divisions) == stated[history.company.id], (period, kind)


def test_the_position_is_the_same_position_every_time() -> None:
    """Same seed, same figures — no clock, no `random`, no set reaching output."""
    def built() -> list[tuple[str, str, float]]:
        world = ProcureToPayWorld(seed=SEED).build().run(PurchaseToPayCycle(period=PERIOD))
        return [
            (fact.id, fact.subject, fact.value.amount)
            for fact in world.facts
            if fact.kind in ESTATE_KINDS and fact.value is not None
        ]

    assert built() == built()
