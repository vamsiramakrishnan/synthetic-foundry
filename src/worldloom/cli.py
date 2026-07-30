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
narrate_app = typer.Typer(
    no_args_is_help=True,
    help="Hand prose requests to an agent, and validate what comes back.",
)
app.add_typer(narrate_app, name="narrate")

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
def build(
    seed: int = typer.Option(8128, "--seed", "-s", help="World seed. The same seed rebuilds the same world."),
    period: str = typer.Option("2026-03", "--period", "-p", help="Reporting period, YYYY-MM."),
    out: Path = typer.Option(None, "--out", "-o", help="Directory to write the corpus into."),
    incident: bool = typer.Option(
        None, "--incident/--no-incident",
        help="Force the operational incident on or off. Omit to let the seed and lore decide.",
    ),
    employees: int = typer.Option(80_000, "--employees", help="Stated headcount for the company."),
    formats: list[str] = typer.Option(
        None, "--format", "-f",
        help="Render these formats. Repeatable. Omit to plan artifacts without rendering.",
    ),
    narrate: bool = typer.Option(
        False, "--narrate",
        help="Generate prose with the built-in deterministic provider (no network, no key).",
    ),
    replay: Path = typer.Option(
        None, "--replay",
        help="Replay narration from an existing corpus's generation ledger instead of generating.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace the destination if it exists."),
) -> None:
    """Generate a world deterministically from a seed, then validate it.

    Unlike `demo`, nothing here is hand-authored — the organisation, financials,
    events, artifact plan, and evaluation cases are all generated. The same seed
    always produces the same world.
    """
    from .retail import MonthEndClose, RetailWorld

    world = RetailWorld(seed=seed, employees=employees).build()
    world = world.run(MonthEndClose(period=period, include_operational_incident=incident))

    if narrate or replay is not None:
        from .narrative import DeterministicProvider, ProviderError, UnreachableProvider

        ledger = ()
        provider = DeterministicProvider()
        if replay is not None:
            source = _load(str(replay))
            ledger = source._ledger
            if not ledger:
                err.print(f"[red]error:[/red] {replay} carries no generation ledger to replay")
                raise typer.Exit(code=2)
            # Unreachable on purpose: a replay that quietly falls back to
            # generating would not be a replay.
            provider = UnreachableProvider()

        try:
            world = world.narrate(provider, ledger=ledger)
        except ProviderError as exc:
            err.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=2) from exc

        calls, replayed, rejected = world._narration
        console.print(
            f"[dim]narration:[/dim] {calls} provider call(s), {replayed} replayed"
            f", {rejected} rejected\n"
        )

    if formats:
        from .render import RenderError

        try:
            world = world.render(*formats)
        except RenderError as exc:
            err.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=2) from exc

    console.print(_summary_table(world))
    console.print()
    if not _report(world):
        raise typer.Exit(code=1)

    if out is not None:
        # Compile before writing, so the exported corpus carries its artifact IR
        # and an agent can ask it for prose requests without rebuilding.
        if not world.artifact_irs:
            world = world.compile()
        try:
            written = world.export(out, overwrite=overwrite)
        except FileExistsError as exc:
            err.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"[green]✓[/green] exported to [bold]{written}[/bold]")


@narrate_app.command("requests")
def narrate_requests(
    corpus: str = typer.Argument(..., help="Corpus path or bundled name."),
    out: Path = typer.Option(None, "--out", "-o", help="Write JSON here instead of stdout."),
) -> None:
    """Emit the prose requests an agent needs to answer.

    Each request is self-describing: the facts it may use, which are required, what
    the author knew and when, the voice, and the rules in full.
    """
    from .narrative import handshake

    world = _load(corpus)
    if not world.artifact_irs:
        try:
            world = world.compile()
        except ValueError as exc:
            err.print(f"[red]error:[/red] {corpus}: {exc}")
            raise typer.Exit(code=2) from exc

    document = handshake.requests_document(world)
    if not document["requests"]:
        console.print("[green]✓[/green] nothing awaiting prose")
        return

    payload = handshake.dump(document)
    if out is None:
        typer.echo(payload, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        console.print(
            f"[green]✓[/green] {len(document['requests'])} request(s) written to [bold]{out}[/bold]"
        )


@narrate_app.command("accept")
def narrate_accept(
    corpus: str = typer.Argument(..., help="Corpus path to write prose into."),
    source: Path = typer.Option(..., "--from", "-i", help="Response JSON from the agent."),
    model_id: str = typer.Option(
        "agent", "--model-id",
        help="Who wrote it. Recorded in the ledger and part of the replay key.",
    ),
) -> None:
    """Validate agent-written prose and commit it, or report every violation.

    Nothing is committed unless every response passes. A partial commit would leave
    a corpus half-narrated with no record of which half.
    """
    from .narrative import ResponseProvider, handshake

    world = _load(corpus)
    if not world.artifact_irs:
        world = world.compile()
    try:
        responses = handshake.parse_responses(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {source}: {exc}")
        raise typer.Exit(code=2) from exc

    verdicts = handshake.review(world, responses)
    rejected = {name: v for name, v in verdicts.items() if not v.accepted}

    if rejected:
        err.print(
            f"[red]✗[/red] {len(rejected)} of {len(verdicts)} response(s) rejected."
            " Nothing was committed."
        )
        for name, verdict in sorted(rejected.items()):
            err.print(f"\n[bold]{name}[/bold]")
            for violation in verdict.violations:
                err.print(f"  [yellow]{violation.code}[/yellow] {violation.detail}")
        raise typer.Exit(code=1)

    narrated = world.narrate(ResponseProvider(responses, model_id=model_id), retries=0)
    written = narrated.export(corpus, overwrite=True)

    console.print(
        f"[green]✓[/green] {len(verdicts)} section(s) accepted and recorded in the ledger"
    )
    console.print(f"[green]✓[/green] written to [bold]{written}[/bold]")
    if not _report(narrated):
        raise typer.Exit(code=1)


@app.command()
def render(
    corpus: str = typer.Argument(..., help="Corpus path or bundled name."),
    formats: list[str] = typer.Option(..., "--format", "-f", help="Formats to render. Repeatable."),
    out: Path = typer.Option(None, "--out", "-o", help="Write here instead of back into the corpus."),
) -> None:
    """Render an existing corpus into files."""
    from .render import RenderError

    world = _load(corpus)
    try:
        rendered = world.render(*formats)
    except (RenderError, ValueError) as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    written = rendered.export(out or Path(corpus), overwrite=True)
    console.print(f"[green]✓[/green] {len(rendered._rendered)} file(s) written to [bold]{written}[/bold]")
    if not _report(rendered):
        raise typer.Exit(code=1)


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
def formats() -> None:
    """List the renderers this installation has."""
    from .render import available

    for name in available():
        console.print(name)


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
