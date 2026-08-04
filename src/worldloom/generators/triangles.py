"""The triangle generator.

Computes one quarter's cohort-level claims development for the affected
long-tail line: what was paid and incurred, at the prior valuation and this
one, and the actuarial estimates each valuation supports. Pure figures, no
facts — the episode generator (``reserving.py``) decides *when* each number
enters the world and at what authority, which is not a number's business to
know. Same division of labour as ``capital.py``.

**This is not chain-ladder, and that is deliberate.** A real reserving
engine fits development factors from a full triangle of historical diagonals
and projects them forward; building one would mean carrying years of
synthetic history nothing else in this corpus needs, and it would still be a
toy next to what real actuarial software does — effort spent making the
arithmetic *look* authoritative rather than making the corpus hard in the way
this vertical exists to be hard, which is about authority and supersession,
not curve-fitting. So the model here is the smallest one that can carry the
premise honestly: each cohort's ultimate moves by exactly its own adverse
emergence for the quarter, drawn from a named ``Rng`` stream and bounded to
stay inside the lore-stated magnitude (a "material but not implausible"
distortion) — auditable by inspection, and never mistaken for a real
actuarial projection because no development factors are anywhere in it.

Two disciplines carried over from ``capital.py``, for the same reason: book
(cohort) figures are *allocated* from a book-level total by largest
remainder, never drawn and summed, so a roll-up reconciles to its cohorts
exactly; and the corrected (strengthened) figures differ from the prior ones
by precisely the adverse-emergence amount, because the strengthening this
episode confirms has one cause and a figure that moved for any other reason
would be a second, unexplained movement.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..parameters import DEFAULT, Parameters
from ..rng import Rng
from .finance import allocate

MONEY = "AUD_millions"
PCT = "pct"

#: How many accident cohorts the affected line carries into a valuation.
#: Fixed at four — the ``~4 cohorts`` the design record scopes triangles to —
#: and derived from the episode, never the archetype: a many-unit pack must
#: not silently multiply the grid (design record, risk 2).
COHORT_COUNT = 4


@dataclass(frozen=True)
class CohortPosition:
    """One accident cohort's figures at both valuations."""

    accident_period: str
    paid_prior: int
    incurred_prior: int
    ultimate_prior: int
    ibnr_prior: int
    expected_incurred_current: int
    """What this cohort's incurred was expected to develop to, under the
    pattern the prior valuation's projection factors were calibrated on —
    before the 2024 transformation's distortion. Never itself minted as a
    fact; it exists so ``actual_vs_expected`` is a real subtraction rather
    than an invented number."""
    paid_current: int
    incurred_current: int
    actual_vs_expected: int
    """``incurred_current - expected_incurred_current``. Positive is adverse:
    the cohort closed more incurred than the calibrated pattern predicted."""
    ultimate_current: int
    ibnr_current: int


@dataclass(frozen=True)
class TrianglePosition:
    """One quarter's triangle: every cohort, plus the roll-up."""

    cohorts: tuple[CohortPosition, ...]
    paid_prior_total: int
    incurred_prior_total: int
    paid_current_total: int
    incurred_current_total: int
    central_estimate_prior: int
    """Sum of ``ultimate_prior`` across cohorts — the book's central estimate
    before this quarter's emergence."""
    central_estimate_current: int
    """Sum of ``ultimate_current`` — after strengthening."""
    total_movement: int
    """``central_estimate_current - central_estimate_prior``, exactly the sum
    of the cohorts' ``actual_vs_expected`` by construction."""
    pattern_change_amount: int
    """The benign share of ``total_movement``: attributable to the
    transformation programme changing *when* cases close, not the true cost."""
    deterioration_amount: int
    """The adverse share: ``total_movement - pattern_change_amount``, exactly."""
    margin_prior: int
    margin_released: int
    margin_current: int
    """``margin_prior - margin_released``. Goes negative when the release
    exceeds the standing buffer — the exact condition that opens the
    held-versus-central gap; see ``reserving.generate``'s comment on why the
    generator sizes ``margin_released`` to guarantee it."""
    booked_prior: int
    booked_strengthening: int
    booked_current: int
    held_vs_central_gap: int
    """``central_estimate_current - booked_current``. Positive means the
    booked reserve sits below the actuarial central estimate — the standing
    disagreement the margin decision memo exists to record."""


