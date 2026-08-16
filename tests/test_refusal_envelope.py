"""A refusal is data when asked for, and the exact same prose when not.

`WORLDLOOM_OUTPUT=json` turns every converted CLI refusal into one line of
JSON on stderr — ``{"refusal": code, "message": …, "fix": …, "data": …}`` —
with the same exit code the prose refusal carries. The env var is the whole
opt-in: without it, stderr must be the byte-identical Rich message every
older test pins, because harnesses that regex stderr today must keep working
until they choose to switch.

Five representative refusals are pinned here rather than all of them: one
per *shape* of site — a bad flag value, a declared-cap refusal, an
exception-translated refusal (twin), an exit-3 refusal (mutate), and a
conflict-loop refusal whose code comes from the taxonomy rule
(`unknown_facet`). The conversion is mechanical; the shapes are what can
break differently.

The registry test is the enforcement half of `_REFUSALS`'s reason to exist:
an unregistered code must raise at call time even in default mode, so a
typo'd code is caught by the first test that walks the site rather than
shipping as a new accidental wire code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import _REFUSALS, _refuse, app

runner = CliRunner()

SEED = "8128"


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One default corpus for the whole module — `twin` needs a real recipe."""
    out = tmp_path_factory.mktemp("envelope") / "corpus"
    result = runner.invoke(app, ["build", "--seed", SEED, "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


def _flat(text: str) -> str:
    # Rich wraps to a width nothing in the test controls; see test_flag_reach.
    return " ".join(text.split())


def _both(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> tuple:
    """The same invocation in default mode and JSON mode.

    Returns ``(default_result, json_result, envelope)``. Asserts the two
    modes agree on the exit code — the envelope is a different *rendering*
    of the refusal, never a different refusal.
    """
    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    default = runner.invoke(app, args)
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    as_json = runner.invoke(app, args)
    assert default.exit_code == as_json.exit_code
    envelope = json.loads(as_json.stderr)
    assert set(envelope) == {"refusal", "message", "fix", "data"}
    assert envelope["refusal"] in _REFUSALS
    return default, as_json, envelope


def test_unknown_access_level(monkeypatch: pytest.MonkeyPatch) -> None:
    default, as_json, envelope = _both(monkeypatch, ["build", "--access", "nope"])
    assert as_json.exit_code == 2
    assert envelope["refusal"] == "unknown_access_level"
    assert "unknown access level 'nope'" in envelope["message"]
    assert (
        "unknown access level 'nope'; expected one of open, standard, strict"
        in _flat(default.stderr)
    )


def test_periods_over_declared_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    args = ["build", "-a", "midsize_general_insurer", "--periods", "2"]
    default, as_json, envelope = _both(monkeypatch, args)
    assert as_json.exit_code == 2
    assert envelope["refusal"] == "period_cap"
    # The cap itself rides in `data`, so a fan-out harness can clamp and
    # retry without parsing prose.
    assert envelope["data"] == {"cap": 1, "asked": 2}
    assert "insurance builds at most 1 period(s) per corpus" in _flat(default.stderr)


def test_twin_unrecorded_path(monkeypatch: pytest.MonkeyPatch, corpus: Path) -> None:
    args = ["twin", str(corpus), "--set", "unrecorded_key=1"]
    default, as_json, envelope = _both(monkeypatch, args)
    assert as_json.exit_code == 2
    assert envelope["refusal"] == "unrecorded_path"
    assert "'unrecorded_key' is not recorded" in envelope["message"]
    assert "'unrecorded_key' is not recorded" in _flat(default.stderr)


def test_mutate_existence_path_exits_3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A bare recipe file, not a corpus: `mutate` accepts either, and the
    # existence refusal is classified before anything is built.
    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps({"seed": 1, "employees": 23}), encoding="utf-8")
    args = ["mutate", str(recipe), "--set", "employees=100",
            "--out", str(tmp_path / "out")]
    default, as_json, envelope = _both(monkeypatch, args)
    assert as_json.exit_code == 3
    assert envelope["refusal"] == "existence_path"
    assert "decides what exists" in envelope["message"]
    assert "refused: path 'employees' refused" in _flat(default.stderr)


def test_spec_with_unknown_facet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"facets": {"nope": "x"}}), encoding="utf-8")
    default, as_json, envelope = _both(monkeypatch, ["build", "--spec", str(spec)])
    assert as_json.exit_code == 2
    # The taxonomy rule is the code when the description fell to one rule —
    # `unknown_facet` is `facets.py`'s own name for this refusal, and the
    # envelope must not invent a second spelling for it.
    assert envelope["refusal"] == "unknown_facet"
    assert envelope["data"]["conflicts"][0]["rule"] == "unknown_facet"
    assert "this description cannot be built:" in _flat(default.stderr)
    assert "no such facet" in _flat(default.stderr)


def test_unregistered_code_fails_loudly() -> None:
    with pytest.raises(RuntimeError, match="unregistered refusal code 'not_a_code'"):
        _refuse("not_a_code", "[red]error:[/red] never printed")


def test_registry_meanings_are_one_line() -> None:
    # The registry is the enumerable contract: every code snake_case, every
    # meaning a single line a `--help`-style listing could print verbatim.
    for code, meaning in _REFUSALS.items():
        assert code == code.strip() and code.replace("_", "a").isalnum(), code
        assert code == code.lower(), code
        assert meaning and "\n" not in meaning, code
