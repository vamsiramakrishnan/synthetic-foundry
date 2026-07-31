"""Scoring a corpus against its own evaluation set.

The existential question for a synthetic corpus is not whether it is coherent —
that is what ``validate`` answers — but whether it *discriminates*. A corpus on
which a keyword baseline scores ninety-five per cent tells you nothing about the
system under test, however beautifully it reconciles.

So this ships the floor: a BM25 retriever with no notion of time, authority or
provenance, and a scorer that reports where it succeeds and where it fails. A
good result here is a *bad* score on the question types the corpus exists to
pose. If the baseline answers temporal-state and authority-resolution questions
as easily as direct lookups, the corpus is not hard and the honest thing is to
know that.

**Retrieval is graded, not generation.** An expected answer is free text and
grading text against text needs a judge, which would put a model inside the
measurement. But the manifest already records which facts each artifact carries,
who wrote it, when, and with what authority — so "did you surface a document
carrying the fact this answer rests on" is objective, reproducible, and needs
nothing but the corpus.
"""

from __future__ import annotations

from .bm25 import Bm25
from .index import Passage, passages
from .score import Outcome, Scorecard, score

__all__ = ["Bm25", "Passage", "passages", "Outcome", "Scorecard", "score"]
