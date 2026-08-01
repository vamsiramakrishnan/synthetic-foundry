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

from ..rng import Rng
from .operations import business_days_after


@dataclass(frozen=True)
class LiquiditySeries:
    """Consecutive business-day LCR observations, in date order."""

    observations: tuple[tuple[date, float], ...]


def generate(rng: Rng, *, start: date, days: int) -> LiquiditySeries:
    """*days* consecutive business-day LCR values from *start* (inclusive).

    The band is an ordinary well-covered bank: comfortably above 100%, moving
    day to day, never dramatic. The series deliberately does not react to the
    episode's reconciliation break — the break is in an *input* feed, and a
    coverage ratio that dipped on cue would be the corpus dramatising its own
    plot rather than reporting a calculation.
    """
    if days < 1:
        raise ValueError("a liquidity series needs at least one day")
    current = start if start.weekday() < 5 else business_days_after(start, 1)
    observations: list[tuple[date, float]] = []
    for _ in range(days):
        value = rng.derive(f"lcr/{current.isoformat()}").number(126.0, 138.0, places=1)
        observations.append((current, value))
        current = business_days_after(current, 1)
    return LiquiditySeries(observations=tuple(observations))
