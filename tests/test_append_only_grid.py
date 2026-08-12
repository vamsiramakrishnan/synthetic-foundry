"""A declared invariant as a contract the *runner* keeps, not only the checker.

`never-superseded` shipped as a validator rule with no minting behaviour behind
it, and the cohort branch of `episodes.run` always linked a predecessor and
closed its window. Between them that made one real shape unauthorable: the
**append-only observation grid** — a paid or incurred triangle diagonal, where
a later reading of a cohort sits *beside* the earlier one rather than
correcting it, because both are things the company actually observed. A kind
declaring the rule linted clean, minted a chain anyway, and then failed its own
declaration (`triangle_touched`, and the derived `never_superseded_touched`).

So the two supersession invariants are now read at mint time as well:

- **`never-superseded` on a cohort kind mints an append-only grid.** No
  predecessor is linked, no window is closed — this run's and the last run's
  reading of one cohort are both open, which is what a diagonal *is*.
- **`supersedes-prior`, or neither, is unchanged.** The chained grid the
  reserving cycle already ships, cell by cell, byte for byte.
- **Declaring both is refused.** They instruct the runner to do opposite
  things, and whichever it picked the other check would fail the facts it
  minted.

Both grids are exercised in one spec on one world, which is the only reading
that shows the two behaviours are a *choice the declaration makes* rather than
a change of engine: same runner, same period, same axis, two kinds.

The registry-restoring fixture is `tests/test_cohorts.py`'s, for its reason
verbatim: installing a spec also registers its derived check group, which
`validate` then runs against every world for the rest of the session, and a
test may add to a registry but may not leave anything in one.
"""

from __future__ import annotations

import pytest

from worldloom import InsuranceWorld, World, cohorts, episodes, packs
from worldloom import validate as validate_module

PACK = "examples/packs/longtail-insurer.json"
SEED = 8128
QUARTERS = ("2026-03", "2026-06")
#: The cohorts both valuations observe — where a chain has something to chain
#: to and a diagonal has two readings standing side by side.
CARRIED = ("2025-06", "2025-09", "2025-12")

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


def _probe() -> episodes.EpisodeSpec:
    """One valuation, two grids: a chained estimate and an append-only diagonal.

    Deliberately minimal beside the shipped pack's own episode — what is under
    test is the minting rule, and a spec carrying documents and a benchmark
    would make a failure here ambiguous about which layer moved.
    """
    return episodes.EpisodeSpec(
        name="AppendOnlyProbe",
        domain="insurance",
        period="quarter",
        cohorts=[episodes.CohortSpec(
            name="accident_quarter", count=4, spacing_months=3, lag_months=3,
        )],
        fact_kinds=[
            episodes.FactKindSpec(
                kind="reserves.central_estimate_total",
                value_type="money",
                subject_type="category",
                subject_role="cat_lt_liability",
                parameter="reserves.cohort.ultimate",
                scale=4,
                invariants=[episodes.Invariant(kind="holds-at")],
            ),
            episodes.FactKindSpec(
                kind="reserves.ultimate",
                value_type="money",
                subject_type="category",
                subject_role="cat_lt_liability",
                cohort="accident_quarter",
                derive="allocation_of(reserves.central_estimate_total)",
                parameter="reserves.cohort.ultimate",
                invariants=[
                    episodes.Invariant(kind="holds-at"),
                    episodes.Invariant(
                        kind="rolls-up-to", operands=["reserves.central_estimate_total"],
                    ),
                ],
            ),
            episodes.FactKindSpec(
                kind="claims.paid_to_date",
                value_type="money",
                subject_type="category",
                subject_role="cat_lt_liability",
                cohort="accident_quarter",
                derive="allocation_of(reserves.central_estimate_total)",
                parameter="reserves.cohort.paid_out_fraction",
                invariants=[
                    episodes.Invariant(kind="holds-at"),
                    episodes.Invariant(
                        kind="never-superseded",
                        detail="A diagonal is what was read at a valuation; the next"
                               " valuation reads again beside it and corrects nothing.",
                    ),
                ],
            ),
        ],
        events=[episodes.EventSpec(
            kind="valuation_read",
            when="start",
            business_day=18,
            summary="The {period} valuation read the diagonal and set the estimate.",
            actors=["chief_actuary"],
            fact_keys=[
                "reserves.central_estimate_total",
                "reserves.ultimate",
                "claims.paid_to_date",
            ],
        )],
    )


