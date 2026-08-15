"""Value primitives for authored episodes.

The episode-grammar autopsy's finding was that *specifics cannot be data* —
value curves live in generators. This module is the smallest honest response:
the four parameterised shapes the QuarterlyCapitalReturn proof spec actually
needs, extracted so an authored episode can mint values without owning a
generator, and nothing more. It is deliberately not an attempt to make every
existing generator a primitive:

* ``capital.generate``'s understatement is rounded to the nearest ten and its
  book weights are the archetype's two-level income shares — call-site
  arithmetic, not a reusable curve;
* ``liquidity.generate`` names its per-day streams ``lcr/<date>`` — a stream
  label is generator-private identity, and a primitive that took labels as
  data would let a spec silently re-key every figure a seed ever meant;
* ``finance.generate``'s comparative history and ``reserving.generate``'s
  triangle walk are whole shapes, not draws.

Where a primitive here and a generator draw the same physics span, the two
still produce *different* values, because the streams are named differently —
that is a documented property, not a defect. Byte-identity with a hand-built
episode is a claim about stream names and call order, and those belong to the
generator that made them.

Determinism: every draw comes through ``parameters.Parameters`` on a named
``Rng`` stream the caller derives; no clock, no ``random``, no UUID, and no
set iteration decides anything here.
"""

from __future__ import annotations

from datetime import date

from ..parameters import Parameters
from ..rng import Rng
from .finance import allocate
from .operations import CALENDAR, Calendar

__all__ = ["level", "series", "rollup", "supersession_pair", "carried_forward"]


def level(physics: Parameters, parameter: str, rng: Rng) -> float | int:
    """One level+noise draw from a registered span.

    Dispatches on the span's own kind so an integer span draws an integer with
    exactly the arguments the literal it replaced used — the property
    ``parameters.py`` calls the whole contract.
    """
    span = physics.span(parameter)
    if span.kind == "integer":
        return physics.integer(parameter, rng)
    if span.kind == "chance":
        raise TypeError(
            f"{parameter} is a chance, not a level — a probability is decided"
            " where it is spent, not drawn as a value"
        )
    return physics.number(parameter, rng)


def series(
    physics: Parameters,
    parameter: str,
    rng: Rng,
    *,
    start: date,
    days: int,
    calendar: Calendar = CALENDAR,
) -> tuple[tuple[date, float], ...]:
    """*days* consecutive business-day draws from one span, in date order.

    ``liquidity.generate``'s discipline, span-generic: each day's value comes
    from a stream named for the *date*, never for draw order, so extending the
    window can never reshuffle the days already drawn. The stream is
    ``<parameter>/<iso-date>`` under *rng* — which is also why this series
    cannot reproduce ``liquidity.generate``'s values for the same span: that
    generator's streams are named ``lcr/<date>``, and the label is its own.
    """
    if days < 1:
        raise ValueError("a series needs at least one day")
    current = start if calendar.is_business_day(start) else calendar.business_days_after(start, 1)
    out: list[tuple[date, float]] = []
    for _ in range(days):
        value = physics.number(parameter, rng.derive(f"{parameter}/{current.isoformat()}"))
        out.append((current, value))
        current = calendar.business_days_after(current, 1)
    return tuple(out)


def rollup(total: int, weights: list[float]) -> list[int]:
    """Children that sum to a declared parent exactly.

    ``finance.allocate``'s largest-remainder split, re-exported under the
    primitive's name: allocated from the total, never drawn and summed, which
    is the only shape under which a sums-to invariant can be *guaranteed* by
    construction rather than merely checked after.
    """
    return allocate(total, weights)


def supersession_pair(
    physics: Parameters,
    parameter: str,
    error_parameter: str,
    rng: Rng,
    *,
    scale: float = 1.0,
) -> tuple[int, int]:
    """An initial value and the corrected value that supersedes it.

    The initial value is a level draw from *parameter* (times *scale*, for
    spans whose unit is a multiple — ``capital.rwa.filed_hundreds`` counts
    hundreds). The correction adds ``initial × error`` where the error fraction
    is drawn from *error_parameter*, rounded to a whole unit. Two streams,
    named ``base`` and ``error`` under *rng*, so tuning the error span can
    never move the initial figure.

    Deliberately not ``capital.generate``'s arithmetic: that generator rounds
    its understatement to the nearest ten (``round(..., -1)``) — a
    presentation decision belonging to that episode's figures, not to the
    shape. A spec replaying the banking episode through this primitive gets an
    understatement that differs in its last digit, and the byte-diff says so.
    """
    initial = round(float(level(physics, parameter, rng.derive("base"))) * scale)
    error = float(level(physics, error_parameter, rng.derive("error")))
    corrected = initial + round(initial * error)
    return initial, corrected


def carried_forward(world, *, kind: str, subject: str, rule: str, prior_period: str | None = None):
    """The prior period's fact this period resolves, by declared rule.

    - ``reuse``: the standing fact itself, to be re-listed (never re-minted) —
      the caller filters it back out of ``world.extend``'s facts, exactly as
      ``QuarterlyCapitalReturn.run`` does with the standing minimum.
    - ``sum`` / ``derive``: the prior fact for its *value*; the caller's
      generator derives this period's from it and mints a new fact.

    Returns ``None`` when there is no prior fact — the first period of any
    corpus. ``prior_period`` scopes the lookup for period-keyed kinds;
    standing kinds are looked up unscoped, because a standing fact carries no
    period and a scoped lookup would never find it (the exact defect the
    comment in ``banking_scenarios.py`` records).
    """
    if rule not in ("reuse", "sum", "derive"):
        raise ValueError(f"unknown carry-forward rule {rule!r}; reuse, sum, or derive")
    return world.authoritative(kind, subject, period=prior_period)
