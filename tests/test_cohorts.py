"""The cohort axis: origin cohort × observation date, as declared data.

A loss triangle, a vintage curve, a hiring cohort and a warranty book are one
shape — a two-axis grid — and the episode grammar had one axis until now, which
is the real reason the shipped insurer's reserving episode is hand-written
Python capped at a single quarter. These tests are the acceptance suite for the
second axis, written against the cohort contract rather than against the
implementation, so they say what the axis *must* do rather than what some code
happens to do.

Five claims, each pinned where it could silently rot:

- **The grid is arithmetic, not a table.** ``period``, ``count``,
  ``spacing_months`` and ``lag_months`` determine the cohorts exactly, and the
  shipped insurer's ``2026-03 → (2025-03 … 2025-12)`` is the acceptance case.
- **A cohort fact is keyed by its cohort.** ``CanonicalFact.period`` carries the
  *origin*, never the valuation — the decision the existing
  ``generators/reserving.py`` already made and the reason no new field goes on
  ``CanonicalFact``.
- **A grid reconciles to its parent by construction.** ``allocation_of(K)``
  splits by largest remainder, so the cells sum to the parent exactly rather
  than nearly — including when the division does not come out even, which is
  the case that actually exercises the remainder.
- **A cohort walks its own diagonal.** ``prior_in_cohort(K)`` resolves what
  *this same cohort* held at the previous observation, and zero at the first —
  the same rule and the same reason as ``prior(K)``. A second observation of a
  cohort supersedes the first *and closes its window*, cell by cell, so exactly
  one number about a cohort ever reads as current.
- **The lint refuses the four shapes that would make a grid with holes in it**,
  and a spec that declares no cohorts mints byte-for-byte what it minted before.

The grammar's names are reached as ``episodes.CohortSpec`` at use rather than
imported at the top of the file. That was load-bearing while the axis was being
written — a module-level import of a name that did not exist yet would have
collect-errored the whole file, taking the byte-neutrality pin down with it, and
that pin is the one test here that has to pass *before* the change as much as
after. It is kept because it will be load-bearing again for the next axis.
"""

from __future__ import annotations

import itertools

import pytest

from worldloom import InsuranceWorld, episodes
from worldloom import validate as validate_module

SEED = 8128

#: The shipped insurer's grid: four accident quarters, the newest a quarter
#: behind the valuation. Named because three tests are about this one tuple.
VALUATION = "2026-03"
GRID = ("2025-03", "2025-06", "2025-09", "2025-12")

#: The next valuation on the same axis. Three of its four cohorts are the ones
#: above, which is what makes `prior_in_cohort` a diagonal rather than a lookup.
NEXT_VALUATION = "2026-06"
NEXT_GRID = ("2025-06", "2025-09", "2025-12", "2026-03")

#: The three process-global registries this file writes to. `_REGISTERED_CHECKS`
#: is in the list although nothing reads it after a run: it is the cache that
#: makes re-installing one spec re-register the *same* callable, so leaving a
#: stale entry behind under a name a later test reuses is how a check group
#: silently becomes the wrong one.
_REGISTRIES = (
    lambda: episodes._LOADED,
    lambda: episodes._REGISTERED_CHECKS,
    lambda: validate_module._DOMAIN_CHECKS,
)


@pytest.fixture(autouse=True)
def _restore_the_registries():
    """Install into the grammar, then put it back exactly as it was.

    An acceptance suite for a grammar feature builds a *lot* of throwaway
    specs — a dozen here, each needing its own name, because `install` rightly
    refuses to redefine one — and installing a spec also registers its derived
    check group, which `validate` then runs against every world for the rest of
    the session. Found rather than foreseen: with this file left uncleaned,
    `test_scale`'s bound on how many times `validate` may read `World.facts`
    went from 32 to 40 and failed, in a file that has nothing to do with
    cohorts. That bound is a real gate on validator cost, and the right place
    to fix it is here — a test may add to a registry; it may not leave anything
    in one.

    Per test rather than per module, because that is the stronger claim and
    costs nothing: a spec installed by one test is not visible to the next, so
    no test in this file can come to depend on another having run first.
    """
    saved = [(registry(), dict(registry())) for registry in _REGISTRIES]
    try:
        yield
    finally:
        for registry, original in saved:
            registry.clear()
            registry.update(original)


