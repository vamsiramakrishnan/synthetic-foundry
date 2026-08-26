"""Typer commands for planning and validating enterprise agent eval corpora."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .enterprise_corpus import EnterpriseCorpus, validate_corpus
from .enterprise_queries import plan_queries, valid_rows
from .enterprise_specs import CoverageProfile, builtin_registry
from .world import World

app = typer.Typer(help="Plan, generate, and validate enterprise MCP workflow evaluations.")


@app.command("space")
def space(max_candidates: int = typer.Option(1_000_000, min=1)) -> None:
    """Count semantically valid candidates without creating connector fixtures."""
    profile = CoverageProfile(max_candidates=max_candidates)
    typer.echo(json.dumps({"valid_candidates": sum(1 for _ in valid_rows(builtin_registry(), profile)), "profile": profile.name}, sort_keys=True))


@app.command("plan")
def plan(world_path: Path, output: Path, strength: int = typer.Option(2, min=1, max=4), limit: int | None = None, exhaustive: bool = False) -> None:
    """Write JSONL queries; exhaustive mode streams and honors --limit."""
    world = World.load(world_path)
    profile = CoverageProfile(strengths=strength)
    queries, report = plan_queries(world, profile=profile, strategy="exhaustive" if exhaustive else "covering", limit=limit)
    with output.open("w", encoding="utf-8") as handle:
        for query in queries:
            handle.write(query.model_dump_json() + "\n")
    if report is not None:
        typer.echo(report.model_dump_json())


@app.command("validate")
def validate(path: Path) -> None:
    """Validate a materialized enterprise corpus and exit non-zero on findings."""
    corpus = EnterpriseCorpus.model_validate_json(path.read_text(encoding="utf-8"))
    findings = validate_corpus(corpus)
    if findings:
        for finding in findings:
            typer.echo(finding, err=True)
        raise typer.Exit(1)
    typer.echo("valid")
