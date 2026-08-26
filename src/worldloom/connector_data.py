"""Deterministic Jira, ServiceNow and email projections of a World."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import Field

from .ids import content_key
from .models import Model

if TYPE_CHECKING:
    from .world import World


class ConnectorVerb(StrEnum):
    SEARCH = "search"
    LIST = "list"
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    PATCH = "patch"
    UPSERT = "upsert"
    DELETE = "delete"
    COMMENT = "comment"
    ATTACH = "attach"
    LINK = "link"
    UNLINK = "unlink"
    DRAFT = "draft"
    SEND = "send"
    REPLY = "reply"
    FORWARD = "forward"


class ContentVerb(StrEnum):
    SUMMARIZE = "summarize"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    COMPARE = "compare"
    RECONCILE = "reconcile"
    TRANSFORM = "transform"
    GENERATE = "generate"
    RENDER = "render"
    CONVERT = "convert"


class ConnectorCapability(Model):
    connector: str
    entity: str
    verbs: tuple[ConnectorVerb, ...]
    content_verbs: tuple[ContentVerb, ...] = ()
    stable_id_field: str


class ConnectorRecord(Model):
    id: str
    connector: str
    entity: str
    external_id: str
    title: str
    fields: dict[str, Any]
    fact_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)


class ConnectorDataset(Model):
    capabilities: list[ConnectorCapability]
    records: list[ConnectorRecord]

    def for_connector(self, name: str) -> list[ConnectorRecord]:
        return [record for record in self.records if record.connector == name]


CAPABILITIES = [
    ConnectorCapability(
        connector="jira",
        entity="issue",
        verbs=(
            ConnectorVerb.SEARCH,
            ConnectorVerb.LIST,
            ConnectorVerb.READ,
            ConnectorVerb.CREATE,
            ConnectorVerb.UPDATE,
            ConnectorVerb.PATCH,
            ConnectorVerb.UPSERT,
            ConnectorVerb.COMMENT,
            ConnectorVerb.ATTACH,
            ConnectorVerb.LINK,
            ConnectorVerb.UNLINK,
        ),
        content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
        stable_id_field="key",
    ),
    ConnectorCapability(
        connector="servicenow",
        entity="incident",
        verbs=(
            ConnectorVerb.SEARCH,
            ConnectorVerb.LIST,
            ConnectorVerb.READ,
            ConnectorVerb.CREATE,
            ConnectorVerb.UPDATE,
            ConnectorVerb.PATCH,
            ConnectorVerb.UPSERT,
            ConnectorVerb.COMMENT,
            ConnectorVerb.ATTACH,
        ),
        content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
        stable_id_field="sys_id",
    ),
    ConnectorCapability(
        connector="servicenow",
        entity="change_request",
        verbs=(
            ConnectorVerb.SEARCH,
            ConnectorVerb.LIST,
            ConnectorVerb.READ,
            ConnectorVerb.CREATE,
            ConnectorVerb.UPDATE,
            ConnectorVerb.PATCH,
            ConnectorVerb.UPSERT,
            ConnectorVerb.COMMENT,
            ConnectorVerb.ATTACH,
        ),
        content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
        stable_id_field="sys_id",
    ),
    ConnectorCapability(
        connector="email",
        entity="message",
        verbs=(
            ConnectorVerb.SEARCH,
            ConnectorVerb.LIST,
            ConnectorVerb.READ,
            ConnectorVerb.DRAFT,
            ConnectorVerb.SEND,
            ConnectorVerb.REPLY,
            ConnectorVerb.FORWARD,
            ConnectorVerb.ATTACH,
            ConnectorVerb.DELETE,
        ),
        content_verbs=(
            ContentVerb.SUMMARIZE,
            ContentVerb.EXTRACT,
            ContentVerb.CLASSIFY,
        ),
        stable_id_field="message_id",
    ),
    *[
        ConnectorCapability(
            connector="salesforce",
            entity=entity,
            verbs=(
                ConnectorVerb.SEARCH,
                ConnectorVerb.LIST,
                ConnectorVerb.READ,
                ConnectorVerb.CREATE,
                ConnectorVerb.UPDATE,
                ConnectorVerb.PATCH,
                ConnectorVerb.UPSERT,
            ),
            content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
            stable_id_field="id",
        )
        for entity in ("account", "opportunity")
    ],
    *[
        ConnectorCapability(
            connector=connector,
            entity=entity,
            verbs=(
                ConnectorVerb.SEARCH,
                ConnectorVerb.LIST,
                ConnectorVerb.READ,
                ConnectorVerb.CREATE,
                ConnectorVerb.UPDATE,
                ConnectorVerb.PATCH,
                ConnectorVerb.UPSERT,
                ConnectorVerb.DELETE,
            ),
            content_verbs=(
                ContentVerb.SUMMARIZE,
                ContentVerb.EXTRACT,
                ContentVerb.GENERATE,
                ContentVerb.CONVERT,
            ),
            stable_id_field=stable_id,
        )
        for connector, entity, stable_id in (
            ("confluence", "page", "page_id"),
            ("sharepoint", "file", "item_id"),
            ("drive", "file", "file_id"),
            ("salesforce", "case", "id"),
        )
    ],
]


def canonical_verb(value: str, *, target: str = "record") -> str:
    """Resolve user language to one executable verb.

    Modify is deliberately not a protocol verb: for a stored record it means
    update; for content in memory it means transform. Callers needing field-
    level semantics should ask for patch explicitly.
    """
    lowered = value.strip().lower()
    if lowered == "modify":
        return (
            ContentVerb.TRANSFORM.value
            if target == "content"
            else ConnectorVerb.UPDATE.value
        )
    valid = {verb.value for verb in ConnectorVerb} | {
        verb.value for verb in ContentVerb
    }
    if lowered not in valid:
        raise ValueError(f"unknown verb {value!r}")
    return lowered


def _facts_by_event(world: World) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for fact in world.facts:
        if fact.event_id:
            grouped.setdefault(fact.event_id, []).append(fact)
    return grouped


def _artifact_ids(world: World, fact_ids: set[str]) -> list[str]:
    records = tuple(world.artifacts) or tuple(world.artifact_intents)
    ids: list[str] = []
    for artifact in records:
        cited = set(
            getattr(artifact, "supporting_fact_ids", None)
            or getattr(artifact, "required_fact_ids", ())
            or ()
        )
        if cited & fact_ids:
            ids.append(artifact.id)
    return sorted(ids)


def _email_address(name: str, company: str) -> str:
    local = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")
    domain = re.sub(r"[^a-z0-9]+", "", company.lower()) or "worldloom"
    return f"{local}@{domain}.example"


def generate_jira(world: World) -> list[ConnectorRecord]:
    facts = _facts_by_event(world)
    records: list[ConnectorRecord] = []
    if world.tasks:
        for index, task in enumerate(sorted(world.tasks, key=lambda item: (item.created_at, item.id)), start=1):
            key = f"WL-{index}"
            record_id = content_key("jira", world.seed, task.id)
            records.append(
                ConnectorRecord(
                    id=f"CONN-JIRA-{record_id[:12].upper()}",
                    connector="jira",
                    entity="issue",
                    external_id=key,
                    title=task.title,
                    fields={
                        "key": key,
                        "summary": task.title,
                        "description": f"{task.kind.replace('_', ' ').title()} for {world.company.name}.",
                        "status": {"open": "To Do", "assigned": "In Progress", "closed": "Done"}.get(task.state, "To Do"),
                        "priority": "High" if task.addresses == "control" else "Medium",
                        "labels": ["worldloom", task.domain, task.kind],
                        "assignee_id": task.owner_id,
                        "reporter_id": task.created_by,
                        "due_at": task.due_at.isoformat() if task.due_at else None,
                        "subject_ref": task.subject_ref,
                    },
                    fact_ids=sorted(task.fact_ids),
                    source_artifact_ids=_artifact_ids(world, set(task.fact_ids)),
                )
            )
        return records
    for index, event in enumerate(world.timeline(), start=1):
        linked = facts.get(event.id, [])
        fact_ids = sorted(fact.id for fact in linked)
        records.append(
            ConnectorRecord(
                id=f"CONN-JIRA-{content_key(world.seed, event.id)[:12].upper()}",
                connector="jira",
                entity="issue",
                external_id=f"WL-{index}",
                title=event.summary,
                fields={
                    "key": f"WL-{index}",
                    "summary": event.summary,
                    "description": f"Track {event.kind.replace('_', ' ')} for {world.company.name}.",
                    "status": "Done" if any(not fact.is_superseded for fact in linked) else "Open",
                    "priority": "Highest" if "incident" in event.kind else "Medium",
                    "labels": ["worldloom", event.kind, world.period or "current"],
                    "linked_event_id": event.id,
                    "service_ids": event.services,
                    "system_ids": event.systems,
                    "created_at": event.occurred_at.isoformat(),
                },
                fact_ids=fact_ids,
                event_ids=[event.id],
                source_artifact_ids=_artifact_ids(world, set(fact_ids)),
            )
        )
    return records


def generate_servicenow(world: World) -> list[ConnectorRecord]:
    facts = _facts_by_event(world)
    records: list[ConnectorRecord] = []
    incident_number = 1
    change_number = 1
    for event in world.timeline():
        is_incident = "incident" in event.kind or "failure" in event.kind
        entity = "incident" if is_incident else "change_request"
        prefix = "INC" if is_incident else "CHG"
        ordinal = incident_number if is_incident else change_number
        if is_incident:
            incident_number += 1
        else:
            change_number += 1
        linked = facts.get(event.id, [])
        fact_ids = sorted(fact.id for fact in linked)
        sys_id = content_key("servicenow", world.seed, event.id)
        records.append(
            ConnectorRecord(
                id=f"CONN-SNOW-{sys_id[:12].upper()}",
                connector="servicenow",
                entity=entity,
                external_id=f"{prefix}{ordinal:07d}",
                title=event.summary,
                fields={
                    "sys_id": sys_id,
                    "number": f"{prefix}{ordinal:07d}",
                    "short_description": event.summary,
                    "description": f"{event.kind.replace('_', ' ').title()} affecting {world.company.name}.",
                    "state": "Closed" if any(not fact.is_superseded for fact in linked) else "New",
                    "priority": "1" if is_incident else "3",
                    "correlation_id": event.id,
                    "service_ids": event.services,
                    "system_ids": event.systems,
                    "opened_at": event.occurred_at.isoformat(),
                },
                fact_ids=fact_ids,
                event_ids=[event.id],
                source_artifact_ids=_artifact_ids(world, set(fact_ids)),
            )
        )
    return records


def generate_email(world: World) -> list[ConnectorRecord]:
    people = {person.id: person for person in world.people}
    fallback = list(world.people)[:2]
    facts = _facts_by_event(world)
    records: list[ConnectorRecord] = []
    if world.messages:
        prior_by_thread: dict[str, str] = {}
        for message in sorted(world.messages, key=lambda item: (item.sent_at, item.id)):
            sender = people.get(message.sender_id)
            recipients = [people[item] for item in message.recipient_ids if item in people]
            sender_name = sender.name if sender else "System Operations"
            recipient_names = [item.name for item in recipients] or ["Programme Office"]
            thread_id = content_key("email-thread", message.subject_ref or message.id)
            message_key = content_key("email", world.seed, message.id)
            external_id = f"<{message_key}@worldloom.example>"
            records.append(
                ConnectorRecord(
                    id=f"CONN-EMAIL-{message_key[:12].upper()}",
                    connector="email",
                    entity="message",
                    external_id=external_id,
                    title=message.text.splitlines()[0][:120] or message.kind.replace("_", " ").title(),
                    fields={
                        "message_id": external_id,
                        "thread_id": thread_id,
                        "from": _email_address(sender_name, world.company.name),
                        "to": [_email_address(name, world.company.name) for name in recipient_names],
                        "subject": message.subject_ref or message.kind.replace("_", " ").title(),
                        "body": message.text,
                        "sent_at": message.sent_at.isoformat(),
                        "in_reply_to": prior_by_thread.get(thread_id),
                        "labels": ["worldloom", message.kind, world.period or "current"],
                    },
                    fact_ids=sorted(message.disclosed_fact_ids),
                    source_artifact_ids=_artifact_ids(world, set(message.disclosed_fact_ids)),
                )
            )
            prior_by_thread[thread_id] = external_id
        return records
    for index, event in enumerate(world.timeline(), start=1):
        actors = [people[actor] for actor in event.actors if actor in people]
        sender = actors[0] if actors else (fallback[0] if fallback else None)
        recipient = actors[1] if len(actors) > 1 else (
            fallback[1] if len(fallback) > 1 else sender
        )
        sender_name = sender.name if sender else "System Operations"
        recipient_name = recipient.name if recipient else "Programme Office"
        linked = facts.get(event.id, [])
        fact_ids = sorted(fact.id for fact in linked)
        message_key = content_key("email", world.seed, event.id)
        records.append(
            ConnectorRecord(
                id=f"CONN-EMAIL-{message_key[:12].upper()}",
                connector="email",
                entity="message",
                external_id=f"<{message_key}@worldloom.example>",
                title=event.summary,
                fields={
                    "message_id": f"<{message_key}@worldloom.example>",
                    "thread_id": content_key("thread", event.caused_by or event.id),
                    "from": _email_address(sender_name, world.company.name),
                    "to": [_email_address(recipient_name, world.company.name)],
                    "subject": event.summary,
                    "body": (
                        f"{recipient_name},\n\n{event.summary}. This update relates to "
                        f"{world.company.name} and record {event.id}. Please review the "
                        f"linked evidence and outstanding actions.\n\n{sender_name}"
                    ),
                    "sent_at": event.occurred_at.isoformat(),
                    "in_reply_to": None if index == 1 else records[-1].external_id,
                    "labels": ["worldloom", world.period or "current"],
                },
                fact_ids=fact_ids,
                event_ids=[event.id],
                source_artifact_ids=_artifact_ids(world, set(fact_ids)),
            )
        )
    return records


def generate_artifact_projection(
    world: World, connector: str
) -> list[ConnectorRecord]:
    entity = {
        "confluence": "page",
        "sharepoint": "file",
        "drive": "file",
        "salesforce": "case",
    }[connector]
    artifacts = tuple(world.artifacts) or tuple(world.artifact_intents)
    records = []
    for index, artifact in enumerate(sorted(artifacts, key=lambda item: item.id), start=1):
        fact_ids = sorted(
            getattr(artifact, "supporting_fact_ids", None)
            or getattr(artifact, "required_fact_ids", ())
            or ()
        )
        key = content_key(connector, world.seed, artifact.id)
        external_id = {
            "confluence": str(10_000_000 + index),
            "sharepoint": key,
            "drive": key,
            "salesforce": f"500{key[:15].upper()}",
        }[connector]
        title = getattr(artifact, "title", None) or (
            f"{artifact.artifact_type.replace('_', ' ').title()} - "
            f"{world.period or 'current'}"
        )
        records.append(
            ConnectorRecord(
                id=f"CONN-{connector.upper()}-{key[:12].upper()}",
                connector=connector,
                entity=entity,
                external_id=external_id,
                title=title,
                fields={
                    "name": title,
                    "artifact_type": artifact.artifact_type,
                    "domain": artifact.domain,
                    "author_id": artifact.author_id,
                    "audience": artifact.audience,
                    "version": getattr(artifact, "version", 1),
                    "world_artifact_id": artifact.id,
                    "reporting_period": world.period,
                },
                fact_ids=fact_ids,
                event_ids=sorted(
                    getattr(artifact, "event_ids", ())
                    or getattr(artifact, "triggered_by", ())
                ),
                source_artifact_ids=[artifact.id],
            )
        )
    return records


def generate_salesforce(world: World) -> list[ConnectorRecord]:
    records = [
        ConnectorRecord(
            id=f"CONN-SALESFORCE-{content_key('salesforce-account', world.company.id)[:12].upper()}",
            connector="salesforce",
            entity="account",
            external_id=f"001{content_key('salesforce-account', world.company.id)[:15].upper()}",
            title=world.company.name,
            fields={"name": world.company.name, "company_id": world.company.id, "reporting_period": world.period},
        )
    ]
    facts = _facts_by_event(world)
    for index, event in enumerate(world.timeline(), start=1):
        lowered = f"{event.kind} {event.summary}".lower()
        if not any(token in lowered for token in ("customer", "sale", "renew", "opportun", "case", "support", "escalat")):
            continue
        entity = "case" if any(token in lowered for token in ("case", "support", "escalat")) else "opportunity"
        prefix = "500" if entity == "case" else "006"
        key = content_key("salesforce", world.seed, event.id, entity)
        linked = facts.get(event.id, [])
        records.append(
            ConnectorRecord(
                id=f"CONN-SALESFORCE-{key[:12].upper()}",
                connector="salesforce",
                entity=entity,
                external_id=f"{prefix}{key[:15].upper()}",
                title=event.summary,
                fields={
                    "id": f"{prefix}{key[:15].upper()}",
                    "name": event.summary,
                    "stage": "Closed Won" if any(not fact.is_superseded for fact in linked) else "Qualification",
                    "account_id": records[0].external_id,
                    "event_id": event.id,
                    "occurred_at": event.occurred_at.isoformat(),
                },
                fact_ids=sorted(fact.id for fact in linked),
                event_ids=[event.id],
            )
        )
    return records


def generate_connector_data(
    world: World,
    connectors: tuple[str, ...] = (
        "jira",
        "confluence",
        "sharepoint",
        "drive",
        "servicenow",
        "salesforce",
        "email",
    ),
) -> ConnectorDataset:
    generators = {
        "jira": generate_jira,
        "servicenow": generate_servicenow,
        "email": generate_email,
        "confluence": lambda value: generate_artifact_projection(value, "confluence"),
        "sharepoint": lambda value: generate_artifact_projection(value, "sharepoint"),
        "drive": lambda value: generate_artifact_projection(value, "drive"),
        "salesforce": generate_salesforce,
    }
    unknown = set(connectors) - set(generators)
    if unknown:
        raise ValueError(f"unknown connector projection(s): {sorted(unknown)}")
    records = [
        record
        for connector in connectors
        for record in generators[connector](world)
    ]
    capabilities = [
        capability
        for capability in CAPABILITIES
        if capability.connector in connectors
    ]
    return ConnectorDataset(capabilities=capabilities, records=records)
