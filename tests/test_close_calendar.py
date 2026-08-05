"""The close calendar: which days a company works, and where its year starts.

Two findings from the locales work, made load-bearing here.

* **One working week, not three.** ``operations.business_days_after``,
  the escalation's inline `+1 unless Saturday`, and ``liquidity.generate``'s
  ``weekday() < 5`` were three independent Monday-to-Friday rules with no
  holiday table between them. They are now one question asked of a
  ``Calendar``, and ``locales.Locale`` answers it directly.
* **A fiscal year that means something.** ``fiscal_year_start_month`` was set
  by a pack, copied by three org generators, stored on ``Company`` and read by
  nothing. It now decides period *identity* — which financial year a period
  falls in, how far into it, whether it closes a quarter or the year.

The organising claim of this file is the one that cannot be faked: the same
sentence — "the close is due four business days after month end" — resolves to
different dates under different calendars, and every dependent timestamp in the
episode moves with it. Everything is asserted against generated output, never
against the table it came from, and the default-calendar goldens below are the
dates the engine has always produced.
"""

from __future__ import annotations

from datetime import date

import pytest

from worldloom import locales
from worldloom.generators import liquidity, operations
from worldloom.ids import Minter
from worldloom.models import Company, FiscalPeriod, fiscal_period
from worldloom.rng import Rng

SEED = 8128

#: Enough of a role table for the close and the full incident chain. Ids rather
#: than a built world: this file is about arithmetic, and a real world would
#: make each assertion depend on the organisation generator's draws as well.
ROLES: dict[str, str] = {
    key: f"X-{key}"
    for key in (
        "reporting_manager", "controller", "cfo", "audit", "merch_analyst",
        "platform_lead", "platform_senior", "svc_orchestrator", "svc_valuation",
        "svc_hierarchy", "svc_desk", "svc_incident", "sys_erp", "sys_mdm",
        "sys_platform", "unit_gm",
    )
}


def close(period: str, *, calendar=operations.CALENDAR, incident: bool = True):
    """One close episode on *calendar*, with the incident forced on.

    Forced rather than seeded, because the incident chain is where two thirds
    of the episode's dates live — the escalation, the review, the remediation
    and the revised close date — and a calendar that only moved the due date
    would be a calendar that had reached one call site.
    """
    return operations.generate(
        Rng(SEED), Minter(), period=period, company_id="CO-0001", roles=ROLES,
        lore_by_target={}, incident_likelihood=0.0, force_incident=incident,
        calendar=calendar,
    )


def dates(episode) -> dict[str, str]:
    """The episode's calendar, as the corpus states it: the two date-valued
    facts, plus the day each event happened on."""
    stated = {
        fact.kind: fact.text_value for fact in episode.facts
        if fact.kind in ("close.due_date", "close.revised_date")
    }
    stated.update({
        event.kind: event.occurred_at.date().isoformat() for event in episode.events
    })
    return stated


# ---------------------------------------------------------------------------
# The default calendar is the engine's calendar
# ---------------------------------------------------------------------------

#: Every date in the March 2026 close as the engine has always produced it,
#: captured before the calendar became a parameter. Goldens rather than a
#: recomputation, because recomputing them with the code under test would
#: assert that the new arithmetic agrees with itself.
MARCH_2026: dict[str, str] = {
    "close.due_date": "2026-04-06",
    "close.revised_date": "2026-04-07",
    "close_started": "2026-04-01",
    "pipeline_failed": "2026-04-01",
    "incident_opened": "2026-04-01",
    "hypothesis_recorded": "2026-04-01",
    "hypothesis_superseded": "2026-04-01",
    "root_cause_confirmed": "2026-04-01",
    "workaround_applied": "2026-04-01",
    "valuation_available": "2026-04-01",
    "close_delayed": "2026-04-02",
    "control_failure_identified": "2026-04-03",
    "remediation_created": "2026-04-03",
    "close_finalised": "2026-04-07",
}


