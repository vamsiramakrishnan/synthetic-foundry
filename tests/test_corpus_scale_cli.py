"""The public CLI must deliver physical rows and detect altered projections."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.corpus import write_json
from worldloom.synthesis import retail

runner = CliRunner()


def _inputs(root: Path) -> tuple[Path, Path]:
    program = root / "program.json"
    profile = root / "profile.json"
    write_json(program, retail(stores=2, products=3, ticks=4).model_dump(mode="json"))
    write_json(profile, {"name": "cli-smoke", "minimum_relational_rows": 29, "native_targets": []})
    return program, profile


def test_cli_build_verify_resume_and_tamper(tmp_path: Path) -> None:
    program, profile = _inputs(tmp_path)
    destination = tmp_path / "scaled"
    argv = ["corpus-scale", "build", "retail-close", "--program", str(program), "--profile", str(profile),
            "--out", str(destination), "--shard-rows", "5", "--xlsx"]
    built = runner.invoke(app, argv)
    assert built.exit_code == 0, built.output
    report = json.loads(built.output)
    assert report["relational_rows"] == 29
    assert report["foreign_key_links"] == 48
    assert any(file["kind"] == "xlsx" for file in report["files"])
    checked = runner.invoke(app, ["corpus-scale", "verify", "retail-close", str(destination)])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output) == report
    resumed = runner.invoke(app, [*argv, "--resume"])
    assert resumed.exit_code == 0, resumed.output
    assert json.loads(resumed.output) == report
    shard = next(file["path"] for file in report["files"] if file["kind"] == "csv")
    (destination / shard).write_bytes((destination / shard).read_bytes() + b"fabricated,row\n")
    refused = runner.invoke(app, ["corpus-scale", "verify", "retail-close", str(destination)])
    assert refused.exit_code != 0, refused.output
    assert "scale_checksum" in refused.output


def test_cli_assessment_reports_missing_scale_and_does_not_export(tmp_path: Path) -> None:
    program, _ = _inputs(tmp_path)
    result = runner.invoke(app, ["corpus-scale", "assess", "retail-close", "--program", str(program)])
    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert report["adequate"] is False
    assert report["relational_rows_planned"] == 29
    assert report["findings"]
    assert not (tmp_path / "scaled").exists()
