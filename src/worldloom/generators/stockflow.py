"""One grammar for a balance that moves: closing equals opening plus what
flowed in, less what flowed out, plus any adjustments — and the closing balance
is the opening balance of whatever period comes next.

**The measured problem.** A multi-period world reads as N independent monthly
photographs: each period's figures are drawn under that period's own stream,
and nothing a period states is *caused* by the period before it. The one
carry-forward this project had (the undelivered balance one vertical's cycle
releases) is enforced by a hand-written check in that vertical's own check
group — correct, and unshareable. Yet a large class of enterprise facts shares
exactly one shape: a bank's capital base, an insurer's reserve, a warehouse's
stock, a contractor's order book are all ``closing = opening + inflows −
outflows``. This module states that shape once, so a vertical that wants a
balance to carry across periods declares *which fact kinds play which part*
and gets the arithmetic, the carry, and the tamper surface from one place.

**Vocabulary comes from the caller, never from here.** A ``StockFlowSpec`` is
four (or five) fact-kind names supplied by a domain module; this file knows no
industry and names no kind — ``tests/test_stockflow.py`` scans the code to
keep it that way, the same ratchet ``tests/test_thin_waist.py`` holds core to.

**Exact, never tolerant.** ``verify`` compares with ``==``. Every consumer
builds these balances by integer allocation (``finance.allocate``) or by
integer arithmetic over already-rounded figures, so the identity holds to the
unit by construction — and a tolerance here would quietly absorb a later
generator's slide back to round-and-hope, which is precisely the drift the
grammar exists to refuse. A consumer whose balances genuinely cannot be exact
has a generator defect, not a verification problem.

**Periods are ordered, not stepped.** Observed period labels are sorted
lexicographically — ISO labels (``2026-03``, ``2026-Q1``) sort correctly — and
the carry is checked between *consecutive observed* periods. Calendar
arithmetic (is April the month after March? is a quarter three months?)
belongs to the vertical that owns the cadence; a module that stepped months
would be wrong for the first quarterly consumer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact


@dataclass(frozen=True)
class StockFlowSpec:
    """Which fact kinds play which part in one balance's movement.

    All five fields are fact *kinds*. The subjects the movement is stated for
    and the periods it covers are read off the facts themselves.
    """

    opening: str
    """The balance brought forward — stated per period, so a reader of one
    period's record holds the whole movement without the prior period's file."""

    inflows: tuple[str, ...]
    """What raises the balance. Summed when a period states several kinds."""

    outflows: tuple[str, ...]
    """What lowers the balance. Summed likewise."""

    closing: str
    """The balance carried forward — the next observed period's opening."""

    adjustments: tuple[str, ...] = ()
    """Signed movements that are neither: revaluations, write-ons. Added as
    stated, so a write-down is a negative fact rather than a hidden sign."""


@dataclass(frozen=True)
class Break:
    """One violation of the grammar, in the caller's own vocabulary.

    ``code`` is generic (this module names no industry); ``detail`` cites the
    spec's fact kinds and the figures, which is the caller's vocabulary carried
    as data. A domain check group forwards these as its own ``Violation``s.
    """

    code: str
    subject: str
    period: str
    detail: str


def close(opening: int, inflows: Sequence[int], outflows: Sequence[int],
          adjustments: Sequence[int] = ()) -> int:
    """The closing balance the grammar implies. Integer in, integer out.

    Trivial on purpose — the point is that the generator deriving a balance
    and the verifier checking it call one function, so they cannot state two
    versions of the identity. A generator that inlined this line would drift
    from ``verify`` the first time an adjustments term grew a convention.
    """
    return opening + sum(inflows) - sum(outflows) + sum(adjustments)


