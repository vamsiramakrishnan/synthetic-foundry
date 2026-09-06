"""Deterministic shard ownership and crash-safe corpus checkpoints.

Generation remains a pure function of the global plan. A shard only owns world
``(index - 1) % shard_count == shard_index``; changing worker count therefore
requires a new plan and is refused by the digest check. Narration acceptances are
fsync'd as JSONL immediately, while small shard state documents use atomic
replacement. A resumed narration canonicalises checkpoint ids in
``narrative.compiler`` and consequently produces the same final ledger bytes as
an uninterrupted run.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from .models import GenerationLedgerEntry

T = TypeVar("T")
PLAN_VERSION = 1


def canonical(document: dict[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(document).encode("utf-8")).hexdigest()


def owned(items: Sequence[T], *, shard_count: int, shard_index: int) -> tuple[T, ...]:
    if shard_count < 1:
        raise ValueError(f"shard count must be at least 1, got {shard_count}")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(
            f"shard index must be in [0, {shard_count - 1}], got {shard_index}"
        )
    return tuple(
        item for position, item in enumerate(items, start=1)
        if (position - 1) % shard_count == shard_index
    )


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
    )
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    # newline="\n" so shard state and plan bytes do not depend on the OS: the
    # plan digest is compared across resumes, and a CRLF rewrite on Windows
    # text mode would be a byte drift no digest check here would explain.
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def install_plan(out: Path, document: dict[str, Any], *, resume: bool) -> str:
    """Write a global plan, or prove an existing plan is exactly this one."""
    plan_hash = digest(document)
    final = {**document, "plan_digest": plan_hash}
    path = out / "mosaic.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("plan_digest") != plan_hash:
            raise ValueError(
                "output directory contains a different mosaic plan; choose a new"
                " directory or resume with the original arguments"
            )
        # Another shard of the same plan legitimately finds this file. Reusing
        # the *same shard* without --resume is refused by ShardState below.
        return plan_hash
    out.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, final)
    return plan_hash


class Checkpoint:
    """One world's append-only accepted-narration log."""

    def __init__(self, out: Path, world_index: int) -> None:
        self.path = out / ".worldloom" / "checkpoints" / f"world-{world_index:06d}.jsonl"
        self._lock = threading.Lock()

    def _complete_prefix(self) -> bytes:
        """Return complete newline-framed records and discard a torn tail.

        Every successful append ends in ``\n``.  Its absence is therefore an
        unambiguous interrupted write, not a malformed committed record.  The
        tail is truncated before another append can join onto it; terminated
        malformed rows remain untouched and are rejected by :meth:`load`.
        The checkpoint consequently has WAL semantics: a crash may lose the
        record being written, never an earlier durable acceptance.
        """
        if not self.path.exists():
            return b""
        payload = self.path.read_bytes()
        if not payload or payload.endswith(b"\n"):
            return payload
        complete = payload.rfind(b"\n") + 1
        with self.path.open("r+b") as handle:
            handle.truncate(complete)
            handle.flush()
            os.fsync(handle.fileno())
        return payload[:complete]

    def load(self) -> tuple[GenerationLedgerEntry, ...]:
        if not self.path.exists():
            return ()
        with self._lock:
            records = self._complete_prefix().splitlines()
            by_key: dict[str, GenerationLedgerEntry] = {}
            for number, record in enumerate(records, start=1):
                if not record.strip():
                    continue
                try:
                    entry = GenerationLedgerEntry.model_validate_json(record)
                except Exception as exc:
                    raise ValueError(
                        f"invalid narration checkpoint {self.path}:{number}: {exc}"
                    ) from exc
                existing = by_key.get(entry.key)
                if existing is not None and existing != entry:
                    raise ValueError(
                        f"checkpoint {self.path} contains conflicting rows for {entry.key}"
                    )
                by_key[entry.key] = entry
        return tuple(by_key.values())

    def append(self, entry: GenerationLedgerEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (entry.model_dump_json() + "\n").encode("utf-8")
        with self._lock:
            # Repair a prior interrupted append even when a caller resumes by
            # appending directly rather than calling ``load`` first.
            self._complete_prefix()
            # O_BINARY (Windows-only; getattr yields 0 elsewhere) because the
            # MSVC CRT defaults os.open to text mode, which silently rewrites
            # the "\n" framing to "\r\n" on write. The loader above tolerates
            # CRLF, so the drift would stay invisible until a resumed run
            # failed byte-identity against an uninterrupted one — corruption
            # no check in this module reports, the worst kind.
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o644,
            )
            try:
                written = 0
                while written < len(payload):
                    count = os.write(descriptor, payload[written:])
                    if count == 0:  # defensive: a regular file must progress
                        raise OSError("checkpoint append wrote zero bytes")
                    written += count
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


class ShardState:
    """Atomic progress for one worker's deterministic slice."""

    def __init__(
        self, out: Path, *, plan_digest: str, shard_count: int, shard_index: int,
        resume: bool = False,
    ) -> None:
        self.path = (
            out / ".worldloom" / "shards"
            / f"shard-{shard_index:04d}-of-{shard_count:04d}.json"
        )
        self.plan_digest = plan_digest
        self.shard_count = shard_count
        self.shard_index = shard_index
        self.completed: set[int] = set()
        if self.path.exists():
            if not resume:
                raise ValueError(
                    f"shard state {self.path} already exists; pass --resume"
                )
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("plan_digest") != plan_digest:
                raise ValueError(f"shard state {self.path} belongs to a different plan")
            self.completed = {int(value) for value in document.get("completed", ())}

    def mark_completed(self, world_index: int) -> None:
        self.completed.add(world_index)
        _atomic_json(self.path, {
            "version": PLAN_VERSION,
            "plan_digest": self.plan_digest,
            "shard_count": self.shard_count,
            "shard_index": self.shard_index,
            "completed": sorted(self.completed),
        })


__all__ = [
    "Checkpoint", "PLAN_VERSION", "ShardState", "digest", "install_plan", "owned",
]