# ---------------------------------------------------------------------------
# Construction helpers — the idiom of tests/test_process.py, one axis wider
# ---------------------------------------------------------------------------


def _axis(name: str = "accident_quarter", **overrides):
    """The shipped insurer's declared origin axis."""
    fields = {"name": name, "count": 4, "spacing_months": 3, "lag_months": 3}
    fields.update(overrides)
    return episodes.CohortSpec(**fields)


def _valuation_event(*kinds: str):
    return episodes.EventSpec(
        kind="reserving.valuation",
        when="start",
        summary="The actuary values the book at {period}.",
        fact_keys=list(kinds),
    )


def _spec(name: str, fact_kinds, *, cohorts=None, events=None):
    """A one-event insurance process over the declared kinds."""
    return episodes.EpisodeSpec(
        name=name,
        domain="insurance",
        period="quarter",
        cohorts=list(cohorts if cohorts is not None else [_axis()]),
        fact_kinds=list(fact_kinds),
        events=list(events if events is not None else
                    [_valuation_event(*[fk.kind for fk in fact_kinds])]),
    )


def _run(spec, *periods):
    """Install *spec* and run it over *periods* on one seeded insurer."""
    episodes.install([spec])
    world = InsuranceWorld(seed=SEED).build()
    for period in periods:
        world = world.run(episodes.AuthoredEpisode(episode=spec.name, period=period))
    return world


def _observations(world, kind: str) -> list[tuple[str, dict[str, float]]]:
    """This kind's grid per observation, oldest observation first.

    Keyed by the observation moment rather than by the period, because two
    valuations of one triangle mint facts for the *same* cohort periods — which
    is the whole point of the axis and would silently collapse a period-keyed
    dictionary down to whichever run happened to be written last.
    """
    by_moment: dict[str, dict[str, float]] = {}
    for fact in world.facts:
        if fact.kind != kind:
            continue
        cells = by_moment.setdefault(fact.valid_from.isoformat(), {})
        cells[fact.period] = None if fact.value is None else fact.value.amount
    return sorted(by_moment.items())


# ---------------------------------------------------------------------------
# 1. The arithmetic
# ---------------------------------------------------------------------------


def test_the_shipped_insurers_grid_is_the_acceptance_case() -> None:
    """Four accident quarters observed from 2026-03, oldest first.

    Verified against the shipped insurer corpus rather than derived here:
    `FACT-0016` and `FACT-0018` are one subject's `reserves.ultimate` at
    `2025-03` and `2025-06`. Whatever indexing computes the window, this tuple
    is what it has to produce, or an authored triangle and the generated one
    are different triangles.
    """
    assert episodes.cohort_periods(VALUATION, _axis()) == GRID


def test_the_grid_walks_forward_with_the_valuation() -> None:
    """A triangle's second observation keeps three cohorts and gains one.

    This overlap is not incidental — it is the only thing that makes
    `prior_in_cohort` a diagonal step rather than a lookup, so it is pinned
    beside the grid itself.
    """
    assert episodes.cohort_periods(NEXT_VALUATION, _axis()) == NEXT_GRID
    assert len(set(GRID) & set(NEXT_GRID)) == 3


def test_the_axis_is_the_four_numbers_and_nothing_else() -> None:
    """A monthly vintage on the same arithmetic, so the acceptance grid is read
    as an instance of a definition rather than as a special case."""
    monthly = _axis("vintage", count=3, spacing_months=1, lag_months=1)
    assert episodes.cohort_periods(VALUATION, monthly) == (
        "2025-12", "2026-01", "2026-02",
    )

    annual = _axis("underwriting_year", count=2, spacing_months=12, lag_months=12)
    assert episodes.cohort_periods(VALUATION, annual) == ("2024-03", "2025-03")


def test_the_grid_is_ordered_oldest_first_and_never_reaches_the_valuation() -> None:
    """Two properties every consumer of the axis depends on: the roll-up reads
    the cells in a fixed order, and a cohort that had not yet begun by the
    valuation would be a column of facts about the future."""
    periods = episodes.cohort_periods(VALUATION, _axis())
    assert list(periods) == sorted(periods)
    assert len(set(periods)) == len(periods)
    assert all(period < VALUATION for period in periods)


