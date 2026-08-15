"""The stock-flow grammar, held to being generic, exact, and able to fail.

Three properties, each with the reason it is a test:

* **Generic.** The module's *code* names no industry — the vocabulary arrives
  in a ``StockFlowSpec``. Scanned the way ``test_thin_waist.py`` scans core
  (comments and docstrings stripped: prose about a consumer is not coupling),
  because "the waist stays thin" was a review habit until it was a ratchet.

* **Exact.** ``verify`` compares with ``==`` and these tests break it with a
  discrepancy of one — the validator's ``RECONCILIATION_TOLERANCE`` would
  absorb exactly that, which is why the engine must not borrow it. Every
  consumer builds its balances by integer arithmetic; a tolerance here would
  be the door a generator slides back to round-and-hope through.

* **Able to fail.** A stock-flow check that cannot fail is decoration, so
  every break code is shown firing: a movement that does not close, a balance
  that tears between periods, a missing opening, a pinned owner with no
  balance at all.

The vocabulary below is a warehouse's — deliberately not any shipped
vertical's, so nothing here passes because a domain module helped.
"""

from __future__ import annotations

from datetime import datetime, timezone

from worldloom.generators.stockflow import Break, StockFlowSpec, close, verify
from worldloom.models import Authority, CanonicalFact, Quantity

SPEC = StockFlowSpec(
    opening="inv.units.opening",
    inflows=("inv.units.received",),
    outflows=("inv.units.issued",),
    closing="inv.units.closing",
)

ADJUSTING = StockFlowSpec(
    opening="inv.units.opening",
    inflows=("inv.units.received",),
    outflows=("inv.units.issued",),
    closing="inv.units.closing",
    adjustments=("inv.units.written_off",),
)

_serial = iter(range(10_000))


def fact(kind: str, subject: str, period: str, amount: float) -> CanonicalFact:
    return CanonicalFact(
        id=f"FACT-{next(_serial):04d}",
        kind=kind,
        subject=subject,
        period=period,
        value=Quantity(amount=amount, unit="units"),
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        authority=Authority.SYSTEM_OF_RECORD,
    )


def month(subject: str, period: str, opening: float, received: float,
          issued: float, closing: float) -> list[CanonicalFact]:
    return [
        fact("inv.units.opening", subject, period, opening),
        fact("inv.units.received", subject, period, received),
        fact("inv.units.issued", subject, period, issued),
        fact("inv.units.closing", subject, period, closing),
    ]


def codes(breaks: list[Break]) -> set[str]:
    return {b.code for b in breaks}


# ---------------------------------------------------------------------------
# The grammar, holding
# ---------------------------------------------------------------------------


def test_a_consistent_history_is_clean_and_counted() -> None:
    facts = month("WH-1", "2026-01", 500, 200, 150, 550) \
        + month("WH-1", "2026-02", 550, 100, 300, 350)
    breaks, checks = verify(SPEC, facts)
    assert breaks == []
    # Three claims per period (opening present, closing present, identity)
    # plus one carry between the pair — counted, because a check group's cost
    # must be readable off its checks number.
    assert checks == 7


def test_derive_and_verify_are_one_identity() -> None:
    """`close` is the generator's half of the same sentence `verify` checks,
    so a balance derived by one must always satisfy the other."""
    closing = close(500, [200], [150])
    assert closing == 550
    breaks, _ = verify(SPEC, month("WH-1", "2026-01", 500, 200, 150, closing))
    assert breaks == []


def test_adjustments_are_added_as_stated() -> None:
    """A write-down arrives as a negative fact, not as a hidden sign — the
    spec says *added*, so the fact carries its own direction."""
    facts = month("WH-1", "2026-01", 500, 200, 150, 530)
    facts.append(fact("inv.units.written_off", "WH-1", "2026-01", -20))
    breaks, _ = verify(ADJUSTING, facts)
    assert breaks == []
    assert close(500, [200], [150], [-20]) == 530


def test_a_single_period_is_vacuously_continuous_and_still_checked() -> None:
    """One period: the carry clause has nothing to compare, and that is
    correct rather than a hole — continuity is a claim about two observations.
    Nothing checkable goes unchecked: the opening must still exist and the
    period's own movement is still held to the identity, which the second half
    of this test proves by breaking it."""
    breaks, checks = verify(SPEC, month("WH-1", "2026-01", 500, 200, 150, 550))
    assert breaks == []
    assert checks == 3  # presence twice, identity once; no carry to count

    broken, _ = verify(SPEC, month("WH-2", "2026-01", 500, 200, 150, 999))
    assert codes(broken) == {"movement_does_not_close"}


