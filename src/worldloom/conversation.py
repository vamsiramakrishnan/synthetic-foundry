"""Conversations: an episode's third output, beside its facts and its artifacts.

The ontology in ``docs/next-phase-plan.md`` says an event mints facts and makes
artifacts necessary — *including people talking*. Until now only the second half
had a producer inside the episode path. `MonthEndClose` extended the world with
events, facts and artifact intents, and the question "who in this company knew
that, and when" had no answer unless you switched on the whole actor runtime and
let a provider decide the incident's records.

That is a large price for a small question, and it is the wrong shape besides:
who knew what is a property of the *episode*, not of who wrote its documents.
So this module derives the knowledge layer from what the deterministic episode
already produced — no provider, no tool calls, no decisions taken by anybody —
and the actor runtime keeps its own, richer job of deciding what gets written.

Two records come out, and they are the two the corpus models already had waiting:

``ActorMessage``
    One employee telling others something, and the facts that telling put in
    front of them. Derived, never invented: a message exists only where the
    episode already says somebody had to be told.

``Observation``
    One employee learning one fact at one moment, through one of the channels
    ``actors/observation.py`` describes. Derived by that module, unchanged — the
    channel model is the thing being reused, and a second copy of it here would
    be a second answer to "when did the CFO find out".

**Who has to be told, and by whom.** Two declared edges already answer it, and
neither was being read at build time:

1. ``scheduler.ROUTES`` — which roles an event wakes. Being paged about a
   failure is how the service desk finds out about it.
2. ``ArtifactIntent.triggered_by`` — which events made a document necessary.
   The author of that document has to know what the event established, or they
   are writing about something they never heard of.

The second is the one that matters, and it exposed a real defect: the planner
gives the group financial controller a working note citing the confirmed root
cause (an ``engineering`` fact their role cannot read) and gives the service
desk analyst an email thread citing the close status (a ``finance`` fact theirs
cannot). Both authors were, epistemically, writing about facts no channel could
ever deliver to them. A *briefing* — somebody who did know, telling them, before
the document's own date — is what the corpus was missing, and ``validate``'s
``author_cited_unobserved`` now fails a corpus that lacks one.

**Two passes and no more.** Briefings are chosen from the knowledge the routed
messages produce, and then the observation ledger is derived again with both.
One iteration is enough because a briefing only ever *adds* knowledge: a sender
who knew a fact in the first pass still knows it in the second, and an author
whose gap survives the second pass had no possible informant in either. That
last case is left to fail rather than papered over — it is the invariant doing
its job.

**Opt-in.** ``MonthEndClose(conversations=True)``. Every corpus built without it
is byte-for-byte what it was: nothing here runs, and ``World.export`` writes
``observations.jsonl`` and ``messages.jsonl`` only when they are non-empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .actors import observation as observation_module
from .actors import scheduler
from .actors.models import ActorMessage, Observation
from .actors.policy import policy_for
from .ids import Minter

if TYPE_CHECKING:  # pragma: no cover
    from .models import CanonicalFact
    from .world import World


#: How long after the last thing that happened the knowledge ledger is read off.
#:
#: The longest channel lag in ``actors/observation.py``, and derived from it
#: rather than typed in: the horizon has to be far enough out that every fact
#: which *can* reach somebody has, or the ledger would report an asymmetry that
#: is really just an early cut-off. A shorter horizon would make the last
#: figures of a close look like secrets.
SETTLING = observation_module.MAX_LAG


#: The routing table, with its preconditions dropped.
#:
#: ``scheduler.ROUTES`` gates most routes on ``incident_open``, which asks
#: whether an ``ops.incident_state`` fact exists — and that fact is minted by the
#: actor runtime's ``create_incident`` tool, so in a planner-driven episode it
#: never exists and eight of the nine routes are inert. The gate is right for an
#: actor episode, where the organisation genuinely might not have noticed. It is
#: wrong here, where the episode has *already* produced the incident record, the
#: RCA and the remediation tickets: the organisation demonstrably noticed, and
#: re-deciding that from a fact the planner does not mint would answer "no".
#:
#: A separate table rather than a change to ``_condition_holds``: teaching that
#: function to accept ``ops.incident_opened`` would make the condition true
#: before ``create_incident`` runs in an *actor* episode too, changing the queue
#: and with it every scripted-actor corpus ever built.
ROUTES: tuple[scheduler.TriggerRoute, ...] = tuple(
    route.model_copy(update={"required_conditions": []}) for route in scheduler.ROUTES
)


#: What kind of telling each event kind is. A closed vocabulary, matching
#: ``ActorMessage.kind``'s documented values — free text here would be a second
#: taxonomy nobody could join against.
_MESSAGE_KIND: dict[str, str] = {
    "pipeline_failed": "escalation",
    "incident_opened": "escalation",
    "hypothesis_recorded": "work_note",
    "hypothesis_superseded": "work_note",
    "root_cause_confirmed": "decision",
    "workaround_applied": "work_note",
    "valuation_available": "work_note",
    "close_dependency_raised": "escalation",
    "close_delayed": "escalation",
    "control_failure_identified": "decision",
    "remediation_created": "assignment",
    "close_finalised": "decision",
}


@dataclass(frozen=True)
class Conversation:
    """What an episode's people said, and what they came to know from it."""

    observations: tuple[Observation, ...]
    messages: tuple[ActorMessage, ...]

    def __repr__(self) -> str:
        observers = len({o.observer_id for o in self.observations})
        return (
            f"Conversation(observations={len(self.observations)}, observers={observers}, "
            f"messages={len(self.messages)})"
        )