# ---------------------------------------------------------------------------
# 2. A cohort-keyed kind mints one fact per cohort
# ---------------------------------------------------------------------------


def _ultimate_spec(name: str):
    return _spec(name, [episodes.FactKindSpec(
        kind="reserves.ultimate",
        value_type="money",
        cohort="accident_quarter",
        parameter="reserves.cohort.ultimate",
        invariants=[episodes.Invariant(kind="holds-at")],
    )])


def test_a_cohort_kind_mints_one_fact_per_cohort() -> None:
    world = _run(_ultimate_spec("CohortGrid"), VALUATION)
    cohort_facts = [f for f in world.facts if f.kind == "reserves.ultimate"]

    assert len(cohort_facts) == len(GRID)
    assert len({f.id for f in cohort_facts}) == len(GRID)


def test_each_cohort_facts_period_is_its_cohort_not_the_valuation() -> None:
    """The key decision the existing generator already made, pinned.

    The cohort rides `CanonicalFact.period`; the valuation rides `valid_from`
    and the supersession chain. A grid that keyed on the valuation instead
    would put four facts in one period with nothing to tell them apart, and
    every roll-up over the axis would be a guess.
    """
    world = _run(_ultimate_spec("CohortGridPeriods"), VALUATION)
    cohort_facts = [f for f in world.facts if f.kind == "reserves.ultimate"]

    assert tuple(sorted(f.period for f in cohort_facts)) == GRID
    assert VALUATION not in {f.period for f in cohort_facts}


def test_one_subject_one_observation_four_cohorts() -> None:
    """The shape the shipped corpus has: four cohorts of one book, all recorded
    at the moment the valuation event fired."""
    world = _run(_ultimate_spec("CohortGridShape"), VALUATION)
    cohort_facts = [f for f in world.facts if f.kind == "reserves.ultimate"]

    # Restated rather than assumed: every assertion below is about a *set*, and
    # a set of one satisfies all four. This test passed against a runner that
    # minted a single fact, which is the failure it exists to catch.
    assert len(cohort_facts) == len(GRID)
    assert len({f.subject for f in cohort_facts}) == 1
    assert len({f.valid_from for f in cohort_facts}) == 1
    assert len({f.event_id for f in cohort_facts}) == 1
    assert all(f.event_id is not None for f in cohort_facts)


def test_a_declared_grid_lints_clean() -> None:
    """Zero findings, measured — the gate every authored spec in this
    repository passes before it is allowed to claim anything."""
    assert episodes.lint([_ultimate_spec("CohortGridLint")], base="insurance") == []


# ---------------------------------------------------------------------------
# 3. allocation_of(K) — the cells sum to the parent by construction
# ---------------------------------------------------------------------------

#: Deliberately not a multiple of four. Equal shares of 1002 across the shipped
#: grid are 250.5 each, so the largest-remainder distribution is actually
#: exercised rather than trivially satisfied — the reconciliation this
#: derivation exists to guarantee is precisely the one that fails when a
#: generator rounds four shares independently and hopes.
PARENT_TOTAL = 1002.0


def _allocation_spec(name: str, *, weighted: bool):
    child = {
        "kind": "reserves.ultimate",
        "value_type": "money",
        "cohort": "accident_quarter",
        "derive": "allocation_of(reserves.central_estimate_total)",
        "invariants": [episodes.Invariant(kind="holds-at")],
    }
    if weighted:
        # Weights per cohort, one draw each on the kind's own named stream.
        child["parameter"] = "reserves.cohort.paid_ratio"
    return _spec(name, [
        episodes.FactKindSpec(
            kind="reserves.central_estimate_total",
            value_type="money",
            amount=PARENT_TOTAL,
            invariants=[episodes.Invariant(kind="holds-at")],
        ),
        episodes.FactKindSpec(**child),
    ])


def test_allocation_cells_sum_to_the_parent_exactly() -> None:
    world = _run(_allocation_spec("CohortAllocation", weighted=False), VALUATION)
    (_, cells), = _observations(world, "reserves.ultimate")

    assert tuple(sorted(cells)) == GRID
    assert sum(cells.values()) == PARENT_TOTAL


