"""Transactional revisions and jobs; generated worlds stay in immutable snapshots."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..providers import digest
from .models import ProjectSpec, RunOptions


class StudioConflict(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class ProjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, parent TEXT, ordinal INTEGER NOT NULL,
                    spec TEXT NOT NULL, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, revision TEXT NOT NULL,
                    options TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS interviews (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, revision TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, request TEXT NOT NULL, reply TEXT);
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.root / "studio.sqlite", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, spec: ProjectSpec) -> dict[str, Any]:
        spec = ProjectSpec.model_validate(spec.model_dump(mode="json"))
        payload = spec.model_dump(mode="json")
        key = digest(["company-project/v1", payload])
        revision = digest([key, None, payload])
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM projects WHERE id=?", (key,)).fetchone() is None:
                db.execute("INSERT INTO projects VALUES (?, ?)", (key, revision))
                db.execute("INSERT INTO revisions VALUES (?, ?, NULL, 1, ?, ?)",
                           (revision, key, canonical(payload), "Company created"))
        return self.get(key)

    def get(self, project: str, revision: str | None = None) -> dict[str, Any]:
        with self.connection() as db:
            current = db.execute("SELECT revision FROM projects WHERE id=?", (project,)).fetchone()
            if current is None:
                raise KeyError("company project not found")
            row = db.execute("SELECT * FROM revisions WHERE project=? AND id=?",
                             (project, revision or current["revision"])).fetchone()
            if row is None:
                raise KeyError("company revision not found")
        return {"id": project, "revision": row["id"], "current_revision": current["revision"],
                "parent": row["parent"], "ordinal": row["ordinal"], "reason": row["reason"],
                "spec": json.loads(row["spec"])}

    def projects(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            keys = [row[0] for row in db.execute("SELECT id FROM projects ORDER BY rowid")]
        return [self.get(key) for key in keys]

    def revise(self, project: str, expected: str, spec: ProjectSpec, *, reason: str) -> dict[str, Any]:
        spec = ProjectSpec.model_validate(spec.model_dump(mode="json"))
        if not reason.strip() or len(reason) > 1000:
            raise ValueError("give a change reason of 1 to 1000 characters")
        current = self.get(project)
        if current["revision"] != expected:
            raise StudioConflict("company changed; reload before applying this revision")
        payload = spec.model_dump(mode="json")
        if payload == current["spec"]:
            return current
        key = digest([project, expected, payload])
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE projects SET revision=? WHERE id=? AND revision=?",
                                 (key, project, expected))
            if changed.rowcount != 1:
                raise StudioConflict("company changed; reload before applying this revision")
            db.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?, ?)",
                       (key, project, expected, current["ordinal"] + 1, canonical(payload), reason))
        return self.get(project)

    def history(self, project: str) -> list[dict[str, Any]]:
        self.get(project)
        with self.connection() as db:
            rows = db.execute("SELECT id FROM revisions WHERE project=? ORDER BY ordinal DESC", (project,)).fetchall()
        return [self.get(project, row["id"]) for row in rows]

    def enqueue(self, project: str, revision: str, options: RunOptions) -> dict[str, Any]:
        current = self.get(project, revision)
        payload = options.model_dump(mode="json")
        # Exact repeat clicks are idempotent. New interview messages and new
        # revisions get new jobs, while dataset retries reuse checkpoints.
        key = digest([project, current["revision"], payload])
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, ?, 'queued', NULL, NULL)",
                       (key, project, revision, canonical(payload)))
        return self.job(key)

    def job(self, key: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        if row is None:
            raise KeyError("run not found")
        return {**dict(row), "options": json.loads(row["options"]),
                "result": json.loads(row["result"]) if row["result"] else None}

    def jobs(self, project: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT id FROM jobs WHERE (? IS NULL OR project=?) ORDER BY rowid DESC",
                              (project, project)).fetchall()
        return [self.job(row["id"]) for row in rows]

    def retry(self, key: str) -> dict[str, Any]:
        with self.connection() as db:
            changed = db.execute("UPDATE jobs SET status='queued', error=NULL WHERE id=? AND status IN ('failed','interrupted','paused')", (key,))
            if changed.rowcount != 1:
                raise StudioConflict("only failed, interrupted or paused runs can be retried")
        return self.job(key)

    def finish(self, key: str, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with self.connection() as db:
            db.execute("UPDATE jobs SET status=?, result=?, error=? WHERE id=?",
                       ("failed" if error else "paused" if result and result.get("status") == "paused" else "complete",
                        canonical(result) if result is not None else None,
                        error[:4000] if error else None, key))


__all__ = ["ProjectStore", "StudioConflict"]
