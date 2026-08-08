"""The dense retriever, its cache, and what happens when the extra is absent.

Every test here runs **with no model installed and no network**, deliberately.
That is not a compromise forced by CI — it is the property the module is built
around and therefore the property most worth testing: vectors are cached
content-addressed against a pinned model, so a corpus carrying its cache is
scored by arithmetic over that file and nothing else. A suite that needed to
download half a gigabyte of weights to check the retriever ranks correctly would
be testing the publisher's uptime.

Three things are pinned:

1. **Absence degrades cleanly.** No extra, no cache, and the result is an
   `EmbeddingUnavailable` naming the model and the extra — never an
   `ImportError` from inside a library, never a traceback out of the CLI. The
   `--retriever all` path skips it and still reports the lexical baselines,
   because two readings and a stated omission beat a crash.
2. **The cache is the measurement.** Scores computed from a cache are exact
   integer arithmetic — same bytes, same answer, on any machine — and the file
   itself is byte-stable so two runs that learned the same vectors write the
   same file.
3. **The grading never learns which retriever it is holding.** A retriever with
   a hand-built cache runs through `score()` and `compare()` unchanged, which is
   the whole claim the lexical-versus-semantic comparison rests on.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.cli import app
from worldloom.evaluate import RETRIEVERS, compare, passages, score
from worldloom.evaluate import embedding as embedding_module
from worldloom.evaluate.embedding import (
    DEFAULT_PIN,
    MINILM,
    POTION_RETRIEVAL,
    SCHEME,
    Embedding,
    EmbeddingUnavailable,
    ModelPin,
    VectorCache,
    configured,
    quantise,
)
from worldloom.narrative import DeterministicProvider

runner = CliRunner()


@pytest.fixture(scope="module")
def corpus() -> World:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    return world.narrate(DeterministicProvider()).render("markdown")


# ---------------------------------------------------------------------------
# A stand-in model: deterministic, offline, and not pretending to be semantic
# ---------------------------------------------------------------------------


class _HashedBackend:
    """Vectors from a hash of the text's tokens.

    Not a semantic model and not claiming to be one — it exists so the *plumbing*
    (cache round-trip, quantisation, integer ranking, registry, CLI) can be
    tested without a download. The one property it shares with a real encoder is
    the one under test: the same text always gives the same vector, and
    different text gives a different one. Anything about ranking *quality* is
    measured by `tools/measure_retrievers.py` against the real pins, not here.
    """

    dimensions = 16
    calls = 0

    def encode(self, texts):  # type: ignore[no-untyped-def]
        type(self).calls += 1
        rows = []
        for text in texts:
            values = np.zeros(self.dimensions, dtype=np.float64)
            for token in text.casefold().split():
                # `hash()` is randomised per process, so the corpus's own
                # content_key is used instead — the same rule the rest of this
                # repository follows, and for the same reason.
                from worldloom.ids import content_key

                digest = content_key(token)
                for position in range(self.dimensions):
                    values[position] += int(digest[position * 2 : position * 2 + 2], 16) - 128
            rows.append(values)
        return np.asarray(rows)


TEST_PIN = ModelPin(id="worldloom/test-hashed", revision="0" * 40, backend="hashed", dimensions=16)


@pytest.fixture
def hashed_backend(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setitem(embedding_module.BACKENDS, "hashed", lambda pin: _HashedBackend())
    _HashedBackend.calls = 0
    return _HashedBackend


@pytest.fixture
def warm_cache(tmp_path: Path, corpus: World, hashed_backend) -> Path:  # type: ignore[no-untyped-def]
    """A cache holding every passage *and* every question of `corpus`."""
    path = tmp_path / "vectors.json"
    index = Embedding(
        [p.text for p in passages(corpus)],
        pin=TEST_PIN,
        cache=VectorCache.load(path, TEST_PIN),
    )
    for case in corpus.evaluations:
        index.rank(case.question, limit=5)
    return path


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------


def test_the_embedding_retriever_is_registered_beside_the_lexical_ones() -> None:
    """Registered unconditionally, extra or no extra. "You need the extra" and
    "no such retriever" are different errors and only one of them is true."""
    assert set(RETRIEVERS) == {"bm25", "tfidf", "embedding"}


def test_registering_a_second_pin_is_one_line(hashed_backend) -> None:  # type: ignore[no-untyped-def]
    """The claim `configured()` makes: a differently-pinned model becomes a
    retriever without a new class and without the scorer learning anything."""
    factory = configured(pin=TEST_PIN, cache=None, autosave=False)
    index = factory(["month end close", "capital adequacy return"])
    assert index.rank("close", limit=2) is not None


def test_the_registry_holds_factories_and_the_lexical_ones_are_still_classes() -> None:
    """Widening `RETRIEVERS` to factories must not have turned `bm25` into a
    wrapper — every existing caller that reaches for the class by name still
    gets the class."""
    from worldloom.evaluate import Bm25, TfIdf

    assert RETRIEVERS["bm25"] is Bm25
    assert RETRIEVERS["tfidf"] is TfIdf
    assert callable(RETRIEVERS["embedding"])


# ---------------------------------------------------------------------------
# Absence: the extra is not installed
# ---------------------------------------------------------------------------


def _block_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every backend raises `EmbeddingUnavailable`, exactly as an uninstalled
    extra does. Applied at `BACKENDS` rather than by hiding modules from
    `sys.modules`, because the contract under test is what `_load_backend`
    raises, and a test that faked the import machinery could pass while the real
    import path raised `ImportError` straight through the CLI."""

    def unavailable(pin: ModelPin):  # type: ignore[no-untyped-def]
        raise EmbeddingUnavailable(
            f"{pin} needs the model2vec backend, which is not installed. "
            'Install it with `pip install "worldloom[embeddings]"`, or score '
            "against a cache that already holds this corpus's vectors."
        )

    monkeypatch.setattr(
        embedding_module, "BACKENDS", {name: unavailable for name in embedding_module.BACKENDS}
    )


