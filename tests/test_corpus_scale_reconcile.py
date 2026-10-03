"""Derived reconciliations bind only pairs whose meaning, unit and period match.

``reconcile="auto"`` turns "this program's revenue column is the company's
revenue" from a hand-written JSON binding into a derivation, so the tests
check both directions: a program that genuinely sums to the close builds and
verifies, a program one unit off is refused at materialisation, and every pair
the derivation cannot bind is reported with its reason rather than dropped.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import _load, app
from worldloom.corpus import write_json
from worldloom.corpus_scale import (
    CorpusScaleProfile,
    FactReconciliation,
    derive_reconciliations,
    export_corpus_scale,
    plan_corpus_scale,
    verify_corpus_scale,
)
from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.synthesis.engine import Simulator
from worldloom.synthesis.models import Column, Program, SynthesisError, Table, literal
from worldloom.synthesis.programs import retail
from worldloom.world import World

runner = CliRunner()
PROFILE = CorpusScaleProfile(name="reconcile")


def _company_fact(world: World, kind: str) -> CanonicalFact:
    return next(fact for fact in world.facts if fact.kind == kind and fact.subject == world.company.id)


def _close_program(revenue_per_store: int, gross_profit: int, *, headcount_temporal: bool = False) -> Program:
    # Four stores carrying a quarter of the close's revenue each, one summary
    # row carrying its gross profit, and a one-row-per-employee roster.
    return Program(namespace="close_operations", ticks=2 if headcount_temporal else 1, tables=(
        Table(name="store_sales", count=4, columns=(
            Column(name="revenue", expression=literal(revenue_per_store), unit="AUD_thousands*10^-0"),)),
        Table(name="close_summary", count=1, columns=(
            Column(name="gross_profit", expression=literal(gross_profit), unit="AUD_thousands*10^-0"),)),
        Table(name="roster", count=12, temporal=headcount_temporal, columns=(
            Column(name="headcount", expression=literal(1), unit="employees*10^-0"),)),
    ))


@pytest.fixture(scope="module")
def close_world() -> World:
    return _load("retail-close")


def test_matching_world_binds_revenue_and_gross_profit_and_verifies(close_world: World, tmp_path: Path) -> None:
    revenue = _company_fact(close_world, "financial.revenue.actual")
    gross = _company_fact(close_world, "financial.gross_profit.actual")
    assert revenue.value is not None and gross.value is not None
    program = _close_program(int(revenue.value.amount) // 4, int(gross.value.amount))
    derived = derive_reconciliations(close_world, program)
    assert derived.bound == (
        FactReconciliation(table="store_sales", column="revenue", fact_id=revenue.id, decimals=0),
        FactReconciliation(table="close_summary", column="gross_profit", fact_id=gross.id, decimals=0),
    )
    # retail-close records no workforce fact, so the roster stays unbound and says so.
    [headcount] = [item for item in derived.unbound if item.fact_kind == "org.headcount"]
    assert (headcount.table, headcount.column) == ("roster", "headcount")
    assert headcount.reason == "world has no current company-level org.headcount fact"

    plan = plan_corpus_scale(close_world, Simulator(program, seed=8128), profile=PROFILE, reconcile="auto")
    assert set(plan.reconciliations) == set(derived.bound)
    manifest = export_corpus_scale(close_world, plan, tmp_path / "scaled")
    assert manifest.reconciliations == plan.reconciliations
    assert verify_corpus_scale(close_world, tmp_path / "scaled") == manifest


def test_perturbed_operational_table_is_caught(close_world: World, tmp_path: Path) -> None:
    revenue = _company_fact(close_world, "financial.revenue.actual")
    gross = _company_fact(close_world, "financial.gross_profit.actual")
    assert revenue.value is not None and gross.value is not None
    # One thousand dollars of revenue per store more than the close reports.
    program = _close_program(int(revenue.value.amount) // 4 + 1, int(gross.value.amount))
    plan = plan_corpus_scale(close_world, Simulator(program, seed=8128), profile=PROFILE, reconcile="auto")
    with pytest.raises(SynthesisError, match=r"canonical_total_mismatch: store_sales\.revenue"):
        export_corpus_scale(close_world, plan, tmp_path / "perturbed")
    assert not (tmp_path / "perturbed").exists()
    # The same program without auto keeps today's contract: nothing is asserted.
    declared = plan_corpus_scale(close_world, Simulator(program, seed=8128), profile=PROFILE)
    assert declared.reconciliations == ()


def test_stock_binds_only_to_a_snapshot_and_only_when_the_fact_exists(close_world: World) -> None:
    fact = CanonicalFact(id="FACT-HC", kind="org.headcount", subject=close_world.company.id, period="2026-03",
        value=Quantity(amount=12, unit="employees"), valid_from=datetime(2026, 3, 31, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD)
    world = replace(close_world, _facts=(*close_world._facts, fact))
    snapshot = derive_reconciliations(world, _close_program(1, 1))
    assert FactReconciliation(table="roster", column="headcount", fact_id="FACT-HC", decimals=0) in snapshot.bound
    temporal = derive_reconciliations(world, _close_program(1, 1, headcount_temporal=True))
    [refused] = [item for item in temporal.unbound if item.fact_kind == "org.headcount"]
    assert "once per tick" in refused.reason
    # A second period makes the fact ambiguous until the caller names one.
    later = fact.model_copy(update={"id": "FACT-HC2", "period": "2026-04"})
    two = replace(world, _facts=(*world._facts, later))
    [ambiguous] = [item for item in derive_reconciliations(two, _close_program(1, 1)).unbound
                   if item.fact_kind == "org.headcount"]
    assert "name one period" in ambiguous.reason
    named = derive_reconciliations(two, _close_program(1, 1), period="2026-04")
    assert FactReconciliation(table="roster", column="headcount", fact_id="FACT-HC2", decimals=0) in named.bound


def test_shipped_mechanisms_bind_nothing_and_say_why(close_world: World) -> None:
    # retail's revenue and margin are minor-currency flows of a 30-day
    # simulation: an independent process, never silently the monthly close.
    derived = derive_reconciliations(close_world, retail(stores=2, products=3, ticks=4))
    assert derived.bound == ()
    reasons = {(item.table, item.column): item.reason for item in derived.unbound}
    assert reasons[("inventory", "revenue")] == "column unit 'minor_currency' is not AUD_thousands*10^-<decimals>"
    assert reasons[("inventory", "margin")] == "column unit 'minor_currency' is not AUD_thousands*10^-<decimals>"
    assert reasons[(None, None)] == "no operational column named employees or headcount"


def test_declared_binding_wins_and_period_requires_auto(close_world: World) -> None:
    revenue = _company_fact(close_world, "financial.revenue.actual")
    assert revenue.value is not None
    program = _close_program(int(revenue.value.amount) // 4, 1)
    declared = FactReconciliation(table="store_sales", column="revenue", fact_id=revenue.id, decimals=0)
    derived = derive_reconciliations(close_world, program, declared=(declared,))
    assert all(binding.column != "revenue" for binding in derived.bound)
    assert any(item.reason == "declared explicitly" for item in derived.unbound)
    with pytest.raises(SynthesisError, match="reconcile_period belongs"):
        plan_corpus_scale(close_world, Simulator(program, seed=8128), profile=PROFILE, reconcile_period="2026-03")


def test_cli_reports_and_builds_with_auto_reconciliation(close_world: World, tmp_path: Path) -> None:
    revenue = _company_fact(close_world, "financial.revenue.actual")
    gross = _company_fact(close_world, "financial.gross_profit.actual")
    assert revenue.value is not None and gross.value is not None
    program = tmp_path / "program.json"
    profile = tmp_path / "profile.json"
    write_json(program, _close_program(int(revenue.value.amount) // 4, int(gross.value.amount)).model_dump(mode="json"))
    write_json(profile, {"name": "cli-reconcile", "minimum_relational_rows": 0, "native_targets": []})
    shown = runner.invoke(app, ["corpus-scale", "reconcile", "retail-close", "--program", str(program)])
    assert shown.exit_code == 0, shown.output
    report = json.loads(shown.output)
    assert [binding["column"] for binding in report["bound"]] == ["revenue", "gross_profit"]
    built = runner.invoke(app, ["corpus-scale", "build", "retail-close", "--program", str(program),
                                "--profile", str(profile), "--reconcile", "auto", "--out", str(tmp_path / "scaled")])
    assert built.exit_code == 0, built.output
    assert len(json.loads(built.output)["reconciliations"]) == 2