def test_an_uneven_division_distributes_its_remainder_rather_than_rounding() -> None:
    """1002 over four equal cohorts is 250.5 apiece.

    Round-and-hope gives four 250s or four 251s and misses the parent by two
    either way. Largest remainder gives two of each — so the cells differ, the
    spread is one unit, and the total is exact. All three are asserted, because
    a check on the sum alone passes an implementation that quietly moved the
    whole residual into one cohort.
    """
    world = _run(_allocation_spec("CohortAllocationRemainder", weighted=False), VALUATION)
    (_, cells), = _observations(world, "reserves.ultimate")

    amounts = [cells[period] for period in GRID]
    assert sorted(amounts) == [250, 250, 251, 251]
    assert max(amounts) - min(amounts) == 1
    assert sum(amounts) == PARENT_TOTAL

    # `finance.allocate` breaks ties on index, and the grid is oldest first, so
    # the two spare units land on the two oldest cohorts. Pinned rather than
    # left to chance: an unstable tie-break makes a corpus that rebuilds
    # differently on a different sort, which is the one thing this repository
    # will not ship.
    assert amounts == [251, 251, 250, 250]


def test_a_weighted_allocation_still_reconciles_and_still_replays() -> None:
    """A kind declaring a `parameter` draws its weights per cohort, one stream
    each. The guarantee is unchanged — allocated from the total, never drawn
    and summed — and the draw is on a named stream, so the same seed gives the
    same grid."""
    spec = _allocation_spec("CohortAllocationWeighted", weighted=True)
    first = _run(spec, VALUATION)
    second = _run(spec, VALUATION)

    (_, cells), = _observations(first, "reserves.ultimate")
    (_, again), = _observations(second, "reserves.ultimate")

    assert tuple(sorted(cells)) == GRID
    assert sum(cells.values()) == PARENT_TOTAL
    assert cells == again

    # And the weights were really drawn, cohort by cohort: a spread of one unit
    # is what an *equal* split of 1002 produces, so a wider one is the evidence
    # that `parameter` reached the allocation at all rather than being ignored.
    spread = max(cells.values()) - min(cells.values())
    assert spread > 1, cells


# ---------------------------------------------------------------------------
# 4. prior_in_cohort(K) — the diagonal step
# ---------------------------------------------------------------------------


def _diagonal_spec(name: str):
    """A triangle: a drawn book total, allocated across cohorts, beside what
    each cohort held at the previous observation."""
    return _spec(name, [
        episodes.FactKindSpec(
            kind="reserves.central_estimate_total",
            value_type="money",
            parameter="reserves.cohort.ultimate",
            invariants=[episodes.Invariant(kind="holds-at")],
        ),
        episodes.FactKindSpec(
            kind="reserves.ultimate",
            value_type="money",
            cohort="accident_quarter",
            derive="allocation_of(reserves.central_estimate_total)",
            invariants=[episodes.Invariant(kind="holds-at")],
        ),
        episodes.FactKindSpec(
            kind="reserves.ibnr",
            value_type="money",
            cohort="accident_quarter",
            derive="prior_in_cohort(reserves.ultimate)",
            invariants=[episodes.Invariant(kind="holds-at")],
        ),
    ])


def test_the_first_valuation_has_no_prior_in_any_cohort() -> None:
    """Zero, minted — never omitted.

    `prior(K)`'s rule and `prior(K)`'s reason: "nothing was outstanding" is a
    claim, and a missing fact makes it indistinguishable from "nobody looked".
    A triangle with a hole in its first column is not a triangle.
    """
    world = _run(_diagonal_spec("CohortDiagonalFirst"), VALUATION)
    (_, priors), = _observations(world, "reserves.ibnr")

    assert tuple(sorted(priors)) == GRID
    assert set(priors.values()) == {0}


