"""Public eval-first SDK.

The surface is intentionally small::

    campaign = EvalCampaign(spec)
    run = campaign.run(builder)
    instances = run.instances

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
class CampaignRun:
    """All attempts for one eval design, including candidates that failed.

    Rejected worlds are search feedback. Dropping them would force an
    evolutionary builder to rediscover why a region of candidate space is
    invalid. They remain ordinary generated worlds; only accepted attempts bind
    into gradeable eval instances.
    """

    spec: EvalSpec
    attempts: tuple[GeneratedCandidate, ...]
    instances: tuple[EvalInstance, ...]

    @property
    def accepted(self) -> tuple[GeneratedCandidate, ...]:
        return tuple(candidate for candidate in self.attempts if candidate.validation.accepted)

    @property
    def rejected(self) -> tuple[GeneratedCandidate, ...]:
        return tuple(candidate for candidate in self.attempts if not candidate.validation.accepted)

    @property
    def failed_requirements(self) -> dict[int, tuple[str, ...]]:
        """Hard predicate failures by candidate ordinal."""

        hard = {requirement.id for requirement in self.spec.requirements if requirement.hard}
        return {
            candidate.plan.ordinal: tuple(
                check.requirement_id
                for check in candidate.validation.checks
                if check.requirement_id in hard and not check.satisfied
            )
            for candidate in self.rejected
        }

    def diverse(self, count: int) -> tuple[GeneratedCandidate, ...]:
        """Select valid candidates that are far apart in measured corpus outcomes.

        Validity always happens first. The selector is Worldloom's existing
        outcome-space max-min traversal; this layer does not introduce a second
        diversity objective or optimize against a particular retriever.
        """

        accepted = self.accepted
        if count < 1:
            raise ValueError("diverse candidate count must be at least one")
        if count > len(accepted):
            raise ValueError(f"cannot select {count} from {len(accepted)} accepted candidates")

        from . import outcomes

        readings = tuple(
            outcomes.read(
                candidate.world.compile(),
                name=f"candidate-{candidate.plan.ordinal:04d}",
                seed=candidate.plan.seed,
            )
            for candidate in accepted
        )
        chosen = outcomes.select(readings, count)
        return tuple(accepted[index] for index in chosen)


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

    def run(
        self,
        builder: CandidateBuilder,
        *,
        count: int | None = None,
    ) -> CampaignRun:
        """Generate every attempt and retain failures for candidate search."""

        attempts = self.candidates(builder, count=count, keep_rejected=True)
        accepted = tuple(candidate for candidate in attempts if candidate.validation.accepted)
        instances = tuple(bind_eval_instance(self.spec, candidate) for candidate in accepted)
        return CampaignRun(spec=self.spec, attempts=attempts, instances=instances)

    def instantiate(
        self,
        builder: CandidateBuilder,
        *,
        count: int | None = None,
    ) -> tuple[EvalInstance, ...]:
        """Generate valid candidates and bind each one to its oracle."""

        return self.run(builder, count=count).instances

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
        that export without changing the oracle or candidate seed. Rejected
        attempts are recorded in the manifest as search diagnostics but their
        corpora are not exported by default.
        """

        root = Path(out)
        if root.exists() and any(root.iterdir()) and not overwrite:
            raise FileExistsError(f"evaluation campaign destination is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)

        run = self.run(builder, count=count)
        write_json(root / "eval-spec.json", self.spec.model_dump(mode="json"))

        manifest_candidates: list[dict[str, Any]] = []
        instance_by_seed = {instance.candidate_seed: instance for instance in run.instances}
        for candidate in run.accepted:
            instance = instance_by_seed[candidate.plan.seed]
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
                "design_digest": run.attempts[0].plan.design_digest if run.attempts else "",
                "attempt_count": len(run.attempts),
                "candidate_count": len(run.accepted),
                "rejected_count": len(run.rejected),
                "failed_requirements": {
                    str(ordinal): list(requirements)
                    for ordinal, requirements in run.failed_requirements.items()
                },
                "candidates": manifest_candidates,
            },
        )
        return root


__all__ = [
    "CampaignRun",
    "CandidatePlan",
    "EvalCampaign",
    "EvalInstance",
    "EvalSpec",
    "EvalStepSpec",
    "RequirementKind",
    "WorldRequirement",
]
