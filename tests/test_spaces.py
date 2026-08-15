"""The build-configuration space: the guarantee, and the finding it produces.

Two halves, and the second is the one that matters.

The first is the contract `spaces` inherits from `covering` and re-frames —
`cover` returns a fleet in which every *t*-way combination appears, `holes` is
the complement, `unvaried` is the blunter reading, and `archive_of` turns the
axes into niches. Checked by recomputing, never by pinning the algorithm's
output: a better IPOG would move every row count here and break nothing.

The second is `test_shipped_fleet_*`. A coverage primitive whose only evidence
is a synthetic example has not been shown to be worth having. These run the
repository's *actual* determinism gate — ``tools/sweep.py`` at the seed and
count its workflow ships — and ask what it never covered. The answer is a real
gap in real CI, named as a pair, and it is asserted here so that closing it
requires deleting a test rather than forgetting one.
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

import pytest

from worldloom import archetypes, domains, spaces
from worldloom.covering import Parameter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

#: Same door `tests/test_sweep.py` uses. The sweep is a tool rather than library
#: code — nothing under `src/` imports it — so it is reached by path and skipped
#: rather than failing if a checkout does not carry it.
sweep = pytest.importorskip("sweep")


def small(**widths: int) -> spaces.BuildSpace:
    """A space named by keyword, each axis carrying `width` values named for it."""
    return spaces.BuildSpace(tuple(
        Parameter(name, tuple(f"{name}-{i}" for i in range(width)))
        for name, width in widths.items()
    ))


# ---------------------------------------------------------------------------
# The space itself
# ---------------------------------------------------------------------------


def test_a_space_needs_an_axis() -> None:
    with pytest.raises(ValueError, match="at least one axis"):
        spaces.BuildSpace(())


def test_two_axes_may_not_share_a_name() -> None:
    # Refused at declaration and not at construction: `exhaustive` multiplies
    # widths, so a duplicate is already wrong before anything is covered.
    duplicate = (Parameter("a", ("x", "y")), Parameter("a", ("p", "q")))
    with pytest.raises(ValueError, match="appear more than once"):
        spaces.BuildSpace(duplicate)


def test_exhaustive_and_pair_counts_are_the_two_different_numbers() -> None:
    space = small(a=3, b=4, c=5)
    assert space.exhaustive == 60
    # Pairs, not configurations: 3x4 + 3x5 + 4x5.
    assert space.size_at(2) == 12 + 15 + 20
    assert space.size_at(1) == 3 + 4 + 5


def test_select_keeps_the_axes_named_in_the_order_named() -> None:
    space = small(a=2, b=3, c=4)
    assert space.select(("c", "a")).names == ("c", "a")
    with pytest.raises(KeyError, match="no axis 'd'"):
        space.select(("d",))


def test_row_is_the_strict_door() -> None:
    space = small(a=2, b=2)
    assert space.row(a="a-0", b="b-1") == {"a": "a-0", "b": "b-1"}
    # A typo'd value here would silently cover nothing downstream and read as a
    # hole in whatever built it, so it raises where a measured row would not.
    with pytest.raises(ValueError, match="not a value of axis 'a'"):
        space.row(a="nope", b="b-1")
    with pytest.raises(ValueError, match="missing axis/axes b"):
        space.row(a="a-0")


def test_repr_carries_no_address() -> None:
    # This repository diffs its own output; an address is a line that differs
    # between two runs of one seed.
    assert "0x" not in repr(small(a=2, b=3))
    assert repr(small(a=2, b=3)) == "BuildSpace(a(2) x b(3): 6 configurations)"


# ---------------------------------------------------------------------------
# Cover, and what it guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strength", [1, 2, 3])
def test_cover_covers_completely(strength: int) -> None:
    space = small(a=2, b=3, c=4, d=2, e=5)
    rows = spaces.cover(space, strength=strength)
    assert spaces.coverage(space, rows, strength=strength) == 1.0
    assert spaces.holes(space, rows, strength=strength) == ()


def test_cover_is_a_pure_function_of_the_space() -> None:
    # No `Rng`, no clock, no set iteration: a fleet plan is a checked-in
    # artifact, not a run to be repeated.
    space = small(a=3, b=4, c=2, d=5)
    assert spaces.cover(space) == spaces.cover(space)


def test_holes_are_exactly_what_is_missing() -> None:
    space = small(a=2, b=2)
    rows = [space.row(a="a-0", b="b-0"), space.row(a="a-1", b="b-1")]
    assert spaces.holes(space, rows) == (
        (("a", "a-0"), ("b", "b-1")),
        (("a", "a-1"), ("b", "b-0")),
    )
    assert spaces.coverage(space, rows) == 0.5


def test_unvaried_names_the_knob_nobody_turned() -> None:
    space = small(a=3, b=2, c=2)
    rows = [{"a": "a-0", "b": "b-0"}, {"a": "a-1", "b": "b-0"}]
    # `b` is constant across the fleet; `c` is not mentioned by any row at all.
    # Both are the same finding — a knob that was never turned — arrived at by
    # constancy and by omission.
    assert spaces.unvaried(space, rows) == ("b", "c")


# ---------------------------------------------------------------------------
# The archive over a space
# ---------------------------------------------------------------------------


def test_a_pairwise_fleet_fills_every_two_axis_archive() -> None:
    """The two primitives meeting, and the reason to have both.

    A covering array at strength 2 covers every pair, and an archive over *any*
    two axes has exactly the pairs of those two axes as its niches — so a
    pairwise fleet fills such an archive completely, for every choice of the two.
    That is a property, not a coincidence, and it is what makes `cover` a
    generation target for a quality-diversity loop rather than only a test plan.
    """
    space = small(a=3, b=4, c=2, d=5)
    fleet = spaces.cover(space, strength=2)
    for left, right in itertools.combinations(space.names, 2):
        over = (left, right)
        grid = spaces.archive_of(space, over=over)
        for index, row in enumerate(fleet):
            # Fitness is the caller's; a constant one here says only that every
            # niche is reached, which is the claim being made.
            grid.consider(f"row-{index:02d}", spaces.niche_of(space, row, over=over), 0.0)
        assert grid.holes() == ()
        assert grid.fill() == 1.0
        assert grid.capacity() == len(space.axis(left).values) * len(space.axis(right).values)


def test_archive_of_defaults_to_the_whole_grid() -> None:
    space = small(a=2, b=3)
    assert spaces.archive_of(space).capacity() == 6


def test_niche_of_refuses_a_row_that_has_no_niche() -> None:
    space = small(a=2, b=2)
    with pytest.raises(ValueError, match="no value for b"):
        spaces.niche_of(space, {"a": "a-0"})


# ---------------------------------------------------------------------------
# The real space
# ---------------------------------------------------------------------------


def test_build_space_reads_the_archetype_registry() -> None:
    # Derived rather than typed, for `tools/sweep.py`'s reason: a hand-written
    # list is stale the moment somebody registers an archetype, and a coverage
    # number that stops covering a new value still reports a percentage.
    assert spaces.build_space().axis("archetype").values == tuple(archetypes.available())


def test_build_space_has_a_value_that_is_legal_on_every_engine() -> None:
    """The projection targets, checked as a set.

    A single-episode vertical refuses `--incident`, `--timeline`,
    `--conversations`, `--actors` and a non-`standard` `--eval-density`, and
    procurement refuses `--estate`. This space does not encode that, so what it
    must guarantee instead is that every constrained axis carries a value a
    caller can honestly *project to* — otherwise a row for those engines has no
    legal spelling and the fleet has to leave the axis out, which reads as a
    hole rather than as the collapse it is.
    """
    space = spaces.build_space()
    for name, legal in (("history", "unforced"), ("estate", "none"),
                        ("knowledge", "none"), ("eval_density", "standard"),
                        ("storyline", "fixed")):
        assert legal in space.axis(name).values


@pytest.mark.parametrize("strength", [1, 2, 3])
def test_the_real_space_is_covered_completely(strength: int) -> None:
    space = spaces.build_space()
    rows = spaces.cover(space, strength=strength)
    assert spaces.coverage(space, rows, strength=strength) == 1.0


def test_pairwise_is_within_a_quarter_of_the_floor() -> None:
    """IPOG's quality on the space that matters, bounded from both sides.

    The floor is exact arithmetic rather than a measurement — the two widest
    axes must each take every value, so no pairwise array over this space is
    shorter than their product — and it is computed from the space so that
    registering an archetype moves it rather than breaking this. The ceiling is
    the guard: a greedy construction that started returning twice the floor
    would still pass a coverage assertion, and this is the only test that would
    notice.
    """
    space = spaces.build_space()
    widths = sorted((len(axis.values) for axis in space.axes), reverse=True)
    floor = widths[0] * widths[1]
    rows = spaces.cover(space, strength=2)
    assert floor <= len(rows) <= math.ceil(floor * 1.25)
    # The saving is the reason to bother, and it is four orders of magnitude.
    assert space.exhaustive > 1000 * len(rows)


# ---------------------------------------------------------------------------
# The shipped fleet, and what it never covered
# ---------------------------------------------------------------------------


def fleet_rows() -> list[spaces.Row]:
    """``tools/sweep.py``'s shipped selection, as rows of `build_space`.

    The mapping is a projection in both directions and is written out rather
    than hidden in a comprehension, because each line is a claim about what the
    sweep actually builds:

    * the sweep's `None` locale means the flag was not given, which is this
      space's `"none"`;
    * `None` messiness is `pristine`, since that profile writes nothing and is
      the flag's own default — the one axis where omission and a named value are
      the same build;
    * the sweep forces `--incident` on retail and gives no incident flag at all
      elsewhere, which is `unforced`;
    * five axes the sweep has no knob for take the value a build with no flag
      gets, because that is the build it ran. Leaving them out would be the
      lie — it would report the sweep as *silent* on `--policies` when it in
      fact ships a corpus with no policies in it every single night.
    """
    rows: list[spaces.Row] = []
    for config in sweep.field_of(8, seed=8128).configs:
        rows.append({
            "archetype": config.archetype,
            "locale": config.locale or "none",
            "estate": config.estate or "none",
            "messiness": config.messiness or "pristine",
            "periods": str(config.periods),
            "surface": config.surface,
            "history": "incident" if config.engine == "retail" else "unforced",
            "policies": "none",
            "storyline": "fixed",
            "genome": "authored",
            "eval_density": "standard",
            "knowledge": "none",
        })
    return rows


def test_shipped_fleet_leaves_most_of_the_space_uncovered() -> None:
    space = spaces.build_space()
    rows = fleet_rows()
    assert len(rows) == 8
    covered = spaces.coverage(space, rows)
    # Measured at 0.2397 on this tree. Asserted as a band rather than a figure:
    # the number moves when a registry gains a value, and what is being claimed
    # is the size of the gap, not its fourth decimal place.
    assert 0.15 < covered < 0.35, covered
    # The two readings are complements of one another by construction, and a
    # module that let them drift apart would be reporting two coverage numbers.
    missing = spaces.holes(space, rows)
    assert covered == pytest.approx(1 - len(missing) / space.size_at(2))


def test_shipped_fleet_never_turns_five_of_the_twelve_knobs() -> None:
    """The blunt reading, and the one to take first.

    These five are not axes the sweep sampled badly — they are axes it has no
    enumeration for at all, so several hundred of its holes are consequences of
    five causes. That distinction is invisible in a coverage percentage and is
    the whole reason `unvaried` exists.
    """
    assert spaces.unvaried(spaces.build_space(), fleet_rows()) == (
        "policies", "storyline", "genome", "eval_density", "knowledge",
    )


def test_every_remaining_multi_period_hole_is_one_a_domain_declares() -> None:
    """The finding `holes` produced that nothing else here could, and its fix.

    As found: ``sweep._config`` collapsed `periods` to 1 for *every*
    single-episode vertical, citing a CLI refusal that no longer exists —
    `cli.py` runs ``for index in range(max(1, periods))`` on that branch, and a
    three-quarter ``midsize_adi`` build validates clean at 4,237 checks. So the
    byte-identity gate, the one thing standing between this repository and a
    corpus that does not replay, had never once compared two builds of a bank or
    a contractor beyond a single period, and no number of rotating nights could
    reach one because the projection forbade it.

    The collapse now reads ``domains.Domain.max_periods``, which a domain states
    the way it states ``period_step_months``. So the assertion inverts into the
    stronger one: **every archetype × periods pair this fleet never covers
    belongs to a domain that declared a cap.** A hole with no declaration behind
    it is the old bug returning, and this fails rather than being deleted.

    Asserted at 30 seeds and not one, deliberately. The nightly job rotates its
    seed, so a gap in a single night is a sampling accident and proves nothing;
    a gap that survives 240 configurations is structural.
    """
    space = spaces.build_space()
    rows: list[spaces.Row] = []
    for seed in range(1, 31):
        for config in sweep.field_of(8, seed=seed).configs:
            rows.append({
                "archetype": config.archetype,
                "periods": str(config.periods),
                "estate": config.estate or "none",
            })
    assert len(rows) == 240
    over = space.select(("archetype", "periods"))
    missing = set(spaces.holes(over, rows))

    # The two that were unreachable by construction are now covered.
    assert (("archetype", "midsize_adi"), ("periods", "3")) not in missing
    assert (("archetype", "omnichannel_retailer"), ("periods", "3")) not in missing

    for (_, archetype), (_, periods) in missing:
        domain = domains.for_archetype(archetype)
        cap = None if domain is None else domain.max_periods
        assert cap is not None and int(periods) > cap, (
            f"{archetype} never reaches --periods {periods} and its domain"
            " declares no cap that would explain it — which is how the last one"
            " of these hid: an assumption in the planner, not a stated limit"
        )


def test_the_gate_now_reaches_a_twelve_period_corpus() -> None:
    """The second structural gap, found by this module and since closed.

    As written, `sweep.axes()` enumerated `periods` as `(1, 2, 3)`, so no
    configuration it could ever select carried a year — and a twelve-period
    corpus is where seasonality, a trend and the twelve-copies-of-one-shape
    problem all first appear, which made it simultaneously the part of the space
    most likely to hold a determinism defect and the part the gate structurally
    could not see. That is the distinction `BuildSpace.select` exists to draw:
    not "the fleet chose badly" but "the knob has no front door".

    The axis now reaches 12 and the shipped eight-configuration selection
    carries it twice, so the assertion is inverted rather than deleted. Deleting
    it would leave nothing standing between the axis and somebody trimming it
    back to `(1, 2, 3)` on cost grounds without seeing what that costs.
    """
    space = spaces.build_space()
    rows = fleet_rows()
    assert "12" in space.axis("periods").values
    assert any(row["periods"] == "12" for row in rows), (
        "the shipped sweep selects no twelve-period corpus; the axis reaching a"
        " year is what makes seasonality and trend reachable by the gate at all"
    )


def test_a_pairwise_plan_would_close_every_one_of_those_gaps() -> None:
    """The other half of the claim: the gaps are not inherent to a small fleet.

    Thirty-nine rows — five times the sweep's eight, and a fraction of the 240
    it builds over a month — cover every pair in the space, including every one
    the assertions above name. A fleet this size is a planning decision rather
    than a budget, which is the difference this module is arguing for.
    """
    space = spaces.build_space()
    plan = spaces.cover(space, strength=2)
    assert spaces.holes(space, plan) == ()
    assert spaces.unvaried(space, plan) == ()
    assert len(plan) < 60
