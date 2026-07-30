"""BM25, written out rather than imported.

Forty lines and no dependency, because this is the *floor* — the point is not to
retrieve well, it is to establish what a system with no notion of time,
authority or provenance can already get right. A baseline that pulled in a
sentence-transformer would measure the embedding model; this measures the corpus.

Deliberately blind to everything the manifest knows. Every question type this
scores badly on is a question type the corpus makes genuinely hard.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

_TOKEN = re.compile(r"[a-z0-9]+")

#: Standard BM25 parameters. Not tuned — a tuned baseline is no longer a floor.
K1 = 1.5
B = 0.75


def tokens(text: str) -> list[str]:
    """Lowercase alphanumeric runs. No stemming, no stop list, no cleverness."""
    return _TOKEN.findall(text.casefold())


@dataclass
class Bm25:
    """A BM25 index over a fixed set of documents."""

    documents: list[str]
    _terms: list[Counter] = field(default_factory=list)
    _lengths: list[int] = field(default_factory=list)
    _idf: dict[str, float] = field(default_factory=dict)
    _average: float = 0.0

    def __post_init__(self) -> None:
        self._terms = [Counter(tokens(document)) for document in self.documents]
        self._lengths = [sum(counts.values()) for counts in self._terms]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

        seen: Counter = Counter()
        for counts in self._terms:
            seen.update(counts.keys())
        total = len(self._terms)
        for term, appearances in seen.items():
            # The +0.5 smoothing that keeps a term appearing in every document
            # from scoring negative.
            self._idf[term] = math.log(1 + (total - appearances + 0.5) / (appearances + 0.5))

    def scores(self, query: str) -> list[float]:
        """A score per document, in document order."""
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
        """The *limit* best documents as ``(index, score)``, best first.

        Ties break on index so a run is reproducible — two passages scoring
        identically must not swap places between runs.
        """
        scored = list(enumerate(self.scores(query)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [pair for pair in scored[:limit] if pair[1] > 0.0]