@dataclass(frozen=True)
class _Draft:
    """A message before it has an id.

    Ids are minted after every draft exists, in chronological order, so a reader
    scanning ``messages.jsonl`` reads the episode forwards. Drafting first is
    what makes that possible without a second pass over a minted sequence.
    """

    sent_at: datetime
    kind: str
    sender_id: str
    recipient_ids: tuple[str, ...]
    subject_ref: str
    text: str
    disclosed_fact_ids: tuple[str, ...]

    @property
    def order(self) -> tuple[datetime, str, str, str]:
        return (self.sent_at, self.subject_ref, self.sender_id, self.recipient_ids[0])

    @property
    def signature(self) -> tuple[datetime, str, str, tuple[str, ...], tuple[str, ...]]:
        """What makes two drafts the same telling.

        Everything except the id and the text, so a second period re-deriving a
        first period's conversations recognises them and mints nothing. The id
        cannot be part of it — it is assigned after the comparison — and the text
        must not be, or a re-worded event summary would silently double every
        message in the corpus.
        """
        return (
            self.sent_at,
            self.sender_id,
            self.subject_ref,
            self.recipient_ids,
            self.disclosed_fact_ids,
        )


def _acting(world: World, roles: dict[str, str]) -> dict[str, str]:
    """Person id to role key, for the roles that are actors at all.

    A role with no ``ActorPolicy`` is not an actor — ``policy.policy_for`` says
    so, and substituting a permissive default would invent authority. The cost
    is that an artifact author outside this set has no knowledge ledger and so
    cannot be checked against one; that is a gap in the policy table, reported
    rather than hidden.
    """
    out: dict[str, str] = {}
    for role_key, person_id in sorted(roles.items()):
        if policy_for(role_key) is None or world.people.get(person_id) is None:
            continue
        # First role wins, and roles are walked in sorted order, so a person
        # holding two acting roles resolves the same way in every build.
        out.setdefault(person_id, role_key)
    return out


def _horizon(world: World) -> datetime:
    """When the knowledge ledger is read off: the last thing that happened, settled."""
    moments = [fact.valid_from for fact in world.facts]
    moments += [event.occurred_at for event in world.events]
    return max(moments) + SETTLING


def _employed(world: World, person_id: str, at: datetime) -> bool:
    person = world.people.get(person_id)
    if person is None:
        return False
    return not (
        (person.joined is not None and person.joined > at)
        or (person.left is not None and person.left <= at)
    )