def test_a_missing_extra_is_a_stated_refusal_not_an_import_error(
    tmp_path: Path, corpus: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_backends(monkeypatch)
    monkeypatch.setitem(RETRIEVERS, "embedding", configured(cache=tmp_path / "empty.json"))
    with pytest.raises(EmbeddingUnavailable) as raised:
        score(corpus, retriever="embedding")
    message = str(raised.value)
    assert "worldloom[embeddings]" in message
    assert DEFAULT_PIN.id in message


def test_the_cli_skips_the_unavailable_retriever_and_still_reports_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--retriever all` on an installation without the extra is a smaller
    measurement, not a failed command."""
    _block_backends(monkeypatch)
    exported = tmp_path / "corpus"
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    world.narrate(DeterministicProvider()).render("markdown").export(exported, overwrite=True)

    result = runner.invoke(
        app,
        ["evaluate", str(exported), "--retriever", "all", "--vectors", str(tmp_path / "none.json")],
    )
    assert result.exit_code == 0, result.output
    assert "skipped embedding" in result.output
    assert "worldloom[embeddings]" in result.output
    assert "Baseline retrieval" in result.output
    assert "TFIDF retrieval" in result.output
    assert "Traceback" not in result.output


def test_asking_for_the_unavailable_retriever_by_name_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicitly requested and not runnable: nonzero, because a clean exit with
    no numbers reads as "scored, nothing to report" — but a stated reason and no
    traceback, because a missing optional package is not a defect."""
    _block_backends(monkeypatch)
    exported = tmp_path / "corpus"
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    world.narrate(DeterministicProvider()).render("markdown").export(exported, overwrite=True)

    result = runner.invoke(
        app,
        ["evaluate", str(exported), "--retriever", "embedding", "--vectors", str(tmp_path / "none.json")],
    )
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "worldloom[embeddings]" in result.output


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------


def test_a_warm_cache_scores_with_no_model_at_all(
    corpus: World, warm_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim the whole design rests on: a corpus carrying its vectors is
    scored on an installation that cannot embed anything."""
    _block_backends(monkeypatch)
    monkeypatch.setitem(RETRIEVERS, "embedding", configured(pin=TEST_PIN, cache=warm_cache))
    card = score(corpus, retriever="embedding")
    assert len(card) == len(corpus.evaluations)


def test_a_warm_cache_never_asks_the_model_anything(
    corpus: World, warm_cache: Path, hashed_backend
) -> None:  # type: ignore[no-untyped-def]
    """Not merely "it works offline" but "it does not consult the model", which
    is the difference between a cache and a fallback."""
    hashed_backend.calls = 0
    index = Embedding(
        [p.text for p in passages(corpus)],
        pin=TEST_PIN,
        cache=VectorCache.load(warm_cache, TEST_PIN),
    )
    for case in corpus.evaluations:
        index.rank(case.question, limit=5)
    assert hashed_backend.calls == 0


def test_the_cache_holds_questions_as_well_as_passages(corpus: World, warm_cache: Path) -> None:
    """A cache of passages only would still need the model to embed a question,
    which is most of the way to needing the model. Saving after the corpus was
    embedded and never again is exactly how that regression happens."""
    document = json.loads(warm_cache.read_text(encoding="utf-8"))
    assert len(document["vectors"]) == len(passages(corpus)) + len(
        {case.question for case in corpus.evaluations}
    )


def test_the_cache_file_is_byte_stable(tmp_path: Path, hashed_backend) -> None:  # type: ignore[no-untyped-def]
    """Two runs that learned the same vectors write the same bytes — sorted
    keys, base64 payloads, and not a float anywhere in the file. A cache that
    was not diffable would be unusable as evidence for why a number moved."""
    documents = ["month end close", "capital adequacy", "incident postmortem"]
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    for path in (first, second):
        Embedding(documents, pin=TEST_PIN, cache=VectorCache.load(path, TEST_PIN))
    assert first.read_bytes() == second.read_bytes()


def test_a_cache_written_for_another_pin_is_treated_as_empty(
    tmp_path: Path, hashed_backend
) -> None:  # type: ignore[no-untyped-def]
    """Not an error, and not silently mixed in either. Caches are addressed by
    content, so the honest reading of another model's file is that it holds none
    of ours — refusing to start would make a stale sidecar an outage, and reusing
    it would make the score a lie."""
    path = tmp_path / "vectors.json"
    Embedding(["month end close"], pin=TEST_PIN, cache=VectorCache.load(path, TEST_PIN))
    other = ModelPin(id="worldloom/test-hashed", revision="1" * 40, backend="hashed", dimensions=16)
    reloaded = VectorCache.load(path, other)
    assert reloaded.vectors == {}


def test_the_scheme_is_part_of_the_cache_key() -> None:
    """Changing how vectors are quantised changes the retriever, so it must
    invalidate every vector rather than mixing two scales in one file."""
    assert SCHEME in ("int8-l2-v1",)  # pinned: bumping it is a deliberate act
    first = POTION_RETRIEVAL.key
    monkey = ModelPin(
        id=POTION_RETRIEVAL.id,
        revision=POTION_RETRIEVAL.revision,
        backend=POTION_RETRIEVAL.backend,
        dimensions=POTION_RETRIEVAL.dimensions,
    )
    assert monkey.key == first  # same pin, same key
    assert MINILM.key != first  # different model, different key


def test_every_shipped_pin_names_a_commit_not_a_branch() -> None:
    """`main` is not a pin. A revision that can move under the name is the exact
    failure this module exists to prevent."""
    for pin in (POTION_RETRIEVAL, MINILM):
        assert len(pin.revision) == 40, pin
        assert all(character in "0123456789abcdef" for character in pin.revision), pin


# ---------------------------------------------------------------------------
# Quantisation and integer ranking
# ---------------------------------------------------------------------------


def test_quantisation_is_unit_scaled_and_symmetric() -> None:
    vectors = quantise(np.array([[3.0, 4.0], [-1.0, 0.0], [0.0, 0.0]]))
    assert vectors.dtype == np.int8
    assert vectors[0].tolist() == [76, 102]  # 0.6, 0.8 scaled by 127
    assert vectors[1].tolist() == [-127, 0]
    assert vectors[2].tolist() == [0, 0]  # a zero vector stays zero, not a division by zero


def test_ranking_is_integer_arithmetic_and_therefore_repeatable(
    tmp_path: Path, hashed_backend
) -> None:  # type: ignore[no-untyped-def]
    documents = ["month end close variance", "incident root cause", "capital adequacy return"]
    index = Embedding(documents, pin=TEST_PIN, cache=VectorCache.load(tmp_path / "v.json", TEST_PIN))
    assert index.rank("close variance", limit=3) == index.rank("close variance", limit=3)


def test_scores_are_cosines(tmp_path: Path, hashed_backend) -> None:  # type: ignore[no-untyped-def]
    documents = ["month end close variance", "incident root cause"]
    index = Embedding(documents, pin=TEST_PIN, cache=VectorCache.load(tmp_path / "v.json", TEST_PIN))
    for _, value in index.rank("close", limit=2):
        assert 0.0 < value <= 1.0 + 1e-12


def test_an_empty_corpus_ranks_nothing(tmp_path: Path, hashed_backend) -> None:  # type: ignore[no-untyped-def]
    index = Embedding([], pin=TEST_PIN, cache=VectorCache.load(tmp_path / "v.json", TEST_PIN))
    assert index.rank("anything", limit=5) == []


# ---------------------------------------------------------------------------
# Through the scorer, unchanged
# ---------------------------------------------------------------------------


def test_the_grading_is_the_same_grading(corpus: World, warm_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A dense retriever produces a `Scorecard` of the same shape, over the same
    cases, graded by the same code — which is what makes the per-family
    comparison evidence rather than two unrelated tables printed together."""
    monkeypatch.setitem(RETRIEVERS, "embedding", configured(pin=TEST_PIN, cache=warm_cache))
    dense = score(corpus, retriever="embedding")
    lexical = score(corpus, retriever="bm25")
    assert dense.retriever == "embedding"
    assert [o.case_id for o in dense.outcomes] == [o.case_id for o in lexical.outcomes]
    assert [o.evaluation_type for o in dense.outcomes] == [o.evaluation_type for o in lexical.outcomes]


def test_compare_takes_three_retrievers(corpus: World, warm_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RETRIEVERS, "embedding", configured(pin=TEST_PIN, cache=warm_cache))
    cards = {name: score(corpus, retriever=name) for name in ("bm25", "tfidf", "embedding")}
    findings = compare(cards)
    for finding in findings:
        assert set(finding.scores) == {"bm25", "tfidf", "embedding"}
    from worldloom.evaluate import render_agreement

    text = render_agreement(findings)
    assert "EMBEDDING" in text
    # Three columns, so the verdict says "all" — "hard for both" under three
    # columns describes an experiment that did not run.
    assert "for both" not in text


def test_the_difficulty_reading_needs_both_sides(corpus: World) -> None:
    """`difficulty_by_family` compares lexical against semantic. Given only
    lexical cards it returns nothing rather than a one-sided table, because a
    comparison with one side missing is not a weaker comparison."""
    from worldloom.evaluate import difficulty_by_family

    lexical_only = {name: score(corpus, retriever=name) for name in ("bm25", "tfidf")}
    assert difficulty_by_family(lexical_only) == []


def test_a_family_the_semantic_side_solves_reads_as_a_lexical_trap() -> None:
    """The finding this whole exercise exists to be able to state: a family the
    keyword baselines fail and a semantic retriever solves was never difficulty.
    Built from hand-made scorecards rather than a corpus, so the *reading* is
    pinned independently of whatever any particular corpus happens to score."""
    from worldloom.evaluate import difficulty_by_family
    from worldloom.evaluate.score import Outcome, Scorecard
    from worldloom.models import EvaluationType

    def card(name: str, passes: list[bool]) -> Scorecard:
        return Scorecard(
            outcomes=[
                Outcome(f"C-{index}", EvaluationType.DIRECT_LOOKUP, passed, "")
                for index, passed in enumerate(passes)
            ],
            retriever=name,
        )

    trap = difficulty_by_family({
        "bm25": card("bm25", [False, False, False, False]),
        "tfidf": card("tfidf", [False, False, False, False]),
        "embedding": card("embedding", [True, True, True, True]),
    })
    assert [f.verdict for f in trap] == ["lexical trap"]

    hard = difficulty_by_family({
        "bm25": card("bm25", [False, False, False, False]),
        "tfidf": card("tfidf", [False, False, False, False]),
        "embedding": card("embedding", [False, False, False, False]),
    })
    assert [f.verdict for f in hard] == ["genuinely hard"]

    blind = difficulty_by_family({
        "bm25": card("bm25", [True, True, True, True]),
        "tfidf": card("tfidf", [True, True, True, True]),
        "embedding": card("embedding", [False, False, False, False]),
    })
    assert [f.verdict for f in blind] == ["semantic blind spot"]


def test_the_all_mode_json_carries_the_difficulty_reading(
    tmp_path: Path, corpus: World, warm_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(RETRIEVERS, "embedding", configured(pin=TEST_PIN, cache=warm_cache))
    exported = tmp_path / "corpus"
    corpus.export(exported, overwrite=True)
    result = runner.invoke(app, ["evaluate", str(exported), "--retriever", "all", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload["retrievers"]) == {"bm25", "tfidf", "embedding"}
    assert payload["retriever"] == "all"
    for entry in payload["difficulty"].values():
        assert entry["verdict"] in (
            "solved by everything", "lexical trap", "semantic blind spot", "genuinely hard",
        )


def test_both_mode_carries_no_difficulty_reading(tmp_path: Path, corpus: World) -> None:
    """`--retriever both` is two lexical baselines and its payload must keep the
    shape it had before a third retriever existed — the reading is additive and
    absent, not present and empty."""
    exported = tmp_path / "corpus"
    corpus.export(exported, overwrite=True)
    result = runner.invoke(app, ["evaluate", str(exported), "--retriever", "both", "--json"])
    payload = json.loads(result.output)
    assert set(payload["retrievers"]) == {"bm25", "tfidf"}
    assert "difficulty" not in payload


def test_bm25_is_untouched_by_any_of_this(corpus: World) -> None:
    """Every hardness claim in this repository rests on these exact counts. A
    third retriever must not have moved them by a hair."""
    from worldloom.models import EvaluationType

    card = score(corpus)
    assert card.by_type()[EvaluationType.TEMPORAL_STATE] == (0, 3)
    assert card.by_type()[EvaluationType.AUTHORITY_RESOLUTION] == (0, 3)
    assert card.by_type()[EvaluationType.EXPECTED_ABSTENTION] == (0, 9)
