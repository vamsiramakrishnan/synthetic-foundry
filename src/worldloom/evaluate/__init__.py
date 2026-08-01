"""Scoring a corpus against its own evaluation set.

The existential question for a synthetic corpus is not whether it is coherent —
that is what ``validate`` answers — but whether it *discriminates*. A corpus on
which a keyword baseline scores ninety-five per cent tells you nothing about the
system under test, however beautifully it reconciles.

So this ships two floors, not one: BM25 (`bm25.py`), the original baseline, and
TF-IDF cosine (`tfidf.py`), a genuinely different ranking family — probabilistic
relevance versus vector-space, saturating term frequency versus log-damped, see
`tfidf.py`'s docstring for the rest. Neither has any notion of time, authority,
or provenance. A good result is a *bad* score on the question types the corpus
exists to pose, from **both** — a family that only one of the two fails is a
finding about that heuristic, not about the corpus; a family both fail is
structurally hard. `compare()` makes that reading explicit.

**Retrieval is graded, not generation.** An expected answer is free text and
grading text against text needs a judge, which would put a model inside the
measurement. But the manifest already records which facts each artifact carries,
who wrote it, when, and with what authority — so "did you surface a document
carrying the fact this answer rests on" is objective, reproducible, and needs
nothing but the corpus.
"""

from __future__ import annotations

from .bm25 import Bm25
from .index import Passage, document_texts, passages
from .score import (
    DEFAULT_RETRIEVER,
    RETRIEVERS,
    FamilyAgreement,
    Outcome,
    Scorecard,
    compare,
    render_agreement,
    score,
)
from .tfidf import TfIdf

__all__ = [
    "Bm25",
    "TfIdf",
    "Passage",
    "passages",
    "document_texts",
    "Outcome",
    "Scorecard",
    "FamilyAgreement",
    "RETRIEVERS",
    "DEFAULT_RETRIEVER",
    "score",
    "compare",
    "render_agreement",
]
