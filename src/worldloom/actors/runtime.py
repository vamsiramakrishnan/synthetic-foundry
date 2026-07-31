"""The actor runtime.

One loop, and everything interesting is a constraint on it:

    activation → observation → invocation → action → tool stages → world

The world advances only through ``World.extend``, and only with ids an accepted
``ToolResult`` named. Between turns the actor's observation is re-projected, so
an actor's second decision is taken on what its first one actually changed
rather than on a snapshot from the top of the invocation.

**Replay.** Every decision is content-addressed into the generation ledger, keyed
on ``(seed, call site, turn, observation digest, actor model id, observation
version)`` — the same construction narration uses and for the same reason. A
world whose ledger is present regenerates without touching a provider: identical
observations produce identical keys, identical keys return identical actions, and
everything downstream of an action is arithmetic. That is why the replay test
hands the runtime ``UnreachableActorProvider`` and requires it never to be called.

**Bounds.** Turns per invocation, tool calls per invocation, and invocations per
episode. The last is the one that matters: an actor can wake another actor by
committing an event, so without a ceiling a routing mistake is an infinite loop
rather than a failed test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..ids import Minter, content_key
from ..models import GenerationLedgerEntry
from ..narrative import references
from . import observation as observation_module
from . import policy as policy_module
from . import scheduler
from .models import (
    ActorInvocation,
    ActorLedgerEntry,
    ActorMessage,
    ActorObservation,
    ActorTask,
    Observation,
    ToolResult,
    TriggerRoute,
)
from .providers import (
    OBSERVATION_VERSION,
    ActorProvider,
    ObservationView,
)
from .tools import base as tool_base

if TYPE_CHECKING:  # pragma: no cover
    from ..models import ArtifactIntent
    from ..world import World


#: How long one tool call takes. Constant, and short enough that a full
#: invocation fits comfortably inside its route's deadline.
TOOL_LATENCY = timedelta(minutes=4)

#: Ceiling on invocations in one episode. Far above what the retail-close
#: routing table produces (ten), and there to turn a routing cycle into a loud
#: failure rather than a hang.
MAX_INVOCATIONS = 64


class EpisodeError(Exception):
    """Raised when an episode cannot proceed."""


@dataclass(frozen=True)
class ActorEpisode:
    """Everything one episode produced."""

    world: World
    entries: tuple[ActorLedgerEntry, ...]
    observations: tuple[Observation, ...]
    messages: tuple[ActorMessage, ...]
    tasks: tuple[ActorTask, ...]
    generation_ledger: tuple[GenerationLedgerEntry, ...]
    provider_calls: int
    replayed: int
    rejected: int

    @property
    def accepted(self) -> tuple[ActorLedgerEntry, ...]:
        return tuple(entry for entry in self.entries if entry.result.accepted)

    def __repr__(self) -> str:
        return (
            f"ActorEpisode(invocations={len({e.invocation.id for e in self.entries})}, "
            f"calls={len(self.entries)}, accepted={len(self.accepted)}, "
            f"rejected={self.rejected}, replayed={self.replayed})"
        )


def _statement(world: World, fact_id: str, names: dict[str, str]) -> str:
    """A fact rendered the way an actor reads it.

    Reuses the narrative layer's describer rather than growing a second one.
    Two spellings of one fact is two documents that can disagree about it, and
    that argument does not stop being true because the reader is an actor.
    """
    fact = world.facts.by_id(fact_id)
    return references.describe(fact, names.get(fact.subject))


def _view(
    world: World,
    *,
    invocation: ActorInvocation,
    observed: ActorObservation,
    observations: tuple[Observation, ...],
    messages: tuple[ActorMessage, ...],
    tasks: tuple[ActorTask, ...],
    trigger_kind: str,
    period: str,
    turn: int,
    calls_used: int,
) -> ObservationView:
    """Render the observation into the payload an actor reads."""
    names = world.entity_names()
    person = world.people.by_id(invocation.actor_id)
    persona = world.personas.get(person.persona_id) if person.persona_id else None
    learned = {
        (o.observer_id, o.fact_id): o
        for o in observations
        if o.observer_id == invocation.actor_id
    }
    trigger_event = (
        world.events.get(observed.trigger_event_id) if observed.trigger_event_id else None
    )

    facts = []
    for fact_id in observed.visible_fact_ids:
        fact = world.facts.by_id(fact_id)
        record = learned[(invocation.actor_id, fact_id)]
        facts.append(
            {
                "id": fact.id,
                "kind": fact.kind,
                "subject": fact.subject,
                "subject_name": names.get(fact.subject, fact.subject),
                "statement": _statement(world, fact_id, names),
                "authority": fact.authority.value,
                "valid_from": fact.valid_from.isoformat(),
                "superseded": fact.is_superseded,
                "learned_at": record.learned_at.isoformat(),
                "learned_via": record.source_type,
                "confidence": record.confidence,
            }
        )

    by_id_message = {message.id: message for message in messages}
    by_id_task = {task.id: task for task in tasks}
    intents = {intent.id: intent for intent in world.artifact_intents}

    return ObservationView(
        invocation=invocation,
        actor_title=person.title,
        persona_voice=persona.voice if persona else "plain",
        period=period,
        trigger={
            "event_id": observed.trigger_event_id or "",
            "kind": trigger_kind,
            "summary": trigger_event.summary if trigger_event else "",
            "occurred_at": trigger_event.occurred_at.isoformat() if trigger_event else "",
        },
        facts=tuple(facts),
        messages=tuple(
            {
                "id": message_id,
                "kind": by_id_message[message_id].kind,
                "from": by_id_message[message_id].sender_id,
                "sent_at": by_id_message[message_id].sent_at.isoformat(),
                "text": by_id_message[message_id].text,
            }
            for message_id in observed.message_ids
            if message_id in by_id_message
        ),
        tasks=tuple(
            {
                "id": task_id,
                "kind": by_id_task[task_id].kind,
                "title": by_id_task[task_id].title,
                "state": by_id_task[task_id].state,
                "owner": by_id_task[task_id].owner_id or "",
                "mine": task_id in observed.obligation_ids,
            }
            for task_id in observed.task_ids
            if task_id in by_id_task
        ),
        artifacts=tuple(
            {
                "id": artifact_id,
                "artifact_type": intents[artifact_id].artifact_type,
                "audience": intents[artifact_id].audience,
                "mine": intents[artifact_id].author_id == invocation.actor_id,
            }
            for artifact_id in observed.visible_artifact_ids
            if artifact_id in intents
        ),
        entities=_public_entities(world, names),
        roles=_people_roles(world),
        resources=_resource_roles(world),
        turn=turn,
        calls_used=calls_used,
    )


def _public_entities(world: World, names: dict[str, str]) -> dict[str, str]:
    """The nouns an employee knows by working here.

    Company, divisions, systems, services. No values, no dates, no states — so
    this discloses nothing an evaluation could ask about, and without it an
    actor cannot name the service it is being paged about.
    """
    out = {world.company.id: world.company.name}
    for group in (world.business_units, world.systems, world.services):
        out.update({item.id: names.get(item.id, item.name) for item in group})
    return dict(sorted(out.items()))


def _people_roles(world: World) -> dict[str, str]:
    """Role key to job title, for roles naming a person."""
    return {
        key: world.people.by_id(value).title
        for key, value in sorted(world._roles.items())
        if world.people.get(value) is not None
    }


def _resource_roles(world: World) -> dict[str, str]:
    """Role key to entity id, for roles naming a system, service, or unit."""
    out = {"company": world.company.id}
    for key, value in sorted(world._roles.items()):
        if world.people.get(value) is not None:
            continue
        if (
            world.systems.get(value) is not None
            or world.services.get(value) is not None
            or world.business_units.get(value) is not None
        ):
            out[key] = value
    return out


def _visible_intents(
    world: World, *, actor_id: str, at: datetime
) -> list[str]:
    """Planned artifacts this actor may see, by the corpus's own access rules.

    Uses ``ArtifactIntent`` rather than the manifest because during an episode
    nothing has been rendered yet — the plan is what exists. An author always
    sees their own draft; everyone else goes through the access policy the
    audience resolves to, which is the same check ``World.visible_to`` applies
    once the artifact is real.
    """
    from ..documents import written_at

    person = world.people.by_id(actor_id)
    policies = {policy.id: policy for policy in world.access_policies}
    facts = {fact.id: fact for fact in world.facts}

    out: list[str] = []
    for intent in world.artifact_intents:
        try:
            created = written_at(intent, facts)
        except ValueError:
            # An intent whose facts this world cannot resolve has no date, so it
            # cannot be placed in time and must not be shown. Raised rather than
            # skipped anywhere else; here it means "not yet visible".
            continue
        if created > at:
            continue
        if intent.author_id == actor_id:
            out.append(intent.id)
            continue
        policy_id = world._policy_for(intent.audience)
        policy = policies.get(policy_id) if policy_id else None
        if policy is None or policy.permits(person):
            out.append(intent.id)
    return sorted(out)


def _ledger_key(
    *, seed: int, call_site: str, turn: int, digest: str, model_id: str
) -> str:
    """The content address of one actor decision.

    Every component earns its place, the same audit ``narrative.ledger_key``
    passes. Drop the digest and a corrected figure replays a decision taken on
    the old one; drop the observation version and changing what an actor is
    shown silently changes what a seed means; drop the turn and an invocation's
    second call collides with its first.
    """
    return content_key(seed, call_site, turn, digest, model_id, OBSERVATION_VERSION)


def _execute(
    action_tool: str,
    arguments: dict[str, Any],
    ctx: tool_base.ToolContext,
    *,
    seen: dict[str, ToolResult],
) -> tuple[ToolResult, str | None]:
    """Run the four stages. Returns the result and the idempotency key, if any."""
    try:
        tool = tool_base.get(action_tool)
        checked = tool.check_schema(arguments)
        tool.authorise(ctx)
        tool.validate(checked, ctx)
        key = tool.idempotency_key(checked, ctx)
        if key is not None and key in seen:
            # A repeat is accepted and changes nothing. Returning the first
            # result rather than a rejection is deliberate: the caller asked for
            # a state that already holds, and refusing would push a retry loop
            # into the actor for something that is not an error.
            return seen[key], key
        result = tool.run(checked, ctx)
    except tool_base.ToolRejection as rejection:
        return (
            ToolResult(accepted=False, rejection_reason=f"{rejection.code}: {rejection.detail}"),
            None,
        )
    return result, key


def run_episode(
    world: World,
    provider: ActorProvider,
    *,
    period: str,
    routes: tuple[TriggerRoute, ...] = scheduler.ROUTES,
    ledger: tuple[GenerationLedgerEntry, ...] = (),
    minter: Minter | None = None,
) -> ActorEpisode:
    """Run every activation this world's events warrant, in order.

    The world returned carries the episode's events, facts, and artifact intents.
    Observations, messages, tasks, and the execution ledger come back beside it —
    the caller decides whether to fold them into the corpus, because a scenario
    knows whether it is building one.
    """
    if world.seed is None:
        raise EpisodeError("an actor episode needs a seeded world")
    if minter is None and world._minter is None:
        raise EpisodeError(
            "this world was loaded from disk and cannot be advanced; build one from a seed"
        )
    mint = minter or world._minter
    assert mint is not None

    by_key = {entry.key: entry for entry in ledger}
    roles = dict(world._roles)

    observations: tuple[Observation, ...] = ()
    messages: tuple[ActorMessage, ...] = ()
    tasks: tuple[ActorTask, ...] = ()
    entries: list[ActorLedgerEntry] = []
    recorded: list[GenerationLedgerEntry] = []

    known: set[tuple[str, str]] = set()
    evidence: dict[str, set[str]] = {}
    processed: set[tuple[str, str]] = set()
    idempotent: dict[str, ToolResult] = {}
    provider_calls = replayed = rejected = 0
    sequence = 0
    clock: datetime | None = None

    for _ in range(MAX_INVOCATIONS):
        pending = [
            activation
            for activation in scheduler.queue(world, roles=roles, routes=routes)
            if activation.key not in processed
        ]
        if not pending:
            break
        activation = pending[0]
        processed.add(activation.key)

        policy = policy_module.policy_for(activation.role_key)
        if policy is None:  # pragma: no cover — the scheduler already filtered these
            continue

        # Monotonic. An invocation never starts before the previous one finished,
        # so an actor woken second cannot observe a moment its predecessor has
        # not reached yet. Without this the episode's causal order and its
        # timestamps disagree, and every temporal evaluation built on it is
        # quietly wrong.
        at = activation.at if clock is None else max(activation.at, clock)

        invocation = ActorInvocation(
            id=mint.next("INV"),
            actor_id=activation.actor_id,
            role_key=activation.role_key,
            observation_id="",
            trigger_event_id=activation.event_id,
            available_tools=[spec.name for spec in tool_base.catalogue(policy)],
            max_tool_calls=activation.max_tool_calls,
            max_turns=activation.max_turns,
            deadline=activation.deadline,
        )
        calls_used = 0

        for turn in range(activation.max_turns):
            if calls_used >= activation.max_tool_calls or at > activation.deadline:
                break

            fresh = observation_module.observations_for(
                world,
                actor_id=activation.actor_id,
                policy=policy,
                at=at,
                messages=messages,
                minter=mint,
                known=frozenset(known),
                triggered_by=frozenset({activation.event_id}),
            )
            observations += fresh
            known.update((o.observer_id, o.fact_id) for o in fresh)

            observed = observation_module.project(
                world,
                actor_id=activation.actor_id,
                role_key=activation.role_key,
                policy=policy,
                at=at,
                trigger_event_id=activation.event_id,
                observations=observations,
                messages=messages,
                tasks=tasks,
                minter=mint,
                artifact_ids=_visible_intents(world, actor_id=activation.actor_id, at=at),
            )
            invocation = invocation.model_copy(update={"observation_id": observed.id})

            view = _view(
                world,
                invocation=invocation,
                observed=observed,
                observations=observations,
                messages=messages,
                tasks=tasks,
                trigger_kind=activation.event_kind,
                period=period,
                turn=turn,
                calls_used=calls_used,
            )

            call_site = f"actor/{activation.event_id}/{activation.role_key}"
            key = _ledger_key(
                seed=world.seed,
                call_site=call_site,
                turn=turn,
                digest=view.digest(),
                model_id=provider.id,
            )
            existing = by_key.get(key)
            if existing is not None:
                from .models import ActorAction

                action = ActorAction.model_validate(existing.output)
                replayed += 1
                recorded.append(existing)
            else:
                action = provider.act(view, tool_base.catalogue(policy))
                provider_calls += 1
                recorded.append(
                    GenerationLedgerEntry(
                        id=mint.next("GEN"),
                        key=key,
                        call_site=call_site,
                        ordinal=turn,
                        world_seed=world.seed,
                        input_facts_digest=view.digest(),
                        model_id=provider.id,
                        prompt_version=OBSERVATION_VERSION,
                        output=action.model_dump(mode="json"),
                    )
                )

            if action.tool_name is None:
                entries.append(
                    ActorLedgerEntry(
                        id=mint.next("ALOG"),
                        key=key,
                        sequence=sequence,
                        invocation=invocation,
                        observation=observed,
                        action=action,
                        result=ToolResult(
                            accepted=False,
                            rejection_reason=f"abstained: {action.abstention_reason}",
                        ),
                        acted_at=at,
                    )
                )
                sequence += 1
                break

            ctx = tool_base.ToolContext(
                world=world,
                minter=mint,
                actor=world.people.by_id(activation.actor_id),
                role_key=activation.role_key,
                policy=policy,
                observation=observed,
                at=at,
                period=period,
                roles=roles,
                tasks=tasks,
                messages=messages,
                evidence=frozenset(evidence.get(activation.actor_id, set())),
            )
            result, idem = _execute(action.tool_name, dict(action.arguments), ctx, seen=idempotent)

            entries.append(
                ActorLedgerEntry(
                    id=mint.next("ALOG"),
                    key=key,
                    sequence=sequence,
                    invocation=invocation,
                    observation=observed,
                    action=action,
                    result=result,
                    acted_at=at,
                )
            )
            sequence += 1
            calls_used += 1

            if not result.accepted:
                rejected += 1
                # No state change, and — critically — no clock movement either.
                # A refused call cost the actor a turn, not four minutes of the
                # incident, and letting it move the clock would make a rejection
                # observable in every later timestamp.
                continue

            if idem is not None:
                idempotent.setdefault(idem, result)

            world, messages, tasks = _apply(world, ctx, messages, tasks)

            # An actor knows what it wrote. Recorded directly rather than
            # re-derived, because the channels in `observation.py` describe how
            # somebody learns what *others* did, and none of them describes
            # authorship.
            for fact_id in result.fact_ids:
                if (activation.actor_id, fact_id) in known:
                    continue
                observations += (
                    Observation(
                        id=mint.next("OBS"),
                        observer_id=activation.actor_id,
                        fact_id=fact_id,
                        learned_at=at,
                        source_type="participant",
                        source_id=None,
                        confidence=1.0,
                    ),
                )
                known.add((activation.actor_id, fact_id))

            granted = getattr(tool_base.get(action.tool_name), "grants_evidence", None)
            if granted:
                evidence.setdefault(activation.actor_id, set()).add(granted)

            at = at + TOOL_LATENCY

        clock = at

    return ActorEpisode(
        world=world,
        entries=tuple(entries),
        observations=observations,
        messages=messages,
        tasks=tasks,
        generation_ledger=tuple(recorded),
        provider_calls=provider_calls,
        replayed=replayed,
        rejected=rejected,
    )


def _apply(
    world: World,
    ctx: tool_base.ToolContext,
    messages: tuple[ActorMessage, ...],
    tasks: tuple[ActorTask, ...],
) -> tuple[World, tuple[ActorMessage, ...], tuple[ActorTask, ...]]:
    """Fold one accepted call's output into the world and the actor state.

    Tasks merge by id — an assignment replaces the obligation rather than
    creating a second one — which is the same rule ``World.extend`` uses for a
    person who leaves, and for the same reason: the thing is the same thing, only
    who is on the hook for it changed.
    """
    intents: tuple[ArtifactIntent, ...] = tuple(ctx.new_intents)
    advanced = world.extend(
        events=tuple(ctx.new_events),
        facts=tuple(ctx.new_facts),
        artifact_intents=intents,
    )
    updates = {task.id: task for task in ctx.new_tasks}
    merged = tuple(updates.pop(task.id, task) for task in tasks)
    merged += tuple(task for task in ctx.new_tasks if task.id in updates)
    return advanced, messages + tuple(ctx.new_messages), merged


__all__ = ["MAX_INVOCATIONS", "TOOL_LATENCY", "ActorEpisode", "EpisodeError", "run_episode"]
