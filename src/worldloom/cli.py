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
from typing import Any

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
compose_app = typer.Typer(
    no_args_is_help=True,
    help="Hand an agent the company's technology estate to author, and check it against the graph.",
)
app.add_typer(compose_app, name="compose")
probe_app = typer.Typer(
    no_args_is_help=True,
    help="Derive a world's physics by asking, one question at a time, under propagation.",
)
app.add_typer(probe_app, name="probe")

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


#: `--eval-density`'s named tiers, mapped to the numeric value that rides the
#: recipe. Named rather than a bare float on the CLI for the same reason
#: `--actors` takes `scripted`/`agent` rather than an internal class name: the
#: three words are what a user reasons about, and the float is an
#: implementation detail `MonthEndClose.eval_density` happens to want. `1.0`
#: is `standard` and not, say, `0`, because it is also the multiplier the
#: knob's consumers apply to their own counts — see `scenarios.py` and
#: `generators/evaluation.py`'s docstrings for what each value changes.
_EVAL_DENSITY_LEVELS: dict[str, float] = {"low": 0.0, "standard": 1.0, "high": 2.0}


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
    estate: str = typer.Option(
        None, "--estate",
        help=(
            "Grow a service landscape around the episode's own services: small, "
            "medium or large. Without it the estate is the four services and five "
            "systems the close names and nothing else — nine nodes whether the "
            "archetype has three stores or sixteen hundred, so nothing has a blast "
            "radius and `worldloom topology` has little to read. Omit it and every "
            "existing corpus is byte-identical."
        ),
    ),
    physics: Path = typer.Option(
        None, "--physics",
        help=(
            "Build under overridden world physics: a JSON file of parameter ranges, "
            "as `worldloom probe resolve` writes and `worldloom pack params` lists. "
            "This is what makes a pack able to say the company is a jeweller rather "
            "than a grocer with the labels changed. Only the ranges that differ from "
            "the engine's are recorded, so a file restating the defaults builds a "
            "byte-identical corpus."
        ),
    ),
    trend: float = typer.Option(
        0.0, "--trend",
        help=(
            "Monthly compound growth behind the comparative history, as a fraction "
            "(0.004 is about 5%/year). Without it a year of comparatives oscillates "
            "around a flat level, so a seasonally-adjusted series is flat by "
            "construction and no question about direction has an answer in the data. "
            "Needs --comparatives. 0.0 reproduces every existing corpus byte for byte."
        ),
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
    eval_density: str = typer.Option(
        "standard", "--eval-density",
        help=(
            "How much of the world's own size the evaluation set and its fan-out "
            "documents are allowed to exploit: `low` trims the optional close "
            "documents to the floor a benchmark needs; `standard` is today's "
            "corpus, unchanged; `high` adds direct-lookup, comparison, and "
            "cross-period cases (and the documents to source them from) that only "
            "exist once a world has more units, categories, sites, or periods to "
            "ask about. `standard` reproduces every existing corpus byte for byte."
        ),
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
    distractors: int = typer.Option(
        0, "--distractors",
        help=(
            "Add this many provenance-true noise artifacts once the episode(s) "
            "finish: superseded drafts, personal working copies, and routine "
            "notices — real authors, real dates, real facts, answering nothing "
            "an evaluation case needs. 0 (the default) touches nothing."
        ),
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

    if eval_density not in _EVAL_DENSITY_LEVELS:
        err.print(
            f"[red]error:[/red] --eval-density takes {', '.join(_EVAL_DENSITY_LEVELS)},"
            f" not {eval_density!r}"
        )
        raise typer.Exit(code=2)
    eval_density_value = _EVAL_DENSITY_LEVELS[eval_density]
    if distractors < 0:
        err.print("[red]error:[/red] --distractors takes a non-negative count")
        raise typer.Exit(code=2)

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

    # Resolved once, before anything is built, and applied to the builder *and*
    # every episode: the world's organisation and the episode's figures are
    # drawn under the same physics or the corpus is internally inconsistent
    # about what kind of company it is.
    from .parameters import DEFAULT as _DEFAULT_PHYSICS

    physics_value = _DEFAULT_PHYSICS
    if physics is not None:
        from .parameters import overrides_from

        try:
            document = json.loads(physics.read_text(encoding="utf-8"))
            physics_value = _DEFAULT_PHYSICS.with_overrides(
                overrides_from(document.get("overrides", document))
            )
        except (OSError, AttributeError, KeyError, ValueError, json.JSONDecodeError) as exc:
            err.print(f"[red]error:[/red] {physics}: {escape(str(exc))}")
            raise typer.Exit(code=2) from exc

    def _under_physics(spec: Any) -> Any:
        """*spec* rebound to the requested physics, untouched on the default path.

        Untouched rather than always rebound so that a domain registered
        outside this repository — which may have no ``physics`` field — keeps
        building exactly as it did.
        """
        if physics_value is _DEFAULT_PHYSICS:
            return spec
        from dataclasses import replace as _replace_physics

        try:
            return _replace_physics(spec, physics=physics_value)
        except TypeError as exc:
            err.print(
                f"[red]error:[/red] --physics was given, but {type(spec).__name__}"
                f" does not accept any: {escape(str(exc))}"
            )
            raise typer.Exit(code=2) from exc

    if single_episode is not None:
        refused = [
            flag for flag, given in (
                ("--actors", actors is not None),
                ("--incident/--no-incident", incident is not None),
                ("--comparatives", comparatives > 0),
                # Same reasoning as its neighbour: the trend shapes retail's
                # comparative history, and a single-episode vertical has none.
                ("--trend", trend != 0.0),
                # Retail-only for now: the knob's growth (category commentary,
                # site-level cases) is argued entirely from retail's own
                # hierarchy in `scenarios.py`/`generators/evaluation.py`.
                # Refused rather than silently ignored at a non-default value,
                # same reasoning as its neighbours above; `standard` is a
                # no-op everywhere, so it alone is let through.
                ("--eval-density", eval_density != "standard"),
            ) if given
        ]
        if refused:
            err.print(
                f"[red]error:[/red] {', '.join(refused)} belong(s) to the retail close;"
                f" the {domain.name} vertical runs one episode per build"
            )
            raise typer.Exit(code=2)

        builder = _under_physics(
            domain.world.from_pack(pack_obj, seed=seed)
            if pack_obj is not None
            else domain.world(
                seed=seed, archetype=shape, employees=employees,
                # Every vertical has its own landscape vocabulary now
                # (`worldloom.landscape`), so this is no longer refused. It was
                # refused rather than mis-served for as long as the only pools
                # were retail's: a bank whose landscape is called
                # `click-collect-api` is worse than a bank with no landscape.
                **({} if estate is None else {"estate": estate}),
            )
        )
        world = builder.build()
        for index in range(max(1, periods)):
            world = world.run(_under_physics(
                single_episode(_step_period(period, index, domain.period_step_months))
            ))
    else:
        builder = _under_physics(
            RetailWorld.from_pack(pack_obj, seed=seed)
            if pack_obj is not None
            else RetailWorld(seed=seed, archetype=shape, employees=employees)
        )
        if estate is not None:
            from dataclasses import replace as _replace_builder

            builder = _replace_builder(builder, estate=estate)
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
    if actors == "agent" and distractors:
        err.print(
            "[red]error:[/red] --distractors belongs after the episode that plans "
            "the documents it drafts and copies; --actors agent exports before "
            "that episode has run"
        )
        raise typer.Exit(code=2)

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
                **({} if trend == 0.0 else {"trend_pct": trend}),
                # Only recorded away from its default — see `scenarios.py`'s
                # matching call for why an unconditional write here would
                # break the byte-identity gate every default build depends on.
                **({} if eval_density_value == 1.0 else {"eval_density": eval_density_value}),
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
                    trend_pct=trend if index == 0 else 0.0,
                    actors=actor_provider,
                    actor_ledger=actor_ledger,
                    eval_density=eval_density_value,
                    physics=physics_value,
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

    # After every episode this build runs, never before — a distractor drafts
    # or copies a real document the planner already produced, so it needs the
    # full plan (both branches above, single-episode or the retail loop) in
    # front of it, and it must run before `narrate`/`render` so its sections
    # enter the ordinary awaiting-prose pipeline rather than a second one.
    if distractors:
        from .generators import distractors as distractors_module

        world = distractors_module.apply(world, count=distractors)
        console.print(f"[dim]distractors:[/dim] {distractors} requested\n")

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
            # generating would not be a replay. Its id comes from what the
            # artifacts record as `narrated_by` — the id is a key component,
            # so replaying a corpus narrated by any other provider (anthropic,
            # gemini, a harness) under a fixed id missed every key. It is NOT
            # derived from the ledger's model_ids: an actor-mode corpus's
            # ledger legitimately carries the actor provider's entries beside
            # the narration's (CI's package job proved it, the first commit of
            # this fix having refused exactly that), and extra entries are
            # harmless — a key either matches or it doesn't.
            narrated_ids = {
                ir.metadata["narrated_by"]
                for ir in source._artifact_irs
                if "narrated_by" in ir.metadata
            }
            if len(narrated_ids) > 1:
                err.print(
                    f"[red]error:[/red] {replay} was narrated by several providers"
                    f" ({', '.join(sorted(narrated_ids))}); one narrate pass"
                    " replays one provider's keys"
                )
                raise typer.Exit(code=2)
            provider = (
                UnreachableProvider(id=narrated_ids.pop())
                if narrated_ids
                else UnreachableProvider()
            )

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

    # Responses supplied, and not one of them was even looked at. That happens
    # when every section already has prose, so `pending()` is empty and
    # `review()` has nothing to review — and it printed "✓ 0 section(s)
    # accepted" and exited zero, which is indistinguishable from success to
    # anything reading the exit code.
    #
    # It is not a corner. CI's agent-handshake step submits *deliberately
    # invalid* prose to prove the guardrail rejects it, and had been doing so
    # against an already-narrated corpus: the responses were never reviewed,
    # the step passed on a `FileExistsError` raised further down in `export`,
    # and when that unrelated bug was fixed the step failed and revealed that
    # the guardrail it names had not been exercised in a long time.
    if responses and not verdicts:
        err.print(
            f"[red]error:[/red] {len(responses)} response(s) supplied but this corpus"
            " has no section awaiting prose — nothing was reviewed and nothing was"
            " committed.\n[dim]Every section already carries prose. Run `worldloom"
            " status` to see where this corpus actually is; `worldloom refine` is what"
            " rewrites prose that already exists.[/dim]"
        )
        raise typer.Exit(code=2)

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
        help="Model id. A `gemini-*` id routes to the Gemini provider"
        " (`worldloom[gemini]`, GEMINI_API_KEY); anything else — and the"
        " default — routes to Anthropic (`worldloom[llm]`, ANTHROPIC_API_KEY)."
        " Defaults: `worldloom.narrative.ANTHROPIC_DEFAULT_MODEL` /"
        " `GEMINI_DEFAULT_MODEL`.",
    ),
    retries: int = typer.Option(
        2, "--retries",
        help="Rejections the compiler will absorb per section before giving up.",
    ),
    harness: str = typer.Option(
        None, "--harness",
        help="Answer each request with an agent harness instead of a bare model:"
        " `claude-code` (the claude CLI in headless mode, its own auth) or"
        " `antigravity` (a Google Antigravity Agent; `worldloom[antigravity]`,"
        " GEMINI_API_KEY). `--model` passes through to the harness.",
    ),
    concurrency: int = typer.Option(
        1, "--concurrency",
        help="Live generation calls to run at once, across a thread pool. 1 (the"
        " default) opens no thread pool at all — today's behaviour, byte for"
        " byte. Raising it only changes when calls happen: the recorded ledger"
        " is identical at any concurrency, because completion order never"
        " reaches it (see narrative/compiler.py's module docstring).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the confirmation prompt after the preflight summary. Always"
        " skipped when stdin is not a terminal (CI, a script) — the summary is"
        " still printed either way.",
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

    Before a single call, a preflight prints how many sections are total,
    already in the ledger, already checkpointed, and left to call live, plus
    the provider id and a rough token estimate — see `tests/test_narrate_concurrency.py`.
    Accepted sections persist incrementally to `narration-checkpoint.jsonl`
    inside *corpus* as they land, so a crash or an interrupted run loses no
    paid model output: rerunning this exact command resumes, replaying every
    checkpointed section instead of calling for it again. A section that
    exhausts its retry budget still aborts the run — `NarrationError`, exit
    code 2 — but everything accepted before that point is already safe on
    disk, and the error says how many sections and that rerunning resumes.
    The sidecar is deleted once a run completes successfully; a corpus that
    finished without ever crashing is byte-identical to one narrated with no
    checkpointing at all.
    """
    import os
    import sys

    from .narrative import (
        ANTHROPIC_DEFAULT_MODEL,
        AnthropicProvider,
        AntigravityProvider,
        ClaudeCodeProvider,
        GeminiProvider,
        NarrationError,
        ProviderError,
        checkpoint,
        compiler,
    )

    if concurrency < 1:
        err.print(f"[red]error:[/red] --concurrency must be at least 1, not {concurrency}")
        raise typer.Exit(code=2)

    # `--harness` names an agent runtime and overrides the model-prefix
    # routing below — a harness picks (or is told) its model itself, so the
    # prefix stops being the routing signal the moment one is named.
    if harness is not None:
        if harness == "claude-code":
            # Preflight here, not just in the provider, so the failure comes
            # before a corpus is loaded — same shape as the key checks below.
            import shutil as _shutil

            if _shutil.which("claude") is None:
                err.print(
                    "[red]error:[/red] --harness claude-code needs the `claude`"
                    " CLI on PATH. Install it from https://claude.com/claude-code"
                    " and run it once to authenticate."
                )
                raise typer.Exit(code=2)
            make_provider = lambda: ClaudeCodeProvider(model=model)  # noqa: E731
        elif harness == "antigravity":
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                err.print(
                    "[red]error:[/red] --harness antigravity needs GEMINI_API_KEY"
                    " (GOOGLE_API_KEY also works). Export one before running"
                    " `worldloom narrate auto`."
                )
                raise typer.Exit(code=2)
            make_provider = lambda: AntigravityProvider(model=model, api_key=api_key)  # noqa: E731
        else:
            err.print(
                f"[red]error:[/red] --harness takes claude-code or antigravity, not {harness!r}"
            )
            raise typer.Exit(code=2)
    # Routed by model-id prefix rather than a separate --provider flag: every
    # Gemini id starts with "gemini-" and no Anthropic id does, so the prefix
    # is unambiguous, and one flag that means one thing beats two flags that
    # can contradict each other.
    elif model and model.startswith("gemini"):
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            err.print(
                "[red]error:[/red] GEMINI_API_KEY is not set (GOOGLE_API_KEY also"
                " works). Export one before running `worldloom narrate auto`."
            )
            raise typer.Exit(code=2)
        make_provider = lambda: GeminiProvider(model=model, api_key=api_key)  # noqa: E731
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            err.print(
                "[red]error:[/red] ANTHROPIC_API_KEY is not set."
                " Export it before running `worldloom narrate auto`."
            )
            raise typer.Exit(code=2)
        make_provider = lambda: AnthropicProvider(  # noqa: E731
            model=model or ANTHROPIC_DEFAULT_MODEL, api_key=api_key
        )

    world = _compiled(_load(corpus), corpus)

    # A crash-and-resume sidecar, not a corpus file — see narrative/checkpoint.py.
    # Loaded before the provider is even asked anything, so a rerun after a
    # crash sees exactly what the interrupted run already paid for.
    checkpoint_path = Path(corpus) / checkpoint.FILENAME
    checkpointed = checkpoint.load(checkpoint_path)
    checkpoint_keys = frozenset(entry.key for entry in checkpointed)
    ledger = tuple(world._ledger) + checkpointed

    try:
        provider = make_provider()
        plan = compiler.preflight(world, provider, ledger=ledger)
    except (ProviderError, NarrationError) as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    # `preflight`'s `replay_keys` doesn't know which ledger a hit came from —
    # split it here by intersecting with the checkpoint's own keys, so the
    # summary can tell "already in this corpus's ledger" apart from
    # "recovered from an interrupted run", which are different facts about
    # the corpus even though `narrate()` treats both as an ordinary replay.
    from_checkpoint = len(plan.replay_keys & checkpoint_keys)
    from_ledger = len(plan.replay_keys) - from_checkpoint
    # `~4 chars/token` is the standard rough-English heuristic — the count it
    # is applied to (`live_prompt_chars`) is exact, not guessed: the sum of
    # what `Prompt.render()` will actually send for every live call.
    token_estimate = plan.live_prompt_chars // 4

    console.print(f"[bold]narrate auto[/bold] preflight — [bold]{corpus}[/bold]")
    console.print(f"  sections total             {plan.total_sections:,}")
    console.print(f"  replayed from ledger        {from_ledger:,}")
    console.print(f"  replayed from checkpoint    {from_checkpoint:,}")
    console.print(f"  live calls to make          {plan.live_count:,}")
    console.print(f"  provider                    {provider.id}")
    console.print(
        f"  prompt size                 {plan.live_prompt_chars:,} chars"
        f" (~{token_estimate:,} tokens, rough)\n"
    )

    if plan.live_count and not yes and sys.stdin.isatty():
        if not typer.confirm("Proceed?", default=False):
            console.print("[yellow]aborted[/yellow] — no call was made.")
            raise typer.Exit(code=0)

    writer = checkpoint.Writer(checkpoint_path)
    try:
        narrated = world.narrate(
            provider, ledger=ledger, retries=retries,
            concurrency=concurrency, on_accepted=writer,
        )
    except (ProviderError, NarrationError) as exc:
        writer.close()
        safe = len(checkpoint.load(checkpoint_path))
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        if safe:
            err.print(
                f"[yellow]{safe} section(s)[/yellow] accepted before this failure"
                f" are safe in [bold]{checkpoint_path}[/bold]. Rerunning this exact"
                " command resumes from there instead of paying for them again."
            )
        raise typer.Exit(code=2) from exc
    writer.close()

    written = narrated.export(corpus, overwrite=True)
    # Only reached after a full success — an aborted run above never calls
    # this, so its checkpoint stays on disk for the next attempt to find.
    checkpoint.consume(checkpoint_path)

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


@compose_app.command("requests")
def compose_requests(
    corpus: str = typer.Argument(..., help="Corpus path or bundled name."),
    out: Path = typer.Option(None, "--out", "-o", help="Write JSON here instead of stdout."),
) -> None:
    """Emit the request an agent needs to author this company's estate.

    One request, not one per document: an estate is a graph, and asking for it
    a node at a time would mean no proposal could ever be checked for the
    property that matters — whether the whole thing is coherent.

    The request is self-contained. It carries the company and its units, every
    system and service that already exists (including what each depends on),
    the people who could own something, the closed constraint vocabulary lore
    may use, and the grammar in plain sentences. An agent should not need to
    read this repository to answer, and a rule it cannot see is a rejection it
    could not have predicted.
    """
    import json as json_module

    from . import compose as compose_module

    world = _load(corpus)
    document = compose_module.requests_document(world)
    payload = json_module.dumps(document, indent=2)
    if out is None:
        typer.echo(payload, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        console.print(
            f"[green]✓[/green] estate request written to [bold]{out}[/bold]"
            f"\n[dim]{len(document['existing_services'])} service(s) and"
            f" {len(document['existing_systems'])} system(s) already exist; up to"
            f" {document['budget']['max_services']} more may be proposed.[/dim]"
        )


@compose_app.command("accept")
def compose_accept(
    corpus: str = typer.Argument(..., help="Corpus path to record the estate into."),
    source: Path = typer.Option(..., "--from", "-i", help="Response JSON from the agent."),
    model_id: str = typer.Option(
        "agent", "--model-id",
        help="Who composed it. Recorded in the ledger and part of the replay key.",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit the verdict as JSON — an agent fixing rejections should read data, not parse a table.",
    ),
) -> None:
    """Validate an agent-authored estate against the graph, and commit it or refuse all of it.

    The grammar is `worldloom.graphs`: the same reading `validate` and
    `topology` do. A cycle through any number of hops, a dependency that
    resolves to nothing, an owner who does not work here, a tier the graph
    contradicts, or an estate in which nothing is a single point of failure —
    each is refused with the rule it broke, and every violation is reported at
    once rather than one per round.

    All-or-nothing. A partial commit would leave a corpus half-composed with no
    record of which half, and the half that landed is the half nobody reviewed.
    """
    import json as json_module

    from . import compose as compose_module

    world = _load(corpus)
    try:
        proposal = compose_module.Composition.model_validate(
            json.loads(source.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {source}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    result = compose_module.accept(world, proposal, model_id=model_id)

    if as_json:
        typer.echo(json_module.dumps({
            "accepted": result.accepted,
            "services_added": result.services_added,
            "systems_added": result.systems_added,
            "lore_added": result.lore_added,
            "rejections": [
                {"subject": r.subject, "rule": r.rule, "detail": r.detail}
                for r in result.rejections
            ],
        }, indent=2))
        if not result.accepted:
            raise typer.Exit(code=1)

    if not result.accepted:
        err.print(
            f"[red]✗[/red] {len(result.rejections)} violation(s). Nothing was committed."
        )
        for rejection in result.rejections:
            err.print(f"  [yellow]{rejection.rule}[/yellow] {rejection.subject}: {rejection.detail}")
        raise typer.Exit(code=1)

    assert result.world is not None
    written = result.world.export(corpus, overwrite=True)
    if not as_json:
        console.print(
            f"[green]✓[/green] estate accepted: {result.services_added} service(s),"
            f" {result.systems_added} system(s), {result.lore_added} lore commitment(s)"
            f"\n[dim]recorded in the generation ledger and on the recipe, so"
            f" `--replay` rebuilds it with no provider. Written to {written}."
            f"\nRead it with `worldloom topology {corpus}`.[/dim]"
        )


# ---------------------------------------------------------------------------
# probe — physics a model derives, rather than physics an engineer typed
# ---------------------------------------------------------------------------


def _probe_session(path: Path):  # type: ignore[no-untyped-def]
    from . import probe as probe_module

    try:
        return probe_module.Session.from_document(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {path}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc


def _write_probe(session, path: Path) -> None:  # type: ignore[no-untyped-def]
    path.parent.mkdir(parents=True, exist_ok=True)
    # `allow_nan=False` on purpose. An unbounded end must have been encoded as
    # null before it reaches here; if one slipped through as an infinity this
    # raises rather than writing `Infinity`, which Python reads back and no
    # other JSON parser does.
    path.write_text(json.dumps(session.document(), indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


@probe_app.command("open")
def probe_open(
    premise: str = typer.Option(..., "--premise", "-p",
                                help="What this business is, in a sentence or two."),
    out: Path = typer.Option(Path("probe.json"), "--out", "-o", help="Where to keep the probe."),
    depth: int = typer.Option(
        None, "--depth",
        help="How many levels of sub-question to allow. Two is a sketch; five is a business plan.",
    ),
) -> None:
    """Start a probe from a premise.

    Creates one question — the premise's own — and nothing else. Every quantity
    the world ends up with is raised by a model answering that, and then by
    answering what its own answers raised.
    """
    from . import probe as probe_module

    session = probe_module.Session(
        premise, probe_module.DEFAULT_MAX_DEPTH if depth is None else depth
    )
    _write_probe(session, out)
    console.print(
        f"[green]✓[/green] probe opened at [bold]{out}[/bold]"
        f"\n[dim]depth limit {session.max_depth}. Ask the first question with"
        f" `worldloom probe next {out}`.[/dim]"
    )


@probe_app.command("next")
def probe_next(
    path: Path = typer.Argument(Path("probe.json"), help="The probe to read."),
    out: Path = typer.Option(None, "--out", "-o", help="Write JSON here instead of stdout."),
) -> None:
    """Emit the next question, with the bounds earlier answers have left it.

    The bounds are the *propagated* ones, not the question's own declared
    range. That is the whole mechanism by which context shapes what a model may
    say: by the time margin is asked, sell-through and markdown have already
    squeezed it, and the model answers inside a box that earlier answers built.

    Exits 3 when the graph is settled, so a driving loop can tell "nothing left
    to ask" from "something went wrong" without parsing prose.
    """
    from . import probe as probe_module

    session = _probe_session(path)
    graph = session.graph
    brief = probe_module.frontier(graph)
    payload = json.dumps(
        probe_module.brief_document(brief, premise=session.premise), indent=2, allow_nan=False
    )
    if out is None:
        typer.echo(payload, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        console.print(f"[green]✓[/green] question written to [bold]{out}[/bold]")
    if brief is None:
        raise typer.Exit(code=3)


@probe_app.command("accept")
def probe_accept(
    path: Path = typer.Argument(Path("probe.json"), help="The probe to record into."),
    source: Path = typer.Option(..., "--from", "-i", help="Answer JSON from the agent."),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit the verdict as JSON — an agent fixing rejections should read data, not parse a table.",
    ),
) -> None:
    """Check one answer against the graph, and commit it or refuse all of it.

    Refused for widening a question it was meant to narrow, for raising a
    sub-question with no reasoning under it, for binding a terminal twice — and,
    once it is well-formed, for being unable to hold alongside everything
    already accepted. That last one is the interesting rejection: nobody wrote
    down which combinations are illegal, they fall out of propagating the
    relations the model itself supplied.
    """
    from . import probe as probe_module

    session = _probe_session(path)
    try:
        answer = probe_module.Answer.model_validate(
            json.loads(source.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {source}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    result = probe_module.accept(session.graph, answer)

    if as_json:
        typer.echo(json.dumps({
            "accepted": result.accepted,
            "raised": result.raised,
            "rejections": [
                {"subject": r.subject, "rule": r.rule, "detail": r.detail}
                for r in result.rejections
            ],
        }, indent=2))

    if not result.accepted:
        if not as_json:
            err.print(f"[red]✗[/red] {len(result.rejections)} violation(s). Nothing was committed.")
            for rejection in result.rejections:
                err.print(
                    f"  [yellow]{rejection.rule}[/yellow] {rejection.subject}:"
                    f" {escape(rejection.detail)}"
                )
        raise typer.Exit(code=1)

    _write_probe(session.committed(answer), path)
    if not as_json:
        console.print(
            f"[green]✓[/green] {answer.question} answered"
            + (f", raising {result.raised} sub-question(s)" if result.raised else "")
        )


@probe_app.command("show")
def probe_show(
    path: Path = typer.Argument(Path("probe.json"), help="The probe to read."),
) -> None:
    """The graph as it stands: what is settled, what it implies, what is missing."""
    from . import probe as probe_module

    session = _probe_session(path)
    graph = session.graph
    state = probe_module.propagate(graph)
    resolution = probe_module.resolve(graph)

    console.print(f"[bold]{escape(session.premise)}[/bold]\n")
    for node in graph.ordered:
        if node.key == probe_module.ROOT:
            continue
        bounds = state.domains.get(node.key, node.domain)
        mark = "[green]✓[/green]" if node.answered else "[yellow]?[/yellow]"
        bound = f" [dim]→ {node.binds}[/dim]" if node.binds else ""
        console.print(
            f"{'  ' * node.depth}{mark} [bold]{escape(node.key)}[/bold]"
            f" {bounds} {escape(node.unit)}{bound}"
        )
        if node.because:
            console.print(f"{'  ' * node.depth}  [dim]{escape(node.because)}[/dim]")

    for contradiction in resolution.contradictions:
        err.print(f"[red]✗[/red] {escape(str(contradiction))}")
    for missing in resolution.unbound:
        # Not a warning. A leaf the world needed and the engine cannot read is
        # the only honest evidence for growing the terminal registry, and it
        # only counts as evidence if it survives to be read.
        console.print(f"[magenta]unbound[/magenta] {escape(str(missing))}")
    if resolution.unanswered:
        console.print(f"\n[dim]{len(resolution.unanswered)} question(s) still open.[/dim]")


@probe_app.command("worlds")
def probe_worlds(
    path: Path = typer.Argument(Path("probe.json"), help="The probe to read."),
    count: int = typer.Option(5, "--count", "-n", help="How many worlds."),
    out: Path = typer.Option(None, "--out", "-o", help="Write JSON here instead of stdout."),
) -> None:
    """The worlds this probe allows, as unlike each other as possible.

    A settled probe does not describe one world. It describes a space — every
    assignment inside the narrowed ranges that also respects the relations —
    and taking the midpoint of each range, which is what resolving does,
    produces the single most average member of it.

    This covers the space with a low-discrepancy sequence rather than random
    draws, keeps the assignments that satisfy every relation, and returns the
    ones furthest apart by farthest-point traversal. Deterministic: the same
    graph gives the same mosaic every time.
    """
    from . import probe as probe_module

    session = _probe_session(path)
    try:
        found = probe_module.worlds(session.graph, count=count)
    except ValueError as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    document = {
        "premise": session.premise,
        "worlds": [world.as_dict() for world in found],
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        console.print(f"[green]✓[/green] {len(found)} world(s) written to [bold]{out}[/bold]")
        return

    keys = sorted({key for world in found for key in world.values})
    for index, world in enumerate(found, start=1):
        values = world.as_dict()
        console.print(f"[bold]world {index}[/bold] " + "  ".join(
            f"[dim]{escape(key)}[/dim] {values[key]:.4g}" for key in keys if key in values
        ))


@probe_app.command("resolve")
def probe_resolve(
    path: Path = typer.Argument(Path("probe.json"), help="The probe to resolve."),
    out: Path = typer.Option(None, "--out", "-o", help="Write the overrides here."),
) -> None:
    """Turn a settled graph into overrides for the terminal parameter registry.

    Refuses while anything is unanswered or contradictory: physics derived from
    a graph that does not yet hold would be a build calibrated against
    reasoning nobody finished.
    """
    from . import probe as probe_module

    session = _probe_session(path)
    resolution = probe_module.resolve(session.graph)

    if not resolution.usable:
        err.print("[red]✗[/red] this probe cannot produce physics yet.")
        for contradiction in resolution.contradictions:
            err.print(f"  [red]contradiction[/red] {escape(str(contradiction))}")
        for key in resolution.unanswered:
            err.print(f"  [yellow]unanswered[/yellow] {key}")
        raise typer.Exit(code=1)

    document = {
        "premise": session.premise,
        "overrides": {
            name: span.as_dict() for name, span in sorted(resolution.overrides.items())
        },
        "unbound": [
            {"key": u.key, "asks": u.asks, "claim": u.claim, "unit": u.unit,
             "low": u.bounds.low, "high": u.bounds.high}
            for u in resolution.unbound
        ],
    }
    payload = json.dumps(document, indent=2, allow_nan=False)
    if out is None:
        typer.echo(payload, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload + "\n", encoding="utf-8")
    console.print(
        f"[green]✓[/green] {len(resolution.overrides)} parameter(s) written to [bold]{out}[/bold]"
        + (f"\n[magenta]{len(resolution.unbound)} leaf/leaves bound to nothing[/magenta]"
           " [dim]— parameters this world wanted and the engine cannot read.[/dim]"
           if resolution.unbound else "")
    )


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
    # Reloaded from where the files actually landed, not validated in memory.
    # The in-memory world still resolves artifact paths against the *source*
    # corpus, so rendering to a `--out` directory reported every file it had
    # just written as missing — a false failure, and the loudest possible one,
    # since anyone running this in a pipeline reads it as rendering being
    # broken. Reloading also makes the check mean what it says: the artifact on
    # disk is the thing a reader will open.
    if not _report(_load(str(written))):
        raise typer.Exit(code=1)


@app.command()
def mosaic(
    count: int = typer.Option(5, "--count", "-n", help="How many worlds."),
    seed: int = typer.Option(8128, "--seed", "-s", help="Base seed. World N uses seed+N-1."),
    engine: str = typer.Option(
        "retail", "--engine", "-e",
        help="Which vertical to build: retail, banking or insurance. Each varies"
             " its own physics — a bank's capital headroom, an insurer's tail"
             " length — because a mosaic that moved a retailer's margin through a"
             " bank would report varying something it had not.",
    ),
    out: Path = typer.Option(None, "--out", "-o", help="Directory to write the worlds into."),
    period: str = typer.Option("2026-03", "--period", "-p", help="Reporting period, YYYY-MM."),
    periods: int = typer.Option(1, "--periods", help="Consecutive periods per world."),
    incident: bool = typer.Option(
        None, "--incident/--no-incident",
        help="Force the operational incident. Omit to let each world's seed and lore decide.",
    ),
    describe: bool = typer.Option(
        False, "--describe", help="Print what a mosaic varies, and build nothing.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit the plan as data."),
) -> None:
    """Build several companies at once, as unlike each other as the rules allow.

    Varying the seed does not do this. A seed decides names, figures, and which
    month the incident lands in; it does not decide headcount, span of control,
    reporting depth, trading calendar, or how fast an organisation finds the
    cause of an outage. Five seeds produce one company with different names on
    the same twenty-three people — which is a fine corpus and a poor dataset,
    because a model evaluated against it has seen one enterprise five times.

    Candidates are covered with a low-discrepancy sequence rather than drawn at
    random (random points clump, and a clump is a company shape the tool never
    produces), filtered to the ones that can actually be built, and then the
    furthest apart are chosen by farthest-point traversal. Deterministic: the
    same request gives the same mosaic, and each world carries a recipe that
    rebuilds it on its own.

    `--describe` prints the axes without building anything, which is the right
    first call — deciding whether five worlds are worth the wait should not
    require generating five worlds.
    """
    from . import mosaic as mosaic_module

    if describe:
        try:
            document = mosaic_module.describe(engine)
        except KeyError as exc:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
        if as_json:
            typer.echo(json.dumps(document, indent=2))
            return
        console.print(f"[bold]What a {engine} mosaic varies[/bold]"
                      f" [dim]— engines: {', '.join(document['engines'])}[/dim]\n")
        for axis in document["axes"]:
            bound = f"{axis['low']:g}–{axis['high']:g}"
            console.print(f"[bold]{escape(axis['name'])}[/bold] [cyan]{bound}[/cyan]"
                          + (f" [dim]→ {axis['parameter']}[/dim]" if axis["parameter"] else ""))
            console.print(f"  [dim]{escape(axis['about'])}[/dim]")
        console.print(f"\n[dim]estates: {', '.join(document['estates'])}[/dim]")
        if document.get("calendars"):
            console.print(f"[dim]calendars: {', '.join(document['calendars'])}[/dim]")
        return

    try:
        variants = mosaic_module.field(count, seed=seed, engine=engine)
    except (KeyError, ValueError) as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    spread = mosaic_module.spread(variants)
    if as_json:
        typer.echo(json.dumps(
            {"spread": spread, "worlds": [v.as_dict() for v in variants]}, indent=2))
        if out is None:
            return

    if out is None:
        console.print("[bold]The mosaic[/bold] [dim]— nothing written; pass --out to build[/dim]\n")
        for variant in variants:
            console.print(f"  [bold]{variant.index}[/bold] seed {variant.seed}"
                          f"  {escape(variant.summary())}")
        console.print(
            f"\n[dim]{spread['distinct_shapes']} distinct shape(s),"
            f" headcounts {spread['headcounts']}, spans {spread['spans']},"
            f" estates {spread['estates']}.[/dim]"
        )
        return

    from dataclasses import replace as _replace_spec

    from . import archetypes, domains
    from .scenarios import MonthEndClose

    # The domain names its own archetype. Core may not hold a map from a
    # vertical's name to one of its archetype keys — the thin-waist ratchet
    # forbids engine vocabulary here, and it caught exactly that map when this
    # was first written.
    registered = domains.by_name(engine)
    if registered is None or not registered.default_archetype:
        err.print(f"[red]error:[/red] no domain named {engine!r} is registered;"
                  f" known: {', '.join(domains.names())}")
        raise typer.Exit(code=2)
    domain = registered
    shape = archetypes.get(domain.default_archetype)

    written: list[str] = []
    for variant in variants:
        spec = domain.world(seed=variant.seed, archetype=shape)
        changes: dict[str, Any] = {
            "physics": variant.physics,
            "role_table": variant.role_table(),
        }
        if variant.estate is not None:
            changes["estate"] = variant.estate
        # Only the retail engine reads a trading year, and only its mosaic
        # varies one — handing a bank's world a `seasonality` it has no field
        # for would fail on a keyword rather than on a decision.
        if any(axis.name == "calendar" for axis in mosaic_module.ENGINES[engine]):
            changes["seasonality"] = variant.seasonality
        world = _replace_spec(spec, **changes).build()

        for index in range(max(1, periods)):
            stamp = _step_period(period, index, domain.period_step_months)
            if domain.single_episode is not None:
                episode = _replace_spec(domain.single_episode(stamp),
                                        physics=variant.physics)
            else:
                episode = MonthEndClose(
                    period=stamp,
                    include_operational_incident=incident,
                    physics=variant.physics,
                    seasonality=variant.seasonality,
                )
            world = world.run(episode)
        target = out / f"world-{variant.index:02d}"
        written.append(str(world.export(target, overwrite=True)))
        report = world.validate()
        mark = "[green]✓[/green]" if report.ok else "[red]✗[/red]"
        console.print(f"{mark} [bold]world {variant.index}[/bold] {escape(variant.summary())}"
                      f" [dim]— {report.checks_run} checks,"
                      f" {len(report.violations)} violation(s)[/dim]")
        if not report.ok:
            for violation in report.violations[:3]:
                err.print(f"    [yellow]{violation.code}[/yellow] {escape(violation.detail)}")

    (out / "mosaic.json").write_text(
        json.dumps({"seed": seed, "spread": spread,
                    "worlds": [v.as_dict() for v in variants]}, indent=2) + "\n",
        encoding="utf-8",
    )
    console.print(
        f"\n[green]✓[/green] {len(written)} world(s) written under [bold]{out}[/bold]"
        f"\n[dim]{spread['distinct_shapes']} distinct organisation shape(s);"
        f" headcounts {spread['headcounts']}; estates {spread['estates']}."
        f" The plan is in mosaic.json, and each world rebuilds from its own recipe.[/dim]"
    )


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


def _card_json(card: Any) -> dict[str, Any]:
    """A `Scorecard` as the JSON fragment shared by every `evaluate` shape below.

    Factored out so the single-retriever payload (`{k, overall, by_type,
    outcomes}`, unchanged since before `--retriever` existed) and each entry
    under `"retrievers"` in the `both` payload are built from one place — two
    copies of this dict comprehension drifting apart is exactly the kind of
    thing that would go unnoticed until an agent's `--json` parsing broke on
    one shape and not the other.
    """
    return {
        "overall": {"passed": card.passed, "total": len(card)},
        "by_type": {
            kind.value: {"passed": passed, "total": total}
            for kind, (passed, total) in sorted(card.by_type().items(), key=lambda item: item[0].value)
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
    }


@app.command()
def evaluate(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    k: int = typer.Option(5, "-k", help="How many passages a retriever may return."),
    retriever: str = typer.Option(
        "bm25", "--retriever",
        help=(
            "bm25 (default — the original baseline, unchanged), tfidf "
            "(vector-space cosine, a genuinely different ranking family — see "
            "src/worldloom/evaluate/tfidf.py), or both (side by side, with a "
            "per-family agreement reading: a family low under both retrievers "
            "is structurally hard, not hard for one heuristic)."
        ),
    ),
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
    """Score one or both baseline retrievers against the corpus's evaluation set.

    A *low* score on the hard question types is the good result. Neither
    retriever has any notion of when a document was written or how authoritative
    it is, so a corpus on which they do well on temporal and authority questions
    is a corpus that is not testing anything. `--retriever both` is the stronger
    claim: a family low under BM25 *and* TF-IDF cosine — two different ranking
    families — is hard because of the corpus, not because of which keyword
    heuristic happened to be asked.
    """
    import json as json_module

    from .evaluate import RETRIEVERS, compare, render_agreement
    from .evaluate import score as run_score

    if retriever != "both" and retriever not in RETRIEVERS:
        raise typer.BadParameter(f"must be one of {sorted([*RETRIEVERS, 'both'])}", param_hint="--retriever")

    world = _compiled(_load(corpus), corpus)

    if retriever == "both":
        cards = {name: run_score(world, k=k, retriever=name) for name in sorted(RETRIEVERS)}
        findings = compare(cards)
        if as_json:
            # A new top-level shape, not a variant of the single-retriever one —
            # `retriever="both"` is a capability nothing could request before
            # this flag existed, so there is no old consumer whose parsing this
            # could break. The single-retriever shape below (`bm25`, the
            # default, and `tfidf`) is untouched byte-for-byte.
            typer.echo(json_module.dumps({
                "retriever": "both",
                "k": k,
                "retrievers": {name: _card_json(card) for name, card in cards.items()},
                "agreement": {
                    finding.evaluation_type.value: {
                        "scores": {
                            name: {"passed": passed, "total": total}
                            for name, (passed, total) in finding.scores.items()
                        },
                        "disagreements": finding.disagreements,
                        "total": finding.total,
                        "finding": finding.finding,
                    }
                    for finding in findings
                },
            }, indent=2))
            return
        for name in sorted(cards):
            console.print(str(cards[name]))
            console.print("")
        console.print(render_agreement(findings))
        if verbose:
            for name in sorted(cards):
                console.print(f"\n[bold]{name}[/bold]")
                for outcome in cards[name].outcomes:
                    mark = "[green]✓[/green]" if outcome.passed else "[red]✗[/red]"
                    console.print(f"  {mark} {outcome.case_id}  {outcome.evaluation_type.value}")
                    console.print(f"      {outcome.detail}")
        return

    card = run_score(world, k=k, retriever=retriever)
    if as_json:
        # Exactly the pre-`--retriever` shape, plus one additive key naming
        # which retriever produced it — an old consumer reading `k`/`overall`/
        # `by_type`/`outcomes` sees the same thing it always has.
        typer.echo(json_module.dumps({"retriever": retriever, "k": card.k, **_card_json(card)}, indent=2))
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
    near_duplicates: bool = typer.Option(
        False, "--near-duplicates",
        help=(
            "Also group passages whose prose is near-identical, and name which "
            "artifacts they belong to. Structural sameness and prose sameness are "
            "different failures — a batch can carry twenty distinct shapes and still "
            "say the same sentences in all of them."
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
    from .compiler.diversity import collisions as diversity_collisions
    from .evaluate.index import passages
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
    # Kept beside the fingerprints rather than recovered by re-walking the IR:
    # `collisions()` returns positions, and a position is only useful if it can
    # be turned back into the artifact an author has to open.
    fingerprint_ids: list[str] = []
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
        fingerprint_ids.append(ir.id)

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

        # Which artifacts share a shape, not merely how many shapes there were.
        # A count is a metric; a list of the fourteen documents that are one
        # template is somewhere to go and look.
        repeated = diversity_collisions(fingerprints)
        if repeated:
            console.print("")
            console.print(f"[bold]shapes used by more than one artifact[/bold] ({len(repeated)})")
            for digest, members in repeated[:10]:
                names = ", ".join(fingerprint_ids[i] for i in members[:8])
                more = f" +{len(members) - 8}" if len(members) > 8 else ""
                console.print(f"  [dim]{digest[:12]}[/dim]  ×{len(members)}  {names}{more}")

    if near_duplicates:
        from .stats import near_duplicate_clusters

        pool = list(passages(world))
        groups = near_duplicate_clusters(pool)
        console.print("")
        if not groups:
            console.print("[green]✓[/green] no near-duplicate passages")
        else:
            console.print(f"[bold]near-duplicate passage groups[/bold] ({len(groups)})")
            for group in groups[:10]:
                where = ", ".join(sorted({pool[i].artifact_id for i in group}))
                console.print(f"  ×{len(group)}  {where}")
                console.print(f"      [dim]{pool[group[0]].text[:110]}…[/dim]")

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
def topology(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    limit: int = typer.Option(
        12, "--limit", "-n", help="How many services to list, most load-bearing first.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the reading as JSON — stable keys and ordering, safe to diff in CI.",
    ),
) -> None:
    """Read the corpus's graphs: what depends on what, and what nothing routes around.

    The estate has always been a graph — `depends_on`, `manager_id`,
    `derived_from`, a fact's `supersedes` — and nothing read it. This does.
    Services are ranked by *blast radius*, the number of things that fall over
    transitively when one does, and separately by *gates*, the number of things
    that have no second path to what it serves. Those are different questions:
    a well-replicated shared platform has a large blast radius and gates
    nothing, and a small unloved mapping job can gate the whole close.

    Two readings this is for. As an author: an archetype whose service
    catalogue is a flat list of unrelated names shows up here as zero
    dependency hops, and a world with no provenance depth is one whose
    documents never build on each other. As a corpus buyer: the ranking is
    *derived from the graph*, so it can disagree with the hand-declared
    `criticality_tier` — and a tier-4 service that seventeen things depend on
    is a finding, not a rounding error.

    Every number here is an exact count with ties broken on id. There is no
    centrality score anywhere in it, deliberately: see `graphs.py`'s module
    docstring on why a float from an iterative solver has no business
    deciding a rank in a corpus that must regenerate byte-for-byte.
    """
    import json as json_module

    from . import graphs as graphs_module

    world = _load(corpus)
    reading = graphs_module.analyse(world)

    if as_json:
        typer.echo(json_module.dumps({"corpus": corpus, **reading.as_dict()}, indent=2))
        return

    console.print(str(reading))

    if reading.services:
        console.print("")
        table = Table(title="Services and systems, by blast radius", box=None)
        table.add_column("id", style="dim")
        table.add_column("name")
        table.add_column("kind")
        table.add_column("tier", justify="right")
        table.add_column("depends on it", justify="right")
        table.add_column("blast", justify="right")
        table.add_column("gates", justify="right")
        for rank in reading.services[: max(1, limit)]:
            table.add_row(
                rank.id, rank.name, rank.kind,
                str(rank.tier) if rank.kind == "service" else "[dim]—[/dim]",
                str(rank.fan_in), str(rank.blast_radius),
                f"[yellow]{rank.gates}[/yellow]" if rank.gates else "0",
            )
        console.print(table)

    # Structural defects are printed rather than merely counted, because this
    # command is where someone looks when `validate` has already told them a
    # cycle exists and they need to see it. `validate` owns the pass/fail —
    # this stays a reading, and exits zero either way.
    for label, found in (
        ("dependency cycle", reading.dependency_cycles),
        ("reporting cycle", reading.reporting_cycles),
        ("provenance cycle", reading.provenance_cycles),
    ):
        for cycle in found:
            console.print(f"[red]✗[/red] {label}: {' → '.join(cycle)} → {cycle[0]}")
    for fact_id, superseding in reading.forked_supersessions:
        console.print(
            f"[red]✗[/red] forked supersession: {fact_id} superseded by {', '.join(superseding)}"
        )


#: Units that mean "this is a ratio, not a level". Listed rather than pattern-
#: matched because the three engines spell them differently ("percent", "pct",
#: "bps") and a substring test on "pct" would miss two of them — which is how
#: the default series pick landed on a margin percentage in the first place.
_RATIO_UNITS = frozenset({"percent", "pct", "bps", "ratio", "x"})


@app.command()
def series(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    kind: str = typer.Option(
        None, "--kind", help="Fact kind to read. Default: the longest series in the corpus.",
    ),
    subject: str = typer.Option(
        None, "--subject", help="Entity id the series is about. Default: whichever has the most periods.",
    ),
    cycle: int = typer.Option(
        None, "--cycle", help="Positions in the seasonal cycle. Default: 12 if the data reaches it, else half the series.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the decomposition as JSON — stable keys and ordering.",
    ),
) -> None:
    """Decompose a period-keyed fact series into trend, season, and what is left.

    A multi-period corpus carries a column of monthly figures and, until now,
    no way to ask what shape they have. This separates them: how fast the level
    is moving, how much of the movement is the calendar, and which periods are
    left over — the ones the trend and the season together do not explain.

    That last set is the interesting one. An incident month should sit outside
    the pattern, and if it does not, the corpus is claiming a disruption its own
    numbers do not show. Outliers are scored on **median absolute deviation**
    rather than a z-score, because an outlier inflates the standard deviation it
    would be measured against — a detector that hides its largest findings.

    Build a history worth decomposing with `--comparatives`, and give it a
    direction with `--trend`: without one the level is flat by construction and
    every seasonally-adjusted month looks like every other.
    """
    import json as json_module

    from . import series as series_module

    world = _load(corpus)

    # The longest series in the corpus, unless the caller named one. Grouped
    # on (kind, subject) because those two together are what a series *is*
    # here: one measure, about one entity, across periods.
    grouped: dict[tuple[str, str], dict[str, float]] = {}
    units: dict[tuple[str, str], str] = {}
    for fact in world.facts:
        if fact.period is None or fact.value is None or fact.is_superseded:
            continue
        if kind and fact.kind != kind:
            continue
        if subject and fact.subject != subject:
            continue
        grouped.setdefault((fact.kind, fact.subject), {})[fact.period] = fact.value.amount
        units.setdefault((fact.kind, fact.subject), fact.value.unit)

    if not grouped:
        err.print("[red]error:[/red] no period-keyed numeric facts match that kind/subject")
        raise typer.Exit(code=2)

    # Longest wins, and the ties are the interesting part: a retail close mints
    # a dozen kinds over the same twelve months, so length alone would pick
    # whichever sorted last — a business unit's margin *percentage* rather than
    # the group's revenue. Three tie-breaks, in order: company-level before a
    # unit's, an amount before a ratio, then the kind name. The middle one is
    # not cosmetic — decomposing a percentage multiplicatively asks how a ratio
    # grew, which is a question about two series at once and not the one the
    # output claims to answer. The result is still a pure function of the
    # corpus.
    (chosen_kind, chosen_subject), points = min(
        grouped.items(),
        key=lambda row: (
            -len(row[1]),
            row[0][1] != world.company.id,
            units.get(row[0], "") in _RATIO_UNITS,
            row[0][0],
            row[0][1],
        ),
    )
    periods = sorted(points)
    values = [points[p] for p in periods]

    span = cycle or (12 if len(values) >= 24 else max(2, len(values) // 2))
    try:
        decomposition = series_module.decompose(values, period=span)
    except ValueError as exc:
        err.print(
            f"[red]error:[/red] {escape(str(exc))}\n"
            "[dim]Build a longer history with --comparatives, or name a shorter "
            "--cycle.[/dim]"
        )
        raise typer.Exit(code=2) from exc

    outliers = series_module.anomalies(decomposition)
    expected = decomposition.extend(1)

    if as_json:
        typer.echo(json_module.dumps({
            "corpus": corpus,
            "kind": chosen_kind,
            "subject": chosen_subject,
            "cycle": span,
            "periods": periods,
            "values": list(decomposition.values),
            "trend": list(decomposition.trend),
            "seasonal": list(decomposition.seasonal),
            "residual": list(decomposition.residual),
            "seasonal_indices": list(decomposition.seasonal_indices),
            "growth_per_period": decomposition.growth_per_period,
            "anomalies": [
                {"period": periods[index], "score": score} for index, score in outliers
            ],
            "next_expected": list(expected),
        }, indent=2))
        return

    growth = decomposition.growth_per_period
    console.print(
        f"[bold]{chosen_kind}[/bold] for {chosen_subject} — {len(values)} period(s),"
        f" cycle of {span}"
    )
    console.print(f"  trend                 {decomposition.trend[0]:,.0f} → {decomposition.trend[-1]:,.0f}"
                  f"  ({growth * 100:+.2f}% per period)")
    console.print(f"  seasonal amplitude    {decomposition.seasonal_amplitude:.3f}"
                  f"  (peak-to-trough, as a multiple of normal)")
    console.print(f"  next period expected  {expected[0]:,.0f}" if expected else "")
    if cycle is None and span != 12:
        # Said out loud rather than left in the header, because a fallback
        # cycle on monthly data aliases: a December spike folded into a
        # six-position cycle reappears as a mirrored dip in June, and the
        # outlier column will faithfully flag both. A monthly series needs 24
        # observations before a 12-cycle has more than one number per index.
        console.print(
            f"  [dim]cycle of {span} is a fallback: {len(values)} observations cannot"
            " support the 12 a monthly series wants (24 are needed). Positions alias"
            " onto each other, so read the outliers as pairs. Build with"
            " --comparatives 23, or name a --cycle.[/dim]"
        )

    table = Table(box=None)
    table.add_column("period")
    table.add_column("actual", justify="right")
    table.add_column("trend", justify="right")
    table.add_column("season", justify="right")
    table.add_column("residual", justify="right")
    table.add_column("")
    flagged = dict(outliers)
    for index, period in enumerate(periods):
        table.add_row(
            period,
            f"{decomposition.values[index]:,.0f}",
            f"{decomposition.trend[index]:,.0f}",
            f"{decomposition.seasonal[index]:.3f}",
            f"{decomposition.residual[index]:.3f}",
            f"[yellow]outlier {flagged[index]:+.1f}[/yellow]" if index in flagged else "",
        )
    console.print(table)

    if not outliers:
        console.print(
            "[dim]No period departs from the fitted trend and season. On a corpus "
            "with an incident in it, that is a finding: the disruption the "
            "documents describe is not visible in the figures.[/dim]"
        )


@app.command()
def mcp(
    tools: bool = typer.Option(
        False, "--tools", help="List the tools and exit, without starting a server.",
    ),
) -> None:
    """Serve Worldloom's measurements and gates as MCP tools, over stdio.

    Every other agent path here makes the agent a *function*: the CLI renders a
    request, the agent answers it once, the CLI validates. That cannot run a
    loop — it can only be run by one. Refinement is iterative by nature (measure,
    fix the worst thing, measure again), so the algorithms become tools and the
    agent holds the loop.

    What does not move is the division of labour: `next_target` is chosen by the
    measurement rather than by the agent's sense of what looks repetitive, and
    `submit_section` runs the same claim, reference and entity validators a first
    draft goes through plus the similarity gate. An agent cannot talk its way
    past any of it, which is what makes handing over the loop safe.

    `.mcp.json` at the repository root wires this into Claude Code, and the
    `worldloom-refine` skill drives it.
    """
    from . import mcp as mcp_module

    if tools:
        for tool in mcp_module.TOOLS:
            console.print(f"[bold]{tool['name']}[/bold]")
            console.print(f"  [dim]{tool['description']}[/dim]")
            required = tool["schema"].get("required", [])
            console.print(f"  [dim]required: {', '.join(required) or '(none)'}[/dim]\n")
        return

    try:
        mcp_module.serve()
    except RuntimeError as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc


@app.command()
def refine(
    corpus: str = typer.Argument(..., help="Corpus path to refine in place."),
    rounds: int = typer.Option(
        3, "--rounds", help="How many measure-target-rewrite passes to run at most.",
    ),
    budget: int = typer.Option(
        16, "--budget", help="Sections to rewrite per round. The loop's cost ceiling.",
    ),
    harness: str = typer.Option(
        "claude-code", "--harness",
        help="Who writes the rewrites: `claude-code` (the claude CLI headless, its own"
        " auth), `antigravity`, or `fake` for the deterministic stand-in — which writes"
        " no real prose and exists so the loop is testable with no model.",
    ),
    model: str = typer.Option(None, "--model", help="Model id, passed to the harness."),
    retries: int = typer.Option(
        2, "--retries", help="Rejections absorbed per section before it is left alone.",
    ),
    check: bool = typer.Option(
        False, "--check",
        help="Measure and report only. Exits non-zero if anything still repeats — for"
        " CI, and for a hook that wants to know whether a loop is finished.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit the measurements as JSON."),
) -> None:
    """Measure what a corpus repeats, rewrite only what repeats, and prove it moved.

    The headless half of the refinement loop. `worldloom mcp` gives the same
    algorithms to an agent as tools so it can drive the loop itself; this drives
    the loop *at* an agent, one bounded request at a time, for CI and batches.
    Both run the identical targeting and the identical gate, so the interactive
    and headless paths cannot drift into two definitions of "better".

    The economics are the point. A three-period corpus has ~130 sections and ~16
    that actually duplicate each other. Re-narrating everything to fix them is
    what an open loop does; this rewrites the sixteen. Each rewrite is briefed
    with the passage it must stop resembling, and rejected — with the measured
    similarity — if it did not get far enough away.
    """
    import json as json_module

    from . import refine as refine_module

    world = _load(corpus)
    history = [refine_module.measure(world)]

    if check:
        outstanding = refine_module.targets(history[0], budget=1_000_000)
        if as_json:
            typer.echo(json_module.dumps(
                {**history[0].as_dict(), "outstanding": len(outstanding)}, indent=2
            ))
        else:
            console.print(str(history[0]))
            console.print(f"  {len(outstanding)} section(s) still worth rewriting")
        if outstanding:
            raise typer.Exit(code=1)
        return

    provider = _refine_provider(harness, model)
    console.print(str(history[0]))

    rewritten = failed = 0
    for round_number in range(1, max(1, rounds) + 1):
        targets = refine_module.targets(history[-1], budget=budget)
        if not targets:
            console.print("[green]✓[/green] nothing repeats — the loop is done")
            break
        console.print(
            f"\n[bold]round {round_number}[/bold] — {len(targets)} target(s)"
            f" of {history[-1].passages} passage(s)"
        )
        for target in targets:
            outcome = _rewrite_one(corpus, target, provider, retries=retries)
            if outcome:
                rewritten += 1
                console.print(f"  [green]✓[/green] {target.id}  {outcome}")
            else:
                failed += 1
                console.print(f"  [yellow]—[/yellow] {target.id}  left as it was")

        history.append(refine_module.measure(_load(corpus)))
        console.print(f"  {history[-1]}")
        if refine_module.plateaued(history):
            console.print(
                "[dim]the last round bought less than a passage; stopping rather than"
                " spending the rest of the budget on a corpus that is as good as it"
                " is going to get[/dim]"
            )
            break

    if as_json:
        typer.echo(json_module.dumps({
            "rounds": len(history) - 1,
            "rewritten": rewritten,
            "left_alone": failed,
            "before": history[0].as_dict(),
            "after": history[-1].as_dict(),
        }, indent=2))
        return

    console.print(
        f"\n[green]✓[/green] {rewritten} section(s) rewritten"
        + (f", {failed} left as they were" if failed else "")
        + f"\n[dim]repeated passages {history[0].repeated_passages} →"
        f" {history[-1].repeated_passages}"
        f" of {history[-1].passages}. Only the sections that repeated were touched;"
        f" the other {history[-1].passages - history[0].repeated_passages} were never"
        f" sent to a model.[/dim]"
    )


def _refine_provider(harness: str, model: str | None) -> Any:
    """The writer behind `worldloom refine`."""
    from .narrative import DeterministicProvider
    from .narrative.harness import AntigravityProvider, ClaudeCodeProvider

    if harness == "fake":
        return DeterministicProvider()
    if harness == "claude-code":
        return ClaudeCodeProvider(model=model)
    if harness == "antigravity":
        return AntigravityProvider(model=model)
    err.print(f"[red]error:[/red] unknown harness {harness!r}; expected claude-code, antigravity or fake")
    raise typer.Exit(code=2)


def _rewrite_one(corpus: str, target: Any, provider: Any, *, retries: int) -> str:
    """One target, up to *retries* rejections, committed through the MCP tool body.

    Committed through `mcp.submit_section` rather than through a second commit
    path, deliberately: an agent driving the loop interactively and this command
    driving it headlessly must write the corpus the same way, or a refined corpus
    would carry different ledger entries depending on which door it came through.
    """
    from . import mcp as mcp_module
    from .narrative import prompts
    from .narrative.compiler import _request_for
    from .narrative.providers import ProviderError

    world = _load(corpus)
    facts = {fact.id: fact for fact in world.facts}
    ir = next((i for i in world.artifact_irs if i.id == target.artifact_id), None)
    section = next((s for s in ir.sections if s.heading == target.heading), None) if ir else None
    if ir is None or section is None:
        return ""

    prompt = prompts.get(prompts.SECTION_PROSE_VARIED.name)
    request = _request_for(world, ir, section, facts).model_copy(
        update={"avoid_texts": list(target.avoid_texts)}
    )

    feedback = ""
    for _ in range(max(1, retries + 1)):
        try:
            narrative = provider.complete(request, prompt, facts, feedback=feedback)
        except ProviderError as exc:
            # A harness that cannot run is not the retry loop's problem — no
            # rewording fixes an unauthenticated CLI. Same split the narration
            # compiler draws.
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc

        result = mcp_module.submit_section(
            corpus, target.artifact_id, target.heading, narrative.text,
            [claim.model_dump(mode="json") for claim in narrative.claims],
            model_id=provider.id,
        )
        if result.get("accepted"):
            return str(result.get("detail", ""))
        # The rejection becomes the next attempt's feedback verbatim — including
        # the measured similarity, which is the one piece of feedback an author
        # can actually act on.
        feedback = "\n".join(f"- {v['code']}: {v['detail']}" for v in result.get("violations", []))
    return ""


def _for_stats(name: str) -> World:
    """Load *name* the way `stats` needs it: compiled if it can be.

    Same dance as `diversity`'s loader, for the same reason — a generated
    corpus has `artifact_intents` to recompile IR from and should always be
    scored on that IR, but the hand-authored golden episode
    (`examples/retail-close`) never had intents at all, so `compile()`'s
    `ValueError` there is not a failure, it is "this corpus predates the
    compiler pipeline" — `stats.compute` falls back to the manifest and the
    rendered bytes on disk for exactly that case.
    """
    world = _load(name)
    if not world.artifact_irs:
        try:
            world = world.compile()
        except ValueError:
            pass
    return world


@app.command()
def stats(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    against: str = typer.Option(
        None, "--against", help="A second corpus name or path to diff against, metric by metric."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the statistics as JSON — stable keys and ordering, safe to diff in CI."
    ),
) -> None:
    """Report what the corpus actually contains: no invented benchmark, just numbers.

    Document counts by type, per-document word/token length (min/median/p90/
    max), vocabulary size and type-token ratio, a shingled-Jaccard near-
    duplicate rate over passages, fact-reference density per document, the
    citation graph (facts per document, documents per fact), and eval-case
    counts per family. Nothing here is compared against a "real enterprise
    corpus" figure — no such reference is auditable, so no such number appears.
    The only comparison this command makes is `--against`, between two corpora
    that both exist and can both be opened.

    `evaluate` asks whether the corpus is hard; `diversity` asks whether it
    looks structurally repeated; this asks what is actually in it. Read all
    three before calling a corpus measured.
    """
    import json as json_module

    from . import stats as stats_module

    world = _for_stats(corpus)
    try:
        report = stats_module.compute(world)
    except ValueError as exc:
        err.print(f"[red]error:[/red] {corpus}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    other_report = None
    if against:
        other_world = _for_stats(against)
        try:
            other_report = stats_module.compute(other_world)
        except ValueError as exc:
            err.print(f"[red]error:[/red] {against}: {escape(str(exc))}")
            raise typer.Exit(code=2) from exc

    if as_json:
        payload: dict[str, Any] = {"corpus": corpus, **report.as_dict()}
        if other_report is not None:
            payload["against"] = {"corpus": against, **other_report.as_dict()}
        typer.echo(json_module.dumps(payload, indent=2))
        return

    console.print(str(report))
    if other_report is not None:
        console.print("")
        console.print(stats_module.diff(report, other_report, a_label=corpus, b_label=against))


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


@pack_app.command("profiles")
def pack_profiles(as_json: bool = typer.Option(False, "--json", help="Emit as data.")) -> None:
    """The trading years a pack may choose by name.

    `base` may only be `retail` or `banking`, so any industry that is neither
    runs on the retail engine — and until these had names it inherited that
    engine's calendar. This repository's own general-insurer pack shipped a
    written-premium book peaking 21% at Christmas because of it. `flat` is the
    right answer for any business whose revenue is a book rather than a till.

    A pack may also supply twelve months of its own. They must average one: the
    index multiplies each month's budget, so a year averaging 1.05 does not
    make a business more seasonal, it makes it five per cent bigger.
    """
    from . import profiles as profiles_module

    published = profiles_module.publish()
    if as_json:
        typer.echo(json.dumps(published, indent=2))
        return
    for name, entry in published.items():
        console.print(f"[bold]{escape(name)}[/bold] [cyan]amplitude {entry['amplitude']}[/cyan]")
        console.print("  " + "  ".join(
            f"[dim]{month:>2}[/dim] {entry['index'][str(month)]:.2f}"
            for month in profiles_module.MONTHS))
        if entry.get("about"):
            console.print(f"  [dim]{escape(entry['about'])}[/dim]")


@pack_app.command("params")
def pack_params(
    prefix: str = typer.Argument(None, help="Only parameters under this prefix, e.g. `retail`."),
    as_json: bool = typer.Option(False, "--json", help="Emit the registry as data."),
) -> None:
    """Every world-physics range a pack may override, and what each one decides.

    These are the ranges the engine draws from — the ones a pack could not
    reach until they had names. Gross margin came out of `[0.20, 0.34]`
    whatever a pack said the company sold, which is why every world this tool
    built was a grocer with the labels changed.

    An author cannot override what they cannot see, and reading the source is
    not a reasonable ask for thirty-seven of them. Set them with
    `worldloom build --physics`, or derive them with `worldloom probe` rather
    than filling in a list — they are not independent, and setting margin
    without moving markdown cadence builds a grocer with one figure edited.
    """
    from .parameters import publish

    registry = {
        name: entry for name, entry in publish().items()
        if prefix is None or name.startswith(prefix)
    }
    if not registry:
        err.print(f"[red]error:[/red] no parameter starts with {prefix!r}")
        raise typer.Exit(code=2)

    if as_json:
        typer.echo(json.dumps(registry, indent=2))
        return

    for name, entry in registry.items():
        span = f"[{entry['low']}, {entry['high']}]" if entry["kind"] != "chance" else str(entry["low"])
        console.print(f"[bold]{escape(name)}[/bold] [cyan]{span}[/cyan] [dim]{entry['kind']}[/dim]")
        if entry.get("about"):
            console.print(f"  [dim]{escape(entry['about'])}[/dim]")
        if entry.get("source"):
            console.print(f"  [dim]source: {escape(entry['source'])}[/dim]")
    console.print(f"\n[dim]{len(registry)} parameter(s).[/dim]")


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

    Not shown here, because every one of them is optional and defaults to the
    engine's own behaviour: ``system_brands``, ``voices``, ``episode_text``,
    ``evaluation_text``, and the locale trio — ``name_pools`` (given/family
    name pools for the people the engine mints), ``headquarters`` (the
    company's one location), and ``regions`` (labels for the site estate,
    e.g. the abbreviations behind a stock site's "Branch NSW 001"). The
    shipped examples are the fuller reference: examples/packs/ carries a
    general insurer on the retail engine and a mutual bank on the banking
    one, and the insurer sets all three locale fields.
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