def _routed(
    world: World,
    *,
    acting: dict[str, str],
    roles: dict[str, str],
    routes: tuple[scheduler.TriggerRoute, ...],
) -> tuple[list[_Draft], dict[str, frozenset[str]]]:
    """One message per event that woke somebody or made a document necessary.

    Returns the drafts and, beside them, which events woke which actor — the
    ``trigger`` channel's input, which is otherwise unrecoverable once the queue
    is discarded.
    """
    woken: dict[str, list[str]] = {}
    triggered: dict[str, list[str]] = {}
    for activation in scheduler.queue(world, roles=roles, routes=routes):
        woken.setdefault(activation.event_id, []).append(activation.actor_id)
        triggered.setdefault(activation.actor_id, []).append(activation.event_id)

    authors: dict[str, list[str]] = {}
    for intent in world.artifact_intents:
        for event_id in intent.triggered_by:
            authors.setdefault(event_id, []).append(intent.author_id)

    minted: dict[str, list[CanonicalFact]] = {}
    for fact in world.facts:
        if fact.event_id:
            minted.setdefault(fact.event_id, []).append(fact)

    drafts: list[_Draft] = []
    for event in sorted(world.events, key=lambda e: (e.occurred_at, e.id)):
        # An event with no human on it is not somebody talking. A pipeline
        # failing at 08:05 tells nobody anything; the analyst it pages learns of
        # it through the `trigger` channel, which is what being paged *is*.
        if not event.actors:
            continue
        sent_at = event.occurred_at + scheduler.REACTION
        sender = event.actors[0]
        if not _employed(world, sender, sent_at):
            continue
        candidates = sorted(
            {*woken.get(event.id, ()), *authors.get(event.id, ())} - {sender}
        )
        recipients = tuple(
            person for person in candidates
            if person in acting and _employed(world, person, sent_at)
        )
        disclosed = tuple(
            sorted(f.id for f in minted.get(event.id, ()) if f.valid_from <= sent_at)
        )
        # Both halves are load-bearing. No recipient is a monologue; no
        # disclosure is a message that moves no knowledge, which `ActorMessage`'s
        # own docstring says is not a message at all.
        if not recipients or not disclosed:
            continue
        drafts.append(
            _Draft(
                sent_at=sent_at,
                kind=_MESSAGE_KIND.get(event.kind, "work_note"),
                sender_id=sender,
                recipient_ids=recipients,
                subject_ref=event.id,
                text=event.summary,
                disclosed_fact_ids=disclosed,
            )
        )
    return drafts, {actor: frozenset(events) for actor, events in triggered.items()}


def _knowledge(observations: tuple[Observation, ...]) -> dict[tuple[str, str], datetime]:
    """``(observer, fact)`` to the earliest moment they had it."""
    out: dict[tuple[str, str], datetime] = {}
    for record in observations:
        key = (record.observer_id, record.fact_id)
        held = out.get(key)
        if held is None or record.learned_at < held:
            out[key] = record.learned_at
    return out


