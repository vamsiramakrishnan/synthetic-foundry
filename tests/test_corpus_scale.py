from __future__ import annotations

import csv
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from worldloom import corpus
from worldloom.corpus_scale import (
    CorpusScaleManifest,
    CorpusScaleProfile,
    NativeScaleTarget,
    assess_corpus_scale,
    export_corpus_scale,
    plan_corpus_scale,
    verify_corpus_scale,
)
from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Company,
)
from worldloom.synthesis.engine import Simulator
from worldloom.synthesis.models import (
    Column,
    Program,
    SynthesisError,
    Table,
    literal,
    ref,
)
from worldloom.synthesis.programs import retail
from worldloom.world import World


def _world(sections: int = 8) -> World:
    facts = tuple(CanonicalFact(id=f"FACT-{i:04}", kind="retail.receipt.exception", subject=f"purchase-order:{i}",
        text_value=f"Supplier receipt for purchase order {i} requires receiving-team reconciliation.",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC), authority=Authority.SYSTEM_OF_RECORD)
        for i in range(sections))
    return World(company=Company(id="CO-1", name="Northstar Retail", industry="retail", headquarters="Sydney",
        fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-1", intent_id="INTENT-1", title="Receiving register", sections=[
            ArtifactSection(heading="Supplier reconciliation", body=f"Receiving disposition: {{{{fact:{fact.id}}}}}",
                            fact_ids=[fact.id]) for fact in facts]),))


def _profile(native: bool = True) -> CorpusScaleProfile:
    return CorpusScaleProfile(name="pilot", minimum_relational_rows=40,
        native_targets=(NativeScaleTarget(format="docx", minimum_units=4, minimum_distinct_facts=4),
                        NativeScaleTarget(format="pptx", minimum_units=3, minimum_distinct_facts=3)) if native else ())


def test_scale_adequacy_reports_shortfalls_without_minting_evidence() -> None:
    world = _world(2)
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    profile = _profile().model_copy(update={"minimum_relational_rows": 1_000_000})
    report = assess_corpus_scale(world, simulation, profile=profile)
    assert not report.adequate
    assert report.relational_rows_planned == 41
    assert report.grounded_authored_units == report.distinct_authored_facts == 2
    assert {(f.code, f.target, f.expected, f.observed) for f in report.findings} == {
        ("relational_row_shortfall", "relational", 1_000_000, 41),
        ("authored_content_shortfall", "docx", 4, 2), ("canonical_fact_shortfall", "docx", 4, 2),
        ("authored_content_shortfall", "pptx", 3, 2), ("canonical_fact_shortfall", "pptx", 3, 2),
    }
    with pytest.raises(SynthesisError, match="relational_row_shortfall"):
        plan_corpus_scale(world, simulation, profile=profile)


