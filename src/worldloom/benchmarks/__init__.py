"""Stable SDK for native benchmark construction, exchange and evaluation."""
from __future__ import annotations

from ..native_query_planning import (
    NativeWorkload,
    NativeWorkloadFinding,
    NativeWorkloadPlan,
    plan_native_workload,
)
from .core import (
    BENCHMARK_SCHEMA,
    PUBLIC_WORKLOAD_SCHEMA,
    BenchmarkFile,
    BenchmarkSplitRole,
    NativeBenchmark,
    NativeBenchmarkManifest,
    NativeTaskReply,
    NativeWorkloadGrade,
    NativeWorkloadReplies,
)
from .coverage import (
    BenchmarkAssessment,
    BenchmarkCoverage,
    BenchmarkFinding,
    assess_native_benchmark,
)
from .curriculum import (
    CurriculumAblation,
    CurriculumDemand,
    CurriculumFailure,
    CurriculumObservation,
    NativeCurriculum,
    NativeCurriculumBuild,
    build_curriculum_training,
    diagnose_benchmark,
    load_training_run,
    run_training_curriculum,
)
from .improvement import NativePolicyAgent, improve_benchmark
from .partitions import (
    NativePartitionBuild,
    NativePartitionComponent,
    NativePartitionFamily,
    NativePartitionOmission,
    NativePartitionPlan,
    partition_benchmarks,
    plan_native_partitions,
)
from .requirements import (
    BenchmarkRequirements,
    CoverageDimension,
    CoverageRequirement,
    RequirementCoverage,
    measure_requirements,
    requirement_deficits,
    resolve_requirements,
    task_formats,
)
from .runner import (
    BenchmarkRun,
    BenchmarkTrial,
    CallableHarness,
    CommandHarness,
    HarnessFailure,
    NativeHarness,
    protocol_manifest,
    run_benchmark,
)
from .scenarios import (
    NativeScenarioBuild,
    NativeScenarioDemand,
    NativeScenarioEpisode,
    NativeScenarioProcess,
    build_native_scenarios,
)
from .workflows import (
    NativeWorkflowInput,
    NativeWorkflowLineage,
    NativeWorkflowPlan,
    NativeWorkflowQualification,
    NativeWorkflowRun,
    NativeWorkflowStep,
    NativeWorkflowStepResult,
    qualify_workflow,
    run_workflow,
    validate_workflow,
    workflow_capabilities,
)

__worldloom_seam__ = {
    "name": "benchmarks",
    "purpose": "Build native benchmarks, expose target-only inputs, qualify and grade actual harness output.",
    "canonical_import": "worldloom.benchmarks",
    "compatibility_imports": [],
}


def seam_contract() -> dict[str, object]:
    return {
        "schema": BENCHMARK_SCHEMA,
        "order": ["scenarios", "partition", "build", "assess", "export", "load", "qualify", "run", "grade",
            "workflow", "diagnose", "evolve", "improve"],
        "invariants": ["canonical-source-bound", "target-directory-excludes-oracle",
            "actual-byte-grading", "exact-identity-resume", "independent-source-families",
            "training-only-curriculum", "fresh-source-and-study-identities"],
        "public_types": ["NativeBenchmark", "NativeBenchmarkManifest", "NativeWorkloadPlan",
            "NativeTaskReply", "NativeWorkloadReplies", "NativeWorkloadGrade", "BenchmarkAssessment",
            "CommandHarness", "CallableHarness", "BenchmarkRun", "NativePolicyAgent",
            "NativePartitionPlan", "NativePartitionBuild", "BenchmarkRequirements", "CoverageRequirement",
            "NativeScenarioDemand", "NativeScenarioBuild", "NativeWorkflowPlan", "NativeWorkflowRun",
            "NativeCurriculum", "NativeCurriculumBuild"],
    }


__all__ = ["BENCHMARK_SCHEMA", "PUBLIC_WORKLOAD_SCHEMA", "BenchmarkFile", "BenchmarkSplitRole", "NativeBenchmarkManifest",
    "NativeBenchmark", "NativeWorkload", "NativeWorkloadFinding", "NativeWorkloadPlan", "plan_native_workload", "NativeTaskReply", "NativeWorkloadReplies",
    "NativeWorkloadGrade", "BenchmarkAssessment", "BenchmarkCoverage", "BenchmarkFinding", "assess_native_benchmark",
    "BenchmarkRun", "BenchmarkTrial", "CallableHarness", "CommandHarness", "HarnessFailure", "NativeHarness",
    "protocol_manifest", "run_benchmark", "NativePolicyAgent", "improve_benchmark", "seam_contract",
    "NativePartitionBuild", "NativePartitionComponent", "NativePartitionFamily", "NativePartitionOmission", "NativePartitionPlan",
    "partition_benchmarks", "plan_native_partitions",
    "BenchmarkRequirements", "CoverageDimension", "CoverageRequirement", "RequirementCoverage",
    "measure_requirements", "requirement_deficits", "resolve_requirements", "task_formats",
    "NativeScenarioBuild", "NativeScenarioDemand", "NativeScenarioEpisode", "NativeScenarioProcess", "build_native_scenarios",
    "CurriculumAblation", "CurriculumDemand", "CurriculumFailure", "CurriculumObservation", "NativeCurriculum",
    "NativeCurriculumBuild", "build_curriculum_training", "diagnose_benchmark", "load_training_run", "run_training_curriculum",
    "NativeWorkflowInput", "NativeWorkflowLineage", "NativeWorkflowPlan", "NativeWorkflowQualification", "NativeWorkflowRun",
    "NativeWorkflowStep", "NativeWorkflowStepResult", "qualify_workflow", "run_workflow", "validate_workflow", "workflow_capabilities"]
