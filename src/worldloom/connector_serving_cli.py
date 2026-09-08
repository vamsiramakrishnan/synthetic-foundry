"""CLI adapter for the optional connector MCP server."""
from __future__ import annotations

import json
import os
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
    max_runs: int = typer.Option(32, min=1),
    max_calls: int = typer.Option(512, min=1),
    check: bool = typer.Option(False, "--check", help="Validate the server configuration and exit without listening."),
) -> None:
    """Serve isolated enterprise evaluations as StreamableHTTP MCP connector tools."""
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
        service = ConnectorEvaluationService.from_corpus(
            corpus, allowed_tools=tools or None,
            limits=ServingLimits(max_runs=max_runs, max_calls_per_run=max_calls),
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
