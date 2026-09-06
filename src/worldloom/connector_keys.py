"""Stable hashable keys for connector idempotency and deduplication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias

FrozenKey: TypeAlias = str | int | float | bool | None | tuple["FrozenKey", ...]


def freeze_key(value: Any) -> FrozenKey:
    """Convert JSON-like connector values into deterministic hashable values.

    Product idempotency keys routinely include recipient/member arrays or small
    objects. The emulator must compare those structurally rather than assuming
    every connector field is already hashable.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return tuple(
            (str(key), freeze_key(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_key(item) for item in value)
    return str(value)


__all__ = ["FrozenKey", "freeze_key"]
