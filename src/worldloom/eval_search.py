"""Adaptive candidate generation without moving the evaluator into the generator.

A normal ``CandidateBuilder`` sees one plan. An adaptive builder additionally
sees bounded feedback from earlier attempts: which requirements passed, which
failed, and the observed counts. It never receives authority to change the eval,
its hard predicates, or acceptance logic.

This is the harness seam for evolutionary generation. A model or search policy
can change the *next generation recipe* based on failures while Worldloom keeps
the evaluator sealed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .eval_candidates import (
    GeneratedCandidate,
    RequirementCheck,
    validate_candidate,
)
from .eval_design import CandidatePlan, EvalSpec, plan_candidates

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


@dataclass(frozen=True)
class CandidateFeedback:
    ordinal: int
    seed: int
    accepted: bool
    checks: tuple[RequirementCheck, ...]

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(check.requirement_id for check in self.checks if not check.satisfied)


@dataclass(frozen=True)
class CandidateContext:
    """What an adaptive generator may know when proposing the next world."""

    plan: CandidatePlan
    history: tuple[CandidateFeedback, ...]


AdaptiveCandidateBuilder = Callable[[CandidateContext], "World"]


def search_candidates(
    spec: EvalSpec,
    builder: AdaptiveCandidateBuilder,
    *,
    count: int | None = None,
) -> tuple[GeneratedCandidate, ...]:
    """Generate candidates sequentially, feeding only evaluator results forward."""

    attempts: list[GeneratedCandidate] = []
    feedback: list[CandidateFeedback] = []
    for plan in plan_candidates(spec, count=count):
        world = builder(CandidateContext(plan=plan, history=tuple(feedback)))
        validation = validate_candidate(plan, spec, world)
        candidate = GeneratedCandidate(plan=plan, world=world, validation=validation)
        attempts.append(candidate)
        feedback.append(
            CandidateFeedback(
                ordinal=plan.ordinal,
                seed=plan.seed,
                accepted=validation.accepted,
                checks=validation.checks,
            )
        )
    return tuple(attempts)


__all__ = [
    "AdaptiveCandidateBuilder",
    "CandidateContext",
    "CandidateFeedback",
    "search_candidates",
]
