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
from rich.markup import escape
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
plan_app = typer.Typer(
    no_args_is_help=True,
    help="Hand artifact-shape requests to an agent, and validate what comes back against the grammar.",
)
app.add_typer(plan_app, name="plan")
pack_app = typer.Typer(
    no_args_is_help=True,
    help="Author and check industry packs — a world's shape and lore as data.",
)
app.add_typer(pack_app, name="pack")
act_app = typer.Typer(
    no_args_is_help=True,
    help="Drive an actor episode: one employee's decision at a time, validated before it changes anything.",
)
app.add_typer(act_app, name="act")

console = Console()
err = Console(stderr=True)


def _load(name_or_path: str) -> World:
    try:
        return World.load(name_or_path)
    except CorpusError as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc


def _step_period(period: str, index: int, step_months: int) -> str:
    """*period* advanced by *index* steps of *step_months* months.

    Generic over the step size so a single-episode domain's own cadence never
    needs a domain name in this file — the thin-waist ratchet test forbids
    engine vocabulary here, so "how far apart do this domain's periods sit"
    has to be data (`Domain.period_step_months`) the domain hands back, not a
    fact this function is allowed to know.
    """
    year, month = (int(part) for part in period.split("-"))
    total_months = year * 12 + (month - 1) + index * step_months
    year, month = divmod(total_months, 12)
    return f"{year:04d}-{month + 1:02d}"


def _summary_table(world: World) -> Table:
    table = Table(title=world.company.name, title_style="bold", show_header=False, box=None)
    table.add_column(style="dim")
    table.add_column(justify="right")
    for label, value in world.summary().rows:
        table.add_row(label, value)
    return table


