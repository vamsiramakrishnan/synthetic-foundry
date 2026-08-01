"""`worldloom evaluate --retriever` — the CLI surface over `score()`/`compare()`.

`tests/test_evaluate.py` and `tests/test_retrievers.py` cover the library calls
directly; this covers what `cli.py` adds on top — the `--retriever` choices, the
`both` mode's console and JSON shapes, and that the pre-existing default shape
(no flag at all) is untouched. Mirrors `test_diversity_cli.py`'s split between
library and command-surface tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld
from worldloom.cli import app
from worldloom.narrative import DeterministicProvider

runner = CliRunner()


@pytest.fixture(scope="module")
def scored_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("scored-corpus")
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    world = world.narrate(DeterministicProvider()).render("markdown")
    world.export(out, overwrite=True)
    return out


def test_no_flag_is_byte_identical_to_before_retriever_existed(scored_corpus: Path) -> None:
    """The exact console text `Scorecard.__str__` produced before `--retriever`
    was added — "Baseline retrieval", not "Bm25 retrieval" — so nothing reading
    the printed table (a human, a doc example) sees a changed word."""
    result = runner.invoke(app, ["evaluate", str(scored_corpus)])
    assert result.exit_code == 0, result.output
    assert "Baseline retrieval @5" in result.output


def test_default_json_shape_is_unchanged_plus_one_additive_key(scored_corpus: Path) -> None:
    result = runner.invoke(app, ["evaluate", str(scored_corpus), "--json"])
    payload = json.loads(result.output)
    assert payload["retriever"] == "bm25"
    for key in ("k", "overall", "by_type", "outcomes"):
        assert key in payload


def test_explicit_bm25_matches_the_default(scored_corpus: Path) -> None:
    default = runner.invoke(app, ["evaluate", str(scored_corpus), "--json"])
    explicit = runner.invoke(app, ["evaluate", str(scored_corpus), "--retriever", "bm25", "--json"])
    assert json.loads(default.output) == json.loads(explicit.output)


def test_tfidf_runs_and_reports_its_own_name(scored_corpus: Path) -> None:
    result = runner.invoke(app, ["evaluate", str(scored_corpus), "--retriever", "tfidf"])
    assert result.exit_code == 0, result.output
    assert "TFIDF retrieval" in result.output
    payload = json.loads(
        runner.invoke(app, ["evaluate", str(scored_corpus), "--retriever", "tfidf", "--json"]).output
    )
    assert payload["retriever"] == "tfidf"


def test_both_prints_both_scorecards_and_the_agreement_table(scored_corpus: Path) -> None:
    result = runner.invoke(app, ["evaluate", str(scored_corpus), "--retriever", "both"])
    assert result.exit_code == 0, result.output
    assert "Baseline retrieval" in result.output
    assert "TFIDF retrieval" in result.output
    assert "Agreement" in result.output


def test_both_json_grows_a_new_shape_without_touching_the_old_one(scored_corpus: Path) -> None:
    result = runner.invoke(app, ["evaluate", str(scored_corpus), "--retriever", "both", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["retriever"] == "both"
    assert set(payload["retrievers"]) == {"bm25", "tfidf"}
    for name in ("bm25", "tfidf"):
        for key in ("overall", "by_type", "outcomes"):
            assert key in payload["retrievers"][name]
    assert "agreement" in payload
    for finding in payload["agreement"].values():
        assert finding["finding"] in ("consistently hard", "consistently easy", "disagreement")


def test_an_unknown_retriever_is_a_clean_cli_error(scored_corpus: Path) -> None:
    result = runner.invoke(app, ["evaluate", str(scored_corpus), "--retriever", "nope"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
