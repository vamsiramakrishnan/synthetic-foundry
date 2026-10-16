"""`worldloom doctor` judges the installation and names the fix.

What these tests pin: every check green in the development environment (which
installs every extra), a missing renderer dependency reported as ✗ *with the
pip extra named* rather than a bare ImportError, a stale command reference
reported with the command that regenerates it, and the exit code carrying the
verdict both ways — 0 all-green, 1 otherwise, with the `doctor_unhealthy`
envelope in JSON mode so a harness need not parse the table.

The agent-setup checks below (the `worldloom` on PATH being this install,
`.mcp.json`'s commands resolving, the `mcp` extra where that file launches
`worldloom mcp`) fail like the rest; the optional extras report – and the
install command, and never change the exit code.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import sysconfig
import tomllib
import types
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import docs as docs_generator
from worldloom.cli import _DOCTOR_EXTRAS, _DOCTOR_NEXT, app

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
    non-checkout directory makes that claim the thing measured. For the same
    reason this installation's scripts go first on PATH, as an activated
    environment has them: `.venv/bin/pytest` run without activation, on a
    machine where another `worldloom` is installed, would otherwise make the
    PATH check's verdict about that machine rather than this install.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([sysconfig.get_path("scripts"), os.environ.get("PATH", "")]))
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
    assert "✓ path:worldloom" in flat
    assert "✓ extra:mcp" in flat
    # The run ends on what to do next, not on the last check.
    assert result.stdout.rstrip("\n").splitlines()[-1] == f"next: {_DOCTOR_NEXT}"


def test_json_emits_the_check_list(outside_checkout: Path) -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    names = {entry["check"] for entry in payload["checks"]}
    assert {"python", "render:xlsx", "render:markdown",
            "corpus:retail-close", "docs:reference", "path:worldloom",
            "extra:mcp", "extra:embeddings", "extra:visuals"} <= names
    # Every entry, old and new, has one shape.
    assert all(set(entry) == {"check", "ok", "optional", "detail", "fix"}
               for entry in payload["checks"])
    # The dev extra installs neither `embeddings` nor `visuals`, so a green
    # run may hold optional entries that are not ok; it may hold no other.
    assert all(entry["ok"] or entry["optional"] for entry in payload["checks"])
    # A fix beside a passing check would claim something needs fixing.
    assert all(entry["fix"] is None for entry in payload["checks"] if entry["ok"])
    assert payload["next"] == _DOCTOR_NEXT


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
    # Unhealthy, the next command is doctor again once the fixes are in, and
    # the green run's `next:` line is withheld.
    assert _flat(result.stderr).endswith("fix: apply each fix above, then run `worldloom doctor` again")
    assert "next:" not in result.stdout


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


# -- the agent setup ---------------------------------------------------------
#
# Asserted through `--json` wherever a path is involved: Rich folds a long
# path mid-word at the terminal width, which `_flat` cannot undo.


def _entries(result: Any) -> dict[str, dict[str, Any]]:
    payload = json.loads(result.stdout)
    return {entry["check"]: entry for entry in payload["checks"]}


def _which_without_worldloom(monkeypatch: pytest.MonkeyPatch, found: str | None) -> None:
    """Make PATH lookup of `worldloom` return *found*; every other name is real."""
    real = shutil.which

    def which(name: str, *args: Any, **kwargs: Any) -> str | None:
        return found if name == "worldloom" else real(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", which)


def test_no_worldloom_on_path_fails_and_names_the_directory(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _which_without_worldloom(monkeypatch, None)
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1, result.output
    entry = _entries(result)["path:worldloom"]
    assert entry["ok"] is False and entry["optional"] is False
    assert entry["fix"].startswith(f"put {sysconfig.get_path('scripts')} on PATH")
    assert "check(s) failed: path:worldloom" in _flat(result.stderr)


def test_another_installation_first_on_path_is_a_failure(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hazard the check exists for: a harness would run other code.

    A script whose directory is not this environment's and whose shebang
    names another interpreter, the shape a second checkout's or a system
    install's console script has.
    """
    elsewhere = outside_checkout / "elsewhere" / "bin"
    elsewhere.mkdir(parents=True)
    script = elsewhere / "worldloom"
    script.write_text("#!/opt/another/python3\nimport sys\n", encoding="utf-8")
    _which_without_worldloom(monkeypatch, str(script))
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1, result.output
    entry = _entries(result)["path:worldloom"]
    assert entry["ok"] is False
    assert "another installation" in entry["detail"]
    assert entry["fix"] == f"put {sysconfig.get_path('scripts')} ahead of {elsewhere} on PATH"


