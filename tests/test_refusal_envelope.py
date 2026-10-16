"""A refusal is data when asked for, and the exact same prose when not.

`WORLDLOOM_OUTPUT=json` turns every converted CLI refusal into one line of
JSON on stderr — ``{"refusal": code, "message": …, "fix": …, "data": …}`` —
with the same exit code the prose refusal carries. The env var is the whole
opt-in: without it, stderr must still begin with the byte-identical Rich
message every older test pins, because harnesses that regex stderr today must
keep working until they choose to switch. What prose gained is one line after
it, ``  fix: …``, whenever the site or `_REFUSAL_FIXES` knows the next action;
the default-fix tests below hold every registry entry to being a command the
CLI would actually parse.

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

import ast
import json
import re
import shlex
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from worldloom import cli as cli_module
from worldloom import docs
from worldloom.cli import _REFUSAL_FIXES, _REFUSALS, _refuse, app

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


# -- the fix line ----------------------------------------------------------


def test_prose_prints_the_default_fix_under_the_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `unknown_archetype` passes no fix at its site, so this is the registry's
    # fallback reaching both renderings: a dim line under the prose, and the
    # same string in the envelope's `fix`, which used to be null here.
    default, _, envelope = _both(monkeypatch, ["build", "--archetype", "nope"])
    assert envelope["refusal"] == "unknown_archetype"
    assert envelope["fix"] == _REFUSAL_FIXES["unknown_archetype"] == "worldloom archetypes"
    lines = default.stderr.rstrip("\n").splitlines()
    assert lines[-1] == "  fix: worldloom archetypes", default.stderr
    assert "unknown archetype 'nope'" in _flat(default.stderr)


def test_a_site_fix_wins_over_the_default(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit):
        _refuse("unknown_archetype", "[red]error:[/red] nope", fix="pass a shape from the list")
    assert capsys.readouterr().err.splitlines() == [
        "error: nope", "  fix: pass a shape from the list",
    ]


def test_a_fix_the_message_already_states_is_not_repeated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Older sites spelled the remedy into the message and passed it as `fix`
    # too; prose prints it once, the envelope still carries it as data.
    with pytest.raises(typer.Exit):
        _refuse("destination_exists", "[red]error:[/red] out exists; pass --overwrite to replace it",
                fix="pass --overwrite to replace it")
    assert capsys.readouterr().err.splitlines() == [
        "error: out exists; pass --overwrite to replace it",
    ]


def test_a_fix_is_escaped_not_read_as_markup(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit):
        _refuse("mcp_unavailable", "[red]error:[/red] no mcp", fix="pip install 'worldloom[mcp]'")
    assert "  fix: pip install 'worldloom[mcp]'" in capsys.readouterr().err


def test_a_code_without_a_fix_prints_the_message_alone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert "cannot_combine" not in _REFUSAL_FIXES
    with pytest.raises(typer.Exit):
        _refuse("cannot_combine", "[red]error:[/red] --a and --b")
    assert capsys.readouterr().err.splitlines() == ["error: --a and --b"]


# -- the default-fix registry ----------------------------------------------


def _parse(fix: str) -> list[str]:
    """Parse *fix* as the CLI would, returning its command path.

    Walks the typer surface by subcommand name, then hands the remainder to
    the leaf's own parser (`make_context`, which parses and checks without
    invoking), so an unknown flag, a missing required argument or a stray
    extra one fails here exactly as it would in a terminal.
    """
    tokens = shlex.split(fix)
    assert tokens and tokens[0] == "worldloom", fix
    command = typer.main.get_command(app)
    parent = command.make_context("worldloom", [], resilient_parsing=True)
    path, rest = ["worldloom"], tokens[1:]
    while rest and rest[0] in getattr(command, "commands", {}):
        path.append(rest.pop(0))
        command = command.commands[path[-1]]
    assert not getattr(command, "commands", None), f"{fix!r} stops at the group {' '.join(path)}"
    command.make_context(" ".join(path), rest, parent=parent)
    return path


def test_every_default_fix_is_a_real_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Off the checkout, so no path in an example happens to exist and parse
    # for a reason the fix itself does not supply.
    monkeypatch.chdir(tmp_path)
    surface = docs.commands()
    for code, fix in sorted(_REFUSAL_FIXES.items()):
        path = _parse(fix)
        command = " ".join(path[1:])
        assert command in surface, (code, fix)
        for token in shlex.split(fix):
            if token.startswith("-"):
                assert token.split("=", 1)[0] in surface[command], (code, fix, token)


def test_the_fix_parser_has_teeth() -> None:
    # Without these the test above could pass by parsing nothing.
    assert _parse("worldloom pack facets") == ["worldloom", "pack", "facets"]
    for bogus in ("worldloom archetypes --nope", "worldloom doctor extra",
                  "worldloom status", "worldloom no-such-command", "worldloom pack"):
        # Click's exception classes move between typer releases (vendored as
        # `typer._click` from 0.27), so the parse refusal is recognised by the
        # `ClickException` API rather than by importing a class.
        with pytest.raises(Exception) as refused:
            _parse(bogus)
        assert isinstance(refused.value, AssertionError) or hasattr(
            refused.value, "format_message"
        ), (bogus, refused.value)


def test_default_fixes_are_for_registered_codes() -> None:
    assert set(_REFUSAL_FIXES) <= set(_REFUSALS), set(_REFUSAL_FIXES) - set(_REFUSALS)


def test_every_refusal_site_names_a_registered_code() -> None:
    """Every literal code a `_refuse(...)` call passes is in the registry.

    `_refuse` raises on an unregistered code, but only when the site runs, and
    four sites (`bad_housekeeping_spec`, `unknown_surface`,
    `surface_unavailable`, `unknown_brief`) shipped that way: each turned a
    bad flag into a RuntimeError traceback. Reading the source catches a site
    no test walks. The modules that wrap `_refuse` under the same name keep
    the code as the first argument (or fix it to `pack_rejected` and pass the
    message first, which is never code-shaped), so the first argument is the
    code wherever it is a snake_case literal.
    """
    source = Path(cli_module.__file__).parent
    unregistered = []
    for path in sorted(source.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_refuse" and node.args):
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            if re.fullmatch(r"[a-z][a-z_]*", first.value) and first.value not in _REFUSALS:
                unregistered.append(f"{path.relative_to(source)}:{node.lineno} {first.value}")
    assert not unregistered, unregistered
