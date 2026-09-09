"""CLI adapter for bounded, independently qualified enterprise coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def qualify_command(
    world_path: Annotated[Path, typer.Argument(help="Source World corpus.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Qualified corpus, coverage findings and exact execution proofs.")],
    pool_size: Annotated[int, typer.Option("--pool-size", min=1, help="Maximum query candidates to inspect before admission and selection.")] = 128,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Maximum qualified outputs; uncovered interactions remain in the report.")] = None,
    strength: Annotated[int, typer.Option("--strength", min=1, max=4, help="Interaction strength for selection after qualification.")] = 2,
    profile_path: Annotated[Path | None, typer.Option("--profile", help="Existing enterprise ScenarioProfile JSON.")] = None,
    dag_shape: Annotated[list[str] | None, typer.Option("--dag-shape", help="Executable DAG shape; repeat or use * for the versioned catalogue.")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace an existing qualification export.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print the complete qualification report.")] = False,
) -> None:
    """Qualify actual evidence and execution, then select enterprise coverage."""
    from .cli import _load, _refuse
    from .enterprise_sdk import EnterpriseEvalHarness
    from .enterprise_specs import ScenarioProfile
    from .validate import CoherenceError

    world = _load(str(world_path))
    harness = EnterpriseEvalHarness.from_world(world)
    if profile_path is not None:
        try:
            scenario = ScenarioProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            _refuse("unreadable_document", f"{profile_path}: {error}", path=str(profile_path))
        try:
            harness = harness.with_scenario(scenario)
        except ValueError as error:
            _refuse("scenario_profile_rejected", str(error))
    harness = harness.with_profile(harness.profile.model_copy(update={"strengths": strength}))
    try:
        if dag_shape:
            harness = harness.with_dag_grammar() if dag_shape == ["*"] else harness.with_dag_grammar(*dag_shape)
        result = harness.qualify(pool_size=pool_size, max_selected=limit)
    except (ValueError, KeyError, CoherenceError) as error:
        _refuse("enterprise_qualification_failed", str(error))
    try:
        result.export(out, overwrite=overwrite)
    except FileExistsError as error:
        _refuse("destination_exists", str(error), destination=str(out), fix="pass --overwrite for a qualification directory")
    report = result.report.model_dump(mode="json")
    if not result.corpus.queries:
        _refuse("no_qualified_evals", "no candidate satisfied evidence and execution requirements",
                exit_code=3, report=report, destination=str(out))
    if json_output:
        typer.echo(result.report.model_dump_json())
    else:
        typer.echo(f"Qualified selection: {len(result.corpus.queries)} query(s); report and proofs at {out}")


__all__ = ["qualify_command"]