#: The two multiples that must stay strictly above 1.0, and what the corpus
#: loses if either one drops to it. Enforced here rather than in the pack
#: linter for two reasons. The linter only sees packs, and a ``Parameters``
#: reaches this generator by other routes too — ``with_overrides`` is public,
#: a recipe replays overrides with no pack file on hand, and a test or an
#: in-process caller passes one directly; a rule that only one of those routes
#: honours is not an invariant. And ``packs.py`` is core, where
#: ``tests/test_thin_waist.py`` forbids ``reserves.`` outright: stating the
#: rule there would mean teaching core an insurer's vocabulary and duplicating
#: the reasoning that only this module holds.
_DEFICIT_MULTIPLES: tuple[tuple[str, str], ...] = (
    ("reserves.decision.margin_release_multiple",
     "the release stops being guaranteed to exceed the standing margin, and the"
     " booked-below-central gap this vertical exists to pose stops opening"),
    ("reserves.decision.movement_multiple",
     "the recommended strengthening stops being guaranteed to exceed the release,"
     " and booked_strengthening — the amount finance actually put up — can come"
     " out zero or negative"),
)


def _check_deficit_multiples(physics: Parameters) -> None:
    """Refuse physics that lets the held-versus-central gap fail to open.

    ``generate``'s sizing order *guarantees* the gap — the whole point of drawing
    margin, then release, then movement in dependency order rather than
    independently and hoping. That guarantee rests entirely on both multiples
    being above 1.0, and until the physics registry existed it rested on them
    being literals nobody could reach. Now a pack can reach them, so the
    guarantee needs saying in code: the registry's ``about`` says a pack may
    tune the severity and must not tune it away, and prose in a docstring is
    not a check.

    Refused rather than clamped, for the same reason ``with_overrides``
    refuses an unknown name rather than ignoring it. A clamped span builds a
    perfectly valid corpus in which ``held_vs_central_gap`` is zero or
    negative, insurance check (g) skips itself on exactly that condition
    (``if gap.value.amount <= 0: continue``), and the author is told nothing —
    they get a corpus that no longer poses the contest the vertical exists for
    and no sign at all that their intent was dropped.
    """
    for name, consequence in _DEFICIT_MULTIPLES:
        span = physics.span(name)
        if span.low <= 1.0:
            raise ValueError(
                f"{name} must stay strictly above 1.0; got [{span.low}, {span.high}]."
                f" At or below 1.0 {consequence}. A pack may tune how severe the"
                " deficit is; it may not tune the deficit away."
            )


