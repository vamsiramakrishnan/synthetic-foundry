"""The operational generator.

Produces the close sequence and, when lore makes it likely, the incident chain:
detection, triage, a wrong first answer, its supersession, the confirmed cause, a
workaround, and the control failure underneath.

The wrong first answer is generated deliberately. A corpus in which every document
agrees is easy to build and useless for testing whether a system can tell *what
was believed at the time* from *what turned out to be true*. So the hypothesis is
a real fact with real validity that really expires, and it is superseded rather
than overwritten.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from .. import locales
from ..ids import Minter
from ..models import Authority, CanonicalFact, EnterpriseEvent, FiscalPeriod, Quantity, fiscal_period
from ..parameters import DEFAULT, Parameters
from ..rng import Rng
from . import episode_text

#: The engine default currency unit — the same value `finance.py`'s `MONEY`
#: holds, and the one every retail archetype in this repository resolves to.
#: `generate`'s `money_unit` parameter overrides it for a pack with a
#: different currency; this module only mints one bare-money fact
#: (`financial.incident_pl_impact`, always zero-valued, below), so it is a
#: parameter rather than a whole `_Ledger`-style plumbing exercise.
MONEY = "AUD_thousands"

#: The close engine's surface text: every sentence an event carries and every
#: prose fact the episode states, keyed so a pack can re-voice the narration
#: without touching the causality underneath (see `generators/episode_text`).
#: The defaults are the strings this engine always used, verbatim — stock
#: corpora are byte-identical whether or not this table exists. Machine values
#: (statuses, dates, "unassigned") are deliberately not here.
TEXT: dict[str, str] = {
    "event.close_started":
        "{period} month-end close commenced; the orchestrator began the overnight sequence.",
    "event.close_finalised_on_time":
        "{period} close finalised and the ledger locked on the committed date.",
    "event.close_finalised_delayed":
        "{period} close finalised and the ledger locked, one business day later than the calendar commitment.",
    "event.pipeline_failed":
        "The inventory valuation pipeline failed. On-hand stock could not be valued for the period.",
    "event.incident_opened":
        "Service operations opened incident {incident_ref} at priority P2 against inventory-valuation.",
    "event.hypothesis_recorded":
        "Initial triage attributed the failure to an overnight ERP outage.",
    "event.hypothesis_superseded":
        "The ERP outage hypothesis was ruled out; ERP logs showed no interruption in the window.",
    "event.root_cause_confirmed":
        "Root cause confirmed as a stale legacy-to-new product hierarchy mapping, leaving "
        "{affected:,} SKUs unmapped and unvaluable.",
    "event.workaround_applied":
        "A manual hierarchy mapping override was applied so valuation could complete for the period.",
    "event.valuation_available":
        "Inventory valuation completed for {period} following the manual override.",
    "event.close_delayed":
        "Final close was pushed by one business day and escalated to the Group CFO.",
    "event.control_failure_identified":
        "Review established the underlying failure as a control failure: the hierarchy mapping "
        "table has no registered owner and no required reviewer.",
    "event.remediation_created":
        "Two remediation tickets raised: automate the mapping validation, and assign ownership "
        "of the mapping table with a mandatory reviewer.",
    "fact.incident_reference":
        "{incident_ref} opened at priority P2 against inventory-valuation",
    "fact.hypothesis": "Overnight ERP outage",
    "fact.hypothesis_ruled_out": "ERP logs show no interruption during the valuation window",
    "fact.cause":
        "Stale legacy-to-new product hierarchy mapping in the merchandising master",
    "fact.recurrence_with_period":
        "A comparable valuation failure in {prior_period} was traced to the same mapping table,"
        " and the response then restored service without assigning ownership",
    "fact.recurrence_first":
        "A comparable valuation failure was traced to the same mapping table",
    "fact.workaround":
        "Manual hierarchy mapping override applied to complete valuation for the period",
    "fact.valuation_status": "Inventory valuation completed",
    "fact.classification":
        "control_failure: the mapping table has no registered owner and no required reviewer",
    "fact.remediation":
        "One ticket automates mapping validation; one assigns mapping table ownership "
        "with a mandatory reviewer",
    "fact.remediation_scope":
        "The ownership ticket addresses the control failure; the validation ticket addresses "
        "only the detection gap",
}


#: Alternative incident storylines: the same eight-step causal chain — detect,
#: triage, be wrong, be corrected, work around, escalate — wearing a different
#: failure. Each entry is a ``TEXT`` overlay (the same seam a pack re-voices
#: through), so a storyline can never touch causality, fact ids, or machine
#: values; it can only change what the failure *was*. The library exists
#: because a 24-period flagship measured 24 byte-similar incidents — one
#: distinct confirmed cause across 48 ``ops.cause`` facts — and a company
#: whose only operational failure mode is one stale mapping table, monthly,
#: with the same remediation raised each time and never done, is a diversity
#: hole and a coherence hole at once. Every storyline still blocks inventory
#: valuation (that is the causal layer: the close is delayed because stock
#: cannot be valued) and still lands on a control failure with two tickets,
#: because the downstream documents — RCA, Jira summary, knowledge article —
#: are planned against those keys.
#:
#: ``hierarchy_mapping`` is the storyline this engine always told, as an empty
#: overlay: the default build is byte-identical to every corpus that predates
#: the library.
STORYLINES: dict[str, dict[str, str]] = {
    "hierarchy_mapping": {},
    "fx_rate_stale": {
        "event.pipeline_failed":
            "The inventory valuation pipeline failed. Landed costs could not be computed, so "
            "on-hand stock could not be valued for the period.",
        "event.hypothesis_recorded":
            "Initial triage attributed the failure to an overnight outage of the market-rates service.",
        "event.hypothesis_superseded":
            "The rates-service outage hypothesis was ruled out; the service's logs showed "
            "uninterrupted publication through the window.",
        "event.root_cause_confirmed":
            "Root cause confirmed as a stale foreign-exchange rate table in the landed-cost "
            "engine, leaving {affected:,} imported SKUs valued at a rate the period never traded at.",
        "event.workaround_applied":
            "The rate table was refreshed by hand and the affected receipts revalued so the "
            "period could close.",
        "event.control_failure_identified":
            "Review established the underlying failure as a control failure: the rate-table "
            "refresh has no registered owner and no required reviewer.",
        "event.remediation_created":
            "Two remediation tickets raised: automate rate-staleness validation, and assign "
            "ownership of the refresh with a mandatory reviewer.",
        "fact.hypothesis": "Overnight market-rates service outage",
        "fact.hypothesis_ruled_out":
            "Rates-service logs show uninterrupted publication during the valuation window",
        "fact.cause": "Stale foreign-exchange rate table in the landed-cost engine",
        "fact.recurrence_with_period":
            "A comparable valuation failure in {prior_period} was traced to the same rate table,"
            " and the response then refreshed the rates without assigning ownership",
        "fact.recurrence_first": "A comparable valuation failure was traced to the same rate table",
        "fact.workaround":
            "Manual rate refresh and revaluation applied to complete valuation for the period",
        "fact.classification":
            "control_failure: the rate-table refresh has no registered owner and no required reviewer",
        "fact.remediation":
            "One ticket automates rate-staleness validation; one assigns refresh ownership "
            "with a mandatory reviewer",
        "fact.remediation_scope":
            "The ownership ticket addresses the control failure; the staleness check addresses "
            "only the detection gap",
    },
    "duplicate_grn": {
        "event.pipeline_failed":
            "The inventory valuation pipeline failed its reconciliation gate. Receipts exceeded "
            "purchase orders, so on-hand stock could not be valued for the period.",
        "event.hypothesis_recorded":
            "Initial triage attributed the failure to a warehouse network outage double-sending receipts.",
        "event.hypothesis_superseded":
            "The network outage hypothesis was ruled out; transmission logs showed a single, "
            "clean delivery of each receipt file.",
        "event.root_cause_confirmed":
            "Root cause confirmed as duplicate goods-receipt postings from a retried batch job "
            "with no idempotency guard, inflating {affected:,} SKUs' on-hand quantities.",
        "event.workaround_applied":
            "The duplicate postings were reversed by journal and the batch rerun under "
            "supervision so valuation could complete for the period.",
        "event.control_failure_identified":
            "Review established the underlying failure as a control failure: the receipt batch "
            "retries without an idempotency key, and manual reposts have no required reviewer.",
        "event.remediation_created":
            "Two remediation tickets raised: add an idempotency key to receipt posting, and "
            "put a mandatory reviewer on manual reposts.",
        "fact.hypothesis": "Warehouse network outage double-sending receipt files",
        "fact.hypothesis_ruled_out":
            "Transmission logs show one clean delivery per receipt file during the window",
        "fact.cause":
            "Duplicate goods-receipt postings from a retried batch job with no idempotency guard",
        "fact.recurrence_with_period":
            "A comparable valuation failure in {prior_period} was traced to the same retry path,"
            " and the response then reversed the duplicates without guarding the retry",
        "fact.recurrence_first": "A comparable valuation failure was traced to the same retry path",
        "fact.workaround":
            "Duplicate receipts reversed by journal and the batch rerun to complete valuation "
            "for the period",
        "fact.classification":
            "control_failure: receipt posting retries carry no idempotency key and manual "
            "reposts have no required reviewer",
        "fact.remediation":
            "One ticket adds an idempotency key to receipt posting; one puts a mandatory "
            "reviewer on manual reposts",
        "fact.remediation_scope":
            "The idempotency ticket addresses the control failure; the reviewer ticket addresses "
            "only the manual path",
    },
    "snapshot_late": {
        "event.pipeline_failed":
            "The inventory valuation pipeline failed its completeness check. The stock snapshot "
            "closed early, so on-hand stock could not be valued for the period.",
        "event.hypothesis_recorded":
            "Initial triage attributed the failure to an overnight ERP outage delaying putaway postings.",
        "event.hypothesis_superseded":
            "The ERP outage hypothesis was ruled out; ERP logs showed postings flowing "
            "normally through the window.",
        "event.root_cause_confirmed":
            "Root cause confirmed as the warehouse stock snapshot cutting over before final "
            "putaways posted, leaving {affected:,} SKUs counted short of what was on hand.",
        "event.workaround_applied":
            "The snapshot was re-taken after putaway confirmation so valuation could complete "
            "for the period.",
        "event.control_failure_identified":
            "Review established the underlying failure as a control failure: the snapshot "
            "cutover time is edited by hand with no registered owner and no required reviewer.",
        "event.remediation_created":
            "Two remediation tickets raised: derive the cutover from putaway confirmation, and "
            "assign ownership of the snapshot schedule with a mandatory reviewer.",
        "fact.hypothesis": "Overnight ERP outage delaying putaway postings",
        "fact.hypothesis_ruled_out": "ERP logs show postings flowing normally during the window",
        "fact.cause":
            "Warehouse stock snapshot cut over before final putaways posted",
        "fact.recurrence_with_period":
            "A comparable valuation failure in {prior_period} was traced to the same snapshot"
            " schedule, and the response then re-took the snapshot without assigning ownership",
        "fact.recurrence_first":
            "A comparable valuation failure was traced to the same snapshot schedule",
        "fact.workaround":
            "Snapshot re-taken after putaway confirmation to complete valuation for the period",
        "fact.classification":
            "control_failure: the snapshot cutover time is hand-edited with no registered owner "
            "and no required reviewer",
        "fact.remediation":
            "One ticket derives the cutover from putaway confirmation; one assigns snapshot "
            "schedule ownership with a mandatory reviewer",
        "fact.remediation_scope":
            "The derivation ticket addresses the control failure; the ownership ticket addresses "
            "only the accountability gap",
    },
    "credential_expired": {
        "event.pipeline_failed":
            "The inventory valuation pipeline failed at authentication. The costing engine could "
            "not read the merchandising master, so on-hand stock could not be valued for the period.",
        "event.hypothesis_recorded":
            "Initial triage attributed the failure to the previous evening's platform release.",
        "event.hypothesis_superseded":
            "The release hypothesis was ruled out; the deployment log showed no release touching "
            "the costing path in the window.",
        "event.root_cause_confirmed":
            "Root cause confirmed as an expired service credential between the costing engine and "
            "the merchandising master, leaving {affected:,} SKUs unreadable and unvaluable.",
        "event.workaround_applied":
            "An emergency credential rotation was applied so valuation could complete for the period.",
        "event.control_failure_identified":
            "Review established the underlying failure as a control failure: service credential "
            "expiry is untracked, with no registered owner and no required reviewer for rotation.",
        "event.remediation_created":
            "Two remediation tickets raised: monitor credential expiry ahead of the deadline, and "
            "assign rotation ownership with a mandatory reviewer.",
        "fact.hypothesis": "Previous evening's platform release broke the costing path",
        "fact.hypothesis_ruled_out":
            "Deployment logs show no release touching the costing path during the window",
        "fact.cause":
            "Expired service credential between the costing engine and the merchandising master",
        "fact.recurrence_with_period":
            "A comparable valuation failure in {prior_period} was traced to the same credential,"
            " and the response then rotated it without assigning ownership",
        "fact.recurrence_first": "A comparable valuation failure was traced to the same credential",
        "fact.workaround":
            "Emergency credential rotation applied to complete valuation for the period",
        "fact.classification":
            "control_failure: service credential expiry is untracked, with no registered owner "
            "and no required reviewer for rotation",
        "fact.remediation":
            "One ticket monitors credential expiry ahead of the deadline; one assigns rotation "
            "ownership with a mandatory reviewer",
        "fact.remediation_scope":
            "The monitoring ticket addresses the detection gap; the ownership ticket addresses "
            "the control failure",
    },
    "uom_overwrite": {
        "event.pipeline_failed":
            "The inventory valuation pipeline failed its sanity bounds. Unit conversions produced "
            "impossible quantities, so on-hand stock could not be valued for the period.",
        "event.hypothesis_recorded":
            "Initial triage attributed the failure to storage-layer corruption in the data platform.",
        "event.hypothesis_superseded":
            "The corruption hypothesis was ruled out; storage integrity checks came back clean "
            "across the window.",
        "event.root_cause_confirmed":
            "Root cause confirmed as unit-of-measure conversion factors overwritten by a supplier "
            "catalogue import, mis-stating quantities on {affected:,} SKUs.",
        "event.workaround_applied":
            "The conversion table was restored from the prior day's backup so valuation could "
            "complete for the period.",
        "event.control_failure_identified":
            "Review established the underlying failure as a control failure: the catalogue import "
            "writes straight to the production conversion table, with no registered owner and no "
            "required reviewer.",
        "event.remediation_created":
            "Two remediation tickets raised: stage catalogue imports behind a validation gate, and "
            "assign conversion-table ownership with a mandatory reviewer.",
        "fact.hypothesis": "Storage-layer corruption in the data platform",
        "fact.hypothesis_ruled_out":
            "Storage integrity checks report clean across the valuation window",
        "fact.cause":
            "Unit-of-measure conversion factors overwritten by a supplier catalogue import",
        "fact.recurrence_with_period":
            "A comparable valuation failure in {prior_period} was traced to the same import path,"
            " and the response then restored the table without staging the import",
        "fact.recurrence_first": "A comparable valuation failure was traced to the same import path",
        "fact.workaround":
            "Conversion table restored from the prior day's backup to complete valuation for "
            "the period",
        "fact.classification":
            "control_failure: the catalogue import writes straight to the production conversion "
            "table with no registered owner and no required reviewer",
        "fact.remediation":
            "One ticket stages catalogue imports behind a validation gate; one assigns "
            "conversion-table ownership with a mandatory reviewer",
        "fact.remediation_scope":
            "The staging ticket addresses the control failure; the ownership ticket addresses "
            "only the accountability gap",
    },
}


#: The same storylines, on the *benchmark's* surface (`evaluation.EVAL_TEXT`).
#: Seven of the engine's answer templates state the classic failure in words —
#: "the same mapping table", "the product hierarchy mapping table" — and under
#: any other storyline those answers would contradict the corpus's own facts:
#: a benchmark asserting a mapping table failed in a month whose confirmed
#: cause was an expired credential grades retrievers against a lie. Kept in
#: this module beside `STORYLINES`, not in `evaluation`, because a storyline
#: is one authored thing with two surfaces, and splitting it across modules is
#: how the two surfaces drift apart.
EVAL_STORYLINES: dict[str, dict[str, str]] = {
    "hierarchy_mapping": {},
    "fx_rate_stale": {
        "a.incident.undetected":
            "The rate-table refresh has no registered owner and no required reviewer, so no"
            " control would have caught it.",
        "a.incident.recurrence":
            "Yes — a comparable valuation failure was traced to the same rate table, and"
            " the response refreshed the rates without assigning ownership.",
        "q.citation.mapping_owner": "Who owns the landed-cost engine's foreign-exchange rate table?",
        "a.across.recurrence":
            "In {prior_period}. It did not — the same rate table failed again in"
            " {period}, and refresh ownership is still unassigned.",
        "q.abstain.next_audit": "When is the next scheduled audit of the rate table?",
        "q.incident.undetected.estate":
            "The rate table sits under {system}, which {reach} service(s) depend on."
            " What allowed the valuation failure to reach production undetected?",
        "q.citation.mapping_owner.estate":
            "Who owns the foreign-exchange rate table held in {system}?",
        "a.cross.remediation_choice":
            "The refresh-ownership assignment. The staleness check addresses detection only.",
    },
    "duplicate_grn": {
        "a.incident.undetected":
            "Receipt posting retries carry no idempotency key and manual reposts have no"
            " required reviewer, so no control would have caught it.",
        "a.incident.recurrence":
            "Yes — a comparable valuation failure was traced to the same retry path, and"
            " the response reversed the duplicates without guarding the retry.",
        "q.citation.mapping_owner": "Who owns the goods-receipt posting batch job?",
        "a.across.recurrence":
            "In {prior_period}. It did not — the same retry path failed again in"
            " {period}, and ownership is still unassigned.",
        "q.abstain.next_audit": "When is the next scheduled audit of the receipt posting job?",
        "q.incident.undetected.estate":
            "The receipt batch runs under {system}, which {reach} service(s) depend on."
            " What allowed the valuation failure to reach production undetected?",
        "q.citation.mapping_owner.estate":
            "Who owns the goods-receipt posting batch job held in {system}?",
        "a.cross.remediation_choice":
            "The idempotency key. The reviewer ticket addresses only the manual repost path.",
    },
    "snapshot_late": {
        "a.incident.undetected":
            "The snapshot cutover time is hand-edited with no registered owner and no"
            " required reviewer, so no control would have caught it.",
        "a.incident.recurrence":
            "Yes — a comparable valuation failure was traced to the same snapshot schedule,"
            " and the response re-took the snapshot without assigning ownership.",
        "q.citation.mapping_owner": "Who owns the warehouse stock snapshot schedule?",
        "a.across.recurrence":
            "In {prior_period}. It did not — the same snapshot schedule failed again in"
            " {period}, and ownership is still unassigned.",
        "q.abstain.next_audit": "When is the next scheduled audit of the snapshot schedule?",
        "q.incident.undetected.estate":
            "The snapshot schedule sits under {system}, which {reach} service(s) depend on."
            " What allowed the valuation failure to reach production undetected?",
        "q.citation.mapping_owner.estate":
            "Who owns the stock snapshot schedule held in {system}?",
        "a.cross.remediation_choice":
            "Deriving the cutover from putaway confirmation. The ownership ticket addresses"
            " only the accountability gap.",
    },
    "credential_expired": {
        "a.incident.undetected":
            "Service credential expiry is untracked, with no registered owner and no required"
            " reviewer for rotation, so no control would have caught it.",
        "a.incident.recurrence":
            "Yes — a comparable valuation failure was traced to the same credential, and"
            " the response rotated it without assigning ownership.",
        "q.citation.mapping_owner": "Who owns rotation of the costing engine's service credential?",
        "a.across.recurrence":
            "In {prior_period}. It did not — the same credential failed again in"
            " {period}, and rotation ownership is still unassigned.",
        "q.abstain.next_audit": "When is the next scheduled audit of the credential register?",
        "q.incident.undetected.estate":
            "The credential authenticates against {system}, which {reach} service(s) depend on."
            " What allowed the valuation failure to reach production undetected?",
        "q.citation.mapping_owner.estate":
            "Who owns rotation of the service credential for {system}?",
        "a.cross.remediation_choice":
            "The rotation-ownership assignment. The expiry monitoring addresses detection only.",
    },
    "uom_overwrite": {
        "a.incident.undetected":
            "The catalogue import writes straight to the production conversion table, with no"
            " registered owner and no required reviewer, so no control would have caught it.",
        "a.incident.recurrence":
            "Yes — a comparable valuation failure was traced to the same import path, and"
            " the response restored the table without staging the import.",
        "q.citation.mapping_owner": "Who owns the unit-of-measure conversion table?",
        "a.across.recurrence":
            "In {prior_period}. It did not — the same import path failed again in"
            " {period}, and ownership is still unassigned.",
        "q.abstain.next_audit": "When is the next scheduled audit of the conversion table?",
        "q.incident.undetected.estate":
            "The conversion table sits under {system}, which {reach} service(s) depend on."
            " What allowed the valuation failure to reach production undetected?",
        "q.citation.mapping_owner.estate":
            "Who owns the unit-of-measure conversion table held in {system}?",
        "a.cross.remediation_choice":
            "The staging gate. The ownership ticket addresses only the accountability gap.",
    },
}


def storyline_eval_text(name: str) -> dict[str, str]:
    """The ``EVAL_TEXT`` overlay for a named incident storyline.

    Same refusal posture as ``storyline_text``, and looked up there first so
    one unknown name produces one error, not two."""
    storyline_text(name)
    return EVAL_STORYLINES[name]


def storyline_text(name: str) -> dict[str, str]:
    """The ``TEXT`` overlay for a named incident storyline.

    Refused rather than defaulted for an unknown name: a recipe that recorded
    a storyline this build does not know cannot be silently rebuilt as the
    classic one — that would be a different world reported as the same world,
    which is the exact lie the recipe exists to prevent.
    """
    try:
        return STORYLINES[name]
    except KeyError:
        raise ValueError(
            f"unknown incident storyline {name!r}; known:"
            f" {', '.join(sorted(STORYLINES))}"
        ) from None


def storyline_rotation(rng: Rng) -> list[str]:
    """Every storyline once — the classic first, the rest in seed order.

    Classic-first is load-bearing, not aesthetic: a single-period build under
    rotation is then byte-identical to a build without it, so turning the knob
    on cannot move a corpus that was too short to benefit from it.
    """
    rest = [name for name in STORYLINES if name != "hierarchy_mapping"]
    return ["hierarchy_mapping", *rng.shuffled(rest)]


class Calendar(Protocol):
    """What the close asks of a working calendar.

    A protocol rather than a class of this module's own, because
    ``locales.Locale`` already answers all three and answering them is most of
    what a locale *is*. Structural typing here means a caller writes
    ``generate(..., calendar=locales.GULF)`` with nothing in between — no
    adapter, no conversion, and no second place where a working week is
    written down and could disagree with the first.

    Only three members, deliberately. A calendar decides which days exist and
    where a period sits in the year; it does not decide when the close is due
    (that is this module's policy, four business days), nor how a date is
    spelled (ISO, see the locales module on why that stays closed).
    """

    fiscal_year_start_month: int

    def is_business_day(self, day: date) -> bool: ...

    def business_days_after(self, start: date, count: int) -> date: ...


#: The calendar every corpus built before this parameter existed was made on,
#: and the one every call that does not name a calendar still gets: Monday to
#: Friday, no public holiday, a July financial year. It is the default *locale*
#: rather than a constant of this module, so that "the engine's calendar" and
#: "Australia's calendar" cannot drift apart — they were the same thing by
#: accident for the whole life of this project and are now the same thing on
#: purpose. `tests/test_locales.py` pins the equality across 2024-2028 × 1-12
#: business days, which is what makes swapping the arithmetic byte-neutral.
CALENDAR: Calendar = locales.DEFAULT


@dataclass(frozen=True)
class CloseEpisode:
    """The events and facts of one month-end close."""

    events: tuple[EnterpriseEvent, ...]
    facts: tuple[CanonicalFact, ...]
    finalised_at: datetime
    close_event_id: str
    had_incident: bool
    delay_days: int
    keys: dict[str, str] = field(default_factory=dict)
    """Named handles for facts and events a planner or evaluation needs to cite."""

    fiscal: FiscalPeriod | None = None
    """Where this close's period sits in the company's financial year.

    Derived, not stored, and carried on the episode rather than minted as a
    fact: a new fact would take an id from the minter and shift every id after
    it, which is exactly the byte-for-byte diff CI regenerates a corpus to
    catch. Optional only so that an episode built by a test that predates the
    field still constructs; ``generate`` always sets it.
    """


def business_days_after(start: date, count: int, calendar: Calendar = CALENDAR) -> date:
    """The date *count* business days after *start*, on *calendar*.

    Kept as a module function with its original two-argument call intact,
    because five other modules import it (``scenarios``, ``banking_scenarios``,
    ``banking``, ``regulatory``, ``reserving``) and each of them is a
    single-word change away from taking a calendar of its own. What it no
    longer is, is the *definition* of a business day: that lived here as
    ``weekday() < 5`` in three places — here, the escalation below, and
    ``liquidity.generate`` — with no holiday table anywhere, so a corpus could
    not have a public holiday even if its pack said which country it was in.
    """
    return calendar.business_days_after(start, count)


def period_end(period: str) -> date:
    """The last calendar day of a ``YYYY-MM`` period.

    Calendar, and staying calendar, at every fiscal year start. A period's
    *identity* is its calendar month — see ``models.FiscalPeriod`` for the
    argument — and the fiscal year decides what that month counts as, not when
    it ends.
    """
    year, month = (int(part) for part in period.split("-"))
    first_next = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return first_next - timedelta(days=1)


def _at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


def _text(minter: Minter, kind: str, subject: str, text: str, *, at: datetime,
          authority: Authority, event: str | None = None, source: str | None = None,
          period: str | None = None, until: datetime | None = None,
          supersedes: str | None = None, lore: list[str] | None = None) -> CanonicalFact:
    return CanonicalFact(
        id=minter.next("FACT"),
        kind=kind,
        subject=subject,
        period=period,
        text_value=text,
        valid_from=at,
        valid_to=until,
        authority=authority,
        source_system=source,
        event_id=event,
        supersedes=supersedes,
        lore_ids=lore or [],
    )


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    roles: dict[str, str],
    lore_by_target: dict[str, list[str]],
    incident_likelihood: float,
    force_incident: bool | None = None,
    prior_incident_periods: tuple[str, ...] = (),
    text: Mapping[str, str] | None = None,
    money_unit: str = MONEY,
    calendar: Calendar = CALENDAR,
    physics: Parameters = DEFAULT,
) -> CloseEpisode:
    """Generate the close, and an incident if lore and the seed conspire.

    ``text`` overrides entries of ``TEXT`` — the surface a pack re-voices,
    over causality it cannot touch. ``money_unit`` is the archetype's own
    currency (``f"{currency}_{currency_unit}"``); it defaults to the stock
    retail unit so a caller that never sets it reproduces every corpus this
    engine has ever built.

    ``calendar`` is which days this company works and when its year opens
    (``worldloom.locales``). It decides *dates*, not policy: the close is due
    four business days after month end everywhere, and "four business days"
    resolves to 4 September in Sydney and 6 September in Dubai for the August
    2026 close — the same commitment, a different Tuesday-through-Friday. The
    default is the Monday-to-Friday, no-holiday calendar every corpus this
    engine has built was made on, so an un-named calendar reproduces them byte
    for byte.
    """
    t = episode_text.merged(TEXT, text)
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}

    ends = period_end(period)
    day1 = calendar.business_days_after(ends, 1)
    due = calendar.business_days_after(ends, 4)

    incident_lore = lore_by_target.get("data_quality_incident/inventory", [])
    calendar_lore = lore_by_target.get("close_cycle_time", [])
    ownership_lore = lore_by_target.get("hierarchy_mapping_change", [])

    start = EnterpriseEvent(
        id=minter.next("EV"), kind="close_started", occurred_at=_at(day1, 6, 0),
        summary=t["event.close_started"].format(period=period),
        actors=[roles["reporting_manager"]], services=[roles["svc_orchestrator"]],
        systems=[roles["sys_erp"]], lore_ids=calendar_lore,
    )
    events.append(start)
    keys["event_close_started"] = start.id

    due_fact = _text(minter, "close.due_date", company_id, due.isoformat(), at=start.occurred_at,
                     authority=Authority.SYSTEM_OF_RECORD, event=start.id, source=roles["sys_erp"],
                     period=period, lore=calendar_lore)
    facts.append(due_fact)
    keys["fact_due_date"] = due_fact.id

    had_incident = force_incident if force_incident is not None else rng.derive("incident").chance(
        min(0.95, incident_likelihood)
    )
    delay_days = 0
    finalised_day = due

    if had_incident:
        chain = _incident_chain(rng.derive("chain"), minter, period=period, day=day1,
                               company_id=company_id, roles=roles,
                               incident_lore=incident_lore, calendar_lore=calendar_lore,
                               ownership_lore=ownership_lore, previous_event=start,
                               prior_incident_periods=prior_incident_periods, t=t,
                               money_unit=money_unit, calendar=calendar, physics=physics)
        events.extend(chain["events"])
        facts.extend(chain["facts"])
        keys.update(chain["keys"])
        delay_days = 1
        finalised_day = calendar.business_days_after(ends, 5)

    finalised_at = _at(finalised_day, 16, 40)
    finalised = EnterpriseEvent(
        id=minter.next("EV"), kind="close_finalised", occurred_at=finalised_at,
        summary=t[
            "event.close_finalised_delayed" if delay_days else "event.close_finalised_on_time"
        ].format(period=period),
        actors=[roles["controller"], roles["reporting_manager"]],
        services=[roles["svc_orchestrator"]], systems=[roles["sys_erp"]],
        caused_by=[keys.get("event_close_delayed", start.id)], lore_ids=calendar_lore,
    )
    events.append(finalised)
    keys["event_close_finalised"] = finalised.id

    if had_incident:
        delayed_fact = next(f for f in facts if f.id == keys["fact_close_delayed"])
        facts[facts.index(delayed_fact)] = delayed_fact.model_copy(update={"valid_to": finalised_at})
        final_status = _text(minter, "close.status", company_id, "final", at=finalised_at,
                             authority=Authority.SYSTEM_OF_RECORD, event=finalised.id,
                             source=roles["sys_erp"], period=period, supersedes=delayed_fact.id)
    else:
        final_status = _text(minter, "close.status", company_id, "final", at=finalised_at,
                             authority=Authority.SYSTEM_OF_RECORD, event=finalised.id,
                             source=roles["sys_erp"], period=period)
    facts.append(final_status)
    keys["fact_close_status_final"] = final_status.id

    delay_fact = CanonicalFact(
        id=minter.next("FACT"), kind="close.delay", subject=company_id, period=period,
        value=Quantity(amount=delay_days, unit="business_days"), valid_from=finalised_at,
        authority=Authority.SYSTEM_OF_RECORD, source_system=roles["sys_erp"], event_id=finalised.id,
        lore_ids=calendar_lore,
    )
    facts.append(delay_fact)
    keys["fact_close_delay"] = delay_fact.id

    return CloseEpisode(
        events=tuple(events), facts=tuple(facts), finalised_at=finalised_at,
        close_event_id=finalised.id, had_incident=had_incident, delay_days=delay_days, keys=keys,
        fiscal=fiscal_period(period, calendar.fiscal_year_start_month),
    )


def _affected_unit(roles: dict[str, str]) -> str:
    """The business unit the mapping failure lands on.

    The general-merchandise unit when the archetype has one — that is where
    range architecture is fought over, the same rule ``organisation`` uses to
    home the merchandising roles — else the first unit the world has. The
    fallback exists because this used to be ``roles["unit_gm"]``, which made
    the whole engine crash for any pack whose units were named honestly for a
    different business: the exact coupling the telco experiment measured, hit
    again by the first insurer pack, fixed rather than worked around.
    """
    if "unit_gm" in roles:
        return roles["unit_gm"]
    return next(roles[key] for key in roles if key.startswith("unit_"))


def _incident_chain(
    rng: Rng, minter: Minter, *, period: str, day: date, company_id: str, roles: dict[str, str],
    incident_lore: list[str], calendar_lore: list[str], ownership_lore: list[str],
    previous_event: EnterpriseEvent, prior_incident_periods: tuple[str, ...] = (),
    t: Mapping[str, str] = TEXT, money_unit: str = MONEY,
    calendar: Calendar = CALENDAR,
    physics: Parameters = DEFAULT,
) -> dict:
    """The eight-step incident: detect, triage, be wrong, be corrected, work around, escalate."""
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}

    detected = _at(day, 8, physics.integer("ops.incident.detected_minute", rng))
    raised = detected + timedelta(minutes=physics.integer("ops.incident.raise_minutes", rng))
    hypothesised = detected + timedelta(minutes=physics.integer("ops.incident.hypothesis_minutes", rng))
    ruled_out = hypothesised + timedelta(minutes=physics.integer("ops.incident.rule_out_minutes", rng))
    confirmed = ruled_out + timedelta(minutes=physics.integer("ops.incident.confirm_minutes", rng))
    worked_around = confirmed + timedelta(minutes=physics.integer("ops.incident.workaround_minutes", rng))
    available = worked_around + timedelta(minutes=physics.integer("ops.incident.recovery_minutes", rng))
    # Was `day + 1 day, or +3 if that lands on a Saturday` — the third and last
    # hand-rolled weekend rule in the engine, and the one that hid its
    # assumption best: `day` is always a business day, so "+1 unless Saturday"
    # is only ever *next business day* spelled out, and it silently could not
    # skip a public holiday or a Friday weekend. Identical on the default
    # calendar; on the Gulf's, a Thursday close escalates on the Sunday, where
    # the literal put the Group CFO's escalation on a Friday the office is shut.
    escalated = _at(calendar.business_days_after(day, 1), 9, 0)
    reviewed = _at(calendar.business_days_after(day, 2), 11, 0)
    remediated = _at(calendar.business_days_after(day, 2), 14, 0)

    affected = physics.integer("ops.incident.affected_records", rng)
    # Left a literal beside the converted draw above: a reference number's
    # format belongs to the ticketing system, not to the world's physics.
    incident_ref = f"INC{rng.integer(10_000, 99_999):07d}"

    def event(kind: str, at: datetime, summary: str, *, actors: list[str], services: list[str] = [],
              systems: list[str] = [], units: list[str] = [], caused_by: list[str] = [],
              lore: list[str] = []) -> EnterpriseEvent:
        made = EnterpriseEvent(id=minter.next("EV"), kind=kind, occurred_at=at, summary=summary,
                               actors=actors, services=services, systems=systems,
                               business_units=units, caused_by=caused_by, lore_ids=lore)
        events.append(made)
        return made

    valuation, hierarchy = roles["svc_valuation"], roles["svc_hierarchy"]
    mdm, platform, erp = roles["sys_mdm"], roles["sys_platform"], roles["sys_erp"]

    failed = event("pipeline_failed", detected,
                   t["event.pipeline_failed"],
                   actors=[], services=[valuation, hierarchy], systems=[platform],
                   caused_by=[previous_event.id], lore=incident_lore)
    opened = event("incident_opened", raised,
                   t["event.incident_opened"].format(incident_ref=incident_ref),
                   actors=[roles["svc_desk"], roles["svc_incident"]], services=[valuation],
                   systems=[platform], caused_by=[failed.id])
    guessed = event("hypothesis_recorded", hypothesised,
                    t["event.hypothesis_recorded"],
                    actors=[roles["svc_desk"]], services=[valuation], systems=[erp, platform],
                    caused_by=[opened.id])
    dismissed = event("hypothesis_superseded", ruled_out,
                      t["event.hypothesis_superseded"],
                      actors=[roles["platform_senior"]], services=[valuation], systems=[erp],
                      caused_by=[guessed.id])
    found = event("root_cause_confirmed", confirmed,
                  t["event.root_cause_confirmed"].format(affected=affected),
                  actors=[roles["platform_senior"], roles["merch_analyst"]], services=[hierarchy],
                  systems=[mdm], units=[_affected_unit(roles)], caused_by=[dismissed.id], lore=incident_lore)
    patched = event("workaround_applied", worked_around,
                    t["event.workaround_applied"],
                    actors=[roles["platform_senior"], roles["merch_analyst"]],
                    services=[valuation, hierarchy], systems=[mdm, platform],
                    caused_by=[found.id], lore=calendar_lore)
    valued = event("valuation_available", available,
                   t["event.valuation_available"].format(period=period),
                   actors=[roles["platform_senior"]], services=[valuation], systems=[platform],
                   caused_by=[patched.id])
    delayed = event("close_delayed", escalated,
                    t["event.close_delayed"],
                    actors=[roles["controller"], roles["cfo"]], services=[roles["svc_orchestrator"]],
                    systems=[erp], caused_by=[valued.id], lore=calendar_lore)
    classified = event("control_failure_identified", reviewed,
                       t["event.control_failure_identified"],
                       actors=[roles["platform_lead"], roles["audit"]], services=[hierarchy],
                       systems=[mdm], units=[_affected_unit(roles)], caused_by=[found.id], lore=ownership_lore)
    remediation = event("remediation_created", remediated,
                        t["event.remediation_created"],
                        actors=[roles["platform_lead"]], services=[hierarchy], systems=[mdm],
                        caused_by=[classified.id], lore=ownership_lore)

    keys.update({
        "event_pipeline_failed": failed.id,
        "event_incident_opened": opened.id,
        "event_hypothesis": guessed.id,
        "event_root_cause": found.id,
        "event_close_delayed": delayed.id,
        "event_control_failure": classified.id,
        "event_remediation": remediation.id,
    })

    status = _text(minter, "ops.feed_status", valuation, "failed", at=detected,
                   authority=Authority.SYSTEM_OF_RECORD, event=failed.id, source=platform)
    # Stamped with its reporting period, because an incident belongs to a close.
    # Without it a later episode cannot find the earlier one, and "has this
    # happened before" stays a rhetorical question.
    reference = _text(minter, "ops.incident_opened", valuation,
                      t["fact.incident_reference"].format(incident_ref=incident_ref),
                      at=raised, authority=Authority.SYSTEM_OF_RECORD, event=opened.id,
                      source=platform, period=period)

    # The wrong answer, with an expiry. It is superseded, never overwritten.
    hypothesis = _text(minter, "ops.cause", valuation, t["fact.hypothesis"], at=hypothesised,
                       authority=Authority.INITIAL_HYPOTHESIS, event=guessed.id, until=ruled_out)
    dismissal = _text(minter, "ops.cause_ruled_out", valuation,
                      t["fact.hypothesis_ruled_out"], at=ruled_out,
                      authority=Authority.CONFIRMED, event=dismissed.id, source=erp)
    cause = _text(minter, "ops.cause", valuation,
                  t["fact.cause"],
                  at=confirmed, authority=Authority.CONFIRMED, event=found.id, source=mdm,
                  supersedes=hypothesis.id, lore=incident_lore)

    records = CanonicalFact(
        id=minter.next("FACT"), kind="ops.affected_records", subject=hierarchy,
        value=Quantity(amount=affected, unit="SKUs"), valid_from=confirmed,
        authority=Authority.CONFIRMED, source_system=mdm, event_id=found.id, lore_ids=incident_lore,
    )
    # Named rather than gestured at. "A comparable failure happened before" is
    # unfalsifiable and unanswerable; naming the period makes "when did this last
    # happen, and did the fix hold" a question with an answer in the corpus.
    recurrence = _text(
        minter, "ops.previous_similar_incident", valuation,
        (
            t["fact.recurrence_with_period"].format(prior_period=prior_incident_periods[-1])
            if prior_incident_periods
            else t["fact.recurrence_first"]
        ),
        at=confirmed, authority=Authority.CONFIRMED, event=found.id,
        source=platform, lore=incident_lore,
    )
    workaround = _text(minter, "ops.workaround", valuation,
                       t["fact.workaround"],
                       at=worked_around, authority=Authority.CONFIRMED, event=patched.id,
                       source=platform, lore=calendar_lore)
    valuation_status = _text(minter, "ops.valuation_status", valuation, t["fact.valuation_status"],
                             at=available, authority=Authority.SYSTEM_OF_RECORD, event=valued.id,
                             source=platform, period=period)
    delayed_status = _text(minter, "close.status", company_id, "delayed", at=escalated,
                           authority=Authority.SYSTEM_OF_RECORD, event=delayed.id, source=erp,
                           period=period, lore=calendar_lore)
    revised = _text(minter, "close.revised_date", company_id,
                    calendar.business_days_after(period_end(period), 5).isoformat(), at=escalated,
                    authority=Authority.SYSTEM_OF_RECORD, event=delayed.id, source=erp, period=period)
    classification = _text(minter, "ops.root_cause_classification", hierarchy,
                           t["fact.classification"],
                           at=reviewed, authority=Authority.CONFIRMED, event=classified.id, lore=ownership_lore)
    owner = _text(minter, "ops.mapping_table_owner", mdm, "unassigned", at=reviewed,
                  authority=Authority.CONFIRMED, event=classified.id, source=mdm, lore=ownership_lore)
    tickets = _text(minter, "ops.remediation", hierarchy,
                    t["fact.remediation"], at=remediated, authority=Authority.SYSTEM_OF_RECORD,
                    event=remediation.id, source=mdm, lore=ownership_lore)
    scope = _text(minter, "ops.remediation_addresses", hierarchy,
                  t["fact.remediation_scope"], at=remediated, authority=Authority.CONFIRMED,
                  event=remediation.id, lore=ownership_lore)
    impact = CanonicalFact(
        id=minter.next("FACT"), kind="financial.incident_pl_impact", subject=company_id, period=period,
        value=Quantity(amount=0, unit=money_unit),
        valid_from=_at(calendar.business_days_after(period_end(period), 5), 16, 40),
        authority=Authority.SYSTEM_OF_RECORD, source_system=erp, event_id=None,
    )

    facts.extend([status, reference, hypothesis, dismissal, cause, records, recurrence, workaround,
                  valuation_status, delayed_status, revised, classification, owner, tickets, scope, impact])

    keys.update({
        "fact_feed_status": status.id,
        "fact_incident_ref": reference.id,
        "fact_hypothesis": hypothesis.id,
        "fact_cause_ruled_out": dismissal.id,
        "fact_cause": cause.id,
        "fact_affected": records.id,
        "fact_recurrence": recurrence.id,
        "fact_workaround": workaround.id,
        "fact_valuation_status": valuation_status.id,
        "fact_close_delayed": delayed_status.id,
        "fact_revised_date": revised.id,
        "fact_classification": classification.id,
        "fact_owner": owner.id,
        "fact_remediation": tickets.id,
        "fact_remediation_scope": scope.id,
        "fact_pl_impact": impact.id,
        "incident_reference": incident_ref,
    })
    return {"events": events, "facts": facts, "keys": keys}