def test_the_second_valuation_resolves_each_cohorts_own_prior() -> None:
    """Each cohort reads back its *own* previous value, not the book's.

    Three of the second valuation's four cohorts were observed a quarter
    earlier; the fourth has just entered the window and has nothing behind it.
    Getting this wrong in the obvious way — resolving the prior *period* rather
    than the prior observation of this *cohort* — would produce a grid that
    lines up one cell out and still validates, because every number in it is a
    real number from a real fact.
    """
    world = _run(_diagonal_spec("CohortDiagonalSecond"), VALUATION, NEXT_VALUATION)

    ultimates = _observations(world, "reserves.ultimate")
    priors = _observations(world, "reserves.ibnr")
    assert len(ultimates) == len(priors) == 2

    (_, first_ultimate), (_, second_ultimate) = ultimates
    (_, second_prior) = priors[1]

    assert tuple(sorted(second_prior)) == NEXT_GRID
    for cohort in set(GRID) & set(NEXT_GRID):
        assert second_prior[cohort] == first_ultimate[cohort], cohort

    # The cohort that has only just entered the window: nothing behind it.
    assert second_prior[VALUATION] == 0

    # And the two observations really do differ, or the assertion above would
    # hold for a derivation that simply read this run's own cells.
    assert any(
        second_ultimate[cohort] != first_ultimate[cohort]
        for cohort in set(GRID) & set(NEXT_GRID)
    ), "the two valuations drew identical grids; this test cannot discriminate"


def test_a_later_observation_closes_the_cell_it_replaces() -> None:
    """The other half of "encoded by ``valid_from`` plus the supersession chain".

    A cohort observed twice is one cell revalued, so the second fact must
    supersede the first *and* the first's window must close where the second's
    opens. Linking without closing leaves two facts about one cohort both
    reading as current, which is the exact shape insurance's own
    ``estimate_chain_not_singular`` refuses ("2 unsuperseded facts, expected
    exactly 1") and the grammar's ``succession_torn`` refuses one layer up —
    and it is not a cosmetic defect: a triangle whose diagonal is two open
    numbers cannot answer "what do we think this cohort is worth", which is the
    only question a triangle is built to answer.
    """
    world = _run(_diagonal_spec("CohortSuccession"), VALUATION, NEXT_VALUATION)

    for kind in ("reserves.ultimate", "reserves.ibnr"):
        cells: dict[str, list] = {}
        for fact in world.facts:
            if fact.kind == kind:
                cells.setdefault((fact.subject, fact.period), []).append(fact)

        revalued = 0
        for (subject, cohort), chain in sorted(cells.items()):
            chain.sort(key=lambda f: f.valid_from)
            open_now = [f for f in chain if f.valid_to is None]
            assert len(open_now) == 1, (kind, subject, cohort, len(open_now))
            for earlier, later in itertools.pairwise(chain):
                assert later.supersedes == earlier.id, (kind, cohort)
                assert earlier.valid_to == later.valid_from, (kind, cohort)
                revalued += 1
        assert revalued == 3, (
            f"{kind}: three cohorts are in both valuations and should have been"
            " revalued"
        )


# ---------------------------------------------------------------------------
# 5. The lint refusals
# ---------------------------------------------------------------------------


def test_a_cohort_naming_an_undeclared_axis_is_refused() -> None:
    """The `factkinds` defence one axis over: a plausible-looking axis name
    that nothing declares would mint a grid of one column forever."""
    spec = _spec(
        "CohortUndeclaredAxis",
        [episodes.FactKindSpec(
            kind="reserves.ultimate",
            value_type="money",
            cohort="accident_year",
            parameter="reserves.cohort.ultimate",
            invariants=[episodes.Invariant(kind="holds-at")],
        )],
        cohorts=[_axis("accident_quarter")],
    )
    findings = episodes.lint([spec], base="insurance")
    assert any(
        "accident_year" in f and "cohort" in f and "accident_quarter" in f
        for f in findings
    ), findings


def test_a_cohort_kind_that_is_not_period_keyed_is_refused() -> None:
    """A cohort kind that *may* be absent makes a grid with holes in it, and a
    hole is indistinguishable from a cohort that reported nothing — so every
    roll-up over the axis becomes unanswerable."""
    spec = _spec("CohortNotPeriodKeyed", [episodes.FactKindSpec(
        kind="reserves.ultimate",
        value_type="money",
        cohort="accident_quarter",
        period_scope="period-scoped",
        parameter="reserves.cohort.ultimate",
        invariants=[episodes.Invariant(kind="holds-at")],
    )])
    findings = episodes.lint([spec], base="insurance")
    assert any(
        "period-keyed" in f and "period-scoped" in f for f in findings
    ), findings


