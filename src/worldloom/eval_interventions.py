"""Replayable demand events and constructive candidate orchestration.

Eval provenance is not an enterprise causal edge. Requirement/step IDs belong
in required_by; EnterpriseEvent.caused_by may only name actual world events.
Acceptance is still owned by the independent candidate validator.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .eval_demands import DemandSet, WorldDemand, compile_demands
from .eval_design import CandidatePlan, EvalSpec, design_digest
from .eval_tactics import TacticKind, TacticProposal
from .ids import content_key
from .models import EnterpriseEvent, Model
from .world import World

if TYPE_CHECKING:
    from .eval_candidates import GeneratedCandidate


def demand_event(demand: WorldDemand, *, occurred_at: datetime,
                 eval_spec_id: str = "unscoped", digest: str = "") -> EnterpriseEvent:
    """Project an obligation, retaining its owner and complete replay inputs."""
    payload = json.dumps({
        "schema": "eval-demand/v1", "eval_spec_id": eval_spec_id,
        "design_digest": digest, "demand_id": demand.id,
        "hard": demand.hard, "minimum": demand.minimum,
        "selector": demand.selector,
        "source_requirement_ids": demand.source_requirement_ids,
        "source_step_ids": demand.source_step_ids,
        "required_by": sorted((*demand.source_requirement_ids, *demand.source_step_ids)),
    }, sort_keys=True, separators=(",", ":"))
    return EnterpriseEvent(
        id=f"EV-DEMAND-{content_key(demand.kind.value, occurred_at.isoformat(), payload)[:20]}",
        kind=f"demand.{demand.kind.value}", occurred_at=occurred_at,
        summary=payload, caused_by=[],
    )


def demand_events(demands: DemandSet, *, occurred_at: datetime) -> tuple[EnterpriseEvent, ...]:
    return tuple(demand_event(demand, occurred_at=occurred_at,
                              eval_spec_id=demands.eval_spec_id, digest=demands.design_digest)
                 for demand in demands.demands)


def intervene(world: World, demands: DemandSet, *, occurred_at: datetime) -> World:
    """Record demands exactly once and save sufficient inputs for ordinary replay.

    Recording an obligation does not satisfy it. construct_candidate applies
    supported tactics and returns independent validation for the completed world.
    """
    from .recipe import with_step

    by_id = {event.id: event for event in world.events}
    additions: list[EnterpriseEvent] = []
    for event in demand_events(demands, occurred_at=occurred_at):
        previous = by_id.get(event.id)
        if previous is not None:
            if previous != event:
                raise ValueError(f"conflicting demand event: {event.id}")
        else:
            additions.append(event)
            by_id[event.id] = event
    if not additions:
        return world
    return replace(world, _events=(*world._events, *additions),
                   _recipe=with_step(world.recipe, "EvalDemands",
                                     demands=demands.model_dump(mode="json"),
                                     occurred_at=occurred_at.isoformat()))


class ConstructionFinding(Model):
    requirement_id: str
    code: str
    detail: str


@dataclass(frozen=True)
class ConstructionResult:
    candidate: GeneratedCandidate
    findings: tuple[ConstructionFinding, ...]
    applied_tactic_ids: tuple[str, ...]


def _default_clock(world: World) -> datetime:
    """When the constructions happen: after the last thing the world recorded.

    Derived from the world rather than read from a clock, so two constructions
    of the same candidate mint the same event ids. A world with no events has
    no timeline to be after; refusing is better than inventing an epoch.
    """

    from datetime import timedelta

    events = tuple(world.events)
    if not events:
        raise ValueError("cannot intervene on a world with no events; run an episode first")
    return max(event.occurred_at for event in events) + timedelta(hours=1)


def _step_demand_is_moot(world: World, demand: WorldDemand) -> bool:
    """Whether a step-derived demand has nothing left to construct.

    A step with no connector is abstract until the eval binds one, so there is
    no surface to mint a witness on; that is the design allowing abstract
    operations before binding, not a defect. A search step whose connector
    already holds a record of the entity is satisfiable as it stands.
    """

    from .eval_candidates import _connector_records
    from .eval_demands import DemandKind

    connector = demand.selector.get("connector")
    if not isinstance(connector, str) or not connector:
        return True
    if demand.kind is not DemandKind.SEARCH:
        return False
    entity = demand.selector.get("entity")
    try:
        records = _connector_records(world, connector)
    except ValueError:
        return False
    return any(entity is None or record.entity == entity for record in records)


def construct_candidate(spec: EvalSpec, plan: CandidatePlan, base: World, *,
                        occurred_at: datetime | None = None) -> ConstructionResult:
    """Make the base world satisfy the eval, one tactic per demand, then re-check.

    This is where the eval drives generation. The demand compiler says what
    must be true; each demand's tactic is executed through ``eval_witnesses``
    (witness records, preconditions, artifact families, access policies,
    events, revision chains), every construction is a recipe verb so the
    candidate replays, and the independent validator still has the last word:
    nothing here can accept its own output.

    A tactic that cannot run returns a finding naming the seam to use instead
    (a fact belongs to an episode, a lifecycle to a revision chain); it never
    stubs a record to make a check pass. A requirement that is already
    satisfied by the base world is left alone, so a vertical that happens to
    produce the state is preferred over a minted witness.
    """

    from .eval_candidates import (
        GeneratedCandidate,
        check_requirement,
        validate_candidate,
    )
    from .eval_tactics import proposal_for
    from .eval_witnesses import ConstructionRefused, executors

    if (plan.eval_spec_id != spec.id or plan.design_digest != design_digest(spec)
            or plan.requirements != spec.requirements or plan.seed != base.seed):
        raise ValueError("candidate plan, world and immutable eval design disagree")
    demands = compile_demands(spec)
    clock = occurred_at or _default_clock(base)
    world = intervene(base, demands, occurred_at=clock)
    events = {json.loads(event.summary)["demand_id"]: event.id
              for event in demand_events(demands, occurred_at=clock)}
    requirements = {requirement.id: requirement for requirement in spec.requirements}
    table = executors()
    findings: list[ConstructionFinding] = []
    applied: list[str] = []
    # Requirement-backed demands first: a step's search is satisfiable once the
    # requirement it reads has minted its witnesses, and the check below asks
    # the world, so order decides whether a bare witness gets minted for
    # nothing.
    ordered = sorted(demands.demands, key=lambda d: (not d.source_requirement_ids, d.id))
    for demand in ordered:
        sources = [requirements[rid] for rid in demand.source_requirement_ids if rid in requirements]
        if sources and all(check_requirement(r, world).satisfied for r in sources):
            continue
        if not sources and _step_demand_is_moot(world, demand):
            continue
        proposal = proposal_for(demand)
        requirement_kind = demand.selector.get("requirement_kind")
        if requirement_kind is not None:
            proposal = proposal.model_copy(update={
                "parameters": {**proposal.parameters, "requirement_kind": requirement_kind},
            })
        if proposal.kind is TacticKind.REVISION_FAMILY:
            parameters = dict(proposal.parameters)
            parameters.update(minimum=demand.minimum, source_event_id=events[demand.id])
            proposal = TacticProposal(
                id="tactic:revision:" + content_key(demands.design_digest, demand.id)[:20],
                kind=TacticKind.REVISION_FAMILY, covers=(demand.id,),
                cost=2 + demand.minimum, parameters=parameters,
            )
        executor = table.get(proposal.kind)
        owner = demand.source_requirement_ids[0] if demand.source_requirement_ids else demand.id
        if executor is None:
            findings.append(ConstructionFinding(requirement_id=owner,
                            code="unsupported_construction", detail=proposal.kind.value))
            continue
        try:
            world = executor(world, proposal, occurred_at=clock)
            applied.append(proposal.id)
        except (ConstructionRefused, ValueError) as error:
            findings.append(ConstructionFinding(requirement_id=owner,
                            code="construction_refused", detail=str(error)))
    validation = validate_candidate(plan, spec, world)
    return ConstructionResult(candidate=GeneratedCandidate(plan=plan, world=world, validation=validation),
                              findings=tuple(findings), applied_tactic_ids=tuple(applied))


@dataclass(frozen=True)
class EvalDemands:
    """The recipe verb behind ``intervene``.

    Same seam and same defect as ``eval_construction.EvalRevisionFamily``:
    ``intervene`` recorded a step no registry knew, so recording it was itself
    the failure (``unknown scenario 'EvalDemands'`` in
    ``tests/test_eval_interventions.py``). Stored arguments are exactly the
    JSON ``intervene`` wrote — the demand set's own dump and an ISO timestamp —
    so the class is its own builder, as ``messiness.Imperfections`` is.

    Replay re-records through ``intervene`` itself, whose exactly-once guard
    (an identical demand event already present is not appended again) is what
    makes a replayed step a no-op on the events while still restoring the
    recipe line.
    """

    demands: dict[str, Any]
    occurred_at: str
    physics: Any = None
    """Never read; carried for ``recipe._under``, see ``EvalRevisionFamily``."""

    def run(self, world: World) -> World:
        return intervene(
            world,
            DemandSet.model_validate(self.demands),
            occurred_at=datetime.fromisoformat(self.occurred_at),
        )


from . import recipe as _recipe

_recipe.register_step("EvalDemands", ("demands", "occurred_at"), EvalDemands)


__all__ = [
    "ConstructionFinding", "ConstructionResult", "EvalDemands", "construct_candidate",
    "demand_event", "demand_events", "intervene",
]
