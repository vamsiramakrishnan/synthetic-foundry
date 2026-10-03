"""`worldloom guide` may only name commands and flags that exist.

The guide is the first thing a new user runs, which makes it the most
expensive place for a stale command: a renamed flag in it is a refusal on the
reader's first try, from the page that promised to stop that happening. So
every command the guide prints is parsed here by the real Typer app. Click's
own parser (`make_context`, which validates without invoking) checks the
command path, every option, the argument count and the required options; an
explicit pass over the flags names the one that is wrong.

The harness-docs gate (`tests/test_harness_docs.py`) does the same for fenced
examples in prose. This file exists because the guide's commands are data in
`worldloom.guide`, not prose in a fenced block, and nothing else reads them.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from worldloom import guide
from worldloom.cli import _REFUSALS, app

ROOT = Path(__file__).resolve().parent.parent

runner = CliRunner()

#: Shell syntax a guide command may use after its arguments; the parse stops
#: there. `pack spec --template > company.json` is the one in use.
_SHELL_OPERATORS = {">", ">>", "|", "&&", ";"}

#: A file shipped in a checkout, named in a command or a reason. Outputs and
#: placeholders are spelled `./x` by the guide's convention and never match.
_SHIPPED = re.compile(r"(?<![\w./-])((?:docs|examples|src|\.claude)/[\w./-]+[\w-])")


def _every_step() -> list[tuple[str, guide.Step]]:
    found = []
    for goal in guide.GOALS:
        steps = [*goal.setup, *goal.steps, *(step for route in goal.alternatives for step in route.steps)]
        found += [(goal.id, step) for step in steps]
    return found


STEPS = _every_step()
STEP_IDS = [f"{goal_id}:{step.command[:60]}" for goal_id, step in STEPS]


def _tokens(command: str) -> list[str]:
    tokens = shlex.split(command)
    for index, token in enumerate(tokens):
        if token in _SHELL_OPERATORS:
            return tokens[:index]
    return tokens


def _resolve(tokens: list[str]) -> tuple[Any, list[str], list[str]]:
    """The command the leading words name, its path, and the arguments left."""
    command: Any = typer.main.get_command(app)
    path: list[str] = []
    rest = list(tokens)
    while hasattr(command, "commands") and rest and rest[0] in command.commands:
        path.append(rest[0])
        command = command.commands[rest.pop(0)]
    return command, path, rest


def _options(command: Any) -> set[str]:
    return {
        spelling
        for param in command.params
        if param.param_type_name == "option"
        for spelling in (*param.opts, *param.secondary_opts)
    }


@pytest.mark.parametrize(("goal_id", "step"), STEPS, ids=STEP_IDS)
def test_every_guide_command_parses_against_the_cli(goal_id: str, step: guide.Step) -> None:
    tokens = _tokens(step.command)
    if tokens[0] == "python":
        # The SDK goal's one line of Python: it must at least compile. It
        # runs, too, in `test_the_python_step_runs`.
        assert tokens[1] == "-c" and len(tokens) == 3, step.command
        compile(tokens[2], f"<guide {goal_id}>", "exec")
        return

    assert tokens[0] == "worldloom", f"{goal_id}: a step that is neither worldloom nor python: {step.command}"
    command, path, rest = _resolve(tokens[1:])
    assert path, f"{goal_id}: `{step.command}` names no command"
    assert not hasattr(command, "commands"), (
        f"{goal_id}: `{step.command}` stops at the group `worldloom {' '.join(path)}`, not a command"
    )

    known = _options(command)
    unknown = [flag.split("=", 1)[0] for flag in rest
               if flag.startswith("-") and flag.split("=", 1)[0] not in known]
    assert not unknown, f"{goal_id}: `worldloom {' '.join(path)}` does not accept {unknown}"

    # Arity, value types and required options, by the parser the CLI uses.
    try:
        command.make_context(" ".join(["worldloom", *path]), rest)
    except Exception as error:  # click's UsageError family, whatever typer vendors
        pytest.fail(f"{goal_id}: `{step.command}` does not parse: {error}")


@pytest.mark.parametrize(("goal_id", "step"), STEPS, ids=STEP_IDS)
def test_flags_named_in_a_reason_belong_to_its_command(goal_id: str, step: guide.Step) -> None:
    """`--harness codex works the same way` must be true of the command beside it."""
    tokens = _tokens(step.command)
    if tokens[0] != "worldloom":
        return
    command, path, _ = _resolve(tokens[1:])
    mentioned = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", step.why))
    assert mentioned <= _options(command), (
        f"{goal_id}: the reason for `worldloom {' '.join(path)}` names {sorted(mentioned - _options(command))}"
    )


def test_shipped_paths_exist() -> None:
    """A path without `./` is a file in a checkout, and has to be there."""
    texts = [goal.read_next for goal in guide.GOALS]
    texts += [text for _, step in STEPS for text in (step.command, step.why)]
    texts += [route.when for goal in guide.GOALS for route in goal.alternatives]
    missing = sorted({path for text in texts for path in _SHIPPED.findall(text) if not (ROOT / path).exists()})
    assert not missing, f"the guide names files a checkout does not have: {missing}"
    for goal in guide.GOALS:
        assert (ROOT / goal.read_next).is_file(), f"{goal.id}: read_next {goal.read_next} does not exist"


def test_first_command_is_the_first_step() -> None:
    for goal in guide.GOALS:
        assert goal.steps, f"{goal.id} has no steps"
        first = goal.steps[0].command
        assert goal.first_command in first, f"{goal.id}: {goal.first_command!r} is not in {first!r}"
        if goal.first_command.startswith("worldloom "):
            _, path, _ = _resolve(_tokens(first)[1:])
            assert goal.first_command == " ".join(["worldloom", *path]), (
                f"{goal.id}: first_command {goal.first_command!r} is not the command its first step runs"
            )


def test_goal_ids_are_unique_words() -> None:
    ids = [goal.id for goal in guide.GOALS]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z]+", goal_id) for goal_id in ids), ids


def test_evaluation_commands_are_real_and_point_at_goals() -> None:
    root = typer.main.get_command(app)
    ids = {goal.id for goal in guide.GOALS}
    for item in guide.EVALUATION_COMMANDS:
        assert item.command in root.commands, f"`worldloom {item.command}` is not a command"
        assert set(item.goals) <= ids, f"{item.command} names unknown goals {set(item.goals) - ids}"


def test_the_python_step_runs() -> None:
    """The SDK line is executed, not just compiled: an API rename breaks it."""
    (code,) = [_tokens(step.command)[2] for goal_id, step in STEPS if goal_id == "python"
               and step.command.startswith("python ")]
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(code, "<guide python>", "exec"), {})
    assert printed.getvalue().startswith("True "), printed.getvalue()


def test_the_native_fact_is_the_company_revenue(tmp_path: Path) -> None:
    """The one seed-specific literal in the guide still names what it says.

    `corpus-scale build --fact` needs a canonical fact id, and the native
    sequence names seed 8128's company revenue. A generation change that
    renumbers facts would leave the guide pointing at some other fact.
    """
    native = guide.goal("native")
    assert native is not None
    build, scale = native.setup
    fact_id = _tokens(scale.command)[_tokens(scale.command).index("--fact") + 1]
    out = tmp_path / "corpus"
    argv = [str(out) if token == "./corpus" else token for token in _tokens(build.command)[1:]]
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output

    from worldloom import World

    world = World.load(str(out))
    fact = next(fact for fact in world.facts if fact.id == fact_id)
    assert fact.kind == "financial.revenue.actual", fact
    assert fact.subject == world.company.id, fact


def test_overview_lists_every_goal_on_one_line() -> None:
    result = runner.invoke(app, ["guide"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    for goal in guide.GOALS:
        row = [line for line in lines if line.split()[:1] == [goal.id]]
        assert len(row) == 1, f"{goal.id}: {row}"
        assert goal.summary in row[0] and row[0].rstrip().endswith(goal.first_command), row[0]
    for item in guide.EVALUATION_COMMANDS:
        assert f"worldloom {item.command} " in result.output


@pytest.mark.parametrize("goal", guide.GOALS, ids=[goal.id for goal in guide.GOALS])
def test_a_goal_prints_every_command_on_its_own_line(goal: guide.Goal) -> None:
    result = runner.invoke(app, ["guide", goal.id.upper()])
    assert result.exit_code == 0, result.output
    lines = {line.strip() for line in result.output.splitlines()}
    expected = [*goal.setup, *goal.steps, *(step for route in goal.alternatives for step in route.steps)]
    for step in expected:
        assert step.command in lines, f"{goal.id}: `{step.command}` is not printed on a line of its own"
    assert f"Read next: {goal.read_next}" in lines


def test_json_is_the_manifest() -> None:
    result = runner.invoke(app, ["guide", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == json.loads(json.dumps(guide.manifest()))
    assert payload["schema"] == guide.GUIDE_SCHEMA
    assert [item["id"] for item in payload["goals"]] == [goal.id for goal in guide.GOALS]

    one = json.loads(runner.invoke(app, ["guide", "agent", "--json"]).output)
    assert one["schema"] == guide.GUIDE_SCHEMA
    assert one["id"] == "agent" and one["first_command"] == "worldloom enterprise-evals build"
    assert one["steps"][0]["command"].startswith("worldloom enterprise-evals build ")


def test_an_unknown_goal_is_refused_with_the_way_back(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "unknown_goal" in _REFUSALS
    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    prose = runner.invoke(app, ["guide", "retrieval"])
    assert prose.exit_code == 2, prose.output
    assert "unknown goal 'retrieval'" in " ".join(prose.stderr.split())

    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    data = runner.invoke(app, ["guide", "retrieval"])
    assert data.exit_code == 2
    envelope = json.loads(data.stderr)
    assert envelope["refusal"] == "unknown_goal"
    assert "worldloom guide" in envelope["fix"]
    assert envelope["data"] == {"goal": "retrieval", "goals": [goal.id for goal in guide.GOALS]}


def test_status_without_a_corpus_is_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The guide adds a front door; it does not reroute the no-corpus refusal."""
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    missing = str(tmp_path / "missing")
    result = runner.invoke(app, ["status", missing])
    assert result.exit_code == 2
    envelope = json.loads(result.stderr)
    assert envelope["refusal"] == "corpus_unloadable"
    assert envelope["data"] == {"corpus": missing}
    assert "guide" not in result.stderr


def test_guide_is_the_first_command_in_help() -> None:
    """Registration order is help order; the front door is listed first."""
    root = typer.main.get_command(app)
    assert next(iter(root.list_commands(typer.Context(root)))) == "guide"
