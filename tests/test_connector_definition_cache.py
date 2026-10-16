"""The cached shipped connector definitions are shared, so nothing may mutate them.

`_shipped_definition` parses each shipped connector once per process and hands
every caller the same frozen model. `frozen=True` stops attribute assignment,
not in-place edits of its dict fields (`entities`, `tools`, ...), and a deep copy
per call costs twice the parse it replaced. So the guard is this test: drive the
code that reads definitions (planning, case building, the emulated services a
reference run calls) in this process and require every cached definition to be
byte-identical afterwards.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_definition import REFERENCE_CONNECTORS, _shipped_definition

runner = CliRunner()


def _snapshot() -> dict[str, str]:
    return {name: _shipped_definition(name).model_dump_json() for name in REFERENCE_CONNECTORS}


def test_planning_building_and_running_cases_leave_shared_definitions_untouched(tmp_path: Path) -> None:
    before = _snapshot()
    corpus, cases, runs = tmp_path / "corpus", tmp_path / "cases", tmp_path / "runs"
    for args in (
        ["build", "--seed", "8128", "--out", str(corpus)],
        ["enterprise-evals", "plan", "examples/hospital", str(tmp_path / "plan.jsonl"), "--limit", "10"],
        ["enterprise-evals", "build", str(corpus), str(cases), "--exhaustive", "--limit", "6"],
        ["evalrun", "run", str(cases), "-o", str(runs)],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
    assert _snapshot() == before
