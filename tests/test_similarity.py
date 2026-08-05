"""Set similarity: the exact answer, faster, and the approximate one labelled.

The claim `similarity.near_duplicate_pairs` makes is unusually strong for an
optimisation — that it returns *exactly* the pairs a full pairwise scan would,
not a good approximation of them — so it is checked against brute force over
randomised inputs rather than against a fixture. A fixture would prove the
filters agree with themselves on the one case someone thought of; a randomised
sweep is what catches a prefix bound that is off by one, which is the only
interesting way this can be wrong.
"""

from __future__ import annotations

import itertools
import random

import pytest

from worldloom import similarity


def brute_force(sets: list[frozenset[str]], threshold: float) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(
        (i, j)
        for i, j in itertools.combinations(range(len(sets)), 2)
        if similarity.jaccard(sets[i], sets[j]) >= threshold
    ))


# ---------------------------------------------------------------------------
# The exact join
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("threshold", [0.2, 0.5, 0.8, 0.95, 1.0])
def test_the_join_returns_exactly_what_brute_force_does(threshold: float) -> None:
    rng = random.Random(8128)
    vocabulary = [f"w{i}" for i in range(40)]
    for _ in range(20):
        sets = [
            frozenset(rng.sample(vocabulary, rng.randint(0, 25)))
            for _ in range(30)
        ]
        assert similarity.near_duplicate_pairs(sets, threshold) == brute_force(sets, threshold)


def test_identical_sets_are_found_at_a_threshold_of_one() -> None:
    sets = [frozenset("abc"), frozenset("abc"), frozenset("abd")]
    assert similarity.near_duplicate_pairs(sets, 1.0) == ((0, 1),)


def test_empty_sets_never_pair() -> None:
    """Two documents with no shingles are not near-duplicates of each other;
    they are two documents nobody has written yet."""
    sets = [frozenset(), frozenset(), frozenset("ab")]
    assert similarity.near_duplicate_pairs(sets, 0.5) == ()


def test_a_threshold_outside_the_open_unit_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="threshold"):
        similarity.near_duplicate_pairs([frozenset("a"), frozenset("a")], 0.0)


def test_the_join_is_fast_where_brute_force_is_not() -> None:
    """Corpus-shaped input: shared boilerplate, near-unique bodies, and a
    family of documents stamped from one template. Two thousand documents is
    two million pairs, which brute force does not finish quickly and this
    does — the whole reason the algorithm changed."""
    rng = random.Random(11)
    boilerplate = frozenset(f"b{i}" for i in range(20))
    sets: list[frozenset[str]] = []
    for index in range(2000):
        if index and index % 50 == 0:
            sets.append(sets[index - 50] | frozenset({f"u{index}"}))
        else:
            sets.append(boilerplate | frozenset(
                f"s{rng.randrange(1_000_000)}" for _ in range(120)
            ))
    pairs = similarity.near_duplicate_pairs(sets, 0.8)
    assert len(pairs) > 0, "the stamped-from-a-template family must be found"
    # Every reported pair really does clear the bar, checked directly rather
    # than trusted: a filter bug that let extra pairs through would otherwise
    # look like a better recall figure.
    for left, right in pairs:
        assert similarity.jaccard(sets[left], sets[right]) >= 0.8


def test_clusters_group_a_stamped_family() -> None:
    sets = [
        frozenset("abcdefgh"),
        frozenset("abcdefgi"),
        frozenset("abcdefgj"),
        frozenset("zyxwvuts"),
    ]
    pairs = similarity.near_duplicate_pairs(sets, 0.7)
    assert similarity.clusters(pairs, len(sets)) == ((0, 1, 2),)


def test_a_lone_document_is_not_a_cluster() -> None:
    assert similarity.clusters((), 5) == ()


# ---------------------------------------------------------------------------
# Shingles
# ---------------------------------------------------------------------------


def test_shingles_of_a_short_text_are_the_whole_text() -> None:
    assert similarity.shingles(["a", "b"], 5) == frozenset({("a", "b")})
    assert similarity.shingles([], 5) == frozenset()


def test_shingles_slide() -> None:
    assert similarity.shingles(["a", "b", "c"], 2) == frozenset({("a", "b"), ("b", "c")})


