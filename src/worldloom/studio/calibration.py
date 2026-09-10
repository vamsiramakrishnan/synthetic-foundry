"""Case-based calibration for one company; worlds are variants, not samples.

The existing empirical estimator owns uncertainty. Independent evidence
components own support. Every use case must fit before a variant is eligible.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..eval_metrics import (
    CalibrationObservation,
    DifficultyCalibrator,
    DifficultyEstimate,
    feature_slice,
)
from ..evals.calibration import NoiseVariant
from ..models import Model
from ..providers import digest


class CompanyCalibrationPlan(Model):
    variants: tuple[NoiseVariant, ...] = Field(min_length=1, max_length=16)
    cohort: str = Field(min_length=1)
    target_low: float = Field(default=.3, ge=0, le=1, allow_inf_nan=False)
    target_high: float = Field(default=.7, ge=0, le=1, allow_inf_nan=False)
    min_support: int = Field(default=20, ge=1, le=4096, strict=True)
    max_training_attempts: int = Field(default=128, ge=1, le=4096, strict=True)
    max_holdout_attempts: int = Field(default=64, ge=1, le=4096, strict=True)
    reader_share: float = Field(default=.1, gt=0, le=1, allow_inf_nan=False)
    max_turns: int = Field(default=32, ge=1, le=128, strict=True)

    @model_validator(mode="after")
    def _contract(self) -> CompanyCalibrationPlan:
        if self.target_low >= self.target_high:
            raise ValueError("target_low must be below target_high")
        if len({v.name for v in self.variants}) != len(self.variants):
            raise ValueError("noise variant names must be unique")
        return self


def independent_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One sample per transitive evidence component and use case.

    Cross-process cases can contribute to each separate use-case estimate,
    never twice to the same estimate or to opposite sides of the holdout.
    """
    parent = list(range(len(rows)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owners: dict[str, int] = {}
    for i, row in enumerate(rows):
        for key in [row["case_id"], *row["evidence"]]:
            if key in owners:
                a, b = root(i), root(owners[key])
                parent[max(a, b)] = min(a, b)
            else:
                owners[key] = i
    groups: dict[int, list[dict[str, Any]]] = {}
    for i, row in enumerate(rows):
        groups.setdefault(root(i), []).append(row)
    samples = []
    for group in groups.values():
        if len({r["split"] for r in group}) != 1:
            raise ValueError("calibration evidence crosses dataset splits")
        for case in sorted({r["stratum"] for r in group}):
            chosen = min((r for r in group if r["stratum"] == case), key=lambda r: r["id"])
            if chosen["split"] in {"train", "test"}:
                samples.append(chosen)
    ordered: list[dict[str, Any]] = []
    for split in ("train", "test"):
        queues = {case: sorted((r for r in samples if r["stratum"] == case and r["split"] == split), key=lambda r: r["id"])
                  for case in sorted({r["stratum"] for r in samples})}
        ordered.extend(queue[index] for index in range(max((len(q) for q in queues.values()), default=0))
                       for queue in queues.values() if index < len(queue))
    return ordered


def estimates(plan: CompanyCalibrationPlan, designs: dict[str, Any],
              observations: list[CalibrationObservation], *, variant: str,
              split: Literal["train", "holdout"] = "train") -> dict[str, DifficultyEstimate]:
    calibrator = DifficultyCalibrator()
    for observation in observations:
        calibrator.ingest(observation)
    return {case: calibrator.estimate(plan.cohort, features(plan, design, case, variant),
                                    min_trials=plan.min_support, split=split)
            for case, design in sorted(designs.items())}


def features(plan: CompanyCalibrationPlan, design: Any, case: str, variant: str) -> Any:
    return feature_slice(design, conditions={"company_calibration": digest(plan.model_dump(mode="json")),
                                             "use_case": case, "variant": variant})


def supported(plan: CompanyCalibrationPlan, values: dict[str, DifficultyEstimate]) -> bool:
    return bool(values) and all(v.fitted and v.interval_low >= plan.target_low
                               and v.interval_high <= plan.target_high for v in values.values())


def select(plan: CompanyCalibrationPlan, summaries: dict[str, dict[str, DifficultyEstimate]]) -> str | None:
    eligible = [name for name, values in summaries.items() if supported(plan, values)]
    midpoint = (plan.target_low + plan.target_high) / 2
    # One dataset owns one world. A niche archive may recommend alternatives;
    # it cannot splice company versions into one published dataset.
    return min(eligible, key=lambda name: (sum(abs(v.predicted_pass_rate - midpoint)
        for v in summaries[name].values()), name)) if eligible else None
