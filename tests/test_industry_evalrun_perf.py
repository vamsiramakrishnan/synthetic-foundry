"""A programme's record requests read one index of its records, never a scan each."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from worldloom import industry, sor
from worldloom.connector_data import ConnectorRecord
from worldloom.process_bindings import BusinessUnit, CompanySpec


class Unscannable(Sequence[ConnectorRecord]):
    """A record set a row may look up through its index but never walk."""

    def __init__(self, records: Sequence[ConnectorRecord]) -> None:
        self.records = tuple(records)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, item: Any) -> Any:
        raise AssertionError("evalrun_row scanned the record set")

    def __iter__(self) -> Iterator[ConnectorRecord]:
        raise AssertionError("evalrun_row scanned the record set")


def scanned_population(request: industry.Request, records: Sequence[ConnectorRecord]) -> list[str]:
    """The population as the row was first built: a scan of every record."""
    by_id = {record.id: record for record in records}
    binding_id = str(next(by_id[r] for r in request.expected_record_ids if r in by_id).fields["binding_id"])
    return [record.id for record in records
            if record.fields.get("binding_id") == binding_id and record.fields.get("period") == request.period]


@pytest.fixture(scope="module")
def derived() -> industry.Programme:
    company = CompanySpec(name="Ardent Telecom", industry="telecom", operating_model="centralised", countries=("IN",),
                          bus=(BusinessUnit(name="Consumer", archetype="customer_segment"),
                               BusinessUnit(name="Group Finance", archetype="group_function")))
    return industry.programme(company)


def test_rows_read_the_index_and_match_a_full_scan(derived: industry.Programme) -> None:
    index = industry._RecordIndex.of(derived.records)
    blind = Unscannable(derived.records)
    record_requests = [r for r in derived.requests if r.expected_record_ids]
    assert record_requests
    # A lone call scans to build its own index; a spread sample keeps the
    # comparison with it linear.
    for request in record_requests[::max(1, len(record_requests) // 40)]:
        row = industry.evalrun_row(request, blind, index=index)
        assert row == industry.evalrun_row(request, derived.records)
        searched = [rid for node in row["expected_dag"]["nodes"] for rid in node["expected_reads"]]
        assert sorted(searched) == sorted(scanned_population(request, derived.records))
        assert all(node["server"] == sor.CONNECTOR for node in row["expected_dag"]["nodes"])


def test_cases_are_the_rows_in_request_order(derived: industry.Programme) -> None:
    cases = industry.evalrun_cases(derived)
    index = industry._RecordIndex.of(derived.records)
    rows = [industry.evalrun_row(r, derived.records, index=index) for r in derived.requests if r.expected_record_ids]
    assert [case.row for case in cases] == rows
    chosen = [rows[0]["id"], rows[-1]["id"]]
    assert [case.id for case in industry.evalrun_cases(derived, requests_selected=chosen)] == chosen
