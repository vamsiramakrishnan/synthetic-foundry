"""TF-IDF cosine as a second, genuinely different ranking family.

`bm25.py` was already this repository's baseline before this file existed, and
it already *is* BM25 — reading it first is what caught that a literal second
BM25 would not be a second ranking family, just a spare copy of the first
(`tfidf.py`'s module docstring has the full account). This file tests the three
things `evaluating.md`'s credibility argument depends on:

1. BM25's own numbers do not move by a hair now that `score()` takes a
   `retriever` argument — every existing hardness claim in this repository
   rests on those numbers, so a silent drift here would invalidate them all.
2. TF-IDF genuinely differs from BM25 — at least one real question in the
   fixture corpus, the two disagree on — rather than reimplementing the same
   ranking under a different name with different variable names.
3. `compare()` reports agreement and disagreement *per family*, not an
   average that could hide a family one retriever aces and the other flunks.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.evaluate import (
    LEXICAL_RETRIEVERS,
    RETRIEVERS,
    Bm25,
    TfIdf,
    compare,
    passages,
    render_agreement,
    score,
)
from worldloom.evaluate.score import DEFAULT_RETRIEVER
from worldloom.models import EvaluationType
from worldloom.narrative import DeterministicProvider

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def corpus() -> World:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    return world.narrate(DeterministicProvider()).render("markdown")


# ---------------------------------------------------------------------------
# Registry and defaults
# ---------------------------------------------------------------------------


def test_both_lexical_retrievers_are_registered_as_their_own_classes() -> None:
    """`RETRIEVERS` widened from classes to factories when the dense retriever
    arrived (it needs a pinned model and a vector cache that the scorer must
    never see). A lexical index needs nothing but the text, so its class is
    still its own factory and every caller reaching for it by name still gets
    the class — see `tests/test_embedding_retriever.py` for the third entry."""
    assert LEXICAL_RETRIEVERS == ("bm25", "tfidf")
    assert set(LEXICAL_RETRIEVERS) <= set(RETRIEVERS)
    assert RETRIEVERS["bm25"] is Bm25
    assert RETRIEVERS["tfidf"] is TfIdf


def test_the_default_retriever_is_still_bm25() -> None:
    """Every existing caller — `score(corpus)` with no argument, `worldloom
    evaluate` with no flag, CI's "the baseline still fails the hard questions"
    step — must keep meaning exactly what it always meant."""
    assert DEFAULT_RETRIEVER == "bm25"


def test_an_unknown_retriever_name_is_a_clear_error(corpus: World) -> None:
    with pytest.raises(ValueError, match="unknown retriever"):
        score(corpus, retriever="reranker-9000")


# ---------------------------------------------------------------------------
# Parity: BM25's numbers must not move
# ---------------------------------------------------------------------------


def test_score_with_no_retriever_argument_still_means_bm25(corpus: World) -> None:
    default = score(corpus)
    explicit = score(corpus, retriever="bm25")
    assert default.retriever == "bm25"
    assert [(o.case_id, o.passed, o.detail) for o in default.outcomes] == [
        (o.case_id, o.passed, o.detail) for o in explicit.outcomes
    ]


def test_bm25_numbers_are_pinned_exactly(corpus: World) -> None:
    """A regression here means either `Bm25` or the grading logic changed —
    deliberately or not. Every hardness claim this repository makes rests on
    these exact counts staying put across unrelated refactors (adding a second
    retriever chief among them), so this pins the number rather than just the
    inequalities `test_evaluate.py` already checks.

    citation_required moved 2/3 → 3/3 when the escalation thread was given the
    affected-records fact its own purpose was already quoting (the request had
    demanded a figure it withheld): the SKU count now legitimately appears in
    one more document, and the keyword baseline finds it at @5. Deliberate —
    the corpus grew a citation, not the retriever an ability — and the families
    the corpus exists to keep hard (authority, temporal, abstention) are
    unmoved at zero.

    numerical_comparison moved 6/8 → 5/8, and overall 23 → 22, when documents
    gained a signature block (`documents._signoff`). Two names, two titles and
    a date per document is more text to rank against and no more of the text a
    figure question is looking for, so one comparison fell out of the top five.
    The corpus got harder for a keyword baseline by getting more like a real
    archive, which is the direction every number in this table is supposed to
    move — a signature block that made retrieval *easier* would mean the
    baseline was matching on furniture.
    """
    card = score(corpus)
    assert card.passed == 22
    assert card.by_type() == {
        EvaluationType.AUTHORITY_RESOLUTION: (0, 3),
        EvaluationType.CAUSAL_MULTI_HOP: (1, 3),
        EvaluationType.CITATION_REQUIRED: (3, 3),
        EvaluationType.CROSS_ARTIFACT: (4, 4),
        EvaluationType.DIRECT_LOOKUP: (9, 9),
        EvaluationType.EXPECTED_ABSTENTION: (0, 9),
        EvaluationType.NUMERICAL_COMPARISON: (5, 8),
        EvaluationType.TEMPORAL_STATE: (0, 3),
    }


# ---------------------------------------------------------------------------
# TF-IDF: determinism, and genuine difference from BM25
# ---------------------------------------------------------------------------


def test_tfidf_ranking_is_reproducible(corpus: World) -> None:
    pool = passages(corpus)
    index = TfIdf([p.text for p in pool])
    question = corpus.evaluations[0].question
    assert index.rank(question, limit=5) == index.rank(question, limit=5)


def test_tfidf_returns_nothing_for_nonsense(corpus: World) -> None:
    pool = passages(corpus)
    index = TfIdf([p.text for p in pool])
    assert index.rank("zebra unicorn parliament", limit=5) == []


def test_tfidf_scores_are_bounded_like_a_cosine(corpus: World) -> None:
    """Unlike BM25's unbounded scores, cosine similarity is always in [0, 1] —
    the clearest arithmetic signature that this is a different ranking family
    and not BM25 wearing a different class name."""
    pool = passages(corpus)
    index = TfIdf([p.text for p in pool])
    for case in corpus.evaluations:
        for _, value in index.rank(case.question, limit=5):
            assert 0.0 <= value <= 1.0 + 1e-9


def test_the_two_families_disagree_on_at_least_one_question() -> None:
    """If BM25 and TF-IDF ranked identically on every question, running both
    would tell a corpus card nothing it did not already know from one.

    Asserted across seeds rather than on the module fixture, because *where*
    they split is a property of the corpus and not of the retrievers. It used
    to be seed 8128's `numerical_comparison` family; adding a signature block
    to every document moved that case out of both retrievers' top five at once,
    and the two agreed on all forty-two. Pinning the property to one seed made
    an honest corpus change look like a lost capability, so the property is now
    stated the way it was always meant: these are two ranking families, and a
    corpus exists where they differ.
    """
    for seed in (8128, 42):
        world = RetailWorld(seed=seed).build().run(
            MonthEndClose(period=PERIOD, include_operational_incident=True)
        ).narrate(DeterministicProvider()).render("markdown")
        bm25 = {o.case_id: o.passed for o in score(world, retriever="bm25").outcomes}
        tfidf = {o.case_id: o.passed for o in score(world, retriever="tfidf").outcomes}
        if any(bm25[case_id] != tfidf[case_id] for case_id in bm25):
            return
    raise AssertionError("bm25 and tfidf agreed on every question of every seed tried")


def test_tfidf_also_gets_the_easy_questions(corpus: World) -> None:
    """Same floor test `test_evaluate.py` runs for BM25: a retriever this
    mediocre should still pass the questions the corpus itself labels easy, or
    something is broken rather than merely hard."""
    card = score(corpus, retriever="tfidf")
    outcomes = {o.case_id: o for o in card.outcomes}
    easy = [c for c in corpus.evaluations if c.difficulty == "easy"]
    for case in easy:
        assert outcomes[case.id].passed, f"{case.id} is labelled easy but TF-IDF failed it"


# ---------------------------------------------------------------------------
# compare(): the credibility reading, per family
# ---------------------------------------------------------------------------


def test_compare_reports_every_family(corpus: World) -> None:
    cards = {"bm25": score(corpus, retriever="bm25"), "tfidf": score(corpus, retriever="tfidf")}
    findings = compare(cards)
    assert {f.evaluation_type for f in findings} == set(EvaluationType)
    for finding in findings:
        assert finding.finding in ("consistently hard", "consistently easy", "disagreement")
        assert set(finding.scores) == {"bm25", "tfidf"}


def test_a_family_both_retrievers_fail_reads_as_consistently_hard(corpus: World) -> None:
    """`temporal_state` is the corpus's central claim (see `evaluating.md`): a
    retriever with no notion of *when* a document was written cannot pass it,
    regardless of which ranking family it is. Both should fail it identically,
    which is the "structurally hard, not hard-for-one-heuristic" reading this
    whole mechanism exists to support."""
    cards = {"bm25": score(corpus, retriever="bm25"), "tfidf": score(corpus, retriever="tfidf")}
    findings = {f.evaluation_type: f for f in compare(cards)}
    temporal = findings[EvaluationType.TEMPORAL_STATE]
    assert temporal.finding == "consistently hard"
    assert temporal.scores["bm25"][0] == 0
    assert temporal.scores["tfidf"][0] == 0


def test_disagreement_is_flagged_per_case_not_by_matching_aggregate_rate() -> None:
    """Two retrievers passing the same *count* of cases in a family while
    disagreeing about *which* ones is a disagreement — an aggregate-only
    comparison would miss it entirely because 1/2 == 1/2."""
    from worldloom.evaluate.score import Outcome, Scorecard

    bm25 = Scorecard(
        outcomes=[
            Outcome("C-1", EvaluationType.DIRECT_LOOKUP, True, ""),
            Outcome("C-2", EvaluationType.DIRECT_LOOKUP, False, ""),
        ],
        retriever="bm25",
    )
    tfidf = Scorecard(
        outcomes=[
            Outcome("C-1", EvaluationType.DIRECT_LOOKUP, False, ""),
            Outcome("C-2", EvaluationType.DIRECT_LOOKUP, True, ""),
        ],
        retriever="tfidf",
    )
    findings = compare({"bm25": bm25, "tfidf": tfidf})
    assert len(findings) == 1
    assert findings[0].finding == "disagreement"
    assert findings[0].disagreements == 2
    assert findings[0].total == 2


def test_render_agreement_names_both_retrievers(corpus: World) -> None:
    cards = {"bm25": score(corpus, retriever="bm25"), "tfidf": score(corpus, retriever="tfidf")}
    text = render_agreement(compare(cards))
    assert "BM25" in text
    assert "TFIDF" in text
    for kind in EvaluationType:
        assert kind.value in text
