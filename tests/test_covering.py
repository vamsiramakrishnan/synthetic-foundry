"""Covering arrays: the guarantee, not the algorithm.

`covering.covering_array` makes one claim — at strength *t*, every combination
of *t* values appears in some row — and it is checked here by recomputing the
whole space and asking `coverage` for the fraction, over several spaces and
every strength each one admits. That is the only honest way to test a greedy
heuristic: the row counts it happens to produce are a measurement, and pinned
as one below, but they are not the contract and a better IPOG would move them.

The order tests are the other half. Everything here runs inside a build whose
output CI diffs byte-for-byte, so "same answer twice" and "same answer for a
shuffled batch" are correctness, not hygiene.
"""

from __future__ import annotations

import itertools
import random

import pytest

from worldloom.covering import Parameter, Row, coverage, covering_array, holes


def space(**widths: int) -> list[Parameter]:
    """Parameters named by keyword, each with `width` values named after it."""
    return [
        Parameter(name, tuple(f"{name}-{i}" for i in range(width)))
        for name, width in widths.items()
    ]


#: The shape structure generation actually has: two wide axes, a handful of
#: narrow ones, and four booleans. Everything below that names a real case
#: uses this one.
STRUCTURE = space(
    scope=3, density=3, storyline=6, style=5,
    appendix=2, exhibits=2, glossary=2, footnotes=2,
)

BINARY_FIVE = space(a=2, b=2, c=2, d=2, e=2)

MIXED_SPACES = [
    space(a=2, b=3),
    space(a=2, b=2, c=2),
    space(a=6, b=2, c=3),
    space(a=2, b=3, c=4, d=5),
    space(a=5, b=4, c=3, d=2, e=2),
]


def total_combinations(parameters: list[Parameter], strength: int) -> int:
    return sum(
        len(list(itertools.product(*(parameters[j].values for j in subset))))
        for subset in itertools.combinations(range(len(parameters)), strength)
    )


# ---------------------------------------------------------------------------
# The central claim
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("parameters", MIXED_SPACES + [BINARY_FIVE])
def test_the_array_covers_the_space_at_every_strength(parameters: list[Parameter]) -> None:
    """The property the module exists for, at every strength it accepts.

    Mixed cardinalities are in the sweep deliberately: a covering array over
    uniform domains is the easy case, and every space this project has is
    mixed.
    """
    for strength in range(1, len(parameters) + 1):
        rows = covering_array(parameters, strength=strength)
        assert coverage(rows, parameters, strength=strength) == 1.0
        assert holes(rows, parameters, strength=strength) == ()


def test_the_structure_space_covers_at_every_strength() -> None:
    for strength in range(1, len(STRUCTURE) + 1):
        rows = covering_array(STRUCTURE, strength=strength)
        assert coverage(rows, STRUCTURE, strength=strength) == 1.0


@pytest.mark.parametrize("parameters", MIXED_SPACES + [BINARY_FIVE, STRUCTURE])
def test_every_row_is_a_complete_configuration(parameters: list[Parameter]) -> None:
    """A row with a missing or invented value would still let `coverage` report
    1.0 for the combinations it does carry, and would be unusable as a build
    configuration."""
    for row in covering_array(parameters, strength=2):
        assert sorted(row) == sorted(p.name for p in parameters)
        for parameter in parameters:
            assert row[parameter.name] in parameter.values


def test_strength_one_needs_exactly_the_widest_parameter() -> None:
    """At t=1 the optimum is known — every value of every parameter must appear,
    and the widest parameter alone forces that many rows — so this is the one
    strength where the greedy construction can be held to the exact answer."""
    for parameters in MIXED_SPACES + [STRUCTURE]:
        rows = covering_array(parameters, strength=1)
        assert len(rows) == max(len(p.values) for p in parameters)


def test_full_strength_is_the_exhaustive_product() -> None:
    parameters = space(a=2, b=3, c=4)
    rows = covering_array(parameters, strength=3)
    assert len(rows) == 2 * 3 * 4
    assert len({tuple(sorted(row.items())) for row in rows}) == 24


# ---------------------------------------------------------------------------
# What it costs — measurements, pinned so a change has to restate them
# ---------------------------------------------------------------------------


def test_the_row_counts_quoted_in_the_docstring() -> None:
    """Pinned measurements, not requirements. If a better construction moves
    them, move these and the module docstring together — the figures are quoted
    there and this is what stops the two drifting apart."""
    assert len(covering_array(BINARY_FIVE, strength=2)) == 7
    assert len(covering_array(BINARY_FIVE, strength=3)) == 12
    assert len(covering_array(STRUCTURE, strength=2)) == 30


