"""The reserving cycle as authored data: `examples/packs/longtail-insurer.json`.

The shipped insurer's reserving episode is hand-written Python
(`generators/reserving.py`, `generators/triangles.py`) and is capped at one
valuation quarter by `insurance_scenarios.QuarterlyReserving`'s own phase
guard. This pack is the same cycle expressed on the cohort axis instead —
four accident quarters allocated from a book-level central estimate, each
cohort's previous carrying value read back off its own row, and a booked
reserve standing below the actuary's estimate — and the thing worth pinning
is that it runs *twice*, which is what the hand-written one cannot do.

Four claims, each of which would rot silently:

- **The grid is the shipped insurer's.** `2026-03 → (2025-03 … 2025-12)`, and
  `2026-06` slides one quarter. If the axis arithmetic moved, an authored
  triangle and the generated one would be about different quarters.
- **Every valuation's cells reconcile to their parent exactly.** Not within a
  tolerance: `allocation_of` splits by largest remainder, so the crumb has
  nowhere to go, and a check that only ever passes on correct arithmetic is
  what catches the arithmetic changing.
- **The second quarter derives from the first.** `prior_in_cohort` reads what
  *this same cohort* was carried at, and zero for a cohort making its first
  appearance — the diagonal step, which is the one thing the period axis
  cannot take.
- **It rebuilds from its own recipe with no pack file on hand.** The recipe
  embeds the pack, the pack installs the spec, and the `AuthoredEpisode` steps
  find it — which is the whole argument for authoring an episode as data
  rather than as a generator.

The registry-restoring fixture is `tests/test_cohorts.py`'s, for its reason
verbatim: installing a spec also registers its derived check group, which
`validate` then runs against every world for the rest of the session, and a
test may add to a registry but may not leave anything in one.
"""

from __future__ import annotations

import json

import pytest

from worldloom import InsuranceWorld, World, cohorts, episodes, packs
from worldloom import recipe as recipe_module
from worldloom import validate as validate_module

PACK = "examples/packs/longtail-insurer.json"
EPISODE = "QuarterlyValuation"
SEED = 8128

#: The two valuations, and the grid each observes. The first is the shipped
#: insurer's own (verified in `dist/fleet/insurer/facts.jsonl`); the second is
#: the same axis one stride on, which is what makes three of its four cohorts
#: a diagonal rather than a fresh grid.
QUARTERS = ("2026-03", "2026-06")
GRIDS = {
    "2026-03": ("2025-03", "2025-06", "2025-09", "2025-12"),
    "2026-06": ("2025-06", "2025-09", "2025-12", "2026-03"),
}

_REGISTRIES = (
    lambda: episodes._LOADED,
    lambda: episodes._REGISTERED_CHECKS,
    lambda: validate_module._DOMAIN_CHECKS,
)


@pytest.fixture(autouse=True)
def _restore_the_registries():
    saved = [(registry(), dict(registry())) for registry in _REGISTRIES]
    try:
        yield
    finally:
        for registry, original in saved:
            registry.clear()
            registry.update(original)


def _built() -> World:
    """The pack's own insurer, two consecutive valuations deep."""
    pack = packs.load(PACK)
    world = InsuranceWorld.from_pack(pack, seed=SEED).build()
    for quarter in QUARTERS:
        world = world.run(episodes.AuthoredEpisode(episode=EPISODE, period=quarter))
    return world.compile()


def _column(world: World, kind: str, at) -> dict[str, float]:
    """One valuation's view of a grid, by cohort."""
    return {
        fact.period: fact.value.amount
        for fact in world.facts
        if fact.kind == kind and fact.valid_from == at
    }


def _valuations(world: World) -> list:
    """The moments the book's central estimate was set, oldest first."""
    return sorted(
        fact.valid_from for fact in world.facts
        if fact.kind == "reserves.central_estimate_total"
    )


# ---------------------------------------------------------------------------
# The pack itself
# ---------------------------------------------------------------------------


def test_the_pack_lints_clean_against_the_insurance_engine() -> None:
    """Nothing authored here is a claim the engine cannot honour.

    `packs.lint` runs the episode lint, the LOB slot bindings, the doctype
    lint and the lore-target check together — which is the only reading that
    catches a process declaring a seat no line of business sits in.
    """
    assert packs.lint(packs.load(PACK)) == []


def test_the_episode_declares_the_shipped_insurers_axis() -> None:
    """Four accident quarters, three months apart, the newest a quarter behind.

    Read off the pack rather than restated, so editing the axis fails here
    instead of quietly producing a different triangle.
    """
    packs.archetype_of(packs.load(PACK))  # installs the spec
    axis = episodes.loaded()[EPISODE].cohorts[0]
    assert (axis.name, axis.count, axis.spacing_months, axis.lag_months) == (
        "accident_quarter", 4, 3, 3,
    )
    for period, grid in GRIDS.items():
        assert episodes.cohort_periods(period, axis) == grid


# ---------------------------------------------------------------------------
# Two quarters, which is the point
# ---------------------------------------------------------------------------


def test_two_consecutive_valuations_each_mint_a_whole_grid() -> None:
    """One cell per declared cohort per valuation, and the grid slides.

    The hand-written episode refuses its second run outright
    (`QuarterlyReserving.run`'s phase guard); this is the same cycle running
    twice with the second observing a grid the first did not.
    """
    world = _built()
    moments = _valuations(world)
    assert len(moments) == 2

    for at, period in zip(moments, QUARTERS):
        assert tuple(sorted(_column(world, "reserves.ultimate", at))) == tuple(
            sorted(GRIDS[period])
        )


