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
    ├── detail.jsonl              transaction-level rows under the facts

    ├── actor-observations.jsonl  who knew what, when, and how
    ├── actor-messages.jsonl      what one employee told another
    ├── actor-tasks.jsonl         obligations, and who owns them
    ├── actor-ledger.jsonl        every tool call, accepted and rejected
    └── artifacts/                 artifact bodies
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
# Detail tables: transaction-level rows generated under ledger facts by a
# declared recipe (see `detail.py`). One file, one model per line — a table is
# one generated thing with one provenance; its rows mean nothing individually.
# Written only when a recipe produced any, so a corpus without one is
# byte-identical to what it was.
DETAIL_FILE = "detail.jsonl"
LEDGER_FILE = "generation-ledger.jsonl"
# The actor layer, written only when an episode ran. Four files rather than one
# because they answer four different questions — who knew what, who was told
# what, who owes what, and who did what — and folding them together would make
# every one of those a filter over a mixed stream.
# Reference tables (generators/masterdata.py), written only when a build opted
# in — an un-opted corpus grows no file, and CI diffs whole directories. One
# JSON document rather than three JSONL ledgers because the table is a single
# immutable value with cross-collection integrity (a SKU names its vendor), and
# a reader should get the whole consistent register or none of it.
MASTERDATA_FILE = "masterdata.json"
OBSERVATIONS_FILE = "actor-observations.jsonl"
MESSAGES_FILE = "actor-messages.jsonl"
TASKS_FILE = "actor-tasks.jsonl"
ACTOR_LEDGER_FILE = "actor-ledger.jsonl"
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


@dataclass(frozen=True)
class TreeDivergence:
    """The first way two corpus trees fail to be byte-identical.

    Exactly one of the two halves is populated: a file-*set* divergence carries
    the ``missing``/``extra`` relative paths and an empty ``differing``; a
    *byte* divergence carries the first differing relative path (in sorted
    order) and empty sets. Paths are strings so a caller can print or serialise
    them without knowing which ``Path`` flavour produced them.
    """

    missing: tuple[str, ...]
    """Expected by the reference tree, absent from the tree under test."""
    extra: tuple[str, ...]
    """Present in the tree under test, not produced by the reference tree."""
    differing: str | None
    """The first file whose bytes differ, when the file sets already agree."""


def tree_divergence(expected: Path, actual: Path) -> TreeDivergence | None:
    """How *actual* diverges from *expected*, or ``None`` when byte-identical.

    File set first, then bytes, deliberately in that order: a corpus missing a
    file *and* differing in another should report the missing file, because a
    wrong file set means the two trees are different corpora and any byte diff
    inside them is noise about the wrong question. Only after the sets agree is
    the first byte difference (in sorted path order) worth naming.

    This is the comparison the dispersed replay sweep has always made
    (``.github/scripts/dispersed_replay.py``); it lives here so ``worldloom
    verify`` and the sweep cannot drift apart about what "byte-identical"
    means — the third hand-rolled copy is the one that would have.
    """
    expected_files = {
        path.relative_to(expected) for path in expected.rglob("*") if path.is_file()
    }
    actual_files = {path.relative_to(actual) for path in actual.rglob("*") if path.is_file()}
    if expected_files != actual_files:
        return TreeDivergence(
            missing=tuple(sorted(str(path) for path in expected_files - actual_files)),
            extra=tuple(sorted(str(path) for path in actual_files - expected_files)),
            differing=None,
        )
    for relative in sorted(expected_files):
        if (expected / relative).read_bytes() != (actual / relative).read_bytes():
            return TreeDivergence(missing=(), extra=(), differing=str(relative))
    return None


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
