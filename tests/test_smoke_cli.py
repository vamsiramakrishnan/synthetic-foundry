"""`worldloom smoke` drives every stage on a tiny world and names the one that fails.

What these tests pin: the full run passes on the development install, prints
one line per stage in pipeline order, leaves each stage's output where the
next one read it, and finishes well inside the minute it promises; a failing
stage stops the run, exits 1, and is named in the `smoke_failed` envelope with
the tail of what it printed; and a non-empty destination is refused before
anything runs, because a leftover corpus would make `build` refuse and read
as the pipeline being broken.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app

runner = CliRunner()

STAGES = ("build", "narrate", "render", "validate", "evaluate", "enterprise-evals", "evalrun")


def test_the_whole_pipeline_passes_stage_by_stage(tmp_path: Path) -> None:
    out = tmp_path / "smoke"
    started = time.perf_counter()
    result = runner.invoke(app, ["smoke", "--out", str(out)])
    elapsed = time.perf_counter() - started
    assert result.exit_code == 0, result.output

    reported = [line.split()[1] for line in result.output.splitlines() if line.startswith("✓ ")]
    assert tuple(reported[: len(STAGES)]) == STAGES, result.output
    assert "smoke passed: 7 stages" in result.output

    # Each stage's product is on disk where the next stage read it.
    assert (out / "corpus" / "generation-ledger.jsonl").read_text(encoding="utf-8").strip()
    assert any((out / "corpus").rglob("*.xlsx")), "render wrote no workbook"
    assert (out / "cases" / "proof.json").exists()
    summary = json.loads((out / "runs" / "reference" / "summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] == summary["cases"] > 0

    # The promise is "well under a minute" on CI hardware; a local run that
    # needs more than this has regressed by multiples, not by noise.
    assert elapsed < 60, f"smoke took {elapsed:.1f}s"


def test_a_failing_stage_is_named_and_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    out = tmp_path / "smoke"
    result = runner.invoke(app, ["smoke", "--out", str(out), "-f", "no-such-format"])
    assert result.exit_code == 1, result.output
    envelope = json.loads(next(
        line for line in result.output.splitlines() if line.startswith('{"refusal"')
    ))
    assert envelope["refusal"] == "smoke_failed"
    assert envelope["data"]["stage"] == "render", envelope
    assert "no-such-format" in envelope["data"]["output"]
    # Nothing after the failing stage ran.
    assert not (out / "cases").exists()


def test_a_non_empty_destination_is_refused_before_anything_runs(tmp_path: Path) -> None:
    out = tmp_path / "smoke"
    out.mkdir()
    (out / "leftover.txt").write_text("from an earlier run\n", encoding="utf-8")
    result = runner.invoke(app, ["smoke", "--out", str(out)])
    assert result.exit_code == 1, result.output
    assert "setup" in result.output and "not empty" in result.output
    assert not (out / "corpus").exists()
