"""`worldloom evalrun`: compile cases, run an agent, summarize, compare, import Eval Studio.

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


def _corpus_cases(corpus: Path, limit: int | None) -> tuple[Any, tuple[Any, ...]]:
    from ..cli import _refuse
    from ..enterprise_io import load_exported_corpus
    from .contract import cases_from_corpus

    try:
        loaded = load_exported_corpus(corpus)
    except (OSError, ValueError) as error:
        _refuse("corpus_unreadable", f"{corpus}: {error}", fix="point at a directory written by `worldloom enterprise-evals build`")
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


def _agent(spec: str, cases: tuple[Any, ...]) -> Any:
    from ..cli import _refuse
    from .agents import ReferenceAgent, ScriptedAgent, ToolCall

    if spec == "reference":
        return ReferenceAgent(cases)
    if spec == "lazy":
        return ScriptedAgent([], name="lazy", answer="")
    if spec.startswith("scripted:"):
        path = Path(spec.removeprefix("scripted:"))
        try:
            script = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            _refuse("script_unreadable", f"{path}: {error}")
        if not isinstance(script, dict) or not all(isinstance(value, dict) for value in script.values()):
            _refuse("script_invalid", f"{path}: expected {{case_id: {{calls: [[tool, args]...], answer: str}}}}")

        class _PerCase:
            name = f"scripted:{path.name}"

            def run(self, task: Any, tools: Any) -> Any:
                entry = script.get(task.case_id, {})
                calls = [ToolCall(tool=str(call[0]), arguments=dict(call[1] or {})) for call in entry.get("calls", ())]
                return ScriptedAgent(calls, answer=str(entry.get("answer", "")), name=self.name).run(task, tools)

        return _PerCase()
    _refuse("unknown_agent", f"{spec!r} is not one of {AGENTS} (scripted takes scripted:<path.json>)")


@app.command("run")
def run_command(
    corpus: Path = typer.Argument(..., help="Directory written by `worldloom enterprise-evals build`."),
    out: Path = typer.Option(..., "--out", "-o", help="Run directory to write (run.json, results.jsonl, summary.json)."),
    agent: str = typer.Option("reference", "--agent", help="reference | lazy | scripted:<path.json>"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    principal: str = typer.Option("agent", "--principal", help="The principal every run is begun under."),
    rater: str | None = typer.Option(None, "--rater", help="grounded: rate answers without a model, where the shape allows."),
    timed: bool = typer.Option(False, "--timed", help="Record wall-clock latency per case. Off by default so a run is byte-reproducible."),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Run one agent over the case set, one isolated connector state per case, and grade.

    The reference agent walks each expected DAG through the same tool surface
    an external agent gets; its run is the executable ceiling for the set.
    An agent that raises produces an error row, excluded from every mean.
    """
    from ..cli import _refuse
    from .rater import GroundedRater
    from .results import write_run
    from .runner import run_cases, service_for

    loaded, cases = _corpus_cases(corpus, limit)
    if not cases:
        _refuse("no_cases", f"{corpus} compiled to no cases")
    under_test = _agent(agent, cases)
    grader = None
    if rater is not None:
        if rater != "grounded":
            _refuse("unknown_rater", f"{rater!r}; the built-in rater is 'grounded'")
        grader = GroundedRater()
    clock = None
    if timed:
        import time

        clock = time.perf_counter
    try:
        service = service_for(cases, loaded.connector_data.records)
    except Exception as error:  # ServingError and its causes are all refusals here
        _refuse("service_unbuildable", str(error))
    report = run_cases(service, cases, under_test, principal=principal, clock=clock, rater=grader)
    summary = write_run(out, report)
    _print_summary(summary, json_output)


def _print_summary(summary: Any, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(summary.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True))
        return
    typer.echo(f"{summary.agent}: {summary.passed}/{summary.graded} passed ({summary.pass_rate}),"
               f" {summary.errors} error(s) excluded; plan {summary.means.plan}, trajectory {summary.means.trajectory},"
               f" outcomes {summary.means.outcomes}")
    typer.echo(f"trajectory: exact {summary.exact_match_rate}, in-order {summary.in_order_match_rate},"
               f" any-order {summary.any_order_match_rate}; mean calls {summary.mean_calls}")
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
    typer.echo(f"axis deltas: plan {result.axis_deltas.plan}, trajectory {result.axis_deltas.trajectory},"
               f" outcomes {result.axis_deltas.outcomes}")
    if result.newly_errored or result.newly_graded:
        typer.echo(f"reliability: {len(result.newly_errored)} newly errored, {len(result.newly_graded)} newly graded")
    for item in result.deltas:
        if item.verdict == "regression":
            typer.echo(f"  regression {item.case_id}: {item.baseline} -> {item.recent} {item.axes}")


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
