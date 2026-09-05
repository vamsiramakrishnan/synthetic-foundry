"""Replayable eval-demand interventions.

A demand is not a second kind of world state. Once applied to a base world it is
an ordinary enterprise event with provenance back to the eval requirements that
caused it. Tactics may inspect these events to decide what minimal world changes
to make; independent validators still decide whether the resulting world passes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime

from .eval_demands import DemandSet, WorldDemand
from .ids import content_key
from .models import EnterpriseEvent
from .world import World


def _payload(demand: WorldDemand) -> str:
    return json.dumps(
        {
            "hard": demand.hard,
            "minimum": demand.minimum,
            "selector": demand.selector,
            "source_requirement_ids": demand.source_requirement_ids,
            "source_step_ids": demand.source_step_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def demand_event(demand: WorldDemand, *, occurred_at: datetime) -> EnterpriseEvent:
    """Materialize one constructive obligation as an append-only event."""

    required_by = tuple(sorted((*demand.source_requirement_ids, *demand.source_step_ids)))
    payload = _payload(demand)
    return EnterpriseEvent(
        id=f"event:demand:{content_key(demand.id, occurred_at.isoformat(), payload)[:20]}",
        kind=f"demand.{demand.kind.value}",
        occurred_at=occurred_at,
        summary=payload,
        caused_by=list(required_by),
    )


def demand_events(demands: DemandSet, *, occurred_at: datetime) -> tuple[EnterpriseEvent, ...]:
    """Deterministically project a normalized demand set into world history."""

    return tuple(demand_event(demand, occurred_at=occurred_at) for demand in demands.demands)


def intervene(world: World, demands: DemandSet, *, occurred_at: datetime) -> World:
    """Append eval-demand events to *world* without satisfying them implicitly.

    This is provenance, not a cheat path. The returned world still needs tactics
    and validation; simply appending a demand event cannot make its requirement
    pass.
    """

    events = demand_events(demands, occurred_at=occurred_at)
    return replace(world, _events=(*world._events, *events))


__all__ = ["demand_event", "demand_events", "intervene"]
