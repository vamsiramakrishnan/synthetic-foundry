"""The reserving episode generator: one quarterly valuation, phase 1.

Produces "The Living Estimate" — the insurance vertical's first episode — in
``operations.py``'s idiom: a frozen result carrying events, facts, and a keys
dict of named handles, with every timestamp pure arithmetic on the period
string and every drawn number taken from a stream named for what it is.

The episode's shape, and why each part is there:

* Two valuations sit inside one run. The prior valuation's diagonal and
  estimates are minted at the prior valuation's own ``valid_from`` — pure
  arithmetic into the past, the founding-facts pattern ``regulatory.py``
  already uses for the standing capital minimum — so the corpus carries a
  genuine two-link supersession chain (prior estimate superseded by
  strengthened estimate) from a single episode run, mirroring how banking
  mints filed-then-restated inside one quarter.

* Three mutation disciplines run at once, on purpose. Triangle diagonals
  (``claims.*_to_date``) are minted and never touched again. Reserve
  estimates (``reserves.ultimate``, ``reserves.ibnr``) form a supersession
  chain in which the superseded prior estimate carries no marker that it was
  wrong — it wasn't; the corpus's own record was simply incomplete when it
  was made. The booked total (``reserves.booked_total``) is a frozen
  snapshot, re-minted every valuation and never superseded, the closest
  analogue this vertical has to banking's ``_as_filed`` permanence.

* The decision is sized to fire the trap it exists to demonstrate, not to
  merely risk it. ``generators/triangles.generate`` guarantees — not merely
  makes likely — that this quarter's margin release exceeds the standing
  margin, which is what opens a real held-versus-central gap (booked below
  central) rather than a coincidence of the seed. See that module's comment
  on why the three quantities are sized in dependency order.

* The two authorities never resolve. The central estimate
  (``reserves.ultimate``/``reserves.central_estimate_total``, CONFIRMED) and
  the booked reserve (``reserves.booked_total``, SYSTEM_OF_RECORD) both stand
  as the corpus's current answer to two different questions — "what does the
  actuary believe" and "what is carried on the balance sheet" — reconciled
  only by the margin fact, never by one outranking the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from collections.abc import Mapping

from ..ids import Minter
from ..models import Authority, CanonicalFact, EnterpriseEvent, Quantity
from ..rng import Rng
from . import episode_text
from .finance import previous_periods
from .operations import _at, business_days_after, period_end
from .triangles import TrianglePosition

MONEY = "AUD_millions"
PCT = "pct"

#: How many accident cohorts back from the valuation the episode asks the
#: triangle generator for. An episode-shape decision (how many quarterly
#: steps back), not a figure decision, so it lives here rather than in
#: ``triangles.py`` — which only documents the design record's own count.
COHORT_COUNT = 4

#: The insurance engine's surface text — see ``generators/episode_text`` and
#: the identical table in ``operations.py`` and ``regulatory.py``. Defaults
#: are the strings this engine always used, extracted verbatim so stock
#: corpora are byte-identical; a pack overrides by key through
#: ``episode_text``.
TEXT: dict[str, str] = {
    'event.close_started':
        '{period} month-end close commenced; the overnight ledger sequence began.',
    'event.close_finalised':
        '{period} close finalised and the ledger locked on the committed date.',
    'event.prior_valuation_recorded':
        'The prior valuation is on record: the {prior_period} diagonal, the actuarial '
        'central estimate by cohort, and the reserve booked against it.',
    'event.current_diagonal_recorded':
        "This quarter's paid and incurred diagonal was pulled from the claims system for "
        'the long-tail liability book.',
    'event.emergence_assessed':
        'Actual-versus-expected emergence was assessed by cohort against the pattern the '
        'prior valuation was calibrated on. The long-tail liability book shows adverse '
        'emergence across every open accident cohort.',
    'event.attribution_determined':
        'The deviation was attributed: part pattern change from the 2024 claims-'
        'transformation programme, part genuine deterioration. The two do not resolve to '
        'one figure — both are booked as a split.',
    'event.reserves_strengthened':
        'The actuarial central estimate was strengthened by cohort to reflect the '
        "quarter's emergence. The prior estimate is superseded, not marked wrong — it was "
        'the correct reading of an incomplete record.',
    'event.committee_recommended':
        'The reserving committee recommended booking the full central strengthening.',
    'event.reserves_partially_booked':
        'Finance booked part of the recommended strengthening and released risk margin to '
        'absorb the rest, under the standing combined-ratio target. The booked reserve now '
        "sits below the actuary's central estimate — a standing, recorded disagreement, not "
        'an error.',
    'event.booked_total_frozen':
        "This quarter's booked reserve for the long-tail liability book was posted to the "
        'general ledger.',
    'fact.philosophy':
        'Risk margin is held at the 75th percentile of the actuarial central estimate '
        'range, released only against a reserving committee recommendation',
    'fact.attribution_pattern':
        'Pattern change from the 2024 claims-transformation programme: cases are closing '
        'earlier and at higher case reserves than the calibrated pattern assumed, which is '
        'not itself a change in the true cost of claims',
    'fact.attribution_deterioration':
        'Genuine deterioration: claims on the long-tail liability book are costing more '
        'than the prior valuation assumed',
    'fact.committee_recommendation':
        'The reserving committee recommends booking the full central strengthening this '
        'quarter, with no margin release',
    'fact.gap_note':
        "The booked reserve is below the actuary's central estimate for the long-tail "
        'liability book; the margin decision memo records why',
}


@dataclass(frozen=True)
class ReservingEpisode:
    """The events and facts of one quarterly valuation, phase 1."""

    events: tuple[EnterpriseEvent, ...]
    facts: tuple[CanonicalFact, ...]
    period: str
    prior_period: str
    valuation_at: datetime
    prior_valuation_at: datetime
    keys: dict[str, str] = field(default_factory=dict)
    """Named handles for the facts and events documents and evaluations cite."""


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    roles: dict[str, str],
    triangle: TrianglePosition,
    lore_by_target: dict[str, list[str]],
    risk_margin_policy_pct: float,
    text: Mapping[str, str] | None = None,
    existing_philosophy: CanonicalFact | None = None,
    existing_margin_policy: CanonicalFact | None = None,
) -> ReservingEpisode:
    """Generate the phase-1 reserving cycle for the quarter ending *period*.

    ``triangle`` is the pre-drawn figure set (``generators.triangles``) —
    passed in rather than drawn here, the same separation ``regulatory.py``
    keeps from ``capital.py``: this function decides *when* a number enters
    the world and at what authority, never what the number is.

    ``existing_philosophy``/``existing_margin_policy`` are the standing
    facts already on the world's record, if a prior quarter minted them —
    see the ``existing_minimum`` comment in ``regulatory.py``, which this
    mirrors exactly: ``period=None`` because these never belong to a quarter.
    """
    t = episode_text.merged(TEXT, text)
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}

    ends = period_end(period)
    prior_period = previous_periods(period, 3)[0]
    prior_ends = period_end(prior_period)
    bd = lambda n: business_days_after(ends, n)  # noqa: E731 — read as arithmetic
    prior_bd = lambda n: business_days_after(prior_ends, n)  # noqa: E731

    lt = roles["cat_lt_liability"]
    claims_sys, actuarial_sys = roles["sys_claims"], roles["sys_actuarial"]
    gl = roles["sys_general_ledger"]

    transformation_lore = lore_by_target.get("triangle_distortion/long_tail", [])
    booking_lore = lore_by_target.get("finance/partial_booking", [])
    committee_lore = lore_by_target.get("reserving_committee_signoff", [])

    def event(kind: str, at: datetime, summary: str, *, actors: list[str] = [],
              systems: list[str] = [], caused_by: list[str] = [],
              lore: list[str] = []) -> EnterpriseEvent:
        made = EnterpriseEvent(id=minter.next("EV"), kind=kind, occurred_at=at,
                               summary=summary, actors=actors, systems=systems,
                               caused_by=caused_by, lore_ids=lore)
        events.append(made)
        keys[f"event_{kind}"] = made.id
        return made

    def fact(kind: str, subject: str, cohort_period: str | None, *, at: datetime,
             authority: Authority, event_id: str | None, source: str,
             amount: int | None = None, text_value: str | None = None,
             until: datetime | None = None, supersedes: str | None = None,
             lore: list[str] | None = None) -> CanonicalFact:
        made = CanonicalFact(
            id=minter.next("FACT"), kind=kind, subject=subject, period=cohort_period,
            value=Quantity(amount=amount, unit=MONEY) if amount is not None else None,
            text_value=text_value, valid_from=at, valid_to=until,
            authority=authority, source_system=source, event_id=event_id,
            supersedes=supersedes, lore_ids=lore or [],
        )
        facts.append(made)
        return made

    # -- the quarterly close, uneventful: this episode's story belongs to the
    # reserving cycle, not the close. Reuses retail's close.* kinds verbatim.
    close_start = event(
        "close_started", _at(bd(1), 6, 0),
        t["event.close_started"].format(period=period),
        actors=[roles["financial_controller"]], systems=[gl],
    )
    keys["fact_close_due"] = fact(
        "close.due_date", company_id, period, at=close_start.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=close_start.id, source=gl,
        text_value=bd(4).isoformat(),
    ).id
    close_done = event(
        "close_finalised", _at(bd(4), 16, 40),
        t["event.close_finalised"].format(period=period),
        actors=[roles["financial_controller"]], systems=[gl], caused_by=[close_start.id],
    )
    keys["fact_close_status"] = fact(
        "close.status", company_id, period, at=close_done.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=close_done.id, source=gl,
        text_value="final",
    ).id
    keys["fact_close_delay"] = fact(
        "close.delay", company_id, period, at=close_done.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=close_done.id, source=gl,
        amount=0,
    ).id

    # -- standing facts: resolved from the world if a prior quarter already
    # minted them, minted here otherwise. `period=None` throughout — see the
    # docstring above and `regulatory.py`'s identical `existing_minimum`
    # comment, which this mirrors exactly.
    prior_valuation_at = _at(prior_bd(10), 9, 0)
    if existing_philosophy is not None:
        philosophy_fact = existing_philosophy
    else:
        philosophy_fact = CanonicalFact(
            id=minter.next("FACT"), kind="reserves.philosophy", subject=company_id,
            text_value=t["fact.philosophy"], valid_from=prior_valuation_at,
            authority=Authority.SYSTEM_OF_RECORD, source_system=gl,
        )
    facts.append(philosophy_fact)
    keys["fact_philosophy"] = philosophy_fact.id

    if existing_margin_policy is not None:
        margin_policy_fact = existing_margin_policy
    else:
        margin_policy_fact = CanonicalFact(
            id=minter.next("FACT"), kind="reserves.risk_margin_policy_pct", subject=company_id,
            value=Quantity(amount=risk_margin_policy_pct, unit=PCT), valid_from=prior_valuation_at,
            authority=Authority.SYSTEM_OF_RECORD, source_system=gl,
        )
    facts.append(margin_policy_fact)
    keys["fact_margin_policy"] = margin_policy_fact.id

    # -- the prior valuation, minted now but dated to when it actually stood.
    # `current_valuation_at` is known up front (like `regulatory.py`'s
    # `restated_at`) so the prior estimates can be closed (`until=`) exactly
    # when the strengthening below supersedes them.
    current_valuation_at = _at(bd(18), 11, 0)

    prior_recorded = event(
        "prior_valuation_recorded", prior_valuation_at,
        t["event.prior_valuation_recorded"].format(period=period, prior_period=prior_period),
        actors=[roles["reserving_actuary"]], systems=[claims_sys, actuarial_sys],
    )

    for cohort in triangle.cohorts:
        keys[f"fact_paid_prior_{cohort.accident_period}"] = fact(
            "claims.paid_to_date", lt, cohort.accident_period, at=prior_valuation_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=prior_recorded.id,
            source=claims_sys, amount=cohort.paid_prior,
        ).id
        keys[f"fact_incurred_prior_{cohort.accident_period}"] = fact(
            "claims.incurred_to_date", lt, cohort.accident_period, at=prior_valuation_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=prior_recorded.id,
            source=claims_sys, amount=cohort.incurred_prior,
        ).id
    keys["fact_paid_prior_rollup"] = fact(
        "claims.paid_to_date", lt, None, at=prior_valuation_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=prior_recorded.id,
        source=claims_sys, amount=triangle.paid_prior_total,
    ).id
    keys["fact_incurred_prior_rollup"] = fact(
        "claims.incurred_to_date", lt, None, at=prior_valuation_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=prior_recorded.id,
        source=claims_sys, amount=triangle.incurred_prior_total,
    ).id

    # Prior estimates, CONFIRMED (the actuarial platform's view): each closed
    # at the moment the strengthening below supersedes it, with no
    # ruled-out marker — the discipline this vertical exists to exercise
    # (module docstring).
    prior_ultimate_ids: dict[str, str] = {}
    prior_ibnr_ids: dict[str, str] = {}
    for cohort in triangle.cohorts:
        prior_ultimate_ids[cohort.accident_period] = fact(
            "reserves.ultimate", lt, cohort.accident_period, at=prior_valuation_at,
            authority=Authority.CONFIRMED, event_id=prior_recorded.id, source=actuarial_sys,
            amount=cohort.ultimate_prior, until=current_valuation_at,
        ).id
        prior_ibnr_ids[cohort.accident_period] = fact(
            "reserves.ibnr", lt, cohort.accident_period, at=prior_valuation_at,
            authority=Authority.CONFIRMED, event_id=prior_recorded.id, source=actuarial_sys,
            amount=cohort.ibnr_prior, until=current_valuation_at,
        ).id
        # Named explicitly, beside the superseding (current) keys minted
        # below, rather than left reachable only by walking `supersedes` —
        # a document's `required_fact_ids` needs the literal id, and the
        # temporal_state case that asks "what was it as at the prior
        # valuation" needs one too.
        keys[f"fact_ultimate_prior_{cohort.accident_period}"] = prior_ultimate_ids[cohort.accident_period]
        keys[f"fact_ibnr_prior_{cohort.accident_period}"] = prior_ibnr_ids[cohort.accident_period]
    keys["fact_central_prior"] = fact(
        "reserves.central_estimate_total", lt, None, at=prior_valuation_at,
        authority=Authority.CONFIRMED, event_id=prior_recorded.id, source=actuarial_sys,
        amount=triangle.central_estimate_prior,
    ).id
    keys["fact_margin_prior"] = fact(
        "reserves.risk_margin_remaining", lt, None, at=prior_valuation_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=prior_recorded.id, source=gl,
        amount=triangle.margin_prior,
    ).id
    keys["fact_booked_prior"] = fact(
        "reserves.booked_total", lt, None, at=prior_valuation_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=prior_recorded.id, source=gl,
        amount=triangle.booked_prior,
    ).id

    # -- this quarter's diagonal --------------------------------------------
    current_recorded = event(
        "current_diagonal_recorded", _at(bd(10), 9, 30),
        t["event.current_diagonal_recorded"],
        actors=[roles["reserving_actuary"]], systems=[claims_sys],
        caused_by=[close_done.id],
    )
    for cohort in triangle.cohorts:
        keys[f"fact_paid_current_{cohort.accident_period}"] = fact(
            "claims.paid_to_date", lt, cohort.accident_period, at=current_recorded.occurred_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=current_recorded.id,
            source=claims_sys, amount=cohort.paid_current,
        ).id
        keys[f"fact_incurred_current_{cohort.accident_period}"] = fact(
            "claims.incurred_to_date", lt, cohort.accident_period, at=current_recorded.occurred_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=current_recorded.id,
            source=claims_sys, amount=cohort.incurred_current,
        ).id
    keys["fact_paid_current_rollup"] = fact(
        "claims.paid_to_date", lt, None, at=current_recorded.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=current_recorded.id,
        source=claims_sys, amount=triangle.paid_current_total,
    ).id
    keys["fact_incurred_current_rollup"] = fact(
        "claims.incurred_to_date", lt, None, at=current_recorded.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=current_recorded.id,
        source=claims_sys, amount=triangle.incurred_current_total,
    ).id

    # -- emergence: adverse actual-versus-expected, per cohort ---------------
    emergence = event(
        "emergence_assessed", _at(bd(14), 10, 0),
        t["event.emergence_assessed"],
        actors=[roles["reserving_actuary"]], systems=[actuarial_sys],
        caused_by=[current_recorded.id], lore=transformation_lore,
    )
    for cohort in triangle.cohorts:
        keys[f"fact_avse_{cohort.accident_period}"] = fact(
            "claims.actual_vs_expected", lt, cohort.accident_period, at=emergence.occurred_at,
            authority=Authority.CONFIRMED, event_id=emergence.id, source=actuarial_sys,
            amount=cohort.actual_vs_expected, lore=transformation_lore,
        ).id

    # -- attribution: a checkable split, not a resolved figure ---------------
    attribution = event(
        "attribution_determined", _at(bd(16), 14, 0),
        t["event.attribution_determined"],
        actors=[roles["chief_actuary"], roles["reserving_actuary"]],
        caused_by=[emergence.id], lore=transformation_lore,
    )
    keys["fact_attribution_pattern"] = fact(
        "reserves.attribution_pattern_change", lt, None, at=attribution.occurred_at,
        authority=Authority.CONFIRMED, event_id=attribution.id, source=actuarial_sys,
        amount=triangle.pattern_change_amount, lore=transformation_lore,
    ).id
    keys["fact_attribution_deterioration"] = fact(
        "reserves.attribution_deterioration", lt, None, at=attribution.occurred_at,
        authority=Authority.CONFIRMED, event_id=attribution.id, source=actuarial_sys,
        amount=triangle.deterioration_amount, lore=transformation_lore,
    ).id

    # -- strengthening: supersedes the priors, no ruled-out marker -----------
    strengthened = event(
        "reserves_strengthened", current_valuation_at,
        t["event.reserves_strengthened"],
        actors=[roles["chief_actuary"]], systems=[actuarial_sys],
        caused_by=[attribution.id],
    )
    for cohort in triangle.cohorts:
        keys[f"fact_ultimate_current_{cohort.accident_period}"] = fact(
            "reserves.ultimate", lt, cohort.accident_period, at=strengthened.occurred_at,
            authority=Authority.CONFIRMED, event_id=strengthened.id, source=actuarial_sys,
            amount=cohort.ultimate_current, supersedes=prior_ultimate_ids[cohort.accident_period],
        ).id
        keys[f"fact_ibnr_current_{cohort.accident_period}"] = fact(
            "reserves.ibnr", lt, cohort.accident_period, at=strengthened.occurred_at,
            authority=Authority.CONFIRMED, event_id=strengthened.id, source=actuarial_sys,
            amount=cohort.ibnr_current, supersedes=prior_ibnr_ids[cohort.accident_period],
        ).id
    keys["fact_central_current"] = fact(
        "reserves.central_estimate_total", lt, None, at=strengthened.occurred_at,
        authority=Authority.CONFIRMED, event_id=strengthened.id, source=actuarial_sys,
        amount=triangle.central_estimate_current,
    ).id

    # -- the committee: recommends the full strengthening --------------------
    committee = event(
        "committee_recommended", _at(bd(20), 15, 0),
        t["event.committee_recommended"],
        actors=[roles["chief_actuary"], roles["cfo"], roles["claims_director"]],
        caused_by=[strengthened.id], lore=committee_lore,
    )
    keys["fact_committee_recommendation"] = fact(
        "reserves.committee_recommendation", lt, None, at=committee.occurred_at,
        authority=Authority.CONFIRMED, event_id=committee.id, source=actuarial_sys,
        amount=triangle.total_movement, text_value=t["fact.committee_recommendation"],
        lore=committee_lore,
    ).id

    # -- the decision: partial booking, margin release, the gap opens --------
    decided = event(
        "reserves_partially_booked", _at(bd(22), 11, 0),
        t["event.reserves_partially_booked"],
        actors=[roles["cfo"], roles["chief_actuary"]],
        caused_by=[committee.id], lore=booking_lore,
    )
    keys["fact_booked_strengthening"] = fact(
        "reserves.booked_strengthening", lt, None, at=decided.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=decided.id, source=gl,
        amount=triangle.booked_strengthening, lore=booking_lore,
    ).id
    keys["fact_margin_released"] = fact(
        "reserves.margin_released", lt, None, at=decided.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=decided.id, source=gl,
        amount=triangle.margin_released, lore=booking_lore,
    ).id
    keys["fact_margin_current"] = fact(
        "reserves.risk_margin_remaining", lt, None, at=decided.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=decided.id, source=gl,
        amount=triangle.margin_current,
    ).id
    keys["fact_held_vs_central_gap"] = fact(
        "reserves.held_vs_central_gap", lt, None, at=decided.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=decided.id, source=gl,
        amount=triangle.held_vs_central_gap, lore=booking_lore,
    ).id

    # -- the frozen snapshot: never superseded, never closed -----------------
    frozen = event(
        "booked_total_frozen", _at(bd(23), 9, 0),
        t["event.booked_total_frozen"],
        actors=[roles["financial_controller"]], systems=[gl],
        caused_by=[decided.id],
    )
    keys["fact_booked_current"] = fact(
        "reserves.booked_total", lt, None, at=frozen.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=frozen.id, source=gl,
        amount=triangle.booked_current,
    ).id

    return ReservingEpisode(
        events=tuple(events), facts=tuple(facts), period=period,
        prior_period=prior_period, valuation_at=current_valuation_at,
        prior_valuation_at=prior_valuation_at, keys=keys,
    )


__all__ = ["COHORT_COUNT", "ReservingEpisode", "TEXT", "generate"]
