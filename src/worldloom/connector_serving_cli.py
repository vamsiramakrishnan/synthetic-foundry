"""CLI adapter for the optional connector MCP server."""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer


def serve_command(
    corpus_path: Path,
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000, min=1, max=65535),
    query_ids: Annotated[list[str] | None, typer.Option("--query-id", help="Serve only these query IDs; repeat to select more.")] = None,
    tools: Annotated[list[str] | None, typer.Option("--tool", help="Allow a connector.tool; repeat. Every selected query must remain executable.")] = None,
    tokens_env: str | None = typer.Option(None, "--tokens-env", help="Environment variable holding a JSON map of principal names to bearer secrets."),
    allowed_hosts: Annotated[list[str] | None, typer.Option("--allowed-host", help="Trusted external Host header; repeat for multiple proxy names.")] = None,
    max_runs: int | None = typer.Option(None, min=1, help="Runs open at once (default: policy `connectors.serving.max_runs`)."),
    max_calls: int | None = typer.Option(None, min=1, help="Calls one run may make (default: policy `connectors.serving.max_calls_per_run`)."),
    worker_id: str | None = typer.Option(None, "--worker-id", help="Prefix every run id with this worker's name (w3 mints w3-run-1), so ids from several server processes never collide. Each process keeps its own runs: route every call for a run id to the process that began it."),
    check: bool = typer.Option(False, "--check", help="Validate the server configuration and exit without listening."),
) -> None:
    """Serve isolated enterprise evaluations as StreamableHTTP MCP connector tools.

    One process holds its runs in memory, so the server runs one worker. To
    serve more, start several processes, each with its own `--worker-id`,
    behind a proxy with sticky routing by run id: the id's prefix names the
    process that began it, and a call that reaches another process is
    refused as an unknown run. Run state is never shared across processes.
    """
    from .cli import _refuse
    from .connectors.serving import (
        ConnectorEvaluationService,
        ServingLimits,
        create_connector_app,
    )
    from .enterprise_corpus import EnterpriseCorpus
    from .enterprise_io import load_exported_corpus

    try:
        corpus = (load_exported_corpus(corpus_path) if corpus_path.is_dir()
                  else EnterpriseCorpus.model_validate_json(corpus_path.read_text(encoding="utf-8")))
        if query_ids:
            selected = set(query_ids)
            missing = selected - {query.id for query in corpus.queries}
            if missing:
                raise ValueError(f"unknown queries: {sorted(missing)}")
            corpus = corpus.model_copy(update={
                "queries": tuple(query for query in corpus.queries if query.id in selected),
                "fixtures": tuple(fixture for fixture in corpus.fixtures if fixture.query_id in selected),
            })
        tokens = None
        if tokens_env:
            raw = os.environ.get(tokens_env)
            if raw is None:
                raise ValueError(f"environment variable {tokens_env} is not set")
            try:
                tokens = json.loads(raw)
            except ValueError as error:
                raise ValueError("tokens environment variable must contain a JSON object") from error
            if not isinstance(tokens, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tokens.items()):
                raise ValueError("tokens must map principal names to string secrets")
        # Unset limits come from the policy in force, the same defaults the
        # SDK uses; the flag used to hard-code 512 calls against a policy of 4096.
        policy = ServingLimits()
        limits = replace(policy,
                         max_runs=policy.max_runs if max_runs is None else max_runs,
                         max_calls_per_run=policy.max_calls_per_run if max_calls is None else max_calls)
        service = ConnectorEvaluationService.from_corpus(
            corpus, allowed_tools=tools or None, limits=limits,
            run_prefix=f"{worker_id}-" if worker_id else "",
        )
        app = create_connector_app(service, host=host, bearer_tokens=tokens, allowed_hosts=allowed_hosts or ())
        if check:
            typer.echo(json.dumps({"queries": len(service.rows), "connector_tools": len(service.tools),
                                   "evaluation_tools": 5, "transport": "streamable-http", "path": "/mcp"}, sort_keys=True))
            return
        import uvicorn

        uvicorn.run(app, host=host, port=port, workers=1)
    except (OSError, ValueError, RuntimeError) as error:
        _refuse("connector_serve_failed", str(error))
