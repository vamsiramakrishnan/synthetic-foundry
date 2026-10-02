"""Exercise the cohesive CLI from public package construction to target resume."""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest
from test_native_evals_cli import exchange  # noqa: F401
from typer.testing import CliRunner

from worldloom.cli import app

runner = CliRunner()


@pytest.fixture
def package(exchange: Path) -> Path:  # noqa: F811
    root = exchange.parent
    destination = root / "benchmark"
    result = runner.invoke(app, ["native-evals", "build", str(root / "source"), str(root / "scale"),
        "--plan", str(root / "workload.json"), "--out", str(destination), "--layout", "split"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["target_directory"] == str(destination / "public")
    assert (destination / "private/oracle.json").is_file()
    assert not (destination / "public/oracle.json").exists()
    return destination


def test_package_inspection_reports_solvability_separately_from_promotion(package: Path) -> None:
    result = runner.invoke(app, ["native-evals", "inspect", str(package), "--source-origin", "northstar"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["execution_ready"]
    assert report["reference_qualified"] == report["tasks"]
    assert report["independent_units"] == 1
    assert not report["promotion_ready"]
    assert report["findings"]
    qualified = runner.invoke(app, ["native-evals", "qualify", str(package)])
    assert qualified.exit_code == 0, qualified.output
    assert json.loads(qualified.output)["passed"]


def test_run_reports_target_failure_and_resumes_without_reinvoking(package: Path, tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text('''import json, pathlib, sys
request = json.load(sys.stdin)
root = pathlib.Path(request["input_root"])
assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) == sorted(i["path"] for i in request["task"]["inputs"])
assert "oracle" not in json.dumps(request)
with (pathlib.Path(sys.argv[1]) / "calls.txt").open("a") as stream:
    stream.write(request["task"]["id"] + "\\n")
print(json.dumps({"schema": "worldloom.native-harness-response/v1", "task_id": request["task"]["id"], "execution_id": request["task"]["execution_id"], "submission": {"answers": [], "files": []}}))
''', encoding="utf-8")
    argv = ["native-evals", "run", str(package), "--command", shlex.join([sys.executable, str(target), str(tmp_path)]),
        "--out", str(tmp_path / "run")]
    result = runner.invoke(app, argv)
    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert not report["passed"]
    before = (tmp_path / "calls.txt").read_text()
    assert len(before.splitlines()) == len(json.loads((package / "public/public-tasks.json").read_text())["tasks"])
    resumed = runner.invoke(app, [*argv, "--resume"])
    assert resumed.exit_code == 1, resumed.output
    assert json.loads(resumed.output) == report
    assert (tmp_path / "calls.txt").read_text() == before
    target.write_text(target.read_text() + "\n# changed implementation\n")
    changed = runner.invoke(app, [*argv, "--resume"])
    assert changed.exit_code != 0
    assert (tmp_path / "calls.txt").read_text() == before


def test_protocol_is_machine_readable_and_does_not_require_a_corpus() -> None:
    result = runner.invoke(app, ["native-evals", "protocol"])
    assert result.exit_code == 0, result.output
    contract = json.loads(result.output)
    assert contract["request_schema"] == "worldloom.native-harness-request/v1"
    assert contract["response_schema"] == "worldloom.native-harness-response/v1"
    assert "submission" in contract["response"]


def test_partition_builds_disjoint_packages_and_exactly_resumes(exchange: Path) -> None:  # noqa: F811
    root = exchange.parent
    argv = ["native-evals", "partition", str(root / "source"), "--plan", str(root / "workload.json"),
        "--train-families", "1", "--holdout-families", "1", "--out", str(root / "partitioned")]
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["split_audit"]["isolated"]
    assert report["split_audit"]["training_units"] == report["split_audit"]["heldout_units"] == 1
    for split in ("training", "heldout"):
        qualified = runner.invoke(app, ["native-evals", "qualify", str(root / "partitioned" / split)])
        assert qualified.exit_code == 0, qualified.output
        assert json.loads(qualified.output)["passed"]
    resumed = runner.invoke(app, [*argv, "--resume"])
    assert resumed.exit_code == 0, resumed.output
    assert json.loads(resumed.output) == report
