"""Public eval-first campaign orchestration.

The eval exists before candidate data. Builders receive deterministic plans and
Worldloom independently accepts/rejects their worlds before binding gradeable
instances. This module owns campaign orchestration; individual compile,
validation, tactic, execution and export stages remain small implementation
modules during the compatibility release.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..corpus import write_json
from ..eval_candidates import CandidateBuilder, GeneratedCandidate, generate_candidates
from ..eval_demands import DemandSet, compile_demands
from ..eval_design import CandidatePlan, EvalSpec, plan_candidates
from ..eval_instances import EvalInstance, bind_eval_instance
from ..eval_interventions import ConstructionResult
from ..eval_tactics import TacticPlan, plan_tactics

if TYPE_CHECKING:  # pragma: no cover
    from ..eval_reference import ExecutionProof, StepExecutor
    from ..eval_search import AdaptiveCandidateBuilder
    from ..world import World


@dataclass(frozen=True)
class CampaignRun:
    """Every candidate attempt for one immutable eval design."""

    spec: EvalSpec
    attempts: tuple[GeneratedCandidate, ...]
    instances: tuple[EvalInstance, ...]
    constructions: tuple[ConstructionResult, ...] = ()
    """Per attempt, what the constructive layer did and what it refused.

    Empty when the run used a plain builder. A refused construction is the
    reason a candidate was rejected, in the words of the seam that should have
    produced the state, which is what a harness needs to act on.
    """
    selected_ordinals: tuple[int, ...] | None = None
    """An explicit output selection; None retains every accepted attempt."""

    @property
    def accepted(self) -> tuple[GeneratedCandidate, ...]:
        return tuple(
            candidate for candidate in self.attempts if candidate.validation.accepted
        )

    @property
    def rejected(self) -> tuple[GeneratedCandidate, ...]:
        return tuple(
            candidate
            for candidate in self.attempts
            if not candidate.validation.accepted
        )

    @property
    def selected(self) -> tuple[GeneratedCandidate, ...]:
        """Accepted attempts eligible for output after any explicit selection."""

        if self.selected_ordinals is None:
            return self.accepted
        chosen = set(self.selected_ordinals)
        return tuple(candidate for candidate in self.accepted if candidate.plan.ordinal in chosen)

    @property
    def failed_requirements(self) -> dict[int, tuple[str, ...]]:
        hard = {
            requirement.id
            for requirement in self.spec.requirements
            if requirement.hard
        }
        return {
            candidate.plan.ordinal: tuple(
                check.requirement_id
                for check in candidate.validation.checks
                if check.requirement_id in hard and not check.satisfied
            ) + tuple(
                check.requirement_id
                for check in candidate.validation.shape_checks
                if not check.satisfied
            )
            for candidate in self.rejected
        }

    def diverse(self, count: int) -> tuple[GeneratedCandidate, ...]:
        """Select valid candidates far apart in measured corpus outcome space."""

        accepted = self.accepted
        if count < 1:
            raise ValueError("diverse candidate count must be at least one")
        if count > len(accepted):
            raise ValueError(
                f"cannot select {count} from {len(accepted)} accepted candidates"
            )

        from .. import outcomes

        readings = tuple(
            outcomes.read(
                candidate.world if candidate.world.artifact_irs else candidate.world.compile(),
                name=f"candidate-{candidate.plan.ordinal:04d}",
                seed=candidate.plan.seed,
            )
            for candidate in accepted
        )
        chosen = outcomes.select(readings, count)
        return tuple(accepted[index] for index in chosen)

    def select(self, count: int) -> CampaignRun:
        """Choose diverse accepted outputs while retaining every attempt for audit."""

        candidates = self.diverse(count)
        return replace(
            self,
            selected_ordinals=tuple(candidate.plan.ordinal for candidate in candidates),
            instances=tuple(bind_eval_instance(self.spec, candidate) for candidate in candidates),
        )

    def map_worlds(self, transform: Callable[[World], World]) -> CampaignRun:
        """Transform every attempt, then independently validate and rebind it.

        Narration, rendering and noise can change what evidence exists. A
        prior acceptance and its oracle cannot survive such a change by fiat.
        Rejected attempts remain available to the transform and in the result,
        and constructive provenance continues to describe the same attempt.
        """

        from ..eval_candidates import validate_candidate

        attempts: list[GeneratedCandidate] = []
        for candidate in self.attempts:
            world = transform(candidate.world)
            attempts.append(GeneratedCandidate(
                plan=candidate.plan,
                world=world,
                validation=validate_candidate(candidate.plan, self.spec, world),
            ))
        by_ordinal = {candidate.plan.ordinal: candidate for candidate in attempts}
        constructions = tuple(
            replace(result, candidate=by_ordinal[result.candidate.plan.ordinal])
            for result in self.constructions
        )
        instances = tuple(
            bind_eval_instance(self.spec, candidate)
            for candidate in attempts if candidate.validation.accepted
            and (self.selected_ordinals is None or candidate.plan.ordinal in self.selected_ordinals)
        )
        return CampaignRun(
            spec=self.spec, attempts=tuple(attempts), instances=instances,
            constructions=constructions, selected_ordinals=self.selected_ordinals,
        )

    def prove(self, executor: StepExecutor) -> tuple[ExecutionProof, ...]:
        """Execute accepted instances against their exact worlds without rebuilding."""

        from ..eval_reference import execute_reference

        instance_by_seed = {
            instance.candidate_seed: instance for instance in self.instances
        }
        return tuple(
            execute_reference(
                instance_by_seed[candidate.plan.seed], candidate.world, executor
            )
            for candidate in self.selected
        )

    def export(
        self,
        out: str | Path,
        *,
        formats: tuple[str, ...] = (),
        overwrite: bool = False,
    ) -> Path:
        """Export this run's final worlds and their independently bound instances.

        Rendering is a world transformation too. When formats are requested,
        revalidate and rebind the rendered worlds before writing the matching
        corpora; no builder or constructive tactic is run a second time.
        """

        run = self.map_worlds(lambda world: world.render(*formats)) if formats else self
        root = Path(out)
        if root.exists() and any(root.iterdir()):
            if not overwrite:
                raise FileExistsError(
                    f"evaluation campaign destination is not empty: {root}"
                )
            # Replace means replace: a rerun with fewer candidates must not
            # leave last run's directories beside this run's manifest for a
            # consumer enumerating `candidates/` to find. Only a directory
            # that is a campaign is cleared; anything else is refused rather
            # than deleted on the strength of a flag.
            manifest = root / "manifest.json"
            try:
                schema = json.loads(manifest.read_text(encoding="utf-8")).get("schema")
            except (OSError, ValueError):
                schema = None
            if schema != "worldloom.eval-campaign/v1":
                raise FileExistsError(
                    f"{root} is not an evaluation campaign directory; refusing to overwrite it"
                )
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)

        demands = compile_demands(self.spec)
        tactics = plan_tactics(demands)
        write_json(root / "eval-spec.json", self.spec.model_dump(mode="json"))
        write_json(root / "demand-set.json", demands.model_dump(mode="json"))
        write_json(root / "tactic-plan.json", tactics.model_dump(mode="json"))

        manifest_candidates: list[dict[str, Any]] = []
        instance_by_seed = {
            instance.candidate_seed: instance for instance in run.instances
        }
        for candidate in run.selected:
            instance = instance_by_seed[candidate.plan.seed]
            name = f"{candidate.plan.ordinal:04d}-{candidate.plan.seed}"
            candidate_dir = root / "candidates" / name
            corpus_dir = candidate_dir / "corpus"
            candidate.world.export(corpus_dir, overwrite=overwrite)
            write_json(
                candidate_dir / "eval-instance.json",
                instance.model_dump(mode="json"),
            )
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
                "design_digest": (
                    run.attempts[0].plan.design_digest if run.attempts else ""
                ),
                "demand_digest": tactics.demand_digest,
                "tactic_count": len(tactics.proposals),
                "attempt_count": len(run.attempts),
                "candidate_count": len(run.selected),
                "accepted_count": len(run.accepted),
                "rejected_count": len(run.rejected),
                "selected_ordinals": (
                    list(run.selected_ordinals) if run.selected_ordinals is not None else None
                ),
                "failed_requirements": {
                    str(ordinal): list(requirements)
                    for ordinal, requirements in run.failed_requirements.items()
                },
                "attempts": [
                    {
                        "ordinal": candidate.plan.ordinal,
                        "seed": candidate.plan.seed,
                        "validation": candidate.validation.model_dump(mode="json"),
                    }
                    for candidate in run.attempts
                ],
                "constructions": [
                    {
                        "ordinal": result.candidate.plan.ordinal,
                        "seed": result.candidate.plan.seed,
                        "applied": list(result.applied_tactic_ids),
                        "findings": [finding.model_dump(mode="json") for finding in result.findings],
                    }
                    for result in run.constructions
                ],
                "candidates": manifest_candidates,
            },
        )
        return root


@dataclass(frozen=True)
class EvalCampaign:
    """One immutable eval design plus its deterministic candidate operations."""

    spec: EvalSpec

    def demands(self) -> DemandSet:
        return compile_demands(self.spec)

    def tactics(self) -> TacticPlan:
        return plan_tactics(self.demands())

    def plans(self, *, count: int | None = None) -> tuple[CandidatePlan, ...]:
        return plan_candidates(self.spec, count=count)

    def candidates(
        self,
        builder: CandidateBuilder,
        *,
        count: int | None = None,
        keep_rejected: bool = False,
    ) -> tuple[GeneratedCandidate, ...]:
        return generate_candidates(
            self.spec,
            builder,
            count=count,
            keep_rejected=keep_rejected,
        )

    def construct(
        self,
        base: CandidateBuilder,
        *,
        count: int | None = None,
        occurred_at: datetime | None = None,
    ) -> CampaignRun:
        """Build each candidate, then make it satisfy the eval, then validate.

        The eval drives generation: *base* supplies a world the way a vertical
        builds one, and ``construct_candidate`` executes one tactic per demand
        the design compiled to. The validator that accepts the result is the
        same one ``run`` uses and knows nothing about the constructions, so a
        tactic cannot accept its own output.
        """

        from ..eval_interventions import construct_candidate

        constructions = tuple(
            construct_candidate(self.spec, plan, base(plan), occurred_at=occurred_at)
            for plan in self.plans(count=count)
        )
        attempts = tuple(result.candidate for result in constructions)
        accepted = tuple(candidate for candidate in attempts if candidate.validation.accepted)
        instances = tuple(bind_eval_instance(self.spec, candidate) for candidate in accepted)
        return CampaignRun(spec=self.spec, attempts=attempts, instances=instances,
                           constructions=constructions)

    def run(
        self,
        builder: CandidateBuilder,
        *,
        count: int | None = None,
    ) -> CampaignRun:
        attempts = self.candidates(builder, count=count, keep_rejected=True)
        accepted = tuple(
            candidate for candidate in attempts if candidate.validation.accepted
        )
        instances = tuple(
            bind_eval_instance(self.spec, candidate) for candidate in accepted
        )
        return CampaignRun(
            spec=self.spec,
            attempts=attempts,
            instances=instances,
        )

    def search(
        self,
        builder: AdaptiveCandidateBuilder,
        *,
        count: int | None = None,
    ) -> CampaignRun:
        """Use the existing adaptive search seam with sealed evaluator feedback."""

        from ..eval_search import search_candidates

        attempts = search_candidates(self.spec, builder, count=count)
        instances = tuple(
            bind_eval_instance(self.spec, candidate)
            for candidate in attempts if candidate.validation.accepted
        )
        return CampaignRun(spec=self.spec, attempts=attempts, instances=instances)

    def instantiate(
        self,
        builder: CandidateBuilder,
        *,
        count: int | None = None,
    ) -> tuple[EvalInstance, ...]:
        return self.run(builder, count=count).instances

    def prove(
        self,
        builder: CandidateBuilder,
        executor: StepExecutor,
        *,
        count: int | None = None,
    ) -> tuple[ExecutionProof, ...]:
        return self.run(builder, count=count).prove(executor)

    def export(
        self,
        builder: CandidateBuilder,
        out: str | Path,
        *,
        count: int | None = None,
        formats: tuple[str, ...] = (),
        overwrite: bool = False,
        construct: bool = False,
        occurred_at: datetime | None = None,
    ) -> Path:
        """Build once and export; use ``CampaignRun.export`` after finalization."""

        run = (
            self.construct(builder, count=count, occurred_at=occurred_at)
            if construct else self.run(builder, count=count)
        )
        return run.export(out, formats=formats, overwrite=overwrite)


__all__ = ["CampaignRun", "EvalCampaign"]