def test_scaled_corpus_materialises_native_depth_real_joins_and_exact_statistics(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    pytest.importorskip("pptx")
    world = _world()
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    plan = plan_corpus_scale(world, simulation, profile=_profile(), csv_shard_rows=5)
    assert plan.native_surface == "business"
    assert all(native.surface == "business" for native in plan.native_plans)
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = export_corpus_scale(world, plan, first)
    assert manifest == export_corpus_scale(world, plan, second)
    assert corpus.tree_divergence(first, second) is None
    assert verify_corpus_scale(world, first) == manifest
    assert export_corpus_scale(world, plan, first, resume=True) == manifest
    assert manifest.relational_rows == 41
    assert manifest.foreign_key_links == 72
    assert manifest.physical_native_pages is None
    assert manifest.distinct_native_facts == 8
    assert len(manifest.native) == 2
    assert all(not native.ballast_is_evidence for native in manifest.native)
    records = {}
    for table in manifest.tables:
        records[table.name] = []
        for shard in table.csv_shards:
            with (first / shard).open(newline="", encoding="utf-8") as source:
                part = list(csv.DictReader(source))
            assert 1 <= len(part) <= 5
            records[table.name].extend(part)
        assert len(records[table.name]) == table.rows
        assert {row["company_id"] for row in records[table.name]} == {world.company.id}
    assert {row["fk_store"] for row in records["inventory"]} <= {row["entity_id"] for row in records["store"]}
    assert {row["fk_product"] for row in records["inventory"]} <= {row["entity_id"] for row in records["product"]}
    inventory = next(table for table in manifest.tables if table.name == "inventory")
    revenue = next(column for column in inventory.columns if column.name == "revenue")
    assert revenue.unit == "minor_currency"
    assert revenue.total == sum(int(row["revenue"]) for row in records["inventory"])
    assert revenue.maximum == max(int(row["revenue"]) for row in records["inventory"])
    assert revenue.minimum == min(int(row["revenue"]) for row in records["inventory"])


def test_verification_refuses_forged_csv_even_when_manifest_checksum_is_updated(tmp_path: Path) -> None:
    world = _world()
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    plan = plan_corpus_scale(world, simulation, profile=_profile(native=False), csv_shard_rows=5)
    directory = tmp_path / "scaled"
    manifest = export_corpus_scale(world, plan, directory)
    chosen = next(file for file in manifest.files if file.kind == "csv")
    path = directory / chosen.path
    changed = path.read_bytes().replace(b"CO-1", b"CO-2", 1)
    path.write_bytes(changed)
    corrupted = manifest.model_copy(update={"files": tuple(
        file.model_copy(update={"sha256": hashlib.sha256(changed).hexdigest()}) if file == chosen else file
        for file in manifest.files)})
    corpus.write_json(directory / "manifest.json", corrupted.model_dump(mode="json"))
    with pytest.raises(SynthesisError, match="scale_projection_replay"):
        verify_corpus_scale(world, directory)


def test_scaled_corpus_refuses_rebound_company_and_revised_fact(tmp_path: Path) -> None:
    world = _world()
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    plan = plan_corpus_scale(world, simulation, profile=_profile(native=False))
    other = replace(world, company=world.company.model_copy(update={"id": "CO-2"}))
    with pytest.raises(SynthesisError, match="scale_company_binding"):
        export_corpus_scale(other, plan, tmp_path / "other")
    revised = replace(world, _facts=(world._facts[0].model_copy(update={"text_value": "Revised receipt"}), *world._facts[1:]))
    with pytest.raises(SynthesisError, match="scale_company_binding"):
        export_corpus_scale(revised, plan, tmp_path / "revised")


def test_byte_shards_and_bounded_exact_distinct_statistics(tmp_path: Path) -> None:
    simulation = Simulator(Program(namespace="large_register", tables=(
        Table(name="register", count=600, temporal=True, columns=(Column(name="ordinal", expression=ref("_entity")),)),)), seed=7)
    world = _world()
    profile = CorpusScaleProfile(name="bounded", minimum_relational_rows=600)
    plan = plan_corpus_scale(world, simulation, profile=profile, csv_shard_rows=1000, csv_shard_bytes=4096)
    manifest = export_corpus_scale(world, plan, tmp_path / "scaled")
    assert manifest.relational_rows == 600
    assert all(file.file_size_bytes <= 4096 for file in manifest.files if file.kind == "csv")
    assert len(manifest.tables[0].csv_shards) > 1
    column = manifest.tables[0].columns[0]
    assert column.distinct_observed == 512
    assert not column.distinct_exact
    assert column.total == sum(range(600))
    assert verify_corpus_scale(world, tmp_path / "scaled") == manifest


def test_optional_spreadsheets_preserve_types_and_literal_company_text(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    simulation = Simulator(Program(namespace="typed_register", tables=(Table(name="register", count=2,
        columns=(Column(name="amount", expression=literal(12500), unit="minor_currency"),
                 Column(name="approved", expression=literal(True), kind="bool"),
                 Column(name="description", expression=literal("=SUM(A1:A9)"), kind="str"))),)), seed=7)
    world = _world()
    world = replace(world, company=world.company.model_copy(update={"name": "=Northstar Retail"}))
    plan = plan_corpus_scale(world, simulation, profile=CorpusScaleProfile(name="typed", minimum_relational_rows=2),
                            spreadsheets=True, csv_shard_rows=1)
    manifest = export_corpus_scale(world, plan, tmp_path / "scaled")
    assert len(manifest.tables[0].spreadsheet_shards) == 2
    for shard in manifest.tables[0].spreadsheet_shards:
        workbook = openpyxl.load_workbook(tmp_path / "scaled" / shard)
        sheet = workbook["Records"]
        cells = dict(zip((cell.value for cell in sheet[1]), sheet[2], strict=True))
        assert cells["amount"].value == 12500
        assert cells["amount"].data_type == "n"
        assert cells["approved"].value is True
        assert cells["description"].value == "=SUM(A1:A9)"
        assert cells["description"].data_type == "s"
    assert verify_corpus_scale(world, tmp_path / "scaled") == manifest


def test_projection_namespace_and_file_budget_refusals() -> None:
    world = _world()
    profile = CorpusScaleProfile(name="small")
    simulation = Simulator(Program(namespace="collision", tables=(Table(name="register", count=1,
        columns=(Column(name="row_id", expression=literal("claimed"), kind="str"),)),)), seed=7)
    with pytest.raises(SynthesisError, match="reserved_projection_column"):
        plan_corpus_scale(world, simulation, profile=profile)
    normal = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    with pytest.raises(SynthesisError, match="scale_file_budget"):
        plan_corpus_scale(world, normal, profile=profile, csv_shard_rows=1, maximum_files=10)


def test_measured_counts_are_recomputed_instead_of_trusting_manifest(tmp_path: Path) -> None:
    world = _world()
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    plan = plan_corpus_scale(world, simulation, profile=_profile(native=False))
    manifest = export_corpus_scale(world, plan, tmp_path / "scaled")
    altered = CorpusScaleManifest.model_validate(manifest.model_dump(mode="json") | {"relational_rows": 1_000_000})
    corpus.write_json(tmp_path / "scaled" / "manifest.json", altered.model_dump(mode="json"))
    with pytest.raises(SynthesisError, match="scale_measurement"):
        verify_corpus_scale(world, tmp_path / "scaled")


def test_large_ledger_allocations_reconcile_to_canonical_fact_and_preserve_declared_skew(tmp_path: Path) -> None:
    from worldloom.corpus_scale import ledger_allocation_source
    from worldloom.models import Quantity

    world = _world()
    fact = world._facts[0].model_copy(update={"value": Quantity(amount=12550.75, unit="AUD"), "text_value": None})
    world = replace(world, _facts=(fact, *world._facts[1:]))
    source = ledger_allocation_source(world, fact_id=fact.id, rows=10_000, seed=8128)
    profile = CorpusScaleProfile(name="ledger", minimum_relational_rows=10_001)
    plan = plan_corpus_scale(world, source.simulator, profile=profile, reconciliations=(source.reconciliation,), csv_shard_rows=2000)
    manifest = export_corpus_scale(world, plan, tmp_path / "ledger")
    transaction = next(table for table in manifest.tables if table.name == "transaction")
    amount = next(column for column in transaction.columns if column.name == "amount_scaled")
    assert amount.total == 1_255_075
    assert amount.unit == "AUD*10^-2"
    assert manifest.reconciliations == (source.reconciliation,)
    assert manifest.foreign_key_links == 10_000
    rows = [row for row in source.simulator.rows() if row.table == "transaction"]
    ranks = {int(row.values()["allocation_rank"]) for row in rows}
    assert ranks == set(range(10_000))
    head = [int(row.values()["amount_scaled"]) for row in rows if int(row.values()["allocation_rank"]) < 1000]
    tail = [int(row.values()["amount_scaled"]) for row in rows if int(row.values()["allocation_rank"]) >= 1000]
    assert sum(head) == 1_004_060
    assert sum(tail) == 251_015
    assert verify_corpus_scale(world, tmp_path / "ledger") == manifest


def test_incorrect_canonical_reconciliation_fails_atomically(tmp_path: Path) -> None:
    from worldloom.corpus_scale import ledger_allocation_source
    from worldloom.models import Quantity

    world = _world()
    first = world._facts[0].model_copy(update={"value": Quantity(amount=100, unit="AUD"), "text_value": None})
    second = world._facts[1].model_copy(update={"value": Quantity(amount=101, unit="AUD"), "text_value": None})
    world = replace(world, _facts=(first, second, *world._facts[2:]))
    source = ledger_allocation_source(world, fact_id=first.id, rows=20, seed=8128)
    binding = source.reconciliation.model_copy(update={"fact_id": second.id})
    plan = plan_corpus_scale(world, source.simulator, profile=CorpusScaleProfile(name="mismatch"), reconciliations=(binding,))
    with pytest.raises(SynthesisError, match="canonical_total_mismatch"):
        export_corpus_scale(world, plan, tmp_path / "mismatch")
    assert not (tmp_path / "mismatch").exists()
    assert list(tmp_path.iterdir()) == []


def test_unauthored_sections_and_paraphrases_do_not_inflate_adequacy() -> None:
    world = _world(1)
    original = world._artifact_irs[0]
    sections = [*original.sections, ArtifactSection(heading="Planned section", body=None), original.sections[0]]
    world = replace(world, _artifact_irs=(original.model_copy(update={"sections": sections}),))
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    report = assess_corpus_scale(world, simulation, profile=_profile())
    assert report.grounded_authored_units == report.distinct_authored_facts == 1
    assert not report.adequate


def test_rendering_decisions_are_part_of_the_world_binding(tmp_path: Path) -> None:
    from worldloom import recipe

    world = _world()
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    plan = plan_corpus_scale(world, simulation, profile=_profile(native=False))
    german = replace(world, _recipe=recipe.with_locale(world.recipe, "germany"))
    reader = replace(world, _recipe=recipe.with_presentation(world.recipe, "reader"))
    for changed in (german, reader):
        with pytest.raises(SynthesisError, match="scale_company_binding"):
            export_corpus_scale(changed, plan, tmp_path / "rebound")
    assert not (tmp_path / "rebound").exists()


def test_export_and_verify_refuse_symbolic_link_root(tmp_path: Path) -> None:
    world = _world()
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    plan = plan_corpus_scale(world, simulation, profile=_profile(native=False))
    export_corpus_scale(world, plan, tmp_path / "real")
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(SynthesisError, match="invalid_scale_corpus"):
        export_corpus_scale(world, plan, tmp_path / "alias", resume=True)
    with pytest.raises(SynthesisError, match="invalid_scale_corpus"):
        verify_corpus_scale(world, tmp_path / "alias")


def test_public_table_inventory_omits_curator_files_and_canonical_fact_keys(tmp_path: Path) -> None:
    from worldloom.corpus_scale import ledger_allocation_source
    from worldloom.models import Quantity

    world = _world()
    fact = world._facts[0].model_copy(update={"value": Quantity(amount=100, unit="AUD"), "text_value": None})
    world = replace(world, _facts=(fact, *world._facts[1:]))
    source = ledger_allocation_source(world, fact_id=fact.id, rows=20, seed=8128)
    plan = plan_corpus_scale(world, source.simulator, profile=CorpusScaleProfile(name="public"),
                            reconciliations=(source.reconciliation,))
    manifest = export_corpus_scale(world, plan, tmp_path / "scaled")
    assert manifest.target_files
    assert all(path.startswith(("tables/", "native/")) for path in manifest.target_files)
    assert not {"plan.json", "manifest.json", "source/recipe.json", "source/manifest.json", "source/records.jsonl"} & set(manifest.target_files)
    for path in manifest.target_files:
        assert fact.id.encode() not in (tmp_path / "scaled" / path).read_bytes()
    assert verify_corpus_scale(world, tmp_path / "scaled") == manifest


def test_business_adequacy_measures_grounded_table_sections_without_prose() -> None:
    from worldloom.models import Cell, Quantity
    from worldloom.models import Column as IRColumn
    from worldloom.models import Row as IRRow
    from worldloom.models import Table as IRTable

    world = _world(1)
    fact = world._facts[0].model_copy(update={"value": Quantity(amount=125.5, unit="AUD"), "text_value": None})
    section = ArtifactSection(heading="Receiving value", table=IRTable(key="receipts", title="Receiving value",
        columns=[IRColumn(key="amount", label="Amount")], rows=[IRRow(key="receipt", label="Supplier receipt",
            cells={"amount": Cell(value=125.5, fact_id=fact.id)})]))
    world = replace(world, _facts=(fact,), _artifact_irs=(world._artifact_irs[0].model_copy(update={"sections": [section]}),))
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    profile = CorpusScaleProfile(name="structured", minimum_relational_rows=40,
        native_targets=(NativeScaleTarget(format="xlsx", minimum_units=1, minimum_distinct_facts=1),))
    report = assess_corpus_scale(world, simulation, profile=profile)
    assert report.adequate
    assert report.grounded_authored_units == report.distinct_authored_facts == 0
    assert report.grounded_native_units == report.distinct_native_facts == 1
    legacy = assess_corpus_scale(world, simulation, profile=profile, native_surface="legacy")
    assert not legacy.adequate


def test_business_entity_labels_are_part_of_rendering_binding(tmp_path: Path) -> None:
    from worldloom.models import BusinessUnit

    world = replace(_world(), _business_units=(BusinessUnit(id="BU-1", name="Supply Chain",
        company_id="CO-1", leader_id="LEADER-1", kind="shared_service"),))
    simulation = Simulator(retail(stores=2, products=3, ticks=6), seed=8128)
    plan = plan_corpus_scale(world, simulation, profile=_profile(native=False))
    changed = replace(world, _business_units=(world._business_units[0].model_copy(update={"name": "Receiving Operations"}),))
    with pytest.raises(SynthesisError, match="scale_company_binding"):
        export_corpus_scale(changed, plan, tmp_path / "rebound")


@pytest.mark.parametrize("value", [float("inf"), float("nan"), float("-inf")])
def test_allocation_refuses_nonfinite_canonical_quantity(value: float) -> None:
    from worldloom.corpus_scale import ledger_allocation_source
    from worldloom.models import Quantity

    world = _world(1)
    fact = world._facts[0].model_copy(update={"value": Quantity(amount=value, unit="AUD"), "text_value": None})
    world = replace(world, _facts=(fact,))
    with pytest.raises(SynthesisError, match="reconciliation_fact"):
        ledger_allocation_source(world, fact_id=fact.id, rows=2, seed=7)
