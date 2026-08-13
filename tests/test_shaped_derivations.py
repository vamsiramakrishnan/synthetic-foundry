"""A derivation takes its shape from its operands.

The seven arithmetic derivations were scalar-only, and a cohort grid handed to
one was silently its roll-up — a defensible reading, unstated, so the lint
refused it outright. That refusal made the figure reserving actually argues
about unauthorable: **adverse development is per cohort**. `minus` over two
book totals is the movement in the central estimate; `minus` over the same two
kinds as *grids* is which accident quarter moved, and a corpus that can only
state the first cannot say which quarter went bad.

So the shape rule, which is what these tests pin:

- **all scalars → a scalar**, computed exactly as before. Every corpus built
  before this rebuilds byte-for-byte, which is the gate this path answers to;
  here it is pinned as arithmetic rather than as bytes.
- **all grids on one axis → the same computation, cell by cell**, and the
  result is a grid.
- **mixed → the scalar broadcasts** across the cells. A board percentage
  applied to a triangle is one rate and four answers.
- **grids on different axes → refused**, in the lint and again at run. Nothing
  pairs cell *i* of one origin axis with cell *i* of another.

And the rule that keeps a grid checkable: a kind whose derivation comes out
gridded must *declare* the axis, because completeness, roll-up and cohort
sanity all read `cohort` and a column they never look at is held to nothing.

No new verbs: `SHAPED_DERIVATIONS` is seven of the vocabulary's existing
fourteen, and the test that says so is the one that fails if somebody adds
`minus_grid` beside `minus`.

The registry-restoring fixture is `tests/test_cohorts.py`'s, for its reason
verbatim.
"""

from __future__ import annotations

import pytest

from worldloom import InsuranceWorld, World, episodes, packs
from worldloom import validate as validate_module

PACK = "examples/packs/longtail-insurer.json"
SEED = 8128
QUARTERS = ("2026-03", "2026-06")

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


def _kind(kind: str, **overrides) -> episodes.FactKindSpec:
    base = dict(
        value_type="money",
        subject_type="category",
        subject_role="cat_lt_liability",
        invariants=[episodes.Invariant(kind="holds-at")],
    )
    base.update(overrides)
    return episodes.FactKindSpec(kind=kind, **base)


def _probe(kinds: list[episodes.FactKindSpec], **overrides) -> episodes.EpisodeSpec:
    """A one-event valuation over whichever kinds a test needs."""
    spec = dict(
        name="ShapeProbe",
        domain="insurance",
        period="quarter",
        cohorts=[
            episodes.CohortSpec(
                name="accident_quarter", count=4, spacing_months=3, lag_months=3,
            ),
            episodes.CohortSpec(
                name="underwriting_year", count=2, spacing_months=12, lag_months=12,
            ),
        ],
        fact_kinds=kinds,
        events=[episodes.EventSpec(
            kind="valuation_read",
            when="start",
            business_day=18,
            summary="The {period} valuation.",
            actors=["chief_actuary"],
            fact_keys=[fk.kind for fk in kinds],
        )],
    )
    spec.update(overrides)
    return episodes.EpisodeSpec(**spec)


#: The book total every probe starts from, and its grid.
_TOTAL = _kind(
    "reserves.central_estimate_total",
    parameter="reserves.cohort.ultimate",
    scale=4,
)
_GRID = _kind(
    "reserves.ultimate",
    cohort="accident_quarter",
    derive="allocation_of(reserves.central_estimate_total)",
    parameter="reserves.cohort.ultimate",
)


def _run(spec: episodes.EpisodeSpec, *, quarters=QUARTERS) -> World:
    episodes.install([spec])
    world = InsuranceWorld.from_pack(packs.load(PACK), seed=SEED).build()
    for quarter in quarters:
        world = world.run(episodes.AuthoredEpisode(episode=spec.name, period=quarter))
    return world


def _cells(world: World, kind: str, at=None) -> dict[str, float]:
    return {
        fact.period: fact.value.amount
        for fact in world.facts
        if fact.kind == kind and (at is None or fact.valid_from == at)
    }


# ---------------------------------------------------------------------------
# The vocabulary did not grow
# ---------------------------------------------------------------------------