def _built() -> World:
    """The pack's insurer, two valuations of the probe deep."""
    spec = _probe()
    episodes.install([spec])
    world = InsuranceWorld.from_pack(packs.load(PACK), seed=SEED).build()
    for quarter in QUARTERS:
        world = world.run(episodes.AuthoredEpisode(episode=spec.name, period=quarter))
    # No `compile()`: the probe plans no documents, and what is under test is
    # the facts a declaration mints rather than the paperwork over them.
    return world


def _cells(world: World, kind: str) -> list:
    return sorted(
        (fact for fact in world.facts if fact.kind == kind),
        key=lambda fact: (fact.period or "", fact.valid_from),
    )


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


def test_a_kind_declaring_both_supersession_invariants_is_refused() -> None:
    """Contradictory instructions, refused where they are authored.

    Not merely redundant: the runner has to pick one, and the check derived
    from the other then fails the facts it minted — a spec that is wrong
    whatever the engine does.
    """
    spec = _probe()
    both = spec.fact_kinds[2].model_copy(update={
        "invariants": [
            *spec.fact_kinds[2].invariants,
            episodes.Invariant(kind="supersedes-prior"),
        ],
    })
    findings = episodes.lint([spec.model_copy(update={
        "fact_kinds": [*spec.fact_kinds[:2], both],
    })])
    assert any(
        "both never-superseded and supersedes-prior" in finding for finding in findings
    ), findings


def test_the_probe_itself_lints_clean() -> None:
    """Declaring one of the two, on a kind the registry declares it for, is
    ordinary authoring — the registry now says the diagonal is append-only,
    which is what the insurance engine has enforced since it shipped."""
    assert episodes.lint([_probe()], base="insurance") == []


# ---------------------------------------------------------------------------
# The minting
# ---------------------------------------------------------------------------


def test_an_append_only_grid_links_nothing_and_closes_nothing() -> None:
    """Two readings of one cohort, both standing.

    The diagonal's whole claim: what the company held at the first valuation is
    not wrong, it is *earlier*, so nothing supersedes it and nothing closes it.
    """
    world = _built()
    cells = _cells(world, "claims.paid_to_date")
    assert len(cells) == 8  # four cohorts, twice
    assert all(cell.supersedes is None for cell in cells)
    assert all(cell.valid_to is None for cell in cells)

    for cohort in CARRIED:
        readings = [cell for cell in cells if cell.period == cohort]
        assert len(readings) == 2
        assert readings[0].valid_from < readings[1].valid_from


def test_a_chained_grid_beside_it_is_untouched() -> None:
    """The same runner, the same axis, the other declaration.

    Cell by cell supersession with exact validity handover — the behaviour
    `tests/test_reserving_pack.py` pins for the shipped cycle, asserted here
    beside an append-only kind so "unchanged" means unchanged *in the presence
    of* the new branch rather than in a world that never reaches it.
    """
    world = _built()
    cells = _cells(world, "reserves.ultimate")
    by_key = {(cell.period, cell.valid_from): cell for cell in cells}
    moments = sorted({cell.valid_from for cell in cells})
    assert len(moments) == 2

    first, second = moments
    for cohort in CARRIED:
        was, now = by_key[(cohort, first)], by_key[(cohort, second)]
        assert now.supersedes == was.id
        assert was.valid_to == now.valid_from


def test_the_world_validates_including_the_engines_own_triangle_rule() -> None:
    """`triangle_touched` is the check this could not get past before.

    The insurance engine has always refused a closed or superseded
    `claims.*_to_date` fact; an authored diagonal chained by the runner failed
    it on every carried cohort. Validating clean here is the two halves of the
    declaration agreeing.
    """
    world = _built()
    report = world.validate()
    assert report.violations == []

    violations, checks = cohorts.check(
        list(world.facts), (episodes.loaded()["AppendOnlyProbe"],)
    )
    assert violations == []
    assert checks > 0