def test_a_cohort_kind_may_not_also_be_a_business_day_series() -> None:
    """Two different second axes. The fact's own `period` can carry the cohort
    or it can be dropped for a daily observation; it cannot do both, and the
    refusal is stated rather than resolved by whichever branch runs first."""
    spec = _spec("CohortAndSeries", [episodes.FactKindSpec(
        kind="reserves.ultimate",
        value_type="money",
        cohort="accident_quarter",
        parameter="reserves.cohort.ultimate",
        series_days=5,
        series_start_bd=1,
        invariants=[episodes.Invariant(kind="holds-at")],
    )])
    findings = episodes.lint([spec], base="insurance")
    assert any("series" in f and "cohort" in f for f in findings), findings


def test_a_cohort_derivation_on_a_kind_with_no_cohort_is_refused() -> None:
    """Both halves of the derived vocabulary need an axis to derive over.

    `allocation_of` with no cohort has nothing to split across, and
    `prior_in_cohort` with no cohort is `prior` wearing a longer name — either
    would run, produce a plausible number, and mean nothing.
    """
    parent = episodes.FactKindSpec(
        kind="reserves.central_estimate_total",
        value_type="money",
        amount=PARENT_TOTAL,
        invariants=[episodes.Invariant(kind="holds-at")],
    )
    allocation = _spec("CohortAllocationNoAxis", [
        parent,
        episodes.FactKindSpec(
            kind="reserves.ultimate",
            value_type="money",
            derive="allocation_of(reserves.central_estimate_total)",
            invariants=[episodes.Invariant(kind="holds-at")],
        ),
    ])
    findings = episodes.lint([allocation], base="insurance")
    assert any("allocation_of" in f and "cohort" in f for f in findings), findings

    diagonal = _spec("CohortPriorNoAxis", [
        parent,
        episodes.FactKindSpec(
            kind="reserves.ultimate",
            value_type="money",
            derive="prior_in_cohort(reserves.central_estimate_total)",
            invariants=[episodes.Invariant(kind="holds-at")],
        ),
    ])
    findings = episodes.lint([diagonal], base="insurance")
    assert any("prior_in_cohort" in f and "cohort" in f for f in findings), findings


def test_rolls_up_to_is_declarable_beside_the_other_invariants() -> None:
    """The invariant a cohort grid carries — the cells sum to the parent for
    the same valuation, to the cent. Declared on the kind and recomputed by the
    validator, which is this repository's rule for every check it runs: derived
    from the declaration, never hand-written per kind."""
    invariant = episodes.Invariant(
        kind="rolls-up-to", operands=["reserves.central_estimate_total"],
    )
    assert invariant.operands == ["reserves.central_estimate_total"]


# ---------------------------------------------------------------------------
# 6. Byte-neutrality — the gate the whole axis is built behind
# ---------------------------------------------------------------------------

#: A process authored before the cohort axis existed: a pack's JSON with no
#: `cohorts` key at all, which is how every shipped spec reads on disk.
NEUTRAL_DOCUMENT = {
    "episodes": [{
        "name": "CohortNeutral",
        "domain": "insurance",
        "period": "quarter",
        "fact_kinds": [
            {"kind": "reserves.central_estimate_total", "value_type": "money",
             "parameter": "reserves.cohort.ultimate",
             "invariants": [{"kind": "holds-at"}]},
            {"kind": "reserves.ibnr", "value_type": "money",
             "derive": "pct_of(reserves.central_estimate_total)",
             "parameter": "reserves.cohort.incurred_ratio",
             "invariants": [{"kind": "holds-at"}]},
            {"kind": "reserves.philosophy", "value_type": "text",
             "text": "The reserving philosophy in force for {period}.",
             "invariants": [{"kind": "holds-at"}]},
        ],
        "events": [{
            "kind": "reserving.valuation", "when": "start",
            "summary": "The actuary values the book at {period}.",
            "fact_keys": ["reserves.central_estimate_total", "reserves.ibnr",
                          "reserves.philosophy"],
        }],
    }],
}

