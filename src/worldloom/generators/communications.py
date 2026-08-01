"""The communications compilers: meeting minutes and email threads.

The fan-out layer's first two document families, and the reason they are
*mechanism* (this module) rather than domain content: both are pure projections
of structure every episode already generates. A minutes document is an event
with actors, the facts that event established, and the decisions those facts
record; a thread is a causal chain of events, one message per event, each
message knowing only what its own event had established. Neither invents
anything — which is what lets them be added to a vertical by planning an
intent, with no new facts, no new events, and no id shifts ahead of anything
already minted.

Minutes are deliberately **fully resolved** — tables, no prose sections. Real
minutes are mostly structure (who was there, what was decided, who owns what),
and structure is what the deterministic layer owns. It also means adding
minutes to an episode adds zero narration burden: the reference narration CI,
which rejects any submission with a request it does not answer, is unaffected.

Threads are the opposite: a message body is prose, so each message is a
section awaiting narrative, bounded to the facts its own event established.
The epistemic constraint is carried by fact assignment — an early message's
allowed facts simply do not include what was only learned later — which is the
same mechanism that keeps a stale status page honestly wrong.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ..ids import Minter
from ..models import (
    ArtifactIntent,
    ArtifactIR,
    ArtifactSection,
    CanonicalFact,
    Cell,
    Column,
    EnterpriseEvent,
    Row,
    Table,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World

#: How long after the meeting its minutes are circulated, and how long after
#: an event its message is sent. Small and fixed: minutes go out the same
#: afternoon, a message follows its moment within the hour.
#:
#: These same values are registered as the types' ``_LAG`` entries in
#: ``documents.py``, and the coupling is deliberate: the manifest dates an
#: artifact by ``written_at`` (newest cited fact plus the type's lag), and the
#: IR metadata below must stamp the identical instant, or a file's own
#: properties would contradict the corpus.
MINUTES_LAG = timedelta(hours=3)
MESSAGE_LAG = timedelta(minutes=25)


def _created(facts: list[CanonicalFact], lag: timedelta) -> str:
    """The manifest's ``written_at`` rule, computed locally: newest cited fact
    plus the type lag. Local rather than imported, because ``documents.py``
    imports this module to register its compilers and the dependency cannot
    run both ways."""
    return (max(fact.valid_from for fact in facts) + lag).isoformat()


def _attendees(world: World, event: EnterpriseEvent) -> list:  # type: ignore[no-untyped-def]
    return [world.people.by_id(pid) for pid in event.actors]


def minutes_ir(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """Minutes of the meeting the intent's first triggering event records.

    The event supplies the meeting: its actors are the attendees, its summary
    is the item under discussion, and the intent's facts are what the meeting
    decided or noted. Everything on the page is a citation; nothing is prose —
    which is both what real minutes look like and what keeps this artifact
    outside the narration loop entirely.
    """
    from ..narrative import references

    if not intent.triggered_by:
        raise ValueError(f"{intent.id}: minutes need a triggering event to be minutes of")
    event = world.events.by_id(intent.triggered_by[0])
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    names = world.entity_names()
    company = world.company

    attendees = _attendees(world, event)
    attendance = Table(
        key="attendees",
        title="Attendance",
        columns=[
            Column(key="name", label="Name"),
            Column(key="title", label="Title"),
        ],
        rows=[
            Row(key=person.id, label=person.name, cells={
                "name": Cell(value=person.name),
                "title": Cell(value=person.title),
            })
            for person in attendees
        ],
        note="Attendance is drawn from the meeting's own event record.",
    )

    # Decisions and noted facts, one row per citation. The distinction a reader
    # needs — what was *decided* here versus what was merely *before* the
    # meeting — is the fact's own event linkage: a fact this meeting's event
    # minted is a decision of this meeting, anything else is tabled material.
    decided = [f for f in facts if f.event_id == event.id]
    tabled = [f for f in facts if f.event_id != event.id]

    def fact_table(key: str, title: str, rows: list[CanonicalFact], note: str) -> Table:
        return Table(
            key=key,
            title=title,
            columns=[
                Column(key="subject", label="Subject"),
                Column(key="statement", label="Statement"),
                Column(key="standing", label="Standing"),
            ],
            rows=[
                Row(key=fact.id, label=fact.id, cells={
                    "subject": Cell(value=names.get(fact.subject, fact.subject)),
                    "statement": Cell(value=references.describe(fact), fact_id=fact.id),
                    "standing": Cell(value=fact.authority.value),
                })
                for fact in rows
            ],
            note=note,
        )

    sections = [
        ArtifactSection(
            heading="Meeting",
            table=Table(
                key="meeting",
                title="Meeting",
                columns=[Column(key="field", label=""), Column(key="value", label="")],
                rows=[
                    Row(key="held", label="Held", cells={
                        "field": Cell(value="Held"),
                        "value": Cell(value=event.occurred_at.isoformat()),
                    }),
                    Row(key="item", label="Item", cells={
                        "field": Cell(value="Item"),
                        "value": Cell(value=event.summary),
                    }),
                ],
            ),
        ),
        ArtifactSection(heading="Attendance", table=attendance),
    ]
    if tabled:
        sections.append(ArtifactSection(
            heading="Tabled",
            table=fact_table(
                "tabled", "Tabled before the meeting", tabled,
                "Material the meeting had in front of it. Standing is the record's, "
                "not the meeting's.",
            ),
        ))
    if decided:
        sections.append(ArtifactSection(
            heading="Decisions",
            table=fact_table(
                "decisions", "Decided and recorded", decided,
                "What this meeting itself put on the record.",
            ),
        ))

    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"Minutes — {event.summary.rstrip('.')}"[:120],
        subtitle=f"{company.name} · {event.occurred_at.date().isoformat()}",
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_created": _created(facts, MINUTES_LAG),
            "company": company.name,
            "author": author.name,
            "author_title": author.title,
            "persona": persona.label if persona else "",
            "voice": persona.voice if persona else "",
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )


def thread_ir(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    """An email thread over the intent's triggering events, one message each.

    The chain is the thread: each triggering event contributes one message,
    sent by that event's first actor shortly after the moment it records, and
    allowed to cite only the intent facts that event had established — facts
    minted by the event itself or already valid when it occurred. That bound is
    what makes the early messages honestly incomplete: the first report of an
    incident cannot cite the cause, because the cause was not a fact yet.
    """
    if not intent.triggered_by:
        raise ValueError(f"{intent.id}: a thread needs triggering events to thread")
    events = sorted(
        (world.events.by_id(e) for e in intent.triggered_by),
        key=lambda e: e.occurred_at,
    )
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    names = world.entity_names()

    sections: list[ArtifactSection] = []
    participants: dict[str, None] = {}
    for index, event in enumerate(events):
        if not event.actors:
            continue
        sender = world.people.by_id(event.actors[0])
        participants.setdefault(sender.id, None)
        recipients = [names.get(a, a) for a in event.actors[1:]]
        sent_at = event.occurred_at + MESSAGE_LAG
        knowable = [
            fact.id for fact in facts
            if fact.event_id == event.id
            or (fact.valid_from <= sent_at and fact.event_id != event.id)
        ]
        if not knowable:
            continue
        header = f"{index + 1} · {sender.name}"
        if recipients:
            header += f" to {', '.join(recipients)}"
        header += f" · {sent_at.strftime('%d %b %H:%M')}"
        sections.append(ArtifactSection(
            heading=header,
            body=None,
            fact_ids=knowable,
            purpose=(
                f"One email, written by {sender.name} ({sender.title}) at this moment "
                f"in the sequence: {event.summary} Write only what the sender knew "
                "then, in a working email's register — direct, addressed to the "
                "recipients, no pleasantries beyond a line. Later messages in the "
                "thread will correct this one; do not anticipate them."
            ),
            semantic_role="chronology",
        ))

    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"Email thread — {events[0].summary.rstrip('.')}"[:120],
        subtitle=" · ".join(
            names.get(pid, pid) for pid in participants
        ),
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_created": _created(facts, MESSAGE_LAG),
            "company": world.company.name,
            "author": author.name,
            "author_title": author.title,
            "persona": persona.label if persona else "",
            "voice": persona.voice if persona else "",
            "awaiting_prose": "true",
            "note": "Synthetic corpus generated by Worldloom. Not a real company.",
        },
    )
