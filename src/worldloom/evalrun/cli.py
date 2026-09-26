"""`worldloom evalrun`: compile cases, run an agent, grade a planner, summarize, compare, import Eval Studio.

Every command delegates to a library operation and adds argument handling and
refusals. The corpus argument is always a directory written by
`worldloom enterprise-evals build`; the run argument is always a directory
written by `evalrun run` (or `import-studio`), so a run can be summarized and
compared long after the process that produced it is gone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(
    no_args_is_help=True,
    help="Execute an agent against a compiled case set and grade plan, trajectory and outcomes.",
)

AGENTS = ("reference", "lazy", "scripted")


class _CaseSet:
    """A case set read from disk, shaped like the corpus the commands expect: its records under `connector_data.records`."""

    class _Data:
        def __init__(self, records: tuple[Any, ...]) -> None:
            self.records = records

    def __init__(self, records: tuple[Any, ...]) -> None:
        self.connector_data = self._Data(records)


def _corpus_cases(corpus: Path, limit: int | None) -> tuple[Any, tuple[Any, ...]]:
    """The cases of an enterprise corpus, or of a case set (`industry export` writes one)."""
    from ..cli import _refuse
    from ..enterprise_io import load_exported_corpus
    from .contract import cases_from_corpus, is_case_set, read_case_set

    if is_case_set(corpus):
        try:
            cases, records = read_case_set(corpus)
        except (OSError, ValueError) as error:
            _refuse("case_set_unreadable", f"{corpus}: {error}")
        return _CaseSet(records), cases[:limit] if limit else cases
    try:
        loaded = load_exported_corpus(corpus)
    except (OSError, ValueError) as error:
        _refuse("corpus_unreadable", f"{corpus}: {error}",
                fix="point at a directory written by `worldloom enterprise-evals build` or `worldloom industry programme`")
    try:
        cases = cases_from_corpus(loaded)
    except ValueError as error:
        _refuse("cases_uncompilable", str(error))
    return loaded, cases[:limit] if limit else cases


@app.command("cases")
def cases_command(
    corpus: Path = typer.Argument(..., help="Directory written by `worldloom enterprise-evals build`."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write cases.jsonl here."),
    limit: int | None = typer.Option(None, "--limit", min=1),
    json_output: bool = typer.Option(False, "--json", help="Emit the axis coverage as JSON."),
) -> None:
    """Compile the corpus into three-axis cases and report what the set can grade.

    The coverage is counts per axis: how many cases carry a write, a create,
    an update, a delete, a designed failure, an artifact, an answer. A zero
    is a gap in the set, named before anything runs against it.
    """
    from .contract import axis_coverage

    _, cases = _corpus_cases(corpus, limit)
    coverage = axis_coverage(cases)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as handle:
            for case in cases:
                handle.write(json.dumps(case.model_dump(mode="json"), sort_keys=True, default=str) + "\n")
    payload = coverage.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(f"{coverage.cases} case(s): {coverage.reads} read, {coverage.writes} write"
               f" ({coverage.creates} create, {coverage.updates} update, {coverage.deletes} delete),"
               f" {coverage.verifies} verify, {coverage.designed_failures} designed failure(s),"
               f" {coverage.unstructured} with an artifact contract, {coverage.answers} with an answer contract")
    typer.echo(f"shapes: {coverage.shapes}")
    typer.echo(f"connectors: {coverage.connectors}")
    for axis in ("updates", "deletes", "answers"):
        if payload[axis] == 0:
            typer.echo(f"gap: no case grades {axis}", err=True)
    if out is not None:
        typer.echo(f"{len(cases)} case(s) written to {out}")


def _harness_exec(harness: str | None, exec_command: str | None, *, timeout: float) -> str | None:
    """The bundled adapter as an `--exec` command, or whatever `--exec` gave.

    `--harness codex` is shorthand for the adapter this package already ships
    for the Studio, so grading a real coding harness needs no adapter script.
    Naming both leaves it ambiguous which child runs, so that is refused.
    """
    if harness is None:
        return exec_command
    from ..cli import _refuse
    from ..studio.harness import NAMES, adapter_command

    if exec_command is not None:
        _refuse("cannot_combine", "--harness and --exec both name the child process; give one")
    if harness not in NAMES:
        _refuse("unknown_harness",
                f"{harness!r}; use {' or '.join(NAMES)}, or --exec for a custom adapter")
    # The child is given less than the parent allows, so the parent's timeout
    # is what reports the overrun rather than a race between the two.
    return adapter_command(harness, timeout=max(1.0, timeout - 5))


def _read_run(path: Path) -> Any:
    """``read_run`` for a command: an unfinished run is refused as ``run_partial`` with its fix.

    Any other failure propagates, so each command keeps refusing it as
    ``run_unreadable`` in its own words.
    """
    from ..cli import _refuse
    from .results import PartialRun, read_run

    try:
        return read_run(path)
    except PartialRun as error:
        _refuse("run_partial", str(error),
                fix=f"finish it with `worldloom evalrun run <corpus> -o {path} --resume` and the flags it was started with")


_AGENT_PACK_HELP = ("An `agent` pack the --exec/--harness child runs under: agent:<name>[@<digest>] or a pack file. "
                    "Its standing instruction, rule overlays and tool advice reach the child, and run.json records "
                    "its reference and digest.")


def _agent_pack(ref: str | None, exec_command: str | None) -> Any:
    """The resolved, linted `agent` pack for `--agent-pack`, or None.

    Refused without `--exec`/`--harness`: the reference, lazy and scripted
    agents never read a policy, and a run recording one it ignored would
    claim a measurement it did not make.
    """
    from ..cli import _refuse

    if ref is None:
        return None
    if exec_command is None:
        _refuse("cannot_combine", "--agent-pack applies to an --exec or --harness agent; the reference, lazy and "
                "scripted agents ignore a policy")
    from .policy import load

    try:
        return load(ref)
    except (KeyError, ValueError) as error:
        _refuse("pack_rejected", str(error).strip("'\""))


def _agent(spec: str, cases: tuple[Any, ...]) -> Any:
    from ..cli import _refuse
    from .agents import ReferenceAgent, ScriptedAgent
    from .harness import ResponsesAgent, load_responses

    if spec == "reference":
        return ReferenceAgent(cases)
    if spec == "lazy":
        return ScriptedAgent([], name="lazy", answer="")
    if spec.startswith("scripted:"):
        path = Path(spec.removeprefix("scripted:"))
        try:
            scripts = load_responses(path)
        except OSError as error:
            _refuse("script_unreadable", f"{path}: {error}")
        except ValueError as error:
            _refuse("script_invalid", str(error))
        return ResponsesAgent(scripts, name=f"scripted:{path.name}")
    _refuse("unknown_agent", f"{spec!r} is not one of {AGENTS} (scripted takes scripted:<responses.json>)")


def _planner(spec: str, cases: tuple[Any, ...]) -> Any:
    from ..cli import _refuse
    from .plans import ReferencePlanner, ScriptedPlanner, load_plans

    if spec == "reference":
        return ReferencePlanner(cases)
    if spec.startswith("scripted:"):
        path = Path(spec.removeprefix("scripted:"))
        try:
            plans = load_plans(path)
        except OSError as error:
            _refuse("script_unreadable", f"{path}: {error}")
        except ValueError as error:
            _refuse("script_invalid", str(error))
        return ScriptedPlanner(plans, name=f"plan:scripted:{path.name}")
    _refuse("unknown_agent", f"{spec!r} is not reference or scripted:<plans.json>")


@app.command("requests")
def requests_command(
    corpus: Path = typer.Argument(..., help="Directory written by `worldloom enterprise-evals build`."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write requests.json here instead of stdout."),
    limit: int | None = typer.Option(None, "--limit", min=1),
    principal: str = typer.Option("agent", "--principal"),
    purpose: str = typer.Option("run", "--for", help="run: answered with trajectories for `evalrun run`; plan: answered with DAGs for `evalrun plan`."),
) -> None:
    """Write every case as a request a harness can answer offline: query, persona, tools.

    The document carries what the agent may know and nothing else: no
    expected DAG, no fixture ids, no assertions. A harness answers with a
    responses document (`worldloom.evalrun-responses/v1`), replayed by
    `evalrun run --agent scripted:responses.json`. Replay cannot observe a
    call's result; an agent that needs one runs through `evalrun run --exec`.
    `--for plan` asks for a stated DAG per case instead (`worldloom.evalrun-plans/v1`),
    replayed by `evalrun plan --agent scripted:plans.json`.
    """
    from ..cli import _refuse
    from ..corpus import write_json
    from .harness import requests_document
    from .plans import plan_requests_document
    from .runner import service_for

    if purpose not in {"run", "plan"}:
        _refuse("unknown_agent", f"--for must be run or plan, not {purpose!r}")
    loaded, cases = _corpus_cases(corpus, limit)
    service = service_for(cases, loaded.connector_data.records)
    document = (plan_requests_document(service, cases, principal=principal) if purpose == "plan"
                else requests_document(service, cases, principal=principal))
    if out is None:
        typer.echo(json.dumps(document, indent=2, sort_keys=True))
        return
    write_json(out, document)
    typer.echo(f"{len(document['cases'])} request(s) written to {out}")


@app.command("run")
def run_command(
    corpus: Path = typer.Argument(..., help="Directory written by `worldloom enterprise-evals build`, or a case set written by `worldloom industry programme` (evalrun-cases.jsonl beside records.jsonl)."),
    out: Path = typer.Option(..., "--out", "-o", help="Run directory to write (run.json, results.jsonl, summary.json)."),
    agent: str = typer.Option("reference", "--agent", help="reference | lazy | scripted:<responses.json>"),
    exec_command: str | None = typer.Option(
        None, "--exec",
        help=("The agent as an executable, one subprocess per turn: reads a "
              "`worldloom.evalrun-turn/v2` JSON document on stdin, prints {\"call\": ...} "
              "or {\"answer\": ...} on stdout. Run without a shell (shlex argv) unless --shell is given."),
    ),
    harness: str | None = typer.Option(
        None, "--harness",
        help="An installed coding harness as the agent, using its own login: codex or claude. Shorthand for the bundled --exec adapter.",
    ),
    timeout: float = typer.Option(600.0, "--timeout", help="Seconds the --exec child may run per turn before it is killed."),
    shell: bool = typer.Option(False, "--shell", help="Run the --exec command through the shell (the opt-in for pipelines)."),
    max_turns: int | None = typer.Option(None, "--max-turns", min=1, help="Turns the --exec child may take per case (default: the agent pack's max_turns, else policy `evalrun.max_turns`, 64)."),
    agent_pack: str | None = typer.Option(None, "--agent-pack", help=_AGENT_PACK_HELP),
    limit: int | None = typer.Option(None, "--limit", min=1),
    principal: str = typer.Option("agent", "--principal", help="The principal every run is begun under."),
    rater: str | None = typer.Option(None, "--rater", help="grounded (no model, where the shape allows) or exec:<command> (a judge over the --exec seam)."),
    rater_timeout: float = typer.Option(600.0, "--rater-timeout", help="Seconds an exec: rater child may run per answer."),
    timed: bool = typer.Option(False, "--timed", help="Record wall-clock latency per case. Off by default so a run is byte-reproducible."),
    progress: bool = typer.Option(False, "--progress", help="Print one line per case to stderr as it is graded: id, status, score, calls and seconds when --timed."),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
    concurrency: int | None = typer.Option(None, "--concurrency", min=1, help="Cases in flight at once, each on its own fork (default: policy `evalrun.concurrency`, 1). The ledger is in case order whatever order they finish in."),
    resume: bool = typer.Option(False, "--resume", help="Keep the ledger already in --out when its run.json names this agent, principal and case set (and shard); grade only the cases it lacks."),
    shard: str | None = typer.Option(None, "--shard", help="Run only shard i of n (1-based, e.g. 2/4), a partition by a stable hash of case id; `evalrun merge` joins the shard directories."),
) -> None:
    """Run one agent over the case set, one isolated connector state per case, and grade.

    Every graded case is appended to `results.jsonl` as it lands, so a run
    killed by its wall clock leaves every case that finished; a run that
    completes rewrites the same lines and is byte-identical either way.
    `--resume` picks such a run up where it stopped. `--concurrency N` runs N
    cases at once; `--shard i/n` runs one partition of the set, so n processes
    or machines can share it and `evalrun merge` can join what they wrote.

    The reference agent walks each expected DAG through the same tool surface
    an external agent gets; its run is the executable ceiling for the set.
    `--exec` makes any executable the agent, one subprocess per turn, with the
    transcript so far as its only memory. An agent that raises, exits
    non-zero or breaks the turn contract produces an error row, excluded from
    every mean and carrying the child's stderr tail.
    """
    from ..cli import _refuse
    from .rater import GroundedRater
    from .results import (
        append_result,
        begin_ledger,
        resume_ledger,
        shard_document,
        shard_of,
        write_run,
        write_shard,
    )
    from .runner import (
        ConcurrencyRefused,
        case_set_digest,
        default_concurrency,
        run_cases,
        service_for,
    )

    # Before the corpus: a typo in --harness should not wait on a build.
    exec_command = _harness_exec(harness, exec_command, timeout=timeout)
    policy = _agent_pack(agent_pack, exec_command)
    shard_at: tuple[int, int] | None = None
    if shard is not None:
        index_text, _, count_text = shard.partition("/")
        if not (index_text.isdigit() and count_text.isdigit() and 1 <= int(index_text) <= int(count_text)):
            _refuse("evalrun_shard_invalid", f"--shard {shard!r}: give i/n with 1 <= i <= n, e.g. 2/4")
        shard_at = (int(index_text), int(count_text))
    loaded, cases = _corpus_cases(corpus, limit)
    if not cases:
        _refuse("no_cases", f"{corpus} compiled to no cases")
    workers = concurrency if concurrency is not None else default_concurrency()
    if exec_command is not None:
        if agent != "reference":
            _refuse("cannot_combine", "--exec and --agent both name the agent under test; give one")
        from .harness import ExecAgent

        under_test: Any = ExecAgent(exec_command, timeout=timeout, shell=shell, max_turns=max_turns, policy=policy)
    else:
        under_test = _agent(agent, cases)
    grader: Any = None
    if rater == "grounded":
        grader = GroundedRater()
    elif rater is not None and rater.startswith("exec:"):
        from .rater import exec_rater

        grader = exec_rater(rater.removeprefix("exec:"), timeout=rater_timeout, shell=shell)
    elif rater is not None:
        _refuse("unknown_rater", f"{rater!r}; use grounded or exec:<command>")
    clock = None
    if timed:
        import time

        clock = time.perf_counter
    try:
        # Over the whole set even for one shard: the service a case runs in
        # is then the one a single process would have given it.
        service = service_for(cases, loaded.connector_data.records, concurrency=workers)
    except Exception as error:  # ServingError and its causes are all refusals here
        _refuse("service_unbuildable", str(error))
    selected = list(cases)
    shard_doc = None
    if shard_at is not None:
        selected = [case for case in cases if shard_of(case.id, shard_at[1]) == shard_at[0] - 1]
        shard_doc = shard_document(shard_at[0], shard_at[1], cases)
    # The identity this run will write (agent, principal, grader, agent pack),
    # read off an empty run so it is whatever `run_cases` itself records.
    identity = run_cases(service, (), under_test, principal=principal, clock=clock, rater=grader)
    identity = identity.model_copy(update={"case_set": case_set_digest(selected)})
    prior: list[Any] = []
    if resume:
        try:
            prior, note = resume_ledger(out, identity, shard=shard_doc)
        except ValueError as error:
            _refuse("resume_mismatch", str(error), fix="point --out at a fresh directory, or run without --resume to start over")
        if note is not None:
            typer.echo(note, err=True)
    else:
        # A fresh ledger: the checkpoint appends, and a stale file from an earlier
        # run into the same directory would otherwise sit above this run's lines.
        (out / "results.jsonl").unlink(missing_ok=True)
        # Likewise a stale shard.json, which would make an unsharded run
        # look like a shard to `evalrun merge`.
        (out / "shard.json").unlink(missing_ok=True)
    begin_ledger(out, identity, len(selected))
    if shard_doc is not None:
        write_shard(out, shard_doc)
    done_ids = {result.case_id for result in prior}
    pending = [case for case in selected if case.id not in done_ids]
    total = len(selected)

    def _checkpoint(result: Any) -> None:
        append_result(out, result)
        if not progress:
            return
        done = sum(1 for _ in (out / "results.jsonl").open(encoding="utf-8"))
        score = f"score {result.score.score}" if result.score is not None else f"error {result.error}"
        seconds = f" {result.latency.ttlt}s" if result.latency is not None and result.latency.ttlt is not None else ""
        typer.echo(f"[{done}/{total}] {result.case_id[:8]} {result.status} {score} {result.calls} call(s){seconds}", err=True)

    try:
        report = run_cases(service, pending, under_test, principal=principal, clock=clock, rater=grader,
                           on_result=_checkpoint, concurrency=workers)
    except ConcurrencyRefused as error:
        _refuse("concurrency_refused", str(error))
    if prior or shard_doc is not None:
        # Resumed or sharded: the prior results and this process's, in the
        # set's order, under the identity the whole run carries.
        graded = {result.case_id: result for result in (*prior, *report.results)}
        report = report.model_copy(update={"case_set": identity.case_set,
                                           "results": tuple(graded[case.id] for case in selected)})
    summary = write_run(out, report)
    _print_summary(summary, json_output)


@app.command("merge")
def merge_command(
    out: Path = typer.Argument(..., help="Run directory to write the merged run into."),
    shards: list[Path] = typer.Argument(..., help="Shard directories written by `evalrun run --shard i/n`, one per shard."),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Join the shard directories of one sharded run into one run, in case order.

    Refuses shards that differ in agent, principal, grader, agent pack, case
    set or shard count, a shard given twice, a case two shards graded, an
    unfinished shard and a missing one. The merged directory is
    byte-identical to what one process running the whole set would write.
    """
    from ..cli import _refuse
    from .results import merge_shards, write_run

    try:
        report = merge_shards(shards)
    except (OSError, ValueError, KeyError) as error:
        _refuse("shards_unmergeable", str(error))
    summary = write_run(out, report)
    _print_summary(summary, json_output)


