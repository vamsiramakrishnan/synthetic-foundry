"""Measure candidate shape without treating generation requests as evidence.

The World exposes canonical records and compiled content. Office structure is
measured from the actual package bytes. Layout, evidence placement and tool
execution need independent witnesses and remain explicit failures without them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from .connector_data import ConnectorRecord, builtin_projections
from .eval_design import EvalShape
from .models import Model
from .native_artifacts import NativeArtifactError, NativeSnapshot, inspect_artifact

if TYPE_CHECKING:
    from .world import World

_NATIVE_SUFFIXES = (".docx", ".xlsx", ".pptx", ".pdf", ".html", ".md")


class ShapeCheck(Model):
    requirement_id: str
    satisfied: bool
    observed: int
    required: int
    evidence_ids: tuple[str, ...] = ()
    detail: str = ""
    supported: bool = True


class ArtifactByteWitness(Model):
    """Identity of bytes read from one in-memory or persisted World artifact."""

    artifact_id: str
    format: str
    path: str
    size_bytes: int
    payload_digest: str


def _bytes(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def artifact_byte_witnesses(world: World) -> dict[tuple[str, str], ArtifactByteWitness]:
    """Receipts for actual renderings, including files restored by ``World.load``.

    An in-memory render supersedes persisted output. The manifest only locates
    a file: a missing file or a path escaping the corpus proves no shape.
    """
    witnesses: dict[tuple[str, str], ArtifactByteWitness] = {}

    def witness(artifact_id: str, path: str, size: int, payload_digest: str) -> None:
        suffix = PurePosixPath(path).suffix
        key = (artifact_id, suffix)
        item = ArtifactByteWitness(artifact_id=artifact_id,
                                   format="markdown" if suffix == ".md" else suffix.removeprefix("."),
                                   path=path, size_bytes=size, payload_digest=payload_digest)
        prior = witnesses.get(key)
        if prior is None or (size, payload_digest, path) > (prior.size_bytes, prior.payload_digest, prior.path):
            witnesses[key] = item

    if world._rendered:
        for item in world._rendered:
            if not item.path.endswith(".citations.md"):
                witness(item.artifact_id, item.path, len(item.payload), hashlib.sha256(item.payload).hexdigest())
    elif world.root is not None:
        root = world.root.resolve()
        for artifact in world.artifacts:
            path = PurePosixPath(artifact.path)
            if (not path.name or path.is_absolute() or ".." in path.parts
                    or artifact.path.endswith(".citations.md")):
                continue
            # The manifest records one primary format. Native renderers share
            # one basename (render.slug_for), so other formats are located as
            # siblings, and count only after their own bytes have been read.
            paths = {path, *(path.with_suffix(suffix) for suffix in _NATIVE_SUFFIXES)}
            for candidate in sorted(paths):
                try:
                    source = (root / candidate).resolve(strict=True)
                    if not source.is_relative_to(root) or not source.is_file():
                        continue
                    size = 0
                    payload_hash = hashlib.sha256()
                    with source.open("rb") as stream:
                        while chunk := stream.read(65_536):
                            size += len(chunk)
                            payload_hash.update(chunk)
                except (OSError, RuntimeError):
                    # Unreadable files and symlink loops provide no evidence either.
                    continue
                witness(artifact.id, str(candidate), size, payload_hash.hexdigest())
    return witnesses


def _native_snapshot(world: World, witness: ArtifactByteWitness) -> NativeSnapshot | None:
    if witness.size_bytes > 512 * 1024 * 1024:
        return None
    payload: bytes | None = None
    if world._rendered:
        for item in world._rendered:
            if item.artifact_id == witness.artifact_id and item.path == witness.path:
                payload = item.payload
                break
    elif world.root is not None:
        try:
            root = world.root.resolve()
            source = (root / witness.path).resolve(strict=True)
            if source.is_relative_to(root):
                payload = source.read_bytes()
        except (OSError, RuntimeError):
            return None
    if payload is None or hashlib.sha256(payload).hexdigest() != witness.payload_digest:
        return None
    try:
        return inspect_artifact(payload, witness.format)
    except NativeArtifactError:
        return None


_NATIVE_METRICS = {
    "docx": {"paragraphs": "paragraphs", "image_bytes": "image_bytes"},
    "pptx": {"slides": "slides", "image_bytes": "image_bytes",
             "speaker_note_slides": "speaker_notes", "hidden_slides": "hidden_slides",
             "native_charts": "native_charts"},
    "xlsx": {"sheets": "sheets", "rows_per_sheet": "rows_per_sheet",
             "columns_per_sheet": "columns_per_sheet", "image_bytes": "image_bytes",
             "formulas": "formula_cells", "comments": "comments"},
}


def check_candidate_shape(
    shape: EvalShape,
    world: World,
    *,
    project: Callable[[str], Sequence[ConnectorRecord]] | None = None,
) -> tuple[ShapeCheck, ...]:
    """Check all constraints; each count includes only jointly eligible items.

    Record fields and byte counts describe the canonical connector payload, not
    an estimate from a custom-field manifest. Native artifact instances require
    rendered bytes. Layout, evidence placement and execution-pressure constraints
    fail closed instead of being inferred from IR or a connector declaration.
    """
    checks: list[ShapeCheck] = []
    cache: dict[str, Sequence[ConnectorRecord]] = {}

    def records(connector: str) -> Sequence[ConnectorRecord]:
        if connector not in cache:
            cache[connector] = (project(connector) if project is not None
                                else builtin_projections().project(connector, world))
        return cache[connector]

    def count(key: str, ids: Sequence[str], required: int, detail: str) -> None:
        evidence = tuple(sorted(set(ids)))
        checks.append(ShapeCheck(requirement_id=key, satisfied=len(evidence) >= required,
                                 observed=len(evidence), required=required,
                                 evidence_ids=evidence, detail=detail))

    def unsupported(key: str, fields: Sequence[str]) -> None:
        for field in fields:
            checks.append(ShapeCheck(requirement_id=f"{key}.{field}", satisfied=False,
                                     observed=0, required=1, supported=False,
                                     detail=f"unsupported shape constraint: {field} requires an independent witness"))

    for index, requirement in enumerate(shape.records):
        key = f"shape.records[{index}]"
        unavailable = [name for name in ("custom_fields", "projection_required", "maximum_read_bytes")
                       if getattr(requirement, name)]
        if requirement.fill_rate_scale != 1.0:
            unavailable.append("fill_rate_scale")
        unsupported(key, unavailable)
        try:
            matches = [record.id for record in records(requirement.connector)
                       if record.entity == requirement.entity
                       and len(record.fields) >= requirement.total_fields
                       and sum(value is not None and value != "" and value != [] and value != {}
                               for value in record.fields.values()) >= requirement.minimum_populated_fields
                       and _bytes(record.fields) >= requirement.minimum_payload_bytes]
        except ValueError as error:
            checks.append(ShapeCheck(requirement_id=key, satisfied=False, observed=0,
                                     required=requirement.records, detail=str(error)))
            continue
        count(key, matches, requirement.records,
              "records jointly meeting canonical field, populated-field and UTF-8 payload-byte minima")

    native_formats = {suffix[1:] for suffix in _NATIVE_SUFFIXES} | {"markdown"}
    irs = {ir.id: ir for ir in world.artifact_irs}
    intents = {intent.id: intent for intent in world.artifact_intents}
    artifact_witnesses = artifact_byte_witnesses(world) if shape.artifacts else {}
    snapshots: dict[tuple[str, str], NativeSnapshot | None] = {}
    for index, artifact_requirement in enumerate(shape.artifacts):
        key = f"shape.artifacts[{index}]"
        native = artifact_requirement.artifact_type in native_formats
        metric_fields = _NATIVE_METRICS.get(artifact_requirement.artifact_type, {})
        unsupported_fields = [name for name in (
            "pages", "slides", "sheets", "rows_per_sheet", "columns_per_sheet",
            "image_bytes", "speaker_note_slides", "hidden_slides", "native_charts",
            "formulas", "comments", "evidence_index", "evidence_modality", "locator_required",
        ) if getattr(artifact_requirement, name) and name not in metric_fields]
        if native and artifact_requirement.paragraphs and "paragraphs" not in metric_fields:
            unsupported_fields.append("paragraphs")
        unsupported(key, unsupported_fields)
        suffix = "md" if artifact_requirement.artifact_type == "markdown" else artifact_requirement.artifact_type
        rendered: dict[str, int] = {}
        for (identifier, extension), byte_witness in artifact_witnesses.items():
            size = byte_witness.size_bytes
            if identifier not in intents:
                continue
            if not native or extension == f".{suffix}":
                rendered[identifier] = max(rendered.get(identifier, 0), size)
        candidates = set(rendered) if native else {
            identifier for identifier, intent in intents.items()
            if intent.artifact_type == artifact_requirement.artifact_type and identifier in irs
        }
        if artifact_requirement.artifact_type in _NATIVE_METRICS:
            for identifier in sorted(candidates):
                snapshot_key = (identifier, f".{suffix}")
                if snapshot_key not in snapshots:
                    snapshots[snapshot_key] = _native_snapshot(world, artifact_witnesses[snapshot_key])
            # A revision chain must consist of readable native versions too.
            candidates = {identifier for identifier in candidates if snapshots[(identifier, f".{suffix}")] is not None}
        eligible: list[str] = []
        for identifier in sorted(candidates):
            ir = irs.get(identifier)
            if artifact_requirement.artifact_type in _NATIVE_METRICS:
                snapshot = snapshots[(identifier, f".{suffix}")]
                if snapshot is None or any(
                    snapshot.metrics.get(metric, 0) < getattr(artifact_requirement, field)
                    for field, metric in metric_fields.items()
                ):
                    continue
            if artifact_requirement.file_size_bytes and rendered.get(identifier, 0) < artifact_requirement.file_size_bytes:
                continue
            if artifact_requirement.paragraphs and not native:
                paragraphs = sum(len(re.split(r"\n\s*\n", section.body.strip()))
                                 for section in ir.sections if section.body and section.body.strip()) if ir else 0
                if paragraphs < artifact_requirement.paragraphs:
                    continue
            # Versions are a traversable family, never a mutable version label.
            chain = {identifier}
            cursor = intents.get(identifier)
            while cursor and cursor.revises in candidates and cursor.revises not in chain:
                chain.add(cursor.revises)
                cursor = intents.get(cursor.revises)
            if len(chain) >= artifact_requirement.versions:
                eligible.append(identifier)
        count(key, eligible, artifact_requirement.instances,
              "parsed native bytes or compiled logical artifacts jointly meeting supported size, structure and revision minima; pages and evidence placement require independent witnesses")

    for index, thread_requirement in enumerate(shape.threads):
        key = f"shape.threads[{index}]"
        if thread_requirement.pagination_required:
            unsupported(key, ("pagination_required",))
        if thread_requirement.entity != "message":
            unsupported(key, ("thread_membership",))
            continue
        try:
            messages = [record for record in records(thread_requirement.connector) if record.entity == "message"]
        except ValueError as error:
            checks.append(ShapeCheck(requirement_id=key, satisfied=False, observed=0,
                                     required=thread_requirement.threads, detail=str(error)))
            continue
        groups: dict[str, list[ConnectorRecord]] = {}
        for message in messages:
            thread_id = message.fields.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                groups.setdefault(thread_id, []).append(message)
        eligible = []
        for thread_id, group in sorted(groups.items()):
            by_id = {record.external_id: record for record in group}
            group = list(by_id.values())
            depths = []
            for message in group:
                seen = {message.external_id}
                parent = message.fields.get("in_reply_to")
                while isinstance(parent, str) and parent in by_id and parent not in seen:
                    seen.add(parent)
                    parent = by_id[parent].fields.get("in_reply_to")
                depths.append(0 if isinstance(parent, str) and parent in seen else len(seen))
            attachments = {
                json.dumps(attachment, sort_keys=True) for record in group
                for attachment in (record.fields.get("attachments", [])
                                   if isinstance(record.fields.get("attachments", []), list) else [])
                if isinstance(attachment, dict) and attachment
            }
            if (len(by_id) >= thread_requirement.messages_per_thread
                    and max(depths, default=0) >= thread_requirement.reply_depth
                    and len(attachments) >= thread_requirement.attachments_per_thread
                    and sum(_bytes(record.fields) for record in group) >= thread_requirement.minimum_payload_bytes):
                eligible.append(thread_id)
        count(key, eligible, thread_requirement.threads,
              "actual messages grouped by thread_id; reply links only count within the same thread")
    return tuple(checks)


__all__ = ["ArtifactByteWitness", "ShapeCheck", "artifact_byte_witnesses", "check_candidate_shape"]
