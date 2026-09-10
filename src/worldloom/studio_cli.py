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


@studio_app.command("serve")
def serve_command(
    workspace: Workspace = Path("./worldloom-workspace"),
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
    harness_command: Annotated[str | None, typer.Option("--harness-command", help="Trusted local adapter: JSON stdin, JSON stdout; no shell.")] = None,
    harness: Annotated[str | None, typer.Option("--harness", help="Use an installed codex or claude CLI with its existing login.")] = None,
    timeout: Annotated[float, typer.Option(min=1, max=3600)] = 600,
) -> None:
    """Open the local company console; slow work runs in a separate process."""
    from .cli import _refuse
    from .studio.server import StudioServer

    if harness:
        if harness_command or harness not in {"codex", "claude"}:
            _refuse("studio_rejected", "choose --harness codex/claude or --harness-command, not both")
        import os
        import shlex
        import subprocess
        import sys
        args = [sys.executable, "-m", "worldloom.studio.harness", harness, "--timeout", str(max(1, timeout - 5))]
        harness_command = subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)

    server = StudioServer(workspace, port=port, harness_command=harness_command, timeout=timeout)
    typer.echo(f"Worldloom Studio: http://127.0.0.1:{server.server_port}")
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
    project: str, operation: Annotated[str, typer.Option(help="build, compile, narrate, foundry or native")] = "compile",
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
