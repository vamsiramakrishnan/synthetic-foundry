"""`worldloom doctor` judges the installation and names the fix.

What these tests pin: every check green in the development environment (which
installs every extra), a missing renderer dependency reported as ✗ *with the
pip extra named* rather than a bare ImportError, a stale command reference
reported with the command that regenerates it, and the exit code carrying the
verdict both ways — 0 all-green, 1 otherwise, with the `doctor_unhealthy`
envelope in JSON mode so a harness need not parse the table.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import docs as docs_generator
from worldloom.cli import app

runner = CliRunner()


def _flat(text: str) -> str:
    # Rich wraps to a width nothing in the test controls; see test_flag_reach.
    return " ".join(text.split())


@pytest.fixture()
def outside_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Run doctor from a directory that is not a repository checkout.

    The reference check reads `docs.REFERENCE_PATH` relative to the working
    directory — the same way `docs --check` does — so running these tests from
    the repository root would couple doctor's verdict to whether the
    checked-in reference has been regenerated for the exact CLI surface under
    test. Doctor's health claim is about the *install*; pointing it at a
    non-checkout directory makes that claim the thing measured.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_green_in_the_dev_environment(outside_checkout: Path) -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    flat = _flat(result.stdout)
    assert "✗" not in flat
    assert "✓ python" in flat
    # One dependency-bearing format and one dependency-free format, so both
    # arms of the probe discovery are exercised on the green path.
    assert "✓ render:xlsx" in flat
    assert "✓ render:markdown" in flat
    assert "✓ corpus:retail-close" in flat
    assert "✓ docs:reference" in flat


def test_json_emits_the_check_list(outside_checkout: Path) -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    names = {entry["check"] for entry in payload["checks"]}
    assert {"python", "render:xlsx", "render:markdown",
            "corpus:retail-close", "docs:reference"} <= names
    assert all(entry["ok"] for entry in payload["checks"])
    # A fix beside a passing check would claim something needs fixing.
    assert all(entry["fix"] is None for entry in payload["checks"])


def test_a_missing_renderer_dependency_names_the_extra(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A minimal install's missing extra is a ✗ with the exact pip command.

    ``import openpyxl`` consults ``sys.modules`` first, and ``None`` there
    makes the import raise ImportError even though the package is installed —
    the cheapest honest simulation of an install without the extra, and the
    same seam the renderer's own ``_require_openpyxl`` probe fails through at
    render time.
    """
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    flat = _flat(result.stdout)
    assert "✗ render:xlsx" in flat
    assert "worldloom[xlsx]" in flat
    # Only the format whose dependency is gone fails; the others stay green,
    # or the fix string would be pointing at the wrong extra.
    assert "✓ render:docx" in flat
    assert "✓ render:markdown" in flat


def test_unhealthy_envelope_lists_the_failed_checks(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    envelope = json.loads(result.stderr)
    assert envelope["refusal"] == "doctor_unhealthy"
    assert envelope["data"]["failed"] == ["render:xlsx"]


def test_unhealthy_prose_says_what_failed(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    # No total asserted: the format count grows with the registry, and this
    # test is about the failure being named, not about how many checks exist.
    assert "check(s) failed: render:xlsx" in _flat(result.stderr)


def test_a_stale_reference_is_named_with_its_fix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A checkout whose generated reference lags the CLI is unhealthy.

    Staged in a scratch directory rather than the real checkout, for the same
    reason `outside_checkout` exists: the test must own the staleness it
    asserts on, not inherit whatever state the working tree happens to be in.
    """
    target = tmp_path / Path(docs_generator.REFERENCE_PATH)
    target.parent.mkdir(parents=True)
    target.write_text("not the reference\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    flat = _flat(result.stdout)
    assert "✗ docs:reference" in flat
    assert "is stale" in flat
    assert "worldloom docs" in flat