def _print_summary(summary: Any, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(summary.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True))
        return
    def axis(value: float | None) -> str:
        return "unobserved" if value is None else str(value)

    typer.echo(f"{summary.agent}: {summary.passed}/{summary.graded} passed ({summary.pass_rate}),"
               f" {summary.errors} error(s) excluded; plan {axis(summary.means.plan)},"
               f" trajectory {axis(summary.means.trajectory)}, outcomes {axis(summary.means.outcomes)}")
    typer.echo(f"trajectory: exact {axis(summary.exact_match_rate)}, in-order {axis(summary.in_order_match_rate)},"
               f" any-order {axis(summary.any_order_match_rate)}; mean calls {axis(summary.mean_calls)}")
    typer.echo(f"outcomes: {summary.structured_met}/{summary.structured_expected} structured expectations met,"
               f" {summary.collateral_cases} case(s) with collateral writes")
    if summary.error_codes:
        typer.echo(f"connector errors: {summary.error_codes}")
    if summary.safety_findings:
        typer.echo(f"safety findings: {summary.safety_findings}")
    for part in summary.by_shape:
        typer.echo(f"  shape {part.key}: {part.passed}/{part.graded} passed, overall {part.means.overall}")
    if summary.mean_ttlt is not None:
        typer.echo(f"latency: mean ttlt {summary.mean_ttlt}s over {summary.timed} timed case(s)")


