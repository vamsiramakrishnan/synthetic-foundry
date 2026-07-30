"""The command line interface.

A thin wrapper. Every command calls the same library methods a user would call
themselves, and adds no capability the library lacks::

    worldloom demo retail-close
    worldloom inspect dist/retail-close
    worldloom validate dist/retail-close
    worldloom evals export dist/retail-close
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .corpus import CorpusError
from .world import World

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Generate coherent synthetic enterprise worlds.",
)
evals_app = typer.Typer(no_args_is_help=True, help="Work with a corpus's evaluation set.")
app.add_typer(evals_app, name="evals")

console = Console()
err = Console(stderr=True)


def _load(name_or_path: str) -> World:
    try:
        return World.load(name_or_path)
    except CorpusError as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _summary_table(world: World) -> Table:
    table = Table(title=world.company.name, title_style="bold", show_header=False, box=None)
    table.add_column(style="dim")
    table.add_column(justify="right")
    for label, value in world.summary().rows:
        table.add_row(label, value)
    return table


def _report(world: World, *, quiet: bool = False) -> bool:
    report = world.validate()
    if report.ok:
        if not quiet:
            console.print(f"[green]✓[/green] coherent — {report.checks_run} checks passed")
        return True
    err.print(f"[red]✗[/red] {len(report.violations)} violation(s) across {report.checks_run} checks")
    for group, items in sorted(report.by_group().items()):
        err.print(f"\n[bold]{group}[/bold]")
        for violation in items:
            err.print(f"  [yellow]{violation.code}[/yellow] {violation.subject}: {violation.detail}")
    return False


@app.command()
def demo(
    name: str = typer.Argument("retail-close", help="Bundled corpus to build."),
    out: Path = typer.Option(Path("dist"), "--out", "-o", help="Directory to write the corpus into."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace the destination if it exists."),
) -> None:
    """Build a bundled demo corpus, validate it, and export it.

    This is the first executable: one small, completely coherent corpus that
    proves the product thesis, with no model involved.
    """
    world = _load(name)
    console.print(_summary_table(world))
    console.print()
    if not _report(world):
        raise typer.Exit(code=1)

    destination = out / name
    try:
        written = world.export(destination, overwrite=overwrite)
    except FileExistsError as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print(f"[green]✓[/green] exported to [bold]{written}[/bold]")


@app.command()
def inspect(
    corpus: str = typer.Argument(..., help="Bundled corpus name or path."),
    facts: bool = typer.Option(False, "--facts", help="List facts."),
    events: bool = typer.Option(False, "--events", help="List the timeline."),
    artifacts: bool = typer.Option(False, "--artifacts", help="List artifacts."),
    evaluations: bool = typer.Option(False, "--evals", help="List evaluation cases."),
    lore: bool = typer.Option(False, "--lore", help="List lore commitments."),
) -> None:
    """Show what a corpus contains. Nothing is hidden."""
    world = _load(corpus)

    if not any([facts, events, artifacts, evaluations, lore]):
        console.print(_summary_table(world))
        return

    if lore:
        table = Table(title="Lore", box=None)
        table.add_column("id", style="dim")
        table.add_column("kind")
        table.add_column("constrains", justify="right")
        table.add_column("assertion", overflow="fold")
        for item in world.lore:
            table.add_row(item.id, item.kind.value, str(len(item.constrains)), item.assertion[:96])
        console.print(table, "")

    if events:
        table = Table(title="Timeline", box=None)
        table.add_column("id", style="dim")
        table.add_column("when")
        table.add_column("kind")
        table.add_column("summary", overflow="fold")
        for event in world.timeline():
            table.add_row(event.id, event.occurred_at.strftime("%Y-%m-%d %H:%M"), event.kind, event.summary[:88])
        console.print(table, "")

    if facts:
        table = Table(title="Facts", box=None)
        table.add_column("id", style="dim")
        table.add_column("kind")
        table.add_column("subject")
        table.add_column("value", justify="right", overflow="fold")
        table.add_column("authority")
        table.add_column("", style="dim")
        for fact in world.facts:
            value = f"{fact.value.amount:,g} {fact.value.unit}" if fact.value else (fact.text_value or "")
            table.add_row(
                fact.id,
                fact.kind,
                fact.subject,
                value[:48],
                fact.authority.value,
                "superseded" if fact.is_superseded else "",
            )
        console.print(table, "")

    if artifacts:
        table = Table(title="Artifacts", box=None)
        table.add_column("id", style="dim")
        table.add_column("type")
        table.add_column("author")
        table.add_column("authority")
        table.add_column("facts", justify="right")
        table.add_column("path", overflow="fold")
        for artifact in world.artifacts:
            table.add_row(
                artifact.id,
                artifact.artifact_type,
                artifact.author_id,
                artifact.authority.value,
                str(len(artifact.supporting_fact_ids)),
                artifact.path,
            )
        console.print(table, "")

    if evaluations:
        table = Table(title="Evaluation cases", box=None)
        table.add_column("id", style="dim")
        table.add_column("type")
        table.add_column("diff")
        table.add_column("question", overflow="fold")
        for case in world.evaluations:
            table.add_row(case.id, case.evaluation_type.value, case.difficulty, case.question[:80])
        console.print(table, "")


@app.command()
def validate(corpus: str = typer.Argument(..., help="Bundled corpus name or path.")) -> None:
    """Check a corpus for coherence violations."""
    if not _report(_load(corpus)):
        raise typer.Exit(code=1)


@evals_app.command("export")
def evals_export(
    corpus: str = typer.Argument(..., help="Bundled corpus name or path."),
    out: Path = typer.Option(None, "--out", "-o", help="Write JSONL here instead of stdout."),
) -> None:
    """Export the evaluation set as JSONL, ready to score a retrieval system."""
    world = _load(corpus)
    lines = [json.dumps(case.model_dump(mode="json"), sort_keys=True) for case in world.evaluations]
    payload = "\n".join(lines) + "\n"
    if out is None:
        typer.echo(payload, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        console.print(f"[green]✓[/green] {len(lines)} case(s) written to [bold]{out}[/bold]")


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
