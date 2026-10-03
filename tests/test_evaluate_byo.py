"""Scoring a retrieval system this package did not ship.

`worldloom evaluate` grades its own retrievers. The loop these tests cover is
the one a team with its own retrieval stack runs: export the passages the
built-in retrievers index (`evals passages`), index them, rank, and hand the
rankings back. Each test reads the exported files the way that team would,
from disk, rather than reaching into `World`: the claim under test is that
the files are enough.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.cli import app
from worldloom.evaluate import passages
from worldloom.narrative import DeterministicProvider

runner = CliRunner()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("byo-corpus")
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    world = world.narrate(DeterministicProvider()).render("markdown")
    world.export(out, overwrite=True)
    return out


@pytest.fixture(scope="module")
def exported(corpus: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("byo-passages") / "passages.jsonl"
    result = runner.invoke(app, ["evals", "passages", str(corpus), "-o", str(path)])
    assert result.exit_code == 0, result.output
    return path


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# evals passages: the index the built-in retrievers rank, as a file
# ---------------------------------------------------------------------------


def test_the_export_is_the_index_evaluate_ranks(corpus: Path, exported: Path) -> None:
    """Same units, same order, same text, same fact ids: not a re-chunking.

    A second chunking would hand the team a corpus the scorecard does not
    grade, and its first symptom would be a perfect system whose ids join
    nothing.
    """
    world = World.load(corpus)
    pool = passages(world if world.artifact_irs else world.compile())
    records = _records(exported)

    assert [r["passage_id"] for r in records] == [p.id for p in pool]
    assert [r["text"] for r in records] == [p.text for p in pool]
    assert [r["artifact_id"] for r in records] == [p.artifact_id for p in pool]
    assert [r["fact_ids"] for r in records] == [sorted(p.fact_ids) for p in pool]
    assert [r["authority"] for r in records] == [p.authority.value for p in pool]
    assert len({r["passage_id"] for r in records}) == len(records)


def test_every_record_carries_its_provenance_and_source(corpus: Path, exported: Path) -> None:
    manifest = {entry.id: entry for entry in World.load(corpus).artifacts}
    for record in _records(exported):
        assert set(record) == {
            "passage_id", "artifact_id", "artifact_type", "title", "heading",
            "source", "authority", "created_at", "fact_ids", "text",
        }
        entry = manifest[record["artifact_id"]]
        assert record["title"] == entry.title
        assert record["source"] == entry.path
        # The corpus files' own timestamp spelling, so a `temporal_cutoff`
        # from `evals export` compares against it as a string too.
        assert record["created_at"] == entry.model_dump(mode="json")["created_at"]
        assert record["text"].startswith(f"{entry.title}\n{record['heading']}\n")


def test_the_export_is_byte_stable(corpus: Path, exported: Path) -> None:
    """Stdout and file are the same bytes, every line with sorted keys."""
    result = runner.invoke(app, ["evals", "passages", str(corpus)])
    assert result.exit_code == 0, result.output
    assert result.stdout.encode("utf-8") == exported.read_bytes()
    for line in exported.read_text(encoding="utf-8").splitlines():
        assert line == json.dumps(json.loads(line), sort_keys=True)


def test_a_corpus_with_nothing_to_compile_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The golden episode predates the compiler: `evaluate` cannot index it,
    so there is nothing honest to export either."""
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, ["evals", "passages", "retail-close"])
    assert result.exit_code == 2
    assert json.loads(result.stderr)["refusal"] == "uncompilable"
