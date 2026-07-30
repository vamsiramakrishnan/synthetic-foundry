"""The baseline retriever, and what it proves about the corpus.

A corpus is only useful if it *discriminates*. `validate` says the documents
agree with each other; nothing said whether answering questions about them is
hard. This module runs the floor — BM25 with no notion of time, authority or
provenance — and asserts the corpus is hard in the specific ways it claims to be.

A failing baseline is the passing test. If the numbers here ever go *up* without
someone deliberately making the retriever cleverer, the corpus got easier.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.evaluate import Bm25, passages, score
from worldloom.models import EvaluationType
from worldloom.narrative import DeterministicProvider

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def corpus() -> World:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    return world.narrate(DeterministicProvider()).render("markdown")


def test_the_index_sees_documents_not_machinery(corpus: World) -> None:
    """A retriever answering from the lineage appendix is answering from something
    no reader would have found, which flatters the score without meaning anything."""
    pool = passages(corpus)
    assert pool
    assert all(not p.hidden for p in pool)
    assert any(p.hidden for p in passages(corpus, include_hidden=True))


def test_every_passage_carries_its_provenance(corpus: World) -> None:
    """Available to the index, unused by the baseline — that gap is the point."""
    for passage in passages(corpus):
        assert passage.authority is not None
        assert passage.created_at is not None
        assert passage.artifact_id


def test_ranking_is_reproducible(corpus: World) -> None:
    """Two passages scoring identically must not swap places between runs."""
    pool = passages(corpus)
    index = Bm25([p.text for p in pool])
    question = corpus.evaluations[0].question
    assert index.rank(question, limit=5) == index.rank(question, limit=5)


def test_the_retriever_returns_nothing_for_nonsense(corpus: World) -> None:
    pool = passages(corpus)
    index = Bm25([p.text for p in pool])
    assert index.rank("zebra unicorn parliament", limit=5) == []


# ---------------------------------------------------------------------------
# What the corpus makes hard
# ---------------------------------------------------------------------------


def test_the_baseline_handles_the_easy_questions(corpus: World) -> None:
    """If it failed these the corpus would be incoherent, not hard."""
    card = score(corpus)
    by_type = card.by_type()
    for kind in (EvaluationType.DIRECT_LOOKUP, EvaluationType.NUMERICAL_COMPARISON):
        passed, total = by_type[kind]
        assert passed == total, f"{kind.value}: a keyword baseline should manage {passed}/{total}"


def test_the_baseline_cannot_abstain(corpus: World) -> None:
    """The corpus asks plausible questions it does not answer.

    BM25 retrieves whatever overlaps most, so it answers confidently from
    unrelated documents. Knowing the corpus does not contain the answer is the
    capability being tested, and the floor does not have it.
    """
    passed, total = score(corpus).by_type()[EvaluationType.EXPECTED_ABSTENTION]
    assert total >= 3
    assert passed == 0, "a keyword baseline should never abstain — if it does, check the threshold"


def test_the_baseline_fails_on_knowing_when(corpus: World) -> None:
    """The corpus's central claim, measured.

    The question asks what was believed at a moment when the belief was wrong.
    Every document is in the index at once, so keyword overlap surfaces the later
    correction — the confidently right answer to a question that asked for the
    contemporaneous one.
    """
    card = score(corpus)
    passed, total = card.by_type()[EvaluationType.TEMPORAL_STATE]
    assert total >= 1
    assert passed == 0

    outcome = next(o for o in card.outcomes if o.evaluation_type is EvaluationType.TEMPORAL_STATE)
    assert "after the cut-off" in outcome.detail


def test_a_temporally_aware_retriever_can_answer_what_the_baseline_cannot(corpus: World) -> None:
    """The question has to be *fair*, not merely hard.

    A corpus that nobody can answer is not a benchmark, it is a broken corpus. So
    the same question is run again with the one capability the baseline lacks:
    passages filtered to those that existed at the cut-off. That retriever gets it
    right, which proves the gap is temporal awareness and not missing evidence.

    This also guards the scorer. Its first version filtered by the cut-off before
    grading — handing the baseline the very capability under test, and making the
    corpus look easy because the scorer was doing the work.
    """
    case = next(
        c for c in corpus.evaluations
        if c.evaluation_type is EvaluationType.TEMPORAL_STATE and c.temporal_cutoff
    )
    pool = passages(corpus)

    blind = Bm25([p.text for p in pool])
    top_blind = pool[blind.rank(case.question, limit=1)[0][0]]
    assert not set(case.expected_fact_ids) <= top_blind.fact_ids or (
        top_blind.created_at > case.temporal_cutoff
    ), "the baseline should not be able to answer this correctly"

    knowable = [p for p in pool if p.created_at <= case.temporal_cutoff]
    aware = Bm25([p.text for p in knowable])
    top_aware = knowable[aware.rank(case.question, limit=1)[0][0]]
    assert set(case.expected_fact_ids) <= top_aware.fact_ids, (
        "a retriever that knows when documents were written must be able to answer"
    )


def test_the_scorecard_reports_by_question_type(corpus: World) -> None:
    card = score(corpus)
    assert len(card) == len(corpus.evaluations)
    assert sum(total for _, total in card.by_type().values()) == len(card)
    assert "overall" in str(card)
