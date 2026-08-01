"""The event-driven scheduler.

Actors are not run in a loop. They are woken by committed events, which is the
difference between a simulation and a chat: an actor that can act because it is
its turn will always find something to say, and a corpus made of that is noise
with timestamps.

Routing is deterministic and stays that way. The roadmap allows for an LLM
director resolving genuinely ambiguous actor selection later; note that even then
it gets no mutation tools, because "who should look at this" is a routing
question and routing that can change the world is not routing.

Two properties this file is responsible for:

**The same world and seed produce the same queue.** Nothing here samples. Order is
(activation time, route declaration order, role key), and every tie is broken by
something written down rather than by dictionary order.

**No actor schedules itself.** An activation is identified by (event, role) and
each fires once. An actor can reach another actor — that is what
``close_dependency_raised`` is for — but only by committing an event, which is a
mutation and therefore already went through a tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .models import TriggerRoute
from .policy import policy_for

if TYPE_CHECKING:  # pragma: no cover
    from ..models import EnterpriseEvent
    from ..world import World


#: How long after an event its first responder gets to it, and the gap between
#: responders to the same event.
#:
#: Constants, for the same reason the observation lags are: a sampled reaction
#: time would make two builds of one seed disagree about the order two people
#: acted in, and the order is exactly what a temporal evaluation asks about.
REACTION = timedelta(minutes=12)
STAGGER = timedelta(minutes=9)


#: Named preconditions a route may require. Closed vocabulary, deliberately —
#: the same argument ``ConstraintKind`` makes about lore. A route may only
#: require something the scheduler knows how to check, and adding one means
#: teaching it, which is what stops routing rules from drifting into free text.
CONDITIONS: dict[str, str] = {
    "incident_open": "an incident state exists and is not resolved or closed",
    "close_at_risk": "the close is recorded as delayed or a dependency has been raised",
}


#: The retail-close routing table.
#:
#: Read top to bottom it is the episode from ``docs/actor-simulation.md`` §A5,
#: with one addition the roadmap's cast list does not have: the head of data
#: platform. A5 names six actors and none of them may approve a production
#: change, which would make §A2's second exit gate unprovable — an engineer
#: cannot be shown to be unable to approve their own change if nobody in the
#: episode can approve anything.
ROUTES: tuple[TriggerRoute, ...] = (
    TriggerRoute(
        event_kind="pipeline_failed",
        eligible_roles=["svc_desk"],
        max_actors=1,
        max_tool_calls=4,
        deadline_minutes=60,
    ),
    TriggerRoute(
        event_kind="incident_opened",
        # The engineer and the divisional finance business partner, who are
        # looking at the same failure and will not see the same thing.
        eligible_roles=["platform_senior", "*_bp"],
        required_conditions=["incident_open"],
        max_actors=2,
        max_tool_calls=4,
        deadline_minutes=180,
    ),
    TriggerRoute(
        event_kind="close_dependency_raised",
        eligible_roles=["controller"],
        required_conditions=["close_at_risk"],
        max_actors=1,
        max_tool_calls=3,
        deadline_minutes=240,
    ),
    TriggerRoute(
        event_kind="hypothesis_recorded",
        eligible_roles=["svc_incident"],
        required_conditions=["incident_open"],
        max_actors=1,
        max_tool_calls=3,
        deadline_minutes=180,
    ),
    TriggerRoute(
        event_kind="root_cause_confirmed",
        # The engineer first, then the analyst — order is the declaration order
        # in `eligible_roles`, and it matters here: the analyst's record of the
        # incident is only worth writing once engineering has said what it was,
        # and the runtime's monotonic clock guarantees the second actor starts
        # after the first has finished rather than merely later on paper.
        eligible_roles=["platform_senior", "svc_desk"],
        # Gated, like the two routes above it. The world's own
        # `root_cause_confirmed` event happens whether or not anybody noticed the
        # failure, so without this the engineer confirms a cause against a ticket
        # that was never raised — and the claim in this file's header, that a
        # world where the service desk abstained produces nothing downstream, is
        # false for the four routes that used to be unconditional.
        required_conditions=["incident_open"],
        max_actors=2,
        max_tool_calls=6,
        deadline_minutes=300,
    ),
    TriggerRoute(
        event_kind="close_delayed",
        eligible_roles=["controller"],
        required_conditions=["close_at_risk"],
        max_actors=1,
        max_tool_calls=4,
        deadline_minutes=480,
    ),
    TriggerRoute(
        event_kind="control_failure_identified",
        eligible_roles=["platform_lead"],
        required_conditions=["incident_open"],
        max_actors=1,
        max_tool_calls=3,
        deadline_minutes=480,
    ),
    TriggerRoute(
        event_kind="remediation_created",
        # The lead raises the work; the engineer writes the review. In that
        # order, because the review has to be able to cite the actions, and an
        # engineer woken first would produce an RCA with an empty Actions
        # section — which is the document's whole point missing.
        eligible_roles=["platform_lead", "platform_senior"],
        required_conditions=["incident_open"],
        max_actors=2,
        max_tool_calls=5,
        deadline_minutes=720,
    ),
    TriggerRoute(
        event_kind="close_finalised",
        # Deliberately ungated: a close finalises every period and the executive
        # committee is briefed on it whether or not anything went wrong. Gating
        # this one on an incident would mean a clean month produced no summary.
        eligible_roles=["cfo"],
        max_actors=1,
        max_tool_calls=3,
        deadline_minutes=1440,
    ),
)


@dataclass(frozen=True)
class Activation:
    """One actor woken by one event."""

    event_id: str
    event_kind: str
    role_key: str
    actor_id: str
    at: datetime
    max_tool_calls: int
    max_turns: int
    deadline: datetime
    order: int
    """Route declaration index. Part of the sort key, so two routes matching one
    event always fire in the order they are written rather than in whatever order
    the events happened to be scanned."""

    @property
    def key(self) -> tuple[str, str]:
        """What makes two activations the same. One firing per event per role."""
        return (self.event_id, self.role_key)


def _condition_holds(name: str, world: World, at: datetime) -> bool:
    """Whether a named precondition holds in *world* at *at*."""
    if name == "incident_open":
        states = [
            fact
            for fact in world.facts
            if fact.kind == "ops.incident_state" and fact.valid_from <= at
        ]
        # An incident that was never recorded is not open. This is what stops the
        # `incident_opened` route from waking anyone in a world where the service
        # desk abstained — the organisation did not notice, so nothing follows.
        if not states:
            return False
        return states[-1].text_value not in {"resolved", "closed"}
    if name == "close_at_risk":
        return any(
            fact.valid_from <= at
            and (
                fact.kind == "close.dependency"
                or (fact.kind == "close.status" and fact.text_value == "delayed")
            )
            for fact in world.facts
        )
    raise ValueError(f"unknown route condition {name!r}; add it to CONDITIONS first")


def _resolve_roles(tokens: list[str], roles: dict[str, str], limit: int) -> list[str]:
    """Turn route role tokens into concrete role keys.

    A token beginning with ``*`` matches by suffix, which is how a route names
    "the divisional finance business partner" in a world whose unit mix is an
    archetype decision. Matches are sorted, so the same archetype always picks
    the same partner.
    """
    out: list[str] = []
    for token in tokens:
        if token.startswith("*"):
            suffix = token[1:]
            out.extend(sorted(key for key in roles if key.endswith(suffix)))
        elif token in roles:
            out.append(token)
    # Deduplicated with order preserved: a route naming both `controller` and a
    # pattern that also matches it should wake them once.
    seen: dict[str, None] = {}
    for key in out:
        seen.setdefault(key, None)
    return list(seen)[:limit]


def queue(
    world: World,
    *,
    roles: dict[str, str],
    routes: tuple[TriggerRoute, ...] = ROUTES,
    events: tuple[EnterpriseEvent, ...] | None = None,
) -> tuple[Activation, ...]:
    """Every activation this world's events warrant, in the order they fire.

    Recomputed rather than accumulated, so an event committed by an accepted tool
    call is routed on the next pass without the caller having to notice. The
    runtime's ``processed`` set is what stops that from re-firing anything.
    """
    by_kind: dict[str, list[tuple[int, TriggerRoute]]] = {}
    for index, route in enumerate(routes):
        by_kind.setdefault(route.event_kind, []).append((index, route))

    out: list[Activation] = []
    for event in sorted(events if events is not None else tuple(world.events),
                        key=lambda e: (e.occurred_at, e.id)):
        for index, route in by_kind.get(event.kind, ()):
            at = event.occurred_at + REACTION
            if any(not _condition_holds(name, world, at) for name in route.required_conditions):
                continue
            for position, role_key in enumerate(
                _resolve_roles(route.eligible_roles, roles, route.max_actors)
            ):
                policy = policy_for(role_key)
                actor_id = roles.get(role_key)
                if policy is None or actor_id is None:
                    continue
                # Somebody who has left does not answer their pager. Checked here
                # rather than in the runtime so an activation never names an
                # actor who cannot legitimately act — the successor is woken by
                # the same route on the next period instead.
                person = world.people.get(actor_id)
                if person is None:
                    continue
                fires_at = at + STAGGER * position
                if person.left is not None and person.left <= fires_at:
                    continue
                if person.joined is not None and person.joined > fires_at:
                    continue
                out.append(
                    Activation(
                        event_id=event.id,
                        event_kind=event.kind,
                        role_key=role_key,
                        actor_id=actor_id,
                        at=fires_at,
                        max_tool_calls=route.max_tool_calls,
                        max_turns=route.max_tool_calls + 1,
                        deadline=fires_at + timedelta(minutes=route.deadline_minutes),
                        order=index,
                    )
                )
    return tuple(sorted(out, key=lambda a: (a.at, a.order, a.role_key, a.event_id)))


__all__ = ["CONDITIONS", "REACTION", "ROUTES", "STAGGER", "Activation", "queue"]
