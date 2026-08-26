"""Stable JSON/JSONL interchange for large enterprise evaluation corpora."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from .enterprise_corpus import EnterpriseCorpus, QueryFixture
from .enterprise_queries import PlannedEnterpriseQuery


def export_queries(queries: Iterable[PlannedEnterpriseQuery], path: Path) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for query in queries:
            handle.write(query.model_dump_json() + "\n")
            count += 1
    return count


def iter_queries(path: Path) -> Iterator[PlannedEnterpriseQuery]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield PlannedEnterpriseQuery.model_validate_json(line)
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: invalid planned query") from error


def export_corpus(corpus: EnterpriseCorpus, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    export_queries(corpus.queries, directory / "queries.jsonl")
    (directory / "connector-data.json").write_text(corpus.connector_data.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    with (directory / "fixtures.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for fixture in corpus.fixtures:
            handle.write(fixture.model_dump_json() + "\n")
    manifest = {
        "schema": "worldloom.enterprise-evals/v1",
        "queries": len(corpus.queries),
        "connector_records": len(corpus.connector_data.records),
        "fixtures": len(corpus.fixtures),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def iter_fixtures(path: Path) -> Iterator[QueryFixture]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield QueryFixture.model_validate_json(line)
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: invalid query fixture") from error