def _briefings(
    world: World,
    *,
    acting: dict[str, str],
    known: dict[tuple[str, str], datetime],
) -> list[_Draft]:
    """The conversations the document plan requires but no event produces.

    An author must have heard every fact their document cites, by the date the
    document carries. Where the channels cannot deliver one — because the fact
    belongs to a domain the author's role cannot read, and no event they were
    routed to carried it — somebody who *did* know it told them. The informant
    is the earliest holder who had it in time, which is derived rather than
    chosen; tie broken on person id.

    A gap with no possible informant is left open on purpose. It means no
    employee in the world knew the fact before the document citing it was
    written, and inventing a sender for that would be minting knowledge from
    nowhere. ``validate.actors`` fails it as ``author_cited_unobserved``.
    """
    from .documents import written_at

    facts = {fact.id: fact for fact in world.facts}
    holders: dict[str, list[tuple[datetime, str]]] = {}
    for (person, fact_id), at in known.items():
        holders.setdefault(fact_id, []).append((at, person))
    for entries in holders.values():
        entries.sort()

    # What a briefing has already put in front of somebody, so two documents
    # needing the same fact produce one conversation rather than two identical
    # ones a day apart.
    briefed: dict[tuple[str, str], datetime] = {}

    drafts: list[_Draft] = []
    for intent in sorted(world.artifact_intents, key=lambda i: i.id):
        if intent.author_id not in acting:
            continue
        try:
            deadline = written_at(intent, facts)
        except ValueError:
            # An intent whose facts this world cannot resolve has no date, so
            # nothing about it can be placed in time. Same reading the actor
            # runtime's visibility pass takes of the same failure.
            continue
        by_sender: dict[str, list[tuple[str, datetime]]] = {}
        for fact_id in sorted(intent.required_fact_ids):
            held = known.get((intent.author_id, fact_id))
            if held is not None and held <= deadline:
                continue
            already = briefed.get((intent.author_id, fact_id))
            if already is not None and already <= deadline:
                continue
            informant = next(
                (
                    (at, person)
                    for at, person in holders.get(fact_id, ())
                    if person != intent.author_id and at <= deadline
                ),
                None,
            )
            if informant is None:
                continue
            at, person = informant
            by_sender.setdefault(person, []).append((fact_id, at))
            briefed[(intent.author_id, fact_id)] = at
        for sender in sorted(by_sender):
            carried = by_sender[sender]
            drafts.append(
                _Draft(
                    # The moment the informant could first have said all of it.
                    # Later than any one fact reached them and no later than the
                    # document's own date, so the briefing sits inside the window
                    # where it could actually have happened.
                    sent_at=max(at for _, at in carried),
                    kind="work_note",
                    sender_id=sender,
                    recipient_ids=(intent.author_id,),
                    subject_ref=intent.id,
                    text=f"Briefed ahead of {intent.artifact_type}.",
                    disclosed_fact_ids=tuple(sorted(fact_id for fact_id, _ in carried)),
                )
            )
    return drafts


def _observe(
    world: World,
    *,
    acting: dict[str, str],
    triggered: dict[str, frozenset[str]],
    messages: tuple[ActorMessage, ...],
    at: datetime,
    minter: Minter,
    known: frozenset[tuple[str, str]],
) -> tuple[Observation, ...]:
    """Every actor's knowledge ledger at *at*, through the shipped channel model.

    ``known`` is what the corpus already records, so a second period appends only
    what is new rather than a second copy of everything the first one learned.
    """
    out: list[Observation] = []
    for person_id, role_key in sorted(acting.items(), key=lambda row: (row[1], row[0])):
        policy = policy_for(role_key)
        if policy is None:  # pragma: no cover — `_acting` already filtered these
            continue
        out += observation_module.observations_for(
            world,
            actor_id=person_id,
            policy=policy,
            at=at,
            messages=messages,
            minter=minter,
            known=known,
            triggered_by=triggered.get(person_id, frozenset()),
        )
    return tuple(out)


def _artifact_origins(
    world: World,
    *,
    acting: dict[str, str],
    minter: Minter,
    known: frozenset[tuple[str, str]],
) -> tuple[Observation, ...]:
    """The first artifact carrying an eventless fact is that fact's origin.

    Most facts have an event: its participants and routed messages establish
    who could know it. A deliberately eventless fact has no such source. A
    standing policy is brought into force by its signed policy document; a
    manager's held rating first exists in their one-to-one note; an offer's
    terms first exist in the offer record. The ordinary ``duty`` channel
    delivers those facts only after their originating record was written.

    This is not a blanket "authors know their documents" exception. For each
    eventless fact, only the earliest artifact that carries it is an origin.
    Every later author still needs duty, participation, a message, a readable
    artifact, or a briefing. Event-backed facts are never admitted here, so a
    missing route from an incident to its author remains visible.
    """
    from .documents import written_at

    facts = {fact.id: fact for fact in world.facts}
    first_carrier: dict[str, tuple[datetime, str]] = {}
    deadlines: dict[str, datetime] = {}
    for intent in sorted(world.artifact_intents, key=lambda item: item.id):
        try:
            deadline = written_at(intent, facts)
        except ValueError:
            continue
        deadlines[intent.id] = deadline
        for fact_id in intent.required_fact_ids:
            fact = facts.get(fact_id)
            if fact is None or fact.event_id is not None or fact.valid_from > deadline:
                continue
            candidate = (deadline, intent.id)
            first_carrier[fact_id] = min(
                candidate, first_carrier.get(fact_id, candidate)
            )

    out: list[Observation] = []
    for intent in sorted(world.artifact_intents, key=lambda item: item.id):
        if intent.author_id not in acting or intent.id not in deadlines:
            continue
        at = deadlines[intent.id]
        if not _employed(world, intent.author_id, at):
            continue
        for fact_id in sorted(intent.required_fact_ids):
            fact = facts.get(fact_id)
            if (
                fact is None
                or first_carrier.get(fact_id) != (at, intent.id)
                or (intent.author_id, fact_id) in known
            ):
                continue
            out.append(Observation(
                id=minter.next("OBS"),
                observer_id=intent.author_id,
                fact_id=fact_id,
                learned_at=at,
                source_type="artifact",
                source_id=intent.id,
                confidence=observation_module._CONFIDENCE["artifact"],
            ))
    return tuple(out)


