"""Covering a space, and picking the points furthest apart in it.

Two well-understood primitives that this project needs in more than one place,
kept together because they compose: generate a set of candidates that covers a
space evenly, then take the few that are least like each other.

``halton`` is the covering. ``farthest_first`` is the picking. Neither knows
anything about worlds, documents, or parameters — they take coordinates and a
distance and hand back indices, which is what lets ``compiler.diversity`` use
them on document shapes and ``probe`` use them on whole consistent worlds
without either learning the other's vocabulary.

Both are deterministic and neither draws from an ``Rng``. That is not
incidental: a diversity mechanism seeded from the world seed would make "how
varied is this corpus" depend on which world you happened to build, and the
project's central claim is that the variety is *measured*, not hoped for.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

#: The first primes, one per dimension, as Halton bases. Beyond this many
#: dimensions the sequence's correlation between high-index bases makes it no
#: better than a grid, and a caller asking for more has a modelling problem
#: rather than a sampling one — so it raises instead of silently degrading.
_BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61,
          67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113)


def _radical_inverse(index: int, base: int) -> float:
    """``index`` written in ``base``, digits reflected about the point."""
    result = 0.0
    fraction = 1.0
    while index > 0:
        fraction /= base
        result += fraction * (index % base)
        index //= base
    return result


def halton(dimensions: int, count: int, *, skip: int = 1) -> tuple[tuple[float, ...], ...]:
    """*count* points in the unit hypercube, spread evenly rather than randomly.

    A low-discrepancy sequence, which is the right tool when the goal is
    *coverage* of a space rather than an unbiased sample of it. Uniform random
    points clump and leave holes — with a few hundred draws in six dimensions
    that is not a subtlety, it is most of the space unvisited — and here the
    points are candidate worlds, so a hole is a shape the corpus can never
    take.

    ``skip`` defaults to 1 rather than 0 because the zeroth point of every
    Halton sequence is the origin, and the origin maps to the low end of every
    single interval at once: a "world" in which every quantity simultaneously
    takes its minimum. It is a legitimate corner of the space and a terrible
    first candidate, and ``farthest_first`` starts from the first point it is
    given.
    """
    if dimensions < 1:
        raise ValueError(f"need at least one dimension, got {dimensions}")
    if dimensions > len(_BASES):
        raise ValueError(
            f"halton is defined here for up to {len(_BASES)} dimensions, asked for"
            f" {dimensions}; beyond that the high bases correlate and the sequence"
            " stops covering better than a grid"
        )
    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")
    return tuple(
        tuple(_radical_inverse(index, base) for base in _BASES[:dimensions])
        for index in range(skip, skip + count)
    )


def farthest_first(
    candidates: Sequence[T],
    distance: Callable[[T, T], float],
    count: int,
) -> tuple[int, ...]:
    """The *count* candidates least like each other, by max-min dispersion.

    Gonzalez's farthest-point traversal: take one, then repeatedly take
    whichever remaining candidate is furthest from everything taken so far.
    It is a 2-approximation to the max-min dispersion problem, which is
    NP-hard, and the approximation factor is tight — worth knowing before
    reading anything into a particular selection.

    Returns indices in selection order, so the caller keeps ownership of the
    candidate objects.

    Every tie resolves to the lowest index, and both places that happens are
    deliberate. The first pick has no selected set to be far from, so there is
    no distance-based reason to prefer any candidate and index 0 is chosen
    without inventing a preference the data does not support. Later picks use a
    strict ``>``, so the first candidate to reach the best score keeps it. Both
    matter more than they look: this runs inside a build whose output must be
    byte-identical on replay, and a tie broken by iteration order of a set
    would be a corpus that differed between runs of the same seed.
    """
    n = len(candidates)
    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")
    if count > n:
        raise ValueError(f"cannot select {count} candidate(s) from {n}")
    if count == 0:
        return ()

    selected: list[int] = [0]
    if count == 1:
        return (0,)

    nearest = [distance(candidates[0], candidates[i]) for i in range(n)]
    chosen = {0}
    while len(selected) < count:
        best_index, best_score = -1, -1.0
        for i in range(n):
            if i in chosen:
                continue
            if nearest[i] > best_score:
                best_score, best_index = nearest[i], i
        selected.append(best_index)
        chosen.add(best_index)
        for i in range(n):
            if i in chosen:
                continue
            candidate_distance = distance(candidates[best_index], candidates[i])
            if candidate_distance < nearest[i]:
                nearest[i] = candidate_distance

    return tuple(selected)


def manhattan(left: Sequence[float], right: Sequence[float]) -> float:
    """Sum of absolute differences, coordinate by coordinate.

    L1 rather than Euclidean because these coordinates are unrelated
    quantities — a margin and a reporting depth — normalised onto a common
    scale but not living in a common space. Squaring differences would let one
    wide dimension dominate the notion of "unlike", which is precisely what a
    diversity measure must not do.
    """
    return sum(abs(a - b) for a, b in zip(left, right, strict=True))


__all__ = ["farthest_first", "halton", "manhattan"]
