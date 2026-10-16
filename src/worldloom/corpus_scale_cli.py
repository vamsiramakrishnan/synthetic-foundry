"""CLI for measured, one-company corpus scale; generation stays in the SDK."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from .corpus_scale import CorpusScaleProfile, FactReconciliation
    from .synthesis.engine import Simulator
    from .world import World

scale_app = typer.Typer(no_args_is_help=True, help="Materialise and verify large enterprise corpus files.")


def _inputs(corpus_path: str, program_path: Path | None, limits_path: Path | None, profile: str,
            fact_id: str | None, rows: int | None, reconciliations: list[Path] | None,
            ) -> tuple[World, Simulator, CorpusScaleProfile, tuple[FactReconciliation, ...]]:
    from .cli import _load
    from .corpus_scale import (
        SCALE_PROFILES,
        CorpusScaleProfile,
        FactReconciliation,
        ledger_allocation_source,
        scale_profile,
    )
    from .quality_cli import _document
    from .synthesis.engine import Simulator
    from .synthesis.models import Limits, Program

    world = _load(corpus_path)
    selected = scale_profile(profile) if profile in SCALE_PROFILES else CorpusScaleProfile.model_validate(_document(Path(profile)))
    limits = None if limits_path is None else Limits.model_validate(_document(limits_path))
    bindings = tuple(FactReconciliation.model_validate(_document(path)) for path in reconciliations or ())
    if (program_path is None) == (fact_id is None):
        raise ValueError("supply exactly one of --program or --fact")
    if world.seed is None:
        raise ValueError("corpus scale requires a source world with a recorded seed")
    if fact_id is not None:
        if rows is None:
            raise ValueError("--fact requires an explicit --rows transaction population")
        # The requested transaction population is the caller's row budget;
        # the one ledger dimension is additional. Other work limits stay pinned.
        source = ledger_allocation_source(world, fact_id=fact_id, rows=rows, seed=world.seed,
            limits=limits or Limits(max_rows=rows + 1))
        return world, source.simulator, selected, (*bindings, source.reconciliation)
    if rows is not None:
        raise ValueError("--rows belongs to --fact; a --program owns its population")
    assert program_path is not None
    program = Program.model_validate(_document(program_path))
    return world, Simulator(program, seed=world.seed, limits=limits), selected, bindings


def _reject(error: Exception) -> None:
    from rich.markup import escape

    from .cli import _refuse

    _refuse("corpus_scale_rejected", escape(str(error)), finding=getattr(error, "code", type(error).__name__))


@scale_app.command("assess")
def assess_command(
    corpus_path: Annotated[str, typer.Argument(help="One company's source corpus.")],
    program: Annotated[Path | None, typer.Option("--program", help="Versioned operational synthesis Program JSON.")] = None,
    fact: Annotated[str | None, typer.Option("--fact", help="Canonical numeric fact to allocate into an exactly reconciling transaction ledger.")] = None,
    rows: Annotated[int | None, typer.Option("--rows", min=1, help="Explicit transaction population for --fact.")] = None,
    profile: Annotated[str, typer.Option("--profile", help="development, enterprise, stress, or a profile JSON path.")] = "enterprise",
    limits: Annotated[Path | None, typer.Option("--limits", help="Explicit synthesis resource budgets JSON.")] = None,
    reconciliation: Annotated[list[Path] | None, typer.Option("--reconciliation", help="FactReconciliation JSON for --program; repeat for each exact total.")] = None,
) -> None:
    """Report construction shortfalls before spending on materialisation."""
    from .corpus_scale import assess_corpus_scale
    from .quality_cli import _emit

    try:
        world, simulator, selected, _ = _inputs(corpus_path, program, limits, profile, fact, rows, reconciliation)
        report = assess_corpus_scale(world, simulator, profile=selected)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"))
    if not report.adequate:
        raise typer.Exit(1)


@scale_app.command("build")
def build_command(
    corpus_path: Annotated[str, typer.Argument(help="One company's source corpus with accepted prose.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="New destination; source corpus is unchanged.")],
    program: Annotated[Path | None, typer.Option("--program", help="Versioned operational synthesis Program JSON.")] = None,
    fact: Annotated[str | None, typer.Option("--fact", help="Canonical numeric fact to allocate into an exactly reconciling transaction ledger.")] = None,
    rows: Annotated[int | None, typer.Option("--rows", min=1, help="Explicit transaction population for --fact.")] = None,
    profile: Annotated[str, typer.Option("--profile", help="development, enterprise, stress, or a profile JSON path.")] = "enterprise",
    limits: Annotated[Path | None, typer.Option("--limits", help="Explicit synthesis resource budgets JSON.")] = None,
    reconciliation: Annotated[list[Path] | None, typer.Option("--reconciliation", help="FactReconciliation JSON for --program; repeat for each exact total.")] = None,
    reconcile: Annotated[str, typer.Option("--reconcile", help="declared: only --reconciliation bindings. auto: also bind each operational measure to its company-level fact when both exist (see `corpus-scale reconcile`).")] = "declared",
    reconcile_period: Annotated[str | None, typer.Option("--reconcile-period", help="Fact period the operational run covers, for --reconcile auto.")] = None,
    native_plan: Annotated[list[Path] | None, typer.Option("--native-plan", help="NativeCorpusPlan JSON; repeat to select file topology.")] = None,
    shard_rows: Annotated[int, typer.Option("--shard-rows", min=1, max=1_048_575, help="Maximum physical data rows per CSV shard.")] = 100_000,
    shard_bytes: Annotated[int, typer.Option("--shard-bytes", min=4096, max=536_870_912, help="Maximum bytes per CSV shard.")] = 33_554_432,
    maximum_files: Annotated[int, typer.Option("--maximum-files", min=4, max=100_000, help="Maximum files in the committed corpus.")] = 10_000,
    spreadsheets: Annotated[bool, typer.Option("--xlsx", help="Also write typed workbooks from each relational shard.")] = False,
    resume: Annotated[bool, typer.Option("--resume", help="Reuse a completed destination only after source reconstruction and verification.")] = False,
) -> None:
    """Write bounded relational shards and grounded native files atomically."""
    from .corpus_scale import export_corpus_scale, plan_corpus_scale
    from .native_corpus import NativeCorpusPlan
    from .quality_cli import _document, _emit

    try:
        world, simulator, selected, bindings = _inputs(corpus_path, program, limits, profile, fact, rows, reconciliation)
        plans = None if native_plan is None else tuple(NativeCorpusPlan.model_validate(_document(path)) for path in native_plan)
        if reconcile not in ("declared", "auto"):
            raise ValueError("--reconcile is declared or auto")
        plan = plan_corpus_scale(world, simulator, profile=selected, native_plans=plans, reconciliations=bindings,
            reconcile="auto" if reconcile == "auto" else "declared", reconcile_period=reconcile_period,
            csv_shard_rows=shard_rows, csv_shard_bytes=shard_bytes,
            maximum_files=maximum_files, spreadsheets=spreadsheets)
        report = export_corpus_scale(world, plan, out, resume=resume)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"))


@scale_app.command("reconcile")
def reconcile_command(
    corpus_path: Annotated[str, typer.Argument(help="One company's source corpus.")],
    program: Annotated[Path | None, typer.Option("--program", help="Versioned operational synthesis Program JSON.")] = None,
    fact: Annotated[str | None, typer.Option("--fact", help="Canonical numeric fact to allocate into an exactly reconciling transaction ledger.")] = None,
    rows: Annotated[int | None, typer.Option("--rows", min=1, help="Explicit transaction population for --fact.")] = None,
    limits: Annotated[Path | None, typer.Option("--limits", help="Explicit synthesis resource budgets JSON.")] = None,
    reconciliation: Annotated[list[Path] | None, typer.Option("--reconciliation", help="FactReconciliation JSON already declared; its column is not re-derived.")] = None,
    period: Annotated[str | None, typer.Option("--period", help="Fact period the operational run covers.")] = None,
) -> None:
    """Show which measure-to-fact reconciliations `build --reconcile auto` binds, and why the rest do not."""
    from .corpus_scale import derive_reconciliations
    from .quality_cli import _emit

    try:
        world, simulator, _, bindings = _inputs(corpus_path, program, limits, "development", fact, rows, reconciliation)
        report = derive_reconciliations(world, simulator.program, period=period, declared=bindings)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"))


@scale_app.command("verify")
def verify_command(
    corpus_path: Annotated[str, typer.Argument(help="The original company's source corpus.")],
    directory: Annotated[Path, typer.Argument(help="Materialised corpus scale directory.")],
) -> None:
    """Reconstruct declared projections; reject changed files or source bindings."""
    from .cli import _load
    from .corpus_scale import verify_corpus_scale
    from .quality_cli import _emit

    try:
        report = verify_corpus_scale(_load(corpus_path), directory)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"))
