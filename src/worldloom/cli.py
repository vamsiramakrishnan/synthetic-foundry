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
import os
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__

# Type-only: this module's import time is the console script's startup floor
# (W6), and `World`/`ValidationReport`/`CorpusError` each drag the pydantic
# model stack in. Annotations stay honest through TYPE_CHECKING; runtime uses
# import inside the bodies that actually pay for a world anyway.
if TYPE_CHECKING:
    from .validate import ValidationReport
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
causal_app = typer.Typer(
    no_args_is_help=True,
    help="Author a causal model: lint it, and trace what it would do before building under it.",
)
app.add_typer(causal_app, name="causal")
present_app = typer.Typer(
    no_args_is_help=True,
    help="Decide who a corpus's documents are for, and check a profile you wrote.",
)
app.add_typer(present_app, name="present")
fleet_app = typer.Typer(
    no_args_is_help=True,
    help="Admission control for a fleet of worlds: qualify it for a purpose, curate its champions.",
)
app.add_typer(fleet_app, name="fleet")
benchmark_app = typer.Typer(
    no_args_is_help=True,
    help="Run an executable agent against the corpus's own benchmark, scored on IDs alone.",
)
app.add_typer(benchmark_app, name="benchmark")
enterprise_evals_app = typer.Typer(
    no_args_is_help=True,
    help="Plan, generate, and validate multi-connector enterprise agent evaluations.",
)
app.add_typer(enterprise_evals_app, name="enterprise-evals")

# Keep operational generation in its own command module, not this monolith.
from .seams_cli import seams_command
from .synthesis_cli import app as synthesis_app

app.command("seams")(seams_command)
app.add_typer(synthesis_app, name="synth")


@enterprise_evals_app.command("space")
def enterprise_evals_space(
    max_candidates: int = typer.Option(10_000_000, min=1),
) -> None:
    """Count semantically valid query candidates without generating fixtures."""
    from .enterprise_queries import valid_rows
    from .enterprise_specs import CoverageProfile, builtin_registry

    profile = CoverageProfile(max_candidates=max_candidates)
    count = sum(1 for _ in valid_rows(builtin_registry(), profile))
    typer.echo(json.dumps({"profile": profile.name, "valid_candidates": count}, sort_keys=True))