def generate(
    rng: Rng,
    *,
    accident_periods: tuple[str, ...],
    risk_margin_policy_pct: float,
    physics: Parameters = DEFAULT,
) -> TrianglePosition:
    """Draw one quarter's triangle for ``len(accident_periods)`` cohorts.

    ``accident_periods`` is oldest first, and its length is what actually
    determines the cohort count — not ``COHORT_COUNT``, which only documents
    the design record's own choice. The caller derives the periods from the
    episode's own valuation date, never from the archetype (risk 2).
    """
    _check_deficit_multiples(physics)

    # Prior-valuation figures only, one tuple per cohort — kept separate from
    # `CohortPosition` because that model's current-valuation fields are not
    # known until `total_movement` is sized below, and a placeholder instance
    # carrying zeros for fields that are about to be overwritten is a value
    # that is briefly wrong for no reason.
    priors: list[tuple[str, int, int, int, int, int]] = []
    paid_prior_total = incurred_prior_total = 0
    paid_current_total = incurred_current_total = 0

    for accident_period in accident_periods:
        cohort_rng = rng.derive(f"cohort/{accident_period}")

        # The prior valuation's position. Mid-size figures for a single
        # accident quarter of a long-tail book: tens of millions ultimate,
        # a minority of it still IBNR this many quarters after the loss.
        ultimate_prior = physics.integer(
            "reserves.cohort.ultimate", cohort_rng.derive("ultimate"))
        incurred_prior = round(ultimate_prior * physics.number(
            "reserves.cohort.incurred_ratio", cohort_rng.derive("incurred_ratio")))
        paid_prior = round(incurred_prior * physics.number(
            "reserves.cohort.paid_ratio", cohort_rng.derive("paid_ratio")))
        ibnr_prior = ultimate_prior - incurred_prior

        # Normal quarterly development, under the pattern the prior valuation
        # was calibrated on: a modest fraction of the remaining IBNR closes
        # out as incurred every quarter, distortion or not.
        expected_development = round(ibnr_prior * physics.number(
            "reserves.cohort.expected_development",
            cohort_rng.derive("expected_development")))
        expected_incurred_current = incurred_prior + expected_development

        priors.append((
            accident_period, paid_prior, incurred_prior, ultimate_prior,
            ibnr_prior, expected_incurred_current,
        ))
        paid_prior_total += paid_prior
        incurred_prior_total += incurred_prior

    central_estimate_prior = sum(p[3] for p in priors)

    # Margin sizing first, then the movement and the release are sized off
    # it, in that order — this is what guarantees (never merely makes likely)
    # that a release opens the held-versus-central gap check g exists to
    # exercise: drawing the three quantities independently and hoping the
    # scenario materialises would make the corpus's own hardest contest a
    # coin flip on the seed.
    margin_prior = round(central_estimate_prior * risk_margin_policy_pct / 100)
    # The release exceeds the standing margin — the deficit condition. Not
    # merely "large": this is the one quarter the design record says the gap
    # opens, not a possibility among several, which is why both multiples are
    # gated above rather than trusted.
    margin_released = round(margin_prior * physics.number(
        "reserves.decision.margin_release_multiple", rng.derive("margin_released")))
    total_movement = round(margin_released * physics.number(
        "reserves.decision.movement_multiple", rng.derive("total_movement")))

    # Each cohort's actual-vs-expected deviation is its allocated share of the
    # book-level movement, weighted by remaining IBNR — a book with more
    # unresolved liability absorbs more of the quarter's adverse surprise.
    # Largest-remainder, so the cohorts sum to `total_movement` exactly.
    weights = [p[4] for p in priors]  # ibnr_prior
    shares = allocate(total_movement, weights)

    resolved: list[CohortPosition] = []
    for (accident_period, paid_prior, incurred_prior, ultimate_prior,
         ibnr_prior, expected_incurred_current), share in zip(priors, shares):
        incurred_current = expected_incurred_current + share
        paid_current = paid_prior + round(
            (incurred_current - incurred_prior)
            # Per-cohort stream, so the derive key is built from the cohort
            # while the range is the one book-level parameter — unlike the
            # prior-valuation draws above, this one is not inside the cohort
            # loop's own `cohort_rng`.
            * physics.number(
                "reserves.cohort.paid_out_fraction",
                rng.derive(f"cohort/{accident_period}/paid_out"),
            )
        )
        ultimate_current = ultimate_prior + share
        ibnr_current = ultimate_current - incurred_current
        resolved.append(CohortPosition(
            accident_period=accident_period, paid_prior=paid_prior,
            incurred_prior=incurred_prior, ultimate_prior=ultimate_prior,
            ibnr_prior=ibnr_prior, expected_incurred_current=expected_incurred_current,
            paid_current=paid_current, incurred_current=incurred_current,
            actual_vs_expected=share, ultimate_current=ultimate_current,
            ibnr_current=ibnr_current,
        ))
        paid_current_total += paid_current
        incurred_current_total += incurred_current

    central_estimate_current = central_estimate_prior + total_movement

    # The attribution split: benign (the transformation changed *when* cases
    # close) against adverse (claims are genuinely costing more). Minority
    # benign, because the premise is a genuine deterioration the corpus later
    # confirms — the split itself is what phase 2's revision moves.
    pattern_fraction = physics.number(
        "reserves.attribution.pattern_fraction", rng.derive("pattern_fraction"))
    pattern_change_amount = round(total_movement * pattern_fraction)
    deterioration_amount = total_movement - pattern_change_amount

    booked_prior = central_estimate_prior + margin_prior
    booked_strengthening = total_movement - margin_released
    booked_current = booked_prior + booked_strengthening
    margin_current = margin_prior - margin_released
    held_vs_central_gap = central_estimate_current - booked_current

    return TrianglePosition(
        cohorts=tuple(resolved),
        paid_prior_total=paid_prior_total, incurred_prior_total=incurred_prior_total,
        paid_current_total=paid_current_total, incurred_current_total=incurred_current_total,
        central_estimate_prior=central_estimate_prior,
        central_estimate_current=central_estimate_current,
        total_movement=total_movement,
        pattern_change_amount=pattern_change_amount,
        deterioration_amount=deterioration_amount,
        margin_prior=margin_prior, margin_released=margin_released,
        margin_current=margin_current,
        booked_prior=booked_prior, booked_strengthening=booked_strengthening,
        booked_current=booked_current, held_vs_central_gap=held_vs_central_gap,
    )
