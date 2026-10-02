"""Run a source-bound native workflow against the public-only scripted worker.

Usage: python examples/native-rebuild/workflow_pilot.py /path/to/output
Use --resume to revalidate a completed run at that same output directory.
No generated Office files or run receipts belong in the checked-in example.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from worldloom import RetailWorld
from worldloom.benchmarks.core import NativeBenchmark
from worldloom.benchmarks.runner import CommandHarness
from worldloom.benchmarks.scenarios import NativeScenarioDemand, build_native_scenarios
from worldloom.benchmarks.workflows import (
    NativeWorkflowInput,
    NativeWorkflowPlan,
    NativeWorkflowStep,
    run_workflow,
    workflow_capabilities,
)
from worldloom.corpus import write_json
from worldloom.native_query_planning import NativeWorkloadPlan
from worldloom.providers import digest


def _files(directory: Path) -> dict[str, str]:
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*")) if path.is_file()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    output = arguments.output_directory.absolute()
    output.mkdir(parents=True, exist_ok=True)
    built = build_native_scenarios(RetailWorld(seed=8128).build(), NativeScenarioDemand(
        episodes=3, batch_id="workflow-pilot"))
    benchmark = NativeBenchmark.from_rendered(built.world, built.render(formats=("docx", "xlsx")),
        NativeWorkloadPlan(use_case_id="workflow-pilot",
            objective="Read the source, reconcile outcomes, update the decision, and create the review.",
            formats=("docx", "xlsx"), discovery_scope="artifact", max_tasks=192), split_role="training")
    for update in benchmark.workload.tasks:
        if update.operation != "update" or update.output.format != "docx":
            continue
        reads = [task for task in benchmark.workload.tasks if task.operation == "read"
            and len(task.assertions) == 1 and task.assertions[0].target == update.assertions[0].target]
        analyses = [task for task in benchmark.workload.tasks if task.operation == "analyze"
            and task.inputs == update.inputs and task.assertions[0].calculation.operation == "sum"]
        creates = [task for task in benchmark.workload.tasks if task.operation == "create"
            and task.output.format == "docx" and task.inputs == update.inputs]
        if reads and analyses and creates:
            read, analysis, create = reads[0], analyses[0], creates[0]
            break
    else:
        raise ValueError("No source-compatible DOCX workflow available")
    plan = NativeWorkflowPlan(id="scenario-native-close", benchmark_digest=benchmark.digest, steps=(
        NativeWorkflowStep(id="read", task_id=read.id),
        NativeWorkflowStep(id="analyze", task_id=analysis.id, depends_on=("read",)),
        NativeWorkflowStep(id="update", task_id=update.id, depends_on=("analyze",)),
        NativeWorkflowStep(id="verify", task_id=read.id, depends_on=("update",),
            input_bindings=(NativeWorkflowInput(input_artifact_id=read.inputs[0].artifact_id, parent_step_id="update"),)),
        NativeWorkflowStep(id="create", task_id=create.id, depends_on=("verify",)),
    ))
    harness = CommandHarness((sys.executable, str(Path(__file__).with_name("workflow_worker.py"))),
        identity_files=(Path(__file__).resolve().parents[2] / "src/worldloom/render/ooxml.py",),
        identity_extra={"worker": "public-docx-scenario-pilot/v1"})
    directory = output / "run"
    report = run_workflow(benchmark, plan, harness, directory=directory, resume=arguments.resume)
    before = _files(directory)
    resumed = run_workflow(benchmark, plan, harness, directory=directory, resume=True)
    receipt = json.loads((directory / "receipts" / (digest(["verify"]) + ".json")).read_bytes())
    result = {"seed": 8128, "source_episodes": len(built.episodes), "native_files": len(benchmark.inputs),
        "benchmark_tasks": len(benchmark.workload.tasks), "source_digest": benchmark.source_digest,
        "benchmark_digest": benchmark.digest, "workflow_digest": plan.digest,
        "total_steps": report.total, "passed_steps": report.passed_count,
        "passed": report.passed, "statuses": {step.step_id: step.status for step in report.steps},
        "findings": {step.step_id: list(step.grade.findings) for step in report.steps},
        "assertions": {step.step_id: step.grade.metrics.get("assertions") for step in report.steps},
        "update_checksum_differs": report.steps[3].lineage[0].source_input_sha256 != report.steps[3].lineage[0].sha256,
        "readback_contains_actual_update": "Related evidence:" in receipt["submission"]["answers"][0]["value"],
        "resume_equal": resumed == report, "resume_byte_identical": before == _files(directory),
        "capabilities": workflow_capabilities(), "target_boundary": "trusted subprocess/public-only DOCX worker",
        "pilot_limits": ["one selected scenario case", "DOCX operations only", "authored sum analysis only",
            "runner-scheduled graph", "create uses canonical source inputs; updated-input writes unsupported",
            "no autonomous model performance measurement"]}
    write_json(output / "workflow-plan.json", plan.model_dump(mode="json"))
    write_json(output / "workflow-report.json", result)
    print(json.dumps(result, sort_keys=True))
    if not (report.passed and result["readback_contains_actual_update"] and result["update_checksum_differs"]
            and result["resume_equal"] and result["resume_byte_identical"]):
        raise SystemExit("Workflow pilot did not meet its required observations; inspect workflow-report.json")


if __name__ == "__main__":
    main()
