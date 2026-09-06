from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from worldloom import sdk
from worldloom.fact_ledger import AmbiguousFactView, FactLedger
from worldloom.models import Authority, CanonicalFact, Quantity

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _fact(
    id: str,
    amount: float,
    *,
    observer: str | None = None,
    source_system: str = "erp",
    valid_from: datetime = T0,
    valid_to: datetime | None = None,
    tx_from: datetime | None = None,
    tx_to: datetime | None = None,
    supersedes: str | None = None,
    authority: Authority = Authority.SYSTEM_OF_RECORD,
) -> CanonicalFact:
    return CanonicalFact(
        id=id,
        kind="finance.revenue",
        subject="bu:retail",
        period="2026-01",
        value=Quantity(amount=amount, unit="AUD"),
        valid_from=valid_from,
        valid_to=valid_to,
        tx_from=tx_from,
        tx_to=tx_to,
        authority=authority,
        source_system=source_system,
        observer=observer,
        supersedes=supersedes,
    )


def test_view_separates_what_was_known_from_what_is_known_now() -> None:
    original = _fact("F-1", 100, tx_from=T0)
    corrected = _fact(
        "F-2",
        120,
        tx_from=T0 + timedelta(days=5),
        supersedes="F-1",
    )
    ledger = FactLedger((original, corrected))

    tuesday = ledger.view(
        "*", valid_at=T0 + timedelta(days=2), tx_at=T0 + timedelta(days=2)
    )
    now = ledger.view(
        "*", valid_at=T0 + timedelta(days=2), tx_at=T0 + timedelta(days=10)
    )

    assert [fact.id for fact in tuesday] == ["F-1"]
    assert [fact.id for fact in now] == ["F-2"]


def test_view_isolates_observer_channels() -> None:
    finance = _fact("F-FIN", 98, observer="finance", authority=Authority.REPORTED)
    ops = _fact("F-OPS", 104, observer="ops", authority=Authority.REPORTED)
    ledger = FactLedger((finance, ops))

    finance_view = ledger.view("finance", valid_at=T0, tx_at=T0)
    ops_view = ledger.view("ops", valid_at=T0, tx_at=T0)

    assert [fact.id for fact in finance_view] == ["F-FIN"]
    assert [fact.id for fact in ops_view] == ["F-OPS"]


def test_oracle_refuses_equal_rank_disagreement() -> None:
    a = _fact("F-A", 100, source_system="erp-a")
    b = _fact("F-B", 101, source_system="erp-b")

    with pytest.raises(AmbiguousFactView, match="disagree"):
        FactLedger((a, b)).view("*", valid_at=T0, tx_at=T0)


def test_raw_ledger_retains_every_history_row() -> None:
    first = _fact("F-1", 100, tx_from=T0)
    second = _fact(
        "F-2",
        120,
        tx_from=T0 + timedelta(days=1),
        supersedes="F-1",
    )

    assert FactLedger((first, second)).to_tuple() == (first, second)


def test_world_keeps_raw_history_and_exposes_explicit_resolved_views() -> None:
    first = _fact("F-1", 100, tx_from=T0)
    second = _fact(
        "F-2",
        120,
        tx_from=T0 + timedelta(days=5),
        supersedes="F-1",
    )
    base = sdk.retail(seed=31).build().world
    world = replace(base, _facts=(first, second))

    assert world.facts.ids() == ["F-1", "F-2"]
    assert world.fact_ledger().to_tuple() == (first, second)
    assert world.fact_view(
        "*", valid_at=T0 + timedelta(days=2), tx_at=T0 + timedelta(days=2)
    ).ids() == ["F-1"]
    assert world.fact_view(
        "*", valid_at=T0 + timedelta(days=2), tx_at=T0 + timedelta(days=10)
    ).ids() == ["F-2"]
