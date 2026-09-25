"""Stable hashable keys for connector idempotency and deduplication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias

FrozenKey: TypeAlias = str | int | float | bool | tuple["FrozenKey", ...] | None

# ---------------------------------------------------------------------------
# Identity keys: which payload keys name a record, in one place
# ---------------------------------------------------------------------------

#: The keys a product-shaped payload carries a record's handle under, in the
#: order the emulator indexes them (the first one a record carries wins a
#: collision). ServiceNow answers with ``sys_id`` and ``number``, Salesforce
#: with ``Id``, Slack with ``ts``, Jira with ``key`` beside ``id``, the
#: Atlassian graph with ``ari``.
SHAPED_IDENTITY_KEYS: tuple[str, ...] = ("id", "Id", "sys_id", "key", "number", "ts", "ari")

#: What ``shape_payload`` keeps under a field projection whatever was asked
#: for: every handle, plus the two non-scalar envelope keys (Salesforce's
#: ``attributes``, the object ``type``) a product always returns.
PAYLOAD_IDENTITY_KEYS: frozenset[str] = frozenset((*SHAPED_IDENTITY_KEYS, "attributes", "type"))

#: The keys ``connectors.serving`` reads a recorded result's native handle
#: from, to map it back to the fid it answered for. Not the handle set above:
#: it adds ``name`` and ``title`` (a file or page is addressed by them) and
#: has never read ``ts`` or ``ari``, so a Slack or graph handle in a recorded
#: result is not aliased. Kept as it is, deliberately: the map is read only
#: where ``emulator.by_ident`` no longer knows an id, which is after a delete
#: (``_op_delete`` drops the record's idents). Adding ``ts``/``ari`` can turn
#: a Slack message or thread, or a Rovo/Teamwork Graph object, read back or
#: re-addressed by its handle after its deletion from an unattributed call
#: into an attributed one, which changes the plan and trajectory grade of
#: every recorded run that did so; and because the map is ``setdefault``, a
#: ``ts`` equal to a later entry's ``name`` or ``title`` would take that key
#: from it. Widening it is a grading change to version, not a gap to close.
RECORDED_ALIAS_KEYS: tuple[str, ...] = ("id", "Id", "sys_id", "key", "number", "name", "title")

#: The stable-identifier fields a ``missing_stable_id`` fixture strips from a
#: source record: every ``EntitySpec.stable_id`` the first eight builtin specs
#: name, plus the generic ``stable_id``. The system-of-record ``ident``, and the
#: ``ts``/``ari`` handles of the connectors added later, are not stripped.
STABLE_ID_FIELDS: tuple[str, ...] = ("stable_id", "key", "sys_id", "id", "page_id", "item_id", "file_id",
                                     "message_id", "thread_id")


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


__all__ = ["PAYLOAD_IDENTITY_KEYS", "RECORDED_ALIAS_KEYS", "SHAPED_IDENTITY_KEYS", "STABLE_ID_FIELDS", "FrozenKey",
           "freeze_key"]
