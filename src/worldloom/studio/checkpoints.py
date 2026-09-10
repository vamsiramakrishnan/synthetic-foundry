"""Atomic content-bound checkpoints shared by the foundry stages."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..corpus import write_json
from ..evals.dataset import _files, _read
from ..execseam import ExecReply, run_exec
from ..providers import digest
from ..world import World


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    write_json(temporary, value)
    temporary.replace(path)


def document(path: Path, value: Any) -> None:
    """A deterministic document may be reissued, never silently replaced."""
    if path.exists():
        if _read(path) != value:
            raise ValueError(f"checkpoint changed: {path.name}")
    else:
        atomic_json(path, value)


def load_world(path: Path, intent: Any) -> tuple[World, dict[str, Any]] | None:
    if not path.exists():
        return None
    receipt = _read(path / "receipt.json")
    if receipt.get("intent") != intent or receipt.get("files") != _files(path):
        raise ValueError("foundry stage changed after checkpoint")
    return World.load(path / "world"), _read(path / "result.json")


def save_world(path: Path, intent: Any, world: World, result: dict[str, Any]) -> None:
    if load_world(path, intent) is not None:
        return
    temporary = path.with_name(path.name + ".pending")
    if temporary.exists():
        if (temporary / "intent.json").exists() and _read(temporary / "intent.json") != intent:
            raise ValueError("unfinished stage belongs to another input")
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    write_json(temporary / "intent.json", intent)
    world.export(temporary / "world")
    write_json(temporary / "result.json", result)
    write_json(temporary / "receipt.json", {"intent": intent, "files": _files(temporary)})
    temporary.rename(path)


class Exchanges:
    """Replay a validated prefix of external exchanges, including rejected prose."""

    def __init__(self, root: Path, command: str | None, timeout: float) -> None:
        self.root, self.command, self.timeout = root, command, timeout
        self.ordinal = 0
        self.paths = sorted(root.glob("[0-9][0-9][0-9][0-9][0-9][0-9].json"))
        if [p.name for p in self.paths] != [f"{i:06d}.json" for i in range(len(self.paths))]:
            raise ValueError("harness exchange prefix has a missing turn")
        head = root / "head.json"
        if head.exists():
            expected = _read(head)
            count = expected["count"]
            if count > len(self.paths) or digest([_read(p) for p in self.paths[:count]]) != expected["digest"]:
                raise ValueError("harness exchange journal changed after checkpoint")
            if len(self.paths) > count + 1:
                raise ValueError("harness exchange journal has uncommitted turns")
        elif len(self.paths) > 1:
            raise ValueError("harness exchange journal is missing its head")

    def __call__(self, payload: dict[str, Any]) -> ExecReply:
        path = self.root / f"{self.ordinal:06d}.json"
        self.ordinal += 1
        intent = {"request": payload, "harness": digest(self.command)}
        if path.exists():
            value = _read(path)
            if value.get("intent") != intent or digest(value.get("response")) != value.get("response_digest"):
                raise ValueError("harness exchange changed after checkpoint")
            return ExecReply(document=value["response"], stderr_tail="")
        if not self.command:
            raise ValueError("connect a coding harness to continue the unfinished foundry stage")
        reply = run_exec(self.command, payload, timeout=self.timeout)
        atomic_json(path, {"intent": intent, "response": reply.document,
                           "response_digest": digest(reply.document)})
        self.paths.append(path)
        atomic_json(self.root / "head.json", {"count": len(self.paths),
                    "digest": digest([_read(p) for p in self.paths])})
        return reply