def _message_sender_origins(
    world: World,
    *,
    messages: tuple[ActorMessage, ...],
    minter: Minter,
    known: frozenset[tuple[str, str]],
) -> tuple[Observation, ...]:
    """Record event participation for senders outside the actor-policy table.

    Workforce join events name the joiner as their participant. That person can
    truthfully tell their manager that they joined even when their new role has
    no ongoing ``ActorPolicy`` and therefore is not projected by ``_observe``.
    This origin is limited to facts minted by the message's subject event and a
    sender named on that event; it grants no duty or document visibility.
    """
    facts = {fact.id: fact for fact in world.facts}
    events = {event.id: event for event in world.events}
    out: list[Observation] = []
    pairs = set(known)
    for message in sorted(messages, key=lambda item: item.id):
        event = events.get(message.subject_ref or "")
        if event is None or message.sender_id not in event.actors:
            continue
        for fact_id in sorted(message.disclosed_fact_ids):
            fact = facts.get(fact_id)
            pair = (message.sender_id, fact_id)
            if fact is None or fact.event_id != event.id or pair in pairs:
                continue
            out.append(Observation(
                id=minter.next("OBS"),
                observer_id=message.sender_id,
                fact_id=fact_id,
                learned_at=fact.valid_from,
                source_type="participant",
                source_id=event.id,
                confidence=observation_module._CONFIDENCE["participant"],
            ))
            pairs.add(pair)
    return tuple(out)


def _attribute(
    observations: tuple[Observation, ...], messages: tuple[ActorMessage, ...]
) -> tuple[Observation, ...]:
    """Name the message behind every ``message``-channel observation.

    ``observation._channel`` records ``source_id=None`` for this one channel,
    which loses the half of the provenance that makes it worth having: "somebody
    told them" without saying who. Resolved here rather than in the channel
    function because that function's output is shipped in every scripted-actor
    corpus already built, and this is a new reading of it, not a change to it.

    The join is exact. The message channel has zero lag, so an observation made
    through it carries the sending moment as its ``learned_at``; the message is
    the one sent at that moment, to that person, carrying that fact. Where more
    than one qualifies the lowest id wins, so the attribution is stable.
    """
    index: dict[tuple[datetime, str, str], str] = {}
    for message in sorted(messages, key=lambda m: m.id, reverse=True):
        for person in (message.sender_id, *message.recipient_ids):
            for fact_id in message.disclosed_fact_ids:
                index[(message.sent_at, person, fact_id)] = message.id
    return tuple(
        record
        if record.source_type != "message"
        else record.model_copy(
            update={
                "source_id": index.get(
                    (record.learned_at, record.observer_id, record.fact_id)
                )
            }
        )
        for record in observations
    )