def test_the_default_calendar_produces_the_dates_it_always_did() -> None:
    """The byte-identity claim, at the level the corpus can see it. If this
    moves, every close date in every corpus ever built has moved with it."""
    assert dates(close("2026-03")) == MARCH_2026


def test_the_engines_calendar_is_the_default_locale() -> None:
    """Not a copy of it. The two were the same thing by accident for the whole
    life of this project — Monday to Friday, no holiday, a July year — and a
    second table stating it again is a second table that can drift."""
    assert operations.CALENDAR is locales.DEFAULT
    assert operations.CALENDAR.working_week == locales.MONDAY_TO_FRIDAY
    assert operations.CALENDAR.holidays == ()


def test_business_days_after_still_takes_two_arguments() -> None:
    """Five modules import this function and call it with two arguments. The
    calendar is a third with a default, not a new required parameter."""
    assert operations.business_days_after(date(2026, 3, 31), 4) == date(2026, 4, 6)


# ---------------------------------------------------------------------------
# A Gulf week moves the whole episode
# ---------------------------------------------------------------------------


def test_a_gulf_close_lands_on_different_days_from_an_australian_one() -> None:
    """The August 2026 close, which is the month where the two calendars cross
    rather than merely differ: four business days after 31 August is Friday
    4 September in Sydney, and Friday is a weekend in Dubai, where the same
    commitment falls on Sunday the 6th.

    Asserted on the whole episode, not just the due date. A calendar wired into
    one call site would pass a due-date test and still escalate the incident on
    a Dubai weekend.
    """
    sydney, dubai = dates(close("2026-08")), dates(close("2026-08", calendar=locales.GULF))

    assert sydney["close.due_date"] == "2026-09-04"      # a Friday
    assert dubai["close.due_date"] == "2026-09-06"       # a Sunday
    assert not locales.GULF.is_business_day(date(2026, 9, 4))
    assert locales.GULF.is_business_day(date(2026, 9, 6))

    # And in August, only the due date moves: the escalation and the review
    # fall on days both calendars work, so they coincide. Asserted rather than
    # skipped, because "the Gulf shifts everything by a day" is the wrong
    # mental model and the wrong model is what a later change would break.
    assert sydney["close_delayed"] == dubai["close_delayed"] == "2026-09-02"
    assert sydney["close.revised_date"] == dubai["close.revised_date"] == "2026-09-07"


def test_a_gulf_close_moves_furthest_where_the_week_and_the_holidays_compose() -> None:
    """November 2026, the month that needs both halves of a calendar at once.

    Four business days after 30 November is 4 December in Sydney. In the UAE
    the 2nd and 3rd are National Day, and the 4th and 5th are the weekend, so
    the same four days run out on the 8th — four calendar days apart, not one.
    Every downstream timestamp moves with it, which is the difference between a
    calendar reaching one call site and reaching the episode.
    """
    sydney, dubai = dates(close("2026-11")), dates(close("2026-11", calendar=locales.GULF))
    assert sydney["close.due_date"] == "2026-12-04"
    assert dubai["close.due_date"] == "2026-12-08"
    assert (sydney["close_delayed"], dubai["close_delayed"]) == ("2026-12-02", "2026-12-06")
    assert (sydney["control_failure_identified"], dubai["control_failure_identified"]) == \
        ("2026-12-03", "2026-12-07")
    assert (sydney["close.revised_date"], dubai["close.revised_date"]) == \
        ("2026-12-07", "2026-12-09")


