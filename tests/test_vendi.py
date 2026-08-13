"""The Vendi score's claim is that it counts *effectively*, so that is what is
asserted here — not that it runs.

Four properties carry the whole module, and each one is a way the count it
replaces (`compiler.diversity.DiversityReport.distinct_digests`) is wrong:
identical elements collapse to one, unlike elements each count for a whole one,
replicating the sample changes nothing, and a near-duplicate is worth much less
than a novel element. A test suite that checked shapes and exception types
without those would pass on an implementation that returned ``len(items)``.

Kernels are built from explicit vectors rather than from a fixture matrix,
because the interesting failures are on matrices that are *nearly* valid — a
diagonal a hair off 1.0, a spectrum a hair negative — and a hand-typed fixture
is exactly where those do not occur.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from worldloom import vendi as vendi_module
from worldloom.vendi import effective_count, vendi, vendi_of


# ---------------------------------------------------------------------------
# Kernels to score things with
# ---------------------------------------------------------------------------


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Cosine similarity of two vectors — a kernel, with a unit diagonal."""
    left, right = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(left @ right / (np.linalg.norm(left) * np.linalg.norm(right)))


def bigram_jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Jaccard over adjacent-heading bigrams — the outline kernel.

    The similarity the module docstring's 42-outline measurement uses, kept
    here because it is the shape of the thing this module is actually for: a
    sequence of section headings, compared on adjacency rather than on
    membership, so an RCA that opens with the cause and one that opens with the
    timeline are not the same document. Sentinels pad both ends so a
    one-heading outline still has bigrams to be compared on.
    """
    def grams(sequence: tuple[str, ...]) -> frozenset[tuple[str, str]]:
        padded = ("\x02", *sequence, "\x03")
        return frozenset(zip(padded, padded[1:], strict=False))

    left, right = grams(a), grams(b)
    return len(left & right) / len(left | right)


def random_kernel(n: int, dimensions: int, seed: int) -> np.ndarray:
    """A full-rank cosine kernel over *n* random vectors."""
    rng = np.random.default_rng(seed)
    vectors = rng.normal(size=(n, dimensions))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors @ vectors.T


def basis(index: int, dimensions: int = 8) -> tuple[float, ...]:
    """The *index*th standard basis vector — mutually orthogonal, so cosine
    similarity between any two distinct ones is exactly 0."""
    return tuple(1.0 if position == index else 0.0 for position in range(dimensions))


# ---------------------------------------------------------------------------
# The four properties that are the module
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 7, 40])
def test_identical_items_are_one_effective_item(n: int) -> None:
    """The claim the distinct-shape count cannot make. Forty copies of one
    outline are one outline, and the number says so."""
    assert vendi(np.ones((n, n))) == pytest.approx(1.0)


@pytest.mark.parametrize("n", [1, 2, 7, 40])
def test_mutually_orthogonal_items_are_n_effective_items(n: int) -> None:
    """The other end of the bound. Nothing resembles anything, so the effective
    count is the actual count — exactly, not approximately."""
    assert vendi(np.eye(n)) == pytest.approx(float(n))


def test_replicating_the_whole_sample_leaves_the_score_unchanged() -> None:
    """The property that makes this worth having over an entropy in bits.

    `compiler.diversity.DiversityReport.ngram_entropy_bits` reads 4.12 on a
    12-period corpus and 4.12 on the same corpus at 48 periods, which is
    correct for an average and useless as a diversity headline. This is
    invariant for the same reason and *reads as a count*, so the invariance is
    the honest answer rather than a blind spot: doubling every document does
    not double how many different documents there are.
    """
    kernel = random_kernel(9, dimensions=5, seed=8128)
    doubled = np.block([[kernel, kernel], [kernel, kernel]])
    assert vendi(doubled) == pytest.approx(vendi(kernel), rel=1e-9)

    tripled = np.block([[kernel] * 3 for _ in range(3)])
    assert vendi(tripled) == pytest.approx(vendi(kernel), rel=1e-9)


def test_a_near_duplicate_costs_far_less_than_a_novel_item() -> None:
    """The behaviour the whole module exists for, stated as a monotonicity.

    Four unlike items score 4. What a fifth is worth depends entirely on how
    unlike the other four it is: a whole element when it is orthogonal, and
    **less than nothing** when it is a near-copy of one of them. That last part
    is not a bug and is worth pinning, because it is where this measure parts
    company with intuition: the score is an *evenness*-aware count, so a fifth
    item that piles more mass onto a direction already occupied makes the
    sample less even and the effective count falls. Measured here at 3.80 for a
    0.999-similar fifth item against 4.00 for four alone.

    A distinct-shape count scores every one of these additions identically
    at +1, which is the whole reason this module exists.
    """
    items = [basis(i) for i in range(4)]
    base = vendi_of(items, cosine)
    assert base == pytest.approx(4.0)

    def with_fifth(similarity_to_first: float) -> float:
        # A unit vector at exactly `similarity_to_first` from items[0],
        # composed out of a dimension none of the other four occupy.
        fifth = (
            np.array(basis(0)) * similarity_to_first
            + np.array(basis(7)) * math.sqrt(1.0 - similarity_to_first**2)
        )
        return vendi_of([*items, tuple(fifth)], cosine)

    novelty = [0.999, 0.995, 0.95, 0.9, 0.7, 0.5, 0.3, 0.1, 0.0]
    scores = [with_fifth(similarity) for similarity in novelty]

    # A novel item is worth a whole element; a near-copy is worth a negative
    # fraction of one.
    assert scores[-1] == pytest.approx(5.0)
    assert scores[0] < base
    assert scores[1] - base < 0.05 * (scores[-1] - base)

    # And the whole curve is monotone in novelty, so the measure grades a fifth
    # document rather than merely counting it.
    for closer, further in itertools.pairwise(scores):
        assert further > closer, f"{scores} is not monotone over {novelty}"


def test_k_groups_of_identical_items_score_k() -> None:
    """The composite of the first two properties, and the sentence in the
    module docstring: thirty outlines in three families are three outlines,
    however many copies of each there are."""
    for group_size in (2, 10, 30):
        blocks = [
            [np.ones((group_size, group_size)) if i == j else np.zeros((group_size, group_size))
             for j in range(3)]
            for i in range(3)
        ]
        assert vendi(np.block(blocks)) == pytest.approx(3.0)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_the_score_is_bounded_by_one_and_n(seed: int) -> None:
    """``trace(K / n) == 1`` is what buys this, and it is worth checking on
    arbitrary kernels rather than trusting the arithmetic in a comment."""
    for n in (2, 5, 11):
        kernel = random_kernel(n, dimensions=3, seed=seed * 100 + n)
        score = vendi(kernel)
        assert 1.0 - 1e-9 <= score <= n + 1e-9


# ---------------------------------------------------------------------------
# Determinism, and order-independence
# ---------------------------------------------------------------------------


def test_the_same_matrix_scores_bit_identically_twice() -> None:
    kernel = random_kernel(12, dimensions=6, seed=4242)
    first = vendi(kernel)
    assert vendi(kernel) == first
    assert vendi(kernel.copy()) == first


def test_shuffling_the_sample_does_not_move_the_score() -> None:
    """Order must not matter: a permutation of the sample is a similarity
    transform ``P.T @ K @ P``, whose spectrum is identical. Asserted rather
    than assumed, because a caller building a batch from a dict, a set or the
    corpus's emission order will hand this the same sample in different orders
    and must not get different diversity readings for it.

    Assert to a tolerance, not exactly: the eigenvalues are mathematically the
    same and LAPACK computes them from a differently-permuted matrix, so the
    last bits legitimately differ. `vendi.py`'s docstring says why this number
    must never be fed back into a build.
    """
    items = [tuple(row) for row in np.random.default_rng(99).normal(size=(15, 4))]
    reference = vendi_of(items, cosine)
    order = np.random.default_rng(7).permutation(len(items))
    shuffled = [items[i] for i in order]
    assert vendi_of(shuffled, cosine) == pytest.approx(reference, rel=1e-12)


def test_effective_count_is_the_same_function_under_another_name() -> None:
    assert effective_count is vendi_of


def test_vendi_of_agrees_with_vendi_on_the_matrix_it_builds() -> None:
    items = [("a", "b"), ("a", "b", "c"), ("z",), ("a", "b")]
    matrix = np.array([[bigram_jaccard(a, b) for b in items] for a in items])
    assert vendi_of(items, bigram_jaccard) == vendi(matrix)


def test_an_outline_batch_scores_below_its_distinct_count() -> None:
    """The headline claim, on outline-shaped input.

    Nine outlines: five variations on one financial memo, three on one incident
    review, and a one-heading attendance note. The distinct-sequence count says
    eight, pricing a one-heading difference as a whole new document and one
    exact repeat as nothing. The effective count says fewer — and not *much*
    fewer, because there really are three unrelated documents in there, so a
    measure that collapsed this to ~1 would be as wrong as one reporting 8.
    """
    outlines = [
        ("Position", "By unit", "Drivers"),
        ("Position", "By unit", "Drivers"),
        ("Position", "By unit", "Drivers", "Recommendation"),
        ("Position", "By unit", "Outlook"),
        ("Position", "By unit", "Drivers", "Outlook"),
        ("Timeline", "Cause", "Remediation"),
        ("Cause", "Timeline", "Remediation"),
        ("Cause", "Timeline", "Remediation", "Follow-up"),
        ("Attendance",),
    ]
    distinct = len(set(outlines))
    score = vendi_of(outlines, bigram_jaccard)
    assert distinct == 8
    assert score < distinct
    # And it does not collapse: there really are several unrelated documents in
    # there, so a measure reporting ~1 would be as wrong as one reporting 8.
    assert score > 3.0


# ---------------------------------------------------------------------------
# Rényi orders
# ---------------------------------------------------------------------------


def test_order_zero_counts_non_zero_eigenvalues() -> None:
    """q=0 is the rank — the most generous reading, counting every direction
    the sample occupies at all."""
    assert vendi(np.eye(6), order=0.0) == pytest.approx(6.0)
    assert vendi(random_kernel(6, dimensions=6, seed=5), order=0.0) == pytest.approx(6.0)


def test_order_zero_does_not_count_floating_point_dust_as_a_dimension() -> None:
    """The trap in ``order=0``, and the reason `_EIGENVALUE_NOISE` clamps in
    both directions.

    A sample containing exact duplicates is rank-deficient, and ``eigvalsh``
    returns its structural zeros scattered across ±1e-17 rather than at zero. A
    literal "count the eigenvalues greater than zero" counts about half of that
    dust and reports a rank several above the truth — measured at 38 against a
    true 33 on this repository's own 42 outlines, which is a wrong answer that
    looks entirely plausible.
    """
    rng = np.random.default_rng(31)
    vectors = rng.normal(size=(5, 5))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    # Three exact copies of the first vector: seven items spanning five
    # directions.
    stacked = np.vstack([vectors, vectors[:1], vectors[:1]])
    kernel = stacked @ stacked.T
    assert kernel.shape == (7, 7)
    assert vendi(kernel, order=0.0) == pytest.approx(5.0)


def test_order_infinity_is_one_over_the_largest_eigenvalue() -> None:
    kernel = random_kernel(8, dimensions=4, seed=6)
    largest = float(np.linalg.eigvalsh(kernel / 8).max())
    assert vendi(kernel, order=math.inf) == pytest.approx(1.0 / largest)


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_the_score_never_rises_with_the_order(seed: int) -> None:
    """Rényi entropy is non-increasing in q, so the exponential of it is too —
    which is what lets a caller bracket a sample between the most generous
    reading (q=0) and the most severe (q=inf) and quote both."""
    kernel = random_kernel(10, dimensions=5, seed=seed)
    orders = [0.0, 0.25, 0.5, 1.0, 2.0, 5.0, math.inf]
    scores = [vendi(kernel, order=q) for q in orders]
    for earlier, later in itertools.pairwise(scores):
        assert later <= earlier + 1e-9, f"{scores} is not non-increasing over {orders}"


def test_an_order_beside_one_is_computed_as_shannon() -> None:
    """The general Rényi form divides by ``1 - q`` and is numerically worthless
    a hair away from 1. The limit is Shannon, so taking it is the answer rather
    than an approximation of it."""
    kernel = random_kernel(7, dimensions=4, seed=21)
    assert vendi(kernel, order=1.0 + 1e-12) == vendi(kernel, order=1.0)


@pytest.mark.parametrize("order", [-0.5, float("nan")])
def test_a_negative_or_undefined_order_is_refused(order: float) -> None:
    with pytest.raises(ValueError, match="order"):
        vendi(np.eye(3), order=order)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_an_empty_sample_scores_zero_and_a_singleton_scores_one() -> None:
    """Different numbers on purpose. A sample with nothing in it has no
    effective elements; a sample with one thing in it has one, and reporting
    both as 1.0 would let an empty batch claim a singleton's diversity."""
    assert vendi(np.zeros((0, 0))) == 0.0
    assert vendi_of([], cosine) == 0.0
    assert vendi(np.ones((1, 1))) == pytest.approx(1.0)
    assert vendi_of([basis(0)], cosine) == pytest.approx(1.0)


