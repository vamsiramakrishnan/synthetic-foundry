"""Corpus serialisation.

A corpus is a directory of plain text. Nothing in it requires Worldloom to read:
JSONL for the ledgers, JSON for the world header, and artifact bodies as their
own files. That is deliberate — a corpus outlives the library version that wrote
it, and a benchmark nobody can open is not a benchmark.

Layout::

    retail-close/
    ├── world.json                 header, entities, personas, access policies
    ├── lore.jsonl
    ├── facts.jsonl
    ├── events.jsonl
    ├── artifact-intents.jsonl    planned artifacts, before rendering
    ├── artifact-manifest.jsonl   rendered artifacts, with provenance
    ├── intentional-errors.jsonl
    ├── evals.jsonl
    └── artifacts/                 artifact bodies
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

#: Bumped when the on-disk layout changes incompatibly.
SCHEMA_VERSION = 1

WORLD_FILE = "world.json"
LORE_FILE = "lore.jsonl"
FACTS_FILE = "facts.jsonl"
EVENTS_FILE = "events.jsonl"
INTENTS_FILE = "artifact-intents.jsonl"
IR_FILE = "artifact-ir.jsonl"
MANIFEST_FILE = "artifact-manifest.jsonl"
ERRORS_FILE = "intentional-errors.jsonl"
EVALS_FILE = "evals.jsonl"
LEDGER_FILE = "generation-ledger.jsonl"
ARTIFACTS_DIR = "artifacts"

T = TypeVar("T", bound=BaseModel)


class CorpusError(Exception):
    """Raised when a corpus cannot be read."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping blank lines. Missing file yields an empty list."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise CorpusError(f"{path.name} line {number}: {exc.msg}") from exc
    return rows


def write_jsonl(path: Path, models: list[BaseModel]) -> None:
    """Write models as JSONL, one per line, with stable key order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for model in models:
            handle.write(json.dumps(model.model_dump(mode="json"), sort_keys=True) + "\n")


def load_models(path: Path, model: type[T]) -> list[T]:
    """Read a JSONL file into validated models."""
    out: list[T] = []
    for index, row in enumerate(read_jsonl(path), start=1):
        try:
            out.append(model.model_validate(row))
        except Exception as exc:
            identifier = row.get("id", f"line {index}")
            raise CorpusError(f"{path.name}: {identifier} is invalid: {exc}") from exc
    return out


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object."""
    if not path.is_file():
        raise CorpusError(f"missing required file: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusError(f"{path.name}: {exc.msg}") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON object with stable key order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def bundled_examples_dir() -> Path:
    """Where the bundled example corpora live.

    Works both from a source checkout and from an installed wheel, since the
    examples are force-included into the package at build time.
    """
    installed = Path(__file__).parent / "_examples"
    if installed.is_dir():
        return installed
    return Path(__file__).resolve().parents[2] / "examples"


def resolve_corpus(name_or_path: str) -> Path:
    """Resolve a corpus by bundled name or filesystem path."""
    candidate = Path(name_or_path)
    if candidate.is_dir():
        return candidate
    bundled = bundled_examples_dir() / name_or_path
    if bundled.is_dir():
        return bundled
    available = sorted(p.name for p in bundled_examples_dir().glob("*") if p.is_dir())
    raise CorpusError(
        f"no corpus at {name_or_path!r}. Bundled corpora: {', '.join(available) or 'none'}"
    )