def test_no_month_of_a_gulf_year_matches_the_australian_one() -> None:
    """The scale of it, so that "the locale moves dates" is a measured claim
    rather than an anecdote about August. Every month of 2026 differs somewhere
    in the episode; the *due date* alone differs for six of the twelve, which
    is the number `test_locales` proves against the bare arithmetic."""
    differing = [
        month for month in range(1, 13)
        for period in [f"2026-{month:02d}"]
        if dates(close(period)) != dates(close(period, calendar=locales.GULF))
    ]
    assert differing == list(range(1, 13))

    due_moved = [
        month for month in range(1, 13)
        for period in [f"2026-{month:02d}"]
        if dates(close(period))["close.due_date"]
        != dates(close(period, calendar=locales.GULF))["close.due_date"]
    ]
    assert due_moved == [1, 2, 7, 8, 10, 11]


def test_a_gulf_calendar_never_dates_anything_to_its_weekend() -> None:
    """The invariant behind the dates above, over a whole year. Friday and
    Saturday are the UAE weekend; nothing the episode stamps may land there.

    This is the check that would have failed before the change on every single
    month, because the engine's only notion of a weekend was Saturday and
    Sunday and it applied it to Dubai unasked.
    """
    for month in range(1, 13):
        episode = close(f"2026-{month:02d}", calendar=locales.GULF)
        for day in dates(episode).values():
            assert locales.GULF.is_business_day(date.fromisoformat(day)), (month, day)


def test_a_public_holiday_pushes_the_close_out() -> None:
    """The other half of a calendar, and the half the engine never had at all.

    The December 2025 close runs into New Year's Day. To the engine, 1 January
    2026 is an ordinary Thursday and the close starts on it; to Germany and the
    UK it is a public holiday, so the close starts on the 2nd and everything
    after it lands a day later. Same week, same arithmetic, one day the engine
    could not know about.
    """
    engine = dates(close("2025-12"))
    german = dates(close("2025-12", calendar=locales.GERMANY))
    assert (engine["close_started"], engine["close.due_date"]) == ("2026-01-01", "2026-01-06")
    assert (german["close_started"], german["close.due_date"]) == ("2026-01-02", "2026-01-07")
    # The UK's fixed table differs from Germany's, and on this window agrees.
    assert dates(close("2025-12", calendar=locales.UNITED_KINGDOM))["close.due_date"] == \
        "2026-01-07"


def test_the_escalation_is_the_next_business_day_and_not_a_weekend_literal() -> None:
    """The inline `+1 day, or +3 if that is a Saturday` the incident chain used
    to carry. It was only ever "the next business day" spelled out — identical
    on a Monday-to-Friday week, and unable to skip a holiday or a Friday
    weekend on any other.

    Asserted as an equality against the calendar rather than against a golden,
    because the claim is that one rule replaced three.
    """
    for calendar in (locales.AUSTRALIA, locales.GULF, locales.UNITED_KINGDOM):
        for month in range(1, 13):
            period = f"2026-{month:02d}"
            episode = close(period, calendar=calendar)
            day1 = calendar.business_days_after(operations.period_end(period), 1)
            assert dates(episode)["close_delayed"] == \
                calendar.business_days_after(day1, 1).isoformat()


# ---------------------------------------------------------------------------
# The liquidity series runs on the same calendar
# ---------------------------------------------------------------------------


def test_the_liquidity_window_follows_the_working_week() -> None:
    """The third Monday-to-Friday rule. Ten consecutive business days from a
    Gulf Friday start on Sunday and include no Friday at all.

    Both halves matter: the *start* was `start if start.weekday() < 5`, so a
    window opening on a Dubai Friday used to be accepted as-is.
    """
    friday = date(2026, 9, 4)
    engine = liquidity.generate(Rng(SEED), start=friday, days=10)
    gulf = liquidity.generate(Rng(SEED), start=friday, days=10, calendar=locales.GULF)

    assert engine.observations[0][0] == friday
    assert gulf.observations[0][0] == date(2026, 9, 6)
    assert all(locales.GULF.is_business_day(day) for day, _ in gulf.observations)
    assert not any(day.weekday() == locales.FRIDAY for day, _ in gulf.observations)


