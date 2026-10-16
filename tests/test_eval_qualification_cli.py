"""The audit command respects actual source pins and stable world origins."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_data import ConnectorRecord
from worldloom.corpus import write_json, write_jsonl
from worldloom.evalrun import case_from_row
from worldloom.evalrun import improve as improve_module
from worldloom.evalrun import runner as execution
from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE

runner = CliRunner()


def _source(path: Path, name: str, title: str, *, query: str = "Read the revenue evidence.") -> None:
    case = case_from_row({"id": name, "query": "Read the revenue evidence.", "expected_fact_ids": ["FACT-SHARED"],
                          "expected_dag": {"nodes": [], "edges": []}, "assertions": []})
    # Requests can change without changing the executable gold row. The
    # service attaches this current request when it serves the case.
    case = case.model_copy(update={"query": query})
    record = ConnectorRecord(id="REC-1", connector="jira", entity="issue", external_id="WL-1", title=title,
                             fields={"summary": title}, fact_ids=["FACT-SHARED"])
    path.mkdir()
    write_jsonl(path / CASE_SET_FILE, [case])
    write_jsonl(path / RECORDS_FILE, [record])


def test_audit_refuses_renamed_cases_and_edited_snapshots_without_independent_origins(tmp_path: Path) -> None:
    training, heldout = tmp_path / "training", tmp_path / "heldout"
    _source(training, "original", "Initial snapshot")
    _source(heldout, "renamed", "Cosmetically edited snapshot")
    argv = ["evalrun", "audit-split", str(training), "--holdout-corpus", str(heldout)]
    unscoped = runner.invoke(app, argv)
    assert unscoped.exit_code == 1, unscoped.output
    assert json.loads(unscoped.output)["overlapping_units"] == 1
    variants = runner.invoke(app, [*argv, "--source-origin", "world-1", "--holdout-origin", "world-1"])
    assert variants.exit_code == 1 and not json.loads(variants.output)["isolated"]
    independent = runner.invoke(app, [*argv, "--source-origin", "world-1", "--holdout-origin", "world-2"])
    assert independent.exit_code == 0, independent.output
    assert json.loads(independent.output)["isolated"]


@pytest.mark.parametrize("difference", ["query", "source"])
def test_improve_routes_identical_case_rows_to_their_own_request_and_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, difference: str,
) -> None:
    training, heldout = tmp_path / "training", tmp_path / "heldout"
    train_query = "Read the revenue evidence."
    held_query = "Read the held-out revenue evidence." if difference == "query" else train_query
    _source(training, "same-case-id", "Training snapshot", query=train_query)
    _source(heldout, "same-case-id", "Held-out snapshot", query=held_query)
    policy = tmp_path / "qualification.json"
    write_json(policy, {"trials": 1, "min_units": 2, "min_repeats": 2})
    built: list[Any] = []
    seen: list[tuple[str, str, str]] = []

    def service_for(cases: Any, records: Any, **options: Any) -> Any:
        service = SimpleNamespace(cases=tuple(cases), records=tuple(records))
        built.append(service)
        return service

    def run_cases(service: Any, cases: Any, agent: Any, **options: Any) -> None:
        seen.append((cases[0].query, service.cases[0].query, service.records[0]["title"]))

    def improve(champion: Any, cases: Any, **options: Any) -> Any:
        held = options["holdout"]
        assert cases[0].id == held[0].id and cases[0].row == held[0].row
        if difference == "source":
            assert cases[0].dimensions["source_namespace"] == "world-training"
            assert held[0].dimensions["source_namespace"] == "world-heldout"
        for subset in (cases, held, cases, held):
            options["run"](subset, object())
        return SimpleNamespace(model_dump=lambda **kwargs: {"routing_checked": True})

    monkeypatch.setattr(execution, "service_for", service_for)
    monkeypatch.setattr(execution, "run_cases", run_cases)
    monkeypatch.setattr(improve_module, "improve", improve)
    argv = ["evalrun", "improve", str(training), "--holdout-corpus", str(heldout),
        "--agent-pack", "agent:baseline", "--exec", "target", "--proposer-exec", "proposer",
        "--repeats", "2", "--out", str(tmp_path / "improvement"), "--json"]
    if difference == "source":
        argv.extend(["--qualification-policy", str(policy), "--source-origin", "world-training",
                     "--holdout-origin", "world-heldout"])
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert len(built) == 2
    assert seen == [(train_query, train_query, "Training snapshot"), (held_query, held_query, "Held-out snapshot")] * 2
