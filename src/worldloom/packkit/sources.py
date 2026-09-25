"""Where packs are found: one search path, highest precedence first.

1. roots a caller names (a Studio workspace's ``packs/``, a ``--pack-root``),
2. each directory in ``WORLDLOOM_PACK_PATH`` (``os.pathsep``-separated),
3. the user's own directory, ``$WORLDLOOM_HOME/packs`` (``~/.worldloom/packs``),
4. the packs shipped in ``worldloom/_data/packs``.

Every root has the same layout, ``<kind>/<name>.json`` or a directory
``<kind>/<name>/`` holding ``pack.json`` (the envelope) and body fragments
``*.json`` merged into its body in file-name order. Fragments let one pack be
owned by several authors, one file each, without two of them editing one
document.

A pack found in a higher root shadows the same ``kind:name`` below it, which is
how a user colloquialises a shipped industry: write ``industry/banking.json``
in their own directory, extending ``industry:banking``, and the extension
resolves to the shipped one beneath it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from .envelope import NAME, PackEnvelope, read_envelope

ENV_PATH = "WORLDLOOM_PACK_PATH"
ENV_HOME = "WORLDLOOM_HOME"


def user_root() -> Path:
    home = os.environ.get(ENV_HOME)
    return (Path(home) if home else Path.home() / ".worldloom") / "packs"


def builtin_root() -> Path:
    with as_file(files("worldloom").joinpath("_data", "packs")) as path:
        return Path(path)


@dataclass(frozen=True)
class Located:
    """One pack as found: its envelope, where, and at which precedence."""

    envelope: PackEnvelope
    origin: str
    """``builtin``, ``user``, ``env`` or ``root``: where the pack came from, for
    a person reading ``pack list`` and for an upload's refusal."""
    location: Path
    rank: int
    """Position in the search path; lower shadows higher."""


#: Roots put in force by ``active.use``: searched whenever a caller names none,
#: so a ``--pack-root`` given once reaches every lookup the command makes.
CONTEXT_ROOTS: ContextVar[tuple[str, ...]] = ContextVar("worldloom_pack_roots", default=())


def search_path(roots: Sequence[str | Path] = ()) -> tuple[tuple[str, Path], ...]:
    out: list[tuple[str, Path]] = [("root", Path(root)) for root in (roots or CONTEXT_ROOTS.get())]
    out += [("env", Path(item)) for item in os.environ.get(ENV_PATH, "").split(os.pathsep) if item]
    out.append(("user", user_root()))
    out.append(("builtin", builtin_root()))
    return tuple(out)


def _read(location: Path) -> PackEnvelope:
    if location.is_dir():
        envelope = read_envelope(location / "pack.json")
        body = dict(envelope.body)
        from .resolve import merge

        for fragment in sorted(location.glob("*.json")):
            if fragment.name == "pack.json":
                continue
            data = json.loads(fragment.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"{fragment}: a body fragment is a JSON object")
            body = merge(body, data)
        return envelope.model_copy(update={"body": body})
    return read_envelope(location)


def _candidates(root: Path, kind: str) -> Iterator[tuple[str, Path]]:
    directory = root / kind
    if not directory.is_dir():
        return
    for entry in sorted(directory.iterdir()):
        name = entry.stem if entry.suffix == ".json" else entry.name
        if (entry.is_file() and entry.suffix == ".json") or (entry.is_dir() and (entry / "pack.json").is_file()):
            if NAME.match(name):
                yield name, entry


def find(kind: str, name: str, *, roots: Sequence[str | Path] = (), below: int = -1) -> Located | None:
    """The highest-precedence pack ``kind:name`` ranked after *below*, or ``None``."""
    for rank, (origin, root) in enumerate(search_path(roots)):
        if rank <= below:
            continue
        for found, location in _candidates(root, kind):
            if found == name:
                envelope = _read(location)
                if envelope.kind != kind or envelope.name != name:
                    raise ValueError(f"{location} declares {envelope.ref()}, but is stored as {kind}:{name}")
                return Located(envelope, origin, location, rank)
    return None


def discover(kind: str | None = None, *, roots: Sequence[str | Path] = ()) -> list[Located]:
    """Every visible pack (shadowed ones omitted), by kind then name."""
    from .kinds import kinds

    wanted = [kind] if kind else [k.name for k in kinds()]
    seen: dict[tuple[str, str], Located] = {}
    for rank, (origin, root) in enumerate(search_path(roots)):
        for key in wanted:
            for name, location in _candidates(root, key):
                if (key, name) not in seen:
                    seen[(key, name)] = Located(_read(location), origin, location, rank)
    return [seen[key] for key in sorted(seen)]


def write(envelope: PackEnvelope, root: Path) -> Path:
    """Store *envelope* as ``<root>/<kind>/<name>.json``; the caller has linted it."""
    target = root / envelope.kind / f"{envelope.name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_suffix(".json.pending")
    staging.write_text(json.dumps(envelope.dump(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    staging.replace(target)
    return target


def as_data(located: Located) -> dict[str, Any]:
    return {"ref": located.envelope.ref(), "kind": located.envelope.kind, "name": located.envelope.name,
            "version": located.envelope.version, "title": located.envelope.title,
            "description": located.envelope.description, "extends": list(located.envelope.extends),
            "origin": located.origin, "location": str(located.location)}


__all__ = ["ENV_HOME", "ENV_PATH", "Located", "as_data", "builtin_root", "discover", "find", "search_path",
           "user_root", "write"]
