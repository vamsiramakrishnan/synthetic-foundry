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

from ..ids import Minter
from ..models import Authority, CanonicalFact, EnterpriseEvent, Quantity
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


def business_days_after(start: date, count: int) -> date:
    """The date *count* business days after *start*, excluding weekends."""
    current, remaining = start, count
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def period_end(period: str) -> date:
    """The last calendar day of a ``YYYY-MM`` period."""
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
) -> CloseEpisode:
    """Generate the close, and an incident if lore and the seed conspire.

    ``text`` overrides entries of ``TEXT`` — the surface a pack re-voices,
    over causality it cannot touch. ``money_unit`` is the archetype's own
    currency (``f"{currency}_{currency_unit}"``); it defaults to the stock
    retail unit so a caller that never sets it reproduces every corpus this
    engine has ever built.
    """
    t = episode_text.merged(TEXT, text)
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}

    ends = period_end(period)
    day1 = business_days_after(ends, 1)
    due = business_days_after(ends, 4)

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
                               money_unit=money_unit)
        events.extend(chain["events"])
        facts.extend(chain["facts"])
        keys.update(chain["keys"])
        delay_days = 1
        finalised_day = business_days_after(ends, 5)

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
) -> dict:
    """The eight-step incident: detect, triage, be wrong, be corrected, work around, escalate."""
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}

    detected = _at(day, 8, rng.integer(5, 25))
    raised = detected + timedelta(minutes=rng.integer(4, 12))
    hypothesised = detected + timedelta(minutes=rng.integer(45, 70))
    ruled_out = hypothesised + timedelta(minutes=rng.integer(120, 180))
    confirmed = ruled_out + timedelta(minutes=rng.integer(80, 120))
    worked_around = confirmed + timedelta(minutes=rng.integer(90, 130))
    available = worked_around + timedelta(minutes=rng.integer(120, 170))
    escalated = _at(day + timedelta(days=1 if (day + timedelta(days=1)).weekday() < 5 else 3), 9, 0)
    reviewed = _at(business_days_after(day, 2), 11, 0)
    remediated = _at(business_days_after(day, 2), 14, 0)

    affected = rng.integer(4_000, 26_000)
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
                    business_days_after(period_end(period), 5).isoformat(), at=escalated,
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
        valid_from=_at(business_days_after(period_end(period), 5), 16, 40),
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
