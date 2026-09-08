"""Real operational evidence survives export, compilation and both execution paths."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import BankingWorld, RetailWorld
from worldloom.cli import app
from worldloom.connector_eval_runtime import run_eval_row
from worldloom.enterprise_corpus import score_trace, validate_corpus
from worldloom.enterprise_io import export_corpus, load_exported_corpus
from worldloom.enterprise_rows import compile_rows, runtime_records
from worldloom.enterprise_runner import RunnerConfig, execute_query
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.enterprise_simulator import ConnectorSimulator
from worldloom.enterprise_specs import DestinationRole, Operation
from worldloom.synthesis import (
    IncidentRule,
    Simulator,
    banking,
    retail,
    with_parameters,
)
from worldloom.synthesis.connectors import operational_profile


@pytest.mark.parametrize("vertical", ("retail", "banking"))
@pytest.mark.parametrize("dag_shape", (None, "map_read", "conditional", "write_chain"))
def test_operational_evidence_produces_verified_outcomes(vertical: str, dag_shape: str | None, tmp_path: Path) -> None:
    if vertical == "retail":
        world = RetailWorld(seed=8128).build()
        program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
        rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    else:
        world = BankingWorld(seed=8128).build()
        program = banking(borrowers=8, ticks=8)
        rule = IncidentRule(table="loan", signal="arrears", title="Payment arrears")
    scenario = operational_profile(vertical)
    scenario = scenario.model_copy(update={"coverage": scenario.coverage.model_copy(update={"failures": ("none",)})})
    if dag_shape == "write_chain":
        # Email drafts deliberately have no update operation. Author a destination
        # that admits the requested write/read/update/read trajectory.
        workflow = scenario.additional_workflows[0].model_copy(update={
            "destinations": (DestinationRole(connector="confluence", entities=("page",),
                                             operations=(Operation.CREATE,), formats=("html",)),),
        })
        scenario = scenario.model_copy(update={
            "additional_workflows": (workflow,),
            "connectors": (*scenario.connectors, "confluence"),
        })
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(scenario)
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(24)
    )
    if dag_shape is not None:
        harness = harness.with_dag_grammar(dag_shape)
    corpus, _ = harness.build()
    assert len(corpus.queries) == 24
    assert validate_corpus(corpus) == ()
    assert all(fixture.expected_evidence_ids for fixture in corpus.fixtures)
    assert all(not fixture.expected_fact_ids for fixture in corpus.fixtures)
    export_corpus(corpus, tmp_path)
    loaded = load_exported_corpus(tmp_path)
    assert loaded == corpus
    records = runtime_records(loaded.connector_data.records)
    report = compile_rows(loaded.queries, loaded.fixtures, records)
    assert report.refusals == (), report.reasons()
    for row in report.rows:
        result = run_eval_row(row, records)
        assert result.grade["status"] in {"ok", "behavior"}, (row["id"], result.grade)
        assert result.grade["fails"] == []
        assert all(span.error is None for span in result.spans)
    if dag_shape is not None:
        response = CliRunner().invoke(app, ["enterprise-evals", "simulate", str(tmp_path)])
        assert response.exit_code == 0, response.output
        summary = json.loads(response.output)
        assert summary["completed"] == 24, summary
        assert summary["raised"] == summary["assertion_failed"] == 0, summary
        assert summary["assertion_passed"] == 24
        assert summary["average_dag_score"] is None
        return
    simulator = ConnectorSimulator(loaded)
    for query, fixture in zip(loaded.queries, loaded.fixtures, strict=True):
        result = asyncio.run(execute_query(query, fixture, RunnerConfig(), simulator.invoke))
        assert result.completed, result.finding
        score = score_trace(query, result.calls, fixture=fixture)
        assert score.provenance == 1.0, score.findings