#: Measured on this repository *before* the cohort axis was written — against a
#: `git archive HEAD` checkout run out-of-tree, not against the working copy —
#: from `InsuranceWorld(seed=8128)` over `2026-03`. Literals rather than a
#: recomputation, because a recomputation compares the change against itself:
#: the claim is that a spec declaring no cohorts mints exactly what it minted
#: before, and only a figure captured beforehand can witness it. Measured off
#: the runner and never hand-written, for the matching reason — a pin whose
#: numbers were guessed cannot fail for the reason it exists.
#:
#: The episode *name* is load-bearing in these figures, and getting that wrong
#: is how this constant was first written. `AuthoredEpisode.run` derives its
#: stream as `scenario/{spec.name}/{period}`, so a baseline captured under any
#: other spec name is a different draw and reports a neutrality failure that is
#: really a naming mistake — the one false alarm a gate like this must not
#: raise, since the only sane response to a real one is to go hunting in the
#: minting loop.
#:
#: This is the unit-level half of the claim. The corpus-level half — the shipped
#: insurer and grocer rebuilding with byte-identical `facts.jsonl` — is what
#: actually gates the axis, and lives in CI's replay diff.
NEUTRAL_FACTS = (
    ("FACT-0001", "reserves.central_estimate_total", "2026-03", 80.0),
    ("FACT-0002", "reserves.ibnr", "2026-03", 0.0),
    ("FACT-0003", "reserves.philosophy", "2026-03", None),
)


def test_a_spec_declaring_no_cohorts_mints_what_it_minted_before() -> None:
    """The first non-negotiable gate, as a regression pin.

    Ids, kinds, periods and amounts — the four fields a cohort would have moved
    if the axis had been threaded through the minting loop rather than beside
    it. Every corpus in this repository rebuilds byte-for-byte or the axis does
    not ship, and this is that claim reduced to something a test can hold.
    """
    specs = episodes.load(NEUTRAL_DOCUMENT)
    episodes.install(specs)
    world = InsuranceWorld(seed=SEED).build().run(
        episodes.AuthoredEpisode(episode="CohortNeutral", period=VALUATION)
    )
    minted = tuple(
        (f.id, f.kind, f.period, None if f.value is None else f.value.amount)
        for f in world.facts if f.kind.startswith("reserves.")
    )
    assert minted == NEUTRAL_FACTS


def test_a_spec_written_before_the_axis_still_loads_and_declares_no_axis() -> None:
    """A pack authored before the field existed carries no `cohorts` key, and
    the grammar forbids extra fields in both directions — so the default has to
    be the empty axis list, and the old document has to keep loading."""
    spec = episodes.load(NEUTRAL_DOCUMENT)[0]
    assert list(spec.cohorts) == []
    assert episodes.lint([spec], base="insurance") == []


def test_no_cohort_kind_means_no_cohort_arithmetic_is_reachable() -> None:
    """The neutrality claim from the other side: with no axis declared, every
    fact of an ordinary period-keyed kind still carries the *valuation* in its
    period, which is what every existing corpus, document and check assumes."""
    specs = episodes.load(NEUTRAL_DOCUMENT)
    episodes.install(specs)
    world = InsuranceWorld(seed=SEED).build().run(
        episodes.AuthoredEpisode(episode="CohortNeutral", period=VALUATION)
    )
    periods = {f.period for f in world.facts if f.kind.startswith("reserves.")}
    assert periods == {VALUATION}


# ---------------------------------------------------------------------------
# The gate every authored episode in this repository ends at
# ---------------------------------------------------------------------------


def test_a_cohort_episode_validates_and_replays_from_its_recipe() -> None:
    """A grid is corpus bytes like anything else: it passes the full validator
    and regenerates from the recipe with no spec file on hand."""
    from worldloom import recipe

    world = _run(_diagonal_spec("CohortReplay"), VALUATION, NEXT_VALUATION)

    report = world.validate()
    assert report.ok, report.violations[:5]

    again = recipe.rebuild(recipe=world.recipe)
    assert tuple(again._facts) == tuple(world._facts)
    assert tuple(again._events) == tuple(world._events)


@pytest.mark.parametrize("period", [VALUATION, NEXT_VALUATION])
def test_the_grid_is_the_same_grid_however_often_it_is_computed(period: str) -> None:
    """No clock, no `random`, no set iteration — stated as a property rather
    than trusted, because a cohort window computed from `datetime.now()` would
    pass every other test in this file for most of a quarter."""
    axis = _axis()
    assert episodes.cohort_periods(period, axis) == episodes.cohort_periods(period, axis)
