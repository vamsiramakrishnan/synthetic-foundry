"""The documented harness DAG command produces executable evalrun case sets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_data import ConnectorRecord
from worldloom.corpus import write_jsonl
from worldloom.evalrun.contract import read_case_set
from worldloom.evalrun.harness_dags import HarnessDagConfig

RUNNER = CliRunner()


def inputs(root: Path) -> tuple[Path, Path]:
    sources = [ConnectorRecord(id=f"source-{index}", external_id=f"PUBLIC-{index}", connector="sharepoint",
                               entity="xlsx", title=f"Ledger {index}", fact_ids=[f"fixture-fact-{index}"],
                               fields={"business_unit": "Treasury", "period": "FY2026", "status": "approved",
                                       "amount_minor": index * 100}) for index in range(1, 4)]
    sources.append(ConnectorRecord(id="draft-source", external_id="PUBLIC-DRAFT", connector="sharepoint",
                                   entity="xlsx", title="Draft ledger", fact_ids=["fixture-draft-fact"],
                                   fields={"business_unit": "Treasury", "period": "FY2026", "status": "draft",
                                           "amount_minor": 99999}))
    records, config = root / "sources.jsonl", root / "config.json"
    write_jsonl(records, sources)
    config.write_text(HarnessDagConfig(cases=6).model_dump_json(), encoding="utf-8")
    return records, config


def build(root: Path) -> Path:
    records, config = inputs(root)
    destination = root / "cases"
    result = RUNNER.invoke(app, ["enterprise-evals", "harness-dags", str(records), "--config", str(config),
                                 "--out", str(destination)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["cases"] == 6
    return destination


def test_cli_writes_standard_cases_and_separate_public_tasks(tmp_path: Path) -> None:
    destination = build(tmp_path)
    cases, records = read_case_set(destination)
    assert len(cases) == 6 and len(records) == 7
    public = [json.loads(line) for line in (destination / "public-tasks.jsonl").read_text().splitlines()]
    assert {item["case_id"] for item in public} == {case.id for case in cases}
    text = (destination / "public-tasks.jsonl").read_text()
    assert "expected_dag" not in text and "fixture-fact-" not in text and "PUBLIC-1" not in text


def test_cli_refuses_nonempty_destination_without_modifying_it(tmp_path: Path) -> None:
    destination = build(tmp_path)
    before = {path.name: path.read_bytes() for path in destination.iterdir()}
    result = RUNNER.invoke(app, ["enterprise-evals", "harness-dags", str(tmp_path / "sources.jsonl"),
                                 "--config", str(tmp_path / "config.json"), "--out", str(destination)])
    assert result.exit_code != 0 and "absent or empty" in result.output
    assert before == {path.name: path.read_bytes() for path in destination.iterdir()}


@pytest.mark.parametrize("corrupt", ["json", "config", "records"])
def test_cli_refuses_invalid_input_before_writing(tmp_path: Path, corrupt: str) -> None:
    records, config = inputs(tmp_path)
    if corrupt == "json":
        config.write_text("{broken", encoding="utf-8")
    elif corrupt == "config":
        config.write_text('{"cases": 0}', encoding="utf-8")
    else:
        records.write_text('{"id": "incomplete-record"}\n', encoding="utf-8")
    destination = tmp_path / "refused"
    result = RUNNER.invoke(app, ["enterprise-evals", "harness-dags", str(records), "--config", str(config),
                                 "--out", str(destination)])
    assert result.exit_code != 0, result.output
    assert not destination.exists()


def test_generated_case_set_proves_and_runs_with_standard_reference_agent(tmp_path: Path) -> None:
    destination = build(tmp_path)
    proof = RUNNER.invoke(app, ["evalrun", "prove", str(destination), "--record", "--json"])
    assert proof.exit_code == 0, proof.output
    proof_document = json.loads(proof.stdout)
    assert proof_document["solvable"] == 6 and proof_document["unsolvable"] == 0
    out = tmp_path / "reference"
    result = RUNNER.invoke(app, ["evalrun", "run", str(destination), "--agent", "reference", "--out", str(out), "--json"])
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 6
    assert all(row["status"] == "graded" and row["score"]["passed"] for row in rows), rows
