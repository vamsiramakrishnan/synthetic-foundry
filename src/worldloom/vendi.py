"""Diversity as an effective count, not a count of distinct things.

Every diversity number this project publishes about *structure* is a count of
distinct shapes — `compiler.diversity.DiversityReport.distinct_digests`, and
the headline it produces: "33 distinct heading sequences across 42 artifact
types". A count answers "how many shapes are there" and is structurally unable
to answer "how many *different* shapes are there", because it grades every
pair of shapes as either the same or not. Thirty near-identical outlines that
differ by one heading count as thirty, and a reader who opens any four of them
has seen one document.

`stats.py` already found the same hole on the prose side and closed it with a
second reading beside the first (`near_duplicate_share` beside
`near_duplicate_rate`, because the rate saturates at 1/K and says so with the
arithmetic). This is that move applied to shape: a number that reads as **the
effective number of unique elements in the sample**, computed from a
similarity function rather than from an equality test, so "differs by one
heading" contributes a fraction of an element rather than a whole one.

The Vendi Score (Friedman & Dieng, *The Vendi Score: A Diversity Evaluation
Metric for Machine Learning*, TMLR 2023) is the exponential of the Shannon
entropy of the eigenvalues of the similarity matrix normalised by *n*. Its
governing property is the one that makes it worth having here: it is invariant
to replicating the whole sample, so a corpus built for twelve periods instead
of three does not report itself four times more diverse for having stamped
every template four times more often — the failure
`DiversityReport.ngram_entropy_bits` documents at 4.12 bits on both a
12-period and a 48-period corpus, arrived at from the other direction.

Measured on this repository's own ``documents._OUTLINES``, taking each outline
as its heading sequence and a bigram-Jaccard kernel over adjacent headings
(the ``_NGRAM_SIZE = 2`` argument `compiler.diversity` already makes — bigrams
are the smallest window that sees adjacency, and adjacency is what "the same
outline every time" repeats): **42 outlines, 33 distinct heading sequences,
Vendi score 24.19**. Nine of the forty-two are exact repeats and the count
prices them at zero; the remaining gap between 33 and 24.2 is the near-repeats
the count cannot see at all.

Worth knowing where that leaves the existing number: the same matrix read at
Rényi order ``q = 0`` returns **exactly 33**. The distinct-shape count this
repository already publishes is not a different measurement, it is the most
generous member of this family — the one that asks how many directions the
sample occupies and refuses to ask how much of it is in each. ``q = 1`` asks
the second question and ``q = inf`` (4.20 here) asks only about the dominant
mode. Quoting a bracket rather than a point is the honest reading.

**The similarity function is an argument, and that is the point.** This
repository has several defensible notions of "similar" — `similarity.jaccard`
over text shingles, `compiler.diversity.distance` over structure — and each
deserves its own effective count rather than one of them being promoted to
*the* diversity number.

**A kernel, not any similarity function.** The eigenvalues are read as a
probability distribution, so the matrix has to be a positive semi-definite
kernel with a unit diagonal. Both halves are checked and both refuse rather
than return a plausible wrong figure: a diversity score nobody can tell is
wrong is worse than no diversity score. The second half has teeth — ``1 -
normalised Levenshtein`` is a perfectly reasonable-looking similarity and is
*not* PSD in general (measured: eigenvalues to -0.021 over random short
sequences), even though it happens to be PSD on the 42 outlines above. Jaccard
over shingle sets is a kernel; a metric turned into a similarity by
subtraction is not one unless you check.

**Determinism, and the one caveat this module carries.** Nothing here draws
randomness, reads a clock or iterates a set; the score is a pure function of
the matrix. But `numpy.linalg.eigvalsh` is a LAPACK call, and unlike the
integer arithmetic `similarity.py` deliberately confines its MinHash to, its
last bits are not guaranteed identical across BLAS builds. This is a
*reading*, and it must stay one: a generator that branched on a Vendi score
would make a corpus's bytes depend on which LAPACK the machine linked, which
is precisely the class of defect the determinism sweep exists to catch. Report
it, print it, gate CI on it with a tolerance — do not feed it back into a
build.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TypeVar

import numpy as np

T = TypeVar("T")

#: How far a diagonal entry may sit from 1.0 before the matrix is refused. Not
#: zero: a cosine similarity of a normalised vector with itself lands a few
#: ULPs off 1.0 and is a legitimate kernel. Wide enough to admit that, far too
#: narrow to admit a similarity function that forgot the identity case — which
#: is the failure this guards, because a diagonal of 0.9 silently shrinks every
#: eigenvalue and reports a *lower* diversity for the same sample.
_DIAGONAL_TOLERANCE = 1e-9

#: How far ``K[i, j]`` may sit from ``K[j, i]``. An asymmetric matrix is
#: refused rather than symmetrised as ``(K + K.T) / 2``: the average of two
#: disagreeing similarities is a number neither caller asked for, and the
#: disagreement is nearly always a bug in the similarity function that the
#: symmetrisation would hide for good.
_SYMMETRY_TOLERANCE = 1e-9

#: Per-dimension width of the band around zero that counts as floating-point
#: noise rather than signal. Scaled by *n* rather than fixed, because LAPACK's
#: backward error grows with the dimension: a fixed 1e-12 is right at n=42 and
#: starts refusing genuine kernels somewhere in the thousands, which is exactly
#: the corpus scale this reading is for. Real violations are not close to this
#: — the Levenshtein case in the module docstring is 1e10 times larger.
#:
#: Applied in **both** directions, and the positive half is not symmetry for
#: its own sake. A rank-deficient kernel — which is any sample containing an
#: exact duplicate, so, every corpus — comes back from ``eigvalsh`` with its
#: structural zeros scattered across ``±1e-17`` rather than at zero. Clamping
#: only the negative half leaves the positive dust standing, and ``order=0``,
#: whose whole definition is "how many eigenvalues are non-zero", then counts
#: it: measured on this repository's 42 outlines, **38** where the true rank is
#: 33. The Shannon default hides this (``p log p`` at 1e-17 is nothing), which
#: is exactly why it is worth a constant and a comment rather than a `> 0`.
_EIGENVALUE_NOISE = 1e-12

#: Orders this close to 1 are computed as Shannon. The general Rényi form
#: divides by ``1 - q``, so at q = 1.000000001 it is arithmetically correct and
#: numerically worthless; the limit as q -> 1 *is* Shannon, so taking the limit
#: is not an approximation of the answer, it is the answer.
_ORDER_ONE_TOLERANCE = 1e-9


def _spectrum(similarity: np.ndarray) -> np.ndarray:
    """Validated eigenvalues of ``K / n`` — a probability distribution.

    The normalisation by *n* is what makes the score readable as a count, and
    it is worth stating the bound it buys: the diagonal is 1, so
    ``trace(K / n) == 1`` and the eigenvalues sum to 1. All the mass on one
    eigenvalue gives a score of 1 (every element the same element); mass spread
    evenly over all *n* gives exactly *n* (no two elements alike). The score is
    therefore bounded in ``[1, n]``, and a caller can compare it against the
    sample size directly. Skip the normalisation and the eigenvalues sum to *n*
    instead, which produces a number that grows with the sample and answers no
    question at all.

    ``eigvalsh``, never ``eigvals``: the matrix is symmetric by the check
    above, and the general routine returns complex dtypes in unspecified order
    for it — so the entropy sum would be over an arbitrary permutation of
    values carrying zero imaginary parts, which works until one of them does
    not.
    """
    matrix = np.asarray(similarity, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError(
            f"similarity must be a square matrix, got shape {matrix.shape}"
        )
    n = int(matrix.shape[0])
    if n == 0:
        return np.zeros(0, dtype=float)
    if not np.isfinite(matrix).all():
        raise ValueError(
            "similarity matrix holds a non-finite value; a nan or inf here"
            " propagates into every eigenvalue and the score comes back nan"
        )

    diagonal = np.diagonal(matrix)
    diagonal_error = np.abs(diagonal - 1.0)
    worst = int(diagonal_error.argmax())
    if diagonal_error[worst] > _DIAGONAL_TOLERANCE:
        raise ValueError(
            f"similarity must be 1.0 on the diagonal; entry {worst} is"
            f" {float(diagonal[worst])!r}. An element is not fully similar to"
            " itself, so this is not a similarity function the Vendi score is"
            " defined for"
        )

    asymmetry = np.abs(matrix - matrix.T)
    if float(asymmetry.max()) > _SYMMETRY_TOLERANCE:
        i, j = (int(x) for x in np.unravel_index(int(asymmetry.argmax()), asymmetry.shape))
        raise ValueError(
            f"similarity must be symmetric; K[{i}, {j}] = {float(matrix[i, j])!r}"
            f" but K[{j}, {i}] = {float(matrix[j, i])!r}"
        )

    eigenvalues = np.linalg.eigvalsh(matrix / n)
    noise = _EIGENVALUE_NOISE * n
    smallest = float(eigenvalues.min())
    if smallest < -noise:
        raise ValueError(
            f"similarity is not a positive semi-definite kernel: its smallest"
            f" eigenvalue is {smallest:.6g}. The eigenvalues are read as a"
            " probability distribution, so a negative one makes the score"
            " meaningless rather than merely imprecise. Use a kernel (Jaccard"
            " over shingle sets, cosine over vectors) rather than a metric"
            " turned into a similarity by subtraction — 1 - normalised"
            " Levenshtein is the common offender"
        )
    # Flatten the whole noise band to zero, not just its negative half — see
    # `_EIGENVALUE_NOISE`. The mass discarded is at most `n * noise`, which is
    # 4e-11 of a distribution summing to 1 at corpus scale; the alternative is
    # an `order=0` reading that counts numerical dust as structure.
    return np.where(np.abs(eigenvalues) <= noise, 0.0, eigenvalues)


def _effective_count(probabilities: np.ndarray, order: float) -> float:
    """``exp`` of the Rényi entropy of *probabilities*, at *order*.

    Three orders have closed forms that the general expression cannot compute,
    and each is a question somebody actually asks:

    * ``q = 0`` — the number of non-zero eigenvalues, i.e. the rank. The most
      generous reading: how many directions the sample occupies at all,
      regardless of how little mass is in most of them. The general form would
      evaluate ``0 ** 0 == 1`` and count the zeros too.
    * ``q = 1`` — Shannon, the default and what "the Vendi score" means unless
      qualified.
    * ``q = inf`` — ``1 / max(p)``, the most severe reading: the sample judged
      entirely by its single most dominant mode.

    Zeros are dropped rather than handled inside the sum: ``0 * log(0)`` is
    ``nan`` in floating point and ``0`` in the limit, and a diversity score of
    ``nan`` for a sample containing one duplicate would be indistinguishable
    from a bug anywhere else in the pipeline.
    """
    positive = probabilities[probabilities > 0.0]
    if positive.size == 0:
        return 0.0
    if order == 0.0:
        return float(positive.size)
    if math.isinf(order):
        return float(1.0 / positive.max())
    if abs(order - 1.0) <= _ORDER_ONE_TOLERANCE:
        return float(np.exp(-float((positive * np.log(positive)).sum())))
    return float(float((positive**order).sum()) ** (1.0 / (1.0 - order)))


def vendi(similarity: np.ndarray, *, order: float = 1.0) -> float:
    """The effective number of unique elements behind similarity matrix *K*.

    *K* must be square, symmetric, positive semi-definite and 1.0 on the
    diagonal; every one of those is checked and refused rather than worked
    around — see `_spectrum`.

    *order* is the Rényi order *q*. ``1.0`` (the default) is Shannon and is
    what an unqualified "Vendi score" means. The score is non-increasing in
    *q*: a larger order weights the dominant modes more heavily, so reading the
    same sample at ``q = 0.1`` and ``q = inf`` brackets it between the most
    generous and the most severe count you could defend.

    An empty matrix scores ``0.0`` — a sample with nothing in it has no
    effective elements, which is a different statement from the ``1.0`` a
    one-element sample scores, and collapsing the two would let an empty
    fingerprint batch report the diversity of a singleton.
    """
    if math.isnan(order) or order < 0.0:
        raise ValueError(f"order must be a non-negative Rényi order, got {order!r}")
    probabilities = _spectrum(similarity)
    if probabilities.size == 0:
        return 0.0
    return _effective_count(probabilities, order)


def vendi_of(
    items: Sequence[T],
    similarity_fn: Callable[[T, T], float],
    *,
    order: float = 1.0,
) -> float:
    """The Vendi score of *items* under *similarity_fn*.

    The canonical entry point — `vendi` is the same measurement for a caller
    who already holds a matrix (a cached kernel, or one built by something
    faster than a Python double loop).

    Builds the **full** matrix, calling *similarity_fn* both ways round for
    every pair, rather than computing the upper triangle and mirroring it.
    Mirroring is half the calls and would silently symmetrise an asymmetric
    similarity function, which is the one input `vendi` is explicitly required
    to refuse; paying for the other half is how that refusal reaches a caller
    who passed a function with a bug in it. The diagonal is likewise
    ``similarity_fn(x, x)`` rather than a hard-coded 1.0, because "returns 1.0
    on the diagonal" is a claim about the caller's function and filling it in
    for them would make it unfalsifiable.
    """
    n = len(items)
    matrix = np.empty((n, n), dtype=float)
    for i, left in enumerate(items):
        for j, right in enumerate(items):
            matrix[i, j] = similarity_fn(left, right)
    return vendi(matrix, order=order)


#: `vendi_of` under the name the *reading* has rather than the name the metric
#: has. Deliberately an alias and not a second implementation: two functions
#: that could ever disagree about how diverse a corpus is would be exactly the
#: fork `compiler.diversity.select` refused to keep when it lifted its
#: traversal into `dispersion.farthest_first`.
effective_count = vendi_of


__all__ = ["effective_count", "vendi", "vendi_of"]
