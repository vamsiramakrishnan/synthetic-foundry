"""Public eval-first SDK.

The surface is intentionally small::

    campaign = EvalCampaign(spec)
    instances = campaign.instantiate(builder)

The eval exists before ``builder`` is called. Builders receive deterministic
candidate plans and Worldloom independently accepts or rejects the worlds they
return before binding gradeable instances.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .corpus import write_json
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

    def export(
        self,
        builder: CandidateBuilder,
        out: str | Path,
        *,
        count: int | None = None,
        formats: tuple[str, ...] = (),
        overwrite: bool = False,
    ) -> Path:
        """Write evals and the exact synthetic corpora that make them valid.

        The envelope is intentionally thin. Each accepted candidate is exported
        through ``World.export``; Worldloom does not invent a second corpus
        format for evaluations. Optional *formats* render native artifacts before
        that export without changing the oracle or candidate seed.
        """

        root = Path(out)
        if root.exists() and any(root.iterdir()) and not overwrite:
            raise FileExistsError(f"evaluation campaign destination is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)

        candidates = self.candidates(builder, count=count)
        instances = tuple(bind_eval_instance(self.spec, candidate) for candidate in candidates)
        write_json(root / "eval-spec.json", self.spec.model_dump(mode="json"))

        manifest_candidates: list[dict[str, Any]] = []
        for candidate, instance in zip(candidates, instances, strict=True):
            name = f"{candidate.plan.ordinal:04d}-{candidate.plan.seed}"
            candidate_dir = root / "candidates" / name
            corpus_dir = candidate_dir / "corpus"
            world = candidate.world.render(*formats) if formats else candidate.world
            world.export(corpus_dir, overwrite=overwrite)
            write_json(candidate_dir / "eval-instance.json", instance.model_dump(mode="json"))
            write_json(
                candidate_dir / "candidate-validation.json",
                candidate.validation.model_dump(mode="json"),
            )
            manifest_candidates.append(
                {
                    "ordinal": candidate.plan.ordinal,
                    "seed": candidate.plan.seed,
                    "eval_instance_id": instance.id,
                    "path": candidate_dir.relative_to(root).as_posix(),
                }
            )

        write_json(
            root / "manifest.json",
            {
                "schema": "worldloom.eval-campaign/v1",
                "eval_spec_id": self.spec.id,
                "design_digest": candidates[0].plan.design_digest if candidates else "",
                "candidate_count": len(candidates),
                "candidates": manifest_candidates,
            },
        )
        return root


__all__ = [
    "CandidatePlan",
    "EvalCampaign",
    "EvalInstance",
    "EvalSpec",
    "EvalStepSpec",
    "RequirementKind",
    "WorldRequirement",
]
