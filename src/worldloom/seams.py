"""Machine-readable Worldloom seams discovered from package code.

A seam opts in by defining ``__worldloom_seam__`` in its package ``__init__``.
There is no second registry to update.  Discovery first inspects package source
for that marker and imports only declared seams, preserving the CLI startup
budget for unrelated commands.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from importlib.resources import files
from typing import Any

SEAMS_SCHEMA = "worldloom.seams/v1"
_MARKER = "__worldloom_seam__"


def _declared_packages() -> tuple[str, ...]:
    root = files("worldloom")
    names: list[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        init = child.joinpath("__init__.py")
        if not init.is_file():
            continue
        try:
            source = init.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _MARKER in source:
            names.append(child.name)
    return tuple(sorted(names))


def seam_manifest() -> dict[str, Any]:
    """Return every declared seam and its live generated contract."""

    seams: list[dict[str, Any]] = []
    for package in _declared_packages():
        module = importlib.import_module(f"worldloom.{package}")
        marker = getattr(module, _MARKER, None)
        if not isinstance(marker, dict):
            raise TypeError(f"worldloom.{package} declares an invalid seam marker")
        describe = getattr(module, "seam_contract", None)
        contract = describe() if callable(describe) else {}
        seams.append({**marker, "contract": contract})
    payload: dict[str, Any] = {
        "schema": SEAMS_SCHEMA,
        "seams": seams,
    }
    payload["digest"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return payload


__all__ = ["SEAMS_SCHEMA", "seam_manifest"]
