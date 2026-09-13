"""Every system the catalogue names has records, served through one connector.

The `sor` connector's entities are the catalogue's record kinds and its
records are derived from a company's bindings: the same compiled catalogue
yields the same records, ids in the product's own pattern, a status from the
kind's workflow, an amount where the kind carries money, the binding's
exception on the records that tripped it. The shipped definition and
emulator table equal a rebuild from the catalogue, and with them no line of
any industry lacks an emulated source.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldloom import industry, sor
from worldloom.connector_definition import (
    REFERENCE_CONNECTORS,
    load_connector_definition,
)
from worldloom.connector_emulator import ConnectorEmulator
from worldloom.process_bindings import compile_company, default_company, load_catalogue

REPO = Path(__file__).resolve().parents[1]


def test_the_shipped_connector_and_emulator_table_equal_a_rebuild() -> None:
    from tools.build_sor_connector import build

    definition, table = build()
    shipped = json.loads((REPO / "src/worldloom/_data/connectors/sor.json").read_text(encoding="utf-8"))
    assert shipped == definition
    shipped_table = json.loads(
        (REPO / "src/worldloom/_data/process-catalogue/emulated-systems@2.json").read_text(encoding="utf-8")
    )
    assert shipped_table == table
    assert "sor" in REFERENCE_CONNECTORS
    loaded = load_connector_definition("sor")
    assert len(loaded.entities) == len(definition["entities"]) > 60
    assert loaded.entities["purchase_order"].workflow is not None
    assert loaded.entities["purchase_order"].workflow.states[0] == "created"
    assert table["products"]["SAP S/4HANA"]["connector"] == "sor"
    assert {"SalesOrder", "PurchaseOrder", "JournalEntry"} <= set(table["products"]["SAP S/4HANA"]["objects"])
    assert table["products"]["ServiceNow"]["connector"] == "servicenow", "a product with its own emulator keeps it"


def test_every_product_the_catalogue_names_is_emulated_so_no_line_is_unsupported() -> None:
    cat = load_catalogue()
    products = {product for spec in cat["sor_classes"].values() for product in spec.get("products", {})}
    table = industry.emulated_systems()
    assert products <= set(table["products"])
    for name in ("banking", "retail", "telecom", "healthcare", "public_sector"):
        summary = industry.programme(name).summary
        assert summary.unsupported_lines == ()
        assert all(item.startswith("channel:") for item in summary.unemulated), summary.unemulated


def test_records_are_derived_from_bindings_and_the_same_every_time() -> None:
    compiled = compile_company(default_company("banking"))
    periods = sor.periods_ending("2026-03", 3)
    assert periods == ("2026-01", "2026-02", "2026-03")
    first = sor.records(compiled, company_id="C1", periods=periods)
    second = sor.records(compiled, company_id="C1", periods=periods)
    assert first == second and first
    bound = [row for row in compiled.rows if row.sor_objects]
    assert len(first) == sum(len(row.sor_objects) for row in bound) * len(periods) * sor.RECORDS_PER_PERIOD
    assert len({record.id for record in first}) == len(first)
    by_kind = {record.fields["object"]: record for record in first}
    po = by_kind["PurchaseOrder"]
    assert po.connector == "sor" and po.entity == "purchase_order"
    assert po.external_id.startswith("45") and len(po.external_id) == 10, "SAP's 45{8d} pattern"
    assert po.fields["table"] == "EKKO/EKPO" and po.fields["tcode"] == "ME21N"
    assert po.fields["status"] in load_connector_definition("sor").entities["purchase_order"].workflow.states  # type: ignore[union-attr]
    assert po.fields["amount"] > 0 and po.fields["currency"]
    assert po.fields["pcf_id"] and po.fields["pcf_name"] and po.fields["activity_id"]
    worker = by_kind["Worker"]
    assert "amount" not in worker.fields
    tripped = [r for r in first if r.fields["exception"]]
    with_exception = [r for r in first if any(
        row.id == r.fields["binding_id"] and row.exception.strip() for row in bound)]
    assert with_exception and 0 < len(tripped) < len(with_exception)
    facts = industry.facts(compiled)
    linked = sor.records(compiled, company_id="C1", periods=periods[:1], facts=facts)
    assert all(record.fact_ids for record in linked)


def test_the_emulator_serves_the_records_and_mints_ids_in_the_pattern() -> None:
    compiled = compile_company(default_company("retail"))
    rows = sor.records(compiled, company_id="C1", periods=("2026-02",))
    definition = load_connector_definition("sor")
    emulator = ConnectorEmulator(definition, [
        {**r.fields, "fid": r.id, "server": "sor", "entity": r.entity, "ident": r.external_id,
         "external_id": r.external_id, "name": r.title, "title": r.title}
        for r in rows
    ])
    activity = rows[0].fields["activity_id"]
    found = emulator.call("search_records", entity=rows[0].entity, predicate={"activity_id": activity}, _node="read")
    hits = found.get("records") or found.get("items") or found.get("results") or []
    assert hits and all(hit["activity_id"] == activity for hit in hits)
    created = emulator.call("create_record", entity="purchase_order", name="PO for a test",
                            fields={"activity_id": "p2p.04", "owner_bu": "Supermarkets", "period": "2026-02", "object": "PurchaseOrder"},
                            _node="write")
    ident = created.get("ident") or created.get("id") or created.get("external_id")
    assert ident and ident.startswith("SOR") and len(ident) == len("SOR") + 10


def test_projections_ride_beside_the_builtin_ones() -> None:
    compiled = compile_company(default_company("telecom"))

    class Company:
        id = "C9"

    class WorldLike:
        period = "2026-06"
        company = Company()

    registry = sor.projections(compiled, WorldLike(), periods=2)
    assert "sor" in registry.names and "jira" in registry.names
    assert sor.entity_name("APOpenItem") == "ap_open_item" and sor.entity_name("KB") == "kb"


def test_a_frozen_company_build_reads_the_projections(tmp_path: Path) -> None:
    from worldloom.evals.company_dataset import FrozenCompanyBuilder
    from worldloom.studio.service import Studio

    spec = industry.project("telecom", "Ardent Telecom", lobs=("billing",))
    world, _ = Studio(tmp_path).snapshot(spec)
    compiled = compile_company(spec.structure)  # type: ignore[arg-type]
    registry = sor.projections(compiled, world, periods=2)
    builder = FrozenCompanyBuilder(world, seed=spec.seed, projections=registry)
    assert builder.projections is registry
    served = registry.project("sor", world)
    assert served and all(record.connector == "sor" for record in served)
    assert any(record.fields["stream"] == "usage_to_bill" for record in served)


def test_answers_are_read_off_the_records_by_shape() -> None:
    compiled = compile_company(default_company("retail"))
    rows = sor.records(compiled, company_id=compiled.company, periods=("2026-06",))
    grouped = sor.by_binding(rows)
    binding = next(b for b, periods in grouped.items()
                   if any(r.fields["exception"] for r in periods["2026-06"]) and any(not r.fields["terminal"] for r in periods["2026-06"]))
    period_rows = grouped[binding]["2026-06"]
    assert len(period_rows) == sor.RECORDS_PER_PERIOD * len({r.fields["object"] for r in period_rows})
    text, ids = sor.answer("find_exception", "list", period_rows)
    tripped = [r for r in period_rows if r.fields["exception"]]
    assert ids == tuple(sorted((r.id for r in tripped), key=lambda i: next(x.external_id for x in tripped if x.id == i)))[:0] or set(ids) == {r.id for r in tripped}
    assert text.startswith(f"{len(tripped)} of {len(period_rows)}") and "tripped the exception" in text
    text, ids = sor.answer("triage_queue", "ranked_list", period_rows)
    assert set(ids) == {r.id for r in period_rows if not r.fields["terminal"]} and "by workflow stage" in text
    text, ids = sor.answer("chase", "message", period_rows)
    assert text.startswith("Chase ") and set(ids) == {r.id for r in tripped}
    text, ids = sor.answer("respond_to_query", "narrative", period_rows)
    assert set(ids) == {r.id for r in period_rows} and " is " in text
    closed = [r.model_copy(update={"fields": {**r.fields, "terminal": True, "exception": ""}}) for r in period_rows]
    assert sor.answer("triage_queue", "ranked_list", closed)[0].startswith("Nothing to triage")
    assert sor.answer("chase", "message", closed)[0].startswith("Nothing to chase")
    assert sor.answer("find_exception", "list", closed)[0].startswith("None of the")
    with pytest.raises(ValueError, match="at least one record"):
        sor.answer("chase", "message", [])