def _compiled(world: World, corpus: str) -> World:
    """The world with its artifact IR present, compiling if needed.

    This exact dance — try to compile, translate the empty-world error into an
    exit — appeared at seven call sites with three slightly different error
    messages. An agent debugging a failure got a different sentence depending on
    which command it happened to be running, for the same underlying state.
    """
    if world.artifact_irs:
        return world
    try:
        return world.compile()
    except ValueError as exc:
        err.print(f"[red]error:[/red] {corpus}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc


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
        err.print(f"[red]error:[/red] {escape(str(exc))}")
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
    employees: int = typer.Option(None, "--employees", help="Override the archetype's stated headcount."),
    archetype: str = typer.Option(
        "omnichannel_retailer", "--archetype", "-a",
        help="Company shape to build. See `worldloom archetypes` for the list.",
    ),
    inspired_by: str = typer.Option(
        None, "--inspired-by",
        help=(
            "Describe a real business and build a world of that shape "
            "(e.g. 'a large Australian grocer'). Shape only — no data about it is used."
        ),
    ),
    pack: Path = typer.Option(
        None, "--pack",
        help=(
            "Build from an industry pack: a JSON file carrying the company shape, "
            "lore, and name. See `worldloom pack template` to start one and "
            "`worldloom pack check` to lint it."
        ),
    ),
    comparatives: int = typer.Option(
        0, "--comparatives",
        help="Prior months of actuals to generate, for a trend. 11 gives a rolling year.",
    ),
    periods: int = typer.Option(
        1, "--periods",
        help=(
            "Run this many consecutive episodes — closes for the retail vertical, "
            "or a single-episode vertical's own cadence (a domain's period_step_months). "
            "More than one gives recurrence, superseded documents, and the evaluation "
            "questions a single episode cannot pose."
        ),
    ),
    formats: list[str] = typer.Option(
        None, "--format", "-f",
        help="Render these formats. Repeatable. Omit to plan artifacts without rendering.",
    ),
    actors: str = typer.Option(
        None, "--actors",
        help=(
            "Let employees produce the incident's records by calling tools on what "
            "they observed. `scripted` runs the built-in deterministic actor (no "
            "network, no key); `agent` leaves every decision for you to make "
            "through `worldloom act`."
        ),
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
    from . import archetypes as archetype_registry
    from . import domains
    from .retail import MonthEndClose, RetailWorld

    pack_obj = None
    if pack is not None:
        # A pack supplies the shape, the lore, and the name, so the flags that
        # would supply them another way are refused rather than merged.
        refused_with_pack = [
            flag for flag, given in (
                ("--archetype", archetype != "omnichannel_retailer"),
                ("--inspired-by", inspired_by is not None),
                ("--employees", employees is not None),
            ) if given
        ]
        if refused_with_pack:
            err.print(
                f"[red]error:[/red] {', '.join(refused_with_pack)} cannot be combined"
                " with --pack; the pack states the company's shape and scale"
            )
            raise typer.Exit(code=2)
        from . import packs as packs_module

        try:
            pack_obj = packs_module.load(pack)
        except Exception as exc:
            err.print(f"[red]error:[/red] pack does not validate: {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
        for finding in packs_module.lint(pack_obj):
            err.print(f"[yellow]pack:[/yellow] {escape(finding)}")
        shape = packs_module.archetype_of(pack_obj)
        domain = domains.by_name(pack_obj.base)
        if domain is None:
            err.print(
                f"[red]error:[/red] pack base {pack_obj.base!r} names no registered"
                f" engine; registered: {', '.join(domains.names())}"
            )
            raise typer.Exit(code=2)
    elif inspired_by:
        shape = archetype_registry.inspired_by(inspired_by)
        domain = domains.for_archetype(shape.key)
    else:
        try:
            shape = archetype_registry.get(archetype)
        except KeyError as exc:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
        domain = domains.for_archetype(shape.key)

    # The archetype names its domain, and the domain says how a build runs. A
    # single-episode domain (banking, and any vertical after it) constructs its
    # world and runs one episode per period; the close-loop flags that make no
    # sense outside retail's own incident/actor machinery are refused rather
    # than ignored, because a flag that silently does nothing teaches the
    # wrong lesson about the tool. `--periods` is not among them — it is the
    # one close-loop flag with an honest single-episode reading, "run this
    # many consecutive episodes", so it steps by the domain's own cadence
    # (`period_step_months`) instead. The retail close keeps its bespoke loop
    # below.
    single_episode = domain.single_episode if domain is not None else None

    if single_episode is not None:
        refused = [
            flag for flag, given in (
                ("--actors", actors is not None),
                ("--incident/--no-incident", incident is not None),
                ("--comparatives", comparatives > 0),
            ) if given
        ]
        if refused:
            err.print(
                f"[red]error:[/red] {', '.join(refused)} belong(s) to the retail close;"
                f" the {domain.name} vertical runs one episode per build"
            )
            raise typer.Exit(code=2)

        builder = (
            domain.world.from_pack(pack_obj, seed=seed)
            if pack_obj is not None
            else domain.world(seed=seed, archetype=shape, employees=employees)
        )
        world = builder.build()
        for index in range(max(1, periods)):
            world = world.run(single_episode(_step_period(period, index, domain.period_step_months)))
    else:
        builder = (
            RetailWorld.from_pack(pack_obj, seed=seed)
            if pack_obj is not None
            else RetailWorld(seed=seed, archetype=shape, employees=employees)
        )
        world = builder.build()

    # The actor provider is resolved before the loop, and a replay makes it
    # unreachable for the same reason a replayed narration does: a fallback that
    # quietly generated instead would not be a replay.
    if actors is not None and actors not in {"scripted", "agent"}:
        err.print(f"[red]error:[/red] --actors takes `scripted` or `agent`, not {actors!r}")
        raise typer.Exit(code=2)

    # `agent` exports the world *before* the episode, carrying a recipe that says
    # an actor close is expected. There is no half-run episode to serialise —
    # `worldloom act` resumes by rebuilding from that recipe and the ledger — so
    # the honest artifact at this point is the organisation and nothing else.
    if actors == "agent":
        from dataclasses import replace as _replace

        from .recipe import with_step

        intended = world._recipe
        year, month = (int(part) for part in period.split("-"))
        for index in range(max(1, periods)):
            stamp = f"{year + (month + index - 1) // 12:04d}-{(month + index - 1) % 12 + 1:02d}"
            intended = with_step(
                intended, "MonthEndClose", period=stamp, incident=incident,
                comparatives=comparatives if index == 0 else 0, actors=True,
            )
        world = _replace(world, _recipe=intended)
        if out is None:
            err.print("[red]error:[/red] --actors agent needs --out; the episode is driven from a corpus")
            raise typer.Exit(code=2)
        try:
            written = world.export(out, overwrite=overwrite)
        except FileExistsError as exc:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
        console.print(_summary_table(world))
        console.print(
            f"\n[green]✓[/green] exported to [bold]{written}[/bold]"
            f"\n[dim]{len(intended['steps'])} actor episode(s) awaiting decisions."
            f" Run `worldloom act requests {written}` to see the first.[/dim]"
        )
        return

    actor_provider = None
    actor_ledger: tuple = ()
    if actors == "scripted":
        from .actors import ScriptedActorProvider, UnreachableActorProvider

        actor_provider = ScriptedActorProvider()
        if replay is not None:
            actor_provider = UnreachableActorProvider()
            actor_ledger = _load(str(replay))._ledger

    # Consecutive closes on one world. Comparatives belong to the first only: they
    # backfill months before it, and a later episode asking for them again would
    # generate a second set of facts for months the corpus already has. A
    # single-episode domain already ran its episode above and skips this loop.
    year, month = (int(part) for part in period.split("-"))
    from .actors import ActorProviderError

    for index in range(max(1, periods) if single_episode is None else 0):
        stamp = f"{year + (month + index - 1) // 12:04d}-{(month + index - 1) % 12 + 1:02d}"
        try:
            world = world.run(
                MonthEndClose(
                    period=stamp,
                    include_operational_incident=incident,
                    comparative_months=comparatives if index == 0 else 0,
                    actors=actor_provider,
                    actor_ledger=actor_ledger,
                )
            )
        except ActorProviderError as exc:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc

    if actors == "scripted":
        accepted = sum(1 for entry in world.actor_ledger if entry.result.accepted)
        console.print(
            f"[dim]actors:[/dim] {len(world.actor_ledger)} tool call(s), {accepted} accepted"
            f", {len(world.observations)} observation(s)\n"
        )

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
            err.print(f"[red]error:[/red] {escape(str(exc))}")
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
            err.print(f"[red]error:[/red] {escape(str(exc))}")
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
            err.print(f"[red]error:[/red] {escape(str(exc))}")
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

    world = _compiled(_load(corpus), corpus)

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
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit verdicts as JSON — an agent fixing rejections should read data, not parse a table.",
    ),
) -> None:
    """Validate agent-written prose and commit it, or report every violation.

    Nothing is committed unless every response passes. A partial commit would leave
    a corpus half-narrated with no record of which half.
    """
    from .narrative import ResponseProvider, handshake

    world = _compiled(_load(corpus), corpus)
    try:
        responses = handshake.parse_responses(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {source}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    verdicts = handshake.review(world, responses)
    rejected = {name: v for name, v in verdicts.items() if not v.accepted}

    if as_json:
        import json as json_module

        typer.echo(json_module.dumps({
            "accepted": not rejected,
            "responses": len(verdicts),
            "rejected": {
                name: [{"code": v.code, "detail": v.detail} for v in verdict.violations]
                for name, verdict in sorted(rejected.items())
            },
        }, indent=2))
        if rejected:
            raise typer.Exit(code=1)

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

    if not as_json:
        console.print(
            f"[green]✓[/green] {len(verdicts)} section(s) accepted and recorded in the ledger"
        )
        console.print(f"[green]✓[/green] written to [bold]{written}[/bold]")
    if not _report(narrated, quiet=as_json):
        raise typer.Exit(code=1)


@narrate_app.command("auto")
def narrate_auto(
    corpus: str = typer.Argument(..., help="Corpus path to narrate."),
    model: str = typer.Option(
        None, "--model",
        help="Anthropic model id. Omit to use the provider's default"
        " (see `worldloom.narrative.ANTHROPIC_DEFAULT_MODEL`).",
    ),
    retries: int = typer.Option(
        2, "--retries",
        help="Rejections the compiler will absorb per section before giving up.",
    ),
) -> None:
    """Run requests -> generate -> validate -> accept in-process, against a live model.

    Same loop `narrate requests` / write / `narrate accept` drives by hand, minus the
    human round trip: the compiler's own retry loop (`compiler._generate`) calls the
    model directly and feeds a rejection's violations back as the next attempt's
    prompt, so this is the existing retry mechanism with a live model behind it, not
    a second one. Every call still lands in the generation ledger keyed on
    (seed, call site, fact digest, model id, prompt version) exactly like the
    deterministic and hand-written paths, which is what makes a later
    `--replay` build reproduce this corpus byte-for-byte with no model, key, or
    network involved — `test_a_world_replays_with_the_provider_unreachable` and
    `test_an_exported_corpus_replays_byte_for_byte` in tests/test_narrative.py prove
    that property already, generically over any `Provider`; they just happen to have
    only ever been exercised against deterministic ones.
    `test_anthropic_narrate_auto_ledger_replays_offline` in
    tests/test_anthropic_provider.py closes that gap for this specific,
    non-deterministic provider.
    """
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        err.print(
            "[red]error:[/red] ANTHROPIC_API_KEY is not set."
            " Export it before running `worldloom narrate auto`."
        )
        raise typer.Exit(code=2)

    from .narrative import ANTHROPIC_DEFAULT_MODEL, AnthropicProvider, NarrationError, ProviderError

    world = _compiled(_load(corpus), corpus)

    try:
        provider = AnthropicProvider(model=model or ANTHROPIC_DEFAULT_MODEL, api_key=api_key)
        narrated = world.narrate(provider, retries=retries)
    except (ProviderError, NarrationError) as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    written = narrated.export(corpus, overwrite=True)

    calls, replayed, rejected = narrated._narration
    # `calls` counts every attempt including rejected ones (`1 + attempts` per new
    # section, see compiler.narrate); subtracting `rejected` back out leaves exactly
    # the count of sections that were newly generated this run, so the two together
    # give the sections-narrated total the summary promises without the compiler
    # needing to expose a fourth number for it.
    generated = calls - rejected
    console.print(
        f"[green]✓[/green] {generated + replayed} section(s) narrated with [bold]{provider.id}[/bold]"
    )
    console.print(
        f"[dim]narration:[/dim] {calls} provider call(s), {replayed} replayed from"
        f" the ledger, {rejected} rejected attempt(s)\n"
    )
    console.print(f"[green]✓[/green] written to [bold]{written}[/bold]")
    if not _report(narrated):
        raise typer.Exit(code=1)


@plan_app.command("requests")
def plan_requests(
    corpus: str = typer.Argument(..., help="Corpus path or bundled name."),
    out: Path = typer.Option(None, "--out", "-o", help="Write JSON here instead of stdout."),
) -> None:
    """Emit the artifact-shape requests an agent needs to answer.

    Each request is self-describing: the facts it may cite, the vocabulary of
    beat roles the compiler can spell, this artifact type's grammar stated in
    plain terms, and the headings this author has already used elsewhere.
    """
    from .compiler import handshake

    world = _compiled(_load(corpus), corpus)

    document = handshake.requests_document(world)
    if not document["requests"]:
        console.print("[green]✓[/green] nothing to plan")
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


@plan_app.command("accept")
def plan_accept(
    corpus: str = typer.Argument(..., help="Corpus path to record plans into."),
    source: Path = typer.Option(..., "--from", "-i", help="Response JSON from the agent."),
    model_id: str = typer.Option(
        "agent", "--model-id",
        help="Who proposed it. Recorded in the ledger and part of the replay key.",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit verdicts as JSON — an agent fixing rejections should read data, not parse a table.",
    ),
) -> None:
    """Validate agent-proposed plans and commit them to the ledger, or report every violation.

    Nothing is committed unless every response passes. A partial commit would leave
    a corpus half-planned with no record of which half.
    """
    from .compiler import handshake

    world = _compiled(_load(corpus), corpus)
    try:
        responses = handshake.parse_responses(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {source}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    result = handshake.accept(world, responses, model_id=model_id)
    rejected = {name: v for name, v in result.verdicts.items() if not v.accepted}

    if as_json:
        import json as json_module

        typer.echo(json_module.dumps({
            "accepted": not rejected,
            "plans": len(result.verdicts),
            "rejected": {
                name: [{"code": v.code, "detail": v.detail} for v in verdict.violations]
                for name, verdict in sorted(rejected.items())
            },
        }, indent=2))
        if rejected:
            raise typer.Exit(code=1)

    if rejected:
        err.print(
            f"[red]✗[/red] {len(rejected)} of {len(result.verdicts)} plan(s) rejected."
            " Nothing was committed."
        )
        for name, verdict in sorted(rejected.items()):
            err.print(f"\n[bold]{name}[/bold]")
            for violation in verdict.violations:
                err.print(f"  [yellow]{violation.code}[/yellow] {violation.detail}")
        raise typer.Exit(code=1)

    # Recompile, and do it *after* the ledger holds the accepted plans — the
    # outline reads them from there. Recording the plans and stopping left the
    # corpus with the IR it had compiled before the plans existed, and because
    # every later step skips `compile()` when `artifact_irs` is already
    # populated, narration and rendering both went on using the fixed outline.
    # The plans were accepted, stored, and silently ignored: the whole point of
    # the handshake, lost between two lines that each looked correct.
    updated = world.extend(ledger=result.ledger).compile()
    written = updated.export(corpus, overwrite=True)

    if not as_json:
        console.print(
            f"[green]✓[/green] {len(result.verdicts)} plan(s) accepted and recorded in the ledger"
        )
        console.print(f"[green]✓[/green] written to [bold]{written}[/bold]")
    if not _report(updated, quiet=as_json):
        raise typer.Exit(code=1)


def _warn_on_version_skew(world: World) -> None:
    """Say so when a corpus is being advanced by a different release than made it.

    Resume works by rebuilding from the recipe and replaying the ledger, and the
    ledger's content-addressed keys include a digest of what each actor was
    shown. A different release may generate a slightly different world, so keys
    miss and decisions get re-asked — correct, but baffling without this line.
    """
    from . import __version__

    made_by = world._generator_version
    if made_by and made_by != __version__:
        err.print(
            f"[yellow]![/yellow] this corpus was generated by worldloom {made_by};"
            f" you are running {__version__}. Replay keys may miss, and decisions"
            " already taken may be asked again."
        )


@act_app.command("requests")
def act_requests(
    corpus: str = typer.Argument(..., help="Corpus path carrying an actor episode."),
    out: Path = typer.Option(None, "--out", "-o", help="Write JSON here instead of stdout."),
) -> None:
    """Emit the next decision an employee has to make.

    Self-describing: the facts this person has actually observed and how they
    came to know each one, the messages they were sent, the obligations they
    hold, the tools their role permits, and the rules in full. There is no other
    context — an actor that went looking for some would be reading the world
    rather than its own position in it.

    One decision at a time, because the next one depends on this one. See
    `worldloom.actors.handshake` for why there is no batch form.
    """
    from .actors import handshake
    from .recipe import RecipeError

    world = _load(corpus)
    _warn_on_version_skew(world)
    try:
        document = handshake.requests_document(world)
    except RecipeError as exc:
        err.print(f"[red]error:[/red] {corpus}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    if document.get("complete"):
        # "Complete" and "committed" are not the same thing, and conflating them
        # was a dead end. `requests_document` rebuilds to find the next decision
        # and throws the rebuilt world away, because reading is not writing. If
        # the rebuild finished without needing anybody — a routing table that
        # wakes no one for this world — then the corpus on disk is still the
        # pre-episode organisation, and saying "complete" while leaving it that
        # way gives the user no command that would commit it.
        if not world.actor_ledger:
            console.print(
                "[yellow]![/yellow] this episode requires no decisions, and nothing"
                " has been committed yet.\n"
                "[dim]Commit it with an empty action set:"
                ' `echo \'{"actions": []}\' > none.json &&'
                f" worldloom act accept {corpus} --from none.json`[/dim]"
            )
            return
        console.print("[green]✓[/green] the episode is complete — nothing left to decide")
        return

    payload = handshake.dump(document)
    if out is None:
        typer.echo(payload, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload, encoding="utf-8")
    decision = document["decision"]
    console.print(
        f"[green]✓[/green] [bold]{decision['id']}[/bold] — {decision['title']}"
        f" woken by {decision['trigger']['kind']}"
    )
    console.print(
        f"[dim]{len(decision['facts'])} observed fact(s), {len(decision['tools'])} tool(s)"
        f" available. Written to {out}[/dim]"
    )


@act_app.command("accept")
def act_accept(
    corpus: str = typer.Argument(..., help="Corpus path to record the decision into."),
    source: Path = typer.Option(..., "--from", "-i", help="Action JSON from the agent."),
    model_id: str = typer.Option(
        None, "--model-id",
        help=(
            "Who decided. Recorded in the ledger and part of the replay key, so it "
            "is pinned to the corpus on the first accepted decision and cannot "
            "change mid-episode."
        ),
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit the verdict as JSON — an agent fixing a rejection should read data, not parse a table.",
    ),
) -> None:
    """Validate a decision and commit it, or report the rule it broke.

    Nothing is committed unless the action is legal: a tool beyond the role's
    authority, a fact the actor never observed, or a failed precondition comes
    back with the rule and the corpus is untouched. That is the same contract
    `narrate accept` has — rejection is the harness working.

    While the episode is still running this commits the *ledger*, because
    mid-episode there is no finished world to write and the ledger is what the
    next call resumes from. When the last decision lands, the completed world is
    written whole.
    """
    from .actors import handshake
    from .recipe import RecipeError

    world = _load(corpus)
    _warn_on_version_skew(world)
    try:
        actions = handshake.parse_actions(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {source}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    try:
        outcome = handshake.accept(world, actions, model_id=model_id)
    except (RecipeError, ValueError) as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    if as_json:
        import json as json_module

        typer.echo(json_module.dumps({
            "accepted": outcome.accepted,
            "applied": outcome.applied,
            "complete": outcome.complete,
            "rejected": dict(sorted(outcome.rejections.items())),
        }, indent=2))
        if not outcome.accepted:
            raise typer.Exit(code=1)

    if not outcome.accepted:
        err.print(
            f"[red]✗[/red] {len(outcome.rejections)} action(s) rejected. Nothing was committed."
        )
        for name, reason in sorted(outcome.rejections.items()):
            err.print(f"\n[bold]{name}[/bold]\n  [yellow]{reason}[/yellow]")
        raise typer.Exit(code=1)

    assert outcome.world is not None
    written = outcome.world.export(corpus, overwrite=True)
    if not as_json:
        console.print(
            f"[green]✓[/green] {len(outcome.applied)} decision(s) accepted"
            f" and recorded as [dim]{outcome.model_id}[/dim]"
        )
        console.print(f"[green]✓[/green] written to [bold]{written}[/bold]")

    if not outcome.complete:
        if not as_json:
            console.print(
                "[dim]the episode continues — run `worldloom act requests` for the next decision[/dim]"
            )
        return

    if not as_json:
        console.print(
            f"[green]✓[/green] episode complete: {len(outcome.world.actor_ledger)} tool call(s),"
            f" {len(outcome.world.observations)} observation(s)"
        )
    if not _report(outcome.world, quiet=as_json):
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
        err.print(f"[red]error:[/red] {escape(str(exc))}")
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
def status(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable state instead of the table."
    ),
) -> None:
    """Where this corpus is in the loop, and the exact command that comes next.

    The pipeline's sequence lives in the skill files, but a sequence an agent has
    to memorise is a sequence it will eventually resume in the wrong place — a
    corpus picked up mid-loop looks like a directory of JSONL, and nothing in a
    directory listing says whether prose has been written or an actor episode is
    waiting. This makes the harness answer the question the skill used to answer
    by prose: run `worldloom status`, do what it says, repeat.

    The stage order is the loop's own: an actor episode decides which documents
    exist, so it precedes prose; prose precedes rendering, because a rendered
    outline is a corpus that looks finished and is not.
    """
    import json as json_module

    from .narrative import handshake as narrate_handshake
    from .recipe import has_actor_step

    world = _load(corpus)

    # Compiled in memory only — status must never write. A read command that
    # mutates what it reports on cannot be trusted mid-loop.
    staged = world
    if not staged.artifact_irs and staged._artifact_intents:
        staged = staged.compile()

    actor_pending = has_actor_step(world.recipe) and not world._actor_ledger
    prose_pending = len(narrate_handshake.pending(staged)) if staged.artifact_irs else 0
    plans_accepted = any(entry.call_site.endswith("/plan") for entry in world.ledger)
    rendered = sum(1 for artifact in world.artifacts if artifact.path)
    report = world.validate()

    if actor_pending:
        stage, next_command = "awaiting actor decisions", f"worldloom act requests {corpus} -o decision.json"
    elif prose_pending:
        stage, next_command = (
            f"awaiting prose ({prose_pending} section(s))",
            f"worldloom narrate requests {corpus} -o requests.json",
        )
    elif not rendered:
        stage, next_command = "compiled, not rendered", f"worldloom render {corpus} -f markdown -f xlsx"
    elif not report.ok:
        stage, next_command = "rendered, with violations", f"worldloom validate {corpus}"
    else:
        stage, next_command = "complete and coherent", f"worldloom evaluate {corpus}"

    if as_json:
        typer.echo(json_module.dumps({
            "stage": stage,
            "next": next_command,
            "facts": len(world.facts),
            "artifact_intents": len(world.artifact_intents),
            "sections_awaiting_prose": prose_pending,
            "plans_accepted": plans_accepted,
            "rendered_files": rendered,
            "actor_episode_pending": actor_pending,
            "evaluation_cases": len(world.evaluations),
            "generated_by": world._generator_version,
            "validation": {
                "ok": report.ok,
                "checks": report.checks_run,
                "violations": [
                    {"group": v.group, "code": v.code, "subject": v.subject, "detail": v.detail}
                    for v in report.violations
                ],
            },
        }, indent=2))
        return

    table = Table(title=world.company.name, title_style="bold", show_header=False, box=None)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Stage", stage)
    table.add_row("Facts", f"{len(world.facts):,}")
    table.add_row("Artifact intents", f"{len(world.artifact_intents):,}")
    table.add_row("Awaiting prose", f"{prose_pending:,} section(s)")
    table.add_row("Plans accepted", "yes" if plans_accepted else "no (optional — worldloom plan requests)")
    table.add_row("Rendered files", f"{rendered:,}")
    table.add_row(
        "Validation",
        f"[green]coherent[/green] — {report.checks_run:,} checks"
        if report.ok
        else f"[red]{len(report.violations)} violation(s)[/red]",
    )
    console.print(table)
    console.print(f"\n[bold]next:[/bold] {next_command}")


@app.command()
def validate(
    corpus: str = typer.Argument(..., help="Bundled corpus name or path."),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit the report as JSON — violations as data, not prose to parse.",
    ),
) -> None:
    """Check a corpus for coherence violations."""
    if as_json:
        import json as json_module

        report = _load(corpus).validate()
        typer.echo(json_module.dumps({
            "ok": report.ok,
            "checks": report.checks_run,
            "violations": [
                {"group": v.group, "code": v.code, "subject": v.subject, "detail": v.detail}
                for v in report.violations
            ],
        }, indent=2))
        if not report.ok:
            raise typer.Exit(code=1)
        return
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
def evaluate(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    k: int = typer.Option(5, "-k", help="How many passages the baseline may return."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show every question."),
    as_json: bool = typer.Option(
        False, "--json",
        help=(
            "Emit the scorecard as JSON. This is the measure half of the "
            "measure-then-iterate loop — an agent deciding what to change next "
            "should read data, not parse a bar chart."
        ),
    ),
) -> None:
    """Score the built-in baseline retriever against the corpus's evaluation set.

    A *low* score on the hard question types is the good result. The baseline has
    no notion of when a document was written or how authoritative it is, so a
    corpus on which it does well on temporal and authority questions is a corpus
    that is not testing anything.
    """
    import json as json_module

    from .evaluate import score as run_score

    world = _compiled(_load(corpus), corpus)

    card = run_score(world, k=k)
    if as_json:
        typer.echo(json_module.dumps({
            "k": card.k,
            "overall": {"passed": card.passed, "total": len(card)},
            "by_type": {
                kind.value: {"passed": passed, "total": total}
                for kind, (passed, total) in sorted(
                    card.by_type().items(), key=lambda item: item[0].value
                )
            },
            "outcomes": [
                {
                    "case_id": outcome.case_id,
                    "type": outcome.evaluation_type.value,
                    "passed": outcome.passed,
                    "detail": outcome.detail,
                }
                for outcome in card.outcomes
            ],
        }, indent=2))
        return
    console.print(str(card))

    if verbose:
        console.print("")
        for outcome in card.outcomes:
            mark = "[green]✓[/green]" if outcome.passed else "[red]✗[/red]"
            console.print(f"  {mark} {outcome.case_id}  {outcome.evaluation_type.value}")
            console.print(f"      {outcome.detail}")


@app.command()
def diversity(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Show the per-artifact-type breakdown and every distinct shape within it.",
    ),
    check_quotas: bool = typer.Option(
        False, "--check-quotas",
        help=(
            "Exit non-zero if the batch fails a declared Quotas threshold (see "
            "compiler/diversity.py). For CI: assert the corpus does not get more "
            "monotonous over time."
        ),
    ),
) -> None:
    """Fingerprint every compilable artifact and report how structurally varied the batch is.

    `worldloom evaluate`'s sibling: that command asks whether the corpus is hard
    to retrieve from, this one asks whether it looks the same artifact repeated
    with different numbers. Neither question is answerable from one document —
    a single artifact cannot be "diverse", only a batch can (see
    `compiler.diversity`'s module docstring) — so this always reports on the
    whole corpus at once, the same way `evaluate` always scores the whole
    evaluation set at once.
    """
    from .compiler.compose import compose, plan_from_ir
    from .compiler.diversity import Fingerprint, Quotas, check, fingerprint, report
    from .render.docx import HANDLES as DOCX_ARTIFACT_TYPES
    from .render.xlsx import HANDLES as XLSX_ARTIFACT_TYPES

    world = _load(corpus)
    if not world.artifact_irs:
        try:
            world = world.compile()
        except ValueError:
            # A world with no artifact intents planned at all — `compile()` raises
            # rather than returning an empty result. Left uncaught this would be a
            # traceback for what is really the same case as `fingerprints` ending up
            # empty below: there is nothing yet for this command to fingerprint.
            # `world.artifact_irs` stays `()`, so the loop below simply does not run
            # and falls into that same "nothing compilable" branch — one message,
            # not two different tracebacks for two ways of having nothing.
            pass

    fingerprints: list[Fingerprint] = []
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        # A workbook composes with fmt="xlsx" — its lineage sheet is xlsx-only, so
        # composing it as "docx" raises `ValueError` about a component that does
        # not fit. Every other handled type composes with fmt="docx". Anything
        # neither renderer claims (a Jira, Confluence, or ServiceNow bundle) is a
        # record projection rather than a component composition (see
        # `docs/artifact-compiler.md` §9.5) and has no shape to fingerprint — the
        # same split `tests/test_diversity.py`'s own regression fixture draws.
        if intent.artifact_type in XLSX_ARTIFACT_TYPES:
            fmt = "xlsx"
        elif intent.artifact_type in DOCX_ARTIFACT_TYPES:
            fmt = "docx"
        else:
            continue
        plan = plan_from_ir(ir, artifact_type=intent.artifact_type, size_class=intent.size_profile)
        fingerprints.append(fingerprint(compose(plan, fmt=fmt)))

    if not fingerprints:
        console.print("[green]✓[/green] nothing compilable to fingerprint")
    else:
        batch = report(fingerprints)
        console.print(str(batch))

        if verbose:
            # `DiversityReport.__str__` already gives a distinct-shape *count* per
            # artifact type; verbose additionally names the shapes themselves —
            # the actual component sequences — so an agent deciding whether a
            # regression matters can see what repeated, not just how much did.
            console.print("")
            shapes_by_type: dict[str, dict[str, Fingerprint]] = {}
            for fp in fingerprints:
                shapes_by_type.setdefault(fp.artifact_type, {}).setdefault(fp.digest(), fp)
            for artifact_type, shapes in shapes_by_type.items():
                console.print(f"[bold]{artifact_type}[/bold]")
                for digest, fp in shapes.items():
                    shape = " → ".join(fp.components) if fp.components else "(no components)"
                    console.print(f"  [dim]{digest[:12]}[/dim]  {shape}")

    # Checked even when `fingerprints` is empty: an empty batch trivially meets
    # every quota (nothing to be repetitive or concentrated about yet — see
    # `check`'s own docstring), so `--check-quotas` must not fail a corpus that
    # simply has nothing in it yet.
    if check_quotas:
        violations = check(fingerprints, Quotas())
        if violations:
            err.print(f"\n[red]✗[/red] {len(violations)} quota violation(s)")
            for violation in violations:
                err.print(f"  [yellow]{violation.code}[/yellow] {violation.detail}")
            raise typer.Exit(code=1)


@app.command()
def actors(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    rejected: bool = typer.Option(
        False, "--rejected", help="Show only the calls that were refused, and why."
    ),
    observations: bool = typer.Option(
        False, "--observations", help="Show what each actor knew when it acted."
    ),
) -> None:
    """Show the actor execution ledger: who did what, on what they could see.

    The audit surface. `inspect` answers what the corpus contains; this answers
    how the incident's records came to exist — which accepted tool call produced
    each one, and which attempts were refused for exceeding a role's authority.
    Rejections are shown alongside acceptances rather than hidden, because a
    policy layer that never refuses anything is decoration.
    """
    world = _load(corpus)
    entries = list(world.actor_ledger)
    if not entries:
        console.print("[dim]no actor episode in this corpus[/dim]")
        return

    # An abstention is not a rejection. `--rejected` is for finding calls the
    # policy or a precondition refused; showing "I have nothing further to do"
    # alongside them would bury the interesting rows under the ordinary ones.
    shown = (
        [e for e in entries if not e.result.accepted and e.action.tool_name]
        if rejected
        else entries
    )
    table = Table(title="Actor execution ledger", box=None)
    table.add_column("#", style="dim", justify="right")
    table.add_column("when")
    table.add_column("role")
    table.add_column("tool")
    table.add_column("")
    table.add_column("changed", overflow="fold")
    for entry in shown:
        result = entry.result
        changed = ", ".join(
            [*result.fact_ids, *result.event_ids, *result.artifact_intent_ids, *result.task_ids]
        )
        table.add_row(
            str(entry.sequence),
            entry.acted_at.strftime("%Y-%m-%d %H:%M"),
            entry.invocation.role_key,
            entry.action.tool_name or "—",
            "[green]ok[/green]"
            if result.accepted
            else ("[dim]abstained[/dim]" if entry.action.tool_name is None else "[yellow]refused[/yellow]"),
            changed
            or (entry.action.abstention_reason if entry.action.tool_name is None else "")
            or (result.rejection_reason or ""),
        )
    console.print(table, "")

    if observations:
        # Deliberately per invocation rather than per call: what makes the ledger
        # worth reading is that two people woken by the same failure saw
        # different things, and that is a property of the invocation.
        seen: set[str] = set()
        table = Table(title="What each actor could see", box=None)
        table.add_column("role")
        table.add_column("at")
        table.add_column("facts", justify="right")
        table.add_column("messages", justify="right")
        table.add_column("tasks", justify="right")
        for entry in entries:
            if entry.invocation.id in seen:
                continue
            seen.add(entry.invocation.id)
            table.add_row(
                entry.invocation.role_key,
                entry.observation.observed_at.strftime("%Y-%m-%d %H:%M"),
                str(len(entry.observation.visible_fact_ids)),
                str(len(entry.observation.message_ids)),
                str(len(entry.observation.task_ids)),
            )
        console.print(table, "")


@pack_app.command("check")
def pack_check(
    source: Path = typer.Argument(..., help="Pack JSON file to validate and lint."),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit findings as JSON — an agent authoring a pack should read data.",
    ),
) -> None:
    """Validate a pack against the schema and lint its lore against the engine.

    Schema failures are errors. Lint findings are advisory — an inert lore
    constraint is legal — but each one is a place where the pack's intent and
    the engine's behaviour diverge, named before a corpus quietly ignores it.
    """
    import json as json_module

    from . import packs as packs_module

    try:
        loaded = packs_module.load(source)
    except Exception as exc:
        if as_json:
            typer.echo(json_module.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    findings = packs_module.lint(loaded)
    if as_json:
        typer.echo(json_module.dumps(
            {"ok": True, "name": loaded.name, "base": loaded.base, "findings": findings},
            indent=2,
        ))
        return
    console.print(f"[green]✓[/green] {loaded.name} validates against the {loaded.base} engine")
    for finding in findings:
        console.print(f"[yellow]•[/yellow] {escape(finding)}")
    if not findings:
        console.print("[dim]no lint findings — every commitment is load-bearing[/dim]")


@pack_app.command("targets")
def pack_targets(
    engine: str = typer.Argument(None, help="Engine name; omit to list every engine."),
) -> None:
    """List the lore targets each engine consults, and what each one changes.

    This is the pack author's contract: a lore constraint aimed at one of
    these targets changes generation; aimed anywhere else it is carried,
    citable, and inert. Persona traits are always consulted, as ROLE/trait.
    """
    from . import domains

    for name in domains.names():
        if engine is not None and name != engine:
            continue
        domain = domains.by_name(name)
        console.print(f"[bold]{name}[/bold]")
        console.print("  [underline]lore targets[/underline]")
        for target, effect in domain.consulted_targets:
            console.print(f"    {target}\n      [dim]{effect}[/dim]")
        console.print("    <role>/<trait>\n      [dim]persona_trait: adjusts how that role's holder writes[/dim]")
        console.print("  [underline]system slots (system_brands keys)[/underline]")
        for slot, what in domain.system_slots:
            console.print(f"    {slot}\n      [dim]{what}[/dim]")
        console.print(
            "  [underline]roles (voices keys, persona_trait targets)[/underline]\n"
            f"    {', '.join(domain.role_keys)}\n"
            f"    [dim]plus one per unit key with suffix {', '.join(domain.unit_role_suffixes)}[/dim]"
        )


@pack_app.command("texts")
def pack_texts(
    engine: str = typer.Argument(..., help="Engine name: retail or banking."),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit both key → default-template tables as JSON, for an agent"
             " authoring overrides.",
    ),
) -> None:
    """List the engine's surface-text templates a pack may override.

    Two tables. `episode_text` covers every event sentence and prose fact the
    episode states; `evaluation_text` covers every question and authored
    answer the benchmark asks. An override in either re-voices the surface —
    the causality underneath (episode_text) or the fact graded against
    (evaluation_text) stays the engine's. An override may use any subset of
    its default's {placeholders} and no others.
    """
    import json as json_module

    from . import domains

    domain = domains.by_name(engine)
    if domain is None:
        err.print(f"[red]error:[/red] no engine named {engine!r}; registered: {', '.join(domains.names())}")
        raise typer.Exit(code=2)
    if as_json:
        typer.echo(json_module.dumps(
            {
                "episode_text": dict(domain.episode_text),
                "evaluation_text": dict(domain.evaluation_text),
            },
            indent=2,
        ))
        return
    console.print("[underline]episode_text[/underline]")
    for key, default in domain.episode_text:
        console.print(f"[bold]{key}[/bold]\n  [dim]{escape(default)}[/dim]")
    console.print("[underline]evaluation_text[/underline]")
    for key, default in domain.evaluation_text:
        console.print(f"[bold]{key}[/bold]\n  [dim]{escape(default)}[/dim]")


@pack_app.command("template")
def pack_template(
    engine: str = typer.Argument("retail", help="Engine the pack will run on: retail or banking."),
) -> None:
    """Print a minimal valid pack to start from.

    The shipped examples are the fuller reference: examples/packs/ carries a
    general insurer on the retail engine and a mutual bank on the banking one.
    """
    import json as json_module

    from . import domains

    if domains.by_name(engine) is None:
        err.print(f"[red]error:[/red] no engine named {engine!r}; registered: {', '.join(domains.names())}")
        raise typer.Exit(code=2)
    starter = {
        "name": "my-industry",
        "base": engine,
        "description": "One line on what kind of business this is",
        "company_name": "A Fictional Name",
        "industry": "Your industry",
        "currency": "AUD",
        "currency_unit": "millions" if engine == "banking" else "thousands",
        "annual_revenue": 1000 if engine == "banking" else 1_000_000,
        "employees": 5000,
        "units": [
            {
                "key": "main", "name": "Main Division", "kind": "your_kind", "share": 1.0,
                "categories": [
                    {"name": "First Product Line", "share": 0.6, "margin": 0.25},
                    {"name": "Second Product Line", "share": 0.4, "margin": 0.18},
                ],
                "site_formats": [{"name": "Site", "count": 10, "revenue_weight": 1.0}],
            }
        ],
        "lore": [
            {
                "kind": "decision",
                "assertion": "Something this company did years ago that still shapes how it fails.",
                "effective_from": "2023-01",
                "constrains": [
                    {
                        "kind": "event_likelihood",
                        "target": "data_quality_incident/collateral" if engine == "banking"
                        else "data_quality_incident/inventory",
                        "effect": "Why that decision makes this failure more likely",
                        "magnitude": 2.0,
                    }
                ],
            }
        ],
    }
    typer.echo(json_module.dumps(starter, indent=2))


@app.command()
def archetypes() -> None:
    """List the company shapes `build --archetype` accepts."""
    from . import archetypes as registry

    for key in registry.available():
        shape = registry.get(key)
        console.print(
            f"[bold]{key}[/bold]  {shape.label}\n"
            f"  {len(shape.units)} business units · {shape.category_count} categories · "
            f"{shape.site_count:,} sites · {shape.employees:,} employees"
        )


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(__version__)


@app.command()
def docs(
    check: bool = typer.Option(
        False, "--check", help="Exit non-zero if the checked-in reference is stale."
    ),
) -> None:
    """Regenerate the agent-facing command reference from this CLI."""
    from pathlib import Path

    from . import docs as generator

    target = Path(generator.REFERENCE_PATH)
    current = generator.reference()

    if check:
        existing = target.read_text() if target.exists() else ""
        if existing == current:
            console.print(f"[green]✓[/green] {target} is current")
            return
        # Deliberately not written in --check mode: the point is to fail the
        # build, and a checker that fixes the thing it is checking would make CI
        # pass while the commit stays wrong.
        console.print(f"[red]✗[/red] {target} is stale — run `worldloom docs`")
        raise typer.Exit(1)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(current)
    console.print(f"[green]✓[/green] wrote {target}")


if __name__ == "__main__":  # pragma: no cover
    app()
