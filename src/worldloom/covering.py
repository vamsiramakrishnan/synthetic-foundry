"""Mixed covering arrays: every combination of *t* choices, by construction.

The measured problem this exists to fix: structural variety in this project is
currently *sampled* and then counted afterwards. `compiler.diversity` reports
40 distinct shapes over 249 artifacts and `dispersion.farthest_first` spreads
candidates apart, but neither can answer "did we ever produce a tight-density
unit-scoped section under the supply-shock storyline?" with anything better
than a grep over what happened to come out. A sampler has no stopping
condition either: "generate 200 documents" is a budget, not a target, and
nobody can say which 200.

A covering array answers both by construction. At strength *t*, every
combination of *t* parameter values appears in at least one row, so coverage is
a percentage with a defensible target of 100% and generation stops when the
array is exhausted rather than when a counter runs out. The saving is the
reason to bother: the eight-axis space this project actually has —
``scope(3) × density(3) × storyline(6) × style(5) × four binary section
flags`` — is 4,320 full combinations, and **30 rows** cover every pair of them
here. Thirty is not merely small, it is optimal: the two widest parameters
alone force 6 × 5 rows, so no pairwise array over this space can be shorter.
Five binary parameters take **7 rows** at t=2 and **12** at t=3, against 32
exhaustive.

The construction is IPOG (Lei et al., following NIST's work on combinatorial
interaction testing): build the exhaustive array over the first *t* parameters,
then bring in one parameter at a time by *horizontal growth* — extend every
existing row with the value of the new parameter that covers the most
still-uncovered combinations — followed by *vertical growth*, which adds or
repairs rows for whatever horizontal growth could not reach. It is greedy and
therefore not optimal; the arrays it produces are within a few rows of the best
known for spaces this size, and no exact method is affordable in general
because the problem is NP-hard.

Nothing here knows about worlds, documents or parameters-of-a-build: it takes
named string axes and hands back rows, which is what lets structure generation,
the document planner and `tools/sweep.py` share one notion of "covered".

Deterministic, and with no ``Rng`` at all — not even a seeded one. The greedy
choices tie constantly (five binary parameters tie on the very first row), and
a tie broken by ``max()`` over a ``set`` is exactly the non-determinism CI's
byte-diff catches. Every tie here breaks by parameter order and then by value
order, both stated at the point they are taken.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

#: One configuration: every parameter's name mapped to the value it takes.
#: Keyed in the caller's parameter order, which is the one ordering of a row a
#: caller stated on purpose.
Row = dict[str, str]

#: A *t*-way combination as it is reported: ``(name, value)`` pairs, ordered by
#: parameter name. See :func:`holes` for why the name and not the position.
Combination = tuple[tuple[str, str], ...]

#: The same thing while IPOG is working on it: ``(index, value index)`` pairs,
#: ordered by parameter index. Indices rather than strings because the inner
#: loops are set-membership tests on these, and because the working parameter
#: order is not the caller's (see :func:`covering_array`).
_Cell = tuple[int, int]
_Combo = tuple[_Cell, ...]


@dataclass(frozen=True)
class Parameter:
    """A named axis of a configuration space, and the values it may take."""

    name: str
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a parameter needs a name; rows are keyed by it")
        if len(self.values) < 2:
            raise ValueError(
                f"parameter {self.name!r} has {len(self.values)} value(s), needs at"
                " least 2; a one-valued parameter is a constant, and admitting it"
                " would let a caller report 100% coverage of a space that has no"
                " choice in it"
            )
        repeated = sorted({v for v in self.values if self.values.count(v) > 1})
        if repeated:
            raise ValueError(
                f"parameter {self.name!r} repeats value(s) {', '.join(repeated)};"
                " a repeated value is covered twice and reads as two rows of"
                " coverage that are one row"
            )


def covering_array(
    parameters: Sequence[Parameter], *, strength: int = 2
) -> tuple[Row, ...]:
    """Rows in which every combination of *strength* values appears at least once.

    Mixed cardinalities are the case this is built for — 2 scopes, 3 densities,
    6 storylines is the realistic shape here, not five booleans — so nothing
    below assumes a uniform domain size.

    A pure function of its arguments: no ``Rng``, no randomness, no clock. Rows
    come back in the order IPOG built them, which is stable for equal inputs.
    """
    _validate(parameters, strength)

    # IPOG is sensitive to the order it takes parameters in, and descending
    # domain size is the standard heuristic: the exhaustive seed is built over
    # the *widest* parameters, so the rows that must exist anyway do the most
    # work, and every later parameter has enough rows to spread its values
    # across. It is a heuristic and not a rule — on the eight-axis space in the
    # module docstring it saves a row at t=2 (30 against 31, and 30 is optimal)
    # and costs eight at t=3 (102 against 94) — but over a randomised sweep of
    # 61 (space, strength) cases it produced the shorter array 54 times and the
    # longer one 7. Ties, meaning parameters of equal width, keep the caller's
    # order: a sort key of ``-width`` alone would leave equal-width parameters
    # wherever the sort found them, which is stable in CPython and is not a
    # property this module should be quietly relying on.
    order = sorted(range(len(parameters)), key=lambda j: (-len(parameters[j].values), j))
    widths = tuple(len(parameters[j].values) for j in order)

    rows: list[Row] = []
    for test in _ipog(widths, strength):
        chosen = [0] * len(parameters)
        for position, j in enumerate(order):
            chosen[j] = test[position]
        rows.append({p.name: p.values[chosen[j]] for j, p in enumerate(parameters)})
    return tuple(rows)


def coverage(
    rows: Sequence[Row], parameters: Sequence[Parameter], *, strength: int = 2
) -> float:
    """The fraction in ``[0, 1]`` of *strength*-way combinations `rows` covers.

    Invariant to the order of `rows` and to the order of `parameters`: it is a
    question about two sets, and reporting a different number for a shuffled
    batch would make the headline figure of a corpus depend on the order its
    documents were planned in.

    A row missing a parameter, or carrying a value the parameter does not
    declare, covers no combination involving it rather than raising. Rows here
    come from generators that legitimately carry extra keys, and a partially
    understood row is a coverage question, not an error.
    """
    total, uncovered = _shortfall(rows, parameters, strength)
    # ``total`` cannot be zero: _validate forces at least one parameter, and a
    # Parameter carries at least two values.
    return (total - len(uncovered)) / total


def holes(
    rows: Sequence[Row], parameters: Sequence[Parameter], *, strength: int = 2
) -> tuple[Combination, ...]:
    """The combinations `rows` never produced, sorted.

    This is the actionable half of :func:`coverage` — 96% is a number, and the
    fourteen combinations behind it are a work list.

    Both orderings are canonical rather than positional: the pairs inside one
    hole are sorted by parameter *name*, and the holes among themselves sort
    lexicographically on those pairs. So the result is a pure function of the
    set of rows and the set of parameters, and two callers who declared the
    same axes in different orders get diffable output. Ordering pairs by
    parameter position instead would have been friendlier to read and would
    have made that false.
    """
    _, uncovered = _shortfall(rows, parameters, strength)
    return uncovered


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(parameters: Sequence[Parameter], strength: int) -> None:
    if strength < 1 or strength > len(parameters):
        raise ValueError(
            f"strength must be between 1 and the number of parameters"
            f" ({len(parameters)}), asked for {strength}"
        )
    names = [p.name for p in parameters]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise ValueError(
            f"parameter name(s) {', '.join(repeated)} appear more than once; a row"
            " is a dict keyed by name, so two parameters sharing one would collapse"
            " into a single column and every combination between them would report"
            " as covered"
        )


# ---------------------------------------------------------------------------
# Measuring coverage
# ---------------------------------------------------------------------------


def _shortfall(
    rows: Sequence[Row], parameters: Sequence[Parameter], strength: int
) -> tuple[int, tuple[Combination, ...]]:
    """``(how many combinations exist, which of them nothing covers)``."""
    _validate(parameters, strength)
    names = [p.name for p in parameters]

    present: set[Combination] = set()
    for row in rows:
        held = [row.get(name) for name in names]
        for subset in itertools.combinations(range(len(parameters)), strength):
            # A combination reaching a parameter this row does not carry is not
            # covered by it. Skipped rather than recorded under a placeholder
            # value, because "" is a legal parameter value and a placeholder
            # would collide with it.
            if any(held[j] is None for j in subset):
                continue
            present.add(tuple((names[j], held[j]) for j in subset))  # type: ignore[misc]

    total = 0
    uncovered: list[Combination] = []
    for combination in _all_combinations(parameters, strength):
        total += 1
        if combination not in present:
            uncovered.append(combination)
    # Sorted, not merely built in order: the generator walks parameters by
    # position, and the contract of ``holes`` is name order (see its docstring).
    return total, tuple(sorted(tuple(sorted(c)) for c in uncovered))


def _all_combinations(
    parameters: Sequence[Parameter], strength: int
) -> Iterator[Combination]:
    """Every *strength*-way combination, by parameter position then value order."""
    for subset in itertools.combinations(range(len(parameters)), strength):
        pools = [parameters[j].values for j in subset]
        for values in itertools.product(*pools):
            yield tuple(
                (parameters[j].name, value)
                for j, value in zip(subset, values, strict=True)
            )


# ---------------------------------------------------------------------------
# IPOG
# ---------------------------------------------------------------------------


def _ipog(widths: Sequence[int], strength: int) -> tuple[tuple[int, ...], ...]:
    """IPOG over domain sizes alone, returning rows of value indices.

    Rows carry ``None`` internally for a parameter no combination has pinned
    yet — IPOG's "don't care" — because a free cell is what lets vertical
    growth repair an existing row instead of adding one. They are filled in
    before returning; see the bottom of this function.
    """
    count = len(widths)
    # The seed: the exhaustive array over the first ``strength`` parameters.
    # Every t-way combination among them is covered because all of them are
    # present, which is the base case IPOG grows from.
    tests: list[list[int | None]] = [
        list(combination) + [None] * (count - strength)
        for combination in itertools.product(*(range(w) for w in widths[:strength]))
    ]

    for i in range(strength, count):
        remaining = set(_combinations_reaching(widths, i, strength))

        # Horizontal growth: give every existing row a value for parameter i,
        # preferring whichever covers the most combinations still outstanding.
        for test in tests:
            best_value, best_covered = 0, ()
            for value in range(widths[i]):
                covered = tuple(
                    combination
                    for combination in _combinations_through(test, i, value, strength)
                    if combination in remaining
                )
                # Strict ``>``, so the first value to reach the best score keeps
                # it. Ties are the common case rather than the exception — every
                # row of a five-binary array ties on the first parameter it
                # grows — and ``max()`` over a set of equal scores would pick
                # whatever the set iterated first, which is the shape of
                # non-determinism this repository fails CI on.
                if len(covered) > len(best_covered):
                    best_value, best_covered = value, covered
            test[i] = best_value
            remaining.difference_update(best_covered)

        # Vertical growth: whatever horizontal growth could not reach, either
        # written into a row's free cells or given a row of its own.
        for combination in sorted(remaining):
            # Sorted before iterating, and re-checked for membership: placing
            # one combination usually covers others (a repaired row covers every
            # t-way combination its now-assigned cells make), and the placement
            # below removes them as it goes.
            if combination not in remaining:
                continue
            for test in tests:
                if all(test[j] is None or test[j] == value for j, value in combination):
                    for j, value in combination:
                        test[j] = value
                    remaining.difference_update(_covered_by(test, i, strength))
                    break
            else:
                fresh: list[int | None] = [None] * count
                for j, value in combination:
                    fresh[j] = value
                tests.append(fresh)
                remaining.difference_update(_covered_by(fresh, i, strength))

    # Free cells left over are genuinely free: every combination is already
    # covered, so any value keeps the array covering. The first value is chosen
    # because *some* choice has to be made and this one does not depend on
    # anything — filling from a hash of the row, say, would be equally valid and
    # would make the array a function of the value strings rather than of the
    # space's shape.
    return tuple(tuple(0 if cell is None else cell for cell in test) for test in tests)


def _combinations_reaching(
    widths: Sequence[int], i: int, strength: int
) -> Iterator[_Combo]:
    """Every *strength*-way combination that involves parameter ``i``.

    These are exactly the combinations parameter ``i``'s arrival makes possible;
    everything among ``0..i-1`` was covered by the previous round, which is the
    induction IPOG's correctness rests on.
    """
    for subset in itertools.combinations(range(i), strength - 1):
        for values in itertools.product(*(range(widths[j]) for j in subset)):
            for value in range(widths[i]):
                yield tuple(zip(subset, values, strict=True)) + ((i, value),)


def _combinations_through(
    test: Sequence[int | None], i: int, value: int, strength: int
) -> tuple[_Combo, ...]:
    """The combinations `test` would cover if parameter ``i`` took `value`.

    Only assigned cells count: a free cell covers nothing, which is why a row
    fresh out of vertical growth stops contributing to horizontal growth's
    counts until later rounds fill it.
    """
    assigned = [j for j in range(i) if test[j] is not None]
    return tuple(
        tuple([(j, test[j]) for j in subset] + [(i, value)])  # type: ignore[misc]
        for subset in itertools.combinations(assigned, strength - 1)
    )


def _covered_by(test: Sequence[int | None], i: int, strength: int) -> tuple[_Combo, ...]:
    """The combinations involving parameter ``i`` that `test` covers as it stands."""
    if test[i] is None:
        return ()
    return _combinations_through(test, i, test[i], strength)


__all__ = ["Combination", "Parameter", "Row", "covering_array", "coverage", "holes"]
