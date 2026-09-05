"""Content-bound exports, verified resume, and deterministic shard reduction.

A finished directory has exactly three files. Work is staged beside the
output; the destination is never used as a scratch area. Resume verifies both
bytes and recipe execution, not the mere presence of a success marker.
"""

from __future__ import annotations

import heapq
import os
from collections import Counter
from collections.abc import Iterable, Iterator
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import Field, StrictInt

from ..models import Model
from .compiler import canonical
from .engine import Simulator
from .models import Intervention, Limits, Program, Row, SynthesisError

_FILES = {"recipe.json", "records.jsonl", "manifest.json"}


class Recipe(Model):
    engine: Literal["worldloom.synthesis/v1"]
    seed: StrictInt
    program: Program
    interventions: tuple[Intervention, ...] = ()


class TableCount(Model):
    table: str
    rows: int = Field(ge=0, strict=True)


class Manifest(Model):
    schema_version: Literal["worldloom.synthesis.export/v1"] = "worldloom.synthesis.export/v1"
    recipe_digest: str
    records_sha256: str
    rows: int = Field(ge=0, strict=True)
    tables: tuple[TableCount, ...]
    shard_index: int = Field(ge=0, strict=True)
    shard_count: int = Field(ge=1, strict=True)


def _small_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SynthesisError("invalid_export", f"not a regular file: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise SynthesisError("file_budget", path.name)
    return data


def read_program(path: Path) -> Program:
    try:
        return Program.model_validate_json(_small_file(path, 2_000_000))
    except ValueError as error:
        if isinstance(error, SynthesisError):
            raise
        raise SynthesisError("invalid_program", str(error)) from error


def _metadata(path: Path, limits: Limits | None = None) -> tuple[Simulator, Manifest]:
    if not path.is_dir() or {p.name for p in path.iterdir()} != _FILES:
        raise SynthesisError("invalid_export", "expected recipe.json, records.jsonl and manifest.json")
    try:
        recipe_bytes = _small_file(path / "recipe.json", 2_000_000)
        recipe = Recipe.model_validate_json(recipe_bytes)
        manifest_bytes = _small_file(path / "manifest.json", 64_000)
        manifest = Manifest.model_validate_json(manifest_bytes)
        simulator = Simulator(recipe.program, seed=recipe.seed,
                              interventions=recipe.interventions, limits=limits)
    except ValueError as error:
        if isinstance(error, SynthesisError):
            raise
        raise SynthesisError("invalid_export", str(error)) from error
    if recipe_bytes != canonical(simulator.recipe()) or manifest_bytes != canonical(manifest.model_dump(mode="json")):
        raise SynthesisError("noncanonical_export", "metadata is not canonically encoded")
    if manifest.recipe_digest != simulator.run_digest:
        raise SynthesisError("recipe_mismatch", "manifest does not commit to this recipe")
    if not 0 <= manifest.shard_index < manifest.shard_count:
        raise SynthesisError("invalid_shard", "manifest shard selector is invalid")
    expected_count = sum(len(range(manifest.shard_index, t.count, manifest.shard_count))
                         * (simulator.program.ticks if t.temporal else 1) for t in simulator.program.tables)
    if manifest.rows != expected_count:
        raise SynthesisError("row_count", f"expected {expected_count}, found {manifest.rows}")
    return simulator, manifest


def iter_export(path: Path, *, limits: Limits | None = None, replay: bool = True) -> Iterator[Row]:
    """Yield committed rows; exhaust the iterator to finish integrity checks.

    ``replay=False`` only checks encoding, ordering and the manifest checksum.
    It is useful after ``verify_export``; it is not independent validation.
    """
    simulator, manifest = _metadata(path, limits)
    records_path = path / "records.jsonl"
    if records_path.is_symlink() or not records_path.is_file():
        raise SynthesisError("invalid_export", "records must be a regular file")
    expected = simulator.rows(shard_index=manifest.shard_index, shard_count=manifest.shard_count) if replay else None
    count = 0
    checksum = sha256()
    table_counts: Counter[str] = Counter()
    previous: tuple[str, int, int] | None = None
    with records_path.open("rb") as stream:
        while line := stream.readline(1_000_001):
            if len(line) > 1_000_000:
                raise SynthesisError("file_budget", "record exceeds one megabyte")
            count += 1
            if count > manifest.rows:
                raise SynthesisError("row_count", "more records than committed")
            try:
                row = Row.model_validate_json(line)
            except ValueError as error:
                raise SynthesisError("invalid_record", f"line {count}: {error}") from error
            if line != canonical(row.model_dump(mode="json")):
                raise SynthesisError("noncanonical_export", f"record {count}")
            key = (row.table, row.entity, row.tick)
            if previous is not None and key <= previous:
                raise SynthesisError("record_order", str(key))
            previous = key
            checksum.update(line)
            table_counts[row.table] += 1
            if expected is not None:
                reference = next(expected, None)
                if reference != row:
                    raise SynthesisError("replay_mismatch", f"record {count} is not generated by its recipe")
            yield row
    if count != manifest.rows or (expected is not None and next(expected, None) is not None):
        raise SynthesisError("row_count", "incomplete record stream")
    if checksum.hexdigest() != manifest.records_sha256:
        raise SynthesisError("checksum_mismatch", "records changed after export")
    counts = tuple(TableCount(table=n, rows=v) for n, v in sorted(table_counts.items()))
    if counts != manifest.tables:
        raise SynthesisError("table_count", "per-table counts differ from manifest")


def verify_export(path: Path, *, limits: Limits | None = None) -> Manifest:
    for _ in iter_export(path, limits=limits):
        pass
    return _metadata(path, limits)[1]


def _write(simulator: Simulator, rows: Iterable[Row], directory: Path,
           shard_index: int, shard_count: int) -> Manifest:
    directory = Path(directory)
    if directory.exists():
        raise SynthesisError("destination_exists", str(directory))
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock = directory.parent / f".{directory.name}.synthesis.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise SynthesisError("destination_locked", str(directory)) from error
    try:
        os.close(descriptor)
        with TemporaryDirectory(prefix=f".{directory.name}.stage-", dir=directory.parent) as temporary:
            stage = Path(temporary)
            (stage / "recipe.json").write_bytes(canonical(simulator.recipe()))
            checksum = sha256()
            counts: Counter[str] = Counter()
            with (stage / "records.jsonl").open("wb") as output:
                for row in rows:
                    data = canonical(row.model_dump(mode="json"))
                    checksum.update(data)
                    output.write(data)
                    counts[row.table] += 1
            manifest = Manifest(recipe_digest=simulator.run_digest, records_sha256=checksum.hexdigest(),
                                rows=sum(counts.values()),
                                tables=tuple(TableCount(table=n, rows=v) for n, v in sorted(counts.items())),
                                shard_index=shard_index, shard_count=shard_count)
            (stage / "manifest.json").write_bytes(canonical(manifest.model_dump(mode="json")))
            if directory.exists():
                raise SynthesisError("destination_exists", str(directory))
            stage.rename(directory)
            return manifest
    finally:
        lock.unlink()


def export(simulator: Simulator, directory: Path, *, shard_index: int = 0,
           shard_count: int = 1, resume: bool = False) -> Manifest:
    if resume and directory.exists():
        manifest = verify_export(directory, limits=simulator.compiled.limits)
        if (manifest.recipe_digest, manifest.shard_index, manifest.shard_count) != (
            simulator.run_digest, shard_index, shard_count
        ):
            raise SynthesisError("resume_mismatch", "existing export has a different recipe or shard selector")
        return manifest
    return _write(simulator, simulator.rows(shard_index=shard_index, shard_count=shard_count),
                  directory, shard_index, shard_count)


def merge_exports(paths: Iterable[Path], directory: Path, *, limits: Limits | None = None) -> Manifest:
    paths = tuple(paths)
    if not paths or len(paths) > 128:
        raise SynthesisError("shard_budget", "merge requires between one and 128 shards")
    items = [(_metadata(path, limits), path) for path in paths]
    simulator, first = items[0][0]
    selectors = []
    for (_, manifest), path in items:
        if (manifest.recipe_digest, manifest.shard_count) != (first.recipe_digest, first.shard_count):
            raise SynthesisError("shard_mismatch", str(path))
        selectors.append(manifest.shard_index)
    if len(selectors) != first.shard_count or sorted(selectors) != list(range(first.shard_count)):
        raise SynthesisError("shard_coverage", "missing or duplicate shards")
    # Verify sequentially to keep only one dimension cache resident. The merge
    # pass rechecks checksums, so a shard changed between passes is still refused.
    for path in paths:
        verify_export(path, limits=limits)
    streams = [iter_export(path, limits=limits, replay=False) for path in paths]
    merged = heapq.merge(*streams, key=lambda row: (row.table, row.entity, row.tick))
    return _write(simulator, merged, directory, 0, 1)


def load_simulator(path: Path, *, limits: Limits | None = None) -> Simulator:
    verify_export(path, limits=limits)
    return _metadata(path, limits)[0]


def write_program(program: Program, path: Path) -> None:
    # Unlike an export, this writes a single caller-selected file. Exclusive
    # creation avoids replacing a spec while a harness still references it.
    with path.open("xb") as stream:
        stream.write(canonical(program.model_dump(mode="json")))