def test_a_sample_of_two_identical_items_is_one() -> None:
    assert vendi_of([("a", "b"), ("a", "b")], bigram_jaccard) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# What it refuses, rather than returning a plausible wrong number for
# ---------------------------------------------------------------------------


def test_a_diagonal_that_is_not_one_is_refused() -> None:
    """A similarity function that forgot the identity case shrinks every
    eigenvalue and reports a *lower* diversity for the same sample — wrong in
    a direction nobody would question."""
    matrix = np.eye(3)
    matrix[1, 1] = 0.9
    with pytest.raises(ValueError, match="diagonal"):
        vendi(matrix)


def test_a_diagonal_a_few_ulps_off_one_is_admitted() -> None:
    """Cosine over normalised vectors lands a hair off 1.0 and is a perfectly
    good kernel; the check must not be equality."""
    matrix = np.eye(4)
    np.fill_diagonal(matrix, 1.0 - 1e-15)
    assert vendi(matrix) == pytest.approx(4.0)


def test_an_asymmetric_matrix_is_refused_rather_than_symmetrised() -> None:
    matrix = np.eye(3)
    matrix[0, 1] = 0.8
    matrix[1, 0] = 0.2
    with pytest.raises(ValueError, match="symmetric"):
        vendi(matrix)


def test_an_asymmetric_similarity_function_is_caught_through_vendi_of() -> None:
    """`vendi_of` pays for the full n^2 calls precisely so this reaches the
    caller: mirroring the upper triangle would have hidden the bug for good."""
    def lopsided(a: int, b: int) -> float:
        return 1.0 if a == b else (0.9 if a < b else 0.1)

    with pytest.raises(ValueError, match="symmetric"):
        vendi_of([1, 2, 3], lopsided)


