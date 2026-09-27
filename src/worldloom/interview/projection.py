"""The interviewed world as the records its systems hold: shared ids, per period, per level.

The engine's projections already turn a world into connector records that
share identifiers: a Jira issue and an email carry the event id they record,
a SharePoint file and a Confluence page the artifact id and the fact ids it
reports. What they cannot know is what the interview said: which process step
an event is, which systems that step touches, which period a document was
written for, who authored, reviews and approves it and at what level. This
projection adds exactly that, and nothing else:

- a record the engine already projects for an interviewed event or document
  gains ``interview_*`` fields (the process, the step, the LOB, the period,
  the author's role and level, the review chain, the revision count);
- a step on a system the engine projects nothing for (a ServiceNow change, a
  Salesforce case, a Slack message, an Outlook message, a SharePoint list
  item, a Confluence page) becomes a record of its own, carrying the event's
  facts, its id and the documents it triggered, so it joins the others on the
  same identifiers.

It is a ``ConnectorProjectionRegistry`` like every other, so materialisation,
the emulator and the graders see one record set, and it is opt-in: a corpus
not built from an interview never meets it, so its records are what they were.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from functools import cached_property
from typing import Any

from ..connector_data import (
    ConnectorProjectionRegistry,
    ConnectorRecord,
    builtin_projections,
)
from ..ids import content_key
from .systems import EVENT_PROJECTED, STEP_ENTITIES


def _period(value: Any) -> str:
    return value.isoformat()[:7] if value is not None else ""


class Index:
    """What the projection reads from a world and a resolution, computed once."""

    def __init__(self, world: Any, resolution: Mapping[str, Any]) -> None:
        self.world = world
        self.resolution = resolution

    @cached_property
    def facts(self) -> dict[str, Any]:
        return {fact.id: fact for fact in self.world.facts}

    @cached_property
    def intents(self) -> dict[str, Any]:
        return {intent.id: intent for intent in self.world.artifact_intents}

    @cached_property
    def facts_by_event(self) -> dict[str, list[Any]]:
        out: dict[str, list[Any]] = {}
        for fact in self.world.facts:
            if fact.event_id:
                out.setdefault(fact.event_id, []).append(fact)
        return out

    @cached_property
    def step_of_kind(self) -> dict[str, str]:
        """Event kind -> ``Process.step`` key; the processes lint keeps event kinds unique."""
        return {str(step["step"]): key for key, step in self.resolution["steps"].items()}

    @cached_property
    def role_of_person(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, person in sorted(self.world._roles.items()):
            out.setdefault(str(person), key)
        return out

    @cached_property
    def person_of_role(self) -> dict[str, str]:
        return {key: str(person) for key, person in self.world._roles.items()}

    def event_period(self, event: Any) -> str:
        periods = Counter(fact.period for fact in self.facts_by_event.get(event.id, ()) if fact.period)
        if periods:
            return sorted(periods.items(), key=lambda item: (-item[1], item[0]))[0][0]
        return _period(event.occurred_at)

    @cached_property
    def step_events(self) -> list[tuple[Any, str]]:
        """Every world event that is an interviewed process step, with its step key, in timeline order."""
        return [(event, self.step_of_kind[event.kind]) for event in self.world.timeline() if event.kind in self.step_of_kind]

    @cached_property
    def artifacts_by_event(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for intent in self.world.artifact_intents:
            for event_id in intent.triggered_by:
                out.setdefault(event_id, []).append(intent.id)
        return out

    @cached_property
    def artifact_period(self) -> dict[str, str]:
        """Artifact id -> the period its figures are for (the most common period among them)."""
        out: dict[str, str] = {}
        events = {event.id: event for event in self.world.timeline()}
        for intent in self.world.artifact_intents:
            periods = Counter(self.facts[f].period for f in intent.required_fact_ids if f in self.facts and self.facts[f].period)
            if periods:
                out[intent.id] = sorted(periods.items(), key=lambda item: (-item[1], item[0]))[0][0]
            elif intent.triggered_by and intent.triggered_by[0] in events:
                out[intent.id] = self.event_period(events[intent.triggered_by[0]])
        return out

    def evidence(self, event: Any) -> list[str]:
        """The facts a step's record carries: the event's own, else what its documents report, else its cause's.

        A step that mints nothing this period (a signature whose terms carry
        forward from the first month, a steering meeting whose decisions are
        in its minutes) still happened on the record, and what it rests on is
        the documents it triggered or the event that caused it; a step record
        with no facts at all would be refused as evidence of nothing.
        """
        own = sorted(fact.id for fact in self.facts_by_event.get(event.id, ()))
        if own:
            return own
        reported = sorted({fact for artifact in self.artifacts_by_event.get(event.id, ())
                           for fact in self.intents[artifact].required_fact_ids if fact in self.facts})
        if reported:
            return reported
        return sorted(fact.id for cause in event.caused_by for fact in self.facts_by_event.get(cause, ()))

    def step_fields(self, event: Any, step: str) -> dict[str, Any]:
        detail = self.resolution["steps"][step]
        return {"interview_process": detail["process"], "interview_step": step, "interview_lob": detail["lob"],
                "period": self.event_period(event)}

    def document_fields(self, record: ConnectorRecord) -> dict[str, Any]:
        artifact_id = str(record.fields.get("world_artifact_id") or "")
        artifact_type = str(record.fields.get("artifact_type") or "")
        detail = self.resolution["documents"].get(artifact_type)
        fields: dict[str, Any] = {"period": self.artifact_period.get(artifact_id, "")}
        # A rendered file keeps its file name as `name`: the served emulator
        # and the compiled row's snapshot both read `fields.name` now
        # (`connector_emulator._canonical_record`), so the title no longer has
        # to stand in for it here.
        history = record.fields.get("version_history")
        fields["revisions"] = len(history) if isinstance(history, list) else 1
        author = self.role_of_person.get(str(record.fields.get("author_id") or ""), "")
        if author:
            fields["author_role"] = author
            fields["author_level"] = self.resolution["levels"].get(author, "")
        if detail is not None:
            fields.update(interview_process=detail["process"], interview_lob=detail["lob"])
            for seat in ("reviewer", "approver"):
                holder = detail.get(seat)
                if holder:
                    fields[f"{seat}_role"] = holder
                    fields[f"{seat}_id"] = self.person_of_role.get(holder, "")
        return fields

    def enrich(self, record: ConnectorRecord) -> ConnectorRecord:
        added: dict[str, Any] = {}
        facts = record.fact_ids
        if record.fields.get("world_artifact_id"):
            added.update(self.document_fields(record))
        for event_id in record.event_ids:
            event = self.events.get(event_id)
            if event is not None and event.kind in self.step_of_kind:
                added.update(self.step_fields(event, self.step_of_kind[event.kind]))
                facts = facts or self.evidence(event)
                break
        if not added:
            return record
        return record.model_copy(update={"fields": {**record.fields, **added}, "fact_ids": list(facts)})

    @cached_property
    def events(self) -> dict[str, Any]:
        return {event.id: event for event in self.world.timeline()}

    def step_records(self, connector: str) -> list[ConnectorRecord]:
        """A record per interviewed step on *connector*, where the engine projects none."""
        systems = [system for system, (name, _) in STEP_ENTITIES.items() if name == connector and system not in EVENT_PROJECTED]
        if not systems:
            return []
        system = systems[0]
        _, entity = STEP_ENTITIES[system]
        records: list[ConnectorRecord] = []
        for ordinal, (event, step) in enumerate(self.step_events, start=1):
            if system not in self.resolution["steps"][step]["systems"]:
                continue
            key = content_key("interview-step", self.world.seed, event.id, system)
            external = _external_id(system, ordinal, key)
            actors = [self.role_of_person.get(actor, actor) for actor in event.actors]
            fields: dict[str, Any] = {
                **_native_fields(system, external, event, self.world.company.name),
                **self.step_fields(event, step),
                "linked_event_id": event.id,
                "occurred_at": event.occurred_at.isoformat(),
                "actor_roles": actors,
            }
            records.append(ConnectorRecord(
                id=f"CONN-{connector.upper()}-I{key[:11].upper()}", connector=connector, entity=entity,
                external_id=external, title=event.summary, fields=fields,
                fact_ids=self.evidence(event),
                event_ids=[event.id], source_artifact_ids=sorted(self.artifacts_by_event.get(event.id, ())),
            ))
        return records


def _external_id(system: str, ordinal: int, key: str) -> str:
    return {
        "servicenow": f"CHG{ordinal:07d}",
        "salesforce": f"500{key[:15].upper()}",
        "slack": f"{1_700_000_000 + ordinal}.{key[:6]}",
        "outlook": f"AAMk{key[:20]}",
        "sharepoint": f"LI-{key[:12].upper()}",
        "confluence": str(20_000_000 + ordinal),
    }[system]


def _native_fields(system: str, external: str, event: Any, company: str) -> dict[str, Any]:
    """The fields each product names its record with, so a search reads like that product's."""
    if system == "servicenow":
        return {"sys_id": external, "number": external, "short_description": event.summary,
                "state": "Closed", "approval": "approved", "opened_at": event.occurred_at.isoformat()}
    if system == "salesforce":
        return {"id": external, "subject": event.summary, "status": "Closed", "origin": company}
    if system == "slack":
        return {"ts": external, "text": event.summary}
    if system == "outlook":
        return {"id": external, "subject": event.summary, "body_preview": event.summary}
    if system == "sharepoint":
        return {"id": external, "title": event.summary}
    return {"page_id": external, "title": event.summary}


def projections(world: Any, resolution: Mapping[str, Any]) -> ConnectorProjectionRegistry:
    """The builtin projections, each enriched with the interview and followed by its own step records."""
    base = builtin_projections()
    index = Index(world, resolution)
    step_connectors = {name for name, _ in STEP_ENTITIES.values()}
    mapping = {}
    for connector in sorted(set(base._projections) | step_connectors):
        held = base._projections.get(connector)

        def project(value: Any, connector: str = connector, held: Any = held) -> list[ConnectorRecord]:
            records = [index.enrich(record) for record in (held(value) if held is not None else [])]
            return [*records, *index.step_records(connector)]

        mapping[connector] = project
    return ConnectorProjectionRegistry(mapping)


__all__ = ["Index", "projections"]
