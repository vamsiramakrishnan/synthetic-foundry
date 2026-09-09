"""Thin operator surface for the dataset compiler and its durable run."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

dataset_app = typer.Typer(no_args_is_help=True, help="Compile dataset quotas into diverse, qualified queries with isolated splits.")


@dataset_app.command("compile")
def compile_command(
    plan_path: Annotated[Path, typer.Argument(help="DatasetPlan JSON; company sources, quotas and diversity limits.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Dataset run directory; reuse it to resume the same plan.")],
    batch_limit: Annotated[int | None, typer.Option("--batch-limit", min=1, help="Pause after this many total batches.")] = None,
    replay: Annotated[bool, typer.Option("--replay", help="Require committed batches; never call a generator or executor.")] = False,
) -> None:
    """Generate missing coverage, enforce admission, then export isolated splits."""
    from .cli import _refuse
    from .evals.company_dataset import load_dataset_plan
    from .evals.dataset import _read, compile_dataset

    try:
        plan = load_dataset_plan(_read(plan_path))
        run = compile_dataset(plan, out, batch_limit=batch_limit, replay_only=replay)
    except (OSError, ValueError) as error:
        _refuse("dataset_rejected", str(error))
    typer.echo(run.report.model_dump_json())
    if not run.report.complete:
        _refuse("dataset_incomplete", "dataset quota, diversity or split obligations remain; see report.json",
                exit_code=3, report=run.report.model_dump(mode="json"), destination=str(out))


@dataset_app.command("verify")
def verify_command(
    directory: Annotated[Path, typer.Argument(help="Dataset run to verify, including exact evidence and proof files.")],
) -> None:
    """Check the dataset's content inventory without generation or execution."""
    from .cli import _refuse
    from .evals.dataset import verify_dataset

    try:
        report = verify_dataset(directory)
    except (OSError, ValueError) as error:
        _refuse("dataset_rejected", str(error))
    typer.echo(report.model_dump_json())
    if not report.complete:
        _refuse("dataset_incomplete", "checkpoint is intact but the dataset is incomplete", exit_code=3)


__all__ = ["dataset_app"]
