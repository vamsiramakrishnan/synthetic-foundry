"""Compile controlled-query harness cases through the existing evalrun SDK."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def harness_dags_command(
    records: Annotated[Path, typer.Argument(help="Existing ConnectorRecord JSONL; source evidence is never fabricated.")],
    config: Annotated[Path, typer.Option("--config", help="HarnessDagConfig JSON defining cohort fields, operations and response conditions.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="New evalrun case-set directory with a separate public task view.")],
) -> None:
    """Generate search/read/reconcile/write/readback DAGs with controlled retrieval."""
    from rich.markup import escape

    from .cli import _refuse
    from .connector_data import ConnectorRecord
    from .evalrun import HarnessDagConfig, build_harness_dags
    from .quality_cli import _document, _emit, _parse_json

    try:
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            raise ValueError("harness DAG destination must be absent or empty")
        configuration = HarnessDagConfig.model_validate(_document(config))
        with records.open(encoding="utf-8") as stream:
            sources = tuple(ConnectorRecord.model_validate(_parse_json(line)) for line in stream if line.strip())
        suite = build_harness_dags(sources, configuration)
        suite.write(out)
        _emit({"directory": str(out), "cases": len(suite.cases), "candidates": suite.candidates,
            "source_records": len(sources), "retrieval_mode": "controlled_typed_predicate",
            "public_tasks": str(out / "public-tasks.jsonl"),
            "skipped": [finding.model_dump(mode="json") for finding in suite.skipped]})
    except (ValueError, OSError, KeyError) as error:
        _refuse("harness_dags_rejected", escape(str(error)))
