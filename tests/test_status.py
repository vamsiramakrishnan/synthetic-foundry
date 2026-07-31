"""`worldloom status`: the loop's state machine, made visible.

The pipeline's sequence lives in the skill files, and a sequence an agent has to
memorise is one it will eventually resume in the wrong place. These tests hold
the command to its contract: every stage of the loop names itself and the exact
command that comes next, `--json` is loadable data, and asking never mutates.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from worldloom.cli import app

runner = CliRunner()


def build(tmp_path, *extra: str) -> str:
    corpus = str(tmp_path / "corpus")
    result = runner.invoke(
        app, ["build", "--seed", "8128", "--incident", "--out", corpus, *extra]
    )
    assert result.exit_code == 0, result.output
    return corpus


def status_of(corpus: str) -> dict:
    result = runner.invoke(app, ["status", corpus, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_an_actor_corpus_points_at_the_next_decision(tmp_path) -> None:
    corpus = build(tmp_path, "--actors", "agent")
    state = status_of(corpus)
    assert state["actor_episode_pending"] is True
    assert state["next"].startswith(f"worldloom act requests {corpus}")


def test_a_planned_corpus_points_at_prose(tmp_path) -> None:
    corpus = build(tmp_path)
    state = status_of(corpus)
    assert state["sections_awaiting_prose"] > 0
    assert state["next"].startswith(f"worldloom narrate requests {corpus}")


def test_the_golden_episode_reads_complete() -> None:
    state = status_of("retail-close")
    assert state["stage"] == "complete and coherent"
    assert state["next"].startswith("worldloom evaluate")
    assert state["validation"]["ok"] is True


def test_status_never_writes(tmp_path) -> None:
    """A read command that mutates what it reports on cannot be trusted mid-loop.

    Compilation happens in memory; the corpus directory must be byte-identical
    before and after asking.
    """
    corpus = build(tmp_path)
    before = {
        p.name: p.read_bytes()
        for p in sorted((tmp_path / "corpus").rglob("*"))
        if p.is_file()
    }
    status_of(corpus)
    after = {
        p.name: p.read_bytes()
        for p in sorted((tmp_path / "corpus").rglob("*"))
        if p.is_file()
    }
    assert before == after


def test_validate_json_is_data(tmp_path) -> None:
    corpus = build(tmp_path)
    result = runner.invoke(app, ["validate", corpus, "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["ok"] is True
    assert report["checks"] > 0
    assert report["violations"] == []