def test_the_lifted_derivations_are_seven_of_the_existing_vocabulary() -> None:
    """A shape is not a computation.

    `minus` and a hypothetical `minus_grid` would be one subtraction written
    twice, drifting apart at the first rounding change — so the seven that
    read amounts were lifted and nothing was added beside them.
    """
    assert len(episodes.SHAPED_DERIVATIONS) == 7
    # Every lifted head is one the closed vocabulary already carried: the lint
    # refuses anything outside it, so a name here that it rejects would be a
    # verb this module invented.
    for head in episodes.SHAPED_DERIVATIONS:
        findings = episodes.lint([_probe([
            _TOTAL,
            _kind("reserves.booked_total", derive=f"{head}(reserves.central_estimate_total)"),
        ])])
        assert not any("closed derivation vocabulary" in f for f in findings), head


# ---------------------------------------------------------------------------
# The three shapes
# ---------------------------------------------------------------------------


def test_all_scalar_operands_still_compute_a_scalar() -> None:
    """The path every existing corpus takes, asserted as arithmetic.

    Byte-identity across the shipped corpora is the real gate; this says what
    the bytes mean — no grid, no map, the same subtraction of two numbers.
    """
    world = _run(_probe([
        _TOTAL,
        _kind("reserves.risk_margin_policy_pct", value_type="percent", amount=12.0),
        _kind(
            "reserves.risk_margin_standing",
            derive="percent_of(reserves.central_estimate_total,"
                   " reserves.risk_margin_policy_pct)",
        ),
    ]), quarters=("2026-03",))

    total = next(f for f in world.facts if f.kind == "reserves.central_estimate_total")
    standing = [f for f in world.facts if f.kind == "reserves.risk_margin_standing"]
    assert len(standing) == 1  # one fact, not a grid
    assert standing[0].period == "2026-03"  # the valuation's period, not a cohort's
    assert standing[0].value.amount == round(total.value.amount * 12.0 / 100, 2)


def test_two_grids_on_one_axis_map_cell_by_cell() -> None:
    """Per-cohort adverse development: the figure item 5 exists for.

    `minus(ultimate, ultimate_at_prior_valuation)` over two grids is one
    subtraction per accident quarter — and at a cohort's first appearance the
    comparative is zero by declaration, so its whole ultimate reads as
    development.
    """
    world = _run(_probe(
        [
            _TOTAL,
            _GRID,
            _kind(
                "reserves.ultimate_at_prior_valuation",
                cohort="accident_quarter",
                derive="prior_in_cohort(reserves.ultimate)",
            ),
            _kind(
                "reserves.adverse_development",
                cohort="accident_quarter",
                derive="minus(reserves.ultimate, reserves.ultimate_at_prior_valuation)",
            ),
        ],
        carry_forward=[episodes.CarryForwardSpec(
            from_kind="reserves.ultimate",
            to_kind="reserves.ultimate_at_prior_valuation",
            rule="derive",
        )],
    ))

    moments = sorted({
        fact.valid_from for fact in world.facts if fact.kind == "reserves.ultimate"
    })
    assert len(moments) == 2
    for at in moments:
        ultimate = _cells(world, "reserves.ultimate", at)
        was = _cells(world, "reserves.ultimate_at_prior_valuation", at)
        moved = _cells(world, "reserves.adverse_development", at)
        assert set(moved) == set(ultimate)  # a grid, on the same cohorts
        for cohort, amount in moved.items():
            assert amount == round(ultimate[cohort] - was[cohort], 2)

    # And the second valuation actually moved something: a grid of zeroes
    # would satisfy the arithmetic above and pin nothing.
    assert any(amount for amount in _cells(world, "reserves.adverse_development", moments[1]).values())


def test_a_scalar_broadcasts_across_a_grid() -> None:
    """One board percentage, four answers — the margin each cohort carries.

    The scalar is *not* rolled into the grid's total and it is not paired with
    one cell: it is applied to every cell, which is the only reading of "the
    policy applies to the triangle" that is not a choice made in silence.
    """
    world = _run(_probe([
        _TOTAL,
        _GRID,
        _kind("reserves.risk_margin_policy_pct", value_type="percent", amount=12.0),
        _kind(
            "reserves.risk_margin_standing",
            cohort="accident_quarter",
            derive="percent_of(reserves.ultimate, reserves.risk_margin_policy_pct)",
        ),
    ]), quarters=("2026-03",))

    ultimate = _cells(world, "reserves.ultimate")
    margin = _cells(world, "reserves.risk_margin_standing")
    assert set(margin) == set(ultimate)
    for cohort, amount in margin.items():
        assert amount == round(ultimate[cohort] * 12.0 / 100, 2)


