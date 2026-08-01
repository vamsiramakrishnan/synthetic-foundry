"""Incremental narration checkpointing.

`narrate auto` can run for hours against thousands of sections and a live model
that costs real money per call. A crash at section 900 of 1000 should not mean
re-paying for the first 900 — the whole point of `compiler.narrate`'s
``on_accepted`` hook, which this module answers with a plain, append-only
sidecar file living next to the corpus it is narrating.

The sidecar is deliberately not part of the corpus schema (`corpus.py`'s
``LEDGER_FILE`` and friends): it exists only in the gap between a crash and the
rerun that resumes past it. A completed run consumes it — its entries fold into
the world's own ledger via the ordinary replay path (`compiler.narrate`'s
``_plan``, matching keys exactly as it would against any other ledger) — and
`consume` deletes the file, so a corpus that finished without ever crashing is
byte-identical to one narrated with checkpointing turned off. See
`compiler.narrate`'s module docstring for why the entries written here carry a
scratch id rather than the sequential one the finished corpus will use.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .. import corpus
from ..models import GenerationLedgerEntry

#: The sidecar's name inside a corpus directory. Chosen to sort visibly next to
#: `corpus.LEDGER_FILE` in a directory listing, and to say plainly — to a human
#: finding it after a crash — what it is and that it is safe to leave alone.
FILENAME = "narration-checkpoint.jsonl"


def load(path: Path) -> tuple[GenerationLedgerEntry, ...]:
    """Every section a previous, interrupted run already paid for.

    A missing file, an empty one, and a corpus that was never interrupted all
    read back as "nothing" — `corpus.load_models` already treats a missing
    path as an empty list, so a fresh corpus and a resumed one call this the
    same way with no branch here to get wrong.
    """
    return tuple(corpus.load_models(path, GenerationLedgerEntry))


class Writer:
    """Appends accepted sections to the sidecar as they land, thread-safe.

    One call per accepted section (`compiler.narrate`'s ``on_accepted``), made
    from whichever worker thread produced it. `--concurrency N` fans generation
    out to N workers, and a hard crash can land between any two of their
    completions — so the write, and the ``flush()`` that makes it durable
    against exactly that crash, has to happen right here, at the moment of
    acceptance, guarded by a lock because more than one worker can call this
    at once.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        # Opened lazily, on the first accepted section, not here — a run that
        # replays every section (nothing live to checkpoint) should leave no
        # trace on disk at all, rather than a zero-byte file for `load` to
        # shrug at on the next invocation.
        self._handle = None

    def __call__(self, entry: GenerationLedgerEntry) -> None:
        line = json.dumps(entry.model_dump(mode="json"), sort_keys=True)
        with self._lock:
            if self._handle is None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._handle = self._path.open("a", encoding="utf-8")
            self._handle.write(line + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()


def consume(path: Path) -> None:
    """Delete the sidecar once its entries are folded into the real ledger.

    Callers must only reach this after a narration pass has fully succeeded —
    `cli.narrate_auto` never calls it from an exception handler, so a corpus
    interrupted mid-run always leaves the sidecar in place for the next
    attempt to find. ``missing_ok`` because a run with nothing left to
    checkpoint (every section replayed) never created the file at all.
    """
    path.unlink(missing_ok=True)
