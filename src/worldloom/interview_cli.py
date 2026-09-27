"""``worldloom interview``: a whole world from one interview, one question at a time.

Thin like every command module: each command opens the interview directory,
calls ``worldloom.interview`` and prints what it returned. The loop, the lint
and the build are the package's.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(
    no_args_is_help=True,
    help="Interview a harness (or a script) layer by layer into a company, its people, processes, paperwork, history and evals; then build it.",
)


def _refuse(code: str, message: str, **data: Any) -> Any:
    from rich.markup import escape

    from .cli import _refuse as refuse

    refuse(code, f"[red]error:[/red] {escape(message)}", **data)


def _exchange(script: Path | None, harness: str | None, exec_command: str | None, timeout: float) -> Any:
    from . import interview

    given = [name for name, value in (("--script", script), ("--harness", harness), ("--exec", exec_command)) if value]
    if len(given) != 1:
        _refuse("cannot_combine", "name exactly one interviewee: --script for fixture answers, --harness "
                "for an installed coding harness, or --exec for your own adapter")
    if script is not None:
        try:
            return interview.ScriptedInterviewee.load(script)
        except (OSError, ValueError, KeyError) as error:
            _refuse("interview_refused", f"{script}: {error}")
    if harness is not None:
        from .studio.harness import NAMES, adapter_command

        if harness not in NAMES:
            _refuse("interview_refused", f"{harness!r}; use {' or '.join(NAMES)}, or --exec for a custom adapter")
        exec_command = adapter_command(harness, timeout=max(1.0, timeout - 5))
    assert exec_command is not None
    return interview.exec_exchange(exec_command, timeout=timeout)


def _open(directory: Path) -> Any:
    from . import interview

    try:
        return interview.open_interview(directory)
    except ValueError as error:
        _refuse("interview_refused", str(error))


def _status(opened: Any) -> dict[str, Any]:
    from . import interview

    question = opened.question
    settled = [key for key, _ in opened.state.answers]
    return {
        "directory": str(opened.directory), "complete": question is None, "settled": settled,
        "next": None if question is None else {"id": question.id, "layer": question.layer, "asks": question.asks},
        "remaining": [item.id for item in interview.questions(opened.state) if not opened.state.accepted(item.id)],
        "rounds": len(opened.rounds), "refused": sum(1 for entry in opened.rounds if entry.get("status") == "refused"),
        "findings": list(opened.findings),
    }


@app.command("run")
def interview_run(
    directory: Path = typer.Argument(..., help="The interview directory; an existing one is resumed where it stopped."),
    script: Path | None = typer.Option(None, "--script", help="A scripted interviewee: fixture answers per question (offline, deterministic)."),
    harness: str | None = typer.Option(None, "--harness", help="An installed coding harness as the interviewee, by the name `narrate loop --harness` takes."),
    exec_command: str | None = typer.Option(None, "--exec", help="Your own adapter: one request JSON on stdin, one reply JSON on stdout."),
    max_rounds: int | None = typer.Option(None, "--max-rounds", min=1, help="Attempts per question before stopping (policy world.interview.max_rounds)."),
    stop_after: int | None = typer.Option(None, "--stop-after", min=0, help="Settle at most this many questions, then pause; run again to resume."),
    timeout: float = typer.Option(600.0, "--timeout", help="Seconds a harness may take per question."),
) -> None:
    """Interview until every layer is settled, refusing each answer with findings until it lints clean.

    Writes transcript.jsonl as it goes; once complete, pack.json (the
    assembled company pack) and resolution.json beside it.
    """
    from . import interview
    from .execseam import ExecError

    exchange = _exchange(script, harness, exec_command, timeout)
    try:
        result = interview.run(exchange, directory, max_rounds=max_rounds, stop_after=stop_after)
    except ExecError as error:
        from .cli import _refuse_exec_error

        _refuse_exec_error(error)
    except ValueError as error:
        _refuse("interview_refused", str(error))
    for entry in result.opened.rounds:
        mark = {"accepted": "✓", "refused": "✗", "questions": "?"}.get(str(entry.get("status")), "·")
        typer.echo(f"{mark} {entry['question']} (attempt {entry['attempt'] + 1}): {entry['status']}")
        for finding in entry.get("findings", ())[:6]:
            typer.echo(f"    - {finding}")
    if result.status == "complete":
        typer.echo(f"complete: {len(result.opened.state.answers)} questions settled → {directory}")
        return
    data = {"status": result.status, "question": result.question, "findings": list(result.findings),
            "questions": list(result.questions)}
    _refuse("interview_incomplete", f"stopped at {result.question}: {result.status}", **data)


@app.command("next")
def interview_next(
    directory: Path = typer.Argument(..., help="The interview directory."),
    output: Path | None = typer.Option(None, "-o", "--output", help="Write the request here instead of stdout."),
) -> None:
    """The request for the question in progress: answer it and pass the reply to `interview answer`."""
    from . import interview

    opened = _open(directory)
    payload = interview.ask(opened)
    if payload is None:
        typer.echo(json.dumps({"complete": True}))
        return
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output is None:
        typer.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8", newline="\n")
        typer.echo(f"{payload['question']['id']}: request written to {output}")


@app.command("answer")
def interview_answer(
    directory: Path = typer.Argument(..., help="The interview directory."),
    reply: Path = typer.Option(..., "--reply", help="The reply JSON: {request_id, answer} or {request_id, questions}."),
) -> None:
    """Judge one reply to the question in progress and record the round; refused replies name every finding."""
    from . import interview

    opened = _open(directory)
    if opened.complete:
        _refuse("interview_refused", "the interview is complete; nothing is being asked")
    try:
        document = json.loads(reply.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _refuse("interview_refused", f"{reply}: {error}")
    question = opened.question
    verdict = interview.submit(opened, document)
    if verdict.status == "refused":
        _refuse("interview_refused", f"{question.id}: {len(verdict.findings)} finding(s): " + "; ".join(verdict.findings),
                findings=list(verdict.findings))
    if verdict.status == "questions":
        _refuse("interview_incomplete", f"{question.id}: the interviewee asks the operator: " + "; ".join(verdict.questions),
                questions=list(verdict.questions))
    from .interview.orchestrator import write_outputs

    write_outputs(opened)
    after = opened.question
    typer.echo(f"✓ {question.id} accepted; " + ("the interview is complete" if after is None else f"next: {after.id}"))


@app.command("status")
def interview_status(
    directory: Path = typer.Argument(..., help="The interview directory."),
    json_output: bool = typer.Option(False, "--json", help="Print the status as JSON."),
) -> None:
    """What is settled, what is next, and the findings holding the question in progress."""
    status = _status(_open(directory))
    if json_output:
        typer.echo(json.dumps(status, sort_keys=True))
        return
    typer.echo(f"settled: {', '.join(status['settled']) or 'nothing yet'}")
    typer.echo("complete" if status["complete"] else f"next: {status['next']['id']}")
    for finding in status["findings"]:
        typer.echo(f"    - {finding}")


@app.command("build")
def interview_build(
    directory: Path = typer.Argument(..., help="A complete interview directory."),
    output: Path = typer.Argument(..., help="Where to write corpus/, evals/<level>/, measurements.json and interview-resolution.json."),
    seed: int = typer.Option(8128, "--seed"),
    formats: list[str] | None = typer.Option(None, "-f", "--format", help="Formats to render (default docx, xlsx, pptx, markdown)."),
    narrate_exec: str | None = typer.Option(None, "--narrate-exec", help="A writer adapter for narration (the `narrate loop --exec` contract); default is the deterministic writer."),
    narrate_harness: str | None = typer.Option(None, "--narrate-harness", help="An installed coding harness as the writer, by the name `narrate loop --harness` takes."),
    prove: bool = typer.Option(True, "--prove/--no-prove", help="Run the reference agent over every level's case set and refuse a case it cannot pass."),
    model_id: str = typer.Option("agent", "--model-id", help="Who wrote the prose; recorded in the ledger."),
) -> None:
    """Build, narrate, render and validate the interviewed world, then generate and prove its eval cases per level."""
    from . import interview
    from .interview.realise import prove as prove_cases

    opened = _open(directory)
    if not opened.complete:
        _refuse("interview_incomplete", f"{directory} is not complete; next is {opened.question.id}")
    if narrate_exec and narrate_harness:
        _refuse("cannot_combine", "--narrate-exec and --narrate-harness both name the writer; give one")
    command = narrate_exec
    if narrate_harness:
        from .studio.harness import adapter_command

        command = adapter_command(narrate_harness)
    try:
        realised = interview.realise(opened.state, seed=seed, formats=tuple(formats or interview.DEFAULT_FORMATS),
                                     narrate_command=command, model_id=model_id)
    except interview.CaseRefusal as error:
        _refuse("interview_refused", str(error), findings=list(error.findings))
    except ValueError as error:
        _refuse("interview_refused", str(error))
    proof = prove_cases(realised) if prove else {}
    short = {level: counts for level, counts in proof.items() if counts["passed"] != counts["cases"]}
    if short:
        _refuse("interview_refused", f"the reference agent cannot pass every case: {short}", proof=proof)
    measurements = dict(realised.measurements)
    if proof:
        measurements["reference"] = proof
        realised = replace(realised, measurements=measurements)
    paths = interview.export(realised, output)
    typer.echo(json.dumps({"out": str(output), "cases": measurements["cases"]["total"],
                           "evals": sorted(str(path) for key, path in paths.items() if key.startswith("evals/")),
                           "reference": proof}, sort_keys=True))


@app.command("measure")
def interview_measure(
    output: Path = typer.Argument(..., help="A directory `interview build` wrote."),
) -> None:
    """Print what an interviewed world holds: employees by level, systems, records, documents, revisions, events, cases."""
    path = output / "measurements.json"
    if not path.is_file():
        _refuse("interview_refused", f"{output} holds no measurements.json; run `worldloom interview build` first")
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


__all__ = ["app"]
