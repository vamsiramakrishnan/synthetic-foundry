"""What the retrievers must still answer after being made fast.

`worldloom evaluate` is O(cases × passages) by construction and both grow
linearly with the corpus, so it became the slowest thing in the tool — 26
minutes at 11,264 artifacts. The fix was an inverted index: `rank` touches only
the postings for a query's terms instead of scoring every passage for every
case.

**A performance fix that changes an answer is a bug, not a speed-up**, and for
this one the risk is unusually specific. A sum of the same terms in a different
order is a *different double*, and the transformation inverts a nested loop — so
"the maths is the same" is not an argument, it is the thing to prove. This file
proves it the way ``tests/test_similarity.py`` proves its join: with a reference
implementation right here, written as the obvious scan, checked for **exact
float equality** rather than `pytest.approx`. Approximate agreement is what a
reordered summation gives you; exact agreement is what an unreordered one gives
you, and only the second claim is the one being made.

The reference scans below are transcriptions of the pre-change implementations.
They are deliberately not imported from anywhere: their whole value is being an
independently-written statement of the answer, and a shared helper would drift
into agreeing with the optimisation by construction.
"""

from __future__ import annotations

import math
import random
from collections import Counter

import pytest

from worldloom import RetailWorld
from worldloom.evaluate import RETRIEVERS, Bm25, TfIdf, passages, score
from worldloom.evaluate.bm25 import B, K1, tokens
from worldloom.narrative import DeterministicProvider
from worldloom.scenarios import MonthEndClose
from worldloom.world import World


# ---------------------------------------------------------------------------
# The reference scans
# ---------------------------------------------------------------------------