def test_the_pairwise_array_cannot_be_shorter_than_its_two_widest_axes() -> None:
    """The lower bound holds whatever the heuristic does, and on the structure
    space the construction meets it: 6 storylines x 5 styles = 30."""
    for parameters in MIXED_SPACES + [BINARY_FIVE, STRUCTURE]:
        widest = sorted((len(p.values) for p in parameters), reverse=True)[:2]
        rows = covering_array(parameters, strength=2)
        assert len(rows) >= widest[0] * widest[1]
    assert len(covering_array(STRUCTURE, strength=2)) == 30


def test_covering_is_far_smaller_than_exhaustive() -> None:
    exhaustive = 1
    for parameter in STRUCTURE:
        exhaustive *= len(parameter.values)
    assert exhaustive == 4320
    assert len(covering_array(STRUCTURE, strength=2)) * 100 < exhaustive


# ---------------------------------------------------------------------------
# Determinism and order independence
# ---------------------------------------------------------------------------


def test_the_same_arguments_give_the_same_array() -> None:
    for parameters in MIXED_SPACES + [STRUCTURE]:
        for strength in (1, 2, 3):
            if strength > len(parameters):
                continue
            first = covering_array(parameters, strength=strength)
            second = covering_array(parameters, strength=strength)
            assert first == second


def test_coverage_and_holes_ignore_the_order_of_the_rows() -> None:
    """A shuffled batch is the same batch. Reporting a different coverage for it
    would make a corpus's headline figure depend on the order its documents
    happened to be planned in."""
    rng = random.Random(8128)
    parameters = MIXED_SPACES[3]
    rows: list[Row] = list(covering_array(parameters, strength=1))
    expected_coverage = coverage(rows, parameters, strength=2)
    expected_holes = holes(rows, parameters, strength=2)
    assert expected_holes  # a strength-1 array leaves pairs uncovered; else this proves nothing
    for _ in range(10):
        rng.shuffle(rows)
        assert coverage(rows, parameters, strength=2) == expected_coverage
        assert holes(rows, parameters, strength=2) == expected_holes


def test_coverage_and_holes_ignore_the_order_of_the_parameters() -> None:
    """Coverage is a question about two sets. `holes` therefore reports each
    combination in parameter-*name* order rather than in the caller's order, so
    two callers who declared the same axes differently get identical output —
    which is what makes the result diffable."""
    rng = random.Random(8128)
    parameters = list(MIXED_SPACES[4])
    rows = list(covering_array(parameters, strength=1))
    expected_coverage = coverage(rows, parameters, strength=2)
    expected_holes = holes(rows, parameters, strength=2)
    for _ in range(10):
        rng.shuffle(parameters)
        assert coverage(rows, parameters, strength=2) == expected_coverage
        assert holes(rows, parameters, strength=2) == expected_holes


def test_a_reordered_space_is_still_covered() -> None:
    """The array itself may differ when the parameters are reordered — the
    construction takes them widest-first and breaks ties by the caller's order,
    so the caller's order is an input. What may not differ is whether it
    covers."""
    rng = random.Random(8128)
    parameters = list(STRUCTURE)
    for _ in range(5):
        rng.shuffle(parameters)
        rows = covering_array(parameters, strength=2)
        assert coverage(rows, parameters, strength=2) == 1.0


def test_holes_are_sorted_and_canonical() -> None:
    parameters = MIXED_SPACES[3]
    reported = holes(covering_array(parameters, strength=1), parameters, strength=2)
    assert reported == tuple(sorted(reported))
    for hole in reported:
        assert hole == tuple(sorted(hole))
        assert len(hole) == 2


# ---------------------------------------------------------------------------
# Coverage and holes agree with each other, and with the truth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strength", [1, 2, 3])
def test_coverage_is_the_complement_of_holes(strength: int) -> None:
    parameters = MIXED_SPACES[4]
    total = total_combinations(parameters, strength)
    full = list(covering_array(parameters, strength=strength))
    # Every prefix, so the agreement is checked at every level of partial
    # coverage rather than only at 0 and 1 where it is hard to get wrong.
    for keep in range(len(full) + 1):
        rows = full[:keep]
        missing = holes(rows, parameters, strength=strength)
        assert coverage(rows, parameters, strength=strength) == (total - len(missing)) / total


