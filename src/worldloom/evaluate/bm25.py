"""BM25, written out rather than imported.

Forty lines and no dependency, because this is the *floor* — the point is not to
retrieve well, it is to establish what a system with no notion of time,
authority or provenance can already get right. A baseline that pulled in a
sentence-transformer would measure the embedding model; this measures the corpus.

Deliberately blind to everything the manifest knows. Every question type this
scores badly on is a question type the corpus makes genuinely hard.
"""

from __future__ import annotations

import heapq
import math
import re
from array import array
from collections import Counter
from dataclasses import dataclass, field

_TOKEN = re.compile(r"[a-z0-9]+")

#: Standard BM25 parameters. Not tuned — a tuned baseline is no longer a floor.
K1 = 1.5
B = 0.75


def tokens(text: str) -> list[str]:
    """Lowercase alphanumeric runs. No stemming, no stop list, no cleverness."""
    return _TOKEN.findall(text.casefold())


#: One term's postings: the documents containing it, ascending, and this
#: index's contribution to each of their scores. Two parallel `array`s rather
#: than a list of ``(index, contribution)`` tuples because the whole point of
#: the structure is to be affordable at corpus scale, and the tuple form is not:
#: a 30,000-passage corpus carries a few million postings, which is ~240 MB as
#: boxed tuples-of-boxed-numbers and ~36 MB as ``'i'``/``'d'`` arrays. Storing a
#: Python float into an ``'d'`` array and reading it back is exact — both are
#: IEEE-754 doubles — so this costs nothing in fidelity.
_Postings = tuple[array, array]


@dataclass
class Bm25:
    """A BM25 index over a fixed set of documents.

    **Inverted, not scanned.** The obvious implementation scores every document
    for every query, which is what this was and what made `worldloom evaluate`
    the slowest thing in the tool: cases and passages both grow linearly with
    the corpus, so the product grows quadratically, and a 48-period retail
    corpus spent 16.7 of its 19 seconds inside the old `scores` loop across 39
    million `dict.get` calls — most of them asking a document about a term it
    does not contain. A posting list per term asks only the documents that
    could score at all.

    A document's contribution for a term depends on nothing but that term and
    that document — term frequency, document length, corpus average length and
    idf are all fixed once the index is built — so the contribution is computed
    at build time and the query loop is left with additions. That is the whole
    speed-up; the ranking is arithmetically the same one.

    **Bit-identical, not merely close.** A performance fix that changes an
    answer is a bug, not a speed-up, and here the risk is specifically
    floating-point: a sum of the same terms in a different order is a different
    double. The old loop was ``for document: for term in query: total +=``, so
    each document accumulated its terms in query order. This loop is ``for term
    in query: for document in postings:``, and each document *still* accumulates
    its terms in query order — the nesting is inverted, the per-document
    addition sequence is not. `tests/test_evaluate_scale.py` pins that: identical
    scores, identical rankings, identical per-case verdicts against the previous
    implementation on real corpora.
    """

    documents: list[str]
    _lengths: list[int] = field(default_factory=list)
    _idf: dict[str, float] = field(default_factory=dict)
    _average: float = 0.0
    _postings: dict[str, _Postings] = field(default_factory=dict)

    def __post_init__(self) -> None:
        term_counts = [Counter(tokens(document)) for document in self.documents]
        self._lengths = [sum(counts.values()) for counts in term_counts]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

        seen: Counter = Counter()
        for counts in term_counts:
            seen.update(counts.keys())
        total = len(term_counts)
        for term, appearances in seen.items():
            # The +0.5 smoothing that keeps a term appearing in every document
            # from scoring negative.
            self._idf[term] = math.log(1 + (total - appearances + 0.5) / (appearances + 0.5))

        # `term_counts` is deliberately *not* kept on the instance. It used to
        # be (`_terms`), and holding both it and the postings would double the
        # index's footprint to store the same information twice — the postings
        # are the transpose of it, and nothing outside this build loop ever
        # needed the per-document view.
        indices: dict[str, array] = {}
        contributions: dict[str, array] = {}
        average = self._average or 1
        for index, counts in enumerate(term_counts):
            length = self._lengths[index] or 1
            # Hoisted out of the term loop, where the scan version recomputed it
            # per term. Same expression, same operand order, so the same double
            # — hoisting a loop-invariant is not a re-association.
            saturation = K1 * (1 - B + B * length / average)
            for term, frequency in counts.items():
                # Written in the operand order the scan version used, character
                # for character, because that is what makes the two bit-equal:
                # `(idf * frequency) * (K1 + 1) / denominator` and
                # `idf * (frequency * (K1 + 1)) / denominator` are different
                # doubles, and only one of them is the answer this repository
                # has always given.
                contribution = self._idf[term] * frequency * (K1 + 1) / (frequency + saturation)
                if term not in indices:
                    indices[term] = array("i")
                    contributions[term] = array("d")
                indices[term].append(index)
                contributions[term].append(contribution)
        # Documents are appended in ascending index because the loop above walks
        # them in order — no sort, and nothing here iterates a set.
        self._postings = {term: (indices[term], contributions[term]) for term in indices}

    def scores(self, query: str) -> list[float]:
        """A score per document, in document order."""
        out = [0.0] * len(self._lengths)
        for term in tokens(query):
            posting = self._postings.get(term)
            if posting is None:
                continue
            for index, contribution in zip(*posting):
                out[index] += contribution
        return out

    def rank(self, query: str, *, limit: int) -> list[tuple[int, float]]:
        """The *limit* best documents as ``(index, score)``, best first.

        Ties break on index so a run is reproducible — two passages scoring
        identically must not swap places between runs.

        Accumulates sparsely and takes the top *limit* with a heap rather than
        materialising a score for every document and sorting the lot. Both
        halves matter at scale and for the same reason: a query names a handful
        of terms, so all but a fraction of the pool scores exactly zero, and
        both the zero and its place in a full sort are work spent to discover
        that a document was never a candidate. The zeros are not lost — the
        filter below drops them anyway, and the old full sort put them last,
        because every posting contributes a positive score (`_idf` is strictly
        positive under the +0.5 smoothing above, so no document with a matching
        term can score down into the discarded band).
        """
        accumulated: dict[int, float] = {}
        for term in tokens(query):
            posting = self._postings.get(term)
            if posting is None:
                continue
            for index, contribution in zip(*posting):
                accumulated[index] = accumulated.get(index, 0.0) + contribution
        # Ranked on `(-score, index)` ascending — the exact key the full sort
        # this replaces used, so the resulting order is the same one, not a
        # near-enough one. Negation is exact for finite doubles and reverses the
        # order, and indices are unique, so the comparison is total and the heap
        # has no tie left to break by accident.
        #
        # `nsmallest` over pre-negated pairs rather than `nlargest(..., key=)`
        # on purpose: the keyed form calls `key` once per candidate, which on
        # this workload was three million Python-level lambda invocations and
        # about a third of the whole command's remaining time. A plain tuple
        # comparison stays in C.
        candidates = [(-score, index) for index, score in accumulated.items()]
        return [
            (index, -negated)
            for negated, index in heapq.nsmallest(limit, candidates)
            if -negated > 0.0
        ]
