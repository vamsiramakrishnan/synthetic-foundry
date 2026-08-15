"""Tests for `worldloom.adjacency`.

The central claim is a containment: everything ``synthesise`` returns is
something ``admits`` vouches for, and everything the examples taught is
something the model readmits. Both directions are asserted below, the first
over a fuzz and the second over every example.

Fixtures are local rather than imported from ``documents``: this module is a
pure library by design (no world, no corpus, no I/O), and a test that reached
for the real outline table would make it look like one that is not.
"""

from __future__ import annotations

import itertools

import pytest

from worldloom.adjacency import Adjacency, admits, learn, synthesise
from worldloom.rng import Rng

# Two document families that share exactly one heading ("Position"), which is
# the only seam recombination can happen at — deliberately shaped like the real
# table, where splices are rare and every novel outline goes through one.
OUTLINES: tuple[tuple[str, ...], ...] = (
    ("Position", "By business unit", "Drivers", "Recommendation"),
    ("Position", "Drivers", "Recommendation"),
    ("Summary", "Timeline", "Root cause", "Actions"),
    ("Summary", "Position", "Actions"),
    ("Purpose and scope", "Responsibilities"),
    ("Running note",),
)


def _all_admitted(model: Adjacency, length: int) -> list[tuple[str, ...]]:
    """Every admitted sequence of *length*, by brute force over the alphabet.

    Deliberately not the module's own search — a completeness assertion that
    used the thing under test to decide what should have been found would be
    circular. Exponential and fine: the fixture alphabet is small.
    """
    return [
        candidate
        for candidate in itertools.product(model.alphabet, repeat=length)
        if admits(model, candidate)
    ]


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------


def test_model_readmits_every_example_it_learned_from():
    """The floor. A model that cannot vouch for its own training data is not a
    weak model, it is a broken one — and the failure mode this pins is the
    tempting one: dropping examples shorter than a window."""
    for order in (1, 2, 3):
        model = learn(OUTLINES, order=order)
        for example in OUTLINES:
            assert admits(model, example), f"order {order} rejected {example}"


def test_learning_ignores_example_order():
    """`learn` reads sets, so the batch order must not reach the model."""
    forward = learn(OUTLINES, order=2)
    backward = learn(tuple(reversed(OUTLINES)), order=2)
    assert forward == backward
    assert forward.alphabet == tuple(sorted(forward.alphabet))


def test_learning_records_windows_starts_and_ends():
    model = learn((("a", "b", "c"),), order=2)
    assert model.windows == frozenset({("a", "b"), ("b", "c")})
    assert model.starts == frozenset({("a", "b")})
    assert model.ends == frozenset({("b", "c")})
    assert model.alphabet == ("a", "b", "c")


def test_short_example_is_its_own_window_start_and_end():
    """Six of the shipped outlines have one heading. They must survive an
    order-2 model, and they can only do so as whole windows."""
    model = learn((("only",), ("a", "b")), order=2)
    assert ("only",) in model.windows
    assert admits(model, ("only",))
    # ...and it is not thereby a legal opening for a longer sequence: nothing
    # ever followed it.
    assert not admits(model, ("only", "b"))


def test_empty_examples_teach_nothing():
    """An empty outline must not become an admitted shape. If it landed in
    `starts` and `ends`, a document with no sections would validate."""
    model = learn(((), ("a", "b")), order=2)
    assert not admits(model, ())
    assert () not in model.starts
    assert model.alphabet == ("a", "b")


def test_learning_from_nothing_is_an_empty_model():
    model = learn((), order=2)
    assert model.alphabet == ()
    assert model.windows == frozenset()
    assert not admits(model, ("anything",))
    assert synthesise(model, Rng(1), length=3) is None


def test_order_below_one_is_refused():
    with pytest.raises(ValueError, match="order must be at least 1"):
        learn(OUTLINES, order=0)


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------


def test_admission_is_bounded_by_starts_and_ends():
    """The constraint that stops outlines opening on "Appendix". Every window
    below is real; only the boundaries are wrong."""
    model = learn(OUTLINES, order=2)
    # Every bigram of this occurred, but "Drivers" never opened a document.
    assert ("Drivers", "Recommendation") in model.windows
    assert not admits(model, ("Drivers", "Recommendation"))
    # ...and "By business unit" never closed one.
    assert ("Position", "By business unit") in model.windows
    assert not admits(model, ("Position", "By business unit"))


def test_admission_rejects_an_unseen_window():
    model = learn(OUTLINES, order=2)
    # Both headings are real, both boundaries are real, the pairing is not.
    assert not admits(model, ("Summary", "By business unit", "Drivers", "Recommendation"))


def test_admission_rejects_the_empty_sequence():
    assert not admits(learn(OUTLINES, order=2), ())


def test_a_novel_sequence_is_admitted_through_the_shared_heading():
    """The whole point of the module, asserted on a splice by hand: two
    documents that share one heading yield a third that is in neither."""
    model = learn(OUTLINES, order=2)
    spliced = ("Summary", "Position", "Drivers", "Recommendation")
    assert spliced not in OUTLINES
    assert admits(model, spliced)