def test_a_reported_hole_is_really_absent() -> None:
    parameters = MIXED_SPACES[3]
    rows = covering_array(parameters, strength=2)[:4]
    for hole in holes(rows, parameters, strength=2):
        assert not any(all(row[name] == value for name, value in hole) for row in rows)


def test_no_rows_covers_nothing() -> None:
    assert coverage([], STRUCTURE, strength=2) == 0.0
    assert len(holes([], STRUCTURE, strength=2)) == total_combinations(STRUCTURE, 2)


def test_a_row_missing_a_parameter_covers_only_what_it_carries() -> None:
    """Rows arrive from callers that legitimately carry other keys, and a row
    that is silently treated as covering an axis it does not name would inflate
    every coverage figure this module reports."""
    parameters = space(a=2, b=2, c=2)
    partial: Row = {"a": "a-0", "b": "b-0"}
    assert holes([partial], parameters, strength=2) == (
        (("a", "a-0"), ("b", "b-1")),
        (("a", "a-0"), ("c", "c-0")),
        (("a", "a-0"), ("c", "c-1")),
        (("a", "a-1"), ("b", "b-0")),
        (("a", "a-1"), ("b", "b-1")),
        (("a", "a-1"), ("c", "c-0")),
        (("a", "a-1"), ("c", "c-1")),
        (("b", "b-0"), ("c", "c-0")),
        (("b", "b-0"), ("c", "c-1")),
        (("b", "b-1"), ("c", "c-0")),
        (("b", "b-1"), ("c", "c-1")),
    )


def test_an_undeclared_value_covers_nothing() -> None:
    parameters = space(a=2, b=2)
    assert coverage([{"a": "a-0", "b": "elsewhere"}], parameters, strength=2) == 0.0
    assert coverage([{"a": "a-0", "b": "elsewhere"}], parameters, strength=1) == 0.25


def test_extra_keys_are_ignored() -> None:
    parameters = space(a=2, b=2)
    rows = [dict(row, seed="8128") for row in covering_array(parameters, strength=2)]
    assert coverage(rows, parameters, strength=2) == 1.0


# ---------------------------------------------------------------------------
# Degenerate parameters and refusals
# ---------------------------------------------------------------------------


def test_one_parameter_at_strength_one() -> None:
    parameters = space(only=4)
    rows = covering_array(parameters, strength=1)
    assert [row["only"] for row in rows] == list(parameters[0].values)
    assert coverage(rows, parameters, strength=1) == 1.0


def test_no_parameters_is_refused_rather_than_covered() -> None:
    """An empty space has no combinations, so every answer about it is vacuous.
    Returning 1.0 for "we covered everything" would be the most misleading of
    them."""
    with pytest.raises(ValueError, match="strength must be between 1"):
        covering_array([])
    with pytest.raises(ValueError, match="strength must be between 1"):
        coverage([], [], strength=1)


@pytest.mark.parametrize("strength", [0, -1, 4])
def test_a_strength_outside_the_range_names_what_was_asked_for(strength: int) -> None:
    parameters = space(a=2, b=2, c=2)
    with pytest.raises(ValueError, match=f"\\(3\\), asked for {strength}"):
        covering_array(parameters, strength=strength)
    with pytest.raises(ValueError, match=f"\\(3\\), asked for {strength}"):
        coverage([], parameters, strength=strength)
    with pytest.raises(ValueError, match=f"\\(3\\), asked for {strength}"):
        holes([], parameters, strength=strength)


def test_a_single_valued_parameter_is_refused() -> None:
    with pytest.raises(ValueError, match="needs at least 2"):
        Parameter("scope", ("group",))
    with pytest.raises(ValueError, match="needs at least 2"):
        Parameter("scope", ())


def test_a_repeated_value_is_refused() -> None:
    with pytest.raises(ValueError, match="repeats value"):
        Parameter("density", ("tight", "loose", "tight"))


def test_an_unnamed_parameter_is_refused() -> None:
    with pytest.raises(ValueError, match="needs a name"):
        Parameter("", ("a", "b"))


def test_two_parameters_of_one_name_are_refused() -> None:
    """Rows are dicts keyed by name: two parameters sharing one would collapse
    into a single column, and every combination between them would report as
    covered by every row."""
    parameters = [Parameter("scope", ("a", "b")), Parameter("scope", ("c", "d"))]
    with pytest.raises(ValueError, match="appear more than once"):
        covering_array(parameters)
    with pytest.raises(ValueError, match="appear more than once"):
        coverage([], parameters)