class ScanBm25:
    """BM25 as a scan: score every document for every query, then sort the lot.

    The implementation `Bm25` had before it was inverted, kept here so the
    optimisation has something to be equal to. Note the loop order — document
    outer, query term inner — which is exactly what the inverted version has to
    reproduce per document while nesting the other way round.
    """

    def __init__(self, documents: list[str]) -> None:
        self.documents = documents
        self._terms = [Counter(tokens(document)) for document in documents]
        self._lengths = [sum(counts.values()) for counts in self._terms]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        seen: Counter = Counter()
        for counts in self._terms:
            seen.update(counts.keys())
        total = len(self._terms)
        self._idf = {
            term: math.log(1 + (total - appearances + 0.5) / (appearances + 0.5))
            for term, appearances in seen.items()
        }

    def scores(self, query: str) -> list[float]:
        wanted = tokens(query)
        out = []
        for index, counts in enumerate(self._terms):
            length = self._lengths[index] or 1
            total = 0.0
            for term in wanted:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                denominator = frequency + K1 * (1 - B + B * length / (self._average or 1))
                total += self._idf.get(term, 0.0) * frequency * (K1 + 1) / denominator
            out.append(total)
        return out

    def rank(self, query: str, *, limit: int) -> list[tuple[int, float]]:
        scored = list(enumerate(self.scores(query)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [pair for pair in scored[:limit] if pair[1] > 0.0]


class ScanTfIdf:
    """TF-IDF cosine as a scan, likewise — the implementation `TfIdf` had."""

    def __init__(self, documents: list[str]) -> None:
        self.documents = documents
        term_counts = [Counter(tokens(document)) for document in documents]
        document_frequency: Counter[str] = Counter()
        for counts in term_counts:
            document_frequency.update(counts.keys())
        total = len(term_counts)
        self._idf = {
            term: math.log((1 + total) / (1 + df)) + 1
            for term, df in document_frequency.items()
        }
        self._vectors = []
        self._norms = []
        for counts in term_counts:
            vector = {
                term: (1 + math.log(frequency)) * self._idf[term]
                for term, frequency in counts.items()
            }
            self._vectors.append(vector)
            self._norms.append(math.sqrt(sum(w * w for w in vector.values())))

    def scores(self, query: str) -> list[float]:
        query_counts = Counter(tokens(query))
        query_vector = {
            term: (1 + math.log(frequency)) * self._idf[term]
            for term, frequency in query_counts.items()
            if term in self._idf
        }
        query_norm = math.sqrt(sum(w * w for w in query_vector.values()))
        out = []
        for vector, norm in zip(self._vectors, self._norms):
            if not query_norm or not norm:
                out.append(0.0)
                continue
            # Accumulated in an explicit loop, not `sum()`, and that is the
            # whole reason this line has a comment. **CPython 3.12 changed
            # `builtins.sum()` to use Neumaier compensated summation for
            # floats** (gh-100425), so `sum(floats)` and a left-to-right `+=`
            # over the same floats give different last bits on 3.12+ and
            # identical ones on 3.11. This reference existed to model what the
            # shipped scorer does; written with `sum()` it modelled what
            # *CPython* does, and the pin passed on 3.11 and failed on 3.12 and
            # 3.13 for a difference that was in the reference rather than in the
            # implementation being checked.
            #
            # `ScanBm25.scores` above was always written this way, which is
            # exactly why bm25 never failed. Naive accumulation is also the
            # version-independent choice: a retriever whose scores depend on
            # which Python built the corpus cannot be pinned at all.
            dot = 0.0
            for term, weight in query_vector.items():
                dot += weight * vector.get(term, 0.0)
            out.append(dot / (query_norm * norm))
        return out

    def rank(self, query: str, *, limit: int) -> list[tuple[int, float]]:
        scored = list(enumerate(self.scores(query)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [pair for pair in scored[:limit] if pair[1] > 0.0]


REFERENCES = {"bm25": (Bm25, ScanBm25), "tfidf": (TfIdf, ScanTfIdf)}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _corpus_shaped_documents(count: int, *, seed: int) -> list[str]:
    """Documents shaped the way this engine's actually are: heavy shared
    boilerplate, a repeated template family, and some genuinely distinct bodies.

    The shape matters for what it stresses. A corpus of unrelated documents
    gives every term a short posting list and would flatter any inverted index;
    boilerplate gives some terms a posting list covering the *whole* pool, which
    is the case where the optimisation has the least to offer and the most
    opportunity to disagree about a tie.
    """
    rng = random.Random(seed)
    boilerplate = "close period variance reconciliation controller finance group"
    out: list[str] = []
    for index in range(count):
        if index and index % 7 == 0:
            out.append(out[index - 7] + f" addendum{index % 3}")
        else:
            body = " ".join(f"w{rng.randrange(400)}" for _ in range(rng.randint(20, 90)))
            out.append(f"{boilerplate} {body}")
    return out


def _queries(seed: int) -> list[str]:
    """Queries spanning every case the ranking has to get right: terms nothing
    carries, terms everything carries, and the ordinary middle."""
    rng = random.Random(seed)
    fixed = [
        "",                                   # no terms at all
        "zebra unicorn parliament",           # nothing in the corpus
        "close period variance",              # every document carries these
        "close close close",                  # a repeated query term
        "addendum1",                          # only the template family
    ]
    return fixed + [
        " ".join(f"w{rng.randrange(400)}" for _ in range(rng.randint(1, 6)))
        for _ in range(40)
    ]


@pytest.fixture(scope="module")
def narrated_world() -> World:
    """A real corpus with prose, so the pins run over the text the retrievers
    actually see rather than over synthetic strings alone."""
    world = RetailWorld(seed=8128).build()
    world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    world = world.compile()
    return world.narrate(DeterministicProvider()).compile()


# ---------------------------------------------------------------------------
# 1. The scores are the same doubles, not merely close ones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_scores_are_bit_identical_to_the_scan(name: str) -> None:
    """Exact equality, not `approx`.

    `approx` would pass for an implementation that re-associated the sum, and
    re-association is the one failure mode worth testing for here: it moves a
    score by an ulp, which moves nothing at all until two passages are tied and
    the ranking swaps. This asserts the stronger property that makes the
    swap impossible rather than unlikely.
    """
    fast_cls, scan_cls = REFERENCES[name]
    documents = _corpus_shaped_documents(120, seed=8128)
    fast, scan = fast_cls(list(documents)), scan_cls(list(documents))
    for query in _queries(11):
        assert fast.scores(query) == scan.scores(query), query


@pytest.mark.parametrize("name", sorted(REFERENCES))
@pytest.mark.parametrize("limit", [1, 2, 5, 10, 1000])
def test_rank_is_identical_to_scoring_everything_and_sorting(name: str, limit: int) -> None:
    """Including at a limit larger than the pool, and at limit 1, where a heap
    of size one is the most likely place for a tie-break to differ from a sort."""
    fast_cls, scan_cls = REFERENCES[name]
    documents = _corpus_shaped_documents(120, seed=8128)
    fast, scan = fast_cls(list(documents)), scan_cls(list(documents))
    for query in _queries(11):
        assert fast.rank(query, limit=limit) == scan.rank(query, limit=limit), query


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_ties_break_toward_the_lower_index(name: str) -> None:
    """The property `rank`'s docstring promises, tested where it is decidable:
    identical documents score identically, so the order is entirely the
    tie-break's doing. A heap that resolved ties by insertion accident would
    still pass a same-scores assertion and fail this one."""
    fast_cls, _ = REFERENCES[name]
    index = fast_cls(["alpha beta gamma"] * 6)
    ranked = index.rank("alpha beta", limit=4)
    assert [position for position, _ in ranked] == [0, 1, 2, 3]
    assert len({value for _, value in ranked}) == 1, "the fixture must actually tie"


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_an_empty_pool_ranks_nothing_rather_than_dividing_by_zero(name: str) -> None:
    fast_cls, _ = REFERENCES[name]
    assert fast_cls([]).rank("anything", limit=5) == []
    assert fast_cls([]).scores("anything") == []


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_a_document_with_no_terms_is_never_retrieved(name: str) -> None:
    """An empty document has a zero-length vector, and a cosine against it is
    undefined rather than zero. Both retrievers have to report it as unranked
    rather than as `nan`, which sorts unpredictably."""
    fast_cls, scan_cls = REFERENCES[name]
    documents = ["", "alpha beta", "", "alpha gamma"]
    fast, scan = fast_cls(list(documents)), scan_cls(list(documents))
    assert fast.rank("alpha", limit=5) == scan.rank("alpha", limit=5)
    assert all(not math.isnan(value) for value in fast.scores("alpha"))
    assert [position for position, _ in fast.rank("alpha", limit=5)] == [1, 3]


# ---------------------------------------------------------------------------
# 2. Real prose, and the verdicts that come off it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_scores_are_bit_identical_on_the_engines_own_passages(name: str, narrated_world: World) -> None:
    """The randomised corpora above stress the arithmetic; this asserts the same
    thing over text the corpus actually produces, including its tables — which
    carry number formatting, punctuation and repeated column labels that no
    synthetic fixture would think to generate."""
    fast_cls, scan_cls = REFERENCES[name]
    pool = passages(narrated_world)
    texts = [passage.text for passage in pool]
    assert len(texts) > 10, "the fixture must have something to retrieve from"
    fast, scan = fast_cls(list(texts)), scan_cls(list(texts))
    for case in narrated_world.evaluations:
        assert fast.scores(case.question) == scan.scores(case.question), case.id
        assert fast.rank(case.question, limit=5) == scan.rank(case.question, limit=5), case.id


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_every_case_gets_the_same_verdict_as_it_did_under_the_scan(
    name: str, narrated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identical pass/fail on **every case**, not identical totals.

    Two scorecards can agree on 194/3573 while disagreeing about which cases
    passed, and an aggregate-only check would call that a successful
    optimisation. Compared outcome by outcome, including the ``detail`` string
    — which quotes the top score to two decimals and the retrieved passage's
    authority, so it is a second, independent witness that the same passages
    came back in the same order.
    """
    _, scan_cls = REFERENCES[name]
    fast_card = score(narrated_world, retriever=name)

    # Swapped through `RETRIEVERS` rather than by calling a private hook:
    # `score()` looks the class up there and nowhere else, which is the
    # registration seam the module documents, so this exercises the real path.
    monkeypatch.setitem(RETRIEVERS, name, scan_cls)
    scan_card = score(narrated_world, retriever=name)

    assert len(fast_card.outcomes) == len(scan_card.outcomes)
    assert fast_card.outcomes == scan_card.outcomes
    # Stated separately so a failure says which invariant broke rather than
    # printing several thousand outcomes and leaving the reader to diff them.
    assert fast_card.passed == scan_card.passed
    assert fast_card.unreachable == scan_card.unreachable
    assert fast_card.by_type() == scan_card.by_type()


@pytest.mark.parametrize("name", sorted(REFERENCES))
@pytest.mark.parametrize("k", [1, 5, 10])
def test_a_top_k_call_agrees_with_a_top_1_call_about_the_top(
    name: str, k: int, narrated_world: World
) -> None:
    """What lets `score()` rank each case once instead of twice.

    The abstention floor is calibrated from ``rank(question, limit=1)`` and the
    grading uses ``rank(question, limit=k)`` — the same accumulation over the
    same postings, run again to read one number off the front. Fusing them is
    only sound if the two calls agree about the top element, *including* when
    the top score is zero: the `> 0.0` filter is applied per pair, so both must
    come back empty rather than one returning a zero-scored hit.

    Asserted on the score as well as the position, because the floor is built
    from the score and an equal-position/unequal-score pair would move the
    threshold for every abstention case in the corpus.
    """
    fast_cls, _ = REFERENCES[name]
    index = fast_cls([passage.text for passage in passages(narrated_world)])
    for case in narrated_world.evaluations:
        top_one = index.rank(case.question, limit=1)
        top_k = index.rank(case.question, limit=k)
        assert bool(top_one) == bool(top_k), case.id
        if top_one:
            assert top_one[0] == top_k[0], case.id

    # The zero-score branch, provoked rather than hoped for: the corpus need not
    # contain a question nothing answers, and that is the one case where "agree
    # about the top" means "agree there is no top".
    assert index.rank("zebra unicorn parliament", limit=1) == []
    assert index.rank("zebra unicorn parliament", limit=k) == []


def test_the_authority_index_reports_what_scanning_the_pool_reported(
    narrated_world: World,
) -> None:
    """The other quadratic in `score()`: the authority branch rebuilt
    ``[p for p in pool if set(case.expected_fact_ids) & p.fact_ids]`` per case,
    and the expected-fact set once per *passage*, since the `set(...)` sat
    inside the comprehension's condition.

    The replacement is an inverted fact index, and the two readings taken from
    it — a maximum authority rank and an emptiness test — have to agree with the
    scan for every case, which is asserted directly here rather than inferred
    from the verdicts agreeing.
    """
    pool = passages(narrated_world)
    by_fact: dict[str, list[int]] = {}
    for position, passage in enumerate(pool):
        for fact_id in passage.fact_ids:
            by_fact.setdefault(fact_id, []).append(position)

    checked = 0
    for case in narrated_world.evaluations:
        scanned = [p for p in pool if set(case.expected_fact_ids) & p.fact_ids]
        indexed = [
            pool[position].authority_rank
            for fact_id in case.expected_fact_ids
            for position in by_fact.get(fact_id, ())
        ]
        assert bool(scanned) == bool(indexed), case.id
        if scanned:
            assert max(p.authority_rank for p in scanned) == max(indexed), case.id
            checked += 1
    assert checked, "the fixture must have cases whose evidence is somewhere"


# ---------------------------------------------------------------------------
# 3. The structure that makes it fast, asserted rather than timed
# ---------------------------------------------------------------------------


def test_a_postings_list_holds_exactly_the_documents_carrying_the_term() -> None:
    """The whole speed-up rests on this: a query term reaches only the documents
    that contain it. Asserted against the documents directly, because a posting
    list that quietly included everything would still produce correct scores —
    every extra document would contribute a term frequency of zero — and would
    be a scan wearing an index's name.
    """
    documents = ["alpha beta", "beta gamma", "gamma delta", "alpha alpha delta"]
    index = Bm25(list(documents))
    for term in ("alpha", "beta", "gamma", "delta"):
        posting_indices, _ = index._postings[term]
        expected = [i for i, text in enumerate(documents) if term in tokens(text)]
        assert list(posting_indices) == expected, term
        # Ascending, and asserted rather than assumed: the accumulation order
        # per document is what makes the sums bit-identical, and it comes from
        # the build loop walking documents in order.
        assert list(posting_indices) == sorted(posting_indices)
    assert "zebra" not in index._postings


def test_a_rare_query_touches_a_small_fraction_of_a_large_pool() -> None:
    """The complexity claim, made as a count rather than as a stopwatch.

    A timed assertion on a shared CI box is a flake generator; the property the
    optimisation actually promises is that the work is proportional to the
    postings for the query's terms, not to the pool. That is countable.
    """
    documents = _corpus_shaped_documents(2000, seed=99)
    # One document given a term nothing else uses. Planted rather than found,
    # because whether a randomised corpus happens to contain a singleton term is
    # a property of the seed, and a test that silently stops exercising its
    # claim when a fixture is retuned is worse than no test.
    documents[1234] += " needlehaystack"
    index = Bm25(list(documents))

    touched = sum(len(index._postings[term][0]) for term in tokens("needlehaystack"))
    assert touched == 1, "a term in one document must reach one document"
    assert index.rank("needlehaystack", limit=5) == [
        (1234, index.scores("needlehaystack")[1234])
    ], "and must still retrieve exactly it"

    # The other end: boilerplate really does cover the pool, so the test above
    # is measuring selectivity rather than a corpus with no common terms in it.
    common = len(index._postings["reconciliation"][0])
    assert common > len(documents) * 0.5


def test_a_large_pool_and_many_queries_finish(narrated_world: World) -> None:
    """The shape that was 26 minutes at 11,264 artifacts: many cases against
    many passages. Not timed — this passes or hangs, and a regression to the
    scan makes it hang long enough to be noticed rather than subtly slow."""
    documents = _corpus_shaped_documents(4000, seed=7)
    index = Bm25(list(documents))
    for query in _queries(3) * 20:
        index.rank(query, limit=5)


def test_the_index_does_not_keep_a_second_copy_of_the_corpus() -> None:
    """The postings are the transpose of the per-document term counts, so
    holding both would store the same information twice — which at corpus scale
    is the difference between an index that fits in memory and one that does
    not. `_terms` was that second copy."""
    index = Bm25(["alpha beta", "beta gamma"])
    assert not hasattr(index, "_terms")
    assert not hasattr(TfIdf(["alpha beta", "beta gamma"]), "_vectors")
