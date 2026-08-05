"""Set similarity at corpus scale, and choosing things that are unlike each other.

Two capabilities, one representation. A document is a set of token shingles;
everything below is a question about sets.

**Finding what repeats.** ``stats.py`` has always reported a near-duplicate
rate, computed by comparing every passage against every other one. Its
docstring defends the O(n²) as an acceptable price because "a corpus large
enough for that to matter is larger than anything this tool renders today" —
which was true, and is exactly the thing build-order §12 Gate 1 sets out to
stop being true. Ten thousand artifacts is fifty million pair comparisons of
set intersections, and it is the *scale* corpus, the one whose diversity claim
actually needs auditing, that would never get audited.

So :func:`near_duplicate_pairs` computes the **same answer** by a better
algorithm rather than a cheaper approximation of it. A prefix-filtered
similarity join (Chaudhuri, Ganti and Kaushik's operator, with the standard
Jaccard length and prefix bounds) enumerates every pair above the threshold
and provably misses none: two sets whose Jaccard reaches *t* must share an
element within their prefixes under any fixed global order, so the join can
skip every pair that shares nothing there without ever guessing. The exact
number a skeptical reader can recompute by hand survives; only the time taken
to get it changes. ``tests/test_similarity.py`` pins the agreement against
brute force rather than asserting it.

:class:`MinHash` and :class:`LshIndex` are here too, for the regime past that
one — a hundred thousand documents, where even a filtered exact join is too
much — and they are honestly labelled as approximate, with the recall the band
configuration actually implies. They are not the default, and the default is
not an accident.

The dispersion half of this work is deliberately *not* here.
``compiler/diversity.select`` is already farthest-point traversal over
document shapes, and a second implementation of Gonzalez's algorithm — one
over shingle sets, one over fingerprints — would be two things that could
disagree about what "as unlike each other as possible" means. The batch-level
gap that ``select`` genuinely leaves open (it spreads the alternatives *within*
one artifact; nothing spreads shapes *across* a batch) is closed by
``compiler.diversity.assign``, beside the distance function it has to share.

**Determinism**, the constraint every module here works under. The hashing is
``ids.content_key`` — SHA-256, the same function the generation ledger is
addressed by — never Python's randomised ``hash()``. The MinHash permutations
are universal hash coefficients derived from that same function, so a
signature is a pure function of the text and nothing else. numpy does the
permutation arithmetic because vectorised int64 modular arithmetic is exactly
what it is for, and integer arithmetic is bit-identical everywhere — unlike a
BLAS dot product, which is not, and which is why no float appears in a
signature. Every ordering breaks ties explicitly.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TypeVar

import numpy as np

from .ids import content_key

T = TypeVar("T")

#: The Mersenne prime the universal hash family is taken modulo. 2^31 - 1, not
#: something wider, and the reason is arithmetic rather than taste: the
#: permutation below computes ``a * base + b``, and numpy's int64 **wraps
#: silently on overflow** rather than raising or promoting. With a 61-bit
#: modulus that product needs 122 bits, so every signature would be computed
#: from a silently truncated intermediate — reproducible, since wrapping is
#: deterministic, but no longer the universal hash family the recall figures
#: assume. At 31 bits the product needs 62 and the arithmetic is exact.
_MERSENNE_31 = (1 << 31) - 1

#: Signature length. 128 rows is the usual accuracy/size trade for MinHash: the
#: standard error of the Jaccard estimate is 1/sqrt(rows), so ~9 points at 128.
#: Anything relying on more precision than that should be using the exact join
#: above it, which is the whole argument of this module.
SIGNATURE_ROWS = 128


# ---------------------------------------------------------------------------
# Shingles
# ---------------------------------------------------------------------------


def shingles(words: Sequence[str], size: int) -> frozenset[tuple[str, ...]]:
    """Token *size*-shingles of an already-tokenised text.

    Takes tokens rather than a string on purpose: the caller owns the
    tokenizer, and "near-duplicate" only means anything if it means the same
    thing to this module as it does to the retriever that would be confused by
    the duplication. ``stats.py`` passes ``evaluate.bm25.tokens``' output for
    exactly that reason.
    """
    if len(words) < size:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(
        tuple(words[i : i + size]) for i in range(len(words) - size + 1)
    )


def jaccard(a: frozenset[T], b: frozenset[T]) -> float:
    """Exact Jaccard similarity. ``0.0`` for two empty sets."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# The exact join