# ---------------------------------------------------------------------------
# The approximate path, honestly labelled
# ---------------------------------------------------------------------------


def test_a_signature_is_a_pure_function_of_the_text() -> None:
    """No seed, no stream, no process state: two corpora built in different
    processes have to be comparable, which a seeded permutation would break."""
    members = frozenset(f"x{i}" for i in range(50))
    left = similarity.MinHash().signature(members)
    right = similarity.MinHash().signature(frozenset(reversed(sorted(members))))
    assert list(left) == list(right)


def test_the_estimate_lands_near_the_truth() -> None:
    a = frozenset(f"x{i}" for i in range(200))
    b = frozenset(f"x{i}" for i in range(40, 240))
    minhash = similarity.MinHash()
    estimate = minhash.estimate(minhash.signature(a), minhash.signature(b))
    # 1/sqrt(128) is about 0.088; three of those is the band a correct
    # implementation stays inside and a broken one does not.
    assert abs(estimate - similarity.jaccard(a, b)) < 0.27


def test_the_band_configuration_states_its_own_recall() -> None:
    index = similarity.LshIndex()
    assert index.recall_at(0.8) > 0.9
    assert index.recall_at(0.4) < 0.05
    # Monotone in similarity, which is the whole premise of the S-curve.
    assert index.recall_at(0.9) > index.recall_at(0.8) > index.recall_at(0.7)


def test_an_oversized_band_configuration_is_refused() -> None:
    with pytest.raises(ValueError, match="signature"):
        similarity.LshIndex(bands=32, rows_per_band=8)


def test_candidates_surface_the_similar_pair_and_not_the_unrelated_one() -> None:
    minhash = similarity.MinHash()
    a = frozenset(f"x{i}" for i in range(300))
    b = frozenset(f"x{i}" for i in range(5, 305))
    c = frozenset(f"q{i}" for i in range(300))
    signatures = [minhash.signature(s) for s in (a, b, c)]
    assert similarity.LshIndex().candidates(signatures) == ((0, 1),)


# ---------------------------------------------------------------------------
# The corpus consumer
# ---------------------------------------------------------------------------


def test_the_stats_near_duplicate_rate_is_unchanged_by_the_new_algorithm() -> None:
    """`stats` reports the same number it always did. The point of the join was
    the time it takes to get, not the answer."""
    from worldloom import RetailWorld, stats
    from worldloom.evaluate.index import passages
    from worldloom.narrative import DeterministicProvider
    from worldloom.scenarios import MonthEndClose

    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True,
                      comparative_months=5)
    )
    world = world.compile().narrate(DeterministicProvider()).render("markdown")
    pool = list(passages(world))
    shingle_sets = [stats._shingles(p.text) for p in pool]

    near, total = stats._near_duplicates(pool)
    assert total == len(pool) * (len(pool) - 1) // 2
    assert near == len(brute_force(shingle_sets, stats.NEAR_DUPLICATE_THRESHOLD))


def test_clusters_name_the_repeated_passages_a_rate_only_counts() -> None:
    from worldloom import RetailWorld, stats
    from worldloom.evaluate.index import passages
    from worldloom.narrative import DeterministicProvider
    from worldloom.scenarios import MonthEndClose

    world = RetailWorld(seed=8128).build()
    for period in ("2026-01", "2026-02", "2026-03"):
        world = world.run(MonthEndClose(period=period, include_operational_incident=True))
    world = world.compile().narrate(DeterministicProvider()).render("markdown")
    pool = list(passages(world))

    groups = stats.near_duplicate_clusters(pool)
    assert groups, "three closes of one template must repeat themselves"

    # A cluster is a connected component, so every member is joined to the
    # group by *some* qualifying pair — not necessarily to the first one.
    # Jaccard is not transitive, and asserting it were would be a test that
    # passes on this corpus and fails on a longer chain of gradual drift.
    pairs = set(similarity.near_duplicate_pairs(
        [stats._shingles(p.text) for p in pool], stats.NEAR_DUPLICATE_THRESHOLD
    ))
    for group in groups:
        for member in group:
            assert any(member in pair for pair in pairs), member
