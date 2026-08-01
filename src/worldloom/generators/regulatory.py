"""The regulatory episode generator: one quarterly capital return, challenged.

Produces "The Challenged Return" — the banking vertical's first episode — in
``operations.py``'s idiom: a frozen result carrying events, facts, and a keys
dict of named handles, with every timestamp pure arithmetic on the period
string and every drawn number taken from a stream named for what it is.

The episode's shape, and why each part is there:

* Three cadences run at once. The March monthly close locks the ledger
  (retail's ``close.*`` fact kinds, reused verbatim so cross-vertical
  evaluation code stays shared); the daily liquidity series ticks through the
  window; the quarterly capital return is the spine. Concurrency is the point —
  the daily cadence is what catches the quarterly cadence's error.

* The wrong figure is a decision, not an accident. Second-line review
  challenges the SME collateral treatment *on the record* before filing; a
  lore norm (returns file on the due date, challenges are logged, not
  blocking) means the CFO signs anyway. Both facts stand, at different
  authority, unresolved — the live disagreement window every contested-
  standing evaluation needs.

* Detection is structural. ``svc_rwa_engine`` and ``svc_lcr_daily`` share one
  upstream, and only the daily path reconciles against the collateral system,
  so the graph itself states why one path filed wrong and the other flagged
  the break. No document says so; the join is only in the dependency graph
  and the RCA.

* The filing is immutable. Correction arrives as a *restatement* — a new
  SYSTEM_OF_RECORD artifact whose ``restates`` edge points at the filed
  return, which keeps its lifecycle forever. At the fact layer truth moves on
  (the corrected ratio supersedes the filed one); at the artifact layer the
  record stands. ``capital.cet1_ratio_as_filed`` is minted at filing and never
  superseded, which is what keeps "what was reported as of a date between
  filing and restatement" answerable after the truth has moved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from collections.abc import Mapping

from ..ids import Minter
from ..models import Authority, CanonicalFact, EnterpriseEvent, Quantity
from ..rng import Rng
from . import episode_text
from .capital import CapitalPosition
from .liquidity import LiquiditySeries
from .operations import _at, _text, business_days_after, period_end

MONEY = "AUD_millions"
PCT = "pct"
BPS = "bps"

#: How many consecutive business days the daily liquidity series covers, ending
#: the day after the reconciliation break. Long enough that the daily cadence
#: demonstrably did not pause between filing and detection; short enough that
#: the fact ledger is not padded with a quarter of identical observations.
LIQUIDITY_DAYS = 6


#: The challenged-return engine's surface text — see `generators/episode_text`
#: and the identical table in `operations.py`. Defaults are the strings this
#: engine always used, extracted verbatim by AST so stock corpora are
#: byte-identical; a pack overrides by key through `episode_text`.
TEXT: dict[str, str] = {
    'event.close_started':
        '{period} month-end close commenced; the overnight ledger sequence began.',
    'event.close_finalised':
        '{period} close finalised and the ledger locked on the committed date.',
    'event.capital_return_preparation_started':
        'Preparation of the capital adequacy return for the quarter ended {period} began from the locked ledger.',
    'event.working_paper_issued':
        "The RWA working paper was issued, treating the SME Secured Lending book's collateral as fully secured.",
    'event.second_line_review_started':
        'Prudential Risk began its pre-lodgement review of the draft return.',
    'event.challenge_raised':
        'Prudential Risk challenged the SME Secured collateral treatment on the record: sampled revaluations looked stale and the fully-secured treatment could not be confirmed. The challenge was logged with status open.',
    'event.return_approved':
        "The CFO approved the return for lodgement at the preparer's figure. The second-line challenge remained open: returns file on the due date, and open challenges are logged, not blocking.",
    'event.capital_return_filed':
        'The capital adequacy return for the quarter ended {period} was lodged with the Prudential Standards Authority via the filing portal.',
    'event.liquidity_report_submitted':
        'The daily liquidity coverage report was produced and submitted — the daily cadence running as usual after the quarterly lodgement.',
    'event.liquidity_cadence_continued':
        'The daily liquidity cadence continued between the lodgement and the detection that follows — the two clocks genuinely overlap.',
    'event.reconciliation_break_detected':
        "The daily liquidity calculator's reconciliation of collateral positions against the collateral register flagged a break. The quarterly capital path carries no such control.",
    'event.incident_opened':
        'Service operations opened incident {incident_ref} at priority P2 against collateral-valuation-sync.',
    'event.hypothesis_recorded':
        'Initial triage attributed the break to the market data service applying the end-of-day FX revaluation twice to foreign-currency collateral.',
    'fact.initial_hypothesis':
        'The market data service applied the end-of-day FX revaluation twice to foreign-currency collateral',
    'event.hypothesis_superseded':
        'The FX double-application hypothesis was ruled out: the rate log shows a single end-of-day application in the window.',
    'event.root_cause_confirmed':
        'Root cause confirmed: a stale collateral-valuation mapping left over from the 2023 collateral-system migration. Revaluations had lapsed for the SME Secured Lending book, leaving {affected:,} loan facilities carried at stale collateral values.',
    'fact.confirmed_cause':
        'Stale collateral-valuation mapping left over from the 2023 collateral-system migration; revaluations lapsed for the SME Secured Lending book',
    'event.capital_impact_assessed':
        'Credit risk analytics quantified the impact: risk-weighted assets for the SME Secured book were understated in the filed return, and the corrected CET1 ratio remains above the PSA 110 minimum. A restatement is required.',
    'event.regulator_notified':
        "The CFO notified the Prudential Standards Authority of a material error in the filed return, within the PSA 110 notification window. The regulator's response is not recorded in this corpus.",
    'event.restatement_prepared':
        'First-line regulatory reporting prepared the restatement of the filed return.',
    'event.working_paper_revised':
        'The RWA working paper was revised to version 2 with the corrected treatment — a working note may be revised, because it is not a filing.',
    'event.restatement_reviewed':
        'Prudential Risk reviewed the restatement and, this time, signed off.',
    'event.restatement_approved':
        'The CFO and CRO countersigned the restatement for lodgement.',
    'event.return_restated':
        'The restatement was lodged. The original return stays on the record unchanged; the restatement states which figures moved and why.',
    'event.control_failure_identified':
        'Internal audit upheld the second-line challenge and classified the underlying failure: the revaluation schedule has no registered owner, and the quarterly capital path carries no reconciliation control.',
    'event.remediation_created':
        'Two remediation tickets raised: assign revaluation-schedule ownership with a mandatory second-line reviewer, and automate revaluation-lapse detection on the quarterly path.',
    'fact.challenge':
        'Sampled collateral revaluations for the SME Secured Lending book appear stale; the fully-secured treatment cannot be confirmed from the register',
    'fact.reconciliation_break':
        'Collateral positions consumed by the daily liquidity calculation failed reconciliation against the collateral register',
    'fact.incident_opened':
        '{incident_ref} opened at priority P2 against collateral-valuation-sync',
    'fact.cause_ruled_out':
        'The FX rate log shows a single end-of-day application in the window',
    'fact.error_materiality':
        'material: restatement required under PSA 110',
    'fact.notification':
        'The bank notified the Prudential Standards Authority of a material error in the quarterly capital return within the PSA 110 notification window',
    'fact.restatement_reason':
        'Risk-weighted assets for the SME Secured Lending book were understated in the filed return: a stale collateral-valuation mapping from the 2023 migration left revaluations lapsed, so collateral was treated as fully secured when it was not',
    'fact.root_cause_classification':
        'control_failure: the revaluation schedule has no registered owner and the quarterly capital path has no reconciliation control',
    'fact.remediation':
        'One ticket assigns revaluation-schedule ownership with a mandatory second-line reviewer; one automates revaluation-lapse detection on the quarterly path',
    'fact.remediation_addresses':
        'The ownership ticket addresses the control failure; the detection ticket addresses only the detection gap',
}


@dataclass(frozen=True)
class ReturnEpisode:
    """The events and facts of one challenged capital-return cycle."""

    events: tuple[EnterpriseEvent, ...]
    facts: tuple[CanonicalFact, ...]
    period: str
    filed_at: datetime
    restated_at: datetime
    keys: dict[str, str] = field(default_factory=dict)
    """Named handles for the facts and events documents and evaluations cite."""


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    roles: dict[str, str],
    position: CapitalPosition,
    liquidity: LiquiditySeries,
    book_names: dict[str, str],
    affected_unit_id: str,
    lore_by_target: dict[str, list[str]],
    text: Mapping[str, str] | None = None,
) -> ReturnEpisode:
    """Generate the challenged return for the quarter ending *period*.

    ``affected_unit_id`` is the business unit whose book the error sits in —
    resolved by the caller from the affected book itself, never assumed from a
    unit key. This used to be ``roles["unit_business"]``, which crashed for
    any pack whose units were named for its own business rather than the stock
    archetype's: the same leak class ``operations._affected_unit`` fixes.
    """
    t = episode_text.merged(TEXT, text)
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}

    ends = period_end(period)
    bd = lambda n: business_days_after(ends, n)  # noqa: E731 — read as arithmetic

    sme = roles["cat_sme_secured"]
    core, collateral_sys = roles["sys_core_banking"], roles["sys_collateral"]
    risk_platform, portal = roles["sys_risk_platform"], roles["sys_reg_portal"]
    market = roles["sys_market_data"]
    sync, rwa_engine = roles["svc_collateral_sync"], roles["svc_rwa_engine"]
    lcr_svc, gateway = roles["svc_lcr_daily"], roles["svc_filing_gateway"]

    migration_lore = lore_by_target.get("data_quality_incident/collateral", [])
    ownership_lore = lore_by_target.get("collateral_mapping_change", [])
    filing_lore = lore_by_target.get("finance/file_over_challenge", [])
    charter_lore = lore_by_target.get("regulatory_filing_signoff", [])

    def event(kind: str, at: datetime, summary: str, *, actors: list[str] = [],
              services: list[str] = [], systems: list[str] = [],
              units: list[str] = [], caused_by: list[str] = [],
              lore: list[str] = []) -> EnterpriseEvent:
        made = EnterpriseEvent(id=minter.next("EV"), kind=kind, occurred_at=at,
                               summary=summary, actors=actors, services=services,
                               systems=systems, business_units=units,
                               caused_by=caused_by, lore_ids=lore)
        events.append(made)
        keys[f"event_{kind}"] = made.id
        return made

    # -- the monthly cadence: the March close, uneventful --------------------
    # Reuses retail's close.* kinds verbatim. A quarter's return is prepared
    # from a locked ledger, so the close is the return's precondition, and an
    # uneventful one on purpose: this episode's disruption belongs to the
    # quarterly cadence, and a second crisis would blur whose error the
    # restatement corrects.
    close_start = event(
        "close_started", _at(bd(1), 6, 0),
        t["event.close_started"].format(period=period),
        actors=[roles["controller"]], systems=[core],
    )
    facts.append(_text(minter, "close.due_date", company_id, bd(4).isoformat(),
                       at=close_start.occurred_at, authority=Authority.SYSTEM_OF_RECORD,
                       event=close_start.id, source=core, period=period))
    keys["fact_close_due"] = facts[-1].id

    close_done = event(
        "close_finalised", _at(bd(4), 16, 40),
        t["event.close_finalised"].format(period=period),
        actors=[roles["controller"]], systems=[core], caused_by=[close_start.id],
    )
    facts.append(_text(minter, "close.status", company_id, "final",
                       at=close_done.occurred_at, authority=Authority.SYSTEM_OF_RECORD,
                       event=close_done.id, source=core, period=period))
    keys["fact_close_status"] = facts[-1].id
    facts.append(CanonicalFact(
        id=minter.next("FACT"), kind="close.delay", subject=company_id, period=period,
        value=Quantity(amount=0, unit="business_days"), valid_from=close_done.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, source_system=core, event_id=close_done.id,
    ))
    keys["fact_close_delay"] = facts[-1].id

    # -- the quarterly cadence: preparation and the working paper ------------
    prep = event(
        "capital_return_preparation_started", _at(bd(7), 9, 0),
        t["event.capital_return_preparation_started"].format(period=period),
        actors=[roles["reg_reporting_manager"], roles["reg_analyst"]],
        services=[rwa_engine], systems=[risk_platform], caused_by=[close_done.id],
    )
    facts.append(_text(minter, "capital.return_due_date", company_id, bd(18).isoformat(),
                       at=prep.occurred_at, authority=Authority.SYSTEM_OF_RECORD,
                       event=prep.id, source=portal, period=period))
    keys["fact_return_due"] = facts[-1].id
    # The standard's floor: standing, never superseded, and no period — the
    # minimum does not belong to a quarter.
    facts.append(CanonicalFact(
        id=minter.next("FACT"), kind="capital.minimum_cet1_requirement", subject=company_id,
        value=Quantity(amount=position.minimum_pct, unit=PCT), valid_from=prep.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, source_system=portal, event_id=prep.id,
    ))
    keys["fact_minimum"] = facts[-1].id

    wp = event(
        "working_paper_issued", _at(bd(10), 17, 20),
        t["event.working_paper_issued"],
        actors=[roles["reg_analyst"]], services=[rwa_engine], systems=[risk_platform],
        caused_by=[prep.id],
    )
    facts.append(CanonicalFact(
        id=minter.next("FACT"), kind="capital.cet1_ratio", subject=company_id, period=period,
        value=Quantity(amount=position.ratio_filed_pct, unit=PCT), valid_from=wp.occurred_at,
        authority=Authority.WORKING_DOCUMENT, source_system=risk_platform, event_id=wp.id,
    ))
    keys["fact_wp_ratio"] = facts[-1].id
    facts.append(CanonicalFact(
        id=minter.next("FACT"), kind="capital.rwa_total", subject=company_id, period=period,
        value=Quantity(amount=position.rwa_filed, unit=MONEY), valid_from=wp.occurred_at,
        authority=Authority.WORKING_DOCUMENT, source_system=risk_platform, event_id=wp.id,
    ))
    keys["fact_wp_rwa"] = facts[-1].id
    # The contested treatment, first half. Closed only when the confirmed cause
    # establishes what the collateral actually was — see `impact` below.
    impact_at = _at(bd(25), 12, 0)
    facts.append(_text(minter, "capital.collateral_treatment", sme, "fully_secured",
                       at=wp.occurred_at, authority=Authority.WORKING_DOCUMENT,
                       event=wp.id, source=risk_platform, period=period, until=impact_at))
    keys["fact_treatment_working"] = facts[-1].id

    # -- the second line challenges, on the record ---------------------------
    review = event(
        "second_line_review_started", _at(bd(12), 10, 0),
        t["event.second_line_review_started"],
        actors=[roles["prudential_risk_head"]], caused_by=[wp.id], lore=charter_lore,
    )
    challenge = event(
        "challenge_raised", _at(bd(14), 14, 30),
        t["event.challenge_raised"],
        actors=[roles["prudential_risk_head"]], systems=[collateral_sys],
        units=[affected_unit_id], caused_by=[review.id], lore=filing_lore,
    )
    facts.append(_text(minter, "review.challenge", sme,
                       t["fact.challenge"],
                       at=challenge.occurred_at, authority=Authority.APPROVED_REPORT,
                       event=challenge.id, source=collateral_sys, period=period))
    keys["fact_challenge"] = facts[-1].id
    # The treatment's second half: same book, same period, DIFFERENT authority,
    # and neither supersedes the other. The contest is live — that coexistence
    # is legal is exactly what the banking check group's coexistence rule says.
    facts.append(_text(minter, "capital.collateral_treatment", sme, "unverified",
                       at=challenge.occurred_at, authority=Authority.APPROVED_REPORT,
                       event=challenge.id, source=collateral_sys, period=period))
    keys["fact_treatment_challenged"] = facts[-1].id
    ruling_at = _at(bd(30), 11, 0)
    facts.append(_text(minter, "review.challenge_status", sme, "open",
                       at=challenge.occurred_at, authority=Authority.APPROVED_REPORT,
                       event=challenge.id, period=period, until=ruling_at))
    keys["fact_challenge_open"] = facts[-1].id

    # -- the norm files over the challenge -----------------------------------
    approved = event(
        "return_approved", _at(bd(16), 11, 0),
        t["event.return_approved"],
        actors=[roles["cfo"], roles["reg_reporting_manager"]],
        caused_by=[challenge.id], lore=filing_lore,
    )
    facts.append(_text(minter, "capital.return_approval", company_id,
                       "The CFO approved the return for lodgement while the second-line "
                       "challenge on the SME Secured collateral treatment remained open",
                       at=approved.occurred_at, authority=Authority.CONFIRMED,
                       event=approved.id, period=period, lore=filing_lore))
    keys["fact_approval"] = facts[-1].id

    filed = event(
        "capital_return_filed", _at(bd(18), 10, 15),
        t["event.capital_return_filed"].format(period=period),
        actors=[roles["reg_reporting_manager"]], services=[gateway], systems=[portal],
        caused_by=[approved.id], lore=filing_lore,
    )
    restated_at = _at(bd(29), 10, 15)

    def money(kind: str, subject: str, amount: float, *, at: datetime, event_id: str,
              unit: str = MONEY, authority: Authority = Authority.SYSTEM_OF_RECORD,
              source: str | None = None, until: datetime | None = None,
              supersedes: str | None = None) -> CanonicalFact:
        fact = CanonicalFact(
            id=minter.next("FACT"), kind=kind, subject=subject, period=period,
            value=Quantity(amount=amount, unit=unit), valid_from=at, valid_to=until,
            authority=authority, source_system=source or portal, event_id=event_id,
            supersedes=supersedes,
        )
        facts.append(fact)
        return fact

    at_filing = filed.occurred_at
    keys["fact_cet1_capital"] = money(
        "capital.cet1_capital", company_id, position.cet1_capital,
        at=at_filing, event_id=filed.id).id
    filed_rwa = money("capital.rwa_total", company_id, position.rwa_filed,
                      at=at_filing, event_id=filed.id, until=restated_at)
    keys["fact_rwa_filed"] = filed_rwa.id
    filed_ratio = money("capital.cet1_ratio", company_id, position.ratio_filed_pct,
                        at=at_filing, event_id=filed.id, unit=PCT, until=restated_at)
    keys["fact_ratio_filed"] = filed_ratio.id
    # The permanent record of what the filing reported. NEVER superseded, no
    # valid_to, ever: this fact is how "what did the bank report as of a
    # cutoff" stays answerable after the corrected figure supersedes the filed
    # one. Tests pin the never-closed property.
    keys["fact_ratio_as_filed"] = money(
        "capital.cet1_ratio_as_filed", company_id, position.ratio_filed_pct,
        at=at_filing, event_id=filed.id, unit=PCT).id
    facts.append(_text(minter, "capital.return_filed_at", company_id,
                       at_filing.isoformat(), at=at_filing,
                       authority=Authority.SYSTEM_OF_RECORD, event=filed.id,
                       source=portal, period=period))
    keys["fact_filed_at"] = facts[-1].id
    status_filed = _text(minter, "capital.return_status", company_id, "filed",
                         at=at_filing, authority=Authority.SYSTEM_OF_RECORD,
                         event=filed.id, source=portal, period=period, until=restated_at)
    facts.append(status_filed)
    keys["fact_status_filed"] = status_filed.id

    sme_filed: CanonicalFact | None = None
    for book_id, amount in position.by_book_filed.items():
        book_fact = money("capital.rwa_by_book", book_id, amount, at=at_filing,
                          event_id=filed.id, source=risk_platform,
                          until=restated_at if book_id == sme else None)
        keys[f"fact_book_{book_id}"] = book_fact.id
        if book_id == sme:
            sme_filed = book_fact
    assert sme_filed is not None

    # -- the daily cadence, which does not pause ------------------------------
    first_day = liquidity.observations[0][0]
    witness = event(
        "liquidity_report_submitted", _at(first_day, 8, 30),
        t["event.liquidity_report_submitted"],
        actors=[roles["liquidity_analyst"]], services=[lcr_svc], systems=[risk_platform],
        caused_by=[filed.id],
    )
    previous_lcr: CanonicalFact | None = None
    for day, value in liquidity.observations:
        at = _at(day, 8, 30)
        next_at: datetime | None = None
        index = [d for d, _ in liquidity.observations].index(day)
        if index + 1 < len(liquidity.observations):
            next_at = _at(liquidity.observations[index + 1][0], 8, 30)
        lcr = CanonicalFact(
            id=minter.next("FACT"), kind="liquidity.lcr", subject=company_id,
            value=Quantity(amount=value, unit=PCT), valid_from=at, valid_to=next_at,
            authority=Authority.SYSTEM_OF_RECORD, source_system=risk_platform,
            event_id=witness.id if day == first_day else None,
            supersedes=previous_lcr.id if previous_lcr else None,
        )
        facts.append(lcr)
        keys[f"fact_lcr_{day.isoformat()}"] = lcr.id
        previous_lcr = lcr
    keys["fact_lcr_first"] = keys[f"fact_lcr_{first_day.isoformat()}"]

    mid_day = liquidity.observations[3][0]
    event(
        "liquidity_cadence_continued", _at(mid_day, 8, 30),
        t["event.liquidity_cadence_continued"],
        actors=[roles["liquidity_analyst"]], services=[lcr_svc], systems=[risk_platform],
        caused_by=[witness.id],
    )

    # -- detection: the daily path catches the quarterly path's error --------
    break_day = liquidity.observations[-2][0]
    chain = rng.derive(f"chain/{break_day.isoformat()}")
    detected = _at(break_day, 8, chain.integer(12, 28))
    opened_at = detected + timedelta(minutes=chain.integer(14, 26))
    hypothesised = detected + timedelta(minutes=chain.integer(75, 105))
    ruled_out = hypothesised + timedelta(minutes=chain.integer(150, 210))
    confirmed = ruled_out + timedelta(minutes=chain.integer(90, 145))
    incident_ref = f"INC{chain.integer(10_000, 99_999):07d}"
    affected = chain.integer(800, 4_200)

    breach = event(
        "reconciliation_break_detected", detected,
        t["event.reconciliation_break_detected"],
        actors=[roles["liquidity_analyst"]], services=[lcr_svc, sync],
        systems=[collateral_sys, risk_platform], caused_by=[witness.id],
        lore=migration_lore,
    )
    facts.append(_text(minter, "liquidity.reconciliation_break", lcr_svc,
                       t["fact.reconciliation_break"],
                       at=detected, authority=Authority.SYSTEM_OF_RECORD,
                       event=breach.id, source=risk_platform))
    keys["fact_break"] = facts[-1].id

    opened = event(
        "incident_opened", opened_at,
        t["event.incident_opened"].format(incident_ref=incident_ref),
        actors=[roles["svc_desk"], roles["svc_incident"]], services=[sync],
        systems=[collateral_sys], caused_by=[breach.id],
    )
    facts.append(_text(minter, "ops.incident_opened", sync,
                       t["fact.incident_opened"].format(incident_ref=incident_ref),
                       at=opened_at, authority=Authority.SYSTEM_OF_RECORD,
                       event=opened.id, source=risk_platform, period=period))
    keys["fact_incident_ref"] = facts[-1].id

    guessed = event(
        "hypothesis_recorded", hypothesised,
        t["event.hypothesis_recorded"],
        actors=[roles["svc_desk"]], services=[sync], systems=[market],
        caused_by=[opened.id],
    )
    hypothesis = _text(minter, "ops.cause", sync,
                       t["fact.initial_hypothesis"],
                       at=hypothesised, authority=Authority.INITIAL_HYPOTHESIS,
                       event=guessed.id, until=ruled_out)
    facts.append(hypothesis)
    keys["fact_hypothesis"] = hypothesis.id

    dismissed = event(
        "hypothesis_superseded", ruled_out,
        t["event.hypothesis_superseded"],
        actors=[roles["platform_senior"]], services=[sync], systems=[market],
        caused_by=[guessed.id],
    )
    facts.append(_text(minter, "ops.cause_ruled_out", sync,
                       t["fact.cause_ruled_out"],
                       at=ruled_out, authority=Authority.CONFIRMED,
                       event=dismissed.id, source=market))
    keys["fact_ruled_out"] = facts[-1].id

    found = event(
        "root_cause_confirmed", confirmed,
        t["event.root_cause_confirmed"].format(affected=affected),
        actors=[roles["platform_senior"], roles["credit_risk_lead"]], services=[sync],
        systems=[collateral_sys], units=[affected_unit_id],
        caused_by=[dismissed.id], lore=migration_lore,
    )
    cause = _text(minter, "ops.cause", sync,
                  t["fact.confirmed_cause"],
                  at=confirmed, authority=Authority.CONFIRMED, event=found.id,
                  source=collateral_sys, supersedes=hypothesis.id, lore=migration_lore)
    facts.append(cause)
    keys["fact_cause"] = cause.id
    facts.append(CanonicalFact(
        id=minter.next("FACT"), kind="ops.affected_records", subject=sync,
        value=Quantity(amount=affected, unit="loan_facilities"), valid_from=confirmed,
        authority=Authority.CONFIRMED, source_system=collateral_sys, event_id=found.id,
        lore_ids=migration_lore,
    ))
    keys["fact_affected"] = facts[-1].id

    # -- the capital impact, and the treatment resolved ----------------------
    impact = event(
        "capital_impact_assessed", impact_at,
        t["event.capital_impact_assessed"],
        actors=[roles["credit_risk_lead"], roles["reg_reporting_manager"]],
        services=[rwa_engine], systems=[risk_platform], caused_by=[found.id],
    )
    keys["fact_understatement"] = money(
        "capital.rwa_understatement", company_id, position.understatement,
        at=impact_at, event_id=impact.id, authority=Authority.CONFIRMED,
        source=risk_platform).id
    keys["fact_delta"] = money(
        "capital.cet1_delta", company_id, position.delta_bps, at=impact_at,
        event_id=impact.id, unit=BPS, authority=Authority.CONFIRMED,
        source=risk_platform).id
    facts.append(_text(minter, "capital.error_materiality", company_id,
                       t["fact.error_materiality"],
                       at=impact_at, authority=Authority.CONFIRMED, event=impact.id,
                       period=period))
    keys["fact_materiality"] = facts[-1].id
    facts.append(_text(minter, "capital.affected_book", company_id,
                       f"{book_names.get(sme, 'SME Secured Lending')} ({sme})",
                       at=impact_at, authority=Authority.CONFIRMED, event=impact.id,
                       period=period))
    keys["fact_affected_book"] = facts[-1].id
    # The treatment resolved: the working paper's "fully_secured" is closed by a
    # CONFIRMED statement of what the collateral actually was. The second
    # line's "unverified" stays open beside it — it was never wrong.
    facts.append(_text(minter, "capital.collateral_treatment", sme,
                       "revaluations lapsed; not fully secured",
                       at=impact_at, authority=Authority.CONFIRMED, event=impact.id,
                       source=collateral_sys, period=period,
                       supersedes=keys["fact_treatment_working"]))
    keys["fact_treatment_confirmed"] = facts[-1].id

    notified = event(
        "regulator_notified", _at(bd(26), 9, 30),
        t["event.regulator_notified"],
        actors=[roles["cfo"]], systems=[portal], caused_by=[impact.id],
    )
    facts.append(_text(minter, "regulatory.notification", company_id,
                       t["fact.notification"],
                       at=notified.occurred_at, authority=Authority.SYSTEM_OF_RECORD,
                       event=notified.id, source=portal, period=period))
    keys["fact_notification"] = facts[-1].id

    # -- the restatement ------------------------------------------------------
    prepared = event(
        "restatement_prepared", _at(bd(27), 10, 0),
        t["event.restatement_prepared"],
        actors=[roles["reg_reporting_manager"], roles["reg_analyst"]],
        services=[rwa_engine], caused_by=[notified.id],
    )
    event(
        "working_paper_revised", _at(bd(27), 15, 0),
        t["event.working_paper_revised"],
        actors=[roles["reg_analyst"]], caused_by=[prepared.id],
    )
    reviewed = event(
        "restatement_reviewed", _at(bd(28), 11, 30),
        t["event.restatement_reviewed"],
        actors=[roles["prudential_risk_head"]], caused_by=[prepared.id],
    )
    signed = event(
        "restatement_approved", _at(bd(28), 16, 0),
        t["event.restatement_approved"],
        actors=[roles["cfo"], roles["cro"]], caused_by=[reviewed.id],
    )
    restated = event(
        "return_restated", restated_at,
        t["event.return_restated"],
        actors=[roles["reg_reporting_manager"]], services=[gateway], systems=[portal],
        caused_by=[signed.id],
    )
    keys["fact_rwa_corrected"] = money(
        "capital.rwa_total", company_id, position.rwa_corrected,
        at=restated_at, event_id=restated.id, supersedes=filed_rwa.id).id
    keys["fact_ratio_corrected"] = money(
        "capital.cet1_ratio", company_id, position.ratio_corrected_pct,
        at=restated_at, event_id=restated.id, unit=PCT, supersedes=filed_ratio.id).id
    keys["fact_book_corrected"] = money(
        "capital.rwa_by_book", sme, position.corrected_book_rwa,
        at=restated_at, event_id=restated.id, source=risk_platform,
        supersedes=sme_filed.id).id
    facts.append(_text(minter, "capital.return_status", company_id, "restated",
                       at=restated_at, authority=Authority.SYSTEM_OF_RECORD,
                       event=restated.id, source=portal, period=period,
                       supersedes=status_filed.id))
    keys["fact_status_restated"] = facts[-1].id
    facts.append(_text(minter, "capital.restatement_reason", company_id,
                       t["fact.restatement_reason"],
                       at=restated_at, authority=Authority.SYSTEM_OF_RECORD,
                       event=restated.id, source=portal, period=period,
                       lore=migration_lore))
    keys["fact_restatement_reason"] = facts[-1].id

    # -- the third line rules -------------------------------------------------
    ruling = event(
        "control_failure_identified", ruling_at,
        t["event.control_failure_identified"],
        actors=[roles["audit"], roles["audit_manager"]], services=[rwa_engine, sync],
        systems=[collateral_sys], caused_by=[found.id], lore=ownership_lore,
    )
    facts.append(_text(minter, "review.challenge_status", sme, "upheld",
                       at=ruling_at, authority=Authority.APPROVED_REPORT,
                       event=ruling.id, period=period,
                       supersedes=keys["fact_challenge_open"]))
    keys["fact_challenge_upheld"] = facts[-1].id
    facts.append(_text(minter, "ops.root_cause_classification", rwa_engine,
                       t["fact.root_cause_classification"],
                       at=ruling_at, authority=Authority.CONFIRMED, event=ruling.id,
                       lore=ownership_lore))
    keys["fact_classification"] = facts[-1].id
    facts.append(_text(minter, "ops.collateral_mapping_owner", collateral_sys,
                       "unassigned", at=ruling_at, authority=Authority.CONFIRMED,
                       event=ruling.id, source=collateral_sys, lore=ownership_lore))
    keys["fact_owner"] = facts[-1].id

    remediation = event(
        "remediation_created", _at(bd(30), 14, 0),
        t["event.remediation_created"],
        actors=[roles["platform_lead"]], services=[sync, rwa_engine],
        systems=[collateral_sys], caused_by=[ruling.id], lore=ownership_lore,
    )
    facts.append(_text(minter, "ops.remediation", sync,
                       t["fact.remediation"],
                       at=remediation.occurred_at, authority=Authority.SYSTEM_OF_RECORD,
                       event=remediation.id, source=collateral_sys, lore=ownership_lore))
    keys["fact_remediation"] = facts[-1].id
    facts.append(_text(minter, "ops.remediation_addresses", sync,
                       t["fact.remediation_addresses"],
                       at=remediation.occurred_at, authority=Authority.CONFIRMED,
                       event=remediation.id, lore=ownership_lore))
    keys["fact_remediation_scope"] = facts[-1].id
    keys["incident_reference"] = incident_ref

    return ReturnEpisode(
        events=tuple(events), facts=tuple(facts), period=period,
        filed_at=at_filing, restated_at=restated_at, keys=keys,
    )
