"""TF-IDF cosine, the second ranking family.

`bm25.py` is already this repository's baseline, and it already *is* BM25 —
reading it before writing this file is what caught that a literal second BM25
would not be a second anything, just the first one with a spare copy of its own
docstring. The gap this file exists to close is a **ranking family** gap, not a
"try another set of textbook constants" gap: `score.py`'s credibility argument
("a family low under both retrievers is structurally hard, not hard for one
heuristic") only holds if the two heuristics can fail for different reasons, and
two BM25 instances fail for the same reason by construction.

BM25 is the probabilistic-relevance family: term frequency saturates (a term's
tenth occurrence barely outscores its fifth) inside a formula tuned to
approximate "probability this document is relevant", and length is normalised
multiplicatively against the corpus's average document length (`B` in
`bm25.py`). Vector-space cosine is a different family on every one of those
axes: term frequency is log-damped rather than saturating (`1 + log(tf)`, the
classic `ltc` weighting — a different nonlinearity, not a retuning of the same
one), length normalisation is the Euclidean norm of the document's own vector
rather than a ratio to the corpus average, and the ranking score itself is an
angle between two vectors instead of a sum of per-term relevance
contributions. Two documents can therefore disagree on which the "more
relevant" one is even when both index the identical bag of words — which is
the entire point of running both: where they *agree* that a family is hard,
no amount of swapping the ranking heuristic fixes it.

Tokenisation is imported from `bm25.py` rather than redefined here, on purpose:
if the two retrievers tokenised differently, a disagreement between them could
be an artifact of preprocessing rather than of ranking, and the credibility
argument needs the *only* difference between them to be the ranking math.
"""

from __future__ import annotations

import heapq
import math
from array import array
from collections import Counter
from dataclasses import dataclass, field

from .bm25 import tokens


@dataclass
class TfIdf:
    """A TF-IDF vector-space index over a fixed set of documents.

    Same shape as `Bm25` (`documents` in, `.rank(query, limit=)` out) on purpose
    — `score.py` and the CLI hold a retriever behind one name, and the only
    thing that should distinguish `--retriever bm25` from `--retriever tfidf` is
    which class gets constructed.

    Inverted for the same reason `Bm25` is, and with the same bit-identity
    obligation — see that class's docstring for the argument in full. The one
    difference worth stating here is what a posting can carry: BM25's per-term
    contribution to a document is fully determined at build time, so its
    postings hold finished numbers, whereas a cosine's contribution is
    ``query_weight × document_weight`` and only half of that product exists
    before a query arrives. So these postings hold the document's own term
    weight and the query weight is applied at query time — the same
    multiplication the scan version did, moved rather than removed.
    """

    documents: list[str]
    _norms: list[float] = field(default_factory=list)
    _idf: dict[str, float] = field(default_factory=dict)
    _postings: dict[str, tuple[array, array]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        term_counts = [Counter(tokens(document)) for document in self.documents]

        document_frequency: Counter[str] = Counter()
        for counts in term_counts:
            document_frequency.update(counts.keys())

        total = len(term_counts)
        # Smooth ("probabilistic-free") idf: log((1+N)/(1+df)) + 1. Every term
        # gets a strictly positive weight, including one appearing in every
        # document — unlike BM25's +0.5 smoothing (see `bm25.py`), which is
        # allowed to go slightly negative for a term that common. That +1 floor
        # is deliberate: a cosine of two all-zero-weight vectors is undefined,
        # and a corpus small enough that some term appears everywhere should not
        # silently turn every document invisible to the index.
        self._idf = {
            term: math.log((1 + total) / (1 + df)) + 1
            for term, df in document_frequency.items()
        }

        norms: list[float] = []
        indices: dict[str, array] = {}
        weights: dict[str, array] = {}
        for index, counts in enumerate(term_counts):
            vector = {
                # `1 + log(tf)`: the "l" (logarithmic) weighting from SMART's ltc
                # scheme. A term's fifth occurrence adds much less than its
                # first — damped, not saturated like BM25's `(k1+1)*tf/(tf+...)`
                # — so a document that repeats one keyword cannot out-rank one
                # that uses a broader relevant vocabulary once.
                term: (1 + math.log(frequency)) * self._idf[term]
                for term, frequency in counts.items()
            }
            norms.append(math.sqrt(sum(weight * weight for weight in vector.values())))
            # The norm is computed from the document's whole vector before the
            # vector is transposed away, because it is a property of the
            # document and there is no cheap way back to it from the postings.
            for term, weight in vector.items():
                if term not in indices:
                    indices[term] = array("i")
                    weights[term] = array("d")
                indices[term].append(index)
                weights[term].append(weight)
        self._norms = norms
        # Ascending document order, from walking the documents in order — no
        # sort, and nothing here iterates a set.
        self._postings = {term: (indices[term], weights[term]) for term in indices}

    def _query_vector(self, query: str) -> tuple[dict[str, float], float]:
        """The query as a weighted vector and its norm, exactly as the scan
        version built it — including the insertion order, which is the order
        the dot products below accumulate in and therefore part of the answer."""
        query_counts = Counter(tokens(query))
        query_vector = {
            term: (1 + math.log(frequency)) * self._idf[term]
            for term, frequency in query_counts.items()
            if term in self._idf  # a query term never seen in the corpus has no idf and no signal
        }
        return query_vector, math.sqrt(sum(weight * weight for weight in query_vector.values()))

    def scores(self, query: str) -> list[float]:
        """Cosine similarity between *query* and each document, in document order."""
        query_vector, query_norm = self._query_vector(query)
        out = [0.0] * len(self._norms)
        if not query_norm:
            return out
        # Each document accumulates its dot product over the query's terms in
        # `query_vector` order — the same order the per-document scan used, so
        # the same double. Terms the document lacks are skipped rather than
        # added as `weight * 0.0`; every weight here is strictly positive (idf
        # is floored at 1 above and `1 + log(tf)` at 1), so no partial sum is
        # ever negative zero and dropping the zeros is exact.
        for term, weight in query_vector.items():
            posting = self._postings.get(term)
            if posting is None:
                continue
            for index, document_weight in zip(*posting):
                out[index] += weight * document_weight
        return [
            (dot / (query_norm * norm)) if norm else 0.0
            for dot, norm in zip(out, self._norms)
        ]

    def rank(self, query: str, *, limit: int) -> list[tuple[int, float]]:
        """The *limit* best documents as ``(index, score)``, best first.

        Same tie-break as `Bm25.rank`: ties break on index so a run is
        reproducible rather than depending on Python's sort stability plus
        floating-point coincidence. And the same sparse accumulate plus heap,
        for the same reason — see `Bm25.rank`.
        """
        query_vector, query_norm = self._query_vector(query)
        if not query_norm:
            return []
        dots: dict[int, float] = {}
        for term, weight in query_vector.items():
            posting = self._postings.get(term)
            if posting is None:
                continue
            for index, document_weight in zip(*posting):
                dots[index] = dots.get(index, 0.0) + weight * document_weight
        norms = self._norms
        candidates = [
            (-(dot / (query_norm * norms[index])), index)
            for index, dot in dots.items()
            if norms[index]
        ]
        return [
            (index, -negated)
            for negated, index in heapq.nsmallest(limit, candidates)
            if -negated > 0.0
        ]
