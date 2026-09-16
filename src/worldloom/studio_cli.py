"""Thin CLI adapter for company projects and the local console."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

studio_app = typer.Typer(no_args_is_help=True, help="Interview, build and evaluate one persistent company.")
interview_app = typer.Typer(no_args_is_help=True, help="Exchange bounded company proposals with your coding harness.")
studio_app.add_typer(interview_app, name="interview")
Workspace = Annotated[Path, typer.Option("--workspace", "-w", help="Persistent local Studio workspace.")]


WILDCARD = {"0.0.0.0", "::", "*", ""}


def reachable_host(host: str) -> str:
    """The address to open in a browser. A wildcard bind is reached on loopback."""
    if host in WILDCARD:
        return "127.0.0.1"
    return f"[{host}]" if ":" in host else host


def bind_notice(host: str, port: int) -> list[str]:
    """Say plainly what a non-loopback bind gives away. The console has no login."""
    import ipaddress

    try:
        loopback = ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        loopback = host in {"localhost", ""}
    if loopback:
        return []
    return [
        f"Bound to {host}. The console has no authentication: anyone who reaches",
        f"port {port} can read the company, its documents and its runs, and can start jobs.",
        "Publish it to 127.0.0.1 only, or put an authenticating proxy in front.",
    ]


@studio_app.command("serve")
def serve_command(
    workspace: Workspace = Path("./worldloom-workspace"),
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
    host: Annotated[str, typer.Option("--host", help="Address to bind. The console has no authentication, so anything but a loopback address exposes it.")] = "127.0.0.1",
    harness_command: Annotated[str | None, typer.Option("--harness-command", help="Trusted local adapter: JSON stdin, JSON stdout; no shell.")] = None,
    harness: Annotated[str | None, typer.Option("--harness", help="Use an installed codex or claude CLI with its existing login.")] = None,
    allow_native_writes: Annotated[bool, typer.Option("--allow-native-writes", help="With --harness codex, allow native update/create writes in the task output directory.")] = False,
    timeout: Annotated[float, typer.Option(min=1, max=3600)] = 600,
) -> None:
    """Open the local company console; slow work runs in a separate process."""
    from .cli import _refuse
    from .studio.server import StudioServer

    if allow_native_writes and harness != "codex":
        _refuse("studio_rejected", "--allow-native-writes requires --harness codex")
    if harness:
        if harness_command or harness not in {"codex", "claude"}:
            _refuse("studio_rejected", "choose --harness codex/claude or --harness-command, not both")
        from .studio.harness import adapter_command
        harness_command = adapter_command(
            harness, timeout=max(1, timeout - 5), allow_native_writes=allow_native_writes
        )

    try:
        server = StudioServer(workspace, port=port, host=host, harness_command=harness_command, timeout=timeout)
    except OSError as error:
        _refuse("studio_rejected", f"cannot bind {host}:{port} — {error.strerror or error}")
    for line in bind_notice(host, server.server_port):
        typer.echo(line, err=True)
    typer.echo(f"Worldloom Studio: http://{reachable_host(host)}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


@studio_app.command("init")
def init_command(
    spec_path: Annotated[Path, typer.Argument(help="ProjectSpec JSON with one company and its use cases.")],
    workspace: Workspace = Path("./worldloom-workspace"),
) -> None:
    """Create a project from an explicit company contract."""
    from .cli import _refuse
    from .evals.dataset import _read
    from .studio import ProjectSpec, Studio

    try:
        result = Studio(workspace).store.create(ProjectSpec.model_validate(_read(spec_path)))
    except (OSError, ValueError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(json.dumps(result, sort_keys=True))


@studio_app.command("show")
def show_command(project: str, workspace: Workspace = Path("./worldloom-workspace")) -> None:
    """Inspect company structure, unresolved claims, interview turns and runs."""
    from .cli import _refuse
    from .studio import Studio

    try:
        result = Studio(workspace).describe(project)
    except (OSError, ValueError, KeyError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(json.dumps(result, sort_keys=True))


@studio_app.command("run")
def run_command(
    project: str, operation: Annotated[str, typer.Option(help="build, compile, narrate, foundry, native or evalrun (the reference agent)")] = "compile",
    workspace: Workspace = Path("./worldloom-workspace"),
    batch_limit: Annotated[int | None, typer.Option(min=1)] = None,
    harness_command: Annotated[str | None, typer.Option("--harness-command")] = None,
) -> None:
    """Run an exact company revision synchronously, retaining resumable checkpoints."""
    from .cli import _refuse
    from .providers import digest
    from .studio import RunOptions, Studio
    from .studio.worker import run_job

    try:
        studio = Studio(workspace)
        revision = studio.store.get(project)["revision"]
        options = RunOptions.model_validate({"operation": operation, "batch_limit": batch_limit,
                                             "harness_identity": digest(harness_command) if operation in {"narrate", "foundry", "native"} else ""})
        if options.operation == "interview":
            raise ValueError("use studio interview request for interviews")
        job = studio.store.enqueue(project, revision, options)
        if job["status"] == "paused":
            job = studio.store.retry(job["id"])
        run_job(studio, job["id"], harness_command=harness_command)
        result = studio.store.job(job["id"])
    except (OSError, ValueError, KeyError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(json.dumps(result, sort_keys=True))
    if result["status"] == "paused":
        _refuse("dataset_incomplete", "batch limit reached; repeat the command to resume committed work", exit_code=3)
    if result["status"] != "complete":
        _refuse("studio_rejected", result["error"] or "run is waiting for the active worker")
    if result["result"].get("status") == "blocked":
        _refuse("studio_rejected", "run has unmet gates; see its findings and calibration report", exit_code=3)
    if result["result"].get("report", {}).get("complete") is False:
        _refuse("dataset_incomplete", "company dataset has unmet quotas; see the run report", exit_code=3)


@studio_app.command("evalrun")
def evalrun_command(
    project: str,
    workspace: Workspace = Path("./worldloom-workspace"),
    agent: Annotated[str, typer.Option(help="reference (the executable ceiling; no harness) or harness (the configured coding harness over the exec seam).")] = "reference",
    mode: Annotated[str, typer.Option(help="run: execute through the tool surface and grade three axes; plan: state a DAG only and grade the plan axis.")] = "run",
    source: Annotated[str, typer.Option(help="Which cases: dataset (the connector queryset), programme (the process programme's record requests over the company's records) or both.")] = "dataset",
    split: Annotated[str, typer.Option(help="Grade only this dataset split (train, validation, test); empty grades every row.")] = "",
    limit: Annotated[int | None, typer.Option(min=1, help="Only the first N selected rows.")] = None,
    max_turns: Annotated[int, typer.Option(min=1, max=128, help="Turns the harness may take per case.")] = 32,
    harness_command: Annotated[str | None, typer.Option("--harness-command", help="Trusted local adapter for --agent harness: JSON stdin, JSON stdout; no shell.")] = None,
    timeout: Annotated[float, typer.Option(min=1, max=3600)] = 600,
) -> None:
    """Grade an agent on this company's connector cases, per axis, and print the run summary.

    The reference agent walks every expected DAG through the served tool
    surface and is the ceiling of the dataset; `--agent harness` grades the
    coding harness on the same cases. Results land in a run directory that
    `worldloom evalrun summarize` and `compare` read.
    """
    from .cli import _refuse
    from .providers import digest
    from .studio import RunOptions, Studio
    from .studio.worker import run_job

    try:
        if agent == "harness" and not harness_command:
            raise ValueError("--agent harness needs --harness-command; the reference agent needs none")
        studio = Studio(workspace)
        revision = studio.store.get(project)["revision"]
        options = RunOptions.model_validate({
            "operation": "evalrun", "evalrun_agent": agent, "evalrun_mode": mode, "evalrun_source": source, "evalrun_split": split,
            "evalrun_limit": limit, "evalrun_max_turns": max_turns,
            "harness_identity": digest(harness_command) if agent == "harness" else "",
        })
        job = studio.store.enqueue(project, revision, options)
        if job["status"] in {"failed", "interrupted", "paused"}:
            job = studio.store.retry(job["id"])
        run_job(studio, job["id"], harness_command=harness_command, timeout=timeout)
        result = studio.store.job(job["id"])
    except (OSError, ValueError, KeyError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(json.dumps(result, sort_keys=True))
    if result["status"] != "complete":
        _refuse("studio_rejected", result["error"] or "run is waiting for the active worker")


@studio_app.command("next")
def next_command(project: str, workspace: Workspace = Path("./worldloom-workspace")) -> None:
    """Inspect compact readiness and next actions without generating anything."""
    from .cli import _refuse
    from .studio import Studio
    try:
        result = Studio(workspace).workflow(project).model_dump(mode="json")
    except (OSError, ValueError, KeyError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(json.dumps(result, sort_keys=True))


@studio_app.command("advance")
def advance_command(
    project: str, workspace: Workspace = Path("./worldloom-workspace"),
    harness_command: Annotated[str | None, typer.Option("--harness-command")] = None,
    timeout: Annotated[float, typer.Option(min=1, max=3600)] = 600,
) -> None:
    """Execute one ready stage; stop at a proposal, configuration gap or refusal."""
    from .cli import _refuse
    from .studio import Studio
    try:
        studio = Studio(workspace)
        result = studio.advance(project, studio.store.get(project)["revision"],
                                harness_command=harness_command, timeout=timeout)
    except (OSError, ValueError, KeyError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(json.dumps(result, sort_keys=True))
    job = result.get("job") or {}
    if job.get("status") == "failed" or (job.get("result") or {}).get("status") == "blocked":
        _refuse("studio_rejected", job.get("error") or "run has unmet gates; inspect the workflow findings", exit_code=3)


@studio_app.command("prepare-native")
def prepare_native_command(
    project: str,
    use_case: Annotated[str, typer.Option("--use-case")],
    workspace: Workspace = Path("./worldloom-workspace"),
    formats: Annotated[str, typer.Option(help="Comma-separated docx,pptx,xlsx formats.")] = "docx,pptx,xlsx",
    operations: Annotated[str, typer.Option(help="Comma-separated read,analyze,update,create operations.")] = "read,analyze,update,create",
    minimum_units: Annotated[int, typer.Option(min=1, max=10000)] = 2,
    max_cases: Annotated[int, typer.Option(min=1, max=256)] = 12,
    source_artifact_id: Annotated[list[str] | None, typer.Option("--source-artifact-id", help="Repeat to constrain accepted source artifacts; required for scoped use cases.")] = None,
) -> None:
    """Print a reference-qualified native proposal for review; do not apply it."""
    from .cli import _refuse
    from .studio import NativeSuiteRequest, Studio
    try:
        studio = Studio(workspace)
        request = NativeSuiteRequest.model_validate({"use_case_id": use_case, "formats": formats.split(","),
            "operations": operations.split(","), "minimum_units": minimum_units, "max_cases": max_cases,
            "source_artifact_ids": source_artifact_id or []})
        result = studio.prepare_native(project, studio.store.get(project)["revision"], request)
    except (OSError, ValueError, KeyError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(json.dumps(result, sort_keys=True))


@interview_app.command("request")
def request_command(
    project: str, message: Annotated[str, typer.Option("--message")],
    out: Annotated[Path, typer.Option("--out", "-o")], workspace: Workspace = Path("./worldloom-workspace"),
) -> None:
    """Write the bounded interview request for a coding harness."""
    from .cli import _refuse
    from .corpus import write_json
    from .studio import Studio

    try:
        studio = Studio(workspace)
        request = studio.interview_request(project, studio.store.get(project)["revision"], message)
        write_json(out, request)
    except (OSError, ValueError, KeyError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(str(out))


@interview_app.command("accept")
def accept_command(
    project: str, response: Annotated[Path, typer.Option("--from")],
    apply: Annotated[bool, typer.Option("--apply", help="Commit the reviewed proposal if its company revision is still current.")] = False,
    workspace: Workspace = Path("./worldloom-workspace"),
) -> None:
    """Validate a harness response; proposals remain reviewable until applied."""
    from .cli import _refuse
    from .evals.dataset import _read
    from .studio import InterviewReply, Studio

    try:
        studio = Studio(workspace)
        reply = InterviewReply.model_validate(_read(response))
        result = studio.accept_interview(project, reply)
        if apply:
            result["applied"] = studio.apply_interview(project, reply.request_id)
    except (OSError, ValueError, KeyError) as error:
        _refuse("studio_rejected", str(error))
    typer.echo(json.dumps(result, sort_keys=True))


__all__ = ["studio_app"]
