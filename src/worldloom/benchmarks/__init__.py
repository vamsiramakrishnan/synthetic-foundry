"""Stable SDK for native benchmark construction, exchange and evaluation."""
from __future__ import annotations

from ..native_query_planning import NativeWorkload, NativeWorkloadPlan
from .core import (
    BENCHMARK_SCHEMA,
    PUBLIC_WORKLOAD_SCHEMA,
    BenchmarkFile,
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
from .improvement import NativePolicyAgent, improve_benchmark
from .partitions import (
    NativePartitionBuild,
    NativePartitionFamily,
    NativePartitionOmission,
    NativePartitionPlan,
    partition_benchmarks,
    plan_native_partitions,
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

__worldloom_seam__ = {
    "name": "benchmarks",
    "purpose": "Build native benchmarks, expose target-only inputs, qualify and grade actual harness output.",
    "canonical_import": "worldloom.benchmarks",
    "compatibility_imports": ["worldloom.native_evals_cli", "worldloom.native_eval_bridge"],
}


def seam_contract() -> dict[str, object]:
    return {
        "schema": BENCHMARK_SCHEMA,
        "order": ["partition", "build", "assess", "export", "load", "qualify", "run", "grade", "improve"],
        "invariants": ["canonical-source-bound", "target-directory-excludes-oracle",
            "actual-byte-grading", "exact-identity-resume", "independent-source-families"],
        "public_types": ["NativeBenchmark", "NativeBenchmarkManifest", "NativeWorkloadPlan",
            "NativeTaskReply", "NativeWorkloadReplies", "NativeWorkloadGrade", "BenchmarkAssessment",
            "CommandHarness", "CallableHarness", "BenchmarkRun", "NativePolicyAgent",
            "NativePartitionPlan", "NativePartitionBuild"],
    }


__all__ = ["BENCHMARK_SCHEMA", "PUBLIC_WORKLOAD_SCHEMA", "BenchmarkFile", "NativeBenchmarkManifest",
    "NativeBenchmark", "NativeWorkload", "NativeWorkloadPlan", "NativeTaskReply", "NativeWorkloadReplies",
    "NativeWorkloadGrade", "BenchmarkAssessment", "BenchmarkCoverage", "BenchmarkFinding", "assess_native_benchmark",
    "BenchmarkRun", "BenchmarkTrial", "CallableHarness", "CommandHarness", "HarnessFailure", "NativeHarness",
    "protocol_manifest", "run_benchmark", "NativePolicyAgent", "improve_benchmark", "seam_contract",
    "NativePartitionBuild", "NativePartitionFamily", "NativePartitionOmission", "NativePartitionPlan",
    "partition_benchmarks", "plan_native_partitions"]
