"""Thin command adapters over the public native benchmark SDK."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import typer

if TYPE_CHECKING:
    from .benchmarks.core import BenchmarkSplitRole
    from .benchmarks.curriculum import CurriculumAblation


class _SplitRole(StrEnum):
    TRAINING = "training"
    HELDOUT = "heldout"
    UNSPECIFIED = "unspecified"


class _Ablation(StrEnum):
    NONE = "none"
    WITHOUT_FAILURES = "without_failures"
    WITHOUT_COVERAGE = "without_coverage"


native_evals_app = typer.Typer(no_args_is_help=True,
    help="Build, inspect, run and improve harnesses against byte-graded native tasks.")


def _reject(error: Exception) -> None:
    from rich.markup import escape

    from .cli import _refuse
    _refuse("native_evals_rejected", escape(str(error)))


@native_evals_app.command("scenarios")
def scenarios_command(
    corpus_path: Annotated[str, typer.Argument(help="Replayable canonical company corpus.")],
    demand: Annotated[Path, typer.Option("--demand", help="NativeScenarioDemand JSON defining new business cases.")],
    plan: Annotated[Path, typer.Option("--plan", help="NativeWorkloadPlan JSON for both source-isolated workloads.")],
    train_families: Annotated[int, typer.Option("--train-families", min=1, max=255)],
    holdout_families: Annotated[int, typer.Option("--holdout-families", min=1, max=255)],
    out: Annotated[Path, typer.Option("--out", "-o", help="Destination containing training/, heldout/ and partition.json.")],
    resume: Annotated[bool, typer.Option("--resume", help="Verify and reuse the identical scenario and partition build.")] = False,
) -> None:
    """Generate native business evidence and partition only its newly authored cases."""
    from .benchmarks import (
        NativeScenarioDemand,
        NativeWorkloadPlan,
        build_native_scenarios,
        partition_benchmarks,
    )
    from .cli import _load
    from .quality_cli import _document, _emit

    try:
        built = build_native_scenarios(_load(corpus_path), NativeScenarioDemand.model_validate(_document(demand)))
        report = partition_benchmarks(built.world, NativeWorkloadPlan.model_validate(_document(plan)),
            training_families=train_families, heldout_families=holdout_families, directory=out,
            source_artifact_ids=built.source_artifact_ids, resume=resume)
    except (ValueError, OSError, KeyError) as error:
        _reject(error)
        return
    _emit({**report.model_dump(mode="json"), "scenario_demand": built.demand.model_dump(mode="json"),
        "scenario_episodes": [episode.model_dump(mode="json") for episode in built.episodes]})


@native_evals_app.command("partition")
def partition_command(
    corpus_path: Annotated[str, typer.Argument(help="Canonical company corpus with authored native evidence.")],
    plan: Annotated[Path, typer.Option("--plan", help="NativeWorkloadPlan JSON for both independently built workloads.")],
    train_families: Annotated[int, typer.Option("--train-families", min=1, max=255)],
    holdout_families: Annotated[int, typer.Option("--holdout-families", min=1, max=255)],
    out: Annotated[Path, typer.Option("--out", "-o", help="Atomic destination containing training/, heldout/ and partition.json.")],
    resume: Annotated[bool, typer.Option("--resume", help="Verify and reuse identical source, plan, family allocation and packages.")] = False,
) -> None:
    """Render disjoint source families and build independently audited train/holdout packages."""
    from .benchmarks import NativeWorkloadPlan, partition_benchmarks
    from .quality_cli import _document, _emit
    from .world import World
    try:
        report = partition_benchmarks(World.load(corpus_path), NativeWorkloadPlan.model_validate(_document(plan)),
            training_families=train_families, heldout_families=holdout_families, directory=out, resume=resume)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"))


@native_evals_app.command("build")
def build_command(
    corpus_path: Annotated[str, typer.Argument(help="Original source company corpus.")],
    scale_directory: Annotated[Path, typer.Argument(help="Verified corpus-scale output containing native files.")],
    plan: Annotated[Path, typer.Option("--plan", help="NativeWorkloadPlan JSON: objective, formats, operations and task budget.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Benchmark package destination.")],
    split_role: Annotated[_SplitRole, typer.Option("--split-role", help="Persisted allocation role; curriculum feedback requires training.")] = _SplitRole.UNSPECIFIED,
    resume: Annotated[bool, typer.Option("--resume", help="Verify and reuse an identical completed package; refuse drift.")] = False,
) -> None:
    """Compile and reference-qualify tasks through the same SDK used by harnesses."""
    from .benchmarks import NativeBenchmark
    from .cli import _load
    from .native_query_planning import NativeWorkloadPlan
    from .quality_cli import _document, _emit
    try:
        benchmark = NativeBenchmark.build(_load(corpus_path), scale_directory,
            NativeWorkloadPlan.model_validate(_document(plan)), split_role=cast("BenchmarkSplitRole", split_role.value))
        benchmark = benchmark.export(out, resume=resume)
        public, private = out / "public", out / "private"
        workload = benchmark.workload
    except (ValueError, OSError, KeyError) as error:
        _reject(error)
        return
    _emit({"tasks": len(workload.tasks), "reference_qualified": workload.reference_qualified,
        "operation_counts": workload.operation_counts, "capability_coverage": workload.capability_coverage,
        "findings": [finding.model_dump(mode="json") for finding in workload.findings],
        "public_tasks": str(public / "public-tasks.json"), "private_oracle": str(private / "oracle.json"),
        "target_directory": str(public), "benchmark_digest": benchmark.digest, "split_role": benchmark.split_role})


@native_evals_app.command("qualify")
def qualify_command(
    directory: Annotated[Path, typer.Argument(help="Native benchmark package.")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write independent reference grades JSON.")] = None,
) -> None:
    """Construct reference replies and check satisfiability against actual bytes."""
    from .benchmarks import NativeBenchmark
    from .quality_cli import _emit
    try:
        report = NativeBenchmark.load(directory).qualify()
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"), out)
    if not report.passed:
        raise typer.Exit(1)


@native_evals_app.command("grade")
def grade_command(
    directory: Annotated[Path, typer.Argument(help="Evaluator's native benchmark package.")],
    replies: Annotated[Path, typer.Option("--replies", help="NativeWorkloadReplies JSON with actual output bytes as base64.")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write grades JSON.")] = None,
) -> None:
    """Require exact task coverage and independently grade replies and files."""
    from .benchmarks import NativeBenchmark, NativeWorkloadReplies
    from .quality_cli import _document, _emit
    try:
        report = NativeBenchmark.load(directory).grade(NativeWorkloadReplies.model_validate(_document(replies)))
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"), out)
    if not report.passed:
        raise typer.Exit(1)


@native_evals_app.command("inspect")
def inspect_command(
    directory: Annotated[Path, typer.Argument(help="Native benchmark package to assess.")],
    heldout: Annotated[Path | None, typer.Option("--holdout", help="Independently built held-out benchmark to audit against training.")] = None,
    source_origin: Annotated[str, typer.Option("--source-origin", help="Stable world origin shared across snapshots and format replicas.")] = "benchmark",
    qualification_policy: Annotated[Path | None, typer.Option("--qualification-policy", help="Declared fresh-tranche and repeat requirements.")] = None,
    requirements: Annotated[Path | None, typer.Option("--requirements", help="Additional required capability cells and independent-unit floors.")] = None,
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="Planned observations per task and policy.")] = 2,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write readiness and coverage JSON.")] = None,
) -> None:
    """Separate executable tasks, requested coverage and independent promotion support."""
    from .benchmarks import BenchmarkRequirements, NativeBenchmark
    from .evalrun.qualification import QualificationPolicy
    from .quality_cli import _document, _emit
    try:
        policy = QualificationPolicy.model_validate(_document(qualification_policy)) if qualification_policy else None
        report = NativeBenchmark.load(directory).assess(namespace=source_origin,
            qualification_policy=policy, repeats=repeats,
            heldout=NativeBenchmark.load(heldout) if heldout else None,
            requirements=BenchmarkRequirements.model_validate(_document(requirements)) if requirements else None)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"), out)


@native_evals_app.command("protocol")
def protocol_command(
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the versioned target request/reply contract.")] = None,
) -> None:
    """Print the JSON exchange contract for a native harness adapter."""
    from .benchmarks.runner import protocol_manifest
    from .quality_cli import _emit
    _emit(protocol_manifest(), out)


@native_evals_app.command("run")
def run_command(
    directory: Annotated[Path, typer.Argument(help="Native benchmark package.")],
    command: Annotated[str, typer.Option("--command", help="Trusted target executable and arguments; no shell expansion.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Run directory with independently graded task receipts.")],
    repeats: Annotated[int, typer.Option("--repeats", min=1)] = 1,
    timeout: Annotated[float, typer.Option("--timeout", min=0.001, help="Maximum seconds per task invocation.")] = 120,
    max_output_bytes: Annotated[int, typer.Option("--max-output-bytes", min=1, help="Maximum target stdout/stderr bytes.")] = 16 * 1024 * 1024,
    identity_files: Annotated[list[Path] | None, typer.Option("--identity-file", help="Pin an imported module or configuration file; repeat as needed.")] = None,
    resume: Annotated[bool, typer.Option("--resume", help="Reuse completed receipts only under identical inputs and harness identity.")] = False,
) -> None:
    """Run the real target on task-scoped public inputs; regrade actual submitted bytes."""
    import shlex

    from .benchmarks import NativeBenchmark
    from .benchmarks.runner import CommandHarness, run_benchmark
    from .quality_cli import _emit
    try:
        harness = CommandHarness(tuple(shlex.split(command)), timeout_seconds=timeout,
            max_output_bytes=max_output_bytes, identity_files=tuple(identity_files or ()))
        report = run_benchmark(NativeBenchmark.load(directory), harness,
            directory=out, repeats=repeats, resume=resume)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"))
    if not report.passed:
        raise typer.Exit(1)


@native_evals_app.command("workflow-qualify")
def workflow_qualify_command(
    directory: Annotated[Path, typer.Argument(help="Source-bound native benchmark package.")],
    plan: Annotated[Path, typer.Option("--plan", help="NativeWorkflowPlan JSON with ordered dependencies and input bindings.")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write independently graded reference workflow results.")] = None,
) -> None:
    """Check every authored workflow step and actual bound reference file."""
    from .benchmarks import NativeBenchmark, NativeWorkflowPlan, qualify_workflow
    from .quality_cli import _document, _emit

    try:
        report = qualify_workflow(NativeBenchmark.load(directory), NativeWorkflowPlan.model_validate(_document(plan)))
    except (ValueError, OSError, KeyError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"), out)
    if not report.passed:
        raise typer.Exit(1)


@native_evals_app.command("workflow-run")
def workflow_run_command(
    directory: Annotated[Path, typer.Argument(help="Source-bound native benchmark package.")],
    plan: Annotated[Path, typer.Option("--plan", help="NativeWorkflowPlan JSON sealed to this benchmark.")],
    command: Annotated[str, typer.Option("--command", help="Trusted native target command; no shell expansion.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Workflow run directory with step receipts and byte lineage.")],
    timeout: Annotated[float, typer.Option("--timeout", min=0.001, help="Maximum seconds per step invocation.")] = 120,
    max_output_bytes: Annotated[int, typer.Option("--max-output-bytes", min=1)] = 16 * 1024 * 1024,
    identity_files: Annotated[list[Path] | None, typer.Option("--identity-file", help="Pin imported modules/configuration; repeat as needed.")] = None,
    resume: Annotated[bool, typer.Option("--resume", help="Regrade and reuse the identical completed step prefix.")] = False,
) -> None:
    """Execute a bounded authored DAG, blocking descendants of failed steps."""
    import shlex

    from .benchmarks import (
        CommandHarness,
        NativeBenchmark,
        NativeWorkflowPlan,
        run_workflow,
    )
    from .quality_cli import _document, _emit

    try:
        harness = CommandHarness(tuple(shlex.split(command)), timeout_seconds=timeout,
            max_output_bytes=max_output_bytes, identity_files=tuple(identity_files or ()))
        report = run_workflow(NativeBenchmark.load(directory), NativeWorkflowPlan.model_validate(_document(plan)),
            harness, directory=out, resume=resume)
    except (ValueError, OSError, KeyError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"))
    if not report.passed:
        raise typer.Exit(1)


@native_evals_app.command("diagnose")
def diagnose_command(
    training: Annotated[Path, typer.Argument(help="Benchmark package sealed with the training role.")],
    run: Annotated[Path, typer.Argument(help="Committed training run directory, including submission receipts.")],
    source_origin: Annotated[str, typer.Option("--source-origin", help="Stable company origin used throughout the experiment.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Write the content-addressed next-curriculum proposal.")],
    requirements: Annotated[Path | None, typer.Option("--requirements", help="Additional measured capability demands.")] = None,
    qualification_policy: Annotated[Path | None, typer.Option("--qualification-policy", help="Fresh-tranche and repeat budget for the next study.")] = None,
    version: Annotated[int, typer.Option("--version", min=1, help="Curriculum version; later versions require a parent receipt digest.")] = 1,
    parent_digest: Annotated[str | None, typer.Option("--parent-digest", help="Previous curriculum receipt digest.")] = None,
    ablation: Annotated[_Ablation, typer.Option("--ablation", help="Predeclare which training signal contributes demands.")] = _Ablation.NONE,
) -> None:
    """Regrade training receipts and propose SOURCE, QUERY and EVAL demands."""
    from .benchmarks import BenchmarkRequirements, NativeBenchmark, diagnose_benchmark
    from .evalrun.qualification import QualificationPolicy
    from .quality_cli import _document, _emit

    try:
        report = diagnose_benchmark(NativeBenchmark.load(training), run, namespace=source_origin,
            requirements=BenchmarkRequirements.model_validate(_document(requirements)) if requirements else None,
            qualification_policy=QualificationPolicy.model_validate(_document(qualification_policy)) if qualification_policy else None,
            version=version, parent_digest=parent_digest, ablation=cast("CurriculumAblation", ablation.value))
    except (ValueError, OSError, KeyError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"), out)


@native_evals_app.command("evolve")
def evolve_command(
    training: Annotated[Path, typer.Argument(help="Original training benchmark used for the curriculum diagnosis.")],
    run: Annotated[Path, typer.Argument(help="Original committed training run directory, including submissions.")],
    curriculum: Annotated[Path, typer.Option("--curriculum", help="NativeCurriculum receipt; independently rederived before building.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Fresh training benchmark package; qualification needs a new study.")],
    resume: Annotated[bool, typer.Option("--resume", help="Rebuild and verify an identical evolved package.")] = False,
) -> None:
    """Materialize verified curriculum demands into new canonical sources and tasks."""
    from .benchmarks import NativeBenchmark, NativeCurriculum, build_curriculum_training
    from .quality_cli import _document, _emit

    try:
        built = build_curriculum_training(NativeBenchmark.load(training), run,
            NativeCurriculum.model_validate(_document(curriculum)))
        benchmark = built.benchmark.export(out, resume=resume)
    except (ValueError, OSError, KeyError) as error:
        _reject(error)
        return
    _emit({"benchmark_digest": benchmark.digest, "source_digest": benchmark.source_digest,
        "curriculum_digest": built.curriculum.digest, "split_role": benchmark.split_role,
        "target_directory": str(benchmark.target_directory), "directory": str(out),
        "assessment": built.assessment.model_dump(mode="json"), "qualification": built.curriculum.qualification})


@native_evals_app.command("improve")
def improve_command(
    training: Annotated[Path, typer.Argument(help="Training benchmark package with private source provenance.")],
    heldout: Annotated[Path, typer.Argument(help="Held-out benchmark package with independent evidence.")],
    agent_pack: Annotated[str, typer.Option("--agent-pack", help="Initial champion agent pack reference or path.")],
    command: Annotated[str, typer.Option("--command", help="Native target command consuming the public protocol.")],
    proposer_command: Annotated[str, typer.Option("--proposer-command", help="Policy proposer using the existing pack-author JSON exchange.")],
    source_origin: Annotated[str, typer.Option("--source-origin", help="Stable company origin shared by training and held-out source snapshots.")],
    qualification_policy: Annotated[Path, typer.Option("--qualification-policy", help="Predeclared finite promotion budget and evidence requirements.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Persistent sealed study, policy revisions and run receipts.")],
    requirements: Annotated[Path | None, typer.Option("--requirements", help="Required capability cells enforced in both splits and every fresh tranche.")] = None,
    rounds: Annotated[int, typer.Option("--rounds", min=1)] = 1,
    repeats: Annotated[int, typer.Option("--repeats", min=2)] = 2,
    timeout: Annotated[float, typer.Option("--timeout", min=0.001)] = 120,
    identity_files: Annotated[list[Path] | None, typer.Option("--identity-file", help="Pin target imported modules/configuration; repeat as needed.")] = None,
) -> None:
    """Revise a harness policy and qualify improvements on fresh, isolated evidence."""
    import shlex

    from .benchmarks import BenchmarkRequirements, NativeBenchmark
    from .benchmarks.improvement import improve_benchmark
    from .benchmarks.runner import CommandHarness
    from .evalrun.grader import GraderDrift
    from .evalrun.qualification import QualificationPolicy
    from .packkit.authoring import run_exec_exchange
    from .packkit.resolve import resolve
    from .quality_cli import _document, _emit
    try:
        report = improve_benchmark(resolve(agent_pack, kind_name="agent"),
            NativeBenchmark.load(training), NativeBenchmark.load(heldout), namespace=source_origin,
            harness=CommandHarness(tuple(shlex.split(command)), timeout_seconds=timeout,
                identity_files=tuple(identity_files or ())),
            proposer=run_exec_exchange(proposer_command, timeout=timeout), out=out,
            qualification_policy=QualificationPolicy.model_validate(_document(qualification_policy)),
            requirements=BenchmarkRequirements.model_validate(_document(requirements)) if requirements else None,
            repeats=repeats, rounds=rounds)
    except (ValueError, OSError, GraderDrift) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json", by_alias=True))