def test_every_valuations_cells_roll_up_to_their_parent_exactly() -> None:
    """To the cent, and by construction rather than by luck.

    `allocation_of` splits the parent by largest remainder, so this is an
    equality and not a tolerance — the same discipline `triangles.py` states
    for itself one layer down.
    """
    world = _built()
    for at in _valuations(world):
        parent = next(
            fact for fact in world.facts
            if fact.kind == "reserves.central_estimate_total" and fact.valid_from == at
        )
        cells = _column(world, "reserves.ultimate", at)
        assert sum(cells.values()) == parent.value.amount


def test_the_second_quarter_reads_the_first_quarters_cells() -> None:
    """The diagonal: each carried-over cohort's comparative is the *first*
    valuation's figure for that same cohort, and the cohort making its first
    appearance reads zero.

    Zero rather than absent, for `prior(K)`'s reason exactly: "nothing had
    emerged yet" is a claim about the record, not a hole in it.
    """
    world = _built()
    first, second = _valuations(world)

    was = _column(world, "reserves.ultimate", first)
    now = _column(world, "reserves.ultimate_at_prior_valuation", second)

    carried = set(GRIDS["2026-03"]) & set(GRIDS["2026-06"])
    assert len(carried) == 3
    for cohort in carried:
        assert now[cohort] == was[cohort]

    arrived, = set(GRIDS["2026-06"]) - set(GRIDS["2026-03"])
    assert now[arrived] == 0


def test_a_carried_cohorts_cell_supersedes_its_own_predecessor() -> None:
    """Cell by cell, never wholesale — which is what keeps a *row* readable.

    A single grid-level supersession would leave "what did we think this
    cohort was worth last quarter" unanswerable for every cohort but one, and
    that question is the reason the grid is keyed by cohort at all.
    """
    world = _built()
    first, second = _valuations(world)
    was = {
        fact.period: fact for fact in world.facts
        if fact.kind == "reserves.ultimate" and fact.valid_from == first
    }
    now = {
        fact.period: fact for fact in world.facts
        if fact.kind == "reserves.ultimate" and fact.valid_from == second
    }
    for cohort in set(GRIDS["2026-03"]) & set(GRIDS["2026-06"]):
        assert now[cohort].supersedes == was[cohort].id
        # And the predecessor's window closes exactly where the successor
        # opens, so "what did this cohort hold at time T" has one answer for
        # every T rather than two between the observations.
        assert was[cohort].valid_to == now[cohort].valid_from

    # The cohort that dropped out of view is left alone: nothing replaced it,
    # so nothing closes it. A valuation that no longer looks at a quarter has
    # not thereby retracted what it last said about it.
    dropped, = set(GRIDS["2026-03"]) - set(GRIDS["2026-06"])
    assert was[dropped].valid_to is None


def test_the_booked_reserve_stands_below_the_central_estimate_every_quarter() -> None:
    """The standing disagreement, at both valuations.

    Guaranteed rather than risked: the release is a multiple of the standing
    margin drawn from a span the registry holds strictly above 1.0, so the
    margin left over is negative and the booked total is short by exactly
    that much. A quarter where the gap failed to open would be a corpus that
    no longer poses the contest this vertical exists for.
    """
    world = _built()

    def stated(kind: str, at) -> object:
        """This valuation's figure of *kind* — the earliest one dated at or
        after the moment the central estimate was set, because the decision
        that sizes the release and the ledger posting that follows it are
        staged hours apart *within* one valuation."""
        return min(
            (fact for fact in world.facts
             if fact.kind == kind and fact.valid_from >= at),
            key=lambda fact: (fact.valid_from, fact.id),
        )

    for at in _valuations(world):
        central, booked, margin, gap = (
            stated(kind, at)
            for kind in ("reserves.central_estimate_total", "reserves.booked_total",
                         "reserves.risk_margin_remaining", "reserves.held_vs_central_gap")
        )
        assert margin.value.amount < 0
        assert booked.value.amount == round(central.value.amount + margin.value.amount, 2)
        assert gap.value.amount == round(central.value.amount - booked.value.amount, 2)
        assert gap.value.amount > 0


# ---------------------------------------------------------------------------
# The checks, and the replay
# ---------------------------------------------------------------------------


def test_the_two_quarter_corpus_validates_clean() -> None:
    """Including the cohort group, which only runs where the spec is installed.

    Stated because it is the one check group a corpus cannot carry with it:
    `cohorts._specs()` reads the *process* registry, so `worldloom validate`
    on a corpus directory in a process that never installed the pack skips
    the grid entirely. Here the spec is installed, so the roll-up and the
    grid completeness are actually exercised.
    """
    world = _built()
    report = world.validate()
    assert report.violations == []

    violations, checks = cohorts.check(list(world.facts), (episodes.loaded()[EPISODE],))
    assert violations == []
    assert checks > 0


def test_it_rebuilds_from_its_own_recipe_with_no_pack_file(tmp_path) -> None:
    """The recipe embeds the pack; the pack installs the spec; the steps find it.

    Facts compared as serialised JSON rather than by count, because the whole
    claim of an authored episode is that the *same figures* come back — a
    count would pass on a world that drew everything differently.
    """
    world = _built()
    exported = world.export(tmp_path / "corpus", overwrite=True)
    recipe = json.loads((exported / "world.json").read_text(encoding="utf-8"))["recipe"]
    assert [step["scenario"] for step in recipe["steps"]] == ["AuthoredEpisode"] * 2

    # The registries are cleared first so the rebuild is proved to install the
    # spec itself: with it left over from the build above, a recipe that
    # failed to carry the pack would still replay and the test would say
    # nothing about the seam it exists to pin.
    for registry in _REGISTRIES:
        registry().clear()
    again = recipe_module.rebuild(recipe).compile()

    assert [fact.model_dump(mode="json") for fact in again.facts] == [
        fact.model_dump(mode="json") for fact in world.facts
    ]
