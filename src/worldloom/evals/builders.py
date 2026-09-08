"""Adapt the existing company and pipeline contracts to candidate generation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..eval_candidates import CandidateBuilder
    from ..pipeline import Pipeline
    from ..sdk import Blueprint


def candidate_builder(blueprint: Blueprint, pipeline: Pipeline) -> CandidateBuilder:
    """Build each candidate with its planned seed and the company's own stages.

    The pipeline may end at ``Built`` or ``World``. Export is a later operation:
    accepting a path here would sever the candidate from the state independently
    validated and bound to its oracle. Stages that change generation must record
    those changes in the World's recipe, as they do outside a campaign.

    No build occurs until the returned callable receives a candidate plan.
    """

    from ..eval_design import CandidatePlan
    from ..pipeline import StageContext
    from ..sdk import Built
    from ..world import World

    def build(plan: CandidatePlan) -> World:
        run = pipeline.run(
            blueprint.seeded(plan.seed), context=StageContext(seed=plan.seed)
        )
        world = run.value.world if isinstance(run.value, Built) else run.value
        if not isinstance(world, World):
            raise TypeError("candidate pipeline must produce a Built or World before export")
        if world.seed != plan.seed:
            raise ValueError("candidate pipeline changed the planned seed")
        return world

    return build


__all__ = ["candidate_builder"]