def test_a_holiday_is_missing_from_the_series_rather_than_valued() -> None:
    """A UK bank whose LCR is reported on Christmas Day is a corpus that says
    it is not really a UK bank."""
    series = liquidity.generate(
        Rng(SEED), start=date(2025, 12, 22), days=5, calendar=locales.UNITED_KINGDOM
    )
    days = [day for day, _ in series.observations]
    assert date(2025, 12, 25) not in days
    assert date(2025, 12, 26) not in days
    assert days == [date(2025, 12, 22), date(2025, 12, 23), date(2025, 12, 24),
                    date(2025, 12, 29), date(2025, 12, 30)]


def test_a_days_reading_belongs_to_that_day_on_any_calendar() -> None:
    """Each value is drawn from a stream named after its own ISO date, not after
    its position in the window. So two calendars that both work a given day
    report the same figure for it, and a day one calendar does not work is
    simply absent rather than shifted onto its neighbour — which is what would
    have happened had the window been indexed by draw order."""
    friday = date(2026, 9, 4)
    engine = dict(liquidity.generate(Rng(SEED), start=friday, days=10).observations)
    gulf = dict(liquidity.generate(
        Rng(SEED), start=friday, days=10, calendar=locales.GULF).observations)
    shared = set(engine) & set(gulf)
    assert shared, "the two windows overlap on at least one weekday"
    assert all(engine[day] == gulf[day] for day in shared)


# ---------------------------------------------------------------------------
# The fiscal year decides what a period counts as
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start_month, period, expected",
    [
        # Australia's July year: March is the ninth month, third quarter.
        (7, "2026-03", (2026, 3, 9)),
        (7, "2025-07", (2026, 1, 1)),
        (7, "2026-06", (2026, 4, 12)),
        # A calendar year, where FY and CY agree and the guard against
        # labelling every year as the next one has to hold.
        (1, "2026-01", (2026, 1, 1)),
        (1, "2026-12", (2026, 4, 12)),
        # The UK's April year.
        (4, "2026-03", (2026, 4, 12)),
        (4, "2026-04", (2027, 1, 1)),
        # A December start, which is the case the modulo exists for: month one
        # of FY2027 is December 2026, and January is month two.
        (12, "2026-12", (2027, 1, 1)),
        (12, "2027-01", (2027, 1, 2)),
    ],
)
def test_a_period_sits_where_the_fiscal_year_puts_it(
    start_month: int, period: str, expected: tuple[int, int, int]
) -> None:
    """The whole of what a fiscal year decides: a year label, a quarter, and an
    ordinal. The period string itself never moves — ``2026-03`` is March 2026
    under every one of these."""
    sat = fiscal_period(period, start_month)
    assert (sat.year, sat.quarter, sat.month) == expected


def test_the_fiscal_year_labels_by_the_year_it_ends_in() -> None:
    """One convention, not a per-jurisdiction choice. FY2026 runs July 2025 to
    June 2026 in Australia and is the calendar year in Germany, and both are
    the year the period *ends* in — so two subsidiaries' FY labels compare."""
    assert fiscal_period("2025-07", 7).label == "FY2026 Q1 P1"
    assert fiscal_period("2026-06", 7).label == "FY2026 Q4 P12"
    assert fiscal_period("2026-01", 1).label == "FY2026 Q1 P1"
    assert fiscal_period("2026-12", 1).label == "FY2026 Q4 P12"


def test_quarter_and_year_ends_move_with_the_fiscal_year_start() -> None:
    """"Quarter" stops being a label a caller typed.

    July and January are deliberately shown agreeing on *which* months end a
    quarter and disagreeing on *which quarter* it is: any start month
    congruent to 1 mod 3 leaves the quarter-end months at March/June/September/
    December, which is why a test that only compared those lists would look
    like it was passing while measuring nothing. February is the contrast that
    actually moves them.
    """
    def quarter_ends(start: int) -> list[int]:
        return [m for m in range(1, 13) if fiscal_period(f"2026-{m:02d}", start).is_quarter_end]

    assert quarter_ends(7) == [3, 6, 9, 12]
    assert quarter_ends(1) == [3, 6, 9, 12]
    assert quarter_ends(2) == [1, 4, 7, 10]
    assert fiscal_period("2026-03", 7).quarter == 3
    assert fiscal_period("2026-03", 1).quarter == 1

    year_ends = {
        start: [m for m in range(1, 13) if fiscal_period(f"2026-{m:02d}", start).is_year_end]
        for start in (1, 4, 7)
    }
    assert year_ends == {1: [12], 4: [3], 7: [6]}


