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
    max_turns: int | None = typer.Option(None, "--max-turns", min=1, help="Turns the --exec child may take per case (default: policy `evalrun.max_turns`, 64)."),
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
    from ..connectors.serving import ServingError
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
    from .runner import case_set_digest, default_concurrency, run_cases, service_for

    # Before the corpus: a typo in --harness should not wait on a build.
    exec_command = _harness_exec(harness, exec_command, timeout=timeout)
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

        under_test: Any = ExecAgent(exec_command, timeout=timeout, shell=shell, max_turns=max_turns)
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
    except ServingError as error:
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
    loaded, cases = _corpus_cases(corpus, limit)
    if not cases:
        _refuse("no_cases", f"{corpus} compiled to no cases")
    if exec_command is not None:
        if agent != "reference":
            _refuse("cannot_combine", "--exec and --agent both name the planner under test; give one")
        from .plans import ExecPlanner

        planner: Any = ExecPlanner(exec_command, timeout=timeout, shell=shell)
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
    from .results import read_run, summarize

    try:
        report = read_run(run)
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
    from .results import compare, read_run

    try:
        left, right = read_run(baseline), read_run(recent)
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


__all__ = ["app"]
