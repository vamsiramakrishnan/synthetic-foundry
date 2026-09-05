"""Public eval-first SDK.

The surface is intentionally small::

    campaign = EvalCampaign(spec)
    instances = campaign.instantiate(builder)

The eval exists before ``builder`` is called.  Builders receive deterministic
candidate plans and Worldloom independently accepts or rejects the worlds they
return before binding gradeable instances.
"""

from __future__ import annotations

from dataclasses import dataclass

from .eval_candidates import CandidateBuilder, GeneratedCandidate, generate_candidates
from .eval_design import (
    CandidatePlan,
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    plan_candidates,
)
from .eval_instances import EvalInstance, bind_eval_instance


@dataclass(frozen=True)
class EvalCampaign:
    spec: EvalSpec

    def plans(self, *, count: int | None = None) -> tuple[CandidatePlan, ...]:
        """Candidate plans without generating any synthetic data."""

        return plan_candidates(self.spec, count=count)

    def candidates(
        self,
        builder: CandidateBuilder,
        *,
        count: int | None = None,
        keep_rejected: bool = False,
    ) -> tuple[GeneratedCandidate, ...]:
        """Generate and independently validate candidate worlds."""

        return generate_candidates(
            self.spec,
            builder,
            count=count,
            keep_rejected=keep_rejected,
        )

    def instantiate(
        self,
        builder: CandidateBuilder,
        *,
        count: int | None = None,
    ) -> tuple[EvalInstance, ...]:
        """Generate valid candidates and bind each one to its oracle."""

        return tuple(
            bind_eval_instance(self.spec, candidate)
            for candidate in self.candidates(builder, count=count)
        )


__all__ = [
    "CandidatePlan",
    "EvalCampaign",
    "EvalInstance",
    "EvalSpec",
    "EvalStepSpec",
    "RequirementKind",
    "WorldRequirement",
]
