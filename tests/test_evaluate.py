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
    """Graded on difficulty, not on question type.

    Asserting that every numerical comparison passes was only true while they
    were all easy. Ranking thirty-four categories by margin is a numerical
    comparison too, and a keyword baseline has no business answering it — so the
    floor is judged on the cases the corpus labels easy.
    """
    card = score(corpus)
    outcomes = {o.case_id: o for o in card.outcomes}
    easy = [c for c in corpus.evaluations if c.difficulty == "easy"]
    assert len(easy) >= 4, "the set needs a floor to measure against"
    for case in easy:
        assert outcomes[case.id].passed, (
            f"{case.id} is labelled easy but the baseline failed it: {case.question}"
        )


def test_the_baseline_fails_the_hard_ones(corpus: World) -> None:
    """The whole point. If it passed these, the corpus would not be testing anything."""
    card = score(corpus)
    outcomes = {o.case_id: o for o in card.outcomes}
    hard = [c for c in corpus.evaluations if c.difficulty == "hard"]
    assert len(hard) >= 10
    failed = sum(1 for c in hard if not outcomes[c.id].passed)
    assert failed >= len(hard) * 0.5, (
        f"the baseline answered {len(hard) - failed}/{len(hard)} hard questions — "
        "either the retriever got cleverer or the corpus got easier"
    )


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


# ---------------------------------------------------------------------------
# The taxonomy itself
# ---------------------------------------------------------------------------


def test_every_question_shape_is_represented(corpus: World) -> None:
    """A type with one case is a type the score cannot say anything about."""
    from collections import Counter

    counts = Counter(c.evaluation_type for c in corpus.evaluations)
    assert set(counts) == set(EvaluationType), f"missing: {set(EvaluationType) - set(counts)}"
    thin = {kind.value: n for kind, n in counts.items() if n < 2}
    assert not thin, f"question types with a single case prove nothing: {thin}"


def test_the_set_is_large_enough_to_mean_something(corpus: World) -> None:
    assert len(corpus.evaluations) >= 30


def test_hard_cases_name_their_sources_and_their_traps(corpus: World) -> None:
    """A distractor is what makes authority resolution a test rather than a lookup.

    The stale status page confidently states a cause that was later ruled out. A
    case that does not name it is not testing whether a system can tell the record
    from the rumour.
    """
    authority = [
        c for c in corpus.evaluations
        if c.evaluation_type is EvaluationType.AUTHORITY_RESOLUTION
    ]
    assert authority
    assert any(c.distractor_artifact_ids for c in authority), (
        "no authority case names the document that would mislead"
    )
    assert sum(1 for c in corpus.evaluations if c.required_artifact_ids) >= 10


def test_no_case_is_both_source_and_trap(corpus: World) -> None:
    for case in corpus.evaluations:
        assert not set(case.required_artifact_ids) & set(case.distractor_artifact_ids), case.id


def test_every_answer_is_read_from_the_ledger(corpus: World) -> None:
    """The exit gate for this step: no answer is independently invented."""
    for case in corpus.evaluations:
        if case.expects_abstention:
            assert not case.expected_fact_ids
            continue
        assert case.expected_fact_ids
        for fact_id in case.expected_fact_ids:
            corpus.facts.by_id(fact_id)  # raises if ungrounded


def test_an_abstention_case_stays_unanswerable_as_the_corpus_grows(corpus: World) -> None:
    """The failure mode this family has, and had.

    "How many stores does the food division operate?" was an abstention case
    until a store estate was generated, at which point the answer appeared in the
    workbook and the case silently became wrong. So no abstention question may
    name a dimension the corpus now models.
    """
    modelled = {"store", "stores", "category", "categories", "revenue", "margin", "close"}
    for case in corpus.evaluations:
        if not case.expects_abstention:
            continue
        # It may *mention* a modelled noun, but must not ask for a figure the
        # corpus carries; the safeguard is that no fact of the corpus answers it.
        assert not case.expected_fact_ids
        counted = {"how many stores", "how many categories"}
        assert not any(phrase in case.question.casefold() for phrase in counted), (
            f"{case.id} asks for something the corpus now models: {case.question}"
        )
