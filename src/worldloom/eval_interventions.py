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
from .eval_design import CandidatePlan, EvalSpec, RequirementKind, design_digest
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


def construct_candidate(spec: EvalSpec, plan: CandidatePlan, base: World, *,
                        occurred_at: datetime) -> ConstructionResult:
    """Use the base as-is where possible; construct missing revision witnesses.

    The revision tactic is implemented, not a promise that every proposed tactic
    has an executor. Other missing requirements return explicit findings and an
    independently rejected candidate. The eval and its acceptance rules never
    change to make an unsupported construction appear successful.
    """
    from .eval_candidates import (
        GeneratedCandidate,
        check_requirement,
        validate_candidate,
    )
    from .eval_construction import apply_revision_family

    if (plan.eval_spec_id != spec.id or plan.design_digest != design_digest(spec)
            or plan.requirements != spec.requirements or plan.seed != base.seed):
        raise ValueError("candidate plan, world and immutable eval design disagree")
    demands = compile_demands(spec)
    world = intervene(base, demands, occurred_at=occurred_at)
    events = {json.loads(event.summary)["demand_id"]: event.id
              for event in demand_events(demands, occurred_at=occurred_at)}
    findings: list[ConstructionFinding] = []
    applied: list[str] = []
    for requirement in spec.requirements:
        if check_requirement(requirement, world).satisfied:
            continue
        if requirement.kind is not RequirementKind.REVISION_CHAIN:
            findings.append(ConstructionFinding(requirement_id=requirement.id,
                            code="unsupported_construction", detail=requirement.kind.value))
            continue
        demand = next(d for d in demands.demands if requirement.id in d.source_requirement_ids)
        parameters = dict(requirement.selector)
        parameters.update(minimum=requirement.minimum, source_event_id=events[demand.id])
        proposal = TacticProposal(
            id="tactic:revision:" + content_key(demands.design_digest, demand.id)[:20],
            kind=TacticKind.REVISION_FAMILY, covers=(demand.id,),
            cost=2 + requirement.minimum, parameters=parameters,
        )
        try:
            world = apply_revision_family(world, proposal)
            applied.append(proposal.id)
        except ValueError as error:
            findings.append(ConstructionFinding(requirement_id=requirement.id,
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
