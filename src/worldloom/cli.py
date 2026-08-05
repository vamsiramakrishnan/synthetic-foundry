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

#: `--timeline`'s named densities, mapped to the `timeline.Density` each names.
#: Named on the CLI for the same reason `--eval-density` is: "turbulent" is what
#: somebody asking for a bad year reasons about, and `Density(incidents=1/3,
#: departures=1/4, …)` is four rates they would have to invent a relationship
#: between. `quiet` is deliberately in the table even though it schedules
#: nothing — it is the null hypothesis `--periods` already builds, and having to
#: name it is what makes the other two a choice rather than an accident.
_TIMELINE_DENSITIES: tuple[str, ...] = ("quiet", "steady", "turbulent")


def _density(name: str) -> Any:
    from . import timeline as timeline_module

    return {"quiet": timeline_module.QUIET, "steady": timeline_module.STEADY,
            "turbulent": timeline_module.TURBULENT}[name]


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
    spec: Path = typer.Option(
        None, "--spec",
        help=(
            "Build from a company specification: one JSON document that says "
            "what kind of company this is, instead of the nine surfaces that "
            "each say a piece of it. `worldloom pack spec` prints the schema "
            "and `--template` writes a starter. Every field resolves into a "
            "seam that already exists — an archetype, a vocabulary, facets, "
            "physics ranges, a role table, a locale, a pack — so this adds no "
            "capability the flags lack; what it adds is that the pieces are "
            "resolved *together*, so a description that contradicts itself is "
            "a sentence rather than a corpus. Two things worth knowing. It "
            "refuses the flags it subsumes (--archetype, --inspired-by, "
            "--pack, --employees, --facet, --physics, --locale, --estate) "
            "rather than merging with them, because two accounts of one "
            "company is what a recipe exists to make impossible. And a "
            "specification is never recorded: it resolves to consequences and "
            "the recipe records those, exactly as --facet records "
            "consequences rather than facet names, so the corpus replays "
            "after the registries move underneath it."
        ),
    ),
    facet: list[str] = typer.Option(
        None, "--facet",
        help=(
            "Say what the company *is*, as `name=value` — `--facet listing=listed "
            "--facet maturity=legacy`. Repeatable; `worldloom pack facets` lists "
            "the dimensions and what each value commits the world to. A facet is "
            "not a label: `listed` mints an audit committee chair and a head of "
            "investor relations, raises status-report density, and puts the audit "
            "committee in the filing approval chain, because that is what being "
            "listed means operationally. Contradictory claims are refused naming "
            "both rather than merged — there is no listed mutual. Consequences a "
            "facet has that nothing here implements are printed rather than "
            "dropped. Costs, and the second one is the surprising one: the implied "
            "roles are appended to the organisation, so headcount exceeds what "
            "--employees stated; and naming any facet settles *every* facet at its "
            "registry default, which is what makes the claims composable but means "
            "`--facet listing=listed` alone also asserts trading_pattern=steady — a "
            "flat year, replacing the engine's 21% December. Say "
            "`--facet trading_pattern=christmas_peak` to keep it. An explicit "
            "--estate beats a facet's, and a pack's own trading year beats one a "
            "facet implies, because you said those and the facet only implied it."
        ),
    ),
    locale: str = typer.Option(
        None, "--locale",
        help=(
            "The jurisdiction this corpus is in: `australia`, `united_kingdom`, "
            "`germany` or `gulf` (`worldloom pack locales`). Every world this tool "
            "has built is Australian, and in more places than place names: a "
            "German subsidiary's variance memo printing `(1,234)` where every "
            "German report prints `-1.234` tells a reader the corpus is synthetic, "
            "and tells them from the punctuation. It reaches the *render* half — "
            "the digit grammar, applied corpus-wide so a table and the prose citing "
            "it cannot disagree — and the *build* half: the region labels in every "
            "site name, the pools the people are drawn from, the headquarters city, "
            "the retailer's own second word, and the currency and financial year "
            "every money fact is stated in. A pack's `name_pools`, `regions`, "
            "`headquarters` and currency still win where they overlap, because a "
            "pack is a claim about this company and a locale about the country it "
            "is in. One thing it still does not reach: the working week never "
            "leaves the world spec, so the close calendar counts Monday to Friday "
            "wherever the corpus is set, and a bank's or insurer's own name comes "
            "from its vertical's pool rather than the locale's. It rides the "
            "recipe, so a localised corpus rebuilds as the same world spelled the "
            "same way. Omit it and every existing corpus is byte-identical."
        ),
    ),
    messiness: str = typer.Option(
        None, "--messiness",
        help=(
            "How well the archive is kept: `pristine`, `well_run`, `lived_in` or "
            "`neglected` (`worldloom pack messiness`). Every Worldloom corpus so "
            "far has been almost perfectly kept, and a retriever that has only "
            "ever seen a tidy archive has not been tested against anything. What "
            "this does *not* relax is the invariant: every imperfection is "
            "recorded, so a reader holding only the corpus can establish "
            "mechanically that the stale page is stale and what the current "
            "position is. Costs: the corpus gains documents that are wrong on "
            "purpose, so a benchmark scored against it is measuring recency and "
            "provenance reasoning as well as retrieval. `pristine` is the "
            "default and writes nothing at all."
        ),
    ),
    timeline: str = typer.Option(
        None, "--timeline",
        help=(
            "Sample a history rather than repeating a month: `quiet`, `steady` or "
            "`turbulent`. `--periods 6` runs six closes signed by the same "
            "twenty-three people, drawn from the same distribution — six identical "
            "months with the dates changed. A density schedules incidents and org "
            "changes across those periods instead, so a controller who departs in "
            "period 2 means periods 3-6 are signed by their successor and \"which "
            "month went wrong\" becomes answerable from the corpus. Needs "
            "--periods to have room to work in. Costs: the schedule states "
            "incidents in *both* directions once it schedules any, so it and "
            "--incident cannot both decide; and hires are not sampled, because a "
            "new post's title is a business decision and a sampler inventing one "
            "would write the least plausible sentence in the corpus."
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
    if messiness is not None:
        from . import messiness as messiness_module

        try:
            messiness_module.named(messiness)
        except KeyError as exc:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
    if locale is not None:
        from . import locales as locales_module

        try:
            locales_module.named(locale)
        except KeyError as exc:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
    if timeline is not None and timeline not in _TIMELINE_DENSITIES:
        err.print(
            f"[red]error:[/red] --timeline takes {', '.join(_TIMELINE_DENSITIES)},"
            f" not {timeline!r}"
        )
        raise typer.Exit(code=2)

    # One document instead of nine surfaces. Resolved here, before anything is
    # built, and its consequences are then indistinguishable from the flags'
    # own — which is the whole design: a specification is a *composer*, so
    # everything below this block is the code that already existed, reading
    # values that arrived by a shorter route. Nothing about a spec reaches the
    # recipe; its consequences do, exactly as `--facet` records consequences
    # rather than facet names.
    resolution = None
    annual_revenue: int | None = None
    if spec is not None:
        subsumed = [
            flag for flag, given in (
                ("--archetype", archetype != "omnichannel_retailer"),
                ("--inspired-by", inspired_by is not None),
                ("--pack", pack is not None),
                ("--employees", employees is not None),
                ("--facet", bool(facet)),
                ("--physics", physics is not None),
                ("--locale", locale is not None),
                ("--estate", estate is not None),
            ) if given
        ]
        if subsumed:
            err.print(
                f"[red]error:[/red] {', '.join(subsumed)} cannot be combined with"
                " --spec; the specification already says what kind of company"
                " this is, and two accounts of one company is the thing a"
                " corpus's own recipe exists to make impossible. Put the claim"
                " in the document."
            )
            raise typer.Exit(code=2)
        from . import company as company_module

        try:
            resolution = company_module.resolve(company_module.from_document(spec))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            err.print(f"[red]error:[/red] {spec}: {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
        if not resolution.ok:
            err.print("[red]error:[/red] this description cannot be built:")
            for conflict in resolution.conflicts:
                err.print(f"  [yellow]{conflict.rule}[/yellow] {escape(str(conflict))}")
            raise typer.Exit(code=2)
        # Assigned onto the flags' own locals rather than threaded through a
        # parallel path. Two paths to one build is how the second one quietly
        # stops matching the first, and everything below has already been
        # argued for once.
        archetype = resolution.archetype_key or archetype
        employees = resolution.employees
        annual_revenue = resolution.annual_revenue
        estate = resolution.estate
        locale = resolution.locale
        console.print(
            "[dim]spec:[/dim] "
            + ", ".join(f"{k}={v}" for k, v in sorted(resolution.facet_choices.items()))
        )
        for want in resolution.unmet:
            console.print(f"[yellow]unmet:[/yellow] {escape(want)}")

    pack_obj = None if resolution is None else resolution.pack
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
    elif pack_obj is not None:
        # A specification that carried an identity composed one, or named one to
        # load. Only the named one is linted: `packs.lint` exists to hold an
        # *author* to what they wrote, and a composed pack was written by this
        # tool from a description that has already been resolved and refused
        # against every registry it touches. Running it anyway would report one
        # finding that is simply false — "the pack carries no lore" — because a
        # specification's lore reaches the world through `lore_claims` and
        # `world.extend_lore`, never through `Pack.lore`, and that seam's own
        # docstring is the argument for why.
        from . import packs as packs_module

        if resolution is None or resolution.spec.pack:
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

    # What the company *is*, resolved before the ranges it moves. A facet emits
    # only into vocabularies that already exist and already ride the recipe —
    # parameter spans, a role table, a trading year, an estate size — which is
    # why no recipe key was added for this flag and none is wanted. The recipe
    # records the *consequences*, not the facet names, and that is the stronger
    # of the two: consequences replay this world byte-for-byte even after the
    # facet registry moves under it, whereas a stored `listing=listed` would
    # replay whatever `listed` came to mean later while reporting success.
    facet_roles: tuple[tuple[str, str, str, str | None], ...] = ()
    facet_lore: tuple[Any, ...] = ()
    facet_calendar: str | None = None
    facet_estate: str | None = None
    facet_overrides: dict[str, Any] = {}
    if facet:
        from . import facets as facets_module

        chosen: dict[str, str] = {}
        for entry in facet:
            name, separator, value = entry.partition("=")
            if not separator or not name.strip() or not value.strip():
                err.print(
                    f"[red]error:[/red] --facet takes `name=value`, not {entry!r};"
                    " run `worldloom pack facets` for the dimensions"
                )
                raise typer.Exit(code=2)
            # A dimension named twice is refused rather than last-wins: keyword
            # collection would silently drop the earlier claim, and `--facet
            # listing=listed --facet listing=mutual` is somebody expecting a
            # contradiction to be caught, not a company to be quietly unlisted.
            if name.strip() in chosen:
                err.print(
                    f"[red]error:[/red] --facet {name.strip()} given twice"
                    f" ({chosen[name.strip()]!r} and {value.strip()!r}); a facet is"
                    " one dimension and takes one value"
                )
                raise typer.Exit(code=2)
            chosen[name.strip()] = value.strip()
        resolved = facets_module.resolve(**chosen)
        if not resolved.ok:
            err.print("[red]error:[/red] these claims cannot hold together:")
            for conflict in resolved.conflicts:
                err.print(f"  [yellow]{conflict.rule}[/yellow] {escape(str(conflict))}")
            raise typer.Exit(code=2)
        # Round-tripped through the recipe's own serialisation rather than used
        # as constructed, and that is not fastidiousness: a facet declares
        # `Span(120, 300)` with Python ints, `overrides_from` coerces to float on
        # the way back, and the recipe written by this build would then carry
        # `120` where its own replay carries `120.0`. Same world, different bytes,
        # and the byte-identity gate does not care which of the two is prettier.
        from .parameters import overrides_from as _overrides_from

        facet_overrides = _overrides_from(
            {name: span.as_dict() for name, span in resolved.physics.items()}
        )
        facet_roles = resolved.roles
        facet_calendar = resolved.calendar
        facet_estate = resolved.estate
        console.print(
            f"[dim]facets:[/dim] {', '.join(f'{k}={v}' for k, v in sorted(resolved.chosen.items()))}"
        )
        # Claims rather than constraints, because a claim is what a domain can
        # mint: `world.extend_lore` supplies the id and the effective date this
        # flag has no business choosing. This used to print the lore as `unmet`
        # and tell the caller to write a pack, which was honest while no seam
        # existed and is now merely stale — the same carried-cited-and-inert
        # failure in reverse, a capability reported as missing while it works.
        facet_lore = resolved.claims
        for want in facets_module.unmet(resolved):
            console.print(f"[yellow]unmet:[/yellow] {escape(want)}")

    #: The whole organisation a specification resolved, when one did. Kept apart
    #: from `facet_roles` because it is a different kind of thing: facet roles
    #: are rows to *append* to the engine's table, and this is a table that has
    #: already been through `roles.review` with the engine's own spine placed in
    #: it, the describer's leadership rows added, and the facets' roles folded
    #: in. Appending it to the shipped table would duplicate every spine key.
    spec_role_table: Any = None
    if resolution is not None:
        # Round-tripped through the recipe's own serialisation for the reason
        # the facet path does it: a facet declares `Span(120, 300)` with Python
        # ints and `overrides_from` coerces to float on the way back, so a
        # recipe written here would carry `120` where its own replay carries
        # `120.0`.
        from .parameters import overrides_from as _overrides_from

        facet_overrides = _overrides_from(
            {name: span.as_dict() for name, span in resolution.physics.items()}
        )
        facet_calendar = resolution.calendar
        facet_estate = resolution.estate
        facet_lore = resolution.lore_claims
        spec_role_table = resolution.role_table

    # Estate: an explicit `--estate` beats a facet's, because the caller said it
    # and the facet only implied it. Same rule the SDK's `.facets()` states.
    estate = estate if estate is not None else facet_estate

    physics_value = _DEFAULT_PHYSICS
    overrides: dict[str, Any] = dict(facet_overrides)
    if physics is not None:
        from .parameters import overrides_from

        try:
            document = json.loads(physics.read_text(encoding="utf-8"))
            # Applied *over* the facets' for the same reason as the estate: a
            # file of ranges is a statement, a facet is an implication.
            overrides.update(overrides_from(document.get("overrides", document)))
        except (OSError, AttributeError, KeyError, ValueError, json.JSONDecodeError) as exc:
            err.print(f"[red]error:[/red] {physics}: {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
    if overrides:
        # Rebound only when something was actually overridden, so the identity
        # check in `_under_physics` still recognises a default build and every
        # corpus built before facets existed is the same bytes.
        try:
            physics_value = _DEFAULT_PHYSICS.with_overrides(overrides)
        except (KeyError, TypeError, ValueError) as exc:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc

    #: The trading year a facet actually put on the builder, if any. Held rather
    #: than re-derived because it has to reach the *episodes* as well: a
    #: seasonality on the builder is written to the recipe, and `recipe.rebuild`
    #: hands the recorded one to every `MonthEndClose` — so a build that set it
    #: on the organisation and not on the closes would produce a corpus its own
    #: recipe rebuilds differently. Deliberately not the pack's: `--pack` has
    #: never passed one to a close, and starting now would move the bytes of
    #: every pack-built corpus already in existence.
    claimed_calendar: list[Any] = []

    def _claimed(builder: Any) -> Any:
        """*builder* rebound to whatever the facets oblige, untouched otherwise.

        Roles are appended to the engine's own table rather than replacing it:
        an audit committee chair is what "listed" *means* operationally, and a
        build that recorded the claim without minting the role would be the
        carried-and-inert failure again. That does mean headcount exceeds what
        `--employees` stated; the alternative is dropping a role the claim
        requires, which is worse and quieter.

        A trading year yields to one the builder already has — a pack's, which
        is an authored claim about the business — for the same reason
        `--estate` beats a facet's above.

        Each consequence is applied on its own, and one a builder cannot carry
        is *reported* rather than fatal. `BankingWorld` has no `seasonality`
        field, and every facet set settles `trading_pattern` at its registry
        default, so refusing the whole set would make `--facet` unusable on two
        of the three engines over a claim nobody typed. Reported through the
        same channel `facets.wants` uses, and for the same reason: a consequence
        this claim honestly has that nothing here implements is evidence, and
        the only failure would be letting it pass unsaid.
        """
        if (not facet_roles and facet_calendar is None and not facet_lore
                and spec_role_table is None):
            return builder
        from dataclasses import replace as _replace_claimed

        changes: dict[str, Any] = {}
        if facet_lore:
            changes["lore_claims"] = facet_lore
        if spec_role_table is not None:
            # Substituted, not appended — see `spec_role_table`'s note. The
            # engine's spine is already inside it, placed by `roles.from_shape`
            # and checked by `roles.review`, which is more than the append path
            # can say for a table it never looks at as a whole.
            changes["role_table"] = spec_role_table
        elif facet_roles:
            from . import roles as roles_module

            try:
                base_rows = roles_module.to_rows(roles_module._shipped(domain.name))
            except (AttributeError, KeyError) as exc:
                err.print(
                    f"[red]error:[/red] --facet implies role(s) and the"
                    f" {getattr(domain, 'name', '?')!r} engine has no table to"
                    f" append them to: {escape(str(exc))}"
                )
                raise typer.Exit(code=2) from exc
            have = {row[0] for row in base_rows}
            changes["role_table"] = base_rows + tuple(
                row for row in facet_roles if row[0] not in have
            )
        if facet_calendar is not None and getattr(builder, "seasonality", None) is None:
            from . import profiles as profiles_module

            changes["seasonality"] = profiles_module.named(facet_calendar)
        for name, value in changes.items():
            try:
                builder = _replace_claimed(builder, **{name: value})
            except TypeError:
                # Keyed by field rather than by an if/else on one of them: with
                # two entries the else branch was the role message by
                # elimination, and the third entry would have reported missing
                # lore as missing roles.
                console.print(
                    "[yellow]unmet:[/yellow] the facets imply "
                    + {
                        "seasonality": f"the {facet_calendar!r} trading calendar",
                        "role_table": (
                            f"{len(spec_role_table)} role(s)"
                            if spec_role_table is not None
                            else f"{len(facet_roles)} role(s)"
                        ),
                        "lore_claims": f"{len(facet_lore)} lore commitment(s)",
                    }[name]
                    + f" and {type(builder).__name__} has no `{name}` field, so"
                    " nothing carries them"
                )
                continue
            if name == "seasonality":
                claimed_calendar.append(value)
        return builder

    def _localised(builder: Any) -> Any:
        """*builder* set in the requested jurisdiction, untouched without one.

        On the **builder**, because a locale is a build input: the region
        labels printed into every site name, the pools the people are drawn
        from, the headquarters city, the currency every money fact is
        denominated in. This used to attach the locale to the finished world's
        recipe instead — the only thing that could be done while no world spec
        accepted one — and the result was a corpus that *recorded* Frankfurt
        and was built in Sydney. Two things were wrong with that, and the
        second is the one a test caught: the corpus was half localised, and its
        own rebuild was not, because `recipe.rebuild` reads the recorded locale
        and now builds with it. A build and its replay would have disagreed.

        `_localised_recipe` below is the other half, for a vertical whose spec
        cannot take one.
        """
        if locale is None:
            return builder
        from dataclasses import replace as _replace_locale

        try:
            return _replace_locale(builder, locale=locale)
        except TypeError:
            return builder

    def _localised_recipe(built: Any) -> Any:
        """The figure grammar, attached to a world whose spec would not take it.

        A domain registered outside this repository may have no ``locale``
        field, and the *render* half of a locale survives on the recipe alone
        (``render/values.corpus_locale``). So that corpus still spells its
        figures the requested way and simply has no build-half locale — which
        is the truth about it, not a fallback dressed as one.

        A no-op when the builder took the locale, because ``build_recipe``
        wrote the key itself. Exactly the shape ``recipe.rebuild`` uses, so the
        two paths cannot drift.
        """
        from .recipe import LOCALE_KEY, with_locale

        if locale is None or built.recipe.get(LOCALE_KEY) is not None:
            return built
        return built.extend(recipe=with_locale(built.recipe, locale))

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

    if employees is not None:
        err.print(
            f"[red]error:[/red] --employees is not yet threaded into organisation synthesis."
            f" Specifying headcount is deferred to the episode grammar (Phase 2, `docs/next-phase-plan.md`),"
            f" where declared slots for carry-forward will let a builder state it once for a"
            f" multi-period episode rather than per-period. Use the archetype's own headcount for now."
        )
        raise typer.Exit(code=2)

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
                # A density schedules incidents, and a single-episode vertical's
                # scenario takes no incident flag at all — `QuarterlyCapitalReturn`
                # is constructed from a period and nothing else. So a scheduled
                # incident here would be dropped on the floor and the corpus would
                # be `--periods N` wearing a history's name. Refused rather than
                # silently degraded, same as its neighbours; the org half
                # (departures, reorganisations) is genuinely engine-neutral and is
                # what makes this worth revisiting when a vertical's episode can
                # be told a month went wrong.
                ("--timeline", timeline is not None),
            ) if given
        ]
        if refused:
            err.print(
                f"[red]error:[/red] {', '.join(refused)} belong(s) to the retail close;"
                f" the {domain.name} vertical runs one episode per build"
            )
            raise typer.Exit(code=2)

        builder = _claimed(_under_physics(
            domain.world.from_pack(pack_obj, seed=seed)
            if pack_obj is not None
            else domain.world(
                seed=seed, archetype=shape, employees=employees,
                # Only when a specification stated one. Passed conditionally
                # rather than as `annual_revenue=None` so a domain registered
                # outside this repository, which may have no such field, keeps
                # building exactly as it did.
                **({} if annual_revenue is None else {"annual_revenue": annual_revenue}),
                # Every vertical has its own landscape vocabulary now
                # (`worldloom.landscape`), so this is no longer refused. It was
                # refused rather than mis-served for as long as the only pools
                # were retail's: a bank whose landscape is called
                # `click-collect-api` is worse than a bank with no landscape.
                **({} if estate is None else {"estate": estate}),
            )
        ))
        world = _localised_recipe(_localised(builder).build())
        for index in range(max(1, periods)):
            world = world.run(_under_physics(
                single_episode(_step_period(period, index, domain.period_step_months))
            ))
    else:
        builder = _under_physics(
            RetailWorld.from_pack(pack_obj, seed=seed)
            if pack_obj is not None
            else RetailWorld(
                seed=seed, archetype=shape, employees=employees,
                # See the single-episode branch: conditional, so a build that
                # states no revenue is the bytes it always was.
                **({} if annual_revenue is None else {"annual_revenue": annual_revenue}),
            )
        )
        if estate is not None:
            from dataclasses import replace as _replace_builder

            builder = _replace_builder(builder, estate=estate)
        builder = _claimed(builder)
        if resolution is not None and not claimed_calendar:
            # A trading year the *pack* carries has to reach the closes too, and
            # `_claimed` deliberately does not put a pack's year in
            # `claimed_calendar` — it yields to the builder's rather than
            # setting one. That is right for `--pack`, whose corpora were built
            # before this mattered and must not move. It is wrong here: a
            # specification's calendar reaches a composed pack *and* the
            # builder, `build_recipe` records it, and `recipe.rebuild` hands the
            # recorded year to every `MonthEndClose`. A build that skipped the
            # closes would rebuild into a different corpus and report success.
            carried_year = getattr(builder, "seasonality", None)
            if carried_year is not None:
                claimed_calendar.append(carried_year)
        world = _localised_recipe(_localised(builder).build())

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

    # Same boundary, one step further: an imperfection attaches to a correction
    # an episode recorded and to documents a planner has already written, and
    # `--actors agent` exports before either exists.
    if actors == "agent" and messiness is not None:
        err.print(
            "[red]error:[/red] --messiness decays documents the episode has not "
            "planned yet; --actors agent exports before that episode has run"
        )
        raise typer.Exit(code=2)

    # A sampled history is a *schedule*, and an actor episode is a handshake that
    # resumes from the ledger one decision at a time. Combining them would mean
    # the resumption had to know which of several closes it was inside, and the
    # recipe the `agent` path writes by hand above states one close per period
    # with no org changes between them — so the schedule would be silently
    # discarded on the first `worldloom act`. Refused rather than half-served.
    if timeline is not None and actors is not None:
        err.print(
            "[red]error:[/red] --timeline and --actors cannot be combined; an "
            "episode resumed from the ledger is driven one decision at a time and "
            "a sampled history is decided before the first one is taken"
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

    def _close(stamp: str, stated: bool | None, index: int) -> Any:
        return MonthEndClose(
            period=stamp,
            include_operational_incident=stated,
            comparative_months=comparatives if index == 0 else 0,
            trend_pct=trend if index == 0 else 0.0,
            actors=actor_provider,
            actor_ledger=actor_ledger,
            eval_density=eval_density_value,
            physics=physics_value,
            # Only when a facet put one on the builder — see `claimed_calendar`.
            **({} if not claimed_calendar else {"seasonality": claimed_calendar[0]}),
        )

    if periods > 1 and single_episode is not None:
        err.print(
            f"[red]error:[/red] --periods {periods} is not supported for {domain.name}."
            f" Multi-period support for single-episode verticals arrives with the episode"
            f" grammar (Phase 2, `docs/next-phase-plan.md`), which will define carry-forward"
            f" as declared slots in the episode specification rather than hand-coded per-vertical."
            f" For now, build one period per world."
        )
        raise typer.Exit(code=2)

    if timeline is not None and single_episode is None:
        # A history rather than a repetition. Note what is *not* here: no new
        # recipe verb and no `timeline` key. Every scenario the sampler can emit
        # already records itself through its own `with_step`, so a sampled
        # history rebuilds from the steps it wrote — and a recipe entry for the
        # history beside the steps it produced would be two accounts of one
        # thing, which is the failure `recipe.py`'s docstring names first.
        from . import timeline as timeline_module

        density = _density(timeline)
        if incident is not None and density.incidents:
            err.print(
                f"[red]error:[/red] --incident/--no-incident and --timeline"
                f" {timeline} cannot both decide; the schedule states an incident"
                " in both directions for every period once it schedules any, so"
                " a forced flag would either be ignored or make the schedule"
                " vacuous. Use --timeline quiet to keep the flag."
            )
            raise typer.Exit(code=2)

        stamps = timeline_module.periods_from(period, max(1, periods))
        history = timeline_module.sample(
            roster=timeline_module.Roster.of(world),
            start=period,
            periods=max(1, periods),
            seed=seed,
            density=density,
            # The sampler decides *when* something happens; what a close is
            # remains this command's business, so the episode it schedules is
            # built here with the same arguments the plain loop uses. `stated`
            # is the schedule's answer, and `incident` fills the silence a
            # zero-incident density leaves.
            episode=lambda stamp, stated: _close(
                stamp, incident if stated is None else stated, stamps.index(stamp),
            ),
        )
        console.print(
            f"[dim]timeline:[/dim] {timeline} — "
            + ", ".join(f"{at} {what}" for at, what in history.outline())
            + "\n"
        )
        try:
            world = history.run(world)
        except timeline_module.TimelineError as exc:
            err.print(f"[red]error:[/red] {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
    else:
        for index in range(max(1, periods) if single_episode is None else 0):
            stamp = f"{year + (month + index - 1) // 12:04d}-{(month + index - 1) % 12 + 1:02d}"
            try:
                world = world.run(_close(stamp, incident, index))
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

    # After the distractors and not before, so the decay pass sees the whole
    # archive: a personal working copy is exactly the kind of document that gets
    # orphaned when its author leaves, and a corpus whose noise was immune to its
    # own decay would be a tidier archive than the one it claims to be. Recorded
    # by name rather than as an expanded budget — `messiness.from_document` reads
    # a name back, so the recipe stays the small "how it was made" document it is
    # meant to be, and a profile whose counts are later revised replays as the
    # profile that was asked for.
    if messiness is not None:
        from .messiness import Imperfections

        before = len(world.artifact_intents)
        world = world.run(Imperfections(profile=messiness))
        console.print(
            f"[dim]messiness:[/dim] {messiness} —"
            f" {len(world.artifact_intents) - before} document(s) added,"
            f" {len(world.intentional_errors)} recorded imperfection(s) in total\n"
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
            # generating would not be a replay. Its id comes from what the
            # artifacts record as `narrated_by` — the id is a key component,
            # so replaying a corpus narrated under any other `--model-id`
            # with a fixed id here missed every key. It is NOT
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
            " status` to see where this corpus actually is.[/dim]"
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
    narrate: bool = typer.Option(
        True, "--narrate/--no-narrate",
        help=(
            "Write the prose every section is waiting for, with the built-in "
            "deterministic provider — no network, no key, no spend. On by "
            "default, unlike `build --narrate`: an un-narrated world compiles "
            "fifteen artifacts of which three carry a retrievable passage, so "
            "a third of its evaluation cases cite evidence that is in no "
            "passage at all and every score read off them is about the ranker "
            "when the sentence belongs to the corpus. `--no-narrate` writes "
            "the plan-only corpora this command used to write, for a caller "
            "who wants the shapes and will narrate them another way."
        ),
    ),
    formats: list[str] = typer.Option(
        None, "--format", "-f",
        help=(
            "Render every world to these formats. Repeatable. Separate from "
            "--narrate on purpose: prose is what makes a corpus measurable and "
            "files are what make it readable, and only the first is a "
            "correctness question. Omit to leave the corpora as IR."
        ),
    ),
    probe_file: Path = typer.Option(
        None, "--probe",
        help=(
            "Take the axes from a settled probe instead of this engine's defaults. "
            "The probe decides what varies and between which bounds; the algorithm "
            "still decides which N. Every parameter the probe bound becomes an axis "
            "over the interval it argued for, and axes it said nothing about keep "
            "their defaults."
        ),
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

    Every world is narrated as it is built, so what lands on disk is a corpus
    rather than a plan. `--no-narrate` gives back the plans.

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
        if probe_file is not None:
            from . import probe as probe_module

            session = probe_module.Session.from_document(
                json.loads(probe_file.read_text(encoding="utf-8"))
            )
            variants = mosaic_module.from_probe(session, count, seed=seed, engine=engine)
        else:
            variants = mosaic_module.field(count, seed=seed, engine=engine)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
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
    from .narrative import DeterministicProvider, ProviderError
    from .render import RenderError
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

    # One provider for the whole mosaic, and that is not a shared-state hazard:
    # `DeterministicProvider` reads a request and a fact table and holds nothing
    # between calls but a counter, so five worlds through one instance and five
    # worlds through five instances write the same bytes. The test asserts that
    # rather than trusting it — a provider that *did* carry state would make
    # world 5 depend on world 1 having been built, which is the one thing a
    # mosaic must never do (world N is reproducible without worlds 1..N-1).
    provider = DeterministicProvider()

    written: list[str] = []
    narrated_sections = 0
    unhealthy = 0
    for variant in variants:
        # `speaks` gives the variant its own division, category and site-format
        # names (`worldloom.vocabulary`) without touching a share, a margin or a
        # site count, and returns `shape` unchanged for any engine whose unit
        # kinds nothing names — so this line varies what the five worlds are
        # *called* and cannot vary what they are.
        spec = domain.world(seed=variant.seed, archetype=variant.speaks(shape))
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

        # Narrate before export, so what lands on disk is a corpus rather than
        # a plan. Until this line a mosaic world reached disk as artifact
        # *intents* — the sections were never compiled, let alone written — and
        # a directory of those is indistinguishable from a finished one to
        # anything except the measurement: `evaluate.score` grades a case whose
        # evidence lives in unwritten prose as a failure, and five worlds of
        # them read as a hard benchmark.
        sections = 0
        if narrate:
            try:
                world = world.narrate(provider)
            except ProviderError as exc:
                err.print(f"[red]error:[/red] world {variant.index}: {escape(str(exc))}")
                raise typer.Exit(code=2) from exc
            sections = world._narration[0]
            narrated_sections += sections

        # After narration, never before: `render` compiles if it must, and a
        # render that ran first would freeze the empty sections into the IR the
        # narration then had to be threaded back into.
        if formats:
            try:
                world = world.render(*formats)
            except RenderError as exc:
                err.print(f"[red]error:[/red] world {variant.index}: {escape(str(exc))}")
                raise typer.Exit(code=2) from exc

        target = out / f"world-{variant.index:02d}"
        written.append(str(world.export(target, overwrite=True)))
        report = world.validate()
        mark = "[green]✓[/green]" if report.ok else "[red]✗[/red]"
        unhealthy += 0 if report.ok else 1
        console.print(f"{mark} [bold]world {variant.index}[/bold] {escape(variant.summary())}"
                      f" [dim]— {report.checks_run} checks,"
                      f" {len(report.violations)} violation(s)"
                      + (f", {sections} section(s) written" if narrate else "")
                      + "[/dim]")
        if not report.ok:
            for violation in report.violations[:3]:
                err.print(f"    [yellow]{violation.code}[/yellow] {escape(violation.detail)}")

    # `narrated` and `formats` ride in the plan because a reader of the
    # directory — `evaluate.across.load` above all — otherwise has to infer
    # from a passage count whether a thin corpus is an easy one or an
    # unfinished one, and those are the two readings this whole change exists
    # to stop being confusable.
    (out / "mosaic.json").write_text(
        json.dumps({"seed": seed, "spread": spread, "narrated": narrate,
                    "formats": sorted(formats or ()),
                    "worlds": [v.as_dict() for v in variants]}, indent=2) + "\n",
        encoding="utf-8",
    )
    console.print(
        f"\n[green]✓[/green] {len(written)} world(s) written under [bold]{out}[/bold]"
        f"\n[dim]{spread['distinct_shapes']} distinct organisation shape(s);"
        f" headcounts {spread['headcounts']}; estates {spread['estates']}."
        + (f" {narrated_sections} section(s) of prose written." if narrate else "")
        + f" The plan is in mosaic.json, and each world rebuilds from its own recipe.[/dim]"
    )
    # Said at the end, where a reader stops, and said as a warning rather than
    # as a count. `--no-narrate` is a legitimate request and this does not
    # refuse it; what it refuses is letting the resulting directory be scored
    # by somebody who did not type the flag. A survey over these corpora
    # reports missing prose as failed retrieval, and the two print the same
    # digit.
    if not narrate:
        console.print(
            "[yellow]![/yellow] nothing was narrated: these are plans, and most"
            " of each world's sections are still awaiting prose."
            "\n[dim]`worldloom evaluate` and `worldloom.evaluate.across.survey`"
            " over this directory measure the missing prose, not the"
            " difficulty. Drop --no-narrate to finish them.[/dim]"
        )
    elif unhealthy:
        # Newly reachable rather than newly broken, and the distinction is
        # worth the line: `validate` runs the author/audience and manifest
        # checks over *compiled* artifacts, a plan-only mosaic had none, and so
        # this whole family of checks scored zero out of zero for as long as
        # the command stopped at `build`.
        #
        # What they find today is one defect, in every world of every engine:
        # `author_cannot_see_own_artifact`. `roles.from_shape` deals functions
        # round-robin by position in the reporting tree, so a synthesised
        # organisation puts the engine's `controller` in Merchandising while
        # the access policy the planner picks for a finance document names
        # Finance — the author of the variance memo cannot read it. The corpora
        # were always like that; compiling them is what made it sayable.
        console.print(
            f"[yellow]![/yellow] {unhealthy} of {len(written)} world(s) report"
            " violations. These are checks a plan-only mosaic never ran, not"
            " new defects: narrating compiles the artifacts, and the compiled"
            " artifacts are what the author/audience checks read."
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
    from .compiler.diversity import Fingerprint, Quotas, check, report
    from .compiler.diversity import collisions as diversity_collisions
    from .evaluate.index import passages
    from .stats import census

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

    # One walk, shared with `stats.measure` (and so with the `measure_corpus`
    # MCP tool), rather than the near-copy this command used to hold. Every
    # reader of the census has to agree on which artifacts are in it, and
    # holding the walk twice was how this command came to crash on a corpus
    # another reader could still measure, and vice versa.
    shapes = census(world)
    fingerprints: list[Fingerprint] = list(shapes.fingerprints)
    fingerprint_ids: list[str] = list(shapes.artifact_ids)

    if shapes.uncomposable:
        # Printed before the report, not after, and outside the `if
        # fingerprints` branch: this is the denominator. A reader who sees
        # "8 distinct shape(s)" without first being told the census skipped
        # three artifacts has been given a number over a subset and no way to
        # know it. Printed to stderr and *not* an exit code — nothing here is a
        # failure of this command, and a corpus with an unsatisfiable plan is
        # still a corpus worth reporting on.
        err.print(
            f"[yellow]![/yellow] {len(shapes.uncomposable)} artifact(s) have no"
            " composable shape and are not in the census below"
        )
        for artifact_id, artifact_type, code, detail in shapes.uncomposable[:10]:
            err.print(f"  [yellow]{code}[/yellow] {artifact_id} ({artifact_type}): {escape(detail)}")
        if len(shapes.uncomposable) > 10:
            err.print(f"  [dim]+{len(shapes.uncomposable) - 10} more[/dim]")
        err.print("")

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
    """Serve Worldloom's readings and gates as MCP tools, over stdio.

    Read-only over corpora, by design: every corpus write path stays behind the
    CLI handshakes, which validate a whole response document and commit
    all-or-nothing. What the tools add is the ability to ask the same question —
    what repeats, what depends on what, does it still validate — again and again
    from inside a session, as data rather than a table. The probe tools also
    serve here because a probe is dozens of question/answer turns, and a session
    that holds that loop itself beats being invoked once per question.

    `.mcp.json` at the repository root wires this into Claude Code.
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


@pack_app.command("facets")
def pack_facets(
    name: str = typer.Argument(None, help="One facet by name; omit for the whole registry."),
    as_json: bool = typer.Option(False, "--json", help="Emit the registry as data."),
) -> None:
    """Every dimension of what a company *is*, and what claiming it commits to.

    A `Pack` is a closed schema of twenty fields, each threaded by hand into the
    generators that read it, so every new attribute a company might have —
    listed or unlisted, founder-led or fund-owned — was another field and another
    generator edit. That does not reach "any kind of company"; it reaches the
    twenty things somebody already thought of.

    A facet is the other shape. It is a claim that emits *consequences* into the
    vocabularies this project already reads — parameter ranges, lore, roles, a
    trading year, an estate size — so a new kind of company is data rather than
    code. What each option implies is printed here precisely so it can be
    disagreed with: `listed` mints an audit committee chair because that is what
    listing means operationally, and if you think it should not, that is an
    argument about the registry rather than about the engine.

    `wants` is the honest half. A consequence a claim really has that nothing
    here implements is listed rather than dropped — a facet that looked
    load-bearing while changing nothing would be the defect `pack check` exists
    to catch one layer down. Set them with `worldloom build --facet name=value`.
    """
    from . import facets as facets_module

    try:
        registry = facets_module.describe(name)
    except KeyError as exc:
        err.print(
            f"[red]error:[/red] no facet named {name!r}; known:"
            f" {', '.join(sorted(facets_module.FACETS))}"
        )
        raise typer.Exit(code=2) from exc

    if as_json:
        typer.echo(json.dumps(registry, indent=2))
        return

    for facet_name, entry in registry.items():
        console.print(f"[bold]{escape(facet_name)}[/bold]"
                      f" [dim]default {entry['default'] or '—'}[/dim]")
        console.print(f"  [dim]{escape(entry['about'])}[/dim]")
        for option in entry["options"]:
            implies = option["implies"]
            marks = []
            if implies["physics"]:
                marks.append(f"{len(implies['physics'])} range(s)")
            if implies["roles"]:
                marks.append(f"roles {', '.join(implies['roles'])}")
            if implies["lore"]:
                marks.append(f"{implies['lore']} lore")
            if implies["calendar"]:
                marks.append(f"calendar {implies['calendar']}")
            if implies["estate"]:
                marks.append(f"estate {implies['estate']}")
            console.print(f"  [cyan]{escape(option['value'])}[/cyan]"
                          + (f" [dim]→ {escape(', '.join(marks))}[/dim]" if marks else ""))
            console.print(f"    [dim]{escape(option['about'])}[/dim]")
            if option["excludes"]:
                console.print(f"    [yellow]excludes[/yellow] {', '.join(option['excludes'])}")
            for want in implies["wants"]:
                console.print(f"    [yellow]wants[/yellow] {escape(want)}")
    console.print(f"\n[dim]{len(registry)} facet(s)."
                  " Set them with `worldloom build --facet name=value`.[/dim]")


@pack_app.command("messiness")
def pack_messiness(as_json: bool = typer.Option(False, "--json", help="Emit as data.")) -> None:
    """How well the archive is kept, as named profiles `build --messiness` takes.

    Two halves of a corpus's coherence, and only one of them is load-bearing: no
    document may contradict the ledger, ever. That every document is also
    *current*, correctly quoted, and owned by somebody still employed was never
    promised and is not realistic — a real enterprise archive is full of pages
    nobody updated, and a retriever that has only ever been shown a tidy one has
    not been tested against anything.

    Each imperfection is recorded, which is what keeps this a corpus rather than
    noise: a reader holding only the corpus can establish mechanically that the
    stale page is stale and what the current position is. `staleness` is a
    document written after a correction that still carries the old figure;
    `disagreement` is two live documents and a ledger that says which is right;
    `orphaning` is an author who has left with nobody named in their place —
    which the world already produced and nothing recorded until now.

    Counts are a budget, not a quota: a small world has fewer corrections to be
    stale about and the pass takes what it can support. `pristine` is the
    default and touches neither the documents nor the recipe.
    """
    from . import messiness as messiness_module

    published = messiness_module.publish()
    if as_json:
        typer.echo(json.dumps(published, indent=2))
        return
    for profile_name, entry in published.items():
        budget = ", ".join(f"{kind} {count}" for kind, count in entry["budget"].items() if count)
        console.print(f"[bold]{escape(profile_name)}[/bold]"
                      f" [cyan]{budget or 'nothing decays'}[/cyan]"
                      f" [dim]degree {entry['degree']}[/dim]")
        if entry.get("about"):
            console.print(f"  [dim]{escape(entry['about'])}[/dim]")


@pack_app.command("landscapes")
def pack_landscapes(
    name: str = typer.Argument(None, help="One vertical's vocabulary; omit to list all."),
    as_json: bool = typer.Option(False, "--json", help="Emit the pools as data."),
) -> None:
    """The technology-estate vocabularies `--estate` grows a landscape out of.

    The estate's *construction* — five layers, an edge only ever pointing at a
    strictly lower depth, a chokepoint given a private backing store — is engine
    physics and has nothing to do with retail. Only the words were retail's, and
    that is why `--estate` was once refused for every other vertical: a bank
    called `click-collect-api` is worse than a bank with no estate.

    So these are the words, per engine, and the generator keeps the physics. A
    vocabulary is validated against the fixed layers rather than free to rename
    them — the generator derives `criticality_tier` from the layer and places
    the gate at a named depth, so a pool that forgot a layer would produce an
    estate with a silently empty tier.

    You do not pass one of these to `build`; the engine picks its own, and
    `--estate small|medium|large` decides how much of it to grow. This is the
    lookup for what a corpus will end up being called.
    """
    from . import landscape as landscape_module

    published = landscape_module.publish()
    if name is not None:
        if name not in published:
            err.print(f"[red]error:[/red] no landscape named {name!r};"
                      f" known: {', '.join(sorted(published))}")
            raise typer.Exit(code=2)
        published = {name: published[name]}

    if as_json:
        typer.echo(json.dumps(published, indent=2))
        return

    for vertical, entry in published.items():
        services = entry["services"]
        systems = entry["systems"]
        console.print(f"[bold]{escape(vertical)}[/bold]"
                      f" [cyan]{sum(len(v) for v in services.values())} service name(s),"
                      f" {len(systems)} system name(s),"
                      f" {entry['chokepoints']} chokepoint(s)[/cyan]")
        console.print(f"  [dim]{escape(entry['about'])}[/dim]")
        for layer, pool in services.items():
            console.print(f"  [dim]{layer:>9}[/dim] {escape(', '.join(pool[:4]))}"
                          + (f" [dim]… +{len(pool) - 4}[/dim]" if len(pool) > 4 else ""))
        console.print("  [dim]    sizes[/dim] "
                      + ", ".join(f"{size} {count}" for size, count in entry["profiles"].items()))


@pack_app.command("locales")
def pack_locales(
    name: str = typer.Argument(None, help="One locale by name; omit to list all."),
    as_json: bool = typer.Option(False, "--json", help="Emit the conventions as data."),
) -> None:
    """Jurisdictions, as the conventions a corpus gives itself away by.

    Every world this tool has built is Australian, and in more places than the
    two the schema admits to. `Pack.regions` and `Pack.headquarters` are the only
    places a corpus prints bare geography *if* geography means place names. It is
    not: a corpus also says where it is by whose names its people have, what a
    company's second word is, which days it does not work, and how a figure is
    spelled. A German subsidiary's variance memo printing `(1,234)` where every
    German report prints `-1.234` tells a reader the document is synthetic, and
    tells them from the punctuation.

    `worldloom build --locale <name>` sets one, and it reaches most of what is
    printed below. The figure grammar is corpus-wide and rides the recipe, so
    every renderer and the retrieval index spell one number one way; the region
    labels, the name pools, the headquarters city, the currency and the fiscal
    year reach the generators at build time, so the staff, the sites and the
    units are the jurisdiction's too. A pack's own `name_pools`, `regions`,
    `headquarters` and currency are the narrower claim and still win.

    One column below does not move yet, and it is the `week`: the close calendar
    counts business days on the engine's Monday-to-Friday wherever the corpus is
    set, because no world spec carries a calendar into the episode generators.
    Claim Dubai and the close is still due on a Sydney Friday.

    Dates in facts stay ISO 8601 deliberately, and are not a field here: a
    locale that made one renderer print `03/04/2026` while the fact said
    `2026-04-03` is the divergence `render/values` exists to prevent.
    """
    from . import locales as locales_module

    published = locales_module.publish()
    if name is not None:
        if name not in published:
            err.print(f"[red]error:[/red] no locale named {name!r};"
                      f" known: {', '.join(published)}")
            raise typer.Exit(code=2)
        published = {name: published[name]}

    if as_json:
        typer.echo(json.dumps(published, indent=2))
        return

    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    for locale_name, entry in published.items():
        sample = locales_module.named(locale_name)
        console.print(f"[bold]{escape(locale_name)}[/bold]"
                      f" [cyan]{entry['currency']}[/cyan]"
                      f" [dim]{escape(entry['cities'][0][1])}[/dim]")
        console.print(f"  [dim]{escape(entry['about'])}[/dim]")
        console.print(
            f"  [dim]  figures[/dim] {escape(sample.spell(1234.5, 2))}"
            f"  {escape(sample.negate(sample.spell(1234, 0)))}"
            f"  {escape(sample.percent('4.2'))}"
        )
        console.print(
            f"  [dim]     week[/dim] {', '.join(days[d] for d in entry['working_week'])}"
            f"  [dim]{len(entry['holidays'])} fixed holiday(s)[/dim]"
        )
        console.print(
            f"  [dim]   fiscal[/dim] year starts month {entry['fiscal_year_start_month']}"
            f"  [dim]regions {', '.join(entry['regions'][:4])}…[/dim]"
        )
    console.print(
        "\n[dim]`worldloom build --locale <name>` sets one. It reaches the figure"
        " grammar corpus-wide and the regions, names, headquarters, currency and"
        " fiscal year at build time; the working week above does not reach the"
        " close calendar yet — see this command's help.[/dim]"
    )


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


@pack_app.command("export")
def pack_export_command(
    out: Path = typer.Argument(..., help="Directory to write the bundle into."),
    world: int = typer.Option(
        None, "--world", "-w",
        help="Keep this mosaic world, by its index. Needs --count, --seed and"
             " --engine to match the mosaic it came from — the field is"
             " re-derived deterministically rather than read back from disk, so"
             " the same arguments give the same world without a build.",
    ),
    count: int = typer.Option(5, "--count", "-n", help="Size of the mosaic the world came from."),
    seed: int = typer.Option(8128, "--seed", "-s", help="Base seed of that mosaic."),
    engine: str = typer.Option("retail", "--engine", "-e", help="Engine that mosaic ran on."),
    probe_file: Path = typer.Option(
        None, "--probe", help="Keep a settled probe's physics instead of a mosaic world.",
    ),
    onto: Path = typer.Option(
        None, "--onto",
        help="Apply the derivation to an existing pack rather than minting a"
             " skeleton. What an author who already has a pack and has just"
             " probed its physics wants; without it the identity fields are"
             " placeheld and `pack check` names every one.",
    ),
    name: str = typer.Option("", "--name", help="Name for a minted skeleton pack."),
    as_json: bool = typer.Option(False, "--json", help="Emit the bundle as data instead of writing files."),
) -> None:
    """Keep a derived world: a mosaic variant or a settled probe, as a pack.

    `mosaic` and `probe` both answer "what kind of company is this?" — one by
    covering a space, one by asking — and neither answer survives the command
    that produced it. An author who reads world 3 and wants *that one*, named,
    edited and handed to a colleague, has had nothing to hand over.

    What comes out is a **bundle, not a pack**, and the split is the interesting
    part. A pack is texture: a name, units, books, lore, voices. A variant and a
    probe are physics and shape: parameter ranges, an org chart, an estate. The
    overlap is one field. So this writes `pack.json` plus the sidecars a pack is
    not allowed to hold — `physics.json` for `build --physics`, `shape.json` for
    the org table and estate that have no pack field and no build flag at all —
    rather than widening `Pack` with a physics block, which would give a pack two
    ways to say one thing and make a build decide which wins.

    The third file is the list of what nobody could fill in, and it is a contract
    rather than a warning. Neither source knows what the company is called or
    what it sells; a name invented here would be signed with the author's. Those
    fields come out `TODO`-marked and `worldloom pack check` names every one.
    """
    from . import pack_export as export_module

    if (world is None) == (probe_file is None):
        err.print("[red]error:[/red] pass exactly one of --world (a mosaic index) or --probe")
        raise typer.Exit(code=2)

    base = None
    if onto is not None:
        from . import packs as packs_module

        try:
            base = packs_module.load(onto)
        except Exception as exc:
            err.print(f"[red]error:[/red] {onto}: {escape(str(exc))}")
            raise typer.Exit(code=2) from exc

    try:
        if world is not None:
            from . import mosaic as mosaic_module

            variants = mosaic_module.field(count, seed=seed, engine=engine)
            found = [v for v in variants if v.index == world]
            if not found:
                err.print(
                    f"[red]error:[/red] this mosaic has no world {world};"
                    f" its indices are {[v.index for v in variants]}"
                )
                raise typer.Exit(code=2)
            derived = export_module.from_variant(found[0], name=name, onto=base)
        else:
            from . import probe as probe_module

            session = _probe_session(probe_file)
            derived = export_module.from_probe(
                probe_module.resolve(session.graph),
                engine="" if base is not None else engine,
                name=name or "probe", onto=base, premise=session.premise,
            )
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc

    if as_json:
        typer.echo(json.dumps(derived.as_dict(), indent=2))
        return

    written = derived.write(out)
    for kind, path in written.items():
        console.print(f"[green]✓[/green] {kind} → [bold]{path}[/bold]")
    for note in derived.notes:
        console.print(f"[dim]note:[/dim] {escape(note)}")
    for gap in derived.unfilled:
        console.print(f"[yellow]unfilled:[/yellow] {escape(gap)}")
    console.print(
        f"\n[dim]Lint it with `worldloom pack check {written['pack']}`, then build it"
        f" with `worldloom build --pack {written['pack']}"
        + (f" --physics {written['physics']}" if "physics" in written else "")
        + "`.[/dim]"
    )


@pack_app.command("spec")
def pack_spec(
    template: bool = typer.Option(
        False, "--template",
        help="Emit a starter specification instead of the schema.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit the schema as data."),
) -> None:
    """The one document that says what kind of company this is.

    Nine surfaces answer that question today — an archetype key, `--employees`,
    a `--facet`, `--locale`, `--estate`, a `--physics` file, a `--pack`, a
    vocabulary qualifier, and revenue, which can only be said by writing a
    pack. Somebody describing a business has to know which of the nine each
    clause belongs to, and two of them interact in a way nobody predicts:
    naming *any* facet settles *every* facet at its registry default, so
    `--facet listing=listed` alone also asserts a flat trading year.

    A specification is one document instead, and it is a composer rather than
    an engine: every field resolves into a seam that is already load-bearing,
    so it adds no capability the flags lack. What it adds is that the pieces
    are resolved together. A description saying 40bn of revenue across twelve
    employees is refused with both numbers and the registered shapes that bound
    them; one saying premium margins in a fragmented market is refused with the
    arithmetic; one claiming a trading year on an engine whose builder has no
    field for one is reported rather than dropped.

    It is not a pack, and the difference is worth knowing before choosing.
    A pack is *identity* — a company's name, its divisions, their books, its
    voices — embedded verbatim in the corpus recipe. A specification is a
    *description*, naming no company at all, and is embedded not at all: it
    resolves to consequences and the recipe records those, so the corpus
    replays after the facet registry, the archetype table or the locale presets
    move underneath it. A specification that carries an `identity` composes
    into a pack, which is the only way its `geo` reaches the people and the
    sites rather than only the figure grammar; a specification that names a
    `pack` uses it whole, and the pack wins over everything derived.

    Build one with `worldloom build --spec company.json`.
    """
    from . import company as company_module

    if template:
        typer.echo(json.dumps(company_module.template(), indent=2))
        return

    published = company_module.describe()
    if as_json:
        typer.echo(json.dumps(published, indent=2))
        return

    for entry in published["fields"]:
        mark = {"value": "one value", "range": "a range",
                "open": "free text"}[entry["kind"]]
        console.print(f"[bold]{escape(entry['field'])}[/bold] [cyan]{mark}[/cyan]"
                      + (f" [dim]← {escape(entry['registry'])}[/dim]"
                         if entry["registry"] else ""))
        console.print(f"  [dim]{escape(entry['about'])}[/dim]")
    console.print(
        f"\n[dim]engines: {', '.join(published['engines'])}"
        f"\narchetypes: {', '.join(published['archetypes'])}"
        f"\nlocales: {', '.join(published['locales'])}"
        f"\ncalendars: {', '.join(published['calendars'])}"
        f"\nestates: {', '.join(published['estates'])}"
        f"\n{len(published['parameters'])} physics parameter(s) —"
        " `worldloom pack params`."
        "\n\nA value may only be one the registry holds; a range may only"
        " narrow one the engine draws inside. Start from"
        " `worldloom pack spec --template`.[/dim]"
    )


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
