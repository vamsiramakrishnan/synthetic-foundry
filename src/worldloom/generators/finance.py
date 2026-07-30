"""The financial generator.

Reconciles by construction rather than by arithmetic performed after the fact.
Unit figures are drawn first; group figures are *sums*, never independent draws;
variances are differences; percentages are derived from the rounded amounts they
describe. There is no step at which a total is stated and hoped to match.

That ordering is the whole point. A generator that drew a group total and then
tried to make units add up to it would eventually produce a corpus where a board
deck disagrees with its own workbook, which is the failure the project exists to
eliminate.
"""

from __future__ import annotations

from datetime import datetime

from ..ids import Minter
from ..models import Authority, CanonicalFact, Quantity
from ..rng import Rng

MONEY = "AUD_thousands"
PERCENT = "percent"
BPS = "bps"


def _money(minter: Minter, kind: str, subject: str, period: str, amount: int,
           *, at: datetime, source: str, event: str, lore: list[str] | None = None) -> CanonicalFact:
    return CanonicalFact(
        id=minter.next("FACT"),
        kind=kind,
        subject=subject,
        period=period,
        value=Quantity(amount=amount, unit=MONEY),
        valid_from=at,
        authority=Authority.SYSTEM_OF_RECORD,
        source_system=source,
        event_id=event,
        lore_ids=lore or [],
    )


