"""Measured eval slices and empirical difficulty calibration.

Difficulty is not authored by a formula. Worldloom exposes stable structural
features, then estimates pass rate for a named agent cohort from observed runs.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from .eval_design import EvalSpec, RequirementKind
from .models import Model


class EvalFeatures(Model):
    step_count: int = Field(ge=1)
    dag_depth: int = Field(ge=1)
    connector_count: int = Field(ge=0)
    write_steps: int = Field(ge=0)
    verify_steps: int = Field(ge=0)
    requirement_count: int = Field(ge=1)
    revision_depth: int = Field(ge=0)
    temporal_requirements: int = Field(ge=0)
    permission_requirements: int = Field(ge=0)
    distractor_requirements: int = Field(ge=0)

    def slice_key(self) -> str:
        """Stable coarse slice for calibration and adaptive mutation."""
        return (
            f"d{self.dag_depth}:c{self.connector_count}:w{self.write_steps}:"
            f"r{self.revision_depth}:t{self.temporal_requirements}:"
            f"p{self.permission_requirements}:x{self.distractor_requirements}"
        )


class DifficultyEstimate(Model):
    cohort: str
    slice_key: str
    trials: int = Field(ge=0)
    successes: int = Field(ge=0)
    predicted_pass_rate: float = Field(ge=0.0, le=1.0)

    @property
    def difficulty(self) -> float:
        return 1.0 - self.predicted_pass_rate


def features_for(spec: EvalSpec) -> EvalFeatures:
    depth: dict[str, int] = {}
    for step in spec.steps:
        depth[step.id] = 1 + max((depth[parent] for parent in step.depends_on), default=0)
    connectors = {step.connector for step in spec.steps if step.connector}
    connectors.update(
        str(requirement.selector["connector"])
        for requirement in spec.requirements
        if "connector" in requirement.selector
    )
    revisions = [
        requirement.minimum
        for requirement in spec.requirements
        if requirement.kind == RequirementKind.REVISION_CHAIN
    ]
    return EvalFeatures(
        step_count=len(spec.steps),
        dag_depth=max(depth.values()),
        connector_count=len(connectors),
        write_steps=sum(step.effect == "write" for step in spec.steps),
        verify_steps=sum(step.effect == "verify" for step in spec.steps),
        requirement_count=len(spec.requirements),
        revision_depth=max(revisions, default=0),
        temporal_requirements=sum(
            requirement.kind == RequirementKind.TEMPORAL_RELATION
            for requirement in spec.requirements
        ),
        permission_requirements=sum(
            requirement.kind == RequirementKind.PERMISSION
            for requirement in spec.requirements
        ),
        distractor_requirements=sum(
            requirement.kind == RequirementKind.DISTRACTOR
            for requirement in spec.requirements
        ),
    )


class DifficultyCalibrator:
    """Small empirical pass-rate model keyed by cohort and eval slice.

    Laplace smoothing keeps tiny slices from pretending to have certainty.
    This can later be replaced by a learned model without changing the feature
    or estimate contracts.
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])

    def observe(self, cohort: str, spec: EvalSpec, *, passed: bool) -> None:
        key = (cohort, features_for(spec).slice_key())
        trials, successes = self._counts[key]
        self._counts[key] = [trials + 1, successes + int(passed)]

    def estimate(self, cohort: str, spec: EvalSpec) -> DifficultyEstimate:
        slice_key = features_for(spec).slice_key()
        trials, successes = self._counts[(cohort, slice_key)]
        pass_rate = (successes + 1) / (trials + 2)
        return DifficultyEstimate(
            cohort=cohort,
            slice_key=slice_key,
            trials=trials,
            successes=successes,
            predicted_pass_rate=pass_rate,
        )


__all__ = [
    "DifficultyCalibrator",
    "DifficultyEstimate",
    "EvalFeatures",
    "features_for",
]