# ---------------------------------------------------------------------------
# The grammar, failing — every code shown firing
# ---------------------------------------------------------------------------


def test_a_movement_that_does_not_close_names_the_period_and_subject() -> None:
    facts = month("WH-1", "2026-01", 500, 200, 150, 550) \
        + month("WH-1", "2026-02", 550, 100, 300, 340)  # 10 short
    breaks, _ = verify(SPEC, facts)
    assert len(breaks) == 1
    tear = breaks[0]
    assert tear.code == "movement_does_not_close"
    assert tear.subject == "WH-1"
    assert tear.period == "2026-02"
    assert "350" in tear.detail and "340" in tear.detail


def test_a_discrepancy_of_one_fires_because_there_is_no_tolerance() -> None:
    """The claim in the module docstring, enforced: `==`, never a band. A
    version of `verify` that adopted the validator's reconciliation tolerance
    would pass this corpus and fail this test."""
    breaks, _ = verify(SPEC, month("WH-1", "2026-01", 500, 200, 150, 551))
    assert codes(breaks) == {"movement_does_not_close"}


def test_a_balance_that_tears_between_periods_fires_naming_both() -> None:
    facts = month("WH-1", "2026-01", 500, 200, 150, 550) \
        + month("WH-1", "2026-02", 560, 100, 300, 360)  # opens 10 high
    breaks, _ = verify(SPEC, facts)
    assert codes(breaks) == {"stock_tears_between_periods"}
    tear = breaks[0]
    assert tear.period == "2026-02"
    assert "2026-01" in tear.detail and "550" in tear.detail and "560" in tear.detail


def test_a_closing_with_no_opening_beside_it_fires() -> None:
    facts = month("WH-1", "2026-01", 500, 200, 150, 550)
    facts = [f for f in facts if f.kind != "inv.units.opening"]
    breaks, _ = verify(SPEC, facts, subjects=("WH-1",))
    assert codes(breaks) == {"movement_has_no_opening"}


def test_an_opening_never_struck_fires() -> None:
    facts = month("WH-1", "2026-01", 500, 200, 150, 550)
    facts = [f for f in facts if f.kind != "inv.units.closing"]
    breaks, _ = verify(SPEC, facts, subjects=("WH-1",))
    assert codes(breaks) == {"movement_has_no_closing"}


def test_a_pinned_owner_with_no_balance_at_all_is_a_break_not_a_silence() -> None:
    """The decoration hazard, closed: unpinned, a corpus that dropped every
    movement fact verifies vacuously clean, so a check group that knows the
    balance's owner pins it and gets a break instead."""
    silent, _ = verify(SPEC, [])
    assert silent == []  # a reading over an unknown corpus may be empty
    breaks, checks = verify(SPEC, [], subjects=("WH-1",))
    assert codes(breaks) == {"stock_is_unstated"}
    assert checks == 1


def test_subjects_are_independent_and_a_break_names_the_right_one() -> None:
    facts = month("WH-1", "2026-01", 500, 200, 150, 550) \
        + month("WH-2", "2026-01", 100, 50, 30, 999)
    breaks, _ = verify(SPEC, facts)
    assert [(b.code, b.subject) for b in breaks] == [("movement_does_not_close", "WH-2")]


# ---------------------------------------------------------------------------
# Generic, by ratchet
# ---------------------------------------------------------------------------


def test_the_engine_code_names_no_vertical() -> None:
    """`test_thin_waist.py`'s measurement, applied to this module: coupling is
    measured in code, with comments and docstrings stripped, because prose
    *about* a consumer is how the module explains itself and code *of* a
    consumer is how the waist thickens. The banned list is the procurement
    vocabulary the first consumer would most plausibly have leaked."""
    import io
    import tokenize
    from pathlib import Path

    source = (Path("src/worldloom/generators/stockflow.py")).read_text(encoding="utf-8")
    code: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            # Strings go too, not only docstrings: this module has no business
            # holding *any* literal that names a domain — its break details are
            # built from the spec's own kind names, which arrive as data.
            continue
        code.append(token.string)
    flat = " ".join(code).lower()
    for word in ("p2p", "procurement", "commitment", "supplier", "spend",
                 "capital", "reserve", "grni"):
        assert word not in flat, f"stockflow.py code names a vertical: {word!r}"
