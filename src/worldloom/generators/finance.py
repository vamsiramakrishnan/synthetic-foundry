"""The financial generator.

Reconciles by construction rather than by arithmetic performed after the fact.
Unit figures are drawn first; group figures are *sums*, never independent draws;
variances are differences; percentages are derived from the rounded amounts they
describe. There is no step at which a total is stated and hoped to match.

That ordering is the whole point. A generator that drew a group total and then
tried to make units add up to it would eventually produce a corpus where a board
deck disagrees with its own workbook, which is the failure the project exists to
eliminate.

The same rule runs downward. A retailer's month does not stop at three divisions:
it decomposes by merchandise category and, independently, by store. Both
decompositions are generated here by *allocating* the unit total rather than by
drawing category and store figures and summing them, because allocation cannot
drift and summation can. ``allocate`` uses largest-remainder so the integer parts
add to the integer whole exactly — no residual line, no rounding note.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..ids import Minter
from ..models import Authority, CanonicalFact, Category, Quantity, Site
from ..rng import Rng

MONEY = "AUD_thousands"
PERCENT = "percent"
BPS = "bps"

#: Trading index by calendar month. A grocer's December is not its February, and a
#: twelve-month trend that ignores that reads as noise around a flat line rather
#: than as a business. Shape only — the amplitude is generic retail seasonality.
SEASONALITY: dict[int, float] = {
    1: 0.96, 2: 0.88, 3: 0.97, 4: 0.98, 5: 0.99, 6: 0.99,
    7: 1.00, 8: 0.99, 9: 0.98, 10: 1.01, 11: 1.04, 12: 1.21,
}


@dataclass(frozen=True)
class Financials:
    """What the financial generator produces.

    Two views of one fact set, because they serve incompatible readers. The
    workbook wants every level of the hierarchy; a narrative request must never
    be handed four thousand facts, so ``headline`` is the group-and-unit cut for
    the reporting period — the figures a memo would actually cite.
    """

    facts: tuple[CanonicalFact, ...]
    headline: tuple[CanonicalFact, ...]
    periods: tuple[str, ...]
    """Every period covered, oldest first. The last is the reporting period."""


def allocate(total: int, weights: Sequence[float]) -> list[int]:
    """Split *total* across *weights* so the parts sum to it exactly.

    Largest-remainder rather than round-and-hope: rounding each share
    independently leaves a residual of up to half a unit per row, which at 34
    categories is a reconciliation failure the validator would (correctly) refuse.
    Ties break on index so the result depends on the data and not on sort
    stability.
    """
    pool = sum(weights)
    if pool <= 0:
        raise ValueError("cannot allocate across weights that sum to zero or less")
    raw = [total * weight / pool for weight in weights]
    parts = [math.floor(value) for value in raw]
    remainder = total - sum(parts)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - parts[i]), i))
    for index in order[:remainder]:
        parts[index] += 1
    return parts


def previous_periods(period: str, count: int) -> tuple[str, ...]:
    """The *count* periods before ``YYYY-MM``, oldest first."""
    year, month = (int(part) for part in period.split("-"))
    out: list[str] = []
    for _ in range(count):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        out.append(f"{year:04d}-{month:02d}")
    return tuple(reversed(out))


def _closed_at(period: str, template: datetime) -> datetime:
    """When a period's numbers became known: four days after it ended.

    Derived from the period rather than from the clock, and from the reporting
    close only for its time of day, so a prior month's figures carry a date that
    precedes the artifacts citing them.
    """
    year, month = (int(part) for part in period.split("-"))
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    first = datetime(year, month, 1, template.hour, template.minute, tzinfo=template.tzinfo)
    return first + timedelta(days=3)


def _season(period: str) -> float:
    return SEASONALITY[int(period.split("-")[1])]


class _Ledger:
    """Accumulates facts, so the generator reads as arithmetic rather than plumbing."""

    def __init__(self, minter: Minter, money_unit: str = MONEY) -> None:
        self.minter = minter
        self.facts: list[CanonicalFact] = []
        # A pack's currency was already a build-time field (`Company.currency`/
        # `currency_unit`) that this generator quietly ignored — every fact it
        # minted said "AUD_thousands" regardless, which is only invisible
        # because both stock archetypes happen to use that unit. `money_unit`
        # defaults to `MONEY` so a caller that never passes it (there is none
        # left; every call site now threads the archetype's own unit) still
        # gets the old constant, which is what keeps stock output unchanged.
        self.money_unit = money_unit

    def money(self, kind: str, subject: str, period: str, amount: int, *,
              at: datetime, source: str, event: str | None,
              lore: list[str] | None = None) -> CanonicalFact:
        return self.measure(kind, subject, period, amount, self.money_unit,
                            at=at, source=source, event=event, lore=lore)

    def measure(self, kind: str, subject: str, period: str, amount: float, unit: str, *,
                at: datetime, source: str, event: str | None,
                lore: list[str] | None = None) -> CanonicalFact:
        fact = CanonicalFact(
            id=self.minter.next("FACT"),
            kind=kind,
            subject=subject,
            period=period,
            value=Quantity(amount=amount, unit=unit),
            valid_from=at,
            authority=Authority.SYSTEM_OF_RECORD,
            source_system=source,
            event_id=event,
            lore_ids=lore or [],
        )
        self.facts.append(fact)
        return fact


def _pct(profit: int, revenue: int) -> float:
    return round(profit / revenue * 100, 2) if revenue else 0.0


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    unit_ids: dict[str, str],
    unit_shares: dict[str, float],
    categories: tuple[Category, ...] = (),
    sites: tuple[Site, ...] = (),
    erp_id: str,
    commerce_id: str,
    pos_id: str | None = None,
    finalised_at: datetime,
    close_event_id: str,
    annual_revenue: int,
    lore_by_target: dict[str, list[str]],
    comparative_months: int = 0,
    money_unit: str = MONEY,
) -> Financials:
    """Generate a company's financial facts for one period, plus a trend behind it.

    ``lore_by_target`` maps a constraint target to the lore IDs that touch it, so
    a generated fact records *why* it looks the way it does — a Digital forecast
    miss cites the replatform that made forecasting unreliable.

    ``comparative_months`` adds prior periods at actual only. A trend needs
    actuals; it does not need every prior month's budget, and generating them
    would triple the fact count to fill a column nobody reads.

    ``money_unit`` is the archetype's own ``f"{currency}_{currency_unit}"`` —
    every retail archetype in this repository resolves to ``MONEY``, which is
    what keeps stock output unchanged, but a pack with a different currency
    now gets facts that actually say so instead of a silent "AUD_thousands".
    """
    ledger = _Ledger(minter, money_unit=money_unit)
    monthly = annual_revenue // 12
    key_of_unit = {unit_id: key for key, unit_id in unit_ids.items()}

    cats_of: dict[str, list[Category]] = {unit_id: [] for unit_id in unit_ids.values()}
    for category in categories:
        if category.business_unit_id in cats_of:
            cats_of[category.business_unit_id].append(category)

    # Zero-weight sites are dropped rather than allocated zero, because a
    # distribution centre should have no revenue row at all — a row of zeroes in a
    # store P&L reads as a store that sold nothing, which is a different claim.
    estate_of: dict[str, list[Site]] = {unit_id: [] for unit_id in unit_ids.values()}
    for site in sites:
        if site.business_unit_id in estate_of and site.revenue_weight > 0:
            estate_of[site.business_unit_id].append(site)

    def draw_revenue(target_period: str) -> tuple[dict[str, int], dict[str, int]]:
        """Unit budget and actual for a period. Actual is skewed adverse."""
        budget: dict[str, int] = {}
        actual: dict[str, int] = {}
        season = _season(target_period)
        for key in unit_ids:
            unit_rng = rng.derive(f"revenue/{target_period}/{key}")
            unit_budget = int(round(monthly * unit_shares[key] * season, -2))
            miss_pct = unit_rng.number(-0.065, 0.015, places=4)
            budget[key] = unit_budget
            actual[key] = int(round(unit_budget * (1 + miss_pct), -2))
        return budget, actual

    def unit_margin(unit_id: str, fallback: float) -> float:
        """A unit's budgeted margin, as the revenue-weighted blend of its categories.

        Derived rather than tabulated: a unit's margin is what its mix makes it,
        so a category structure and a unit margin can never disagree here.
        """
        members = cats_of.get(unit_id, [])
        pool = sum(c.revenue_share for c in members)
        if not members or pool <= 0:
            return fallback
        return sum(c.margin_profile * c.revenue_share for c in members) / pool

    def split_revenue(unit_id: str, amount: int, label: str) -> list[int]:
        members = cats_of.get(unit_id, [])
        if not members:
            return []
        return allocate(amount, [c.revenue_share for c in members])

    def emit_level(target_period: str, at: datetime, event: str | None, *,
                   full: bool) -> tuple[dict[str, int], dict[str, int]]:
        """One period's figures, from category up to group.

        ``full`` adds budget, variance, and the store estate. A comparative month
        gets actuals only.
        """
        budget, actual = draw_revenue(target_period)
        group_budget, group_actual = sum(budget.values()), sum(actual.values())

        # -- revenue, category then unit then group ------------------------
        cat_actual: dict[str, int] = {}
        cat_budget: dict[str, int] = {}
        for key, unit_id in unit_ids.items():
            members = cats_of.get(unit_id, [])
            for category, share in zip(members, split_revenue(unit_id, actual[key], "actual")):
                cat_actual[category.id] = share
            for category, share in zip(members, split_revenue(unit_id, budget[key], "budget")):
                cat_budget[category.id] = share

        for category in categories:
            if category.id in cat_actual:
                ledger.money("financial.revenue.actual", category.id, target_period,
                             cat_actual[category.id], at=at, source=erp_id, event=event)
        for unit_id in unit_ids.values():
            ledger.money("financial.revenue.actual", unit_id, target_period,
                         actual[key_of_unit[unit_id]], at=at, source=erp_id, event=event)
        ledger.money("financial.revenue.actual", company_id, target_period, group_actual,
                     at=at, source=erp_id, event=event)

        if full:
            for category in categories:
                if category.id in cat_budget:
                    ledger.money("financial.revenue.budget", category.id, target_period,
                                 cat_budget[category.id], at=at, source=erp_id, event=event)
            for unit_id in unit_ids.values():
                ledger.money("financial.revenue.budget", unit_id, target_period,
                             budget[key_of_unit[unit_id]], at=at, source=erp_id, event=event)
            ledger.money("financial.revenue.budget", company_id, target_period, group_budget,
                         at=at, source=erp_id, event=event)

            for category in categories:
                if category.id in cat_actual:
                    ledger.money("financial.revenue.variance", category.id, target_period,
                                 cat_actual[category.id] - cat_budget[category.id],
                                 at=at, source=erp_id, event=event)
            for key, unit_id in unit_ids.items():
                ledger.money("financial.revenue.variance", unit_id, target_period,
                             actual[key] - budget[key], at=at, source=erp_id, event=event,
                             lore=lore_by_target.get(f"forecast_miss/{key}", []))
            ledger.money("financial.revenue.variance", company_id, target_period,
                         group_actual - group_budget, at=at, source=erp_id, event=event)

            # -- the store estate ------------------------------------------
            # Stores decompose the same unit revenue that categories do, which is
            # why they are allocated from the unit total rather than drawn: two
            # independent decompositions that each sum to the unit are a real
            # cross-check, two independently drawn ones are two contradictions.
            for key, unit_id in unit_ids.items():
                estate = estate_of.get(unit_id, [])
                if not estate:
                    continue
                weights = [site.revenue_weight for site in estate]
                for site, amount in zip(estate, allocate(actual[key], weights)):
                    ledger.money("financial.revenue.actual", site.id, target_period, amount,
                                 at=at, source=pos_id or erp_id, event=event)

                site_budget = allocate(budget[key], weights)
                for site, amount in zip(estate, site_budget):
                    ledger.money("financial.revenue.budget", site.id, target_period, amount,
                                 at=at, source=pos_id or erp_id, event=event)
                # Store-versus-budget is the most-read report in a retailer, and
                # stating it makes the variance on the sheet checkable: without
                # the fact, the workbook's `=actual-budget` has nothing to
                # disagree with.
                site_actual = allocate(actual[key], weights)
                for site, gap in zip(estate, [a - b for a, b in zip(site_actual, site_budget)]):
                    ledger.money("financial.revenue.variance", site.id, target_period, gap,
                                 at=at, source=pos_id or erp_id, event=event)

        # -- gross profit --------------------------------------------------
        gp_budget: dict[str, int] = {}
        gp_actual: dict[str, int] = {}
        cat_gp_actual: dict[str, int] = {}
        cat_gp_budget: dict[str, int] = {}
        for key, unit_id in unit_ids.items():
            margin_rng = rng.derive(f"margin/{target_period}/{key}")
            budget_margin = unit_margin(unit_id, margin_rng.number(0.20, 0.34, places=4))
            erosion = margin_rng.number(0.002, 0.020, places=4)
            gp_budget[key] = int(round(budget[key] * budget_margin))
            gp_actual[key] = int(round(actual[key] * (budget_margin - erosion)))

            members = cats_of.get(unit_id, [])
            if not members:
                continue
            # Erosion is not uniform across a range — promotional depth lands on
            # some categories and not others — so each category gets its own, and
            # the unit total is then allocated across the resulting weights. The
            # spread is real; the total is still exactly what was drawn above.
            eroded = [
                max(
                    c.margin_profile - margin_rng.number(-0.004, 2 * erosion, places=4),
                    0.001,
                )
                for c in members
            ]
            budget_weights = [cat_budget[c.id] * c.margin_profile for c in members]
            actual_weights = [cat_actual[c.id] * m for c, m in zip(members, eroded)]
            for category, amount in zip(members, allocate(gp_actual[key], actual_weights)):
                cat_gp_actual[category.id] = amount
            if full:
                for category, amount in zip(members, allocate(gp_budget[key], budget_weights)):
                    cat_gp_budget[category.id] = amount

        group_gp_budget, group_gp_actual = sum(gp_budget.values()), sum(gp_actual.values())

        for category in categories:
            if category.id in cat_gp_actual:
                ledger.money("financial.gross_profit.actual", category.id, target_period,
                             cat_gp_actual[category.id], at=at, source=erp_id, event=event)
        for key, unit_id in unit_ids.items():
            ledger.money("financial.gross_profit.actual", unit_id, target_period, gp_actual[key],
                         at=at, source=erp_id, event=event)
        ledger.money("financial.gross_profit.actual", company_id, target_period, group_gp_actual,
                     at=at, source=erp_id, event=event)

        if full:
            for category in categories:
                if category.id in cat_gp_budget:
                    ledger.money("financial.gross_profit.budget", category.id, target_period,
                                 cat_gp_budget[category.id], at=at, source=erp_id, event=event)
            for key, unit_id in unit_ids.items():
                ledger.money("financial.gross_profit.budget", unit_id, target_period, gp_budget[key],
                             at=at, source=erp_id, event=event)
            ledger.money("financial.gross_profit.budget", company_id, target_period, group_gp_budget,
                         at=at, source=erp_id, event=event)

            for category in categories:
                if category.id in cat_gp_actual:
                    ledger.money("financial.gross_profit.variance", category.id, target_period,
                                 cat_gp_actual[category.id] - cat_gp_budget[category.id],
                                 at=at, source=erp_id, event=event)
            for key, unit_id in unit_ids.items():
                ledger.money("financial.gross_profit.variance", unit_id, target_period,
                             gp_actual[key] - gp_budget[key], at=at, source=erp_id, event=event)
            ledger.money("financial.gross_profit.variance", company_id, target_period,
                         group_gp_actual - group_gp_budget, at=at, source=erp_id, event=event)

        # -- margins, re-derived from the rounded amounts above -------------
        for category in categories:
            if category.id in cat_gp_actual:
                ledger.measure("financial.gross_margin_pct.actual", category.id, target_period,
                               _pct(cat_gp_actual[category.id], cat_actual[category.id]), PERCENT,
                               at=at, source=erp_id, event=event)
        for key, unit_id in unit_ids.items():
            ledger.measure("financial.gross_margin_pct.actual", unit_id, target_period,
                           _pct(gp_actual[key], actual[key]), PERCENT,
                           at=at, source=erp_id, event=event)
        ledger.measure("financial.gross_margin_pct.actual", company_id, target_period,
                       _pct(group_gp_actual, group_actual), PERCENT,
                       at=at, source=erp_id, event=event)

        if full:
            for category in categories:
                if category.id in cat_gp_budget:
                    ledger.measure("financial.gross_margin_pct.budget", category.id, target_period,
                                   _pct(cat_gp_budget[category.id], cat_budget[category.id]), PERCENT,
                                   at=at, source=erp_id, event=event)
            for key, unit_id in unit_ids.items():
                ledger.measure("financial.gross_margin_pct.budget", unit_id, target_period,
                               _pct(gp_budget[key], budget[key]), PERCENT,
                               at=at, source=erp_id, event=event)
            ledger.measure("financial.gross_margin_pct.budget", company_id, target_period,
                           _pct(group_gp_budget, group_budget), PERCENT,
                           at=at, source=erp_id, event=event)

            _drivers(ledger, rng, unit_ids, company_id, target_period, at,
                     erp_id, commerce_id, close_event_id, lore_by_target,
                     budget, actual, gp_budget, gp_actual,
                     group_budget, group_actual, group_gp_budget, group_gp_actual)

        return budget, actual

    # Comparatives first, so the reporting period's facts are minted last and the
    # newest fact in the corpus is the one the close produced.
    history = previous_periods(period, comparative_months)
    for past in history:
        emit_level(past, _closed_at(past, finalised_at), None, full=False)

    boundary = len(ledger.facts)
    emit_level(period, finalised_at, close_event_id, full=True)

    reporting = ledger.facts[boundary:]
    top = {company_id, *unit_ids.values()}
    headline = tuple(fact for fact in reporting if fact.subject in top)

    return Financials(
        facts=tuple(ledger.facts),
        headline=headline,
        periods=(*history, period),
    )


def _drivers(
    ledger: _Ledger, rng: Rng, unit_ids: dict[str, str], company_id: str, period: str,
    at: datetime, erp_id: str, commerce_id: str, event: str,
    lore_by_target: dict[str, list[str]],
    budget: dict[str, int], actual: dict[str, int],
    gp_budget: dict[str, int], gp_actual: dict[str, int],
    group_budget: int, group_actual: int, group_gp_budget: int, group_gp_actual: int,
) -> None:
    """The derived metrics a variance memo argues from."""
    margin_move = round(
        _pct(group_gp_actual, group_actual) - _pct(group_gp_budget, group_budget), 2
    )
    ledger.measure("metric.gross_margin_variance", company_id, period,
                   round(margin_move * 100), BPS, at=at, source=erp_id, event=event)

    worst = min(unit_ids, key=lambda k: actual[k] - budget[k])
    promo_bps = round(
        (_pct(gp_actual[worst], actual[worst]) - _pct(gp_budget[worst], budget[worst])) * 100
    )
    ledger.measure("metric.promotional_depth_margin_impact", unit_ids[worst], period,
                   promo_bps, BPS, at=at, source=erp_id, event=event,
                   lore=lore_by_target.get("promotional_depth", []))

    if "digital" in unit_ids:
        conv_rng = rng.derive(f"conversion/{period}")
        forecast = conv_rng.number(3.0, 3.4, places=2)
        actual_conv = round(forecast - conv_rng.number(0.05, 0.40, places=2), 2)
        ledger.measure("metric.online_conversion_rate.forecast", unit_ids["digital"], period,
                       forecast, PERCENT, at=at, source=commerce_id, event=event,
                       lore=lore_by_target.get("online_conversion_rate", []))
        ledger.measure("metric.online_conversion_rate.actual", unit_ids["digital"], period,
                       actual_conv, PERCENT, at=at, source=commerce_id, event=event,
                       lore=lore_by_target.get("online_conversion_rate", []))


def worst_performing_unit(facts: tuple[CanonicalFact, ...], unit_ids: dict[str, str]) -> str:
    """The unit ID with the largest adverse revenue variance."""
    by_subject = {
        f.subject: f.value.amount
        for f in facts
        if f.kind == "financial.revenue.variance" and f.value and f.subject in unit_ids.values()
    }
    return min(by_subject, key=lambda s: by_subject[s])