# ---------------------------------------------------------------------------
# The two refusals
# ---------------------------------------------------------------------------


def _two_axis_probe() -> episodes.EpisodeSpec:
    return _probe([
        _TOTAL,
        _GRID,
        _kind(
            "reserves.ibnr",
            cohort="underwriting_year",
            derive="allocation_of(reserves.central_estimate_total)",
            parameter="reserves.cohort.ultimate",
        ),
        _kind(
            "reserves.booked_total",
            cohort="accident_quarter",
            derive="minus(reserves.ultimate, reserves.ibnr)",
        ),
    ])


def test_grids_on_different_axes_are_refused_by_the_lint() -> None:
    """An accident quarter and an underwriting year are not a couple."""
    findings = episodes.lint([_two_axis_probe()])
    assert any("takes grids on axes" in finding for finding in findings), findings


def test_grids_on_different_axes_are_refused_at_run_too() -> None:
    """The lint is advice; `install` does not run it.

    So the runner refuses the same thing rather than pairing cells by position
    and stating a figure with no meaning.
    """
    with pytest.raises(ValueError, match="different axes"):
        _run(_two_axis_probe(), quarters=("2026-03",))


def test_a_kind_whose_derivation_comes_out_gridded_must_declare_the_axis() -> None:
    """An undeclared grid's cells are checked by nothing.

    Completeness, roll-up and cohort sanity all key off `cohort`; a kind that
    mints a column without declaring one mints cells no grid check will ever
    look at — a hole that looks exactly like a passing corpus.
    """
    findings = episodes.lint([_probe([
        _TOTAL,
        _GRID,
        _kind("reserves.ibnr", derive="minus(reserves.ultimate, reserves.ultimate)"),
    ])])
    assert any("must declare" in finding and "accident_quarter" in finding
               for finding in findings), findings


def test_a_pair_reading_derivation_still_refuses_a_grid() -> None:
    """`ratio_pct` and its neighbours read a supersession *pair* — a two-tuple
    a grid would be silently mistaken for — so they are not lifted, and the
    old advice (declare a `rolls-up-to` parent, derive from that) still
    stands."""
    findings = episodes.lint([_probe([
        _TOTAL,
        _GRID,
        _kind(
            "reserves.held_vs_central_gap",
            value_type="percent",
            derive="ratio_pct(reserves.ultimate, reserves.central_estimate_total)",
        ),
    ])])
    assert any("as a scalar operand" in finding for finding in findings), findings


# ---------------------------------------------------------------------------
# What the insurer pack does with it
# ---------------------------------------------------------------------------


def test_the_pack_states_the_engines_own_identity_per_cohort() -> None:
    """`ultimate = paid + case + IBNR`, to the cent, at every valuation.

    The identity the insurance engine checks and the shipped pack could not
    state: it needs the diagonal (append-only, item 4) *and* a subtraction of
    two grids (item 5). Exact rather than close, and by construction rather
    than by luck — the incurred cell is a fraction of the ultimate cell it is
    derived from, so the IBNR that closes the identity cannot come out
    negative and the case reserve cannot either.
    """
    pack = packs.load(PACK)
    packs.archetype_of(pack)  # installs QuarterlyValuation
    world = InsuranceWorld.from_pack(pack, seed=SEED).build()
    for quarter in QUARTERS:
        world = world.run(
            episodes.AuthoredEpisode(episode="QuarterlyValuation", period=quarter)
        )

    cells = 0
    for ultimate in (f for f in world.facts if f.kind == "reserves.ultimate"):
        key = (ultimate.period, ultimate.valid_from)
        stated = {
            fact.kind: fact.value.amount
            for fact in world.facts
            if (fact.period, fact.valid_from) == key
            and fact.kind in ("claims.paid_to_date", "claims.incurred_to_date",
                              "reserves.ibnr", "reserves.adverse_development")
        }
        paid, incurred = stated["claims.paid_to_date"], stated["claims.incurred_to_date"]
        case = incurred - paid
        assert 0 < paid < incurred <= ultimate.value.amount
        assert stated["reserves.ibnr"] >= 0
        assert round(paid + case + stated["reserves.ibnr"], 2) == ultimate.value.amount
        cells += 1
    assert cells == 8  # four cohorts, two valuations

    assert world.compile().validate().violations == []
