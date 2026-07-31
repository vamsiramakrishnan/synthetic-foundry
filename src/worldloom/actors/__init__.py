"""Actors: bounded employees acting on the world through typed tools.

The one sentence this package exists to make true:

    Only successful tool execution changes the world.

An actor observes a *projection* of the world scoped to one employee at one
moment, chooses among the tools its role grants it, and the runtime decides
whether that choice is legal and what it changes. Dialogue, reasoning, and model
output change nothing. See ``docs/actor-simulation.md``.

What actors never own is the shorter and more important list: stable IDs, the
clock, arithmetic, permission resolution, and — the one that keeps being
tempting — *what actually happened*. The inventory pipeline failed because the
deterministic operational generator decided it failed, and the hierarchy mapping
was stale because the world's lore made it stale. An actor that could choose the
root cause would be authoring canonical truth, which is exactly the thing this
design exists to prevent. What an actor chooses is when the organisation finds
out, who records it, what is done about it, and what gets written down.
"""

from __future__ import annotations

from .models import (
    ActorAction,
    ActorInvocation,
    ActorLedgerEntry,
    ActorMessage,
    ActorObservation,
    ActorPolicy,
    ActorTask,
    DecisionRight,
    Observation,
    ToolResult,
    TriggerRoute,
)
from .providers import (
    ActorProvider,
    ActorProviderError,
    ObservationView,
    ScriptedActorProvider,
    TranscriptActorProvider,
    UnreachableActorProvider,
)
from .runtime import ActorEpisode, EpisodeError, run_episode

__all__ = [
    "ActorAction",
    "ActorEpisode",
    "ActorInvocation",
    "ActorLedgerEntry",
    "ActorMessage",
    "ActorObservation",
    "ActorPolicy",
    "ActorProvider",
    "ActorProviderError",
    "ActorTask",
    "DecisionRight",
    "EpisodeError",
    "Observation",
    "ObservationView",
    "ScriptedActorProvider",
    "ToolResult",
    "TranscriptActorProvider",
    "TriggerRoute",
    "UnreachableActorProvider",
    "run_episode",
]