def test_a_non_psd_kernel_is_refused() -> None:
    """The trap worth having: symmetric with a unit diagonal is not enough.
    ``1 - normalised Levenshtein`` looks exactly like this and is not a kernel,
    and a clamped negative eigenvalue would leave the remaining mass summing to
    more than one — a score biased upward with nothing to signal it."""
    matrix = np.array([
        [1.0, 0.9, -0.9],
        [0.9, 1.0, 0.9],
        [-0.9, 0.9, 1.0],
    ])
    assert float(np.linalg.eigvalsh(matrix).min()) < -0.1
    with pytest.raises(ValueError, match="positive semi-definite"):
        vendi(matrix)


def test_noise_scale_negative_eigenvalues_are_clamped_not_refused() -> None:
    """A kernel whose smallest eigenvalue is negative at noise scale must score,
    not raise.

    The negative eigenvalue is *constructed*, not hoped for. This test first
    built a rank-deficient Gram matrix and asserted ``eigvalsh(...).min() < 0``
    on the theory that structural zeros come back as negative dust — which is
    where LAPACK puts them on some builds and not others. It passed locally and
    failed on CI at ``+6.9e-17``, because the sign of that dust is a property of
    whichever BLAS the machine linked, not of anything this repository
    controls. `vendi.py`'s own docstring makes exactly this point about
    ``eigvalsh`` and it is worth not re-learning.

    ``[[1, 1 + e], [1 + e, 1]]`` has eigenvalues ``2 + e`` and ``-e`` in closed
    form, so at ``e = 1e-15`` the smallest is negative, inside the noise band,
    and recovered to within ~2e-16 on any build — the clamp branch is exercised
    deterministically.
    """
    epsilon = 1e-15
    kernel = np.array([[1.0, 1.0 + epsilon], [1.0 + epsilon, 1.0]])
    assert float(np.linalg.eigvalsh(kernel).min()) < 0.0
    assert vendi(kernel) == pytest.approx(1.0)