@app.command("plan")
def plan_command(
    corpus: Path = typer.Argument(..., help="Directory written by `worldloom enterprise-evals build`, or a case set written by `worldloom industry programme` (evalrun-cases.jsonl beside records.jsonl)."),
    out: Path = typer.Option(..., "--out", "-o", help="Run directory to write (run.json, results.jsonl, summary.json)."),
    agent: str = typer.Option("reference", "--agent", help="reference | scripted:<plans.json>"),
    exec_command: str | None = typer.Option(
        None, "--exec",
        help=("The planner as an executable, one subprocess per case: reads a "
              "`worldloom.evalrun-plan/v1` JSON document on stdin (query, tools), prints "
              "{\"plan\": {\"nodes\": [...]}} on stdout. Nothing is executed."),
    ),
    harness: str | None = typer.Option(
        None, "--harness",
        help="An installed coding harness as the planner, using its own login: codex or claude. Shorthand for the bundled --exec adapter.",
    ),
    timeout: float = typer.Option(600.0, "--timeout", help="Seconds the --exec child may run per case."),
    shell: bool = typer.Option(False, "--shell", help="Run the --exec command through the shell."),
    agent_pack: str | None = typer.Option(None, "--agent-pack", help=_AGENT_PACK_HELP),
    limit: int | None = typer.Option(None, "--limit", min=1),
    principal: str = typer.Option("agent", "--principal", help="The principal the tool catalog is advertised to."),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Grade the plan axis alone: the planner states each case's DAG and nothing runs.

    Querying measured apart from execution. The planner receives what an
    agent receives (the request and the tool catalog) and returns only a
    DAG of tool calls; it is graded against the expected DAG by tool name
    and dependency reachability with `grade_plan`'s formula, so the run
    compares with an executed run on the plan axis. Trajectory and outcomes
    are reported as unobserved, never as zeros.
    """
    from ..cli import _refuse
    from .plans import plan_cases
    from .results import write_run
    from .runner import service_for

    exec_command = _harness_exec(harness, exec_command, timeout=timeout)
    policy = _agent_pack(agent_pack, exec_command)
    loaded, cases = _corpus_cases(corpus, limit)
    if not cases:
        _refuse("no_cases", f"{corpus} compiled to no cases")
    if exec_command is not None:
        if agent != "reference":
            _refuse("cannot_combine", "--exec and --agent both name the planner under test; give one")
        from .plans import ExecPlanner

        planner: Any = ExecPlanner(exec_command, timeout=timeout, shell=shell, policy=policy)
    else:
        planner = _planner(agent, cases)
    try:
        service = service_for(cases, loaded.connector_data.records)
    except Exception as error:  # ServingError and its causes are all refusals here
        _refuse("service_unbuildable", str(error))
    report = plan_cases(service, cases, planner, principal=principal)
    summary = write_run(out, report)
    if not json_output:
        typer.echo("plan axis only: nothing was executed; trajectory and outcomes are unobserved", err=True)
    _print_summary(summary, json_output)


@app.command("summarize")
def summarize_command(
    run: Path = typer.Argument(..., help="A run directory written by `evalrun run`."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Recompute a run's summary from its results ledger."""
    from ..cli import _refuse
    from .results import summarize

    try:
        report = _read_run(run)
    except (OSError, ValueError) as error:
        _refuse("run_unreadable", f"{run}: {error}")
    _print_summary(summarize(report), json_output)


@app.command("compare")
def compare_command(
    baseline: Path = typer.Argument(..., help="Baseline run directory."),
    recent: Path = typer.Argument(..., help="Recent run directory."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Compare two runs case by case: improvements, regressions, and which axis moved.

    Joined on case id, never on query text. Eval Studio's ±0.10 bands decide
    improvement and regression; a case graded on one side and errored on the
    other is reported as a reliability change, not a score change.
    """
    from ..cli import _refuse
    from .results import compare

    try:
        left, right = _read_run(baseline), _read_run(recent)
    except (OSError, ValueError) as error:
        _refuse("run_unreadable", str(error))
    result = compare(left, right)
    if json_output:
        typer.echo(json.dumps(result.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True))
        return
    if not result.same_case_set:
        typer.echo("warning: the two runs were not over the same case set; deltas are per shared case id only", err=True)
    typer.echo(f"{result.baseline_agent} -> {result.recent_agent}: {result.compared} shared case(s),"
               f" {len(result.improvements)} improved, {len(result.regressions)} regressed, {result.stable} stable;"
               f" mean delta {result.mean_delta}")
    typer.echo("axis deltas: " + ", ".join(
        f"{axis} {'unobserved on one side' if value is None else value}"
        for axis, value in (("plan", result.axis_deltas.plan), ("trajectory", result.axis_deltas.trajectory),
                            ("outcomes", result.axis_deltas.outcomes))))
    if result.newly_errored or result.newly_graded:
        typer.echo(f"reliability: {len(result.newly_errored)} newly errored, {len(result.newly_graded)} newly graded")
    for item in result.deltas:
        if item.verdict == "regression":
            typer.echo(f"  regression {item.case_id}: {item.baseline} -> {item.recent} {item.axes}")


@app.command("import-served")
def import_served_command(
    corpus: Path = typer.Argument(..., help="Directory written by `worldloom enterprise-evals build`."),
    results: Path = typer.Argument(..., help="JSONL of `eval_score` documents, one per line, collected from the served MCP surface."),
    out: Path = typer.Option(..., "--out", "-o", help="Run directory to write."),
    agent: str = typer.Option("served", "--agent", help="How to label the agent in the ledger."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Bring an external agent's served runs in as a run directory.

    An agent that reached the corpus over `worldloom enterprise-evals serve`
    calls `eval_score` before `eval_end` and keeps each document. Those
    documents are complete three-axis case results graded by the serving
    service; this command only collects them into a comparable ledger.
    A case with no document is reported as not attempted, never as passed.
    """
    from ..cli import _refuse
    from .results import import_served, write_run

    _, cases = _corpus_cases(corpus, None)
    try:
        report = import_served(results, cases, agent=agent)
    except (OSError, ValueError) as error:
        _refuse("results_unjoinable", f"{results}: {error}")
    summary = write_run(out, report)
    _print_summary(summary, json_output)


@app.command("import-studio")
def import_studio_command(
    corpus: Path = typer.Argument(..., help="Directory written by `worldloom enterprise-evals build`."),
    results: Path = typer.Argument(..., help="A results CSV exported by Gemini Enterprise Eval Studio."),
    out: Path = typer.Option(..., "--out", "-o", help="Run directory to write."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Bring an Eval Studio results CSV in as a run, so it can be compared with a local one.

    Eval Studio observes no tool call, so the imported run carries an answer
    score and three latencies per case and nothing on the plan or trajectory
    axes. The summary says so rather than reporting zeros as measurements.
    """
    from ..cli import _refuse
    from .results import import_studio_results, write_run

    _, cases = _corpus_cases(corpus, None)
    try:
        report = import_studio_results(results, cases)
    except (OSError, ValueError) as error:
        _refuse("results_unjoinable", f"{results}: {error}")
    if not report.results:
        _refuse("results_unjoinable", f"{results}: no row's query text matches a case in {corpus}")
    summary = write_run(out, report)
    typer.echo(f"{len(report.results)} case(s) imported; plan and trajectory axes are unobserved in Eval Studio output", err=True)
    _print_summary(summary, json_output)


@app.command("agreement")
def agreement_command(
    corpus: Path = typer.Argument(..., help="Directory written by `worldloom enterprise-evals build`, or a case set."),
    results: Path = typer.Argument(..., help="A results CSV exported by Gemini Enterprise Eval Studio."),
    rater: str = typer.Option("grounded", "--rater", help="The local grader to measure: grounded (no model) or exec:<command> (a judge over the --exec seam)."),
    rater_timeout: float = typer.Option(600.0, "--rater-timeout", help="Seconds an exec: rater child may run per answer."),
    shell: bool = typer.Option(False, "--shell", help="Run the exec: rater through the shell (the opt-in for pipelines)."),
    instruction: str | None = typer.Option(None, "--studio-instruction", help="The auto-rater instruction the Studio run was configured with; recorded, not used."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Directory to write agreement.json into."),
    json_output: bool = typer.Option(False, "--json", help="Emit the whole report as JSON."),
) -> None:
    """Measure how well the local grader agrees with Eval Studio's, answer by answer.

    Each Studio row's own fetched answer is rated again locally, so the only
    thing that differs is the grader. Reports mean absolute error, Pearson
    and Spearman correlation, the share within the comparison band, Cohen's
    kappa of pass/fail at the pass mark, per-shape slices and the cases the
    two disagree on most, then a verdict against the `evalrun.agreement.*`
    policies. Only the answer axis is comparable: Eval Studio observes no
    tool call.
    """
    from ..cli import _refuse
    from ..corpus import write_json
    from .agreement import agreement
    from .rater import GroundedRater, exec_rater
    from .results import import_studio_results

    grader: Any
    if rater == "grounded":
        grader = GroundedRater()
    elif rater.startswith("exec:") and rater.removeprefix("exec:").strip():
        grader = exec_rater(rater.removeprefix("exec:"), timeout=rater_timeout, shell=shell)
    else:
        _refuse("unknown_rater", f"{rater!r}; use grounded or exec:<command>")
    _, cases = _corpus_cases(corpus, None)
    try:
        studio = import_studio_results(results, cases)
    except (OSError, ValueError) as error:
        _refuse("results_unjoinable", f"{results}: {error}")
    if not studio.results:
        _refuse("results_unjoinable", f"{results}: no row's query text matches a case in {corpus}")
    try:
        report = agreement(studio, cases, grader, instruction=instruction)
    except ValueError as error:
        _refuse("results_unjoinable", f"{results}: {error}")
    payload = report.model_dump(mode="json", by_alias=True)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "agreement.json", payload)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    def _cell(value: Any) -> str:
        return "n/a" if value is None else str(value)

    stats = report.stats
    typer.echo(f"grader {report.local['rater']['name']} ({report.local['digest']}) vs {report.studio['agent']}:"
               f" {stats.n} rated pair(s) of {report.studio_rows} Studio row(s)")
    typer.echo(f"  {'shape':<24} {'n':>4} {'mae':>7} {'pearson':>8} {'spearman':>9} {'in band':>8} {'kappa':>7}")
    for key, row in (("all", stats), *((entry.key, entry.stats) for entry in report.by_shape)):
        typer.echo(f"  {key:<24} {row.n:>4} {_cell(row.mae):>7} {_cell(row.pearson):>8} {_cell(row.spearman):>9}"
                   f" {_cell(row.within_band):>8} {_cell(row.kappa):>7}")
    confusion = stats.confusion
    typer.echo(f"pass at {report.threshold}: both pass {confusion.both_pass}, both fail {confusion.both_fail},"
               f" Studio only {confusion.studio_pass_local_fail}, local only {confusion.studio_fail_local_pass}")
    excluded = report.excluded
    typer.echo(f"excluded: {excluded.studio_errors} Studio error(s), {excluded.local_errors} local error(s),"
               f" {excluded.no_answer_contract} without an answer contract;"
               f" {report.abstained.cases} judge-only case(s) the local rater abstains on")
    if excluded.unknown_cases:
        typer.echo(f"  {excluded.unknown_cases} Studio row(s) matched no case in {corpus}")
    for name, reason in sorted(stats.undefined.items()):
        typer.echo(f"  {name} undefined: {reason}")
    for item in report.worst[:5]:
        if item.difference:
            typer.echo(f"  worst {item.case_id}: Studio {item.studio}, local {item.local} ({item.rubric})")
    typer.echo(f"verdict: {report.verdict} ({'; '.join(report.reasons)})")
    if out is not None:
        typer.echo(f"written to {out / 'agreement.json'}", err=True)


@app.command("autopsy")
def autopsy_command(
    run: Path = typer.Argument(..., help="A run directory written by `evalrun run`."),
    top: int = typer.Option(12, "--top", min=1, help="Clusters to report in full; the rest are counted."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write the autopsy as JSON here."),
    json_output: bool = typer.Option(False, "--json", help="Print the autopsy as JSON instead of the brief."),
) -> None:
    """Cluster a run's failing cases by finding and print a brief an improver can act on.

    Each failing case is named by stable finding keys (a safety law, a
    missing plan node kind, an unmet outcome kind, an error code). Clusters
    report their share of the failures, the dimensions they concentrate in
    with lift against the whole run, and bounded evidence from one or two
    example cases. The brief is plain text, ready to hand an improving harness.
    """
    from ..cli import _refuse
    from ..corpus import write_json
    from .autopsy import autopsy, render_brief

    try:
        report = _read_run(run)
    except (OSError, ValueError) as error:
        _refuse("run_unreadable", f"{run}: {error}")
    result = autopsy(report, top=top)
    payload = result.model_dump(mode="json", by_alias=True)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, payload)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(render_brief(result), nl=False)


@app.command("curriculum")
def curriculum_command(
    run: Path = typer.Argument(..., help="A run directory written by `evalrun run`."),
    plan: Path = typer.Option(..., "--plan", help="The base dataset plan (JSON) the run's cases came from."),
    out: Path = typer.Option(..., "--out", "-o", help="Write the targeted dataset plan here."),
    round_number: int = typer.Option(1, "--round", min=1, help="Improvement round; seeds the new plan so rounds never repeat cases."),
    total: int | None = typer.Option(None, "--total", min=1, help="Rows in the new plan; defaults to the base plan's."),
    min_per_cluster: int = typer.Option(4, "--min-per-cluster", min=1, help="Floor on each targeted stratum's rows."),
    max_share: float = typer.Option(0.5, "--max-share", min=0.01, max=1.0, help="Cap on one stratum's share of the rows."),
    holdout_share: float = typer.Option(0.2, "--holdout-share", min=0.01, max=0.99, help="Weight of the held-out `test` split."),
    top: int = typer.Option(12, "--top", min=1, help="Autopsy clusters considered."),
    history: list[Path] = typer.Option([], "--history", help="Earlier run directories pooled with RUN for escalation; repeatable."),
    target_band: tuple[float, float] = typer.Option((0.3, 0.8), "--band", help="Target pass-rate band; a slice whose interval lies above it is saturated."),
    json_output: bool = typer.Option(False, "--json", help="Print the curriculum and escalations as JSON."),
) -> None:
    """Write a dataset plan of fresh cases aimed at a run's failures, and name saturated slices.

    Every actionable autopsy cluster becomes a stratum filtered to the
    dimensions it concentrates in (failure, DAG shape, operation), sized by
    its share of the failures, under a seed derived from the base seed and
    the round, with a held-out split. Clusters no dataset filter can express
    are listed, not dropped. Slices the agent has saturated are reported with
    harder shapes and designed failures to generate instead. Compile the
    written plan with `worldloom evals dataset compile`.
    """
    from ..cli import _refuse
    from ..corpus import write_json
    from ..evals.company_dataset import load_dataset_plan
    from .autopsy import autopsy
    from .curriculum import design_curriculum, escalate

    try:
        report = _read_run(run)
        earlier = [_read_run(path) for path in history]
    except (OSError, ValueError) as error:
        _refuse("run_unreadable", str(error))
    try:
        base = load_dataset_plan(json.loads(plan.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        _refuse("dataset_rejected", f"{plan}: {error}")
    try:
        curriculum = design_curriculum(autopsy(report, top=top), base, round=round_number, total=total,
                                       min_per_cluster=min_per_cluster, max_share=max_share,
                                       holdout_share=holdout_share)
        escalations = escalate([*earlier, report], target_band=target_band)
    except ValueError as error:
        _refuse("dataset_rejected", str(error))
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, curriculum.plan)
    if json_output:
        typer.echo(json.dumps({"curriculum": curriculum.model_dump(mode="json", by_alias=True, exclude={"plan"}),
                               "plan": str(out), "escalations": [item.model_dump(mode="json") for item in escalations]},
                              indent=2, sort_keys=True))
        return
    rows = sum(target.count for target in curriculum.targets)
    typer.echo(f"round {curriculum.round}: {len(curriculum.targets)} stratum(s), {rows} row(s), seed {curriculum.seed} -> {out}")
    for target in curriculum.targets:
        where = ", ".join(f"{key}={value}" for key, value in target.where.items())
        typer.echo(f"  {target.stratum}: {target.count} row(s) where {where} ({', '.join(target.keys)})")
    for item in curriculum.unmappable:
        typer.echo(f"  unmappable {item.key} ({item.cases} case(s)): {item.reason}")
    for escalation in escalations:
        slice_text = ", ".join(f"{key}={value}" for key, value in escalation.slice.items())
        proposals = "; ".join(", ".join(f"{key}={value}" for key, value in proposal.items()) for proposal in escalation.proposals)
        typer.echo(f"  saturated {slice_text}: {escalation.reason}; propose {proposals or 'nothing harder'};"
                   f" {len(escalation.retire)} case(s) no longer discriminate")


@app.command("export")
def export_command(
    run: Path = typer.Argument(..., help="A run directory written by `evalrun run`."),
    corpus: Path = typer.Option(..., "--corpus", help="The corpus or case set the run was over: personas, splits and the case-set digest come from it."),
    fmt: str = typer.Option(..., "--format", help="sft (chat demonstrations) | pairs (preference pairs, needs --against) | rewards (verifiable reward records)."),
    out: Path = typer.Option(..., "--out", "-o", help="JSONL file to write."),
    against: Path | None = typer.Option(None, "--against", help="The second run directory for --format pairs, over the same case set."),
    min_score: float = typer.Option(0.0, "--min-score", min=0.0, max=1.0, help="sft: the least overall score a demonstration may have."),
    include_failed: bool = typer.Option(False, "--include-failed", help="sft: keep cases that scored at least --min-score without passing."),
    margin: float | None = typer.Option(None, "--margin", min=0.0, help="pairs: the least overall-score lead of chosen over rejected (default: policy `evalrun.delta_band`)."),
    split: list[str] | None = typer.Option(None, "--split", help="Keep only this dataset split (repeatable). Default: train, plus any case that carries no split."),
    include_holdout: bool = typer.Option(False, "--include-holdout", help="Allow held-out splits (test, holdout, validation) and runs marked held out. A model trained on them has seen the exam, so promotion over them is void."),
    max_result_chars: int | None = typer.Option(None, "--max-result-chars", min=16, help="sft and pairs: characters of one tool result kept before a truncation marker (default: policy `evalrun.export.max_result_chars`)."),
) -> None:
    """Export a graded run as training data: SFT transcripts, preference pairs or reward records.

    A transcript is rebuilt from the ledger in recorded order: each call
    and its result, each question and the user's reply where it was asked,
    each refused call as a tool error, then the answer. Pairs join two runs
    of one case set on case id and refuse runs graded by different graders.
    Reward records keep the deterministic parts apart from the rated
    answer. Held-out splits (test, holdout, validation) are withheld, and a
    run marked held out is refused, unless --include-holdout.
    """
    from ..cli import _refuse
    from .export import (
        FORMATS,
        ExportRefused,
        HoldoutRefused,
        SplitFilter,
        preference_pairs,
        reward_records,
        sft_records,
        write_records,
    )

    if fmt not in FORMATS:
        _refuse("exactly_one", f"--format takes exactly one of {', '.join(FORMATS)}; got {fmt!r}")
    if fmt == "pairs" and against is None:
        _refuse("missing_flag", "--format pairs needs --against RUN_DIR: a pair is two runs of one case")
    if fmt != "pairs" and against is not None:
        _refuse("cannot_combine", f"--against pairs two runs; --format {fmt} reads one")
    try:
        guard = SplitFilter(tuple(split) if split else None, include_holdout)
    except HoldoutRefused as error:
        _refuse("dataset_rejected", str(error))
    try:
        report = _read_run(run)
        other = _read_run(against) if against is not None else None
    except (OSError, ValueError) as error:
        _refuse("run_unreadable", str(error))
    loaded, cases = _corpus_cases(corpus, None)
    try:
        if fmt == "sft":
            tools: dict[str, Any] | None = None
            try:
                from .harness import requests_document
                from .runner import service_for

                ran = {result.case_id for result in report.results}
                document = requests_document(service_for(cases, loaded.connector_data.records),
                                             [case for case in cases if case.id in ran], principal=report.principal)
                tools = {entry["case_id"]: entry["tools"] for entry in document["cases"]}
            except Exception as error:  # a catalog is an addition to the record, never a reason to lose it
                typer.echo(f"warning: tool catalogs unavailable ({error}); records carry no `tools`", err=True)
            records = sft_records(report, cases, min_score=min_score, require_passed=not include_failed,
                                  tools=tools, max_chars=max_result_chars, split_filter=guard)
        elif fmt == "pairs":
            assert other is not None
            records = preference_pairs(report, other, cases, margin=margin, max_chars=max_result_chars,
                                       split_filter=guard)
        else:
            records = reward_records(report, cases, split_filter=guard)
    except HoldoutRefused as error:
        _refuse("dataset_rejected", str(error))
    except ExportRefused as error:
        _refuse("results_unjoinable", str(error))
    count = write_records(out, records)
    explained = guard.explain()
    if explained:
        typer.echo(explained, err=True)
    typer.echo(f"{count} {fmt} record(s) written to {out}")


@app.command("improve")
def improve_command(
    corpus: Path = typer.Argument(..., help="The corpus or case set the agent is improved on."),
    agent_pack: str = typer.Option(..., "--agent-pack", help="The champion to start from: agent:<name>[@<digest>] or a pack file."),
    out: Path = typer.Option(..., "--out", "-o", help="Directory for rounds/, runs/, packs/ and improve.json."),
    exec_command: str | None = typer.Option(None, "--exec", help="The agent under test as an executable (the `evalrun run --exec` seam)."),
    harness: str | None = typer.Option(None, "--harness", help="An installed coding harness as the agent under test: codex or claude."),
    proposer_exec: str | None = typer.Option(None, "--proposer-exec", help="The harness that proposes revised policies, over the `pack author` seam."),
    proposer_harness: str | None = typer.Option(None, "--proposer-harness", help="An installed coding harness as the proposer: codex or claude."),
    holdout_corpus: Path | None = typer.Option(None, "--holdout-corpus", help="Held-out cases from a separate corpus (fresh seeds). Without it a stable share of CORPUS is held back."),
    holdout_share: float | None = typer.Option(None, "--holdout-share", help="Share of CORPUS held back when no --holdout-corpus is given (default: policy `evalrun.improve.holdout_share`)."),
    rounds: int | None = typer.Option(None, "--rounds", min=1, help="Rounds to run (default: policy `evalrun.improve.rounds`)."),
    rater: str | None = typer.Option(None, "--rater", help="grounded or exec:<command>; pinned for the whole loop."),
    rater_timeout: float = typer.Option(600.0, "--rater-timeout"),
    timeout: float = typer.Option(600.0, "--timeout", help="Seconds a child (agent turn or proposal) may run."),
    shell: bool = typer.Option(False, "--shell", help="Run --exec and --proposer-exec through the shell."),
    max_turns: int | None = typer.Option(None, "--max-turns", min=1),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Use only the first N cases of CORPUS."),
    principal: str = typer.Option("agent", "--principal"),
    concurrency: int | None = typer.Option(None, "--concurrency", min=1, help="Cases in flight at once in every run (default: policy `evalrun.concurrency`, 1)."),
    value: bool = typer.Option(False, "--value", help="Also require the delta weighted by each case's value at stake to clear every gate."),
    no_ablate: bool = typer.Option(False, "--no-ablate", help="Send the candidate to the holdout whole, without taking out hunks that carry nothing."),
    repeats: int | None = typer.Option(None, "--repeats", min=1, help="Run each policy this many times per case set and gate on a paired bootstrap interval over per-case means (default: policy `evalrun.improve.repeats`, 1). Size it with `evalrun noise`."),
    json_output: bool = typer.Option(False, "--json", help="Emit improve.json on stdout."),
) -> None:
    """Improve an agent's policy: failures become a revised `agent` pack, kept only if it wins on held-out cases.

    Each round runs the champion on the training cases, clusters its failures,
    asks the proposer for a revised policy (refused with findings until it
    lints clean), runs the candidate on the same cases, and only if it gains
    there runs both on the held-out cases the proposer never saw. The grader is
    pinned by digest for the whole loop. Every round leaves a receipt.
    """
    from ..cli import _refuse
    from ..packkit.authoring import run_exec_exchange
    from .grader import GraderDrift
    from .harness import ExecAgent
    from .improve import improve
    from .runner import default_concurrency, run_cases, service_for

    exec_command = _harness_exec(harness, exec_command, timeout=timeout)
    if exec_command is None:
        _refuse("missing_flag", "the agent under test is an --exec or --harness child; a policy means nothing to the "
                "reference, lazy or scripted agents")
    proposer = _harness_exec(proposer_harness, proposer_exec, timeout=timeout)
    if proposer is None:
        _refuse("missing_flag", "name the proposer with --proposer-exec or --proposer-harness")
    champion = _agent_pack(agent_pack, exec_command)
    grader = _rater_from(rater, timeout=rater_timeout, shell=shell)
    loaded, cases = _corpus_cases(corpus, limit)
    if not cases:
        _refuse("no_cases", f"{corpus} compiled to no cases")
    records = list(loaded.connector_data.records)
    held: tuple[Any, ...] | None = None
    held_records: list[Any] = []
    if holdout_corpus is not None:
        held_loaded, held = _corpus_cases(holdout_corpus, None)
        held_records = list(held_loaded.connector_data.records)
    services: dict[str, Any] = {}
    workers = default_concurrency() if concurrency is None else concurrency
    values = holdout_values = None
    if value:
        from .value import value_table

        values = value_table(cases, records)
        if held is not None:
            holdout_values = value_table(held, held_records)
    from .runner import case_set_digest

    # Each corpus is served over its own records: two worlds reuse external
    # keys (`WL-1`), so one service over both would resolve a key to whichever
    # world came first.
    held_key = case_set_digest(held) if held is not None else None

    def run(subset: Any, agent: Any) -> Any:
        key = case_set_digest(subset)
        if key not in services:
            try:
                services[key] = service_for(subset, held_records if key == held_key else records, concurrency=workers)
            except Exception as error:  # ServingError and its causes are all refusals here
                _refuse("service_unbuildable", str(error))
        return run_cases(services[key], subset, agent, principal=principal, rater=grader, concurrency=workers)

    def agent_for(pack: Any) -> Any:
        return ExecAgent(exec_command, timeout=timeout, shell=shell, max_turns=max_turns, policy=pack)

    try:
        report = improve(champion, cases, run=run, agent_for=agent_for,
                         exchange=run_exec_exchange(proposer, timeout=timeout), out=out, rater=grader,
                         holdout=held, holdout_share=holdout_share, rounds=rounds,
                         ablate=False if no_ablate else None, values=values, holdout_values=holdout_values,
                         repeats=repeats)
    except GraderDrift as error:
        _refuse("grader_drift", str(error), pinned=error.pinned, current=error.current, changed=list(error.changed))
    except ValueError as error:
        _refuse("cases_uncompilable", str(error))
    if json_output:
        typer.echo(json.dumps(report.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True))
        return
    typer.echo(f"{report.train_cases} training and {report.holdout_cases} held-out case(s); grader {report.grader['digest']}")
    if report.held_out_dropped:
        typer.echo(f"{report.held_out_dropped} case(s) of CORPUS declare a held-out split and were left out of training")
    for item in report.rounds:
        gates = "; ".join(f"{gate.name} {gate.mean_delta:+}" for gate in (item.train, item.holdout) if gate is not None)
        candidate = f" -> {item.candidate['ref']}@{item.candidate['digest'][:12]}" if item.candidate else ""
        why = f" ({'; '.join(item.reasons[:2])})" if item.reasons and item.decision != "promoted" else ""
        typer.echo(f"round {item.round}: {item.decision}{candidate}" + (f" [{gates}]" if gates else "") + why)
    typer.echo(f"champion: {report.champion['ref']}@{report.champion['digest'][:12]}"
               f" after {report.promotions} promotion(s); receipts in {out / 'rounds'}")


def _rater_from(spec: str | None, *, timeout: float, shell: bool) -> Any:
    """The rater a `--rater` value names, or None."""
    from ..cli import _refuse

    if spec is None:
        return None
    if spec == "grounded":
        from .rater import GroundedRater

        return GroundedRater()
    if spec.startswith("exec:"):
        from .rater import exec_rater

        return exec_rater(spec.removeprefix("exec:"), timeout=timeout, shell=shell)
    _refuse("unknown_rater", f"{spec!r}; use grounded or exec:<command>")


@app.command("corners")
def corners_command(
    corpus: Path = typer.Argument(..., help="A world corpus directory (`worldloom build --out`), whose events the cases rest on."),
    out: Path = typer.Option(..., "--out", "-o", help="Case set directory to write (evalrun-cases.jsonl, records.jsonl, corners.json)."),
    templates: list[str] | None = typer.Option(None, "--templates", help="Corner templates to draw from (repeat, or comma-separate); default every template."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Keep only the first N solvable cases."),
    rater: str | None = typer.Option(None, "--rater", help="The rater the proof grades answer contracts with: grounded or exec:<command>. Default: grounded wherever the shape allows it."),
    rater_timeout: float = typer.Option(600.0, "--rater-timeout", help="Seconds an exec: rater child may run per answer."),
    json_output: bool = typer.Option(False, "--json", help="Emit corners.json on stdout."),
) -> None:
    """Draw corner cases from the world's own events, keep the ones the reference agent solves.

    Each template maps a real event in the world (a confirmed cause that
    superseded a hypothesis, a restated return, an escalated exception, a
    departure) to the activity it belongs to and a case whose difficulty is
    that event. A template the world has no event for yields nothing. Every
    case is run by the reference agent with its full expected outcome,
    including any answer contract (graded by --rater); one it cannot solve
    is dropped and the reason printed. The output is a case set
    `worldloom evalrun run` reads.
    """
    from ..cli import _refuse
    from ..world import World
    from .corners import TEMPLATE_IDS, corner_cases, write_corner_set

    names = [name.strip() for value in (templates or ()) for name in value.split(",") if name.strip()]
    unknown = sorted(set(names) - set(TEMPLATE_IDS))
    if unknown:
        _refuse("unknown_corner_template", f"{', '.join(unknown)}; known templates: {', '.join(TEMPLATE_IDS)}")
    try:
        world = World.load(str(corpus))
    except Exception as error:  # a corpus that will not load is a refusal, whatever the cause
        _refuse("corpus_unloadable", f"{corpus}: {error}", fix="point at a directory written by `worldloom build --out`")
    batch = corner_cases(world, templates=names or None, limit=limit,
                         rater=_rater_from(rater, timeout=rater_timeout, shell=False))
    write_corner_set(batch, out)
    summary = batch.summary()
    if json_output:
        typer.echo(json.dumps(summary, indent=2, sort_keys=True))
        return
    for item in batch.yields:
        typer.echo(f"{item.template}: {item.generated} generated, {item.solvable} solvable, {item.dropped} dropped"
                   + (f", {item.unmatched} event(s) with no case" if item.unmatched else ""))
    for drop in batch.drops:
        typer.echo(f"dropped {drop.case_id} ({drop.template}, {drop.event}): {drop.reason}", err=True)
    if not batch.cases:
        typer.echo("gap: this world holds no event any selected template rests on, or none was solvable", err=True)
    typer.echo(f"{len(batch.cases)} corner case(s) written to {out}")


@app.command("frontier")
def frontier_command(
    case_set: Path = typer.Argument(..., help="A case set (evalrun-cases.jsonl beside records.jsonl), e.g. from `evalrun corners`."),
    out: Path = typer.Option(..., "--out", "-o", help="Case set directory for the frontier (frontier.json beside it)."),
    budget: int = typer.Option(..., "--budget", min=1, help="Champion case runs to spend."),
    champion_exec: str | None = typer.Option(None, "--champion-exec", help="The champion as an executable (the `evalrun run --exec` seam)."),
    champion_harness: str | None = typer.Option(None, "--champion-harness", help="An installed coding harness as the champion: codex or claude."),
    agent_pack: str | None = typer.Option(None, "--agent-pack", help=_AGENT_PACK_HELP),
    seeds: list[int] | None = typer.Option(None, "--seed", help="Seed(s) ordering the search (repeat); default 0."),
    holdout: list[Path] | None = typer.Option(None, "--holdout", help="Held-out cases: a case set directory, a cases JSONL file or a file of ids (repeat)."),
    holdout_ids: list[str] | None = typer.Option(None, "--holdout-id", help="A held-out case id (repeat)."),
    holdout_seeds: list[int] | None = typer.Option(None, "--holdout-seed", help="A seed held out for judging (repeat); searching it is refused."),
    timeout: float = typer.Option(600.0, "--timeout", help="Seconds the champion child may run per turn."),
    shell: bool = typer.Option(False, "--shell", help="Run --champion-exec through the shell."),
    max_turns: int | None = typer.Option(None, "--max-turns", min=1),
    json_output: bool = typer.Option(False, "--json", help="Emit frontier.json on stdout."),
) -> None:
    """Keep the cases the reference agent solves and the champion fails: the frontier.

    Cases are offered in a seeded order until `--budget` champion runs are
    spent; each is first run by the reference agent and kept only if it is
    solved there, so a frontier case is one a better agent can pass. Seeds
    or case ids held out for judging (`--holdout`, `--holdout-id`,
    `--holdout-seed`) are refused, never skipped: a search that touched them
    has already learned from them.
    """
    from ..cli import _refuse
    from .corners import (
        HoldoutOverlap,
        frontier,
        read_corner_set,
        read_holdout_ids,
        write_frontier,
    )
    from .harness import ExecAgent

    exec_command = _harness_exec(champion_harness, champion_exec, timeout=timeout)
    if exec_command is None:
        _refuse("missing_flag", "name the champion with --champion-exec or --champion-harness")
    policy = _agent_pack(agent_pack, exec_command)
    try:
        batch = read_corner_set(case_set)
        held = read_holdout_ids(holdout or ())
    except (OSError, ValueError, KeyError) as error:
        _refuse("case_set_unreadable", f"{case_set}: {error}")
    if not batch.cases:
        _refuse("no_cases", f"{case_set} holds no cases")
    champion = ExecAgent(exec_command, timeout=timeout, shell=shell, max_turns=max_turns, policy=policy)
    try:
        report = frontier(batch, champion, budget=budget, seeds=seeds or (0,),
                          holdout_ids=(*held, *(holdout_ids or ())), holdout_seeds=holdout_seeds or ())
    except HoldoutOverlap as error:
        _refuse("holdout_overlap", str(error))
    write_frontier(report, out)
    summary = report.summary()
    if json_output:
        typer.echo(json.dumps(summary, indent=2, sort_keys=True))
        return
    for item in report.yields:
        typer.echo(f"{item.template}: {item.offered} offered, {item.solved} solved by the reference, "
                   f"{item.evaluated} run by the champion, {item.frontier} on the frontier")
    typer.echo(f"{len(report.frontier_ids)} frontier case(s) from {report.spent} champion run(s) of {report.budget}; "
               f"written to {out}")


@app.command("value")
def value_command(
    run: Path = typer.Argument(..., help="A run directory written by `evalrun run`."),
    corpus: Path = typer.Option(..., "--corpus", help="The corpus or case set the run was over: cases and the records they touch come from it."),
    json_output: bool = typer.Option(False, "--json", help="Print the value summary (and mix, with --mix) as JSON."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Also write the JSON here."),
    top: int | None = typer.Option(None, "--top", min=1, help="Costliest failing cases listed (default: policy `evalrun.value.top`)."),
    mix: str | None = typer.Option(None, "--mix", help="Compare the run's cases with the company's mix over this dimension, counted from the records: activity, stream, lob, pcf_id or function."),
) -> None:
    """Read a run by what its cases are worth: value-weighted pass rate, money passed and failed, costliest failures.

    Each case is priced from the records its expected DAG reads or writes
    (their monetary fields, never an estimate), how often the company does
    its activity (record or binding volume) and the cost of getting its
    operation wrong (policy `evalrun.value.*`). Nothing is re-graded and the
    run is unchanged; `evalrun summarize` still prints the unweighted view.
    With --mix, the run's cases are compared with the company's simulated mix
    over one dimension by total variation distance.
    """
    from ..cli import _refuse
    from ..corpus import write_json
    from .value import (
        index_records,
        mix_report,
        reference_mix,
        render_value,
        value_summary,
    )

    try:
        report = _read_run(run)
    except (OSError, ValueError) as error:
        _refuse("run_unreadable", str(error))
    loaded, cases = _corpus_cases(corpus, None)
    ran = {result.case_id for result in report.results}
    chosen = [case for case in cases if case.id in ran]
    if ran and not chosen:
        _refuse("results_unjoinable", f"none of the run's {len(ran)} case(s) is in {corpus}")
    index = index_records(loaded.connector_data.records)
    summary = value_summary(report, chosen, index, top=top)
    payload: dict[str, Any] = {"value": summary.model_dump(mode="json", by_alias=True)}
    mixed = None
    if mix is not None:
        try:
            reference = reference_mix(index, dimension=mix)
        except ValueError as error:
            _refuse("unknown_value", str(error))
        mixed = mix_report(chosen, reference=reference, records=index)
        payload["mix"] = mixed.model_dump(mode="json", by_alias=True)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, payload)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(render_value(summary), nl=False)
    if mixed is not None and mixed.comparison is not None:
        comparison = mixed.comparison
        typer.echo(f"Mix over {comparison.dimension}: total variation {comparison.tvd:.4g} from the company's simulated mix")
        for item in comparison.over:
            typer.echo(f"  over  {item.value}: {item.case_share:.3g} of cases, {item.reference_share:.3g} of the work")
        for item in comparison.under:
            typer.echo(f"  under {item.value}: {item.case_share:.3g} of cases, {item.reference_share:.3g} of the work")
        for note in mixed.notes:
            typer.echo(f"note: {note}")


@app.command("noise")
def noise_command(
    runs: list[Path] = typer.Argument(..., help="Run directories of one policy over one case set, or a directory of rep-<i> runs an improve loop wrote."),
    cases: int | None = typer.Option(None, "--cases", min=1, help="Size the experiment for this many cases (default: the cases the runs graded)."),
    repeats: int | None = typer.Option(None, "--repeats", min=1, help="Size the experiment for this many repeats a side (default: the number of runs given)."),
    confidence: float | None = typer.Option(None, "--confidence", help="Confidence of the interval (default: policy `evalrun.improve.confidence`, 0.95)."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Measure one policy's run-to-run noise, and the smallest effect a comparison could detect through it.

    Given k runs of the same policy, reports each case's mean and spread, the
    pooled run-to-run standard deviation, and the minimum detectable effect
    for a paired comparison of that many cases at that many repeats a side,
    so an improve loop's `--repeats` can be sized before it is paid for.
    """
    from ..cli import _refuse
    from .noise import noise, render_noise

    directories: list[Path] = []
    for path in runs:
        nested = [] if (path / "run.json").exists() else sorted(path.glob("rep-*/run.json"))
        if nested:
            directories.extend(item.parent for item in nested)
        else:
            directories.append(path)
    try:
        reports = [_read_run(path) for path in directories]
    except (OSError, ValueError) as error:
        _refuse("run_unreadable", str(error))
    try:
        report = noise(reports, confidence=confidence, cases=cases, repeats=repeats)
    except ValueError as error:
        # Runs of different policies, case sets or graders: a usage error in
        # what was handed over, not an unreadable run.
        raise typer.BadParameter(str(error), param_hint="RUNS") from error
    if json_output:
        typer.echo(json.dumps(report.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True))
        return
    typer.echo(render_noise(report), nl=False)


__all__ = ["app"]
