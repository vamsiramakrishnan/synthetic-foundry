"""Local process boundary for slow work; no threads or models in the core."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .service import Studio


@contextmanager
def writer_lock(root: Path) -> Iterator[None]:
    """OS ownership survives server restarts and is released on worker death."""
    path = root / "worker.lock"
    path.touch(exist_ok=True)
    with path.open("r+b") as handle:
        if sys.platform == "win32":
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def recover(studio: Studio) -> bool:
    try:
        with writer_lock(studio.root), studio.store.connection() as db:
            db.execute("UPDATE jobs SET status='interrupted', error='Worker stopped; resume from the committed checkpoints' WHERE status='running'")
        return True
    except OSError:
        return False


def run_job(studio: Studio, job_id: str, *, harness_command: str | None = None, timeout: float = 600) -> bool:
    try:
        with writer_lock(studio.root):
            with studio.store.connection() as db:
                changed = db.execute("UPDATE jobs SET status='running', error=NULL WHERE id=? AND status='queued'", (job_id,))
                if changed.rowcount != 1:
                    return False
            try:
                result = studio.execute(job_id, harness_command=harness_command, timeout=timeout)
                studio.store.finish(job_id, result=result)
            except Exception as error:
                # A durable refusal is visible after the browser or server
                # disconnects. Do not expose adapter stdout or stderr secrets.
                studio.store.finish(job_id, error=f"{type(error).__name__}: {error}")
            return True
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("job")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    run_job(Studio(args.root), args.job, harness_command=os.environ.get("WORLDLOOM_STUDIO_HARNESS"), timeout=args.timeout)


if __name__ == "__main__":
    main()