@enterprise_evals_app.command("plan")
def enterprise_evals_plan(
    world_path: Path,
    output: Path,
    strength: int = typer.Option(2, min=1, max=4),
    limit: int | None = None,
    exhaustive: bool = False,
    profile_path: Path | None = typer.Option(None, "--profile"),
    shard_index: int | None = typer.Option(None, "--shard-index"),
    shard_count: int | None = typer.Option(None, "--shard-count"),
) -> None:
    """Write grounded query plans as JSONL."""
    from .enterprise_queries import plan_queries
    from .enterprise_specs import (
        CoverageProfile,
        ScenarioProfile,
        apply_scenario_profile,
        builtin_registry,
    )
    from .world import World

    world = World.load(world_path)
    scenario = (
        ScenarioProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
        if profile_path
        else None
    )
    registry = (
        apply_scenario_profile(builtin_registry(), scenario)
        if scenario
        else builtin_registry()
    )
    coverage = (
        scenario.coverage.model_copy(update={"strengths": strength})
        if scenario
        else CoverageProfile(strengths=strength)
    )
    queries, report = plan_queries(
        world,
        registry=registry,
        profile=coverage,
        strategy="exhaustive" if exhaustive else "covering",
        limit=limit,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    with output.open("w", encoding="utf-8") as handle:
        for query in queries:
            handle.write(query.model_dump_json() + "\n")
    if report is not None:
        typer.echo(report.model_dump_json())


@enterprise_evals_app.command("validate")
def enterprise_evals_validate(path: Path) -> None:
    """Validate a materialized enterprise evaluation corpus."""
    from .enterprise_corpus import EnterpriseCorpus, validate_corpus
    from .enterprise_io import load_exported_corpus

    corpus = (
        load_exported_corpus(path)
        if path.is_dir()
        else EnterpriseCorpus.model_validate_json(path.read_text(encoding="utf-8"))
    )
    findings = validate_corpus(corpus)
    if findings:
        for finding in findings:
            typer.echo(finding, err=True)
        raise typer.Exit(1)
    typer.echo("valid")


@enterprise_evals_app.command("build")
def enterprise_evals_build(
    world_path: Path,
    output: Path,
    strength: int = typer.Option(2, min=1, max=4),
    limit: int | None = None,
    exhaustive: bool = False,
    profile_path: Path | None = typer.Option(None, "--profile"),
    shard_index: int | None = typer.Option(None, "--shard-index"),
    shard_count: int | None = typer.Option(None, "--shard-count"),
    render_limit: int = typer.Option(0, "--render-limit", min=0),
) -> None:
    """Plan, materialize, validate, export, and optionally render a connector corpus."""
    from .enterprise_artifacts import render_corpus_artifacts
    from .enterprise_corpus import materialize_corpus, validate_corpus
    from .enterprise_io import export_corpus
    from .enterprise_queries import plan_queries
    from .enterprise_specs import (
        CoverageProfile,
        ScenarioProfile,
        apply_scenario_profile,
        builtin_registry,
    )
    from .world import World

    world = World.load(world_path)
    scenario = (
        ScenarioProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
        if profile_path
        else None
    )
    registry = (
        apply_scenario_profile(builtin_registry(), scenario)
        if scenario
        else builtin_registry()
    )
    coverage = (
        scenario.coverage.model_copy(update={"strengths": strength})
        if scenario
        else CoverageProfile(strengths=strength)
    )
    queries, report = plan_queries(
        world,
        registry=registry,
        profile=coverage,
        strategy="exhaustive" if exhaustive else "covering",
        limit=limit,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    corpus = materialize_corpus(world, queries)
    findings = validate_corpus(corpus)
    if findings:
        for finding in findings:
            typer.echo(finding, err=True)
        raise typer.Exit(1)
    export_corpus(corpus, output)
    rendered = render_corpus_artifacts(
        corpus, output / "artifacts", limit=render_limit
    ) if render_limit else ()
    if rendered:
        (output / "rendered-artifacts.json").write_text(
            json.dumps([item.model_dump(mode="json") for item in rendered], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    typer.echo(
        json.dumps(
            {
                "queries": len(corpus.queries),
                "records": len(corpus.connector_data.records),
                "rendered_artifacts": len(rendered),
                "coverage": report.model_dump(mode="json") if report else None,
            },
            sort_keys=True,
        )
    )


@enterprise_evals_app.command("score")
def enterprise_evals_score(
    query_path: Path,
    trace_path: Path,
) -> None:
    """Score an MCP trace against one planned query's semantic DAG."""
    from .enterprise_corpus import TraceCall, score_trace
    from .enterprise_queries import PlannedEnterpriseQuery

    query = PlannedEnterpriseQuery.model_validate_json(
        query_path.read_text(encoding="utf-8")
    )
    calls = [
        TraceCall.model_validate(item)
        for item in json.loads(trace_path.read_text(encoding="utf-8"))
    ]
    typer.echo(score_trace(query, calls).model_dump_json())


@enterprise_evals_app.command("simulate")
def enterprise_evals_simulate(
    corpus_path: Path,
    limit: int | None = typer.Option(None, min=1),
) -> None:
    """Execute exported query DAGs against the in-memory MCP simulator."""
    import asyncio

    from .enterprise_corpus import score_trace
    from .enterprise_io import load_exported_corpus
    from .enterprise_runner import RunnerConfig, ToolBinding, execute_query
    from .enterprise_simulator import ConnectorSimulator

    corpus = load_exported_corpus(corpus_path)
    queries = corpus.queries[:limit]
    fixtures = {fixture.query_id: fixture for fixture in corpus.fixtures}
    bindings = tuple(
        ToolBinding(
            connector=connector,
            operation=operation,
            entity=entity,
            tool_name=f"{connector}.{operation}",
        )
        for connector, operation, entity in sorted(
            {
                (node["connector"], node["kind"], node["entity"])
                for query in queries
                for node in query.expected_dag
                if node["connector"] != "model"
            }
        )
    )
    config = RunnerConfig(bindings=bindings)
    simulator = ConnectorSimulator(corpus)

    async def run() -> list[tuple[Any, Any]]:
        results = []
        for query in queries:
            result = await execute_query(
                query, fixtures[query.id], config, simulator.invoke
            )
            results.append((result, score_trace(query, result.calls)))
        return results

    results = asyncio.run(run())
    completed = sum(result.completed for result, _ in results)
    blocked = sum(not result.completed for result, _ in results)
    average = (
        round(sum(score.total for _, score in results) / len(results), 4)
        if results
        else 0.0
    )
    typer.echo(
        json.dumps(
            {
                "queries": len(results),
                "completed": completed,
                "blocked_by_injected_failure": blocked,
                "average_dag_score": average,
                "simulator_records": len(simulator.records),
            },
            sort_keys=True,
        )
    )

console = Console()
err = Console(stderr=True)


@app.callback()
def _install_domains() -> None:
    # No docstring on purpose: typer would surface one as the app's help text,
    # and the app help is pinned in `typer.Typer(help=...)` above.
    #
    # Runs before every command body and never for bare `--help` (click's
    # eager help exits during parsing, before the group is invoked) — which is
    # the whole W6 trade: `worldloom --help` pays only for typer and rich,
    # while a real command finds the domain surface exactly as registered as
    # it was when the package imported everything eagerly. The command bodies
    # below import submodules directly (`from .retail import RetailWorld`),
    # and a direct submodule import no longer registers the *other* verticals'
    # check groups, artifact types and recipe verbs — this callback is what
    # keeps "which tables are full" independent of which command ran, the
    # invariant every comment in `worldloom._install` exists to protect.
    from . import _install

    _install()

#: Every refusal code this CLI can emit, mapped to its one-line meaning. A
#: registry rather than bare strings at the call sites so the codes are
#: enumerable (a harness can list what it must handle) and so a typo'd code
#: fails loudly in `_refuse` instead of shipping a new accidental code — the
#: same reason ledger keys are content addresses, applied to error taxonomy.
#: Codes are stable wire format: renaming one breaks consumers, so don't.
#: Where the refusal already had a taxonomy name (`facets.py` / `company.py`
#: conflict rules like `unknown_facet` and `no_overlap`), the same name is
#: reused here rather than inventing a synonym.
_REFUSALS: dict[str, str] = {
    "synthesis_failed": "the operational synthesis contract was refused; data.finding names the rule",
    "access_profile_failed": "the corpus's documents could not be re-gated under the asked-for access profile",
    "actor_episode_failed": "the actor episode could not run to completion",
    "bad_physics": "a physics override names an unknown parameter or an impossible span",
    "bad_shard": "the shard arguments do not describe a partition of the mosaic",
    "cannot_combine": "two flags were given that cannot both decide the same build",
    "causal_and_messiness": "--causal drives imperfections and --messiness names them; two passes would spend the same corrections twice",
    "causal_model_lint": "the causal model has lint findings; data.findings names each",
    "causal_model_unreadable": "the causal model file cannot be read as a CausalModel",
    "conflict": "a resolution conflict whose rule has no individually registered code",
    "corpus_unloadable": "the corpus (or something it depends on) cannot be read",
    "destination_exists": "the output destination exists and --overwrite was not given",
    "doctor_unhealthy": "this installation cannot do everything the docs promise",
    "duplicate_facet": "one facet dimension was given two values",
    "empty_query": "the search query is empty",
    "engine_lacks_roles": "a facet implies roles and this engine has no role table to append them to",
    "episode_replaces_nothing": "the episode declares it replaces a loop this build does not run",
    "estate_unavailable": "an estate was asked for in a vertical with no landscape vocabulary",
    "exactly_one": "exactly one of a set of mutually exclusive flags must be given",
    "exec_failed": "the --exec child process exited non-zero or could not be started",
    "exec_timeout": "the --exec child process ran past --timeout and was killed",
    "exec_unparseable": "the --exec child's stdout is not the JSON document the contract asks for",
    "excludes": "two facet claims exclude each other",
    "existence_path": "a mutation path decides existence, which a rebuild cannot measure a delta over",
    "evolve_failed": "the evolution run could not complete",
    "facet_syntax": "--facet takes name=value",
    "fidelity_unreadable": "one side of the fidelity comparison cannot be read as rows",
    "fleet_error": "the fleet directory cannot be qualified or curated",
    "history_too_short": "the corpus's history is too short for this decomposition",
    "implausible_productivity": "revenue and employees describe an implausible revenue per head",
    "infeasible_estate": "the structural estate endpoints admit no path over the periods",
    "infeasible_headcounts": "the workforce endpoints admit no path over the periods",
    "intervention_syntax": "--set takes PATH=VALUE",
    "invalid_actions": "the submitted actions cannot be applied to this episode",
    "loop_exhausted": "narrate loop hit --max-rounds with sections still rejected; nothing was committed",
    "mcp_unavailable": "the MCP server cannot start in this installation",
    "missing_flag": "a required companion flag was not given",
    "mosaic_failed": "the mosaic could not be planned or built",
    "narration_conflict": "--narrate-exec names the writer and cannot ride with --no-narrate",
    "narration_failed": "the narration provider failed to produce accepted prose",
    "negative_distractors": "--distractors takes a non-negative count",
    "negative_estate": "structural estate endpoints must be non-negative",
    "negative_headcount": "a headcount takes a non-negative value",
    "no_ledger": "the corpus carries no generation ledger to replay",
    "no_matching_facts": "no period-keyed numeric facts match the asked-for kind/subject",
    "no_overlap": "two facet claims want physics spans whose intersection is empty",
    "no_passages": "the corpus has no retrievable passages (or none inside the cutoff)",
    "no_recipe": "the corpus carries no recipe, so it cannot be rebuilt",
    "not_a_date": "a flag that takes an ISO date was given something else",
    "not_a_recipe": "the named file does not hold a recipe object",
    "nothing_awaiting_prose": "responses were supplied but no section awaits prose",
    "pack_export_failed": "the pack could not be exported",
    "pack_invalid": "the industry pack does not validate",
    "period_cap": "--periods asks for more periods than this engine builds per corpus",
    "physics_unsupported": "--physics was given and this specification type accepts none",
    "recipe_error": "the corpus's recipe and this engine version disagree",
    "render_failed": "a requested format could not be rendered",
    "replay_many_providers": "the corpus was narrated by several providers; one pass replays one",
    "replay_recipe_mismatch": "the replayed corpus's recipe and this build's flags disagree",
    "resume_invalid": "a completed world does not validate for resume",
    "schema_version": "the corpus's schema version cannot be carried to this engine's by the migration chain",
    "shard_state_error": "the shard state on disk cannot be read or does not match this plan",
    "stats_failed": "the corpus does not carry what the statistics need",
    "timeline_infeasible": "the sampled timeline cannot be scheduled over these periods",
    "two_calendars": "two facet claims want different fiscal calendars",
    "uncompilable": "the corpus cannot compile its artifact plans",
    "unknown_access_level": "--access names no known access level",
    "unknown_actors": "--actors takes `scripted` or `agent`",
    "unknown_archetype": "no archetype is registered under that name",
    "unknown_engine": "no engine (domain) is registered under that name",
    "unknown_episode": "--episode names no installed process",
    "unknown_eval_density": "--eval-density names no known tier",
    "unknown_facet": "no facet is registered under that name",
    "unknown_landscape": "no landscape is registered under that name",
    "unknown_locale": "no locale is registered under that name",
    "unknown_messiness": "no messiness level is registered under that name",
    "unknown_parameter": "no physics parameter starts with that prefix",
    "unknown_profile": "no presentation profile is registered under that name",
    "unknown_timeline": "--timeline names no known density",
    "unknown_value": "the facet exists but has no such value",
    "unknown_world": "the mosaic has no world with that index",
    "unreadable_document": "a document handed to the CLI cannot be read or parsed",
    "unrecorded_path": "an intervention path does not resolve against the recorded recipe",
    "verify_diverged": "the corpus's bytes are not what its own recipe and ledger rebuild",
    "vertical_excludes_flags": "the flag belongs to another vertical's episode",
    "workspace_unwritable": "the workspace cannot be written",
}


def _refuse(
    code: str,
    message: str,
    *,
    fix: str | None = None,
    exit_code: int = 2,
    **data: Any,
) -> NoReturn:
    """Refuse with *message*, as prose by default and as data on request.

    Default mode prints *message* — the exact string the site printed before
    this helper existed — through `err`, so default stderr is byte-identical
    and every test pinned to those strings still holds. With
    ``WORLDLOOM_OUTPUT=json`` in the environment, one line of JSON goes to
    stderr instead: ``{"refusal": code, "message": …, "fix": …, "data": …}``.
    An env var and not a global ``--json`` flag because per-command ``--json``
    flags already exist with a different meaning (success payloads) and a
    second reading of the same spelling would be a trap.

    The registry lookup is unconditional — a code missing from `_REFUSALS`
    raises even in default mode, so a typo'd code is caught by the first test
    that walks the site, not by the first harness that matches on it.

    Sites converted out of ``except`` blocks lose their explicit ``raise …
    from exc``; nothing is lost in behaviour — the in-flight exception still
    rides along as ``__context__``, and typer swallows the Exit either way.
    """
    if code not in _REFUSALS:
        raise RuntimeError(
            f"unregistered refusal code {code!r}; add it to _REFUSALS"
        )
    if os.environ.get("WORLDLOOM_OUTPUT") == "json":
        # Rich's own markup parser recovers the plain text, so `escape()`d
        # brackets in the message read back as the user typed them. Written
        # with `typer.echo` and not `err.print` because the envelope must be
        # one machine-readable line and `err` soft-wraps at terminal width.
        from rich.text import Text

        envelope = {
            "refusal": code,
            "message": Text.from_markup(message).plain,
            "fix": fix,
            "data": data,
        }
        # `default=str`: a refusal that crashes while refusing is strictly
        # worse than one whose data field stringified a Path.
        typer.echo(json.dumps(envelope, ensure_ascii=False, default=str), err=True)
    else:
        err.print(message)
    raise typer.Exit(code=exit_code)


def _conflict_code(conflicts: Any) -> str:
    """The refusal code for a list of resolution `Conflict`s.

    When every conflict fell to one rule and that rule is a registered code
    (`unknown_facet`, `no_overlap`, `implausible_productivity`, …), the rule
    is the code — the taxonomy already named this refusal, and a second name
    for it would make harnesses match on two spellings. A mixed or
    unregistered set falls back to the generic ``conflict``; the individual
    rules still ride in the envelope's ``data``. The fallback is deliberate:
    `company.py` grows rules faster than a CLI wire format should, and an
    unregistered rule must degrade to a coarser code, not crash the refusal.
    """
    rules = {conflict.rule for conflict in conflicts}
    if len(rules) == 1 and (rule := next(iter(rules))) in _REFUSALS:
        return rule
    return "conflict"


def _refuse_exec_error(exc: Any) -> NoReturn:
    """An `execseam.ExecError` as a CLI refusal, child stderr included.

    Typed `Any` because `execseam` is imported inside the two commands that
    use it (the module-top import budget is a standing concern in this file),
    and the exception already carries everything the envelope needs: its
    `code` is a `_REFUSALS` key, its `data` includes the stderr tail. The tail
    is printed in prose mode too — a dead subprocess leaves exactly one
    artifact behind, and hiding it in the JSON rendering would make the
    default mode the one you cannot debug an adapter with.
    """
    message = f"[red]error:[/red] {escape(str(exc))}"
    if exc.stderr_tail:
        message += (
            "\n[dim]child stderr, last lines:[/dim]\n" + escape(exc.stderr_tail)
        )
    _refuse(exc.code, message, **exc.data)


def _load(name_or_path: str) -> World:
    # `from . import World`, not `from .world import World`: the package
    # attribute goes through `worldloom.__getattr__`, which installs the whole
    # domain surface first. That matters when a test calls this helper
    # directly — the app callback never ran, and a world loaded into a process
    # with half-registered check groups would validate clean while checking
    # nothing, the failure mode `register_domain_checks` names.
    from . import World
    from .corpus import CorpusError

    try:
        return World.load(name_or_path)
    except CorpusError as exc:
        _refuse(
            "corpus_unloadable",
            f"[red]error:[/red] {escape(str(exc))}",
            corpus=str(name_or_path),
        )


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
        _refuse("uncompilable", f"[red]error:[/red] {corpus}: {escape(str(exc))}",
                corpus=str(corpus))


def _print_report(report: ValidationReport, *, quiet: bool = False) -> bool:
    """Print a validation report and say whether it passed.

    Split from `_report` because `validate` needs the report *before* it is
    printed — it has to catch the corpus errors reconstructing a corpus's own
    pack can raise, and a helper that validates and prints in one breath gives
    it nowhere to stand. Every other caller still hands over a world.

    Advisories print on both paths and change neither the return value nor the
    exit code. `validate` owns pass/fail, and this is the posture `topology`
    already takes one layer up — it prints the cycles it finds and exits zero.
    What is different, and the reason this is here rather than behind a command
    of its own, is that somebody who builds a company should be told its estate
    is decorative without having to know a check for that exists.
    """
    if report.ok:
        if not quiet:
            console.print(f"[green]✓[/green] coherent — {report.checks_run} checks passed")
    else:
        err.print(f"[red]✗[/red] {len(report.violations)} violation(s) across {report.checks_run} checks")
        for group, items in sorted(report.by_group().items()):
            err.print(f"\n[bold]{group}[/bold]")
            for violation in items:
                err.print(f"  [yellow]{violation.code}[/yellow] {violation.subject}: {violation.detail}")
    if report.advisories and not quiet:
        console.print(
            f"\n[bold]organisation[/bold] — {len(report.advisories)} reading(s),"
            " not counted against coherence"
        )
        for advisory in report.advisories:
            console.print(
                f"  [yellow]{advisory.code}[/yellow] {advisory.subject}: {advisory.detail}"
            )
    return report.ok


def _report(world: World, *, quiet: bool = False) -> bool:
    return _print_report(world.validate(), quiet=quiet)


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
        _refuse("destination_exists", f"[red]error:[/red] {escape(str(exc))}",
                fix="pass --overwrite to replace it")

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
    vary_incidents: bool = typer.Option(
        False, "--vary-incidents",
        help=(
            "Rotate the incident's storyline across periods — a stale FX table one "
            "month, a duplicated goods receipt the next — instead of the same "
            "failure retold monthly. Surface only: causality, fact ids and machine "
            "values are identical either way, and each period's storyline is "
            "recorded on its recipe step so --replay reproduces it. Off (the "
            "default) rebuilds every existing corpus byte for byte."
        ),
    ),
    section_omission: int = typer.Option(
        200, "--section-omission", min=0, max=1000,
        help=(
            "Per-mille chance that any one *optional* section is left out of any "
            "one document, so a type emits a subset of its outline rather than "
            "all of it every time. This is swarm testing applied to documents: "
            "sections compete for a reader's attention exactly as test features "
            "compete for room, and a corpus whose every close pack carries the "
            "same five headings teaches a retriever the headings. Sections are "
            "required unless a type says otherwise, so no required fact can ever "
            "be lost to it; an un-annotated corpus has nothing optional and is "
            "unaffected at any value. Pass 0 for the historical all-sections shape."
        ),
    ),
    outline_floor: int = typer.Option(
        1, "--outline-floor", min=1,
        help=(
            "The fewest sections a document may end up with. Omission restores "
            "sections in the order their author wrote them until this is met."
        ),
    ),
    outline_synthesis: int = typer.Option(
        300, "--outline-synthesis", min=0, max=1000,
        help=(
            "Per-mille chance that any one document's outline is *synthesised* — "
            "a shape drawn from what this company's own document types have in "
            "common, rather than the one its type was authored with. "
            "Recombination, never inflation: a synthesised outline must carry at "
            "least what the authored one carries, in no more sections, arguing "
            "the document the way its type argues it, and falls back to the "
            "authored outline when no draw does. Measured at 1000 on a "
            "six-period retail build: 89% of documents synthesised, 40 distinct "
            "shapes becoming 62. Pass 0 for the authored-shape-only corpus."
        ),
    ),
    variant_bias: int = typer.Option(
        1, "--variant-bias", min=0,
        help=(
            "Rotate which authored outline variant each document gets. Two "
            "tenants built from one engine with different biases disagree about "
            "every document's shape, which is most of what stops a mosaic "
            "sharing one shape vocabulary. Only rotates among variants a type "
            "already ships; pass 0 for the historical hash-selected variants."
        ),
    ),
    employees: int = typer.Option(None, "--employees", help="Override the archetype's stated headcount."),
    headcount_end: int = typer.Option(
        None,
        "--headcount-end",
        help=(
            "Exact stated workforce in the final period. Intermediate periods"
            " are interpolated deterministically; may be above or below"
            " --employees. Requires a multi-period retail build."
        ),
    ),
    business_units_end: int = typer.Option(
        None, "--business-units-end",
        help="Exact active business-unit count in the final period.",
    ),
    sites_end: int = typer.Option(
        None, "--sites-end", help="Exact active site count in the final period.",
    ),
    systems_end: int = typer.Option(
        None, "--systems-end", help="Exact active system count in the final period.",
    ),
    services_end: int = typer.Option(
        None, "--services-end", help="Exact active service count in the final period.",
    ),
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
    episode: list[str] = typer.Option(
        None, "--episode",
        help=(
            "Run a pack-authored business process each period, after the engine's "
            "own — repeatable. Names an EpisodeSpec the --pack carries under "
            "`episodes` (see the worldloom-process skill for authoring one). This "
            "is how authored sales, legal or project processes ship: the pack "
            "declares them, this flag runs them, and the recipe replays them. "
            "Additive unless the episode's spec declares `replaces`, naming the "
            "built-in episode it stands in for — that one is then not run, "
            "because two processes minting the same kinds over one period "
            "collide. It is a property of the episode rather than a flag: an "
            "authored reserving cycle *is* the reserving cycle in every build."
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
    policies: str = typer.Option(
        None, "--policies",
        help=(
            "Give the company its standing documents: core or full. These are "
            "the papers a company *has* rather than produces — a delegation of "
            "authority, an expense policy, a leave policy, an information "
            "security policy — as opposed to what a close or an incident emits. "
            "Without it an assistant asked what the approval threshold is has "
            "nothing to find, because the company has no rules. Money "
            "provisions scale off the company's own revenue, so two archetypes "
            "do not share a limit. Omit it and every existing corpus is "
            "byte-identical."
        ),
    ),
    hiring: int = typer.Option(
        0, "--hiring",
        help=(
            "Raise this many vacancies per period and fill them. Each one is a "
            "requisition, an offer and an onboarding checklist, authored by a "
            "manager drawn from anywhere in the reporting tree rather than from "
            "the role table — which is how a modelled organisation stops being a "
            "source of bylines. The approver comes from the delegation of "
            "authority when --policies gave the company one."
        ),
    ),
    reviews: int = typer.Option(
        0, "--reviews",
        help=(
            "Review this many people per period. Each is a signed performance "
            "review countersigned by the manager's own manager, plus the running "
            "one-to-one note that fed it — at a lower authority, and saying "
            "something slightly different."
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
    priors: Path = typer.Option(
        None, "--priors",
        help=(
            "Build under physics calibrated from data by `worldloom calibrate`: a "
            "prior snapshot whose spans replace the engine's ranges and whose "
            "receipt records how they were made and what privacy budget it cost. "
            "Only ranges cross the boundary — no row of the source is in the "
            "snapshot, so none can be in the corpus. Applied before --physics, "
            "which then overrides it range by range."
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
    conversations: bool = typer.Option(
        False, "--conversations",
        help=(
            "Record the episode's knowledge layer beside its facts and documents: "
            "who was told what, by whom, and therefore who knew each fact when. "
            "Adds no facts and no documents, and adds information-asymmetry "
            "evaluation cases nothing else in the corpus can pose. Refused with "
            "`--actors`, which derives its own."
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
            "roles are appended to the organisation, so --employees must be large "
            "enough to contain them; and naming any facet settles *every* facet at its "
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
    causal: Path = typer.Option(
        None, "--causal",
        help=(
            "Run a causal model over the built world: a JSON DAG of named "
            "quantities, linear effects, dated interventions and the imperfection "
            "kinds they drive (`worldloom causal check` lints one; `worldloom "
            "causal trace` shows what it would do). Where --messiness asks for a "
            "number of stale pages, this derives the number from a cause — an ERP "
            "migration raising the error rate — and records the whole trace on "
            "the corpus so the validator can recompute every value. Cannot be "
            "combined with --messiness when the model drives imperfections: two "
            "passes would spend the same corrections twice."
        ),
    ),
    access: str = typer.Option(
        "standard", "--access",
        help=(
            "How much of the corpus is gated: `open`, `standard` or `strict`. "
            "`standard` is the engines' own mapping, records nothing, and every "
            "existing corpus is byte-identical. `open` puts every document under "
            "the all-staff policy; `strict` moves the artifact classes each "
            "engine's STRICT_ACCESS table names under its function-restricted "
            "policies — deterministically by artifact type, never by draw. A "
            "build the level cannot act on is refused with the reason rather "
            "than shipped unchanged. Rides the recipe as an `AccessProfile` "
            "step, so a gated corpus replays byte-for-byte."
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
        _refuse(
            "unknown_eval_density",
            f"[red]error:[/red] --eval-density takes {', '.join(_EVAL_DENSITY_LEVELS)},"
            f" not {eval_density!r}",
            choices=sorted(_EVAL_DENSITY_LEVELS),
        )
    eval_density_value = _EVAL_DENSITY_LEVELS[eval_density]
    if distractors < 0:
        _refuse("negative_distractors",
                "[red]error:[/red] --distractors takes a non-negative count")
    if employees is not None and employees < 0:
        _refuse("negative_headcount",
                "[red]error:[/red] --employees takes a non-negative headcount")
    if headcount_end is not None and headcount_end < 0:
        _refuse("negative_headcount",
                "[red]error:[/red] --headcount-end takes a non-negative headcount")
    estate_ends = {
        "business_units": business_units_end,
        "sites": sites_end,
        "systems": systems_end,
        "services": services_end,
    }
    if any(value is not None and value < 0 for value in estate_ends.values()):
        _refuse("negative_estate",
                "[red]error:[/red] structural estate endpoints must be non-negative")
    if messiness is not None:
        from . import messiness as messiness_module

        try:
            messiness_module.named(messiness)
        except KeyError as exc:
            _refuse("unknown_messiness", f"[red]error:[/red] {escape(str(exc))}")
    causal_model = None
    if causal is not None:
        from . import causal as causal_module

        try:
            causal_model = causal_module.from_document(
                json.loads(causal.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _refuse("causal_model_unreadable", f"[red]error:[/red] {causal}: {escape(str(exc))}")
        findings = causal_module.lint(causal_model)
        if findings:
            _refuse(
                "causal_model_lint",
                f"[red]error:[/red] {causal} has lint findings:\n"
                + "\n".join(f"  - {escape(finding)}" for finding in findings),
                findings=findings,
            )
        if causal_model.drives and messiness is not None:
            _refuse(
                "causal_and_messiness",
                "[red]error:[/red] --causal drives imperfections and --messiness asks"
                " for them by name; two passes would each spend the world's"
                " corrections, and the stale pages of one would be the duplicates"
                " of the other. Let the model decide, or drop its `drives`.",
            )
    if locale is not None:
        from . import locales as locales_module

        try:
            locales_module.named(locale)
        except KeyError as exc:
            _refuse("unknown_locale", f"[red]error:[/red] {escape(str(exc))}")
    if timeline is not None and timeline not in _TIMELINE_DENSITIES:
        _refuse(
            "unknown_timeline",
            f"[red]error:[/red] --timeline takes {', '.join(_TIMELINE_DENSITIES)},"
            f" not {timeline!r}",
            choices=sorted(_TIMELINE_DENSITIES),
        )

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
                ("--priors", priors is not None),
                ("--locale", locale is not None),
                ("--estate", estate is not None),
                ("--policies", policies is not None),
            ) if given
        ]
        if subsumed:
            _refuse(
                "cannot_combine",
                f"[red]error:[/red] {', '.join(subsumed)} cannot be combined with"
                " --spec; the specification already says what kind of company"
                " this is, and two accounts of one company is the thing a"
                " corpus's own recipe exists to make impossible. Put the claim"
                " in the document.",
                flags=[*subsumed, "--spec"],
            )
        from . import company as company_module

        try:
            resolution = company_module.resolve(company_module.from_document(spec))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _refuse("unreadable_document",
                    f"[red]error:[/red] {spec}: {escape(str(exc))}", path=str(spec))
        if not resolution.ok:
            _refuse(
                # The taxonomy rule *is* the refusal when the description fell
                # to a single registered rule (`unknown_facet`,
                # `implausible_productivity`, …) — a harness matching on codes
                # should not need to open `data` for the common one-conflict
                # case. Heterogeneous or unregistered rules fall back to the
                # generic `conflict`; every rule still rides in `data`.
                _conflict_code(resolution.conflicts),
                "[red]error:[/red] this description cannot be built:\n"
                + "\n".join(
                    f"  [yellow]{conflict.rule}[/yellow] {escape(str(conflict))}"
                    for conflict in resolution.conflicts
                ),
                conflicts=[conflict.as_dict() for conflict in resolution.conflicts],
            )
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
            _refuse(
                "cannot_combine",
                f"[red]error:[/red] {', '.join(refused_with_pack)} cannot be combined"
                " with --pack; the pack states the company's shape and scale",
                flags=[*refused_with_pack, "--pack"],
            )
        from . import packs as packs_module

        try:
            pack_obj = packs_module.load(pack)
        except Exception as exc:
            _refuse("pack_invalid",
                    f"[red]error:[/red] pack does not validate: {escape(str(exc))}")
        for finding in packs_module.lint(pack_obj):
            err.print(f"[yellow]pack:[/yellow] {escape(finding)}")
        shape = packs_module.archetype_of(pack_obj)
        domain = domains.by_name(pack_obj.base)
        if domain is None:
            _refuse(
                "unknown_engine",
                f"[red]error:[/red] pack base {pack_obj.base!r} names no registered"
                f" engine; registered: {', '.join(domains.names())}",
                registered=list(domains.names()),
            )
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
            _refuse(
                "unknown_engine",
                f"[red]error:[/red] pack base {pack_obj.base!r} names no registered"
                f" engine; registered: {', '.join(domains.names())}",
                registered=list(domains.names()),
            )
    elif inspired_by:
        shape = archetype_registry.inspired_by(inspired_by)
        domain = domains.for_archetype(shape.key)
    else:
        try:
            shape = archetype_registry.get(archetype)
        except KeyError as exc:
            _refuse("unknown_archetype", f"[red]error:[/red] {escape(str(exc))}")
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

    # Checked before anything builds: `--episode` names an authored process,
    # and the only shipping path for one is the pack that carries it —
    # `packs.archetype_of` installed this pack's specs a few lines up, so a
    # name still missing here is missing everywhere, and failing now beats a
    # world half-built when the second period's step raises.
    #
    # Resolved in the same pass: which built-in episode an authored one *stands
    # in for* (`EpisodeSpec.replaces`). Without it `--episode` is additive — the
    # domain's own episode runs and then the authored one, over the same period
    # — and two processes minting the same kinds collide. The decision is the
    # spec's, never a flag's: that an episode is the reserving cycle is true of
    # every build that runs it.
    stands_in_for: dict[str, list[str]] = {}
    if episode:
        from . import episodes as episodes_module

        for episode_name in episode:
            if episode_name not in episodes_module.loaded():
                installed_names = sorted(episodes_module.loaded()) or ["(none)"]
                _refuse(
                    "unknown_episode",
                    f"[red]error:[/red] --episode {episode_name!r} names no installed"
                    f" process; installed: {', '.join(installed_names)}. An authored"
                    " episode ships in a pack's `episodes` field — build with the"
                    " --pack that declares it.",
                    installed=list(installed_names),
                )
            replaced = episodes_module.loaded()[episode_name].replaces
            if replaced:
                stands_in_for.setdefault(replaced, []).append(episode_name)

    # A substitution this build cannot honour is refused rather than quietly
    # ignored: the spec says it takes the place of another vertical's episode
    # (or of a close this loop drives with flags the grammar cannot state), and
    # building on regardless would run both and report success — the very
    # collision `replaces` exists to end.
    built_in_name = (
        getattr(single_episode, "__name__", "") if single_episode is not None else ""
    )
    unhonoured = sorted(name for name in stands_in_for if name != built_in_name)
    if unhonoured:
        _refuse(
            "episode_replaces_nothing",
            f"[red]error:[/red] --episode declares replaces={unhonoured[0]!r}, but this"
            f" build runs {built_in_name or 'the retail close loop'}; the episode would"
            " stand in for nothing and both would mint over the same period. Build the"
            " archetype whose engine owns that episode.",
        )

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
                _refuse(
                    "facet_syntax",
                    f"[red]error:[/red] --facet takes `name=value`, not {entry!r};"
                    " run `worldloom pack facets` for the dimensions",
                    fix="run `worldloom pack facets` for the dimensions",
                )
            # A dimension named twice is refused rather than last-wins: keyword
            # collection would silently drop the earlier claim, and `--facet
            # listing=listed --facet listing=mutual` is somebody expecting a
            # contradiction to be caught, not a company to be quietly unlisted.
            if name.strip() in chosen:
                _refuse(
                    "duplicate_facet",
                    f"[red]error:[/red] --facet {name.strip()} given twice"
                    f" ({chosen[name.strip()]!r} and {value.strip()!r}); a facet is"
                    " one dimension and takes one value",
                    facet=name.strip(),
                )
            chosen[name.strip()] = value.strip()
        resolved = facets_module.resolve(**chosen)
        if not resolved.ok:
            _refuse(
                _conflict_code(resolved.conflicts),
                "[red]error:[/red] these claims cannot hold together:\n"
                + "\n".join(
                    f"  [yellow]{conflict.rule}[/yellow] {escape(str(conflict))}"
                    for conflict in resolved.conflicts
                ),
                conflicts=[
                    {"subject": c.subject, "rule": c.rule, "detail": c.detail}
                    for c in resolved.conflicts
                ],
            )
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
    said_it = estate is not None
    estate = estate if estate is not None else facet_estate

    # Refused here, before the world is built, and naming where the estate came
    # from. `landscape.LANDSCAPES` is a registry this file can read at plan
    # time, so a vertical with no landscape vocabulary is knowable before any
    # work happens — the same shape as reading `Domain.max_periods` for
    # `--periods`.
    #
    # It mattered most for the estate nobody asked for. Three facet values imply
    # `estate=large` — `maturity=legacy`, `scale=enterprise`,
    # `scale=multinational`, one of which appears in AGENTS.md's own example —
    # and on procurement that reached `ProcureToPayWorld.build` and died with an
    # unhandled `ValueError` whose remediation was "build without `--estate`", a
    # flag the caller had not typed. Every other vertical-inapplicable flag on
    # this branch prints a clean `error:` line; this one printed a stack.
    from . import landscape

    if estate is not None and domain is not None and domain.name not in landscape.LANDSCAPES:
        source = (
            "--estate" if said_it
            else "--spec" if resolution is not None
            else "a facet"
        )
        _refuse(
            "estate_unavailable",
            f"[red]error:[/red] {source} asks for an estate and the"
            f" {domain.name} vertical has no landscape vocabulary — only"
            f" {', '.join(sorted(landscape.LANDSCAPES))} name one. A"
            f" {domain.name} landscape built from another vertical's words"
            " would be worse than none, so this refuses rather than borrows."
            + (
                ""
                if said_it
                else " Nothing named an estate directly: it is implied by the"
                " facets this build resolved."
            ),
        )

    physics_value = _DEFAULT_PHYSICS
    overrides: dict[str, Any] = dict(facet_overrides)
    if priors is not None:
        from .calibrate import PriorSnapshot

        try:
            snapshot = PriorSnapshot.read(priors)
            # Under the facets' and under --physics: a calibration is a
            # measurement of somebody's data, a facet is an implication of a
            # word, and a file of ranges is a statement — and a statement made
            # on purpose outranks a measurement made in general.
            overrides.update(snapshot.overrides())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            err.print(f"[red]error:[/red] {priors}: {escape(str(exc))}")
            raise typer.Exit(code=2) from exc
        receipt = snapshot.receipt
        console.print(
            f"[dim]priors:[/dim] {len(snapshot.spans)} range(s) from {receipt.backend}"
            f" v{receipt.backend_version}, receipt {receipt.key}"
        )
        if not snapshot.private:
            console.print(
                "[yellow]note:[/yellow] this snapshot's noise was seeded — it is a"
                " deterministic summary of its source, not a private release"
            )
        if snapshot.noisy:
            console.print(
                f"[yellow]note:[/yellow] {', '.join(snapshot.noisy)}: more noise than"
                " signal at the budget and row count it was made from; the range is"
                " valid but wide"
            )
    if physics is not None:
        from .parameters import overrides_from

        try:
            document = json.loads(physics.read_text(encoding="utf-8"))
            # Applied *over* the facets' for the same reason as the estate: a
            # file of ranges is a statement, a facet is an implication.
            overrides.update(overrides_from(document.get("overrides", document)))
        except (OSError, AttributeError, KeyError, ValueError, json.JSONDecodeError) as exc:
            _refuse("unreadable_document",
                    f"[red]error:[/red] {physics}: {escape(str(exc))}",
                    path=str(physics))
    if overrides:
        # Rebound only when something was actually overridden, so the identity
        # check in `_under_physics` still recognises a default build and every
        # corpus built before facets existed is the same bytes.
        try:
            physics_value = _DEFAULT_PHYSICS.with_overrides(overrides)
        except (KeyError, TypeError, ValueError) as exc:
            _refuse("bad_physics", f"[red]error:[/red] {escape(str(exc))}")

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
        carried-and-inert failure again. An explicit ``--employees`` remains
        authoritative aggregate headcount; organisation synthesis refuses it
        when it is smaller than the role graph rather than dropping a role the
        claim requires.

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
        spec_master_data = resolution.master_data if resolution is not None else None
        if (not facet_roles and facet_calendar is None and not facet_lore
                and spec_role_table is None and not spec_master_data):
            return builder
        from dataclasses import replace as _replace_claimed

        changes: dict[str, Any] = {}
        if facet_lore:
            changes["lore_claims"] = facet_lore
        if spec_master_data:
            # The reference-table counts a specification asked for. Validated
            # by `company.resolve` (a bad request is a Conflict there, before
            # anything builds), recorded on the recipe by the builder itself.
            changes["master_data"] = dict(spec_master_data)
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
                _refuse(
                    "engine_lacks_roles",
                    f"[red]error:[/red] --facet implies role(s) and the"
                    f" {getattr(domain, 'name', '?')!r} engine has no table to"
                    f" append them to: {escape(str(exc))}",
                )
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
                        "master_data": (
                            "reference tables ("
                            + ", ".join(f"{k}={v}" for k, v in
                                        sorted((spec_master_data or {}).items()))
                            + ")"
                        ),
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

    def _shaped(built: Any) -> Any:
        """*built* with its structural genome recorded on its recipe.

        Applied to the world rather than passed through the spec so that a
        domain registered outside this repository — which has no reason to know
        what a structural genome is — still gets one. The recipe is where the
        document compiler reads it from and where replay reads it back, so this
        one line is the whole threading.

        The flag defaults describe a varying genome, so an unflagged build now
        records the key — and that recording is what keeps it honest: replay
        reads the recorded numbers rather than whatever this release's defaults
        are, and a caller wanting the historical all-sections corpus passes 0s.
        A classic genome (all zeros) still writes nothing, per `with_structure`.
        """
        from .recipe import with_structure
        from .structure import StructuralGenome

        genome = StructuralGenome(
            omission=section_omission, floor=outline_floor, variant_bias=variant_bias,
            synthesis=outline_synthesis,
        )
        if not genome.varies:
            return built
        return built.extend(recipe=with_structure(built.recipe, genome))

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
            _refuse(
                "physics_unsupported",
                f"[red]error:[/red] --physics was given, but {type(spec).__name__}"
                f" does not accept any: {escape(str(exc))}",
            )

    def _rounds(world: World, stamp: str) -> World:
        """The engine-neutral steps that run in *stamp*, after its episode.

        Hiring, performance reviews and authored episodes. All three are strict
        no-ops when unasked, and each runs *after* whatever episode the period
        already ran, so a corpus built without them keeps every id it had and
        one built with them only ever gains ids at the end of a period.

        **One function because three copies is how this broke.** This block
        lived only inside the plain retail loop, so `--hiring`, `--reviews` and
        `--episode` were accepted and silently discarded on banking, insurance
        and procurement, and on every `--timeline` build — producing a
        byte-identical corpus with no warning, while five neighbouring flags on
        the same command refused with a stated reason. Measured, the rounds work
        on all three verticals and validate clean: banking goes from 12 artifact
        intents to 29 and 744 facts to 784. Nothing was missing but the call.
        """
        if hiring > 0:
            from .workforce import HiringRound

            world = world.run(HiringRound(period=stamp, count=hiring))
        if reviews > 0:
            from .workforce import PerformanceCycle

            world = world.run(PerformanceCycle(period=stamp, pairs=reviews))
        for episode_name in episode or []:
            from .episodes import AuthoredEpisode

            world = world.run(AuthoredEpisode(episode=episode_name, period=stamp))
        return world

    if single_episode is not None:
        refused = [
            flag for flag, given in (
                ("--actors", actors is not None),
                # Same reason as `--actors`: the knowledge layer is derived from
                # the retail close's own routing table and document plan, and a
                # single-episode vertical runs neither. Refused rather than
                # silently producing an empty ledger, which would report success
                # for a corpus that gained nothing.
                ("--conversations", conversations),
                ("--incident/--no-incident", incident is not None),
                # Beside `--incident` because it is that flag's companion: it
                # rotates the storyline of the incident `--incident` schedules,
                # and a vertical that takes no incident has no storyline to
                # rotate. It was accepted and silently ignored here while its
                # own companion one line up was refused with a reason, which is
                # the inconsistency rather than the harm — nothing was lost, but
                # a caller had no way to learn the flag did nothing.
                ("--vary-incidents", vary_incidents),
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
                ("--headcount-end", headcount_end is not None),
                ("--business-units-end/--sites-end/--systems-end/--services-end",
                 any(value is not None for value in estate_ends.values())),
            ) if given
        ]
        if refused:
            _refuse(
                "vertical_excludes_flags",
                f"[red]error:[/red] {', '.join(refused)} belong(s) to the retail close;"
                f" the {domain.name} vertical runs one episode per build",
                flags=list(refused),
            )

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
                # Reaches here only for a vertical that names a landscape —
                # `landscape.LANDSCAPES` is checked at plan time, above, where a
                # vertical without one is refused with the source of the estate
                # named. This comment used to claim every vertical had its own
                # vocabulary "now", which was three of four: procurement has
                # none, and the claim is what let a facet-implied estate reach
                # `ProcureToPayWorld.build` and raise. The original reasoning
                # still holds for the three that do — a bank whose landscape is
                # called `click-collect-api` is worse than a bank with none.
                **({} if estate is None else {"estate": estate}),
                # Conditional for `estate`'s reason one line up: a domain
                # registered outside this repository may have no such field,
                # and passing `policies=None` to one that does not would refuse
                # a build that has nothing wrong with it.
                **({} if not (policies or (resolution.policies if resolution is not None else None))
                   else {"policies": policies or resolution.policies}),
            )
        ))
        world = _shaped(_localised_recipe(_localised(builder).build()))
        # The built-in runs unless an authored episode declared itself its
        # stand-in. Announced rather than silent: a skipped episode is a
        # different corpus, and the one thing worse than the collision is a
        # build that quietly produced neither what the flag said nor what the
        # archetype implies. Nothing is recorded on the recipe for it — the
        # steps that ran *are* the record, so the replay drops the same one.
        standing_in = stands_in_for.get(built_in_name, [])
        if standing_in:
            console.print(
                f"[dim]episode:[/dim] {', '.join(standing_in)} stands in for"
                f" {built_in_name}, which is not run\n"
            )
        # Refused here, before a single episode runs, because the engine's own
        # refusal arrives too late to be one. `QuarterlyReserving` raises on its
        # second consecutive run — correctly, phase 2 is not implemented — but
        # by then the world is built and the traceback reaches the terminal raw,
        # so `--periods 3` against the insurer printed a `ValueError` and no
        # corpus. The cap is already declared on the domain for the sweep's
        # benefit (`tools/sweep.py` clamps its periods axis by it), and reading
        # the same declaration here is what makes it a stated limit rather than
        # two places that happen to agree.
        #
        # `max_periods=None` means uncapped, which is the honest default: a
        # domain that has not measured its own limit should not assert one, and
        # banking and procurement both run at 3 and 12.
        #
        # Skipped when something stands in for the built-in, and that is not a
        # loophole — it is what the cap actually means. `max_periods` is a
        # statement about *this engine's own episode*: `QuarterlyReserving`
        # implements phase 1 and cannot run twice. An authored `--episode` that
        # replaces it is a different grammar with its own limits, and the
        # shipped one runs four consecutive valuation quarters. Capping by
        # vertical rather than by the episode being run refused that build,
        # which is how this was found.
        cap = domain.max_periods
        if cap is not None and periods > cap and not standing_in:
            _refuse(
                "period_cap",
                f"[red]error:[/red] {domain.name} builds at most {cap} period(s)"
                f" per corpus, and --periods {periods} was asked for. Build one"
                " at a time, or use a vertical whose episode carries a history.",
                cap=cap,
                asked=periods,
            )
        for index in range(max(1, periods)):
            stamp = _step_period(period, index, domain.period_step_months)
            if not standing_in:
                world = world.run(_under_physics(single_episode(stamp)))
            world = _rounds(world, stamp)
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
        # `--policies` on the command line, or the level a specification
        # resolved. Refused together further up, so at most one is set.
        chosen_policies = policies or (
            resolution.policies if resolution is not None else None
        )
        if chosen_policies:
            from dataclasses import replace as _replace_builder

            builder = _replace_builder(builder, policies=chosen_policies)
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
        world = _shaped(_localised_recipe(_localised(builder).build()))

    workforce = None
    workforce_path: tuple[int, ...] | None = None
    if single_episode is None and (employees is not None or headcount_end is not None):
        from .timeline import Workforce

        workforce = Workforce(
            initial=world.company.employees_total,
            final=(
                world.company.employees_total
                if headcount_end is None
                else headcount_end
            ),
        )
        try:
            workforce_path = workforce.headcounts(max(1, periods))
        except ValueError as exc:
            _refuse("infeasible_headcounts", f"[red]error:[/red] {escape(str(exc))}")
        if workforce.initial != workforce.final:
            console.print(
                "[dim]workforce:[/dim] "
                + " → ".join(f"{value:,}" for value in workforce_path)
                + "\n"
            )

    estate_trajectory = None
    estate_path = None
    if single_episode is None and any(value is not None for value in estate_ends.values()):
        from .timeline import Estate, EstateSize

        initial_estate = EstateSize(
            business_units=len(world.business_units),
            sites=len(world.sites),
            systems=len(world.systems),
            services=len(world.services),
        )
        final_estate = EstateSize(
            business_units=(initial_estate.business_units if business_units_end is None
                            else business_units_end),
            sites=initial_estate.sites if sites_end is None else sites_end,
            systems=initial_estate.systems if systems_end is None else systems_end,
            services=initial_estate.services if services_end is None else services_end,
        )
        estate_trajectory = Estate(initial_estate, final_estate)
        try:
            estate_path = estate_trajectory.sizes(max(1, periods))
        except ValueError as exc:
            _refuse("infeasible_estate", f"[red]error:[/red] {escape(str(exc))}")
        if initial_estate != final_estate:
            console.print(
                "[dim]estate:[/dim] "
                + " → ".join(
                    f"{size.business_units}bu/{size.sites}site/"
                    f"{size.systems}sys/{size.services}svc"
                    for size in estate_path
                )
                + "\n"
            )

    # The actor provider is resolved before the loop, and a replay makes it
    # unreachable for the same reason a replayed narration does: a fallback that
    # quietly generated instead would not be a replay.
    if actors is not None and actors not in {"scripted", "agent"}:
        _refuse("unknown_actors",
                f"[red]error:[/red] --actors takes `scripted` or `agent`, not {actors!r}",
                choices=["scripted", "agent"])

    # Both produce `observations` and `messages`. Refused rather than merged:
    # two producers appending to one knowledge ledger would give a (person,
    # fact) pair two learned_at values, and every asymmetry answer read off it
    # would depend on which of them ran second.
    if conversations and actors is not None:
        _refuse(
            "cannot_combine",
            "[red]error:[/red] --conversations and --actors cannot be combined;"
            " an actor episode already derives its own knowledge ledger from what"
            " each employee could see when it acted",
            flags=["--conversations", "--actors"],
        )

    # `agent` exports the world *before* the episode, carrying a recipe that says
    # an actor close is expected. There is no half-run episode to serialise —
    # `worldloom act` resumes by rebuilding from that recipe and the ledger — so
    # the honest artifact at this point is the organisation and nothing else.
    if actors == "agent" and distractors:
        _refuse(
            "cannot_combine",
            "[red]error:[/red] --distractors belongs after the episode that plans "
            "the documents it drafts and copies; --actors agent exports before "
            "that episode has run",
            flags=["--distractors", "--actors"],
        )

    # Same boundary, one step further: an imperfection attaches to a correction
    # an episode recorded and to documents a planner has already written, and
    # `--actors agent` exports before either exists.
    if actors == "agent" and messiness is not None:
        _refuse(
            "cannot_combine",
            "[red]error:[/red] --messiness decays documents the episode has not "
            "planned yet; --actors agent exports before that episode has run",
            flags=["--messiness", "--actors"],
        )

    # Refused here, not merely validated inside the step at the end of the
    # build: an unknown level should cost nothing, and the two combinations
    # below fail structurally — `--actors agent` exports before any document
    # is planned, and a knowledge ledger records who read what under the
    # access map that existed when it was derived, so re-gating afterwards
    # would leave observations of documents the manifest now denies to their
    # observers. `AccessProfile.run` refuses both anyway; this says it before
    # a world is built, in terms of the flags the caller actually typed.
    from .scenarios import ACCESS_LEVELS

    if access not in ACCESS_LEVELS:
        _refuse(
            "unknown_access_level",
            f"[red]error:[/red] unknown access level {access!r}; expected one "
            f"of {', '.join(ACCESS_LEVELS)}",
            choices=list(ACCESS_LEVELS),
        )
    if access != "standard" and actors == "agent":
        _refuse(
            "cannot_combine",
            "[red]error:[/red] --access re-gates documents the episode has not "
            "planned yet; --actors agent exports before that episode has run",
            flags=["--access", "--actors"],
        )
    if access != "standard" and (conversations or actors is not None):
        _refuse(
            "cannot_combine",
            "[red]error:[/red] --access cannot re-gate a corpus whose knowledge "
            "ledger was derived under the standard map; it is refused beside "
            "--conversations and --actors",
            flags=["--access", "--conversations", "--actors"],
        )

    # A sampled history is a *schedule*, and an actor episode is a handshake that
    # resumes from the ledger one decision at a time. Combining them would mean
    # the resumption had to know which of several closes it was inside, and the
    # recipe the `agent` path writes by hand above states one close per period
    # with no org changes between them — so the schedule would be silently
    # discarded on the first `worldloom act`. Refused rather than half-served.
    if timeline is not None and actors is not None:
        _refuse(
            "cannot_combine",
            "[red]error:[/red] --timeline and --actors cannot be combined; an "
            "episode resumed from the ledger is driven one decision at a time and "
            "a sampled history is decided before the first one is taken",
            flags=["--timeline", "--actors"],
        )
    if headcount_end is not None and actors is not None:
        _refuse(
            "cannot_combine",
            "[red]error:[/red] --headcount-end and --actors cannot be combined;"
            " actor resumption records close decisions one at a time, while a"
            " workforce trajectory is fixed before the first period",
            flags=["--headcount-end", "--actors"],
        )
    if estate_trajectory is not None and actors is not None:
        _refuse(
            "cannot_combine",
            "[red]error:[/red] structural estate endpoints and --actors cannot be"
            " combined; both advance the world between close checkpoints",
            flags=["--business-units-end", "--sites-end", "--systems-end",
                   "--services-end", "--actors"],
        )

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
            _refuse("missing_flag",
                    "[red]error:[/red] --actors agent needs --out; the episode is driven from a corpus",
                    flag="--out")
        try:
            written = world.export(out, overwrite=overwrite)
        except FileExistsError as exc:
            _refuse("destination_exists", f"[red]error:[/red] {escape(str(exc))}",
                    fix="pass --overwrite to replace it")
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

    # One rotation for the whole build, drawn from the world seed under its
    # own label: period N is the same storyline on every rebuild of this
    # world, and a different world's seed deals a different order. Classic
    # first (see `storyline_rotation`), so a one-period build is byte-equal
    # with the flag on or off.
    from .generators import operations as operations_module
    from .rng import Rng

    storyline_order = (
        operations_module.storyline_rotation(Rng(seed).derive("incident-storylines"))
        if vary_incidents else None
    )

    def _close(stamp: str, stated: bool | None, index: int) -> Any:
        return MonthEndClose(
            period=stamp,
            include_operational_incident=stated,
            comparative_months=comparatives if index == 0 else 0,
            trend_pct=trend if index == 0 else 0.0,
            actors=actor_provider,
            actor_ledger=actor_ledger,
            conversations=conversations,
            eval_density=eval_density_value,
            physics=physics_value,
            # Only when a facet put one on the builder — see `claimed_calendar`.
            **({} if not claimed_calendar else {"seasonality": claimed_calendar[0]}),
            **({} if storyline_order is None
               else {"storyline": storyline_order[index % len(storyline_order)]}),
        )

    # No blanket multi-period refusal for single-episode domains any more. The
    # one that stood here predated the episode grammar it was waiting for, and
    # it outlived its own justification: carry-forward *is* declared slots now,
    # the mosaic path has stepped these domains multi-period for as long as it
    # has existed, and measured today banking runs three consecutive quarters
    # and P2P six consecutive months, both validating clean. The authority on
    # whether a *particular* scenario supports a second run is the scenario —
    # `QuarterlyReserving` refuses its own second quarter, loudly and with the
    # reason (attribution supersession is increment 2) — and a gate here would
    # only ever disagree with the code that actually knows.

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
            _refuse(
                "cannot_combine",
                f"[red]error:[/red] --incident/--no-incident and --timeline"
                f" {timeline} cannot both decide; the schedule states an incident"
                " in both directions for every period once it schedules any, so"
                " a forced flag would either be ignored or make the schedule"
                " vacuous. Use --timeline quiet to keep the flag.",
                flags=["--incident/--no-incident", "--timeline"],
                fix="use --timeline quiet to keep the flag",
            )

        stamps = timeline_module.periods_from(period, max(1, periods))
        history = timeline_module.sample(
            roster=timeline_module.Roster.of(world),
            start=period,
            periods=max(1, periods),
            seed=seed,
            density=density,
            workforce=workforce,
            estate=estate_trajectory,
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
            _refuse("timeline_infeasible", f"[red]error:[/red] {escape(str(exc))}")
        # After the whole history rather than interleaved into it, which is the
        # one place these rounds do not sit inside their own period's loop. The
        # sampler owns the schedule — it decides which months hold an incident,
        # a departure or a reorganisation — and reaching into it to run a hiring
        # round mid-history would make this command a second author of a
        # timeline that already has one. Appending per period afterwards keeps
        # the schedule's own ART sequence untouched, which is the same
        # id-stability rule `_rounds` follows everywhere else.
        for stamp in stamps:
            world = _rounds(world, stamp)
    else:
        for index in range(max(1, periods) if single_episode is None else 0):
            stamp = f"{year + (month + index - 1) // 12:04d}-{(month + index - 1) % 12 + 1:02d}"
            try:
                world = world.run(_close(stamp, incident, index))
                world = _rounds(world, stamp)
                if (
                    workforce_path is not None
                    and index + 1 < len(workforce_path)
                    and workforce_path[index + 1] != workforce_path[index]
                ):
                    from .scenarios import WorkforceChange

                    world = world.run(WorkforceChange(
                        period=stamp,
                        headcount=workforce_path[index + 1],
                    ))
                if (
                    estate_path is not None
                    and index + 1 < len(estate_path)
                    and estate_path[index + 1] != estate_path[index]
                ):
                    from .scenarios import StructuralChange

                    target = estate_path[index + 1]
                    world = world.run(StructuralChange(
                        period=stamp,
                        business_units=target.business_units,
                        sites=target.sites,
                        systems=target.systems,
                        services=target.services,
                    ))
            except (ActorProviderError, ValueError) as exc:
                _refuse("actor_episode_failed", f"[red]error:[/red] {escape(str(exc))}")

    if actors == "scripted":
        accepted = sum(1 for entry in world.actor_ledger if entry.result.accepted)
        console.print(
            f"[dim]actors:[/dim] {len(world.actor_ledger)} tool call(s), {accepted} accepted"
            f", {len(world.observations)} observation(s)\n"
        )

    if conversations:
        told = sum(len(m.recipient_ids) for m in world.messages)
        console.print(
            f"[dim]conversations:[/dim] {len(world.messages)} message(s) to {told}"
            f" recipient(s), {len(world.observations)} observation(s) across"
            f" {len({o.observer_id for o in world.observations})} employee(s)\n"
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
        from .generators.distractors import messiness_ceilings
        from .messiness import Imperfections
        from .messiness import from_document as _messiness_profile

        before = len(world.artifact_intents)
        # Measured before the pass runs: it spends what it finds, so the ceiling
        # is a property of the world it was handed.
        ceilings = messiness_ceilings(world)
        asked = _messiness_profile(messiness)
        world = world.run(Imperfections(profile=messiness))
        delivered = len(world.intentional_errors)
        wanted = sum(asked[kind] for kind in ceilings)
        console.print(
            f"[dim]messiness:[/dim] {messiness} —"
            f" {len(world.artifact_intents) - before} document(s) added,"
            f" {delivered} of {wanted} imperfection(s) delivered\n"
        )
        # A shortfall is stated, with the reason, and it is the whole point of
        # this block. "Budget, not quota" is the documented contract and it is
        # correct — this pass may never invent a figure to be wrong about — but
        # a 0-of-17 delivery reported as success is a corpus that is not what
        # was asked for and says nothing about it. On a default retail build
        # that is exactly what happened.
        short = {
            kind: (asked[kind], ceilings[kind])
            for kind in sorted(ceilings)
            if asked[kind] > ceilings[kind]
        }
        if short:
            reasons = {
                "staleness": "needs a corrected figure some document cites",
                "disagreement": "needs a correction whose old and new figures are"
                                " both carried",
                "orphaning": "needs an author who has left, which only a departure"
                             " produces — build with --timeline or --periods > 1",
                # The mechanical kind corrupts a copy of a compiled workbook,
                # so its ceiling is per corruptible workbook —
                # `compiler.mechanical.CORRUPTIBLE` names which types qualify.
                # Every named profile keeps this budget at zero, so today the
                # entry is defensive; the KeyError it prevents would otherwise
                # arrive with the first profile or spec that asks for more
                # mechanical errors than a world's workbooks can carry.
                "mechanical": "needs a workbook this engine can corrupt a copy"
                              " of — the retail month-end model today",
            }
            for kind, (want, ceiling) in short.items():
                console.print(
                    f"[yellow]unmet:[/yellow] {kind} — asked for {want}, this"
                    f" world supports at most {ceiling}: it {reasons[kind]}"
                )
            console.print()

    if causal_model is not None:
        from . import causal as causal_module

        # Under the same physics the episodes ran under — the model's exogenous
        # nodes draw from it — and rebound the same way, so a default build's
        # recipe still carries no physics key.
        world = world.run(_under_physics(
            causal_module.Causal(model=causal_model.model_dump(mode="json"))
        ))
        trace = list(world.causal)[-1]
        console.print(
            f"[dim]causal:[/dim] {causal_model.name} over {len(trace.periods)} period(s),"
            f" {len(causal_model.interventions)} intervention(s);"
            + (
                " budgets " + ", ".join(
                    f"{kind} {trace.delivered.get(kind, 0)}/{count}"
                    for kind, count in sorted(trace.budgets.items())
                ) + " delivered"
                if trace.budgets else " no imperfections driven"
            )
            + "\n"
        )

    # After every pass that plans or copies a document — episodes, workforce
    # rounds, distractors, messiness — and before narrate/render, because the
    # manifest reads each intent's audience at compile time and a level applied
    # later would be recorded on a corpus gated without it. `standard` is an
    # identity inside the step, so the guard here is only to keep the default
    # build's console output byte-identical too.
    if access != "standard":
        from .scenarios import AccessProfile

        before = {i.id: i.audience for i in world.artifact_intents}
        try:
            world = world.run(AccessProfile(level=access))
        except ValueError as exc:
            _refuse("access_profile_failed", f"[red]error:[/red] {escape(str(exc))}")
        moved = sum(
            1 for i in world.artifact_intents if before.get(i.id) != i.audience
        )
        console.print(
            f"[dim]access:[/dim] {access} — {moved} of"
            f" {len(world.artifact_intents)} document(s) re-gated\n"
        )

    # Timeline builds append hiring/review rounds after all closes, and the
    # archive passes above can append still more documents. Their authorship
    # must be reconciled with the opt-in knowledge ledger too. A named recipe
    # step rather than an invisible derive call makes replay reproduce it.
    if conversations:
        from .conversation import ConversationRefresh

        world = world.run(ConversationRefresh())

    if narrate or replay is not None:
        from . import recipe as recipe_module
        from .narrative import DeterministicProvider, ProviderError, UnreachableProvider

        ledger = ()
        provider = DeterministicProvider()
        if replay is not None:
            source = _load(str(replay))
            ledger = source._ledger
            if not ledger:
                _refuse("no_ledger",
                        f"[red]error:[/red] {replay} carries no generation ledger to replay",
                        corpus=str(replay))
            # The world being narrated must be the world the ledger was recorded
            # for, and this says so up front instead of letting it emerge.
            #
            # `--replay` does not rebuild the world — it replays prose into
            # whatever the other flags built — so `worldloom build --replay
            # <a-banking-corpus>` with no `--archetype` narrates the *default
            # retail* world from a bank's ledger. Every key misses, and the
            # failure surfaces from inside `narrate` as "no ledger entry for
            # ART-0001/Commitment", which names an artifact the user never
            # asked for and says nothing about the mistake they actually made.
            #
            # Recipes rather than archetype-and-seed, because the ways to build
            # the wrong world are not enumerable: `--periods`, `--messiness`,
            # `--distractors` and `--facet` all change what there is to narrate.
            # And a divergence that leaves the *sections* intact is the worse
            # one, not the milder — replaying under a different `--annual-
            # revenue` would succeed and file prose quoting last world's figures
            # beside this world's tables, which is the cross-format defect this
            # repository has already paid for once.
            #
            # `presentation` is excluded because a profile decides who a
            # document is for and nothing about the world; `worldloom render`
            # writes one onto an existing corpus, so a corpus rendered after it
            # was narrated would otherwise refuse to replay itself.
            def _world_only(document: dict[str, Any]) -> dict[str, Any]:
                return {
                    key: value
                    for key, value in document.items()
                    if key != recipe_module.PRESENTATION_KEY
                }

            here, there = _world_only(world.recipe), _world_only(source.recipe)
            if here != there:
                differs = sorted(
                    key for key in set(here) | set(there)
                    if here.get(key) != there.get(key)
                )
                _refuse(
                    "replay_recipe_mismatch",
                    f"[red]error:[/red] {replay} recorded a different world;"
                    f" its recipe and this build's disagree on"
                    f" {', '.join(differs)}. A replay reproduces a corpus, so"
                    " the flags that built it have to be the flags that build"
                    f" this one; {replay}/world.json records the recipe it was"
                    " built from.",
                    differs=list(differs),
                )
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
                _refuse(
                    "replay_many_providers",
                    f"[red]error:[/red] {replay} was narrated by several providers"
                    f" ({', '.join(sorted(narrated_ids))}); one narrate pass"
                    " replays one provider's keys",
                    providers=sorted(narrated_ids),
                )
            provider = (
                UnreachableProvider(id=narrated_ids.pop())
                if narrated_ids
                else UnreachableProvider()
            )

        try:
            world = world.narrate(provider, ledger=ledger)
        except ProviderError as exc:
            _refuse("narration_failed", f"[red]error:[/red] {escape(str(exc))}")

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
            _refuse("render_failed", f"[red]error:[/red] {escape(str(exc))}")

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
            _refuse("destination_exists", f"[red]error:[/red] {escape(str(exc))}",
                    fix="pass --overwrite to replace it")
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
        _refuse("unreadable_document",
                f"[red]error:[/red] {source}: {escape(str(exc))}", path=str(source))

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
        _refuse(
            "nothing_awaiting_prose",
            f"[red]error:[/red] {len(responses)} response(s) supplied but this corpus"
            " has no section awaiting prose — nothing was reviewed and nothing was"
            " committed.\n[dim]Every section already carries prose. Run `worldloom"
            " status` to see where this corpus actually is.[/dim]",
            responses=len(responses),
        )

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


@narrate_app.command("loop")
def narrate_loop(
    corpus: str = typer.Argument(..., help="Corpus path to narrate."),
    exec_command: str = typer.Option(
        ..., "--exec",
        help=(
            "The model as an executable: reads one requests JSON document on "
            "stdin, prints one responses JSON document on stdout. Run without "
            "a shell (shlex argv) unless --shell is given."
        ),
    ),
    max_rounds: int = typer.Option(
        8, "--max-rounds",
        help="Rounds to run before giving up with every outstanding violation listed.",
    ),
    timeout: float = typer.Option(
        600.0, "--timeout",
        help="Seconds the child may run per round before it is killed and refused.",
    ),
    shell: bool = typer.Option(
        False, "--shell",
        help="Run the command through the shell — the opt-in for pipelines.",
    ),
    model_id: str = typer.Option(
        "agent", "--model-id",
        help="Who wrote it. Recorded in the ledger and part of the replay key.",
    ),
) -> None:
    """Drive an executable model until every section's prose is accepted.

    One command instead of the requests/accept round trip: each round hands the
    child the same requests document `narrate requests` writes — restricted to
    the still-unaccepted sections — and reads back the same responses document
    `narrate accept --from` reads. Acceptance runs in-process; accepted prose
    is committed to the ledger only once everything passes, so the corpus
    replays byte-for-byte afterwards and a failed loop leaves it untouched.

    The adapter contract is JSON-on-stdin, JSON-on-stdout; no vendor is
    special-cased in code. A working adapter around an agent CLI is a few
    lines of shell — e.g. `adapter.sh`, run as `--exec ./adapter.sh`:

        #!/bin/sh
        exec claude -p "Here is a Worldloom narration requests document.
        Print only the responses JSON document it asks for: $(cat)"
    """
    from . import execseam

    world = _compiled(_load(corpus), corpus)

    def _print_round(round_report: Any) -> None:
        console.print(
            f"round {round_report.number}: {round_report.accepted} of"
            f" {round_report.submitted} section(s) accepted"
        )

    try:
        result = execseam.narrate_loop(
            world, exec_command, model_id=model_id, max_rounds=max_rounds,
            timeout=timeout, shell=shell, on_round=_print_round,
        )
    except execseam.ExecError as exc:
        _refuse_exec_error(exc)

    if not result.rounds:
        console.print("[green]✓[/green] nothing awaiting prose")
        return

    if result.outstanding:
        # Through `_refuse` rather than a bare print-and-exit so a harness in
        # JSON mode gets the violations as data — the loop exhausting its
        # budget is the refusal an unattended run most needs to consume.
        lines = [
            f"[red]✗[/red] {len(result.outstanding)} section(s) still rejected"
            f" after {len(result.rounds)} round(s). Nothing was committed."
        ]
        for name, verdict in sorted(result.outstanding.items()):
            lines.append(f"\n[bold]{name}[/bold]")
            for violation in verdict.violations:
                lines.append(f"  [yellow]{violation.code}[/yellow] {violation.detail}")
        _refuse(
            "loop_exhausted",
            "\n".join(lines),
            exit_code=1,
            rounds=len(result.rounds),
            outstanding={
                name: [{"code": v.code, "detail": v.detail} for v in verdict.violations]
                for name, verdict in sorted(result.outstanding.items())
            },
        )

    narrated = result.world
    assert narrated is not None  # complete with rounds run means a narrated world
    written = narrated.export(corpus, overwrite=True)
    accepted_total = sum(round_report.accepted for round_report in result.rounds)
    console.print(
        f"[green]✓[/green] {accepted_total} section(s) accepted over"
        f" {len(result.rounds)} round(s) and recorded in the ledger"
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
        _refuse("unreadable_document",
                f"[red]error:[/red] {source}: {escape(str(exc))}", path=str(source))

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
        _refuse("unreadable_document",
                f"[red]error:[/red] {path}: {escape(str(exc))}", path=str(path))


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
        _refuse("unreadable_document",
                f"[red]error:[/red] {source}: {escape(str(exc))}", path=str(source))

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
        _refuse("unreadable_document",
                f"[red]error:[/red] {source}: {escape(str(exc))}", path=str(source))

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
        _refuse("recipe_error", f"[red]error:[/red] {corpus}: {escape(str(exc))}",
                corpus=str(corpus))

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
        _refuse("unreadable_document",
                f"[red]error:[/red] {source}: {escape(str(exc))}", path=str(source))

    try:
        outcome = handshake.accept(world, actions, model_id=model_id)
    except (RecipeError, ValueError) as exc:
        _refuse("invalid_actions", f"[red]error:[/red] {escape(str(exc))}")

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
    profile: str = typer.Option(
        None, "--profile",
        help=(
            "Who the documents are for. `audit` (the default, and what every "
            "corpus rendered before this flag existed got) prints the "
            "supporting-fact appendix and the author's voice in the document. "
            "`reader` records both and prints neither, and spells figures the "
            "way a memo does. `filing` puts the citations in a sibling file. "
            "`worldloom present describe` prints every profile and knob; "
            "`worldloom present lint` checks one you wrote."
        ),
    ),
) -> None:
    """Render an existing corpus into files.

    The profile is written onto the corpus's recipe before rendering, so the
    files on disk and the record of how they were made cannot disagree — and a
    later `--replay` reproduces this rendering rather than the default one.
    Re-rendering an existing corpus under a second profile is a supported thing
    to do and needs no rebuild: a profile decides nothing about the world.
    """
    from .presentation import named
    from .recipe import with_presentation
    from .render import RenderError

    world = _load(corpus)
    if profile is not None:
        try:
            world = world.extend(recipe=with_presentation(world.recipe, named(profile)))
        except ValueError as exc:
            _refuse("unknown_profile", f"[red]error:[/red] {escape(str(exc))}")
    try:
        rendered = world.render(*formats)
    except (RenderError, ValueError) as exc:
        _refuse("render_failed", f"[red]error:[/red] {escape(str(exc))}")

    written = rendered.export(out or Path(corpus), overwrite=True)
    console.print(f"[green]✓[/green] {len(rendered._rendered)} file(s) written to [bold]{written}[/bold]")
    # Validated against where the files actually landed, not in memory. The
    # in-memory world still resolves artifact paths against the *source*
    # corpus, so rendering to a `--out` directory reported every file it had
    # just written as missing — a false failure, and the loudest possible one,
    # since anyone running this in a pipeline reads it as rendering being
    # broken. This used to `_load(str(written))` — a full re-parse of every
    # JSONL stream it had exported one line earlier — when the only check that
    # reads the disk is `artifact_files`, and all it needs is the written
    # root. So: rebind `root` and re-parse only the manifest. The manifest
    # comes back off the disk rather than from memory on purpose — it is the
    # file that names what a reader will open, so the check stays a statement
    # about the corpus on disk, not about what this process meant to write.
    # The full write→read round trip this no longer exercises is pinned by
    # `test_export_round_trips_without_loss`; before the reload was dropped,
    # both paths were measured to produce equal reports (8,133 checks, and
    # the same `missing_file` violations when a written artifact is deleted).
    from dataclasses import replace as _replace_root

    from . import corpus as corpus_module
    from .models import ArtifactManifestEntry

    on_disk = _replace_root(
        rendered,
        root=written,
        _artifacts=tuple(corpus_module.load_models(
            written / corpus_module.MANIFEST_FILE, ArtifactManifestEntry,
        )),
    )
    if not _report(on_disk):
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
    shard_count: int = typer.Option(
        1, "--shard-count", help="Deterministic number of batch shards.",
    ),
    shard_index: int = typer.Option(
        0, "--shard-index", help="Zero-based shard owned by this worker.",
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Resume this exact plan from validated worlds and section checkpoints.",
    ),
    narration_concurrency: int = typer.Option(
        1, "--narration-concurrency", min=1,
        help="Concurrent narration sections per world; assembly remains deterministic.",
    ),
    incident: bool = typer.Option(
        None, "--incident/--no-incident",
        help="Force the operational incident. Omit to let each world's seed and lore decide.",
    ),
    narrate: bool = typer.Option(
        True, "--narrate/--no-narrate",
        help=(
            "Write the prose every section is waiting for — with the built-in "
            "deterministic provider by default (no network, no key, no spend), "
            "or through an agent command via --narrate-exec. On by default, "
            "unlike `build --narrate`: an un-narrated world compiles fifteen "
            "artifacts of which three carry a retrievable passage, so a third "
            "of its evaluation cases cite evidence that is in no passage at "
            "all and every score read off them is about the ranker when the "
            "sentence belongs to the corpus. `--no-narrate` writes the "
            "plan-only corpora this command used to write, for a caller who "
            "wants the shapes and will narrate them another way."
        ),
    ),
    narrate_exec: str = typer.Option(
        None, "--narrate-exec",
        help=(
            "Narrate every world through AGENT COMMAND instead of the "
            "deterministic provider: the command runs once per section with "
            "the request document on stdin and must print one responses "
            "document on stdout — the same child contract `narrate loop "
            "--exec` speaks, so one adapter drives either surface (e.g. "
            "`python3 tools/exec_agent.py`, or a wrapper around your writer "
            "of choice). Rejections come back to the child as feedback and "
            "are retried; ledger entries, checkpoint resume and "
            "--narration-concurrency all work exactly as they do for the "
            "deterministic provider. Implies narration; refused together "
            "with --no-narrate."
        ),
    ),
    narrate_model_id: str = typer.Option(
        "agent", "--narrate-model-id",
        help=(
            "Model identifier recorded in the ledger and replay keys when "
            "--narrate-exec is in use. Name the real writer, so a corpus can "
            "say what wrote it."
        ),
    ),
    narrate_timeout: float = typer.Option(
        600.0, "--narrate-timeout", min=1.0,
        help="Seconds one agent command may run before it is killed.",
    ),
    narrate_shell: bool = typer.Option(
        False, "--narrate-shell",
        help="Run --narrate-exec through the shell, for pipelines.",
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
    rather than a plan. `--no-narrate` gives back the plans; `--narrate-exec`
    hands the writing to an agent command of your choosing, section by section,
    under the same child contract `narrate loop --exec` speaks.

    `--describe` prints the axes without building anything, which is the right
    first call — deciding whether five worlds are worth the wait should not
    require generating five worlds.
    """
    from . import batch as batch_module
    from . import mosaic as mosaic_module

    if describe:
        try:
            document = mosaic_module.describe(engine)
        except KeyError as exc:
            _refuse("unknown_engine", f"[red]error:[/red] {escape(str(exc))}")
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
        _refuse("mosaic_failed", f"[red]error:[/red] {escape(str(exc))}")

    spread = mosaic_module.spread(variants)
    try:
        shard_variants = batch_module.owned(
            variants, shard_count=shard_count, shard_index=shard_index,
        )
    except ValueError as exc:
        _refuse("bad_shard", f"[red]error:[/red] {escape(str(exc))}")
    if out is None and (resume or shard_count != 1 or shard_index != 0):
        _refuse("missing_flag", "[red]error:[/red] sharding and resume require --out",
                flag="--out")
    if narrate_exec and not narrate:
        _refuse(
            "narration_conflict",
            "[red]error:[/red] --narrate-exec names the writer, so it cannot ride"
            " with --no-narrate; drop --no-narrate to have the command write.",
            flag="--narrate-exec",
        )
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

    plan_document = {
        "batch_version": batch_module.PLAN_VERSION,
        "generator_version": __version__,
        "seed": seed,
        "count": count,
        "engine": engine,
        "period": period,
        "periods": periods,
        "incident": incident,
        "spread": spread,
        "narrated": narrate,
        "formats": sorted(formats or ()),
        "shard_count": shard_count,
        "worlds": [variant.as_dict() for variant in variants],
    }
    try:
        plan_digest = batch_module.install_plan(out, plan_document, resume=resume)
        shard_state = batch_module.ShardState(
            out, plan_digest=plan_digest,
            shard_count=shard_count, shard_index=shard_index, resume=resume,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _refuse("shard_state_error", f"[red]error:[/red] {escape(str(exc))}")

    from dataclasses import replace as _replace_spec

    from . import archetypes, domains
    from .execseam import ExecError
    from .narrative import DeterministicProvider, ExecProvider, ProviderError
    from .narrative.compiler import NarrationError
    from .render import RenderError
    from .scenarios import MonthEndClose

    # The domain names its own archetype. Core may not hold a map from a
    # vertical's name to one of its archetype keys — the thin-waist ratchet
    # forbids engine vocabulary here, and it caught exactly that map when this
    # was first written.
    registered = domains.by_name(engine)
    if registered is None or not registered.default_archetype:
        _refuse("unknown_engine",
                f"[red]error:[/red] no domain named {engine!r} is registered;"
                f" known: {', '.join(domains.names())}",
                registered=list(domains.names()))
    domain = registered
    shape = archetypes.get(domain.default_archetype)

    # One provider for the whole mosaic, and that is not a shared-state hazard:
    # `DeterministicProvider` reads a request and a fact table and holds nothing
    # between calls but a counter, so five worlds through one instance and five
    # worlds through five instances write the same bytes. The test asserts that
    # rather than trusting it — a provider that *did* carry state would make
    # world 5 depend on world 1 having been built, which is the one thing a
    # mosaic must never do (world N is reproducible without worlds 1..N-1).
    # `ExecProvider` holds no more: a command string and knobs, so the same
    # argument carries — the agent child is stateless across calls by contract,
    # and the ledger, not the provider instance, is what makes world N's prose
    # reproducible.
    if narrate_exec:
        provider = ExecProvider(
            narrate_exec,
            model_id=narrate_model_id,
            timeout=narrate_timeout,
            shell=narrate_shell,
        )
    else:
        provider = DeterministicProvider()

    written: list[str] = []
    narrated_sections = 0
    unhealthy = 0
    skipped = 0
    for variant in shard_variants:
        target = out / f"world-{variant.index:02d}"
        if resume and variant.index in shard_state.completed and target.exists():
            try:
                existing = _load(str(target))
                if existing.recipe.get("seed") != variant.seed:
                    raise ValueError(
                        f"world {variant.index} has seed {existing.recipe.get('seed')},"
                        f" expected {variant.seed}"
                    )
                existing.validate().raise_if_failed()
            except Exception as exc:
                _refuse(
                    "resume_invalid",
                    f"[red]error:[/red] completed world {variant.index} does not"
                    f" validate for resume: {escape(str(exc))}",
                    world=variant.index,
                )
            skipped += 1
            console.print(
                f"[cyan]↷[/cyan] [bold]world {variant.index}[/bold]"
                " [dim]already complete and validated[/dim]"
            )
            continue
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
        if narrate or narrate_exec:
            checkpoint = batch_module.Checkpoint(out, variant.index)
            try:
                checkpoint_ledger = checkpoint.load() if resume else ()
                if checkpoint.path.exists() and not resume:
                    raise ValueError(
                        f"checkpoint {checkpoint.path} already exists; pass --resume"
                    )
                world = world.narrate(
                    provider,
                    ledger=checkpoint_ledger,
                    concurrency=narration_concurrency,
                    on_accepted=checkpoint.append,
                )
            except (OSError, ValueError, ExecError, ProviderError, NarrationError) as exc:
                _refuse("narration_failed",
                        f"[red]error:[/red] world {variant.index}: {escape(str(exc))}",
                        world=variant.index)
            sections = world._narration[0]
            narrated_sections += sections

        # After narration, never before: `render` compiles if it must, and a
        # render that ran first would freeze the empty sections into the IR the
        # narration then had to be threaded back into.
        if formats:
            try:
                world = world.render(*formats)
            except RenderError as exc:
                _refuse("render_failed",
                        f"[red]error:[/red] world {variant.index}: {escape(str(exc))}",
                        world=variant.index)

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
        else:
            shard_state.mark_completed(variant.index)

    # `narrated` and `formats` ride in the plan because a reader of the
    # directory — `evaluate.across.load` above all — otherwise has to infer
    # from a passage count whether a thin corpus is an easy one or an
    # unfinished one, and those are the two readings this whole change exists
    # to stop being confusable.
    console.print(
        f"\n[green]✓[/green] shard {shard_index}/{shard_count} wrote"
        f" {len(written)} world(s) under [bold]{out}[/bold]"
        + (f"; {skipped} already complete" if skipped else "")
        + f"\n[dim]{spread['distinct_shapes']} distinct organisation shape(s);"
        f" headcounts {spread['headcounts']}; estates {spread['estates']}."
        + (f" {narrated_sections} section(s) of prose written." if narrate else "")
        + " The plan is in mosaic.json, and each world rebuilds from its own recipe.[/dim]"
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
        # What they found when this branch was written was one defect, in every
        # world of every engine: `author_cannot_see_own_artifact`, because
        # `roles.from_shape` dealt functions round-robin by position and put
        # the engine's `controller` in Merchandising while the policy on a
        # finance document named Finance. The corpora were always like that;
        # compiling them is what made it sayable, and it is fixed — a spine key
        # now keeps the function its engine gives it, a synthesised role
        # inherits its manager's, and a mosaic validates clean. The branch
        # stays because the next such defect will arrive the same way.
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
    """Check a corpus for coherence violations.

    A corpus built from a pack is checked under its own pack: `validate`
    reconstructs it from the corpus's recipe and installs it before the checks
    run, so an authored corpus's authored invariants are verified here and not
    only in the process that built it. See `validate._under_the_corpus_rules`.
    """
    world = _load(corpus)
    # `_load` maps a corpus that cannot be *read* to exit 2; a corpus whose own
    # rules cannot be *reconstructed* is the same kind of failure and gets the
    # same exit, one step later. Not caught inside `_report`, which the build
    # and render commands share: those hold a world they just built in this
    # process, where the pack is installed already and this cannot arise.
    from .corpus import CorpusError

    try:
        report = world.validate()
    except CorpusError as exc:
        _refuse("corpus_unloadable", f"[red]error:[/red] {escape(str(exc))}")
    if as_json:
        import json as json_module

        typer.echo(json_module.dumps({
            "ok": report.ok,
            "checks": report.checks_run,
            "violations": [
                {"group": v.group, "code": v.code, "subject": v.subject, "detail": v.detail}
                for v in report.violations
            ],
            # Beside `violations` rather than merged into it, for the reason the
            # channel exists: a caller filtering on `violations` is asking what
            # makes this corpus incoherent, and an advisory is not that.
            "advisories": [
                {"group": v.group, "code": v.code, "subject": v.subject, "detail": v.detail}
                for v in report.advisories
            ],
        }, indent=2))
        if not report.ok:
            raise typer.Exit(code=1)
        return
    if not _print_report(report):
        raise typer.Exit(code=1)


@app.command()
def verify(
    corpus: str = typer.Argument(..., help="Corpus path or bundled name."),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the verdict as JSON — files compared, checks run."
    ),
) -> None:
    """Rebuild this corpus from its own record and prove the bytes match.

    The trust demo as one verb: the corpus's recipe and generation ledger are
    rebuilt into a temporary directory, every file is byte-compared against the
    directory on disk, and the corpus is then validated. Exit 0 means this
    corpus is exactly what its own record regenerates, and coherent. The
    rebuild is the same machinery `build --replay` narrates with and `act`
    resumes with — `recipe.rebuild` plus a ledger-only provider — not a second
    replay path that could drift from the one CI proves.

    Rendered artifact files are compared only as the corpus holds them —
    verify never renders. A rebuild without rendering cannot reproduce the
    files `worldloom render` (or `-f` at build) wrote, so a rendered corpus
    reports its first rendered file as beyond the record: verify the corpus as
    built and narrated, and prove a rendering by replaying the build with the
    same `-f` flags (the README's three-command block).
    """
    import tempfile

    from . import corpus as corpus_module
    from . import recipe as recipe_module
    from .actors import ActorProviderError, UnreachableActorProvider
    from .narrative import ProviderError, UnreachableProvider
    from .recipe import RecipeError

    world = _load(corpus)
    root = world.root
    assert root is not None  # `World.load` always records where it read from
    if not world.recipe:
        _refuse(
            "no_recipe",
            "[red]error:[/red] this corpus carries no recipe, so it cannot be"
            " rebuilt — verification is a rebuild of the record.",
            corpus=str(corpus),
        )

    ledger = tuple(world._ledger)
    # The same replay stance `build --replay` takes, for the same reasons: the
    # provider id is a key component, so it comes from what the artifacts
    # record as `narrated_by`; several providers cannot be replayed in one
    # pass; and a rebuild that quietly *generated* where the ledger missed
    # would prove that a plausible corpus exists, not that this one is its own
    # record — which is why both providers below are the unreachable kind.
    narrated_ids = {
        ir.metadata["narrated_by"]
        for ir in world._artifact_irs
        if "narrated_by" in ir.metadata
    }
    if len(narrated_ids) > 1:
        _refuse(
            "replay_many_providers",
            f"[red]error:[/red] {corpus} was narrated by several providers"
            f" ({', '.join(sorted(narrated_ids))}); one narrate pass replays"
            " one provider's keys",
            providers=sorted(narrated_ids),
        )
    if narrated_ids and not ledger:
        _refuse(
            "no_ledger",
            f"[red]error:[/red] {corpus} carries no generation ledger to replay",
            corpus=str(corpus),
        )

    acted = recipe_module.has_actor_step(world.recipe)
    try:
        rebuilt = recipe_module.rebuild(
            world.recipe,
            actors=UnreachableActorProvider() if acted else None,
            actor_ledger=ledger if acted else (),
            ledger=ledger,
        )
        if narrated_ids:
            rebuilt = rebuilt.narrate(
                UnreachableProvider(id=narrated_ids.pop()), ledger=ledger
            )
    except RecipeError as exc:
        _refuse("recipe_error", f"[red]error:[/red] {escape(str(exc))}")
    except ActorProviderError as exc:
        _refuse("actor_episode_failed", f"[red]error:[/red] {escape(str(exc))}")
    except ProviderError as exc:
        _refuse("narration_failed", f"[red]error:[/red] {escape(str(exc))}")
    # Mirror what `build --out` does before exporting, so an unnarrated
    # corpus's rebuild carries the same artifact IR and manifest files its
    # build was exported with. (A narrated rebuild compiled inside `narrate`.)
    if not rebuilt.artifact_irs:
        rebuilt = _compiled(rebuilt, corpus)

    with tempfile.TemporaryDirectory(prefix="worldloom-verify-") as scratch:
        rebuilt_dir = Path(scratch) / "rebuilt"
        rebuilt.export(rebuilt_dir)
        divergence = corpus_module.tree_divergence(rebuilt_dir, root)
        files = sum(1 for path in rebuilt_dir.rglob("*") if path.is_file())

    if divergence is not None:
        if divergence.missing:
            first, kind = divergence.missing[0], "missing"
        elif divergence.extra:
            first, kind = divergence.extra[0], "extra"
        else:
            assert divergence.differing is not None  # the only remaining half
            first, kind = divergence.differing, "different"
        # The one divergence with a known innocent cause gets its explanation
        # in the message, not only in the envelope's `fix` — default mode
        # prints the message alone, and "your rendered corpus failed the trust
        # command" with no way out is the worst sentence this command could say.
        rendered_extra = kind == "extra" and first.startswith(
            f"{corpus_module.ARTIFACTS_DIR}/"
        )
        fix = (
            "verify never renders; prove a rendering by replaying the build"
            " with the same -f flags, and verify the corpus as built and"
            " narrated"
            if rendered_extra else None
        )
        _refuse(
            "verify_diverged",
            f"[red]✗[/red] diverged at {escape(first)} ({kind}): this corpus's"
            " bytes are not what its own recipe and ledger rebuild"
            + (f" — {fix}" if fix else ""),
            exit_code=1,
            fix=fix,
            path=first,
            kind=kind,
            missing=list(divergence.missing),
            extra=list(divergence.extra),
        )

    # Validate the corpus on disk, exactly as `worldloom validate` would —
    # byte-identity has just made "the corpus" and "its rebuild" the same
    # thing, and the on-disk world is the one whose artifact files exist to
    # check. Same `CorpusError` posture as `validate`: a corpus whose own pack
    # cannot be reconstructed fails the same way as one that cannot be read.
    from .corpus import CorpusError

    try:
        report = world.validate()
    except CorpusError as exc:
        _refuse("corpus_unloadable", f"[red]error:[/red] {escape(str(exc))}")

    if as_json:
        typer.echo(json.dumps({
            "verified": report.ok,
            "files": files,
            "checks": report.checks_run,
            "violations": [
                {"group": v.group, "code": v.code, "subject": v.subject, "detail": v.detail}
                for v in report.violations
            ],
        }, indent=2))
        if not report.ok:
            raise typer.Exit(code=1)
        return
    if not _print_report(report, quiet=True):
        raise typer.Exit(code=1)
    console.print(
        f"[green]✓[/green] verified — {files} files byte-identical,"
        f" {report.checks_run} checks passed"
    )


@app.command()
def migrate(
    corpus: str = typer.Argument(..., help="Bundled corpus name or path."),
    out: Path = typer.Option(..., "--out", "-o", help="Directory to write the migrated corpus into."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace the destination if it exists."),
) -> None:
    """Copy a corpus to --out, upgraded to the current schema version.

    Today the chain of version-to-version steps is empty, so this is the
    identity migration: verify the version, copy byte-for-byte. An unknown or
    future schema version is refused with both versions named — see
    `worldloom.migrate` for the bump policy and `tests/test_migrate.py` for
    the frozen fixture that enforces it.
    """
    # Imported here, not at module top: cli.py startup is a budget (W6), and
    # migration is a maintenance verb no other command should pay for.
    from .corpus import CorpusError
    from .migrate import migrate as migrate_corpus

    try:
        written = migrate_corpus(corpus, out, overwrite=overwrite)
    except CorpusError as exc:
        _refuse("corpus_unloadable", f"[red]error:[/red] {escape(str(exc))}",
                corpus=str(corpus))
    except FileExistsError as exc:
        _refuse("destination_exists", f"[red]error:[/red] {escape(str(exc))}",
                fix="pass --overwrite to replace it")
    except ValueError as exc:
        # `migrate` names both versions in the message; the envelope carries
        # the corpus so a harness need not parse them back out of prose.
        _refuse("schema_version", f"[red]error:[/red] {escape(str(exc))}",
                corpus=str(corpus))
    console.print(f"[green]✓[/green] migrated to [bold]{written}[/bold]")


#: One help string for both fleet verbs, because the refusal is part of the
#: contract: "naturalistic" is not a hidden value waiting to be typed, it is a
#: purpose `worldloom.fleet` refuses with the reference data it would need.
_FLEET_PURPOSE_HELP = (
    "What the fleet is being admitted for: challenge (it will be used to "
    "challenge a retrieval or assistant system) or counterfactual (controlled "
    "comparison against a shared frame). 'naturalistic' is refused, naming "
    "the reference data it would need."
)


@fleet_app.command("qualify")
def fleet_qualify(
    fleet_dir: str = typer.Argument(
        ..., help="A directory of member corpora — a mosaic out dir, or any directory of builds."
    ),
    purpose: str = typer.Option("challenge", "--purpose", help=_FLEET_PURPOSE_HELP),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the full qualification record as JSON."
    ),
    out: Path = typer.Option(
        None, "--out", "-o",
        help="Also write the record here — byte-stable, so it can be checked in and diffed.",
    ),
) -> None:
    """Measure a fleet and rule on whether it is qualified for its purpose.

    Exit 1 when the fleet is not qualified, with every failed floor named —
    the same posture `worldloom validate` takes one level down: the exit code
    is the verdict and the text is the reason.
    """
    from . import fleet as fleet_module

    try:
        record = fleet_module.qualify(fleet_dir, purpose)  # type: ignore[arg-type]
    except fleet_module.FleetError as exc:
        _refuse("fleet_error", f"[red]error:[/red] {escape(str(exc))}")

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(record.manifest(), encoding="utf-8")

    if as_json:
        typer.echo(record.manifest(), nl=False)
        if not record.qualified:
            raise typer.Exit(code=1)
        return

    table = Table(title=f"fleet {record.fleet} — {record.purpose}",
                  title_style="bold", box=None)
    table.add_column("world", style="bold")
    table.add_column("coherent")
    table.add_column("replays")
    table.add_column("questions", justify="right")
    for world in record.worlds:
        table.add_row(
            world.name,
            "[green]yes[/green]" if world.ok else f"[red]no ({world.violations})[/red]",
            "[green]yes[/green]" if world.replay_verified else "[red]no[/red]",
            str(world.questions),
        )
    console.print(table)
    console.print(
        f"[dim]coverage {record.coverage['share']:.0%} of {record.coverage['combinations']}"
        f" pair(s); unvaried: {', '.join(record.unvaried) or 'none'};"
        f" spine {record.spine['share']}; questions restated across worlds"
        f" {record.questions['cross_world_restated_share']:.0%};"
        f" effective diversity {record.effective_diversity['vendi_questions']}"
        f" (reported, non-gating)[/dim]"
    )
    if record.qualified:
        console.print(f"[green]✓[/green] qualified for [bold]{record.purpose}[/bold]")
        return
    for name in record.failed:
        err.print(f"[red]✗[/red] {name}: {escape(record.floors[name]['detail'])}")
    raise typer.Exit(code=1)


@fleet_app.command("curate")
def fleet_curate(
    fleet_dir: str = typer.Argument(
        ..., help="A directory of member corpora — a mosaic out dir, or any directory of builds."
    ),
    purpose: str = typer.Option("challenge", "--purpose", help=_FLEET_PURPOSE_HELP),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the manifest as JSON instead of a table."
    ),
) -> None:
    """Keep one champion per niche; name every reject and every empty niche.

    Writes `fleet-manifest.json` at the fleet root, byte-for-byte stable for
    the same fleet. Exit 0 either way: a curation is a keep list, not a gate —
    `fleet qualify` owns pass/fail.
    """
    from . import fleet as fleet_module

    try:
        curation = fleet_module.curate(fleet_dir, purpose)  # type: ignore[arg-type]
    except fleet_module.FleetError as exc:
        _refuse("fleet_error", f"[red]error:[/red] {escape(str(exc))}")

    if as_json:
        typer.echo(curation.manifest(), nl=False)
        return

    for champion in curation.champions:
        niche = ", ".join(f"{key}={champion.niche[key]}" for key in sorted(champion.niche))
        console.print(f"[green]✓[/green] [bold]{champion.world}[/bold] holds"
                      f" ({niche}) at {curation.fitness_metric}={champion.fitness}")
    for reject in curation.rejects:
        displaced = f" — displaced by {reject.displaced_by}" if reject.displaced_by else ""
        console.print(f"[yellow]-[/yellow] {reject.world}: {escape(reject.reason)}{displaced}")
    for hole in curation.holes:
        niche = ", ".join(f"{key}={hole[key]}" for key in sorted(hole))
        console.print(f"[dim]· empty niche ({niche}) — next generation's worklist[/dim]")
    console.print(
        f"[dim]{len(curation.champions)} champion(s), {len(curation.rejects)} reject(s),"
        f" {len(curation.holes)} empty niche(s)."
        f" The manifest is in {fleet_module.MANIFEST_NAME}.[/dim]"
    )


@app.command("evolve")
def evolve_run(
    generations: int = typer.Option(
        3, "--generations", "-g",
        help="How many generations to run, the dispersed generation 0 included.",
    ),
    population: int = typer.Option(
        6, "--population", "-n",
        help="Configurations proposed and built per generation.",
    ),
    seed: int = typer.Option(
        8128, "--seed", "-s",
        help="Run seed. The same seed reruns the same evolution byte for byte.",
    ),
    purpose: str = typer.Option("challenge", "--purpose", help=_FLEET_PURPOSE_HELP),
    out: Path = typer.Option(
        ..., "--out", "-o",
        help="Directory the generations are built into: gen0/, gen1/, ... each"
             " with its own manifest beside fleet's.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the run manifest as JSON instead of a summary."
    ),
) -> None:
    """Evolve build configurations: propose, build, measure, select, vary.

    Generation 0 is a dispersed sample of the build-configuration space;
    every later generation is single-axis variations of the previous
    generation's champions, exactly as `fleet curate` kept them. Fitness and
    selection are fleet's own — integer-gated, vendi reported and never
    gating — and a purpose fleet refuses ('naturalistic') is refused here at
    the door with the same reason. Deterministic throughout: rerunning the
    same seed resumes an interrupted run and rewrites byte-identical
    manifests.
    """
    from . import evolve as evolve_module
    from . import fleet as fleet_module
    from . import spaces as spaces_module

    space = spaces_module.build_space()
    # Narrowed as a visible act, never silently inside the loop: `evolve`
    # refuses a space carrying an axis it cannot drive, so each exclusion is
    # printed with its reason (`surface` above all — a spec is resolved and
    # never recorded, so selection could not see that axis move).
    undrivable = evolve_module.excluded(space)
    for name, reason in sorted(undrivable.items()):
        err.print(f"[yellow]axis {name} not evolved:[/yellow] {escape(reason)}")
    space = space.select([n for n in space.names if n not in undrivable])
    try:
        run = evolve_module.evolve(
            space, seed=seed, generations=generations, population=population,
            out_dir=out, purpose=purpose,  # type: ignore[arg-type]
        )
    except (evolve_module.EvolveError, fleet_module.FleetError) as exc:
        _refuse("evolve_failed", f"[red]error:[/red] {escape(str(exc))}")

    if as_json:
        typer.echo(run.manifest(), nl=False)
        return
    for generation in run.generations:
        champions = ", ".join(generation.champions) or "none"
        variations = ", ".join(
            f"{member.label} {member.axis}->{member.to_value}"
            for member in generation.members if member.axis
        )
        console.print(
            f"[bold]gen{generation.index}[/bold]: {len(generation.members)} built,"
            f" champion(s): {champions}"
            + (f" — varied {variations}" if variations else " — dispersed sample")
        )
    console.print(
        f"[dim]{evolve_module.RUN_MANIFEST_NAME} and"
        f" gen*/{evolve_module.GENERATION_MANIFEST_NAME} record the run under {out}.[/dim]"
    )


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
            "src/worldloom/evaluate/tfidf.py), embedding (dense vectors against "
            "a pinned model — needs the `embeddings` extra or a vector cache), "
            "both (the two lexical baselines side by side, with a per-family "
            "agreement reading), or all (every retriever this installation can "
            "run, skipping any whose model is unavailable)."
        ),
    ),
    vectors: str = typer.Option(
        "", "--vectors",
        help=(
            "Vector cache for --retriever embedding: a file, or a directory to "
            "keep one per model. A corpus that carries its cache scores against "
            "the embedding retriever with no model installed at all."
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
    """Score one or more retrievers against the corpus's evaluation set.

    A *low* score on the hard question types is the good result. No retriever
    here has any notion of when a document was written or how authoritative it
    is, so a corpus on which they do well on temporal and authority questions is
    a corpus that is not testing anything. `--retriever both` is the stronger
    claim: a family low under BM25 *and* TF-IDF cosine — two different ranking
    families — is hard because of the corpus, not because of which keyword
    heuristic happened to be asked. `--retriever all` is stronger still, because
    both of those are still *keyword* heuristics: a family the embedding
    retriever also fails is hard for a reason no ranking function fixes, and a
    family it walks past was a lexical trap rather than a difficult question.
    """
    import json as json_module

    from .evaluate import (
        LEXICAL_RETRIEVERS,
        RETRIEVERS,
        compare,
        difficulty_by_family,
        embedding,
        render_agreement,
        render_difficulty,
    )
    from .evaluate import score as run_score

    choices = sorted([*RETRIEVERS, "both", "all"])
    if retriever not in choices:
        raise typer.BadParameter(f"must be one of {choices}", param_hint="--retriever")

    if vectors:
        # Bound for this invocation only, and by rebinding the registry entry
        # rather than by threading a path through `score()` — the scorer takes
        # documents and a name, and giving it an argument only one retriever
        # understands is exactly the branch the seam exists to prevent.
        RETRIEVERS["embedding"] = embedding.configured(cache=vectors)

    world = _compiled(_load(corpus), corpus)

    if retriever in ("both", "all"):
        # `both` is the two lexical baselines, and stays that way whatever else
        # gets registered: it is the pre-existing reading, its JSON shape is
        # pinned by tests, and "lexical versus semantic" is only a comparison
        # while the lexical side is a fixed pair.
        wanted = list(LEXICAL_RETRIEVERS) if retriever == "both" else sorted(RETRIEVERS)
        cards = {}
        for name in wanted:
            try:
                cards[name] = run_score(world, k=k, retriever=name)
            except embedding.EmbeddingUnavailable as unavailable:
                # A skip, not a failure. The two lexical readings are still a
                # measurement, and saying which one was missing and why is more
                # use than an exit code — see `embedding.py`'s docstring on
                # being absent-friendly.
                if not as_json:
                    # Escaped: the message names the extra as
                    # `worldloom[embeddings]`, and rich reads a bracketed word
                    # as a style tag and prints the instruction with the part
                    # you have to type removed.
                    console.print(f"[yellow]skipped {name}[/yellow] — {escape(str(unavailable))}")
                continue
        if not cards:
            raise typer.Exit(1)
        findings = compare(cards)
        # Only computed where a semantic retriever actually ran. `both` is two
        # lexical baselines, and printing "lexical vs semantic" over a table
        # with no semantic column in it would be a heading describing an
        # experiment that did not happen.
        difficulty = difficulty_by_family(cards)
        if as_json:
            # A new top-level shape, not a variant of the single-retriever one —
            # `retriever="both"` is a capability nothing could request before
            # this flag existed, so there is no old consumer whose parsing this
            # could break. The single-retriever shape below (`bm25`, the
            # default, and `tfidf`) is untouched byte-for-byte.
            typer.echo(json_module.dumps({
                "retriever": retriever,
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
                # Additive, and absent when only lexical retrievers ran — so
                # `--retriever both`'s payload keeps exactly the shape it had.
                **(
                    {
                        "difficulty": {
                            finding.evaluation_type.value: {
                                "lexical": {"passed": finding.lexical[0], "total": finding.lexical[1]},
                                "semantic": {"passed": finding.semantic[0], "total": finding.semantic[1]},
                                "verdict": finding.verdict,
                            }
                            for finding in difficulty
                        }
                    }
                    if difficulty
                    else {}
                ),
            }, indent=2))
            return
        for name in sorted(cards):
            console.print(str(cards[name]))
            console.print("")
        console.print(render_agreement(findings))
        if difficulty:
            console.print("")
            console.print(render_difficulty(difficulty))
        if verbose:
            for name in sorted(cards):
                console.print(f"\n[bold]{name}[/bold]")
                for outcome in cards[name].outcomes:
                    mark = "[green]✓[/green]" if outcome.passed else "[red]✗[/red]"
                    console.print(f"  {mark} {outcome.case_id}  {outcome.evaluation_type.value}")
                    console.print(f"      {outcome.detail}")
        return

    try:
        card = run_score(world, k=k, retriever=retriever)
    except embedding.EmbeddingUnavailable as unavailable:
        # Explicitly asked for, and not runnable. Nonzero, because a command
        # that printed nothing and exited clean would read as "scored, no
        # findings" — but a stated reason and no traceback, because this is a
        # missing optional package, not a defect.
        console.print(f"[red]cannot run {retriever}[/red] — {escape(str(unavailable))}")
        raise typer.Exit(1) from None
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
def search(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    query: str = typer.Argument(..., help="What to look for, in plain words."),
    limit: int = typer.Option(5, "-k", "--limit", help="How many passages to return."),
    as_of: str = typer.Option(
        "", "--as-of",
        help=(
            "ISO date or datetime; only passages from artifacts created at or "
            "before this moment are searched. This is the temporal-cutoff rule "
            "the narration contract already imposes on facts, applied to "
            "retrieval: an author amending a document in March may only lean "
            "on what existed in March."
        ),
    ),
    include_hidden: bool = typer.Option(
        False, "--include-hidden",
        help=(
            "Search hidden sections (lineage appendices) too. Off by default "
            "for `evaluate`'s reason: machinery is not something a reader "
            "would have found."
        ),
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit ranked passages as JSON, full text included.",
    ),
) -> None:
    """Rank the corpus's own passages against a query, BM25, deterministic.

    The retrieval half of self-referential narration: before writing a document
    that amends, summarises or contradicts earlier ones, ask the corpus what it
    already says. This is the same passage index and the same ranking
    `evaluate` scores retrievers with — so what the harness retrieves here is
    exactly what the benchmark's baseline retriever would have seen, and a
    corpus searched while it is being written is searched the way it will be
    judged. Read-only: nothing here writes a byte.
    """
    from datetime import datetime

    from .evaluate.bm25 import Bm25
    from .evaluate.index import passages as index_passages

    if not query.strip():
        _refuse("empty_query",
                "[red]error:[/red] an empty query ranks every passage equally; say what you are looking for")
    cutoff = None
    if as_of:
        try:
            cutoff = datetime.fromisoformat(as_of)
        except ValueError as exc:
            _refuse("not_a_date",
                    f"[red]error:[/red] --as-of {as_of!r} is not an ISO date: {escape(str(exc))}")
        if cutoff.tzinfo is None:
            # Corpus timestamps are timezone-aware UTC throughout; a bare
            # `--as-of 2026-03-01` would otherwise crash on the comparison.
            # Reading it as UTC matches what every timestamp in the corpus
            # means, rather than what the caller's machine is set to.
            cutoff = cutoff.replace(tzinfo=UTC)

    world = _compiled(_load(corpus), corpus)
    found = index_passages(world, include_hidden=include_hidden)
    if cutoff is not None:
        found = [passage for passage in found if passage.created_at <= cutoff]
    if not found:
        # An empty index is a state of the corpus, not a poor query, so it is
        # an error rather than a zero-result success — and it names the flag
        # that caused it when one did.
        reason = (
            f"no artifact existed at or before {cutoff.isoformat()}" if cutoff is not None
            else "this corpus has no retrievable passages"
        )
        _refuse("no_passages", f"[red]error:[/red] nothing to search: {reason}")

    index = Bm25([passage.text for passage in found])
    ranked = index.rank(query, limit=max(1, limit))
    hits = [
        {
            "passage_id": found[position].id,
            "artifact_id": found[position].artifact_id,
            "heading": found[position].heading,
            "created_at": found[position].created_at.isoformat(),
            "authority": found[position].authority.value,
            "score": score,
            "fact_ids": sorted(found[position].fact_ids),
            "text": found[position].text,
        }
        for position, score in ranked
        if score > 0.0
        # Zero-score passages share no term with the query; returning them
        # would pad the list with whatever document order put first and call
        # it a ranking.
    ]

    if as_json:
        typer.echo(json.dumps({"query": query, "searched": len(found), "hits": hits}, indent=2))
        return
    if not hits:
        console.print(f"no passage shares a term with {query!r} ({len(found)} searched)")
        return
    console.print(f"[bold]{len(hits)}[/bold] of {len(found)} passages, best first\n")
    for hit in hits:
        snippet = " ".join(str(hit["text"]).split())
        if len(snippet) > 220:
            snippet = snippet[:220] + "…"
        console.print(
            f"  [cyan]{hit['passage_id']}[/cyan]  {hit['heading']}"
            f"  [dim]{hit['created_at']} · {hit['authority']} · {hit['score']:.3f}[/dim]"
        )
        console.print(f"      {escape(snippet)}\n")


@benchmark_app.command("run")
def benchmark_run(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    exec_command: str = typer.Option(
        ..., "--exec",
        help=(
            "The agent as an executable: reads one case's JSON on stdin, "
            "prints its answer JSON on stdout. Run without a shell (shlex "
            "argv) unless --shell is given."
        ),
    ),
    k: int = typer.Option(5, "-k", help="How many passages each case offers the agent."),
    limit: int = typer.Option(
        0, "--limit", help="Score only the first N cases; 0 means all of them."
    ),
    timeout: float = typer.Option(
        600.0, "--timeout",
        help="Seconds the child may run per case before it is killed and refused.",
    ),
    shell: bool = typer.Option(
        False, "--shell",
        help="Run the command through the shell — the opt-in for pipelines.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the scorecard as JSON, labelled with the exec command."
    ),
) -> None:
    """Score an executable agent against the corpus's own evaluation set.

    Per case the child receives `{"question": ..., "passages": [{"passage_id",
    "text"}, ...]}` — the top-k from the same BM25 index `search` and
    `evaluate` rank with — and must print `{"answer_passage_ids": [...],
    "abstain": bool}`. Scoring is id-based only, never text similarity: a case
    passes when the returned passages carry the expected fact IDs and the
    abstention flag matches the case's expectation. Grading answer *text*
    would put a judge inside a benchmark whose whole point is mechanical
    ground truth, so there is deliberately no flag for it.
    """
    from . import execseam

    world = _compiled(_load(corpus), corpus)
    try:
        card = execseam.benchmark_run(
            world, exec_command, k=k, limit=limit or None,
            timeout=timeout, shell=shell,
        )
    except execseam.ExecError as exc:
        _refuse_exec_error(exc)
    except ValueError as exc:
        # `benchmark_run` raises exactly `evaluate.score()`'s empty-pool
        # sentence for exactly its state; the CLI maps it to the same code
        # `search` uses for a passage-less corpus.
        _refuse("no_passages", f"[red]error:[/red] {escape(str(exc))}")

    if as_json:
        import json as json_module

        # The single-retriever `evaluate --json` shape with `exec` in place of
        # `retriever` — same `k`/`overall`/`by_type`/`outcomes` fragment, so a
        # harness that parses one scorecard parses both.
        typer.echo(json_module.dumps(
            {"exec": exec_command, "k": card.k, **_card_json(card)}, indent=2
        ))
        return
    console.print(f"[bold]exec:[/bold] {escape(exec_command)}")
    console.print(str(card))


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
    across: list[str] = typer.Option(
        None, "--across",
        help=(
            "Additional corpora to compare against — repeatable. Reports shape "
            "overlap and cross-corpus prose duplicates over the whole set, the "
            "failure no single corpus's report can see: five mosaic companies can "
            "each look varied while all five hold the same shapes and say the "
            "same sentences."
        ),
    ),
    effective: bool = typer.Option(
        False, "--effective",
        help=(
            "Also report the Vendi score — the *effective* number of distinct "
            "shapes, which is what a count of distinct shapes overstates. Thirty "
            "shapes that differ by one section each are closer to four documents "
            "than to thirty, and only a metric that reads the similarity matrix "
            "rather than counting equality classes can say so."
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

        if effective:
            # The count and the effective count are two different readings of
            # one batch, and the gap between them is the finding.
            #
            # `1 - compiler.diversity.distance` is the obvious kernel here and
            # it is wrong. That blend is a metric in [0, 1], which buys symmetry
            # and a unit diagonal but *not* positive semi-definiteness — and
            # `vendi` reads the eigenvalues as a probability distribution, so a
            # negative one makes the score meaningless rather than imprecise.
            # Measured on fingerprints shaped the way `stats.census` actually
            # produces them (empty `layouts`, empty `style_key`, so the
            # Levenshtein term carries most of the blend): 11 of 400 random
            # single-type batches and 13 of 400 three-type batches are not PSD,
            # worst eigenvalue -0.003. It passes on most corpora and raises on
            # about three in a hundred, which is the worst way for a reading to
            # be wrong.
            #
            # Jaccard over sets *is* PSD by construction, so the kernel is a
            # feature set instead: the artifact type, the density bucket, the
            # section count, and the adjacent component pairs. Bigrams for the
            # reason `compiler.diversity` already gives for `_NGRAM_SIZE = 2` —
            # the smallest window that sees adjacency — and the three scalar
            # features so the set is never empty, which would make Jaccard 0/0
            # for a fingerprint whose composition resolved to nothing.
            from .vendi import vendi_of

            def features(fp: Fingerprint) -> frozenset[tuple[str, ...]]:
                pairs = zip(fp.components, fp.components[1:], strict=False)
                return frozenset(
                    {
                        ("type", fp.artifact_type),
                        ("density", fp.density_bucket),
                        ("sections", str(fp.section_count)),
                    }
                    | {("bigram", a, b) for a, b in pairs}
                )

            sets = [features(fp) for fp in fingerprints]

            def jaccard(a: frozenset[Any], b: frozenset[Any]) -> float:
                union = len(a | b)
                return 1.0 if not union else len(a & b) / union

            score = vendi_of(sets, jaccard)
            distinct = len({fp.digest() for fp in fingerprints})
            console.print(
                f"\neffective shapes: [bold]{score:.1f}[/bold] of {distinct} distinct"
                f" over {len(fingerprints)} artifacts"
            )
            if distinct > 1:
                console.print(
                    f"[dim]  {score / distinct:.0%} of the distinct count survives"
                    " being read as a similarity rather than an equality[/dim]"
                )

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

    if across:
        # The fleet-level reading no single corpus can give. Shape overlap
        # first (structure), then prose duplicates over the pooled passages
        # (surface) — the same two-failure split `--near-duplicates`'s help
        # text draws, measured across corpora instead of within one.
        from .compiler.diversity import cross_report
        from .stats import near_duplicate_clusters

        batches = {corpus: fingerprints}
        pool = list(passages(world))
        origin = [corpus] * len(pool)
        for other_name in across:
            other = _load(other_name)
            if not other.artifact_irs:
                try:
                    other = other.compile()
                except ValueError:
                    pass
            batches[other_name] = list(census(other).fingerprints)
            other_passages = list(passages(other))
            pool.extend(other_passages)
            origin.extend([other_name] * len(other_passages))

        console.print("")
        console.print(str(cross_report(batches)))

        groups = near_duplicate_clusters(pool)
        spanning = [
            group for group in groups
            if len({origin[i] for i in group}) > 1
        ]
        if not spanning:
            console.print("[green]✓[/green] no near-duplicate passages span corpora")
        else:
            console.print(
                f"[bold]near-duplicate passages spanning corpora[/bold] ({len(spanning)})"
            )
            for group in spanning[:10]:
                where = ", ".join(sorted({
                    f"{origin[i]}:{pool[i].artifact_id}" for i in group
                })[:6])
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
        _refuse("no_matching_facts",
                "[red]error:[/red] no period-keyed numeric facts match that kind/subject")

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
        _refuse(
            "history_too_short",
            f"[red]error:[/red] {escape(str(exc))}\n"
            "[dim]Build a longer history with --comparatives, or name a shorter "
            "--cycle.[/dim]",
            fix="build a longer history with --comparatives, or name a shorter --cycle",
        )

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
        _refuse("mcp_unavailable", f"[red]error:[/red] {escape(str(exc))}")


@app.command()
def twin(
    corpus: str = typer.Argument(..., help="Corpus name or path."),
    set_: str = typer.Option(
        ..., "--set",
        help="PATH=VALUE: one recorded recipe value to replace, slash-separated"
             " because physics names are dotted — e.g."
             " physics/retail.margin.erosion/high=0.06, steps/0/trend_pct=0.008."
             " VALUE is parsed as JSON, falling back to a bare string.",
    ),
    out: Path = typer.Option(
        None, "--out", "-o",
        help="Directory to write the counterfactual corpus into. Omit to"
             " measure the delta without keeping the twin.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the delta manifest as JSON — stable keys and ordering."
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace the destination if it exists."
    ),
) -> None:
    """Rebuild this corpus with one recorded value replaced, and measure the delta.

    A counterfactual twin: same recipe, same ledger, one declared intervention.
    Because `recipe.rebuild` is a pure function of what the corpus records, every
    row that differs between the two worlds differs because of the intervention —
    the delta manifest names the changed facts, documents and evaluation cases,
    with the unchanged counts beside them as the denominator.

    An intervention that changes *how many* things exist (a policy level, an
    incident switched off) reshuffles sequentially-minted ids and is refused with
    the cause rather than diffed; exit code 3 says "refused", so a loop can tell
    a refusal from a failure without parsing prose. See `worldloom.twins`.
    """
    from . import twins as twins_module
    from .recipe import RecipeError

    if "=" not in set_:
        _refuse("intervention_syntax", "[red]error:[/red] --set takes PATH=VALUE")
    raw_path, _, raw_value = set_.partition("=")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        # A bare string like `--set policies=full`. Deliberate: quoting JSON
        # strings through a shell is misery, and no recipe value is ambiguous
        # between "the string full" and anything else.
        value = raw_value

    world = _load(corpus)
    if not world.recipe:
        _refuse(
            "no_recipe",
            "[red]error:[/red] this corpus carries no recipe, so it cannot be"
            " rebuilt — twins are measured between two rebuilds of the record.",
        )

    try:
        result = twins_module.twin(
            world.recipe, tuple(world._ledger),
            twins_module.Intervention(raw_path.strip(), value),
        )
    except (twins_module.TwinError, RecipeError) as exc:
        _refuse("unrecorded_path", f"[red]error:[/red] {escape(str(exc))}")

    manifest = result.manifest
    if out is not None and manifest.refused is None:
        result.world.export(out, overwrite=overwrite)

    if as_json:
        console.print_json(json.dumps(manifest.as_dict()))
    else:
        stated = manifest.intervention
        console.print(
            f"[bold]{stated['path']}[/bold]: {stated['before']!r} -> {stated['after']!r}"
        )
        if manifest.refused is not None:
            err.print(f"[red]refused:[/red] {escape(manifest.refused)}")
        else:
            table = Table(show_header=True, header_style="bold")
            table.add_column("stream")
            table.add_column("changed", justify="right")
            table.add_column("unchanged", justify="right")
            for stream, ids in (
                ("facts", manifest.changed_fact_ids),
                ("events", manifest.changed_event_ids),
                ("artifacts", manifest.changed_artifact_ids),
                ("evaluations", manifest.changed_evaluation_ids),
                ("entities", manifest.changed_entity_ids),
                ("records", manifest.changed_record_ids),
            ):
                table.add_row(stream, str(len(ids)), str(manifest.unchanged_counts[stream]))
            console.print(table)
            if manifest.is_null:
                console.print(
                    "[dim]No row changed: the intervention was absorbed (or was"
                    " the identity). That is a measurement, not a failure.[/dim]"
                )
            if out is not None:
                console.print(f"Counterfactual corpus written to [bold]{out}[/bold]")

    if manifest.refused is not None:
        raise typer.Exit(code=3)


@app.command()
def mutate(
    corpus_or_recipe: str = typer.Argument(
        ..., help="Corpus name or path, or a recipe JSON file."
    ),
    set_: list[str] = typer.Option(
        ..., "--set",
        help="PATH=VALUE: one recorded recipe value to replace; repeat for"
             " several. Same slash-separated grammar as `twin`, because"
             " physics names are dotted — e.g."
             " physics/retail.margin.erosion/high=0.06, steps/0/trend_pct=0.008."
             " VALUE is parsed as JSON, falling back to a bare string.",
    ),
    out: Path = typer.Option(
        ..., "--out", "-o", help="File to write the mutated recipe to."
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Replace the destination if it exists."
    ),
) -> None:
    """Apply interventions to a recipe and write the mutated recipe — no build.

    `twin` applies one intervention and pays for two builds to measure the
    delta; this applies N and pays for none, so a harness can fan out
    structural candidates cheaply and buy builds only for winners. The output
    is an ordinary recipe: `worldloom build --replay`-able, `twin`-able, and
    accepted back here as CORPUS_OR_RECIPE for a further round.

    Every refusal `twin` makes survives the missing build, on `twin`'s own
    exit taxonomy: an unrecorded path is a caller error (exit 2); a path that
    decides what exists rather than what is true about it — a policy level,
    an incident flag, a headcount — is refused (exit 3), because rebuilding
    it would reshuffle sequentially-minted ids and break the alignment every
    delta depends on; and two --set values for one path are an error naming
    the path, since last write winning would hide a fan-out bug until a build
    exposed it. See `worldloom.twins.mutated`.
    """
    from . import twins as twins_module
    from .recipe import RecipeError

    interventions = []
    for entry in set_:
        if "=" not in entry:
            _refuse("intervention_syntax",
                    f"[red]error:[/red] --set takes PATH=VALUE, got {escape(entry)!r}")
        raw_path, _, raw_value = entry.partition("=")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            # Same fallback as `twin`, for the same reason: quoting JSON
            # strings through a shell is misery, and no recipe value is
            # ambiguous between "the string full" and anything else.
            value = raw_value
        interventions.append(twins_module.Intervention(raw_path.strip(), value))

    source = Path(corpus_or_recipe)
    if source.is_file():
        # A bare recipe file — what a previous `mutate --out` wrote, or a
        # recipe lifted from a corpus header. The fan-out case: candidates
        # exist as recipes precisely because no corpus was built for them.
        try:
            recipe_document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _refuse("unreadable_document",
                    f"[red]error:[/red] {corpus_or_recipe}: {escape(str(exc))}",
                    path=str(corpus_or_recipe))
        if not isinstance(recipe_document, dict):
            _refuse(
                "not_a_recipe",
                f"[red]error:[/red] {corpus_or_recipe} does not hold a recipe object",
                path=str(corpus_or_recipe),
            )
    else:
        world = _load(corpus_or_recipe)
        recipe_document = world.recipe
        if not recipe_document:
            _refuse(
                "no_recipe",
                "[red]error:[/red] this corpus carries no recipe, so there is"
                " nothing to mutate — a mutation is an edit to the record.",
            )

    try:
        result = twins_module.mutated(recipe_document, interventions)
    except twins_module.MutationRefused as exc:
        _refuse("existence_path", f"[red]refused:[/red] {escape(str(exc))}",
                exit_code=3)
    except (twins_module.TwinError, RecipeError) as exc:
        _refuse("unrecorded_path", f"[red]error:[/red] {escape(str(exc))}")

    if out.exists() and not overwrite:
        _refuse("destination_exists",
                f"[red]error:[/red] {out} exists; pass --overwrite to replace it",
                fix="pass --overwrite to replace it")
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    for intervention in interventions:
        # The before is read off the source recipe for display, exactly as
        # `twin` states it — safe to walk without the grammar's own errors
        # because `mutated` already resolved every path or raised above.
        node: Any = recipe_document
        for segment in intervention.path.split("/"):
            node = node[int(segment) if isinstance(node, list) else segment]
        console.print(
            f"[bold]{intervention.path}[/bold]: {node!r} -> {intervention.value!r}"
        )
    console.print(f"Mutated recipe written to [bold]{out}[/bold]")


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
        _refuse("stats_failed", f"[red]error:[/red] {corpus}: {escape(str(exc))}",
                corpus=str(corpus))

    other_report = None
    if against:
        other_world = _for_stats(against)
        try:
            other_report = stats_module.compute(other_world)
        except ValueError as exc:
            _refuse("stats_failed", f"[red]error:[/red] {against}: {escape(str(exc))}",
                    corpus=str(against))

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
def fidelity(
    reference: Path = typer.Argument(..., help="The real table: CSV, JSONL, JSON array, or a corpus directory."),
    synthetic: Path = typer.Argument(..., help="The synthetic table, in any of the same forms."),
    table: str = typer.Option(
        "", "--table",
        help="When either side is a corpus directory, the detail table to read from it.",
    ),
    categorical: list[str] = typer.Option(
        None, "--categorical",
        help="Treat this column as categorical even though every value parses as a number — an id, a code. Repeatable.",
    ),
    ignore: list[str] = typer.Option(None, "--ignore", help="Leave this column out entirely. Repeatable."),
    slices: list[str] = typer.Option(
        None, "--slices",
        help="Report the per-column block again per value of this column, most frequent first. Repeatable.",
    ),
    seed: int = typer.Option(0, "--seed", help="Seed for the subsample the two quadratic blocks take past 2,000 rows."),
    as_json: bool = typer.Option(False, "--json", help="Emit the whole vector as JSON — stable keys, safe to diff."),
) -> None:
    """Compare a synthetic table with a real one, dimension by dimension — never as one score.

    Per column: KS and Wasserstein for numbers, Jensen–Shannon and total
    variation for categories, cardinality, unseen categories, missingness. Per
    pair: correlation error and contingency distance. Multivariate: a
    nearest-neighbour two-sample statistic. Privacy: exact matches and distance
    to the closest real record against the real set's own baseline. Read the
    dimension your use depends on; a single number would reward whichever one
    is cheapest to move.
    """
    from . import fidelity as fidelity_module
    from .corpus import CorpusError

    try:
        real_rows = fidelity_module.load_rows(reference, table=table)
        synthetic_rows = fidelity_module.load_rows(synthetic, table=table)
        kinds: dict[str, Any] = {name: "categorical" for name in (categorical or ())}
        kinds.update({name: "ignore" for name in (ignore or ())})
        report = fidelity_module.compute(
            real_rows, synthetic_rows, kinds=kinds, slices=tuple(slices or ()), seed=seed,
        )
    except (OSError, ValueError, CorpusError, json.JSONDecodeError) as exc:
        _refuse("fidelity_unreadable", f"[red]error:[/red] {escape(str(exc))}")
    if as_json:
        typer.echo(json.dumps(
            {"reference": str(reference), "synthetic": str(synthetic), **report.as_dict()},
            indent=2,
        ))
        return
    console.print(escape(str(report)))


@app.command()
def calibrate(
    source: Path = typer.Option(
        None, "--from", help="The sensitive table: CSV, JSONL or a JSON array. Read once, never copied.",
    ),
    schema: Path = typer.Option(
        None, "--schema",
        help="Which columns inform which physics parameters, with clip bounds, bins and quantiles. `--template` writes one.",
    ),
    epsilon: float = typer.Option(1.0, "--epsilon", help="Total privacy budget, split evenly across the calibrated columns."),
    delta: float = typer.Option(0.0, "--delta", help="Recorded on the receipt; the built-in Laplace mechanism spends none."),
    noise_seed: int = typer.Option(
        None, "--noise-seed",
        help="Seed the noise. FOR TESTS: a seeded release is a deterministic summary, not a private one, and the snapshot says so.",
    ),
    out: Path = typer.Option(None, "--out", "-o", help="Where to write the prior snapshot. Stdout when omitted."),
    template: bool = typer.Option(False, "--template", help="Print a calibration schema to start from, and stop."),
) -> None:
    """Learn physics ranges from data the corpus may never contain, under a privacy budget.

    Each calibrated column becomes a `Span` for one physics parameter — a low and
    a high read off a differentially private histogram — and the snapshot carries
    a receipt: mechanism, ε, sensitivity, clipping, bins, contribution bound, and
    digests of the source and the result. `worldloom build --priors` reads it.
    Nothing but ranges crosses: not a row, not a mean.
    """
    from . import calibrate as calibrate_module
    from .providers import digest_bytes

    if template:
        typer.echo(json.dumps(calibrate_module.TEMPLATE, indent=2))
        return
    if source is None or schema is None:
        err.print("[red]error:[/red] --from and --schema are both required (or --template)")
        raise typer.Exit(code=2)
    from . import fidelity as fidelity_module

    try:
        rows = fidelity_module.load_rows(source)
        payload = json.loads(schema.read_text(encoding="utf-8"))
        resolved = calibrate_module.CalibrationSchema.model_validate(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc
    findings = calibrate_module.lint(resolved)
    if findings:
        err.print(f"[red]error:[/red] {schema} has lint findings:")
        for finding in findings:
            err.print(f"  - {escape(finding)}")
        raise typer.Exit(code=2)
    try:
        snapshot = calibrate_module.calibrate(
            rows, resolved, epsilon=epsilon, delta=delta,
            estimator=calibrate_module.LaplaceHistogramEstimator(noise_seed=noise_seed),
            source_digest=digest_bytes(source.read_bytes()),
        )
    except ValueError as exc:
        err.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc
    for name, span in snapshot.spans.items():
        reading = snapshot.quality.get(name, {})
        flag = "  [yellow]noisy[/yellow]" if name in snapshot.noisy else ""
        console.print(
            f"  {name:<40} [{span['low']:g}, {span['high']:g}]"
            f"  from {reading.get('values_read', 0)} value(s){flag}"
        )
    if not snapshot.private:
        console.print(
            "[yellow]note:[/yellow] --noise-seed was given: this snapshot is a deterministic"
            " summary of its source, not a private release, and its receipt says so"
        )
    if snapshot.noisy:
        console.print(
            "[yellow]note:[/yellow] more noise than signal for"
            f" {', '.join(snapshot.noisy)} — raise ε, add rows, or widen the bins"
        )
    if out is None:
        typer.echo(json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True))
        return
    snapshot.write(out)
    console.print(f"wrote {out} — receipt {snapshot.receipt.key}")


@causal_app.command("check")
def causal_check(
    model: Path = typer.Argument(None, help="A causal model as JSON."),
    template: bool = typer.Option(False, "--template", help="Print a model to start from, and stop."),
    as_json: bool = typer.Option(False, "--json", help="Emit the findings as JSON."),
) -> None:
    """Lint a causal model: DAG, declared parents, weights, physics names, drives.

    The same posture as `worldloom pack check`: every divergence between what
    was authored and what the engine would do, named, with exit 1 when there
    are any. Nothing builds under a model that has findings.
    """
    from . import causal as causal_module

    if template:
        typer.echo(json.dumps(causal_module.TEMPLATE, indent=2))
        return
    if model is None:
        err.print("[red]error:[/red] give a model file, or --template")
        raise typer.Exit(code=2)
    try:
        resolved = causal_module.from_document(json.loads(model.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {model}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc
    findings = causal_module.lint(resolved)
    if as_json:
        typer.echo(json.dumps({"model": resolved.name, "ok": not findings, "findings": findings}, indent=2))
    elif findings:
        for finding in findings:
            console.print(f"[red]✗[/red] {escape(finding)}")
    else:
        console.print(
            f"[green]✓[/green] {resolved.name}: {len(resolved.nodes)} node(s),"
            f" {len(resolved.interventions)} intervention(s), {len(resolved.drives)} drive(s)"
        )
    if findings:
        raise typer.Exit(code=1)


@causal_app.command("trace")
def causal_trace(
    model: Path = typer.Argument(..., help="A causal model as JSON."),
    periods: int = typer.Option(6, "--periods", min=1, help="How many monthly periods to trace."),
    period: str = typer.Option("2026-01", "--period", "-p", help="The first period, YYYY-MM."),
    seed: int = typer.Option(8128, "--seed", "-s", help="The seed exogenous nodes draw under."),
    as_json: bool = typer.Option(False, "--json", help="Emit the trace as JSON."),
) -> None:
    """Evaluate a model over a run of periods, without a world, and show what it does.

    The authoring loop: change a weight, see the cascade. Every value printed is
    the value a build under this model at this seed would record — the same
    arithmetic, the same streams — so what this shows is what the corpus gets.
    """
    from . import causal as causal_module
    from .rng import Rng

    try:
        resolved = causal_module.from_document(json.loads(model.read_text(encoding="utf-8")))
        stamps = [_step_period(period, index, 1) for index in range(periods)]
        values = causal_module.evaluate(resolved, stamps, rng=Rng(seed).derive("causal"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        err.print(f"[red]error:[/red] {model}: {escape(str(exc))}")
        raise typer.Exit(code=2) from exc
    if as_json:
        typer.echo(json.dumps([entry.model_dump(mode="json") for entry in values], indent=2))
        return
    names = causal_module.order(resolved)
    table = Table(title=f"{resolved.name} over {periods} period(s), seed {seed}", box=None)
    table.add_column("period")
    for name in names:
        table.add_column(name, justify="right")
    table.add_column("interventions")
    table.add_column("budgets")
    for entry in values:
        table.add_row(
            entry.period,
            *(f"{entry.values[name]:g}" for name in names),
            ", ".join(resolved.interventions[i].reason for i in entry.interventions) or "—",
            ", ".join(f"{k} {v}" for k, v in sorted(entry.budgets.items())) or "—",
        )
    console.print(table)


def _knowledge_table(world: World) -> None:
    """Who came to know how much, and through which channels.

    Per person rather than per invocation, because a derived knowledge ledger
    has no invocations — and because the reading that matters for it is the one
    the execution ledger cannot give: two employees in the same company holding
    a different number of this month's facts.
    """
    channels: dict[str, dict[str, int]] = {}
    earliest: dict[str, str] = {}
    for record in world.observations:
        counts = channels.setdefault(record.observer_id, {})
        counts[record.source_type] = counts.get(record.source_type, 0) + 1
        stamp = record.learned_at.strftime("%Y-%m-%d %H:%M")
        if record.observer_id not in earliest or stamp < earliest[record.observer_id]:
            earliest[record.observer_id] = stamp

    table = Table(title="What each employee came to know", box=None)
    table.add_column("role")
    table.add_column("first heard")
    table.add_column("facts", justify="right")
    table.add_column("by channel", overflow="fold")
    for person_id in sorted(channels, key=lambda p: (-sum(channels[p].values()), p)):
        person = world.people.get(person_id)
        counts = channels[person_id]
        table.add_row(
            person.title if person is not None else person_id,
            earliest[person_id],
            str(sum(counts.values())),
            ", ".join(f"{name} {count}" for name, count in sorted(counts.items())),
        )
    console.print(table, "")

    if not world.messages:
        return
    table = Table(title="Who told whom", box=None)
    table.add_column("sent")
    table.add_column("kind")
    table.add_column("from")
    table.add_column("to", overflow="fold")
    table.add_column("facts", justify="right")
    table.add_column("about")
    for message in sorted(world.messages, key=lambda m: (m.sent_at, m.id)):
        sender = world.people.get(message.sender_id)
        recipients = [world.people.get(r) for r in message.recipient_ids]
        table.add_row(
            message.sent_at.strftime("%Y-%m-%d %H:%M"),
            message.kind,
            sender.title if sender is not None else message.sender_id,
            ", ".join(
                person.title if person is not None else "?" for person in recipients
            ),
            str(len(message.disclosed_fact_ids)),
            message.subject_ref or "",
        )
    console.print(table, "")


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
        # A corpus built with `--conversations` has a knowledge ledger and no
        # execution ledger — nobody took a decision, but the episode still
        # recorded who came to know what. Reporting "no actor episode" and
        # returning would hide a file that is present, which is the failure mode
        # this whole command exists to prevent.
        if observations and world.observations:
            _knowledge_table(world)
            return
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
        _refuse("unknown_parameter",
                f"[red]error:[/red] no parameter starts with {prefix!r}")

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
    except KeyError:
        _refuse(
            "unknown_facet",
            f"[red]error:[/red] no facet named {name!r}; known:"
            f" {', '.join(sorted(facets_module.FACETS))}",
            known=sorted(facets_module.FACETS),
        )

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
            _refuse("unknown_landscape",
                    f"[red]error:[/red] no landscape named {name!r};"
                    f" known: {', '.join(sorted(published))}",
                    known=sorted(published))
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
            _refuse("unknown_locale",
                    f"[red]error:[/red] no locale named {name!r};"
                    f" known: {', '.join(published)}",
                    known=list(published))
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
        _refuse("unknown_engine",
                f"[red]error:[/red] no engine named {engine!r}; registered: {', '.join(domains.names())}",
                registered=list(domains.names()))
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
        _refuse("exactly_one",
                "[red]error:[/red] pass exactly one of --world (a mosaic index) or --probe",
                flags=["--world", "--probe"])

    base = None
    if onto is not None:
        from . import packs as packs_module

        try:
            base = packs_module.load(onto)
        except Exception as exc:
            _refuse("pack_invalid", f"[red]error:[/red] {onto}: {escape(str(exc))}")

    try:
        if world is not None:
            from . import mosaic as mosaic_module

            variants = mosaic_module.field(count, seed=seed, engine=engine)
            found = [v for v in variants if v.index == world]
            if not found:
                _refuse(
                    "unknown_world",
                    f"[red]error:[/red] this mosaic has no world {world};"
                    f" its indices are {[v.index for v in variants]}",
                    indices=[v.index for v in variants],
                )
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
        _refuse("pack_export_failed", f"[red]error:[/red] {escape(str(exc))}")

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
        _refuse("unknown_engine",
                f"[red]error:[/red] no engine named {engine!r}; registered: {', '.join(domains.names())}",
                registered=list(domains.names()))
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
def workspace(
    corpus: Path = typer.Argument(..., help="A rendered corpus directory."),
    out: Path = typer.Option(..., "--out", "-o", help="Where to write the tree."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing tree."),
    noise: str = typer.Option(
        "none", "--noise",
        help=(
            "How untidy the drive is: none, lived_in or neglected. Adds copies, "
            "misfilings, personal versions and archive leftovers — every one a "
            "duplicate of real corpus content, never invented text, because a "
            "drive's junk is the same documents saved again in the wrong place "
            "under the wrong name. Each is labelled in permissions.jsonl, so a "
            "benchmark can tell 'found the wrong copy' from 'was wrong'."
        ),
    ),
) -> None:
    """Lay a rendered corpus out as a shared drive, with its permissions.

    A corpus exports as one flat `artifacts/` folder of numbered files, which is
    right for the harness and wrong for what the corpus is *for*: an enterprise
    assistant indexes the folder a document sits in, the title somebody typed,
    who owns it and who it is shared with. The corpus knows all of that and none
    of it reached the filesystem.

    Writes a folder tree, human filenames — including the subject, so four
    reviews in a month are four names rather than `(2)` through `(5)` — and
    `permissions.jsonl`, one row per file with its owner and every address
    permitted to open it. Superseded documents sit beside their replacements
    marked as such, which is what makes a shelf legible.

    Written to a separate root: nothing in the corpus moves.
    """
    from . import World
    from . import workspace as workspace_module

    try:
        world = World.load(corpus)
    except Exception as exc:
        _refuse("corpus_unloadable", f"[red]error:[/red] {escape(str(exc))}",
                corpus=str(corpus))
    try:
        written = workspace_module.write(world, out, overwrite=overwrite, noise=noise)
    except (FileExistsError, ValueError) as exc:
        _refuse("workspace_unwritable", f"[red]error:[/red] {escape(str(exc))}")

    reading = workspace_module.summarise(world, noise=noise)
    console.print(
        f"[green]✓[/green] {reading['files']} file(s) in {reading['folders']} folder(s),"
        f" {reading['deepest']} deep, under [bold]{written}[/bold]\n"
        f"[dim]{reading['restricted']} restricted ·"
        f" {reading['distinct_owners']} distinct owner(s) ·"
        f" {reading['superseded']} superseded ·"
        f" {reading['junk']} labelled junk[/dim]"
    )


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
def doctor(
    as_json: bool = typer.Option(False, "--json", help="Emit the check list as JSON."),
) -> None:
    """Say whether this installation can do what the docs promise.

    Each check reports ✓ or ✗ with the exact fix when it fails: the Python
    floor (read from the package's own metadata), every registered render
    format's optional dependency, the bundled example corpus validating, and
    the generated command reference being current. Exit 0 when everything
    passes, 1 otherwise. Reads only this process and this disk — no network,
    ever.
    """
    import sys as sys_module
    from importlib import metadata as importlib_metadata

    from . import World
    from . import docs as docs_generator
    from . import render as render_module
    from .corpus import CorpusError
    from .render import RenderError

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, fix: str | None = None) -> None:
        # `fix` is nulled on a passing check rather than stored, so the JSON
        # never shows a remedy beside a ✓ — a fix string is a claim that
        # something needs fixing.
        checks.append({"check": name, "ok": ok, "detail": detail,
                       "fix": None if ok else fix})

    # 1. The Python floor, read from the installed package's own metadata
    # rather than restated here: `requires-python` lives in pyproject.toml,
    # and a hardcoded copy would hold doctor at an old floor the day the real
    # one moves.
    running = ".".join(str(part) for part in sys_module.version_info[:3])
    try:
        requires = importlib_metadata.metadata("worldloom").get("Requires-Python") or ""
    except importlib_metadata.PackageNotFoundError:
        requires = ""
    if requires:
        floor_clause = next(
            (clause.strip() for clause in requires.split(",")
             if clause.strip().startswith(">=")),
            None,
        )
        floor = (
            tuple(int(part) for part in floor_clause[2:].split("."))
            if floor_clause else ()
        )
        check(
            "python",
            not floor or sys_module.version_info[: len(floor)] >= floor,
            f"Python {running} (needs {requires})",
            fix=f"run worldloom under Python {requires}",
        )
    else:
        check(
            "python", False,
            f"Python {running} — worldloom's package metadata is not installed",
            fix="install the package (`pip install worldloom`, or `pip install -e .`"
                " from a checkout) so its declared Python floor exists to check",
        )

    # 2. Every registered render format's optional dependency, probed through
    # the same `_require_*` function the renderer itself calls first at render
    # time — discovered off the registered renderer's own module rather than a
    # table here, so doctor can neither disagree with what `render` would
    # actually do nor drift when a format arrives: a new format's probe rides
    # in with its registration, and a format with no probe needs nothing
    # beyond the library itself.
    for name in render_module.available():
        module = sys_module.modules.get(render_module.renderer(name).__module__)
        probes = [
            probe for attribute, probe in sorted(vars(module).items())
            if attribute.startswith("_require_") and callable(probe)
        ] if module is not None else []
        if not probes:
            check(f"render:{name}", True, "no optional dependency")
            continue
        try:
            for probe in probes:
                probe()
        except RenderError as exc:
            # The probe's message already names the missing package and the
            # exact pip extra that installs it; repeating that here would be a
            # second copy to drift.
            check(f"render:{name}", False, "dependency missing", fix=str(exc))
        else:
            check(f"render:{name}", True, "dependency importable")

    # 3. The pinned example corpus validates. This is the engine end to end —
    # load, pack rules, every coherence check — against a corpus the package
    # ships, so a failure here is an installation defect, not a user corpus's.
    try:
        report = World.load("retail-close").validate()
    except CorpusError as exc:
        check(
            "corpus:retail-close", False, f"cannot load: {exc}",
            fix="reinstall worldloom — the bundled example ships inside the package"
                " (`pip install --force-reinstall worldloom`)",
        )
    else:
        check(
            "corpus:retail-close", report.ok,
            f"{report.checks_run} checks, {len(report.violations)} violation(s)",
            fix="reinstall worldloom — the bundled example must validate, so a"
                " violation here means the install (or an edit to it) is broken",
        )

    # 4. The generated command reference, compared exactly as `docs --check`
    # compares it — imported and called, never shelled out. One stated
    # divergence from that command: `REFERENCE_PATH` is relative to the
    # working directory, so outside a repository checkout there is no
    # checked-in file at all. `docs --check` fails there, to stop CI running
    # from the wrong directory; doctor is judging an *install*, and an install
    # without a checkout has no reference to have let go stale.
    reference_target = Path(docs_generator.REFERENCE_PATH)
    if not reference_target.exists():
        check(
            "docs:reference", True,
            "no checked-in reference here (not a repository checkout) —"
            " nothing to be stale",
        )
    # encoding pinned because the reference contains "→", which cp1252 cannot
    # represent: read under the Windows locale codec, a current reference
    # mojibakes and doctor reports it stale — a false installation defect.
    elif reference_target.read_text(encoding="utf-8") == docs_generator.reference():
        check("docs:reference", True, f"{reference_target} is current")
    else:
        check(
            "docs:reference", False, f"{reference_target} is stale",
            fix="run `worldloom docs` from the repository root and commit the result",
        )

    healthy = all(entry["ok"] for entry in checks)
    if as_json:
        typer.echo(json.dumps({"ok": healthy, "checks": checks}, indent=2))
    else:
        for entry in checks:
            mark = "[green]✓[/green]" if entry["ok"] else "[red]✗[/red]"
            console.print(f"{mark} {escape(entry['check'])} — {escape(entry['detail'])}")
            if not entry["ok"] and entry["fix"]:
                console.print(f"  [yellow]fix:[/yellow] {escape(entry['fix'])}")
    if not healthy:
        failed = [entry["check"] for entry in checks if not entry["ok"]]
        _refuse(
            "doctor_unhealthy",
            f"[red]error:[/red] {len(failed)} of {len(checks)} check(s) failed:"
            f" {', '.join(failed)} — each names its fix above",
            exit_code=1,
            failed=failed,
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
        # Absent and out-of-date are different findings, and the remedy for one
        # of them is not `worldloom docs`. `REFERENCE_PATH` is relative to the
        # working directory, so running this from anywhere but a checkout found
        # no file, compared against `""`, and reported a file that does not
        # exist as *stale* — sending the reader to a command that would write a
        # reference into whatever directory they happened to be standing in.
        if not target.exists():
            console.print(
                f"[red]✗[/red] {target} does not exist. This path is relative to"
                " the working directory; `--check` compares a checked-in"
                " reference against this CLI, so run it from the repository"
                " root."
            )
            raise typer.Exit(code=1)
        # encoding pinned on both sides of this pair: the reference holds
        # "→"/"—", so a cp1252 read on Windows mojibakes the checked-in file
        # and --check reports a current reference as stale.
        existing = target.read_text(encoding="utf-8")
        if existing == current:
            console.print(f"[green]✓[/green] {target} is current")
            return
        # Deliberately not written in --check mode: the point is to fail the
        # build, and a checker that fixes the thing it is checking would make CI
        # pass while the commit stays wrong.
        console.print(f"[red]✗[/red] {target} is stale — run `worldloom docs`")
        raise typer.Exit(1)

    target.parent.mkdir(parents=True, exist_ok=True)
    # utf-8 because the default Windows codec cannot encode the reference's
    # arrows; newline="\n" because a CRLF write here would immediately fail
    # `docs --check` on LF platforms — the same file, two byte sequences.
    target.write_text(current, encoding="utf-8", newline="\n")
    console.print(f"[green]✓[/green] wrote {target}")



# ---------------------------------------------------------------------------
# present — the presentation layer's own surface
# ---------------------------------------------------------------------------


@present_app.command("describe")
def present_describe() -> None:
    """Every registered profile and every knob, rendering nothing.

    The same argument `mosaic --describe` makes: deciding whether a profile is
    the one you want should not require rendering a corpus to find out.
    """
    from .presentation import KNOBS, PROFILES
    from .presentation import describe as describe_profile

    table = Table(title="Presentation profiles", box=None)
    table.add_column("profile")
    for knob in KNOBS:
        table.add_column(knob)
    for name, profile in sorted(PROFILES.items()):
        knobs = describe_profile(profile)
        table.add_row(name, *(knobs[knob] for knob in KNOBS))
    console.print(table)

    console.print()
    for knob, values in KNOBS.items():
        console.print(f"  [bold]{knob}[/bold]  {', '.join(values)}")
    console.print(
        "\n  A profile decides how a value is [italic]shown[/italic] and never"
        " what it is. Nothing a profile omits is lost: every section, every"
        " fact id and the author's voice stay in artifact-ir.jsonl whatever you"
        " choose."
    )


@present_app.command("brief")
def present_brief(
    corpus: str = typer.Argument(None, help="Corpus whose doctypes an override may name."),
    out: Path = typer.Option(None, "--out", "-o", help="Write the brief here as JSON."),
) -> None:
    """The context needed to author a profile, as JSON.

    `cascade.Brief`'s contract, over presentation: the rules the lint enforces
    are stated before anything is proposed rather than discovered one refusal
    at a time. Pass a corpus and the brief carries the doctypes it actually
    mints, so an override cannot name one that never appears.
    """
    import json as _json

    from .presentation import brief as presentation_brief

    doctypes: tuple[str, ...] = ()
    if corpus:
        world = _load(corpus)
        doctypes = tuple(sorted({
            intent.artifact_type for intent in world.artifact_intents
        }))
    payload = presentation_brief(doctypes)
    text = _json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"[green]✓[/green] brief written to [bold]{out}[/bold]")
    else:
        console.print_json(text)


@present_app.command("lint")
def present_lint(
    spec: str = typer.Argument(..., help="Path to a profile document, or the JSON itself."),
    corpus: str = typer.Option(None, "--corpus", help="Check overrides against this corpus's doctypes."),
    register: bool = typer.Option(
        False, "--register",
        help="Register the profile on acceptance, so a later --profile can name it.",
    ),
) -> None:
    """Check a profile, and say every reason it cannot be accepted.

    Every reason and not the first: `cascade`'s protocol, because a reviser
    fixing one knob per round trip pays a turn per rule it could not see.
    """
    from .cascade import load as load_seed
    from .presentation import PresentationSeed, resolve, review
    from .presentation import register as register_profile

    doctypes: tuple[str, ...] = ()
    if corpus:
        world = _load(corpus)
        doctypes = tuple(sorted({i.artifact_type for i in world.artifact_intents}))

    try:
        seed = load_seed(spec, PresentationSeed)
    except Exception as exc:
        _refuse("unreadable_document", f"[red]refused:[/red] {escape(str(exc))}",
                path=str(spec))

    findings = review(seed, doctypes=doctypes)
    if findings:
        err.print(f"[red]refused:[/red] {escape(seed.name)} — {len(findings)} finding(s)")
        for finding in findings:
            err.print(f"  [red]•[/red] {escape(finding)}")
        raise typer.Exit(code=1)

    profile = resolve(seed)
    if register:
        register_profile(seed.name, profile)
    console.print(f"[green]✓[/green] {escape(seed.name)} accepted")
    for knob, value in sorted(profile.__dict__.items()):
        if knob not in ("name", "overrides"):
            console.print(f"    {knob:12} {value}")


@app.command()
def spaces(
    strength: int = typer.Option(
        2, "--strength", "-t", min=1,
        help="Interaction strength. t=2 covers every pair of axis values, t=3"
             " every triple. The row count grows with the product of the t"
             " widest axes, not with the whole space.",
    ),
    cover_plan: bool = typer.Option(
        False, "--cover",
        help="Emit the planned fleet — one JSON object per line, one per"
             " configuration — instead of describing the space. Builds nothing.",
    ),
    against: Path = typer.Option(
        None, "--holes",
        help="A fleet, as the JSON-lines this command's --cover emits. Reports"
             " what that fleet never covered rather than what a plan would.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """The build-configuration space: what a fleet could vary, and what one did.

    `mosaic` and `tools/sweep.py` both choose configurations, and neither can
    say what it failed to reach — a sampler has no denominator. This does:
    every axis `worldloom build` actually accepts, the exhaustive product, and
    a covering array that reaches every t-way combination in a number of rows
    that grows with the widest axes rather than with the space.

    Read `spaces.py` for why a covering array is a different guarantee from
    `dispersion.halton`'s spread: Halton fills a continuous cube evenly and can
    still never once pair a bank with three periods.
    """
    import json as _json

    from . import spaces as spaces_module

    space = spaces_module.build_space()

    if against is not None:
        rows = [
            _json.loads(line)
            for line in Path(against).read_text().splitlines()
            if line.strip()
        ]
        got = spaces_module.coverage(space, rows, strength=strength)
        missing = spaces_module.holes(space, rows, strength=strength)
        never = spaces_module.unvaried(space, rows)
        if as_json:
            console.print_json(data={
                "configurations": len(rows),
                "strength": strength,
                "coverage": got,
                "combinations": space.size_at(strength),
                "holes": [list(map(list, hole)) for hole in missing],
                "unvaried_axes": list(never),
            })
            return
        console.print(
            f"{len(rows)} configuration(s) cover [bold]{got:.1%}[/bold] of"
            f" {space.size_at(strength)} {strength}-way combinations"
        )
        if never:
            # Printed before the holes, because it is their cause. A fleet that
            # never varied five axes has hundreds of holes with one explanation,
            # and listing them without this reads as a hundred separate failures.
            console.print(
                f"[yellow]![/yellow] never varied at all: {', '.join(never)}"
            )
        for hole in missing[:20]:
            console.print("  " + ", ".join(f"{name}={value}" for name, value in hole))
        if len(missing) > 20:
            console.print(f"  [dim]+{len(missing) - 20} more[/dim]")
        return

    if cover_plan:
        for row in spaces_module.cover(space, strength=strength):
            # One object per line rather than one array, so a fleet runner can
            # stream it and `--holes` can read back exactly what it wrote.
            print(_json.dumps(row, sort_keys=True))
        return

    rows = spaces_module.cover(space, strength=strength)
    if as_json:
        console.print_json(data={
            "axes": {axis.name: list(axis.values) for axis in space.axes},
            "exhaustive": space.exhaustive,
            "strength": strength,
            "combinations": space.size_at(strength),
            "rows": len(rows),
        })
        return
    console.print(
        f"[bold]{len(space.axes)}[/bold] axes, [bold]{space.exhaustive:,}[/bold]"
        f" configurations exhaustive\n"
    )
    for axis in space.axes:
        console.print(f"  {axis.name:14} {len(axis.values):>3}  {', '.join(axis.values)}")
    console.print(
        f"\nt={strength}: [bold]{len(rows)}[/bold] rows cover all"
        f" {space.size_at(strength):,} combinations"
        f" — {space.exhaustive // max(1, len(rows)):,}x smaller than exhaustive"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