def derive(
    world: World,
    *,
    minter: Minter,
    roles: dict[str, str] | None = None,
    routes: tuple[scheduler.TriggerRoute, ...] = ROUTES,
    at: datetime | None = None,
) -> Conversation:
    """The knowledge layer of an episode already extended into *world*.

    Call this after the episode's events, facts and artifact intents are in the
    world and before its evaluation cases are generated: the questions in
    ``asymmetry.py`` read what comes back.

    ``roles`` defaults to the world's own role table, which is where it lives
    during a build. A corpus loaded from disk has none — role bindings are not
    exported — so a caller reading a finished corpus has to supply them.

    **Only what is new comes back.** A world that already carries observations
    and messages — the second close of a three-period corpus — contributes them
    as input to the channel model and gets back the difference, so the caller
    can hand the result straight to ``World.extend`` without minting a second
    account of the first period's knowledge.
    """
    bindings = dict(world._roles if roles is None else roles)
    acting = _acting(world, bindings)
    if not acting:
        return Conversation(observations=(), messages=())

    horizon = _horizon(world) if at is None else at
    held = tuple(world.messages)
    recorded = _knowledge(tuple(world.observations))
    known = frozenset(recorded)
    seen = {
        (m.sent_at, m.sender_id, m.subject_ref or "", tuple(m.recipient_ids),
         tuple(m.disclosed_fact_ids))
        for m in held
    }

    drafts, triggered = _routed(world, acting=acting, roles=bindings, routes=routes)
    drafts = [draft for draft in drafts if draft.signature not in seen]
    # Minted from a scratch sequence: this pass exists only to decide who needs
    # briefing, and its records are thrown away. Spending the world's minter on
    # them would put the id of a discarded observation into every later id, so
    # the corpus's numbering would depend on work that left no trace in it.
    scratch = Minter()
    scratch_messages = held + _mint(drafts, scratch)
    first_origins = _artifact_origins(
        world, acting=acting, minter=scratch, known=known
    )
    first_origins += _message_sender_origins(
        world, messages=scratch_messages, minter=scratch, known=known
    )
    first_known = known | frozenset(
        (record.observer_id, record.fact_id) for record in first_origins
    )
    first = first_origins + _observe(
        world, acting=acting, triggered=triggered,
        messages=scratch_messages, at=horizon, minter=scratch,
        known=first_known,
    )

    drafts += [
        draft
        for draft in _briefings(
            world, acting=acting, known={**recorded, **_knowledge(first)}
        )
        if draft.signature not in seen
    ]
    fresh = _mint(drafts, minter)
    messages = held + fresh
    origins = _artifact_origins(world, acting=acting, minter=minter, known=known)
    origins += _message_sender_origins(
        world, messages=messages, minter=minter, known=known
    )
    final_known = known | frozenset(
        (record.observer_id, record.fact_id) for record in origins
    )
    observations = _attribute(
        origins + _observe(
            world, acting=acting, triggered=triggered,
            messages=messages, at=horizon, minter=minter, known=final_known,
        ),
        messages,
    )
    return Conversation(observations=observations, messages=fresh)


@dataclass(frozen=True)
class ConversationRefresh:
    """Reconcile knowledge after later document-producing stages.

    A timeline runs its closes before the CLI appends hiring, review,
    distractor, and messiness records. Each close can only derive knowledge for
    documents that exist at that point. This explicit final stage makes the
    reconciliation part of the recipe, so rebuild performs the same derivation
    instead of relying on an unrecorded CLI side effect.
    """

    def run(self, world: World) -> World:
        from .recipe import with_step

        if world._minter is None:
            raise ValueError(
                "a knowledge refresh needs a build-time world; a loaded corpus"
                " has no deterministic minter"
            )
        if not world.observations and not world.messages:
            raise ValueError(
                "a knowledge refresh needs an existing conversation ledger;"
                " build an episode with conversations=True first"
            )
        fresh = derive(world, minter=world._minter)
        return world.extend(
            observations=fresh.observations,
            messages=fresh.messages,
            recipe=with_step(world._recipe, "ConversationRefresh"),
        )


def _mint(drafts: list[_Draft], minter: Minter) -> tuple[ActorMessage, ...]:
    """Turn drafts into messages, numbered in the order they were sent."""
    return tuple(
        ActorMessage(
            id=minter.next("MSG"),
            kind=draft.kind,
            sent_at=draft.sent_at,
            sender_id=draft.sender_id,
            recipient_ids=list(draft.recipient_ids),
            subject_ref=draft.subject_ref,
            text=draft.text,
            disclosed_fact_ids=list(draft.disclosed_fact_ids),
        )
        for draft in sorted(drafts, key=lambda d: d.order)
    )


__all__ = ["ROUTES", "SETTLING", "Conversation", "ConversationRefresh", "derive"]