def _measure(minter: Minter, kind: str, subject: str, period: str, amount: float, unit: str,
             *, at: datetime, source: str, event: str, lore: list[str] | None = None) -> CanonicalFact:
    return CanonicalFact(
        id=minter.next("FACT"),
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


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    unit_ids: dict[str, str],
    unit_shares: dict[str, float],
    erp_id: str,
    commerce_id: str,
    finalised_at: datetime,
    close_event_id: str,
    annual_revenue: int,
    lore_by_target: dict[str, list[str]],
) -> tuple[CanonicalFact, ...]:
    """Generate a month's financial facts for one company.

    ``lore_by_target`` maps a constraint target to the lore IDs that touch it, so
    a generated fact records *why* it looks the way it does — a Digital forecast
    miss cites the replatform that made forecasting unreliable.
    """
    monthly = annual_revenue // 12
    facts: list[CanonicalFact] = []

    # -- revenue -----------------------------------------------------------
    budget: dict[str, int] = {}
    actual: dict[str, int] = {}
    for key, unit_id in unit_ids.items():
        unit_rng = rng.derive(f"revenue/{key}")
        unit_budget = int(round(monthly * unit_shares[key], -2))
        # A miss is the interesting case, so the distribution is skewed adverse.
        miss_pct = unit_rng.number(-0.065, 0.015, places=4)
        budget[key] = unit_budget
        actual[key] = int(round(unit_budget * (1 + miss_pct), -2))

    group_budget = sum(budget.values())
    group_actual = sum(actual.values())

    for key, unit_id in unit_ids.items():
        facts.append(_money(minter, "financial.revenue.actual", unit_id, period, actual[key],
                            at=finalised_at, source=erp_id, event=close_event_id))
    facts.append(_money(minter, "financial.revenue.actual", company_id, period, group_actual,
                        at=finalised_at, source=erp_id, event=close_event_id))

    for key, unit_id in unit_ids.items():
        facts.append(_money(minter, "financial.revenue.budget", unit_id, period, budget[key],
                            at=finalised_at, source=erp_id, event=close_event_id))
    facts.append(_money(minter, "financial.revenue.budget", company_id, period, group_budget,
                        at=finalised_at, source=erp_id, event=close_event_id))

    for key, unit_id in unit_ids.items():
        facts.append(_money(minter, "financial.revenue.variance", unit_id, period,
                            actual[key] - budget[key], at=finalised_at, source=erp_id,
                            event=close_event_id, lore=lore_by_target.get(f"forecast_miss/{key}", [])))
    facts.append(_money(minter, "financial.revenue.variance", company_id, period,
                        group_actual - group_budget, at=finalised_at, source=erp_id, event=close_event_id))

    # -- gross profit ------------------------------------------------------
    # Margin percentages are drawn; amounts are computed from them and rounded;
    # the reported percentage is then re-derived from the rounded amount, so the
    # percentage on the page always matches the money on the page.
    gp_budget: dict[str, int] = {}
    gp_actual: dict[str, int] = {}
    base_margin = {"food": 0.248, "gm": 0.312, "digital": 0.220}
    for key in unit_ids:
        margin_rng = rng.derive(f"margin/{key}")
        budget_margin = base_margin.get(key, margin_rng.number(0.20, 0.34, places=4))
        erosion = margin_rng.number(0.002, 0.020, places=4)
        gp_budget[key] = int(round(budget[key] * budget_margin))
        gp_actual[key] = int(round(actual[key] * (budget_margin - erosion)))

    group_gp_budget = sum(gp_budget.values())
    group_gp_actual = sum(gp_actual.values())

    for key, unit_id in unit_ids.items():
        facts.append(_money(minter, "financial.gross_profit.actual", unit_id, period, gp_actual[key],
                            at=finalised_at, source=erp_id, event=close_event_id))
    facts.append(_money(minter, "financial.gross_profit.actual", company_id, period, group_gp_actual,
                        at=finalised_at, source=erp_id, event=close_event_id))

    for key, unit_id in unit_ids.items():
        facts.append(_money(minter, "financial.gross_profit.budget", unit_id, period, gp_budget[key],
                            at=finalised_at, source=erp_id, event=close_event_id))
    facts.append(_money(minter, "financial.gross_profit.budget", company_id, period, group_gp_budget,
                        at=finalised_at, source=erp_id, event=close_event_id))

    for key, unit_id in unit_ids.items():
        facts.append(_money(minter, "financial.gross_profit.variance", unit_id, period,
                            gp_actual[key] - gp_budget[key], at=finalised_at, source=erp_id, event=close_event_id))
    facts.append(_money(minter, "financial.gross_profit.variance", company_id, period,
                        group_gp_actual - group_gp_budget, at=finalised_at, source=erp_id, event=close_event_id))

    def pct(profit: int, revenue: int) -> float:
        return round(profit / revenue * 100, 2) if revenue else 0.0

    for key, unit_id in unit_ids.items():
        facts.append(_measure(minter, "financial.gross_margin_pct.actual", unit_id, period,
                              pct(gp_actual[key], actual[key]), PERCENT,
                              at=finalised_at, source=erp_id, event=close_event_id))
    facts.append(_measure(minter, "financial.gross_margin_pct.actual", company_id, period,
                          pct(group_gp_actual, group_actual), PERCENT,
                          at=finalised_at, source=erp_id, event=close_event_id))

    for key, unit_id in unit_ids.items():
        facts.append(_measure(minter, "financial.gross_margin_pct.budget", unit_id, period,
                              pct(gp_budget[key], budget[key]), PERCENT,
                              at=finalised_at, source=erp_id, event=close_event_id))
    facts.append(_measure(minter, "financial.gross_margin_pct.budget", company_id, period,
                          pct(group_gp_budget, group_budget), PERCENT,
                          at=finalised_at, source=erp_id, event=close_event_id))

    # -- derived movement and drivers --------------------------------------
    margin_move = round(
        pct(group_gp_actual, group_actual) - pct(group_gp_budget, group_budget), 2
    )
    facts.append(_measure(minter, "metric.gross_margin_variance", company_id, period,
                          round(margin_move * 100), BPS,
                          at=finalised_at, source=erp_id, event=close_event_id))

    worst_unit = min(unit_ids, key=lambda k: actual[k] - budget[k])
    promo_bps = round(
        (pct(gp_actual[worst_unit], actual[worst_unit]) - pct(gp_budget[worst_unit], budget[worst_unit])) * 100
    )
    facts.append(_measure(minter, "metric.promotional_depth_margin_impact", unit_ids[worst_unit], period,
                          promo_bps, BPS, at=finalised_at, source=erp_id, event=close_event_id,
                          lore=lore_by_target.get("promotional_depth", [])))

    if "digital" in unit_ids:
        conv_rng = rng.derive("conversion")
        forecast = conv_rng.number(3.0, 3.4, places=2)
        actual_conv = round(forecast - conv_rng.number(0.05, 0.40, places=2), 2)
        facts.append(_measure(minter, "metric.online_conversion_rate.forecast", unit_ids["digital"], period,
                              forecast, PERCENT, at=finalised_at, source=commerce_id, event=close_event_id,
                              lore=lore_by_target.get("online_conversion_rate", [])))
        facts.append(_measure(minter, "metric.online_conversion_rate.actual", unit_ids["digital"], period,
                              actual_conv, PERCENT, at=finalised_at, source=commerce_id, event=close_event_id,
                              lore=lore_by_target.get("online_conversion_rate", [])))

    return tuple(facts)


def worst_performing_unit(facts: tuple[CanonicalFact, ...], unit_ids: dict[str, str]) -> str:
    """The unit ID with the largest adverse revenue variance."""
    by_subject = {
        f.subject: f.value.amount
        for f in facts
        if f.kind == "financial.revenue.variance" and f.value and f.subject in unit_ids.values()
    }
    return min(by_subject, key=lambda s: by_subject[s])