def test_the_structural_zeros_of_a_rank_deficient_kernel_are_flattened() -> None:
    """The real-world shape of the case above: a sample containing a duplicate.

    Asserted on magnitude rather than sign for the reason the test above
    records. What matters is that the dust — whichever side of zero this
    machine's LAPACK puts it on — is inside the band and gets flattened, so
    ``order=0`` reports the true rank rather than counting numerical noise as
    structure.

    Four vectors, but they live in the plane, so the Gram matrix is 4x4 of rank
    **2** and two of its four eigenvalues are structural zeros. That is the
    density of dust `_EIGENVALUE_NOISE` exists for: without the positive half of
    the clamp, ``order=0`` here reads 4.
    """
    vectors = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [0.6, 0.8]])
    kernel = vectors @ vectors.T
    assert np.linalg.matrix_rank(kernel) == 2
    assert abs(float(np.linalg.eigvalsh(kernel).min())) <= 1e-12
    assert 1.0 <= vendi(kernel) <= 4.0
    assert vendi(kernel, order=0) == pytest.approx(2.0)


@pytest.mark.parametrize(
    "matrix",
    [
        np.ones(3),
        np.ones((2, 3)),
        np.ones((2, 2, 2)),
    ],
)
def test_a_matrix_that_is_not_square_is_refused(matrix: np.ndarray) -> None:
    with pytest.raises(ValueError, match="square"):
        vendi(matrix)


def test_a_non_finite_entry_is_refused() -> None:
    matrix = np.eye(3)
    matrix[0, 2] = matrix[2, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        vendi(matrix)


def test_the_module_exports_exactly_its_public_surface() -> None:
    assert vendi_module.__all__ == ["effective_count", "vendi", "vendi_of"]
