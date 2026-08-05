"""The liquidity generator.

A bounded run of daily liquidity coverage observations — the second cadence the
banking episode needs, because the whole point of "The Challenged Return" is
that a *daily* process catches a *quarterly* process's error. Pure values, like
``capital.py``: the episode generator decides when each observation enters the
world.

Each day's draw comes from a stream named after the date, not after draw order,
so extending the window by a day can never reshuffle the days already drawn —
the same rule ``organisation._joined_date`` states for people, applied to a
time series.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..parameters import DEFAULT, Parameters
from ..rng import Rng
from .operations import CALENDAR, Calendar


@dataclass(frozen=True)
class LiquiditySeries:
    """Consecutive business-day LCR observations, in date order."""

    observations: tuple[tuple[date, float], ...]


def generate(
    rng: Rng, *, start: date, days: int, calendar: Calendar = CALENDAR,
    physics: Parameters = DEFAULT,
) -> LiquiditySeries:
    """*days* consecutive business-day LCR values from *start* (inclusive).

    The band is an ordinary well-covered bank: comfortably above 100%, moving
    day to day, never dramatic. The series deliberately does not react to the
    episode's reconciliation break — the break is in an *input* feed, and a
    coverage ratio that dipped on cue would be the corpus dramatising its own
    plot rather than reporting a calculation.

    ``calendar`` is what a "business day" means here (``worldloom.locales``).
    It was ``weekday() < 5``, written out a third time rather than asked of
    anything — so a treasury reporting from Dubai produced observations on its
    weekend and none on its Sunday, and a bank in a country with public
    holidays reported an LCR on Christmas Day.

    One caveat worth carrying, because it is not obvious from here:
    ``banking.validate``'s ``liquidity_cadence_gap`` check recomputes "one
    business day later" with ``operations.business_days_after`` on the *default*
    calendar. So a banking episode generated on a non-default calendar produces
    a correct series that the validator will flag, until that check takes the
    same calendar. Named rather than worked around — the fix is one argument in
    a module this change does not own, and silently loosening the check to
    accommodate a locale would trade a real invariant for a convenience.
    """
    if days < 1:
        raise ValueError("a liquidity series needs at least one day")
    # The band's *values* are keyed on the ISO date, so moving the window to a
    # different calendar redraws every observation rather than shifting the
    # same numbers sideways — which is right: a different bank's Sunday is not
    # an Australian Monday's reading printed a day early.
    current = start if calendar.is_business_day(start) else calendar.business_days_after(start, 1)
    observations: list[tuple[date, float]] = []
    for _ in range(days):
        value = physics.number(
            "capital.liquidity.lcr_pct", rng.derive(f"lcr/{current.isoformat()}")
        )
        observations.append((current, value))
        current = calendar.business_days_after(current, 1)
    return LiquiditySeries(observations=tuple(observations))
