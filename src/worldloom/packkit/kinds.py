"""What a pack can be: one registration per kind, the same machinery for all.

A *kind* names a layer of the product that a pack may supply: the industry's
language, the prompts a harness reads, the numeric policy a compile runs
under, a company, a connector, a line of business, a document type, a
presentation profile. Each kind registers once, with

- the model its body validates against (frozen, ``extra="forbid"``, so a
  misspelled field is a refusal rather than a silently dropped knob),
- a lint returning every finding a reviser can act on (``cascade``'s rule),
- how an ``extends`` chain merges (deep by default), and
- what an interview asks when a harness authors one.

Nothing else is per kind. Discovery, layering, content addressing, the
active-pack context, upload, and the harness interview are the kernel's, so a
new kind is a registration and a default body, never a new loader.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..cascade import Finding

#: A lint: the validated body, and the resolved packs it may be checked
#: against (the default of the same kind, for override checks). Returns every
#: finding, never the first.
Lint = Callable[[Any, "LintContext"], list[Finding]]


@dataclass(frozen=True)
class LintContext:
    """What a lint may consult beyond the body itself.

    ``default`` is the kind's resolved default body when the kind has one, so
    an override can be checked against the keys and placeholders it overrides.
    ``resolve`` resolves another pack by reference (``prompts:default``), for
    kinds that point at others.
    """

    kind: str
    name: str
    default: Any = None
    resolve: Callable[[str], Any] | None = None


@dataclass(frozen=True)
class PackKind:
    """One layer a pack can supply."""

    name: str
    """The kind's key, as written in an envelope's ``kind`` and a reference's
    ``kind:name``."""
    model: type[BaseModel]
    """The body's model. Validated after the ``extends`` chain is merged, so a
    child pack may state only what it changes."""
    about: str
    """One paragraph for a person or a harness: what this layer controls."""
    lint: Lint | None = None
    default: str | None = "default"
    """The name of the pack every other pack of this kind implicitly layers on,
    or ``None`` for a kind with no shipped default (a company is authored whole)."""
    asks: tuple[str, ...] = ()
    """Kind-specific interview instructions, beyond the kernel's own."""
    merge_keys: Mapping[str, str] = field(default_factory=dict)
    """Lists merged by a key field rather than replaced, by JSON path
    (``"lobs": "name"``). Unlisted lists replace, which is the safe default:
    a merged list cannot express removal."""
    load: Callable[[Mapping[str, Any]], Any] | None = None
    """How a merged body becomes a model, when validation is not enough (a
    kind wrapping an existing loader). ``model.model_validate`` otherwise."""


_KINDS: dict[str, PackKind] = {}


def register_kind(kind: PackKind) -> PackKind:
    """Register *kind*; a second registration of the same name must be identical.

    Refusing a divergent redefinition rather than letting the last import win,
    because two modules disagreeing about what a kind means is a bug that a
    silent overwrite would turn into whichever import ran last.
    """
    held = _KINDS.get(kind.name)
    if held is not None and held != kind:
        raise ValueError(f"pack kind {kind.name!r} is already registered differently")
    _KINDS[kind.name] = kind
    return kind


def kind(name: str) -> PackKind:
    from . import builtin

    builtin.install()
    try:
        return _KINDS[name]
    except KeyError:
        raise KeyError(f"unknown pack kind {name!r}; registered kinds: {', '.join(sorted(_KINDS))}") from None


def kinds() -> tuple[PackKind, ...]:
    from . import builtin

    builtin.install()
    return tuple(_KINDS[key] for key in sorted(_KINDS))


__all__ = ["Lint", "LintContext", "PackKind", "kind", "kinds", "register_kind"]
