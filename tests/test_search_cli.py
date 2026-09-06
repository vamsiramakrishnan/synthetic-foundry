"""`worldloom search` — the corpus asked about itself, deterministically.

The command exists for self-referential narration: before the harness writes a
document that amends or summarises earlier ones, it retrieves what the corpus
already says — through the *same* passage index and the *same* BM25 ranking
`evaluate` scores retrievers with. That sameness is the property worth pinning:
a corpus searched while it is being written must be searched the way it will
be judged, or the harness optimises against an index the benchmark never uses.

Mirrors `test_evaluate_cli.py`'s split: the index and ranking are covered by
`test_evaluate*.py`/`test_retrievers.py`; this file covers only what the
command adds — refusals, the cutoff, hidden sections, and output stability.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld
from worldloom.cli import app
from worldloom.evaluate.bm25 import Bm25
from worldloom.evaluate.index import passages
from worldloom.narrative import DeterministicProvider

runner = CliRunner()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("searchable-corpus")
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    world.narrate(DeterministicProvider()).export(out, overwrite=True)
    return out


def test_hits_carry_what_an_amending_author_needs(corpus: Path) -> None:
    """passage_id, artifact_id, fact_ids and full text — enough to cite and
    quote a prior document without opening the repository."""
    result = runner.invoke(app, ["search", str(corpus), "operational incident", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["searched"] > 0
    assert payload["hits"], "an incident build must have an incident passage"
    best = payload["hits"][0]
    for key in ("passage_id", "artifact_id", "heading", "created_at", "authority", "score", "fact_ids", "text"):
        assert key in best
    assert best["artifact_id"] in best["passage_id"]
    assert best["score"] > 0.0


def test_the_ranking_is_evaluates_ranking(corpus: Path) -> None:
    """The command must not grow its own retriever. Rebuilt from the library
    directly, the top hits are identical — same passages, same scores."""
    result = runner.invoke(app, ["search", str(corpus), "stock loss variance", "--json", "-k", "4"])
    payload = json.loads(result.output)

    from worldloom.world import World

    found = passages(World.load(str(corpus)))
    index = Bm25([passage.text for passage in found])
    expected = [
        (found[position].id, score)
        for position, score in index.rank("stock loss variance", limit=4)
        if score > 0.0
    ]
    assert [(hit["passage_id"], hit["score"]) for hit in payload["hits"]] == expected


def test_same_query_twice_is_byte_identical(corpus: Path) -> None:
    first = runner.invoke(app, ["search", str(corpus), "margin", "--json"])
    second = runner.invoke(app, ["search", str(corpus), "margin", "--json"])
    assert first.output == second.output


def test_zero_score_passages_are_not_padded_in(corpus: Path) -> None:
    """A passage sharing no term with the query is not a worse answer, it is
    no answer; returning it would present document order as a ranking."""
    result = runner.invoke(app, ["search", str(corpus), "zzqxjv unheard nonsense", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["hits"] == []


def test_an_empty_query_is_refused(corpus: Path) -> None:
    result = runner.invoke(app, ["search", str(corpus), "   "])
    assert result.exit_code == 2
    assert "empty query" in result.output


def test_a_bad_cutoff_is_refused_naming_the_value(corpus: Path) -> None:
    result = runner.invoke(app, ["search", str(corpus), "margin", "--as-of", "not-a-date"])
    assert result.exit_code == 2
    assert "not-a-date" in result.output


def test_the_cutoff_narrows_to_what_existed(corpus: Path) -> None:
    """`--as-of` is the narration contract's temporal-cutoff rule applied to
    retrieval: an author amending in March may only lean on March's corpus."""
    everything = json.loads(
        runner.invoke(app, ["search", str(corpus), "margin", "--json"]).output
    )
    all_created = sorted(
        {hit["created_at"] for hit in everything["hits"]}
    )
    assert all_created, "the corpus must have dated hits for this test to bite"

    narrowed = json.loads(
        runner.invoke(
            app, ["search", str(corpus), "margin", "--json", "--as-of", all_created[0]]
        ).output
    )
    assert narrowed["searched"] < everything["searched"]
    assert all(hit["created_at"] <= all_created[0] for hit in narrowed["hits"])


def test_a_cutoff_before_the_world_began_is_refused(corpus: Path) -> None:
    """Nothing existed, so there is nothing to search — an error naming the
    cutoff, not an empty success a loop would happily iterate on."""
    result = runner.invoke(app, ["search", str(corpus), "margin", "--as-of", "1990-01-01"])
    assert result.exit_code == 2
    assert "1990-01-01" in result.output


def test_hidden_sections_stay_hidden_until_asked_for(corpus: Path) -> None:
    """`evaluate`'s rule, inherited deliberately: lineage appendices are
    machinery, and retrieval that answers from them answers from something no
    reader would have found."""
    visible = json.loads(
        runner.invoke(app, ["search", str(corpus), "lineage", "--json"]).output
    )
    with_hidden = json.loads(
        runner.invoke(
            app, ["search", str(corpus), "lineage", "--json", "--include-hidden"]
        ).output
    )
    assert with_hidden["searched"] >= visible["searched"]