# ---------------------------------------------------------------------------


def near_duplicate_pairs(
    sets: Sequence[frozenset[T]], threshold: float
) -> tuple[tuple[int, int], ...]:
    """Every ``(i, j)`` with ``i < j`` whose Jaccard reaches *threshold*.

    Exact — the same pairs a full pairwise scan would return, and
    ``tests/test_similarity.py`` asserts that against brute force rather than
    taking this docstring's word for it. Two filters do the work, and both are
    sound (they can only skip pairs that provably cannot qualify):

    **Length.** ``|a ∩ b| ≤ min(|a|, |b|)`` and ``|a ∪ b| ≥ max(|a|, |b|)``, so
    Jaccard ``≥ t`` forces ``min ≥ t · max``. Sets are processed in size order,
    so the admissible partners of a set of size *n* are a contiguous run
    ``[t·n, n/t]``, and the scan can stop early rather than test and reject.

    **Prefix.** Under any fixed global order on elements, two sets that reach
    the threshold must share an element within their prefixes of length
    ``|s| - ceil(t·|s|) + 1``. The global order used here is *rarest element
    first* — ordering by document frequency puts the discriminating shingles in
    the prefixes and the boilerplate ("for the period", "business unit") out of
    them, which is what makes the candidate set small on exactly the corpora
    this exists for, where every document shares a header.

    ``threshold`` must be positive; at zero every pair qualifies and the
    filters degenerate, so the caller wanted a full scan and should say so.
    """
    if not 0.0 < threshold <= 1.0:
        raise ValueError(f"threshold must be in (0, 1], not {threshold}")
    if len(sets) < 2:
        return ()

    frequency: dict[T, int] = {}
    for members in sets:
        for element in members:
            frequency[element] = frequency.get(element, 0) + 1

    # Rarest first, ties broken on the element itself so the order is a
    # function of the data and not of dict insertion.
    def rank(element: T) -> tuple[int, str]:
        return (frequency[element], str(element))

    ordered = [sorted(members, key=rank) for members in sets]
    # Index positions by size so the length filter is a range rather than a
    # test applied to everything.
    by_size = sorted(range(len(sets)), key=lambda i: (len(sets[i]), i))

    postings: dict[T, list[int]] = {}
    found: set[tuple[int, int]] = set()

    for index in by_size:
        members = sets[index]
        size = len(members)
        if size == 0:
            continue
        prefix_length = size - math.ceil(threshold * size) + 1
        candidates: set[int] = set()
        for element in ordered[index][:prefix_length]:
            for other in postings.get(element, ()):
                # Sets are visited smallest first, so anything already indexed
                # is no larger than this one; the length filter reduces to a
                # single lower bound.
                if len(sets[other]) >= threshold * size:
                    candidates.add(other)
        for other in candidates:
            if jaccard(members, sets[other]) >= threshold:
                found.add((min(index, other), max(index, other)))
        for element in ordered[index][:prefix_length]:
            postings.setdefault(element, []).append(index)

    return tuple(sorted(found))


def clusters(pairs: Iterable[tuple[int, int]], total: int) -> tuple[tuple[int, ...], ...]:
    """Connected components of the near-duplicate graph, singletons dropped.

    A *rate* says a corpus repeats itself; a *cluster* says which eleven
    documents are the same document. That is the difference between a metric
    and a finding, and the finding is what an author acts on.
    """
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(range(total))
    graph.add_edges_from(sorted(pairs))
    groups = [
        tuple(sorted(component))
        for component in nx.connected_components(graph)
        if len(component) > 1
    ]
    return tuple(sorted(groups, key=lambda group: (-len(group), group)))