def test_the_shipped_insurer_closes_on_its_fiscal_year_end() -> None:
    """Why the fiscal year moves no date, stated as a fact about this repo
    rather than as a preference.

    The insurance archetype's shipped valuation period is 2026-06, and under
    Australia's July year that period *is* the fiscal year end. So any rule
    that made a year-end period behave differently — a longer hard close, an
    extra approval, a later due date — would have moved a shipped corpus on the
    day it landed, at the default value, with no locale involved. The fiscal
    year is a frame; the close calendar is the clock.
    """
    assert fiscal_period("2026-06", 7).is_year_end
    assert not fiscal_period("2026-05", 7).is_year_end
    # An ordinary month and the fiscal year end are due the same number of
    # business days after their own month end. Nothing about a year end is a
    # special case, and this is where that would show first if it became one.
    for period in ("2026-05", "2026-06"):
        due = date.fromisoformat(dates(close(period))["close.due_date"])
        assert due == operations.business_days_after(operations.period_end(period), 4)


def test_a_company_answers_for_its_own_fiscal_year() -> None:
    """On the company, not on the locale. A German subsidiary of an Australian
    group keeps the group's July year while working a German week — a locale
    that decided the fiscal year would make that world unbuildable."""
    company = Company(
        id="CO-0001", name="Test", industry="Retail", headquarters="Frankfurt am Main, Germany",
        fiscal_year_start_month=7, currency="EUR", currency_unit="thousands",
        employees_total=100,
    )
    assert company.fiscal("2026-03") == FiscalPeriod(year=2026, quarter=3, month=9)
    assert company.fiscal("2026-06").is_year_end
    assert not company.fiscal("2026-12").is_year_end


def test_the_episode_carries_the_fiscal_coordinates_of_its_period() -> None:
    """Derived on every close and handed downstream, rather than stored on the
    company and read by nobody. Carried on the episode rather than minted as a
    fact deliberately: a new fact takes an id from the minter and shifts every
    id after it."""
    assert close("2026-03").fiscal == FiscalPeriod(year=2026, quarter=3, month=9)
    gulf = close("2026-03", calendar=locales.GULF)   # a January financial year
    assert gulf.fiscal == FiscalPeriod(year=2026, quarter=1, month=3)


def test_a_close_mints_the_same_facts_whatever_the_fiscal_year() -> None:
    """The fiscal year changes no id, no kind, no count and no text. It is the
    reason a non-default fiscal year is safe to set today and the reason it
    does not yet reach the rendered corpus — see the module docstring."""
    australian = close("2026-03")
    gulf_year = close("2026-03", calendar=locales.GULF)
    assert [f.id for f in australian.facts] == [f.id for f in gulf_year.facts]
    assert [f.kind for f in australian.facts] == [f.kind for f in gulf_year.facts]


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------


def test_every_shipped_locale_is_a_calendar() -> None:
    """The protocol is structural, so nothing checks it at import time. This is
    that check: every preset in the registry can be handed to the close
    unmodified, which is the point of not inventing a second calendar type."""
    for name, locale in sorted(locales.LOCALES.items()):
        episode = close("2026-03", calendar=locale)
        due = date.fromisoformat(dates(episode)["close.due_date"])
        assert locale.is_business_day(due), name
        assert episode.fiscal.year == fiscal_period(
            "2026-03", locale.fiscal_year_start_month).year
