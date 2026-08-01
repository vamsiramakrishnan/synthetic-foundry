"""Epistemic observations: who knew what, when, and how.

The canonical fact ledger says a thing became true at 08:15. It does not say the
CFO knew it at 08:15, and treating those as the same statement is the single
assumption that makes a multi-actor corpus worthless — every actor reasons from
the whole ledger, every document knows everything, and the questions worth asking
about an incident stop having answers.

So knowledge has its own ledger, derived rather than declared. A fact reaches an
employee through exactly one of five channels, and the channel decides both when
they learned it and how much the account is worth:

``participant``
    They were named on the event. Immediate, and worth full confidence — you
    cannot un-witness something.
``trigger``
    They were woken by the event, which is what being paged means: the
    scheduler routed this failure to this role, so the symptom arrives with the
    page. Immediate, and slightly below a participant's account, because being
    told to look at something is not the same as having been there.
``system_of_record``
    They own the system or service that recorded it. Near-immediate: the record
    is theirs, but somebody still has to look.
``message``
    Somebody told them. Arrives when the message was sent, and is worth less
    than seeing it yourself.
``artifact``
    They can read a document that cites it. Slowest, and cheapest — a figure
    read in someone else's memo is the weakest of the five.
``duty``
    Their role is responsible for the domain, so it reaches them eventually
    through the ordinary flow of work. This is the backstop, and it carries the
    longest lag on purpose: without it the world is unknowable, and with a short
    one every actor is omniscient within the hour and the asymmetry disappears.

The earliest channel that has actually delivered by the moment in question wins,
ties going to the more authoritative one. That ordering is why the data engineer
and the service desk analyst see genuinely different incidents at 08:20 while
both see the same one by the afternoon.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from ..ids import Minter
from .models import ActorMessage, ActorObservation, ActorTask, Observation
from .policy import ActorPolicy, domain_of

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact
    from ..world import World


#: How long each channel takes to deliver, and what an account through it is
#: worth. Constants rather than a distribution: a sampled delay would make two
#: builds of one seed disagree about who knew what, and the whole point of the
#: observation ledger is that it is checkable.
_CHANNELS: tuple[tuple[str, timedelta, float], ...] = (
    ("participant", timedelta(0), 1.0),
    ("trigger", timedelta(0), 0.9),
    ("system_of_record", timedelta(minutes=10), 0.95),
    ("message", timedelta(0), 0.75),
    ("artifact", timedelta(minutes=30), 0.6),
    ("duty", timedelta(hours=4), 0.8),
)

_LAG = {name: lag for name, lag, _ in _CHANNELS}
_CONFIDENCE = {name: confidence for name, _, confidence in _CHANNELS}
#: Preference order for breaking a tie on ``learned_at``. Earlier is better.
_PRECEDENCE = {name: index for index, (name, _, _) in enumerate(_CHANNELS)}


def _owned_by(world: World, actor_id: str) -> frozenset[str]:
    """Systems, services, and cost centres this employee owns.

    Ownership is what makes the ``system_of_record`` channel narrow enough to be
    interesting. The senior platform engineer owns the valuation service, so the
    feed's failure is on their screen before anyone tells them; the controller
    owns the ERP, so the ledger's position is. Neither has the other's.
    """
    return frozenset(
        item.id
        for group in (world.systems, world.services, world.cost_centres)
        for item in group
        if getattr(item, "owner_id", None) == actor_id
    )


def _channel(
    fact: CanonicalFact,
    *,
    policy: ActorPolicy,
    owned: frozenset[str],
    participated: frozenset[str],
    triggered_by: frozenset[str],
    disclosed: dict[str, datetime],
    readable_artifacts: dict[str, datetime],
    artifact_facts: dict[str, list[str]],
) -> tuple[str, datetime, str | None] | None:
    """The channel this actor learns *fact* through, and when.

    Returns ``None`` when no channel delivers it at all — which is the important
    case, and the reason this returns an option rather than a default. A fact
    nobody can reach is not a fact known late; it is one this employee never
    learns, and an actor must not be able to cite it.
    """
    candidates: list[tuple[int, datetime, str, str | None]] = []

    def offer(name: str, at: datetime, source: str | None) -> None:
        candidates.append((_PRECEDENCE[name], at + _LAG[name], name, source))

    if fact.event_id and fact.event_id in participated:
        offer("participant", fact.valid_from, fact.event_id)

    # Being paged about a failure is how the service desk finds out about it.
    # Without this channel an analyst woken by a pipeline failure cannot see the
    # failure — the duty channel would deliver it four hours later, which is a
    # world where nobody responds to an outage until lunchtime.
    if fact.event_id and fact.event_id in triggered_by:
        offer("trigger", fact.valid_from, fact.event_id)

    if (fact.source_system and fact.source_system in owned) or fact.subject in owned:
        offer("system_of_record", fact.valid_from, fact.source_system or fact.subject)

    if fact.id in disclosed:
        offer("message", disclosed[fact.id], None)

    # The two derived channels are gated on the role's readable domains. A
    # service desk analyst does not come to know the group's gross margin by
    # working here; they would have to be shown it.
    domain = domain_of(fact.kind)
    if domain in policy.readable_domains:
        for artifact_id, created_at in readable_artifacts.items():
            if fact.id in artifact_facts.get(artifact_id, ()):
                offer("artifact", created_at, artifact_id)
        offer("duty", fact.valid_from, None)

    if not candidates:
        return None
    # Earliest arrival wins; a tie goes to the more direct channel. Sorting on
    # (arrival, precedence) rather than the reverse matters: a message that
    # reaches someone at 09:00 beats a duty channel that would have got there at
    # noon, even though duty is the weaker account.
    _, at, name, source = min(candidates, key=lambda row: (row[1], row[0]))
    return name, at, source


def observations_for(
    world: World,
    *,
    actor_id: str,
    policy: ActorPolicy,
    at: datetime,
    messages: tuple[ActorMessage, ...] = (),
    minter: Minter | None = None,
    known: frozenset[tuple[str, str]] = frozenset(),
    triggered_by: frozenset[str] = frozenset(),
) -> tuple[Observation, ...]:
    """Every fact *actor_id* has learned by *at*, as observation records.

    ``known`` names ``(observer, fact)`` pairs already recorded, so a second
    projection of the same actor appends only what is new. Re-deriving is safe —
    the channel calculation is a pure function of the world — and appending
    rather than replacing is what keeps the ledger append-only.
    """
    mint = minter or Minter()
    person = world.people.get(actor_id)
    if person is None:
        return ()
    # Employment is checked first and hard. Somebody who has left the company
    # learns nothing further, and an artifact they are recorded as having
    # authored afterwards is precisely the defect `author_already_departed`
    # exists to catch — from the other end.
    if (person.joined is not None and person.joined > at) or (
        person.left is not None and person.left <= at
    ):
        return ()

    owned = _owned_by(world, actor_id)
    participated = frozenset(
        event.id for event in world.events if actor_id in event.actors
    )
    disclosed: dict[str, datetime] = {}
    for message in messages:
        if actor_id not in message.recipient_ids and message.sender_id != actor_id:
            continue
        for fact_id in message.disclosed_fact_ids:
            existing = disclosed.get(fact_id)
            if existing is None or message.sent_at < existing:
                disclosed[fact_id] = message.sent_at

    readable_artifacts: dict[str, datetime] = {}
    artifact_facts: dict[str, list[str]] = {}
    for artifact in world.visible_to(actor_id):
        if artifact.created_at <= at:
            readable_artifacts[artifact.id] = artifact.created_at
            artifact_facts[artifact.id] = list(artifact.supporting_fact_ids)

    out: list[Observation] = []
    for fact in world.facts:
        if fact.valid_from > at or (actor_id, fact.id) in known:
            continue
        resolved = _channel(
            fact,
            policy=policy,
            owned=owned,
            participated=participated,
            triggered_by=triggered_by,
            disclosed=disclosed,
            readable_artifacts=readable_artifacts,
            artifact_facts=artifact_facts,
        )
        if resolved is None:
            continue
        source_type, learned_at, source_id = resolved
        if learned_at > at:
            continue
        out.append(
            Observation(
                id=mint.next("OBS"),
                observer_id=actor_id,
                fact_id=fact.id,
                learned_at=learned_at,
                source_type=source_type,
                source_id=source_id,
                confidence=_CONFIDENCE[source_type],
            )
        )
    return tuple(out)


def project(
    world: World,
    *,
    actor_id: str,
    role_key: str,
    policy: ActorPolicy,
    at: datetime,
    trigger_event_id: str | None,
    observations: tuple[Observation, ...],
    messages: tuple[ActorMessage, ...],
    tasks: tuple[ActorTask, ...],
    minter: Minter,
    artifact_ids: list[str] | None = None,
) -> ActorObservation:
    """The bounded view handed to one actor at one moment.

    Ids only. Everything an actor reads is built from this, so a tool argument
    naming a fact absent from ``visible_fact_ids`` is a citation of something the
    actor never saw — which the runtime rejects rather than quietly allows.
    """
    mine = [o for o in observations if o.observer_id == actor_id and o.learned_at <= at]
    visible_facts = sorted({o.fact_id for o in mine})

    # Rendered artifacts when the corpus has them, and the *plan* when it does
    # not. During an episode nothing has been compiled yet, so the caller passes
    # the intents this actor may see; falling back to the manifest keeps this
    # usable for asking what somebody could read from a finished corpus.
    visible_artifacts = (
        sorted(artifact_ids)
        if artifact_ids is not None
        else sorted(
            artifact.id for artifact in world.visible_to(actor_id) if artifact.created_at <= at
        )
    )
    my_messages = sorted(
        message.id
        for message in messages
        if message.sent_at <= at
        and (actor_id in message.recipient_ids or message.sender_id == actor_id)
    )
    # Tasks are visible within the writable domain the role owns, and *owned*
    # only when the actor is named. The distinction is what an actor deciding
    # what to do next actually needs: seeing a ticket is not being on the hook
    # for it.
    my_tasks = sorted(
        task.id
        for task in tasks
        if task.created_at <= at
        and (
            task.owner_id == actor_id
            or task.created_by == actor_id
            or task.domain in policy.readable_domains
        )
    )
    obligations = sorted(
        task.id for task in tasks if task.owner_id == actor_id and task.created_at <= at
    )

    return ActorObservation(
        id=minter.next("AOBS"),
        actor_id=actor_id,
        role_key=role_key,
        observed_at=at,
        trigger_event_id=trigger_event_id,
        visible_fact_ids=visible_facts,
        visible_artifact_ids=visible_artifacts,
        message_ids=my_messages,
        task_ids=my_tasks,
        obligation_ids=obligations,
    )


__all__ = ["observations_for", "project"]
