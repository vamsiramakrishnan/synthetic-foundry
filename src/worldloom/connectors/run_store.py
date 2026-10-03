"""An append-only JSONL journal that lets an evaluation service's runs survive a restart.

The service's run state is an emulator fork plus everything the run's calls
did to it. Copying that state to disk would mean serialising every emulator
and keeping that format in step with the emulator forever. The service is
deterministic instead: the same calls against the same rows leave the same
spans, refusals, questions and records. So the journal keeps only what a
caller did (the begin, each call with its arguments, each question, each
refusal another surface recorded) and the grade an ended run left, and a
restarted service replays the open runs' calls to rebuild them.

One record per line, each written, flushed and fsynced before the call that
made it returns, so a crash loses at most the line being written. A reload
tolerates exactly that: a final line with no newline, or one that does not
parse, is dropped with a warning and cut from the file, so the next append
does not glue a new record onto the remains of the torn one. A bad line
anywhere else is corruption, not a crash, and is refused.

Stdlib only, and no clock: a record carries nothing that is not a function of
the calls, so two services fed the same calls write the same journal.
"""
from __future__ import annotations

import json
import os
import warnings
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any

SCHEMA = "worldloom.run-store/v1"


class RunStoreWarning(UserWarning):
    """A recoverable problem found while reloading a run store (a torn final line, an unreplayable run)."""


class RunStoreError(ValueError):
    """The run store cannot be read or written as a journal."""


def encode(record: Mapping[str, Any]) -> bytes:
    """One record as its journal line: sorted keys, no NaN, a pinned newline."""
    try:
        text = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise RunStoreError(f"run_store: a record must be plain JSON ({error})") from error
    return (text + "\n").encode("utf-8")


class RunStore:
    """The journal at *path*; created on first append, its parent directory included."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        if self.path.is_dir():
            raise RunStoreError(f"run_store: {self.path} is a directory; name a file")
        # Appends from different runs interleave whole lines, never bytes.
        self._lock = Lock()

    def load(self) -> list[dict[str, Any]]:
        """Every complete record, in file order; a torn final line is dropped (with a warning) and truncated away."""
        if not self.path.exists():
            return []
        data = self.path.read_bytes()
        records: list[dict[str, Any]] = []
        offset = 0
        lines = data.split(b"\n")
        # `split` leaves an empty last element when the file ends in a
        # newline; anything else there is a final line the writer never
        # finished.
        complete, tail = lines[:-1], lines[-1]
        for number, line in enumerate(complete, start=1):
            try:
                record = json.loads(line.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("not an object")
            except ValueError as error:
                if number == len(complete) and not tail:
                    self._torn(offset, f"line {number} does not parse ({error})")
                    return records
                raise RunStoreError(f"run_store: {self.path} line {number} is corrupt ({error}); "
                                    "only a torn final line is recovered") from error
            records.append(record)
            offset += len(line) + 1
        if tail:
            self._torn(offset, f"line {len(complete) + 1} has no newline")
        return records

    def _torn(self, offset: int, reason: str) -> None:
        warnings.warn(f"run_store: {self.path}: dropping a torn final record: {reason}", RunStoreWarning, stacklevel=3)
        with self._lock, open(self.path, "r+b") as handle:
            handle.truncate(offset)
            handle.flush()
            os.fsync(handle.fileno())

    def append(self, record: Mapping[str, Any]) -> None:
        """Write one record durably: the line, a flush, an fsync, before returning."""
        line = encode({"schema": SCHEMA, **record})
        with self._lock:
            created = not self.path.exists()
            if created:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "ab") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            if created:
                # The file's directory entry is durable only once its
                # directory is synced; otherwise a crash can lose the file.
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)


__all__ = ["SCHEMA", "RunStore", "RunStoreError", "RunStoreWarning", "encode"]
