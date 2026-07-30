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

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ..ids import Minter
from ..models import Authority, CanonicalFact, EnterpriseEvent, Quantity
from ..rng import Rng


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
) -> CloseEpisode:
    """Generate the close, and an incident if lore and the seed conspire."""
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
        summary=f"{period} month-end close commenced; the orchestrator began the overnight sequence.",
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
                               ownership_lore=ownership_lore, previous_event=start)
        events.extend(chain["events"])
        facts.extend(chain["facts"])
        keys.update(chain["keys"])
        delay_days = 1
        finalised_day = business_days_after(ends, 5)

    finalised_at = _at(finalised_day, 16, 40)
    finalised = EnterpriseEvent(
        id=minter.next("EV"), kind="close_finalised", occurred_at=finalised_at,
        summary=(
            f"{period} close finalised and the ledger locked"
            + (", one business day later than the calendar commitment." if delay_days else " on the committed date.")
        ),
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


def _incident_chain(
    rng: Rng, minter: Minter, *, period: str, day: date, company_id: str, roles: dict[str, str],
    incident_lore: list[str], calendar_lore: list[str], ownership_lore: list[str],
    previous_event: EnterpriseEvent,
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
                   "The inventory valuation pipeline failed. On-hand stock could not be valued for the period.",
                   actors=[], services=[valuation, hierarchy], systems=[platform],
                   caused_by=[previous_event.id], lore=incident_lore)
    opened = event("incident_opened", raised,
                   f"Service operations opened incident {incident_ref} at priority P2 against inventory-valuation.",
                   actors=[roles["svc_desk"], roles["svc_incident"]], services=[valuation],
                   systems=[platform], caused_by=[failed.id])
    guessed = event("hypothesis_recorded", hypothesised,
                    "Initial triage attributed the failure to an overnight ERP outage.",
                    actors=[roles["svc_desk"]], services=[valuation], systems=[erp, platform],
                    caused_by=[opened.id])
    dismissed = event("hypothesis_superseded", ruled_out,
                      "The ERP outage hypothesis was ruled out; ERP logs showed no interruption in the window.",
                      actors=[roles["platform_senior"]], services=[valuation], systems=[erp],
                      caused_by=[guessed.id])
    found = event("root_cause_confirmed", confirmed,
                  "Root cause confirmed as a stale legacy-to-new product hierarchy mapping, leaving "
                  f"{affected:,} SKUs unmapped and unvaluable.",
                  actors=[roles["platform_senior"], roles["merch_analyst"]], services=[hierarchy],
                  systems=[mdm], units=[roles["unit_gm"]], caused_by=[dismissed.id], lore=incident_lore)
    patched = event("workaround_applied", worked_around,
                    "A manual hierarchy mapping override was applied so valuation could complete for the period.",
                    actors=[roles["platform_senior"], roles["merch_analyst"]],
                    services=[valuation, hierarchy], systems=[mdm, platform],
                    caused_by=[found.id], lore=calendar_lore)
    valued = event("valuation_available", available,
                   f"Inventory valuation completed for {period} following the manual override.",
                   actors=[roles["platform_senior"]], services=[valuation], systems=[platform],
                   caused_by=[patched.id])
    delayed = event("close_delayed", escalated,
                    "Final close was pushed by one business day and escalated to the Group CFO.",
                    actors=[roles["controller"], roles["cfo"]], services=[roles["svc_orchestrator"]],
                    systems=[erp], caused_by=[valued.id], lore=calendar_lore)
    classified = event("control_failure_identified", reviewed,
                       "Review established the underlying failure as a control failure: the hierarchy mapping "
                       "table has no registered owner and no required reviewer.",
                       actors=[roles["platform_lead"], roles["audit"]], services=[hierarchy],
                       systems=[mdm], units=[roles["unit_gm"]], caused_by=[found.id], lore=ownership_lore)
    remediation = event("remediation_created", remediated,
                        "Two remediation tickets raised: automate the mapping validation, and assign ownership "
                        "of the mapping table with a mandatory reviewer.",
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
    reference = _text(minter, "ops.incident_opened", valuation,
                      f"{incident_ref} opened at priority P2 against inventory-valuation",
                      at=raised, authority=Authority.SYSTEM_OF_RECORD, event=opened.id, source=platform)

    # The wrong answer, with an expiry. It is superseded, never overwritten.
    hypothesis = _text(minter, "ops.cause", valuation, "Overnight ERP outage", at=hypothesised,
                       authority=Authority.INITIAL_HYPOTHESIS, event=guessed.id, until=ruled_out)
    dismissal = _text(minter, "ops.cause_ruled_out", valuation,
                      "ERP logs show no interruption during the valuation window", at=ruled_out,
                      authority=Authority.CONFIRMED, event=dismissed.id, source=erp)
    cause = _text(minter, "ops.cause", valuation,
                  "Stale legacy-to-new product hierarchy mapping in the merchandising master",
                  at=confirmed, authority=Authority.CONFIRMED, event=found.id, source=mdm,
                  supersedes=hypothesis.id, lore=incident_lore)

    records = CanonicalFact(
        id=minter.next("FACT"), kind="ops.affected_records", subject=hierarchy,
        value=Quantity(amount=affected, unit="SKUs"), valid_from=confirmed,
        authority=Authority.CONFIRMED, source_system=mdm, event_id=found.id, lore_ids=incident_lore,
    )
    recurrence = _text(minter, "ops.previous_similar_incident", valuation,
                       "A comparable valuation failure was traced to the same mapping table",
                       at=confirmed, authority=Authority.CONFIRMED, event=found.id,
                       source=platform, lore=incident_lore)
    workaround = _text(minter, "ops.workaround", valuation,
                       "Manual hierarchy mapping override applied to complete valuation for the period",
                       at=worked_around, authority=Authority.CONFIRMED, event=patched.id,
                       source=platform, lore=calendar_lore)
    valuation_status = _text(minter, "ops.valuation_status", valuation, "Inventory valuation completed",
                             at=available, authority=Authority.SYSTEM_OF_RECORD, event=valued.id,
                             source=platform, period=period)
    delayed_status = _text(minter, "close.status", company_id, "delayed", at=escalated,
                           authority=Authority.SYSTEM_OF_RECORD, event=delayed.id, source=erp,
                           period=period, lore=calendar_lore)
    revised = _text(minter, "close.revised_date", company_id,
                    business_days_after(period_end(period), 5).isoformat(), at=escalated,
                    authority=Authority.SYSTEM_OF_RECORD, event=delayed.id, source=erp, period=period)
    classification = _text(minter, "ops.root_cause_classification", hierarchy,
                           "control_failure: the mapping table has no registered owner and no required reviewer",
                           at=reviewed, authority=Authority.CONFIRMED, event=classified.id, lore=ownership_lore)
    owner = _text(minter, "ops.mapping_table_owner", mdm, "unassigned", at=reviewed,
                  authority=Authority.CONFIRMED, event=classified.id, source=mdm, lore=ownership_lore)
    tickets = _text(minter, "ops.remediation", hierarchy,
                    "One ticket automates mapping validation; one assigns mapping table ownership "
                    "with a mandatory reviewer", at=remediated, authority=Authority.SYSTEM_OF_RECORD,
                    event=remediation.id, source=mdm, lore=ownership_lore)
    scope = _text(minter, "ops.remediation_addresses", hierarchy,
                  "The ownership ticket addresses the control failure; the validation ticket addresses "
                  "only the detection gap", at=remediated, authority=Authority.CONFIRMED,
                  event=remediation.id, lore=ownership_lore)
    impact = CanonicalFact(
        id=minter.next("FACT"), kind="financial.incident_pl_impact", subject=company_id, period=period,
        value=Quantity(amount=0, unit="AUD_thousands"),
        valid_from=_at(business_days_after(period_end(period), 5), 16, 40),
        authority=Authority.SYSTEM_OF_RECORD, source_system=erp, event_id=None,
    )

    facts.extend([status, reference, hypothesis, dismissal, cause, records, recurrence, workaround,
                  valuation_status, delayed_status, revised, classification, owner, tickets, scope, impact])

    keys.update({
        "fact_feed_status": status.id,
        "fact_incident_ref": reference.id,
        "fact_hypothesis": hypothesis.id,
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
