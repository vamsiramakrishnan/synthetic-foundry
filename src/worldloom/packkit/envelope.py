"""The one file format every pack shares, and how a pack is referred to.

    {
      "schema": "worldloom.pack/v1",
      "kind": "industry",
      "name": "healthcare",
      "version": "1",
      "title": "Hospital and health services",
      "description": "...",
      "extends": ["industry:default"],
      "body": { ...the kind's model... }
    }

A reference is ``kind:name`` (``industry:healthcare``), optionally pinned to a
content digest with ``@`` (``industry:healthcare@3f2a…``), or a path to an
envelope file. A pinned reference refuses a pack whose content changed, which
is how a recipe or a project names a pack it must replay exactly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from ..cascade import CascadeModel

SCHEMA = "worldloom.pack/v1"

#: A name is a key a file is stored under, so it is restricted to what every
#: filesystem accepts and nothing that can climb out of a directory.
NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


class PackEnvelope(CascadeModel):
    """A pack as written: identity, lineage, and an unvalidated body.

    The body stays a mapping here because it is only meaningful after its
    ``extends`` chain is merged; validating a child that states two fields
    against a model that requires ten would refuse every layered pack.
    """

    pack_schema: Literal["worldloom.pack/v1"] = Field(default="worldloom.pack/v1", alias="schema")
    kind: str
    name: str
    version: str = "1"
    title: str = ""
    description: str = ""
    extends: tuple[str, ...] = ()
    body: dict[str, Any] = Field(default_factory=dict)

    model_config = CascadeModel.model_config | {"populate_by_name": True}

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not NAME.match(value):
            raise ValueError(f"pack name {value!r} must be lower-case letters, digits, '.', '_' or '-' (at most 64)")
        return value

    def ref(self) -> str:
        return f"{self.kind}:{self.name}"

    def dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class PackRef(CascadeModel):
    """A parsed reference: a kind and name, a pin, or a file."""

    kind: str | None = None
    name: str | None = None
    pin: str | None = None
    path: str | None = None

    def __str__(self) -> str:
        if self.path is not None:
            return self.path
        return f"{self.kind}:{self.name}" + (f"@{self.pin}" if self.pin else "")


def parse_ref(ref: str | Path, *, kind: str | None = None) -> PackRef:
    """``kind:name[@pin]``, a bare ``name`` when *kind* is known, or a path.

    A string naming an existing file is a path whatever it looks like, so a
    pack saved as ``./industry:odd.json`` still loads; anything else must be a
    well-formed reference, and a malformed one is refused rather than guessed.
    """
    text = str(ref)
    if isinstance(ref, Path) or text.endswith(".json") or Path(text).is_file():
        return PackRef(path=text)
    head, _, pin = text.partition("@")
    ref_kind, sep, name = head.partition(":")
    if not sep:
        if kind is None:
            raise ValueError(f"pack reference {text!r} needs a kind: write kind:name")
        ref_kind, name = kind, head
    if kind is not None and ref_kind != kind:
        raise ValueError(f"pack reference {text!r} is a {ref_kind!r} pack; a {kind!r} pack is required here")
    if not NAME.match(name):
        raise ValueError(f"pack reference {text!r} has no valid name")
    return PackRef(kind=ref_kind, name=name, pin=pin or None)


def read_envelope(source: str | Path | dict[str, Any]) -> PackEnvelope:
    """An envelope from a path, JSON text or a mapping (``cascade.load``'s three forms)."""
    if isinstance(source, dict):
        data = source
    elif isinstance(source, Path) or Path(str(source)).is_file():
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        data = json.loads(str(source))
    if not isinstance(data, dict):
        raise ValueError("a pack is a JSON object")
    return PackEnvelope.model_validate(data)


__all__ = ["NAME", "SCHEMA", "PackEnvelope", "PackRef", "parse_ref", "read_envelope"]
