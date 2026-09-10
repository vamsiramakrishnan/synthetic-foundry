"""Bounded grounded-file interventions within sealed evidence components."""
from __future__ import annotations

from typing import Any

from ..native_tasks import NativeTask
from ..providers import digest
from .native_calibration import NativeNoiseVariant


def interventions(tasks: list[NativeTask], components: dict[str, str],
                  variants: tuple[NativeNoiseVariant, ...], sealed: dict[str, Any]) -> dict[str, Any]:
    # Only artifacts already owned by this component can be exposed. Unassigned
    # files might contain holdout evidence; matching a company is insufficient.
    owned: dict[str, set[str]] = {}
    for task in tasks:
        owned.setdefault(components[task.id], set()).update(i.artifact_id for i in task.inputs)
    required = set(sealed["samples"]["train"]) | set(sealed["samples"]["holdout"])
    candidates: dict[str, dict[str, list[str]]] = {}
    findings: list[str] = []
    for variant in variants:
        rows: dict[str, list[str]] = {}
        for task in sorted(tasks, key=lambda task: task.id):
            if task.id not in required:
                continue
            pool = sorted(owned[components[task.id]] - {i.artifact_id for i in task.inputs},
                          key=lambda artifact: digest(["native-distractors/v1", task.id, artifact]))
            rows[task.id] = pool[:variant.distractor_files]
            if len(pool) < variant.distractor_files:
                findings.append(f"insufficient_native_distractors:{variant.name}:{task.id}")
        candidates[variant.name] = rows
    return {"schema": "worldloom.native-noise-seal/v1", "operator": "grounded_distractor_files",
            "candidates": candidates, "selection": "first_training_band_match",
            "feasible": not findings, "findings": findings,
            "scope": "same_evidence_component", "calibration_seal_digest": digest(sealed)}
