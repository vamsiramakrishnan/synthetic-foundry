"""Thin command adapters over the public native benchmark SDK."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from .native_query_planning import NativeWorkload

native_evals_app = typer.Typer(no_args_is_help=True,
    help="Build, inspect, run and improve harnesses against byte-graded native tasks.")
_PUBLIC_WORKLOAD_SCHEMA = "worldloom.native-workload.public/v1"


class PackageLayout(StrEnum):
    LEGACY = "legacy"
    SPLIT = "split"


def __getattr__(name: str) -> Any:
    # Preserve the earlier import location without making CLI startup load the
    # benchmark engine. SDK consumers should import worldloom.benchmarks.
    if name in {"NativeTaskReply", "NativeWorkloadReplies", "NativeWorkloadGrade"}:
        from .benchmarks import core
        return getattr(core, name)
    raise AttributeError(name)


def _reject(error: Exception) -> None:
    from rich.markup import escape

    from .cli import _refuse
    _refuse("native_evals_rejected", escape(str(error)))


def _load_package(directory: Path) -> tuple[NativeWorkload, dict[str, bytes]]:
    from .benchmarks import NativeBenchmark
    benchmark = NativeBenchmark.load(directory)
    return benchmark.workload, dict(benchmark.inputs)


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
    layout: Annotated[PackageLayout, typer.Option("--layout", help="split separates public inputs from private source/oracle; legacy preserves the existing exchange layout.")] = PackageLayout.LEGACY,
    resume: Annotated[bool, typer.Option("--resume", help="Verify and reuse an identical completed package; refuse drift.")] = False,
) -> None:
    """Compile and reference-qualify tasks through the same SDK used by harnesses."""
    from .benchmarks import NativeBenchmark
    from .cli import _load
    from .native_query_planning import NativeWorkloadPlan
    from .quality_cli import _document, _emit
    try:
        benchmark = NativeBenchmark.build(_load(corpus_path), scale_directory,
            NativeWorkloadPlan.model_validate(_document(plan)))
        if layout is PackageLayout.SPLIT:
            benchmark = benchmark.export(out, resume=resume)
            public, private = out / "public", out / "private"
        else:
            benchmark = benchmark.export_legacy(out, resume=resume)
            public = private = out
        workload = benchmark.workload
    except (ValueError, OSError, KeyError) as error:
        _reject(error)
        return
    _emit({"tasks": len(workload.tasks), "reference_qualified": workload.reference_qualified,
        "operation_counts": workload.operation_counts, "capability_coverage": workload.capability_coverage,
        "findings": [finding.model_dump(mode="json") for finding in workload.findings],
        "public_tasks": str(public / "public-tasks.json"), "private_oracle": str(private / "oracle.json"),
        "target_directory": str(public) if layout is PackageLayout.SPLIT else None,
        "layout": layout.value, "benchmark_digest": benchmark.digest})


@native_evals_app.command("qualify")
def qualify_command(
    directory: Annotated[Path, typer.Argument(help="Native benchmark package or legacy exchange.")],
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
    directory: Annotated[Path, typer.Argument(help="Evaluator's native benchmark package or legacy exchange.")],
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
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="Planned observations per task and policy.")] = 2,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write readiness and coverage JSON.")] = None,
) -> None:
    """Separate executable tasks, requested coverage and independent promotion support."""
    from .benchmarks import NativeBenchmark
    from .evalrun.qualification import QualificationPolicy
    from .quality_cli import _document, _emit
    try:
        policy = QualificationPolicy.model_validate(_document(qualification_policy)) if qualification_policy else None
        report = NativeBenchmark.load(directory).assess(namespace=source_origin,
            qualification_policy=policy, repeats=repeats,
            heldout=NativeBenchmark.load(heldout) if heldout else None)
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
    directory: Annotated[Path, typer.Argument(help="Native benchmark package or legacy exchange.")],
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
    rounds: Annotated[int, typer.Option("--rounds", min=1)] = 1,
    repeats: Annotated[int, typer.Option("--repeats", min=2)] = 2,
    timeout: Annotated[float, typer.Option("--timeout", min=0.001)] = 120,
    identity_files: Annotated[list[Path] | None, typer.Option("--identity-file", help="Pin target imported modules/configuration; repeat as needed.")] = None,
) -> None:
    """Revise a harness policy and qualify improvements on fresh, isolated evidence."""
    import shlex

    from .benchmarks import NativeBenchmark
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
            repeats=repeats, rounds=rounds)
    except (ValueError, OSError, GraderDrift) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json", by_alias=True))