# ---------------------------------------------------------------------------
# Synthesis — the central property
# ---------------------------------------------------------------------------


def test_everything_synthesised_is_admitted():
    """The containment the module promises, over a fuzz of a few hundred draws
    across every order and length the fixture supports."""
    checked = 0
    for order in (1, 2, 3):
        model = learn(OUTLINES, order=order)
        for length in range(1, 7):
            for draw in range(30):
                # Derived by name, never by draw order — a shared stream would
                # make draw 17 depend on how much backtracking draw 16 needed.
                rng = Rng(8128, f"adjacency/{order}/{length}/{draw}")
                result = synthesise(model, rng, length=length)
                if result is None:
                    continue
                assert len(result) == length
                assert admits(model, result)
                windows = [
                    result[i : i + order] for i in range(len(result) - order + 1)
                ] or [result]
                assert all(window in model.windows for window in windows)
                checked += 1
    assert checked > 300, f"fuzz was too thin to mean anything: {checked} sequences"


def test_synthesis_is_deterministic_and_order_independent():
    """Same seed, same answer — including when the model was learned from the
    same examples shuffled, since the model is a pure function of the set."""
    forward = learn(OUTLINES, order=2)
    backward = learn(tuple(reversed(OUTLINES)), order=2)
    for length in range(1, 6):
        first = synthesise(forward, Rng(4242, "s"), length=length)
        again = synthesise(forward, Rng(4242, "s"), length=length)
        shuffled = synthesise(backward, Rng(4242, "s"), length=length)
        assert first == again
        assert first == shuffled


def test_synthesis_is_complete_where_brute_force_says_it_should_be():
    """`None` means "no such sequence", not "the search gave up". Checked
    against an independent enumeration rather than against itself — this is
    the property WFC's non-backtracking propagation would fail."""
    model = learn(OUTLINES, order=2)
    for length in range(1, 7):
        expected = _all_admitted(model, length)
        result = synthesise(model, Rng(99, f"complete/{length}"), length=length)
        if expected:
            assert result in expected
        else:
            assert result is None


def test_synthesis_reaches_every_admitted_sequence_eventually():
    """Not a uniform sampler, but it must not be a fixed-point machine either:
    over enough seeds the search covers everything brute force finds."""
    model = learn(OUTLINES, order=2)
    for length in (3, 4):
        expected = set(_all_admitted(model, length))
        seen = {
            synthesise(model, Rng(seed, f"cover/{length}"), length=length)
            for seed in range(200)
        }
        assert expected <= seen


def test_require_and_forbid_are_honoured():
    model = learn(OUTLINES, order=2)
    for seed in range(40):
        result = synthesise(
            model, Rng(seed, "constrained"), length=4,
            require=("Actions",), forbid=("Drivers",),
        )
        if result is None:
            continue
        assert "Actions" in result
        assert "Drivers" not in result
        assert admits(model, result)


def test_unsatisfiable_constraints_return_none_rather_than_raising():
    model = learn(OUTLINES, order=2)
    # Contradictory ask.
    assert synthesise(model, Rng(1), length=4, require=("Actions",), forbid=("Actions",)) is None
    # An element no author ever wrote.
    assert synthesise(model, Rng(1), length=4, require=("Appendix",)) is None
    # More required elements than there are slots.
    assert synthesise(
        model, Rng(1), length=1, require=("Summary", "Actions", "Position")
    ) is None
    # Every opening forbidden.
    assert synthesise(model, Rng(1), length=4, forbid=tuple(model.alphabet)) is None
    # A length nothing was ever written at.
    assert synthesise(model, Rng(1), length=12) is None


def test_degenerate_lengths_return_none():
    model = learn(OUTLINES, order=2)
    assert synthesise(model, Rng(1), length=0) is None
    assert synthesise(model, Rng(1), length=-3) is None


def test_single_example_synthesises_only_itself():
    """The degenerate model: one example, no seams, so the admitted set is a
    single sequence and the generator can only reproduce it."""
    model = learn((("a", "b", "c"),), order=2)
    assert synthesise(model, Rng(7), length=3) == ("a", "b", "c")
    assert synthesise(model, Rng(7), length=2) is None
    assert synthesise(model, Rng(7), length=4) is None


def test_length_below_order_needs_a_whole_short_example():
    """At order 3 a two-element sequence can only come from a two-element
    example — there is no window to build it out of."""
    model = learn((("a", "b", "c", "d"), ("x", "y")), order=3)
    assert synthesise(model, Rng(3), length=2) == ("x", "y")
    assert synthesise(model, Rng(3), length=1) is None


def test_order_one_is_a_bag_bounded_by_its_ends():
    """Order 1 constrains nothing but the alphabet and the boundaries, which is
    the loose end of the dial and has to work rather than crash — the tail
    slice that computes the predecessor context is empty at order 1, and the
    obvious `prefix[-(order - 1):]` returns the whole prefix there."""
    model = learn((("a", "b"), ("c", "d")), order=1)
    result = synthesise(model, Rng(11), length=4)
    assert result is not None
    assert result[0] in ("a", "c")
    assert result[-1] in ("b", "d")
    assert admits(model, result)
