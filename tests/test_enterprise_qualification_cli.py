"""The CLI exports inspectable evidence and preserves failures as outcomes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_eval_runtime import run_eval_row
from worldloom.enterprise_io import load_exported_corpus
from worldloom.enterprise_rows import runtime_records

runner = CliRunner()


def _profile(path: Path, *, entity: str = "incident") -> Path:
    document = {
        "name": "cli-qualification", "industry": "retail",
        "company_description": "Retail incident response.",
        "connectors": ["servicenow", "sharepoint"], "workflows": ["incident_pack"],
        "additional_workflows": [{
            "name": "incident_pack", "purpose": "incident pack", "process": "service_management",
            "sources": [{"connector": "servicenow", "entities": [entity]}],
            "destinations": [{"connector": "sharepoint", "entities": ["file"],
                              "operations": ["create"], "formats": ["docx"]}],
            "content_actions": ["extract"], "audiences": ["analyst", "manager"],
            "topologies": ["chain"], "verification": ["readback"],
            "prompt_template": "Prepare {purpose} for {audience}. Use {sources}. {failure_instruction}",
        }],
        "coverage": {"connector_counts": [1], "failures": ["none", "permission_denied"]},
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_cli_exports_exact_executable_selection_and_cap_holes(tmp_path: Path) -> None:
    profile = _profile(tmp_path / "profile.json")
    output = tmp_path / "qualified"
    result = runner.invoke(app, ["enterprise-evals", "qualify", "examples/retail-close",
                                "--profile", str(profile), "--pool-size", "4", "--limit", "1",
                                "--out", str(output), "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report == json.loads((output / "qualification.json").read_text())
    assert report["pool_count"] == report["eligible_count"] == 4
    assert report["selected_count"] == 1
    assert report["selected_coverage"]["holes"]
    loaded = load_exported_corpus(output)
    row = json.loads((output / "qualified-rows.jsonl").read_text())
    proof = json.loads((output / "proofs.jsonl").read_text())
    assert row["id"] == loaded.queries[0].id == proof["query_id"]
    assert run_eval_row(row, runtime_records(loaded.connector_data.records)).grade == proof["grade"]


def test_no_eligible_candidates_writes_report_and_named_refusal(tmp_path: Path) -> None:
    profile = _profile(tmp_path / "profile.json", entity="change_request")
    output = tmp_path / "empty"
    result = runner.invoke(app, ["enterprise-evals", "qualify", "examples/retail-close",
                                "--profile", str(profile), "--pool-size", "4", "--out", str(output)],
                           env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 3, result.output
    refusal = json.loads(result.output)
    assert refusal["refusal"] == "no_qualified_evals"
    report = json.loads((output / "qualification.json").read_text())
    assert report["pool_count"] == 4
    assert report["selected_count"] == report["eligible_count"] == 0
    assert len({item["query_id"] for item in report["refusals"]}) == 4
    assert refusal["data"]["report"] == report
    assert load_exported_corpus(output).queries == ()


@pytest.mark.parametrize(("flag", "value", "code"), (
    ("--dag-shape", "unknown-shape", "enterprise_qualification_failed"),
    ("--profile", "missing-profile.json", "unreadable_document"),
))
def test_configuration_refusals_do_not_create_exports(tmp_path: Path, flag: str, value: str, code: str) -> None:
    output = tmp_path / "refused"
    result = runner.invoke(app, ["enterprise-evals", "qualify", "examples/retail-close",
                                flag, value, "--out", str(output)], env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["refusal"] == code
    assert not output.exists()
