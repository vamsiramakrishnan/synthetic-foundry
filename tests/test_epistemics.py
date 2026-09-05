from datetime import UTC, datetime

from worldloom.epistemics import FactLedger, FactObservation
from worldloom.models import Authority, Quantity


def _obs(
    id_: str,
    *,
    amount: float,
    observer: str,
    recorded: str,
    authority: Authority,
    source: str = "erp",
) -> FactObservation:
    return FactObservation(
        id=id_,
        fact_id="F-1",
        kind="inventory_on_hand",
        subject="SKU-42",
        value=Quantity(amount=amount, unit="units"),
        source_system=source,
        observer_id=observer,
        valid_from=datetime(2026, 9, 1, tzinfo=UTC),
        recorded_at=datetime.fromisoformat(recorded),
        authority=authority,
    )


def test_bitemporal_cut_distinguishes_then_from_now() -> None:
    early = _obs(
        "O-early",
        amount=7760,
        observer="store-manager",
        recorded="2026-09-01T10:00:00+00:00",
        authority=Authority.UNOFFICIAL_NOTE,
    )
    corrected = _obs(
        "O-corrected",
        amount=7814,
        observer="inventory-control",
        recorded="2026-09-03T09:00:00+00:00",
        authority=Authority.SYSTEM_OF_RECORD,
    )
    ledger = FactLedger((early, corrected))
    valid_at = datetime(2026, 9, 1, 12, tzinfo=UTC)

    then = ledger.as_known(
        valid_at=valid_at,
        recorded_at=datetime(2026, 9, 1, 18, tzinfo=UTC),
    )
    now = ledger.as_known(
        valid_at=valid_at,
        recorded_at=datetime(2026, 9, 5, tzinfo=UTC),
    )

    assert then.best() == early
    assert now.best() == corrected


def test_observer_and_system_views_are_first_class() -> None:
    finance = _obs(
        "O-finance",
        amount=7921,
        observer="finance",
        recorded="2026-09-01T11:00:00+00:00",
        authority=Authority.WORKING_DOCUMENT,
        source="forecast-workbook",
    )
    operations = _obs(
        "O-ops",
        amount=7814,
        observer="operations",
        recorded="2026-09-01T11:30:00+00:00",
        authority=Authority.CONFIRMED,
        source="wms",
    )
    ledger = FactLedger((finance, operations))

    assert ledger.observed_by("finance").to_tuple() == (finance,)
    assert ledger.from_system("wms").to_tuple() == (operations,)


def test_record_time_may_follow_valid_time_for_restatement() -> None:
    observation = _obs(
        "O-late",
        amount=7814,
        observer="auditor",
        recorded="2026-09-05T10:00:00+00:00",
        authority=Authority.CONFIRMED,
    )

    assert observation.valid_from == datetime(2026, 9, 1, tzinfo=UTC)
    assert observation.recorded_at == datetime(2026, 9, 5, 10, tzinfo=UTC)