# ---------------------------------------------------------------------------
# The approximate path, for the scale past the exact one
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _coefficients(rows: int) -> tuple[np.ndarray, np.ndarray]:
    """Universal hash coefficients ``(a, b)``, derived from ``content_key``.

    Not drawn from a random number generator, seeded or otherwise: a signature
    has to be a pure function of the text so that two corpora built in
    different processes compare against each other, and a seeded RNG makes it a
    function of the text *and* of which stream the caller happened to pass.
    """
    a = np.empty(rows, dtype=np.int64)
    b = np.empty(rows, dtype=np.int64)
    for row in range(rows):
        # `a` must be non-zero for the family to be universal; the modulus is
        # prime, so any non-zero residue works.
        a[row] = (int(content_key("minhash/a", row), 16) % (_MERSENNE_31 - 1)) + 1
        b[row] = int(content_key("minhash/b", row), 16) % _MERSENNE_31
    return a, b


@dataclass(frozen=True)
class MinHash:
    """Signatures for a corpus of sets, and Jaccard estimates between them.

    Approximate, and the approximation is the reason to reach for it: signature
    comparison is O(rows) per pair regardless of how long the documents are,
    which is what makes a hundred thousand documents tractable at all. Use
    :func:`near_duplicate_pairs` unless the corpus is past the scale that can
    afford an exact answer — the estimate's standard error is ``1/sqrt(rows)``,
    about nine points at the default, and nine points either side of a 0.8
    threshold is a materially different set of documents.
    """

    rows: int = SIGNATURE_ROWS

    def signature(self, members: frozenset[T]) -> np.ndarray:
        """The MinHash signature of one set, as ``rows`` int64 values."""
        a, b = _coefficients(self.rows)
        if not members:
            return np.full(self.rows, _MERSENNE_31, dtype=np.int64)
        # One SHA-256 per element, then `rows` cheap universal hashes of that
        # — rather than `rows` SHA-256s per element, which is the naive shape
        # and is `rows` times slower for the same signature.
        base = np.array(
            [int(content_key(element), 16) % _MERSENNE_31 for element in sorted(members, key=str)],
            dtype=np.int64,
        )
        # int64 modular arithmetic: exact, and identical on every platform.
        # A float dot product would not be, which is why this is written as
        # integers rather than as the matrix multiply it superficially is.
        permuted = (a[:, None] * base[None, :] + b[:, None]) % _MERSENNE_31
        return permuted.min(axis=1)

    def estimate(self, left: np.ndarray, right: np.ndarray) -> float:
        """The estimated Jaccard between two signatures."""
        return float(np.count_nonzero(left == right)) / self.rows


@dataclass(frozen=True)
class LshIndex:
    """Banded locality-sensitive hashing over MinHash signatures.

    A signature is cut into ``bands`` bands of ``rows_per_band`` rows; two
    documents are candidates if any whole band matches. The probability that a
    pair at similarity *s* becomes a candidate is ``1 - (1 - s**r)**b``, which
    is the S-curve the band configuration *is*: :meth:`recall_at` computes it,
    so a caller can state the recall rather than assume it.
    """

    bands: int = 16
    rows_per_band: int = 8

    def __post_init__(self) -> None:
        if self.bands * self.rows_per_band > SIGNATURE_ROWS:
            raise ValueError(
                f"{self.bands} bands x {self.rows_per_band} rows exceeds the "
                f"{SIGNATURE_ROWS}-row signature"
            )

    def recall_at(self, similarity: float) -> float:
        """The probability a pair at *similarity* is surfaced as a candidate."""
        return 1.0 - (1.0 - similarity ** self.rows_per_band) ** self.bands

    def candidates(self, signatures: Sequence[np.ndarray]) -> tuple[tuple[int, int], ...]:
        """Candidate pairs — everything sharing a whole band, deduplicated."""
        buckets: dict[str, list[int]] = {}
        for index, signature in enumerate(signatures):
            for band in range(self.bands):
                start = band * self.rows_per_band
                rows = signature[start : start + self.rows_per_band]
                key = content_key(band, *(int(value) for value in rows))
                buckets.setdefault(key, []).append(index)
        pairs: set[tuple[int, int]] = set()
        for members in buckets.values():
            for position, left in enumerate(members):
                for right in members[position + 1 :]:
                    pairs.add((min(left, right), max(left, right)))
        return tuple(sorted(pairs))


__all__ = [
    "LshIndex",
    "MinHash",
    "SIGNATURE_ROWS",
    "clusters",
    "jaccard",
    "near_duplicate_pairs",
    "shingles",
]