@pytest.mark.skipif(os.name == "nt", reason="Windows console scripts are .exe launchers, not shebang scripts")
def test_a_script_elsewhere_that_runs_this_interpreter_is_this_installation(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A user-site install shares ~/.local/bin across interpreters; there the
    # shebang, not the directory, says whose script it is.
    shared = outside_checkout / "shared" / "bin"
    shared.mkdir(parents=True)
    script = shared / "worldloom"
    script.write_text(f"#!{sys.executable}\nimport sys\n", encoding="utf-8")
    _which_without_worldloom(monkeypatch, str(script))
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    assert _entries(result)["path:worldloom"]["ok"] is True


def test_every_mcp_json_server_command_must_resolve(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (outside_checkout / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "worldloom": {"command": "worldloom", "args": ["mcp"], "env": {}},
        "absent": {"command": "worldloom-test-no-such-binary", "args": []},
        # Remote: nothing to launch, so nothing to resolve.
        "remote": {"type": "http", "url": "https://example.invalid/mcp"},
    }}), encoding="utf-8")
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1, result.output
    entries = _entries(result)
    assert entries["mcp.json:worldloom"]["ok"] is True
    absent = entries["mcp.json:absent"]
    assert absent["ok"] is False and absent["optional"] is False
    assert "worldloom-test-no-such-binary" in absent["fix"]
    assert "mcp.json:remote" not in entries
    assert "check(s) failed: mcp.json:absent" in _flat(result.stderr)


def test_an_unreadable_mcp_json_is_named(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (outside_checkout / ".mcp.json").write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1, result.output
    assert _entries(result)["mcp.json"]["ok"] is False


def test_the_mcp_extra_is_required_only_where_mcp_json_launches_it(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same seam the renderer tests use: `None` in `sys.modules` makes the
    # import inside `_require_mcp` raise even though the extra is installed.
    monkeypatch.setitem(sys.modules, "mcp", None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    flat = _flat(result.stdout)
    assert "– extra:mcp" in flat
    assert "[mcp]" in flat

    (outside_checkout / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"worldloom": {"command": "worldloom", "args": ["mcp"]}}}
    ), encoding="utf-8")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1, result.output
    assert "✗ extra:mcp" in _flat(result.stdout)
    assert "check(s) failed: extra:mcp" in _flat(result.stderr)


def test_optional_extras_report_and_never_fail(
    outside_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Present by stand-in, so the ✓ arm runs whether or not the dev
    # environment installed the extra; absent by `None`, likewise.
    for name in ("model2vec", "huggingface_hub"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    # `google.genai`, not `PIL`: python-pptx imports PIL too, so hiding PIL
    # failed the pptx renderer check whenever pptx was not already imported.
    monkeypatch.setitem(sys.modules, "google.genai", None)
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    entries = _entries(result)
    embeddings, visuals = entries["extra:embeddings"], entries["extra:visuals"]
    assert embeddings["ok"] is True and embeddings["fix"] is None
    assert visuals["ok"] is False and visuals["optional"] is True
    assert visuals["fix"].startswith("pip install") and visuals["fix"].endswith("[visuals]'")

    prose = runner.invoke(app, ["doctor"])
    assert prose.exit_code == 0, prose.output
    flat = _flat(prose.stdout)
    assert "✓ extra:embeddings" in flat
    assert "– extra:visuals" in flat
    assert "install: pip install" in flat
    assert "✗" not in flat


def test_the_extras_doctor_names_are_pyproject_extras() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    for extra, modules, _ in _DOCTOR_EXTRAS:
        assert extra in declared, extra
        assert modules, extra
    assert "mcp" in declared


def test_the_next_command_is_a_real_command() -> None:
    tokens = _DOCTOR_NEXT.split()
    assert tokens[0] == "worldloom"
    assert " ".join(tokens[1:]) in docs_generator.commands()