def verify(
    spec: StockFlowSpec,
    facts: Iterable["CanonicalFact"],
    *,
    subjects: Sequence[str] | None = None,
) -> tuple[list[Break], int]:
    """Hold *facts* to the grammar. Returns ``(breaks, checks_performed)``.

    Two claims per (subject, period), one claim per consecutive pair:

    * ``closing == opening + Σinflows − Σoutflows + Σadjustments`` — exactly.
    * ``opening[next] == closing[this]`` — the carry, exactly.

    *subjects* pins who must carry the movement. Left ``None``, the population
    is whoever states the opening or closing kind — right for a reading over
    an unknown corpus, and wrong for a validator: a corpus that quietly
    dropped every balance fact would then be vacuously clean. A check group
    that knows the balance's owner passes it, and an owner with no movement at
    all is a break rather than a silence.

    Only the caller's view of the record should arrive here: pass current
    facts, not superseded ones — this module cannot know a domain's
    supersession discipline, so it reads what it is given.
    """
    inflow_kinds = frozenset(spec.inflows)
    outflow_kinds = frozenset(spec.outflows)
    adjustment_kinds = frozenset(spec.adjustments)

    # One pass, four indexes. Presence matters independently of value — a
    # balance of zero is a statement and an absent balance is a gap — so the
    # opening and closing maps exist apart from the flow sums.
    opening: dict[tuple[str, str], float] = {}
    closing: dict[tuple[str, str], float] = {}
    flows: dict[tuple[str, str], list[float]] = {}
    periods_of: dict[str, set[str]] = {}

    def note(subject: str, period: str) -> None:
        periods_of.setdefault(subject, set()).add(period)

    for fact in facts:
        if fact.period is None or fact.value is None:
            continue
        key = (fact.subject, fact.period)
        amount = fact.value.amount
        if fact.kind == spec.opening:
            opening[key] = opening.get(key, 0) + amount
            note(*key)
        elif fact.kind == spec.closing:
            closing[key] = closing.get(key, 0) + amount
            note(*key)
        elif fact.kind in inflow_kinds:
            flows.setdefault(key, [0.0, 0.0, 0.0])[0] += amount
        elif fact.kind in outflow_kinds:
            flows.setdefault(key, [0.0, 0.0, 0.0])[1] += amount
        elif fact.kind in adjustment_kinds:
            flows.setdefault(key, [0.0, 0.0, 0.0])[2] += amount

    population = sorted(subjects) if subjects is not None else sorted(periods_of)
    breaks: list[Break] = []
    checks = 0

    for subject in population:
        periods = sorted(periods_of.get(subject, ()))
        if not periods:
            # Only reachable when the caller pinned the subject, which is the
            # caller asserting this owner carries the balance — so nothing on
            # record is a defect, not an empty loop.
            checks += 1
            breaks.append(Break(
                "stock_is_unstated", subject, "",
                f"no {spec.opening} or {spec.closing} fact states this"
                " subject's balance in any period",
            ))
            continue

        for period in periods:
            key = (subject, period)
            checks += 1
            if key not in opening:
                breaks.append(Break(
                    "movement_has_no_opening", subject, period,
                    f"{spec.closing} is stated with no {spec.opening} beside"
                    " it — the movement cannot be read, only its end",
                ))
            checks += 1
            if key not in closing:
                breaks.append(Break(
                    "movement_has_no_closing", subject, period,
                    f"{spec.opening} is stated with no {spec.closing} beside"
                    " it — a balance brought forward and never struck",
                ))
            if key not in opening or key not in closing:
                continue
            inflow, outflow, adjustment = flows.get(key, [0.0, 0.0, 0.0])
            checks += 1
            derived = opening[key] + inflow - outflow + adjustment
            if closing[key] != derived:
                breaks.append(Break(
                    "movement_does_not_close", subject, period,
                    f"opening {opening[key]:,.0f} + in {inflow:,.0f}"
                    f" − out {outflow:,.0f} + adjustments {adjustment:,.0f}"
                    f" is {derived:,.0f}, but {spec.closing} states"
                    f" {closing[key]:,.0f}",
                ))

        # The carry, between consecutive *observed* periods. With one period
        # there is no pair and this loop is empty — vacuously clean, and
        # correctly so: continuity is a claim about two observations, and the
        # single period's own movement was already held to the identity above,
        # so nothing checkable goes unchecked.
        for earlier, later in zip(periods, periods[1:]):
            if (subject, earlier) not in closing or (subject, later) not in opening:
                continue  # already broken above; one gap, one report
            checks += 1
            if opening[(subject, later)] != closing[(subject, earlier)]:
                breaks.append(Break(
                    "stock_tears_between_periods", subject, later,
                    f"{later} opens at {opening[(subject, later)]:,.0f} but"
                    f" {earlier} closed at {closing[(subject, earlier)]:,.0f}"
                    " — a balance changed between two records with no flow"
                    " stating why",
                ))

    return breaks, checks


__all__ = ["Break", "StockFlowSpec", "close", "verify"]
