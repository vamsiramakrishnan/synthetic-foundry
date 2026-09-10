"""Fixed native corpus difficulty, with evidence-disjoint observed holdouts.

No noise intervention is inferred here. The existing calibration ledger owns
provenance, deduplication and Wilson intervals; this module owns sampling.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..eval_metrics import (
    CalibrationObservation,
    DifficultyCalibrator,
    NativeFeatures,
    feature_slice,
)
from ..models import Model
from ..native_tasks import NativeTask
from ..providers import digest


class NativeCalibrationPlan(Model):
    cohort: str = Field(min_length=1)
    target_low: float = Field(default=.3, ge=0, le=1, allow_inf_nan=False)
    target_high: float = Field(default=.7, ge=0, le=1, allow_inf_nan=False)
    min_support: int = Field(default=32, ge=1, le=4096, strict=True)
    max_training_attempts: int = Field(default=384, ge=1, le=4096, strict=True)
    max_holdout_attempts: int = Field(default=128, ge=1, le=4096, strict=True)
    holdout_percent: int = Field(default=25, ge=1, le=99, strict=True)

    @model_validator(mode="after")
    def contract(self) -> NativeCalibrationPlan:
        if self.target_low >= self.target_high:
            raise ValueError("target_low must be below target_high")
        if self.cohort != self.cohort.strip():
            raise ValueError("cohort must have no surrounding whitespace")
        return self


def stratum(task: NativeTask) -> str:
    return digest([task.use_case_id, task.operation,
                   sorted({i.format for i in task.inputs} | ({task.output.format} if task.output else set()))])


def seal(plan: NativeCalibrationPlan, tasks: list[NativeTask], components: dict[str, str]) -> dict[str, Any]:
    # Assignment is independent of agent outcomes and project revision. Changing
    # the declared component population creates a new, explicitly sealed run.
    groups = sorted(set(components.values()), key=lambda key: digest(["native-holdout/v1", key]))
    n_holdout = max(1, len(groups) * plan.holdout_percent // 100)
    holdout = set(groups[:n_holdout])
    splits = {task.id: "holdout" if components[task.id] in holdout else "train" for task in tasks}
    samples: dict[str, list[str]] = {}
    support: dict[str, dict[str, Any]] = {}
    findings: list[str] = []
    strata = sorted({stratum(task) for task in tasks})
    task_strata = {task.id: stratum(task) for task in tasks}
    representatives = {stratum(task): task for task in tasks}
    for split in ("train", "holdout"):
        chosen: dict[tuple[str, str], str] = {}
        for task in sorted(tasks, key=lambda t: t.id):
            if splits[task.id] == split:
                chosen.setdefault((stratum(task), components[task.id]), task.id)
        queues = [[value for (case, _), value in sorted(chosen.items()) if case == key]
                  for key in sorted({key[0] for key in chosen})]
        ordered = [q[i] for i in range(max(map(len, queues), default=0)) for q in queues if i < len(q)]
        budget = plan.max_training_attempts if split == "train" else plan.max_holdout_attempts
        samples[split] = ordered[:budget]
        support[split] = {}
        for key in strata:
            available = sum(case == key for case, _ in chosen)
            planned = sum(task_strata[task_id] == key for task_id in samples[split])
            support[split][key] = {"available": available, "planned": planned,
                                   "required": plan.min_support, "use_case_id": representatives[key].use_case_id,
                                   "operation": representatives[key].operation}
            if available < plan.min_support:
                findings.append(f"insufficient_native_population:{split}:{key}")
            elif planned < plan.min_support:
                findings.append(f"insufficient_native_budget:{split}:{key}")
    return {"schema": "worldloom.native-calibration-seal/v1", "plan": plan.model_dump(mode="json"),
            "components": components, "splits": splits, "samples": samples,
            "support": support, "feasible": bool(strata) and not findings, "findings": findings,
            "tasks_digest": digest([task.model_dump(mode="json") for task in tasks])}


def summarize(plan: NativeCalibrationPlan, tasks: list[NativeTask], outcomes: list[dict[str, Any]],
              sealed: dict[str, Any], *, corpus_digest: str, evaluator_digest: str,
              split: Literal["train", "holdout"]) -> dict[str, Any]:
    calibrator = DifficultyCalibrator()
    task_map = {task.id: task for task in tasks}
    representatives = {stratum(task): task for task in sorted(tasks, key=lambda t: t.id, reverse=True)}

    def features(task: NativeTask) -> Any:
        return feature_slice(NativeFeatures(operation=task.operation,
            formats=tuple(sorted({i.format for i in task.inputs} | ({task.output.format} if task.output else set()))),
            input_count=len(task.inputs), assertion_count=len(task.assertions)),
            conditions={"native_calibration": digest(sealed), "stratum": stratum(task)})

    seen: set[tuple[str, str]] = set()
    for row in outcomes:
        task = task_map[row["task_id"]]
        observed_split = row["split"]
        if observed_split not in {"train", "holdout"} or task.id not in sealed["samples"][observed_split]:
            raise ValueError("native observation is outside the sealed sample")
        key = (stratum(task), sealed["components"][task.id])
        if key in seen:
            raise ValueError("native evidence component contributes duplicate support")
        seen.add(key)
        calibrator.ingest(CalibrationObservation(cohort=plan.cohort, trial_id=row["trial_id"],
            eval_id=digest(key), corpus_digest=corpus_digest, evaluator_config_digest=evaluator_digest,
            evaluator_kind="agent", features=features(task), passed=row["passed"], split=observed_split))
    estimates = {key: calibrator.estimate(plan.cohort, features(task), min_trials=plan.min_support, split=split)
                 for key, task in sorted(representatives.items())}
    accepted = bool(estimates) and all(v.fitted and v.interval_low >= plan.target_low
                                     and v.interval_high <= plan.target_high for v in estimates.values())
    return {"split": split, "accepted": accepted,
            "estimates": {key: {"use_case_id": representatives[key].use_case_id,
                                "operation": representatives[key].operation, **value.model_dump(mode="json")}
                          for key, value in estimates.items()},
            "observations": calibrator.snapshot().model_dump(mode="json")}
