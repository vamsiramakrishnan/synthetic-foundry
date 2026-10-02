"""Replay the native rebuild's offline evidence and promotion-preflight pilot.

Run from any directory with the project's native-renderer dependencies installed.
No target, provider, proposer, or network service is called. The report records
solvability and evidence support, never an estimate of target-model performance.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from worldloom import RetailWorld
from worldloom.benchmarks.core import NativeBenchmark
from worldloom.benchmarks.partitions import partition_benchmarks
from worldloom.benchmarks.requirements import task_formats
from worldloom.benchmarks.scenarios import NativeScenarioDemand, build_native_scenarios
from worldloom.corpus import write_json
from worldloom.evalrun.contract import EvalCase
from worldloom.evalrun.qualification import (
    QualificationPolicy,
    evidence_components,
    qualification_tranches,
)
from worldloom.native_artifacts import inspect_artifact
from worldloom.native_eval_bridge import native_grader_identity, native_task_cases
from worldloom.native_query_planning import NativeWorkloadPlan
from worldloom.native_requirements import BenchmarkRequirements
from worldloom.providers import digest


def _read(name: str) -> dict[str, Any]:
    return json.loads((Path(__file__).parent / name).read_text(encoding="utf-8"))


def _dimension_support(cases: Sequence[EvalCase], name: str) -> dict[str, dict[str, int]]:
    units = evidence_components(cases)
    values = sorted({case.dimensions.get(name, "undeclared") for case in cases})
    return {value: {"tasks": len(selected := [case for case in cases
        if case.dimensions.get(name, "undeclared") == value]),
        "independent_units": len({units[case.id] for case in selected})} for value in values}


def _benchmark_summary(benchmark: NativeBenchmark, cases: Sequence[EvalCase]) -> dict[str, Any]:
    tasks = benchmark.workload.tasks
    files = []
    for artifact_id, result in sorted(benchmark.rendered.items()):
        snapshot = inspect_artifact(result.payload, result.manifest.format)
        files.append({"artifact_id": artifact_id, "format": snapshot.format,
            "sha256": snapshot.sha256, "size_bytes": len(result.payload), "native_metrics": snapshot.metrics,
            "addressable_units": len(snapshot.units),
            "canonical_artifacts": sorted({entry.source_artifact_id for entry in result.manifest.evidence}),
            "direct_canonical_facts": len({fact_id for entry in result.manifest.evidence for fact_id in entry.fact_ids})})
    calculations = Counter(assertion.calculation.operation for task in tasks for assertion in task.assertions
        if assertion.calculation is not None)
    matrix = Counter(f"{task.operation}:{format}" for task in tasks for format in task_formats(task))
    return {"benchmark_digest": benchmark.digest, "split_role": benchmark.split_role,
        "tasks": len(tasks), "reference_qualified": benchmark.workload.reference_qualified,
        "independent_units": len(set(evidence_components(cases).values())),
        "operation_counts": dict(sorted(Counter(task.operation for task in tasks).items())),
        "operation_format_task_counts": dict(sorted(matrix.items())),
        "calculation_assertion_counts": dict(sorted(calculations.items())),
        "planner_capability_counts": benchmark.workload.capability_coverage,
        "planner_truncated": benchmark.workload.truncated,
        "planner_findings": [finding.model_dump(mode="json") for finding in benchmark.workload.findings],
        "source_files": files, "file_count": len(files),
        "total_source_bytes": sum(item["size_bytes"] for item in files),
        "descriptive_process_support": _dimension_support(cases, "scenario_process"),
        "descriptive_template_support": _dimension_support(cases, "scenario_template")}


def run(directory: Path, report_path: Path, *, resume: bool = False) -> dict[str, Any]:
    experiment = _read("experiment.json")
    demand = NativeScenarioDemand.model_validate(_read("demand.json"))
    requirements = BenchmarkRequirements.model_validate(_read("requirements.json"))
    plan = NativeWorkloadPlan.model_validate({**_read("workload-plan.json"),
        "requirements": requirements.model_dump(mode="json")})
    policy = QualificationPolicy.model_validate(experiment["qualification_policy"])
    print("Building the recorded operational source and verifying recipe replay.", flush=True)
    base = RetailWorld(seed=experiment["seed"]).build()
    background_facts = {fact.id for fact in base.facts}
    source = build_native_scenarios(base, demand)
    source.world.validate().raise_if_failed()
    source.verify_source_replay()
    print("Rendering isolated source families and qualifying the declared task matrix.", flush=True)
    built = partition_benchmarks(source.world, plan, source_artifact_ids=source.source_artifact_ids,
        training_families=experiment["training_families"], heldout_families=experiment["heldout_families"],
        directory=directory, resume=resume)
    training = NativeBenchmark.load(Path(built.training_directory))
    heldout = NativeBenchmark.load(Path(built.heldout_directory))
    print("Revalidating canonical ancestry and every actual fresh held-out tranche.", flush=True)
    assessment = training.assess(heldout=heldout, qualification_policy=policy, repeats=experiment["repeats"])
    cases = {role: native_task_cases(benchmark.workload.tasks, benchmark.rendered,
        namespace=source.world.company.id, world=source.world)
        for role, benchmark in (("training", training), ("heldout", heldout))}
    held_by_id = {case.id: case for case in cases["heldout"]}
    tranches = qualification_tranches(cases["heldout"], policy=policy)
    measured_facts = {fact_id for group in cases.values() for case in group for fact_id in case.row["expected_fact_ids"]}
    overlap = sum(bool(set(first.fact_ids) & set(second.fact_ids))
        for index, first in enumerate(source.episodes) for second in source.episodes[index + 1:])
    report = {"schema": "worldloom.native-rebuild-pilot/v1", "experiment": experiment,
        "demand": demand.model_dump(mode="json"), "workload_plan": plan.model_dump(mode="json"),
        "source_digest": source.source_digest, "source_recipe_replay_verified": True,
        "source_coherence_verified": True, "source_episodes": [episode.model_dump(mode="json") for episode in source.episodes],
        "scope": {"selected_source_artifacts": len(source.source_artifact_ids),
            "background_fact_ids_used": sorted(measured_facts & background_facts),
            "episode_pairs_with_shared_canonical_ancestry": overlap,
            "unique_scoped_canonical_facts": len(measured_facts)},
        "partition": {"training_families": built.training_families, "heldout_families": built.heldout_families,
            "available_components": built.plan.available_components,
            "omissions": [item.model_dump(mode="json") for item in built.plan.omissions],
            "exclusions": [item.model_dump(mode="json") for item in built.plan.exclusions],
            "split_audit": built.split_audit.model_dump(mode="json")},
        "training": _benchmark_summary(training, cases["training"]),
        "heldout": _benchmark_summary(heldout, cases["heldout"]),
        "assessment": assessment.model_dump(mode="json"),
        "fresh_tranches": [{"number": number,
            "cases_digest": digest(list(tranche)), "tasks": len(tranche),
            "independent_units": len(set(evidence_components(tuple(held_by_id[key] for key in tranche)).values())),
            "descriptive_process_support": _dimension_support(tuple(held_by_id[key] for key in tranche), "scenario_process")}
            for number, tranche in enumerate(tranches, start=1)],
        "measurement_limits": {"target_calls": 0, "candidate_proposals": 0,
            "target_model_gain_measured": False,
            "process_and_template_counts_are_descriptive": True,
            "visual_layout_parity_measured": False,
            "cross_artifact_workflows_measured": False},
        "runtime": {"python": platform.python_version(), "native_grader": native_grader_identity()}}
    report["digest"] = digest(report)
    write_json(report_path, report)
    print(json.dumps({"promotion_preflight_ready": assessment.promotion_ready,
        "training_tasks": len(training.workload.tasks), "heldout_tasks": len(heldout.workload.tasks),
        "training_units": built.split_audit.training_units, "heldout_units": built.split_audit.heldout_units,
        "findings": [finding.code for finding in assessment.findings], "report": str(report_path)}, sort_keys=True), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Destination for the actual separated benchmark packages.")
    parser.add_argument("--report", type=Path, default=Path(__file__).parent / "report.json")
    parser.add_argument("--resume", action="store_true", help="Revalidate and reuse exactly identical existing packages.")
    args = parser.parse_args()
    report = run(args.output, args.report, resume=args.resume)
    if not report["assessment"]["promotion_ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
