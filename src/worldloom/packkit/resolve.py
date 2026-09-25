"""A reference becomes one validated, content-addressed body.

Resolution walks the ``extends`` chain depth first, merges the bodies from the
root of the chain to the pack itself, and validates the result against the
kind's model. Every non-default pack implicitly layers on its kind's default,
so a pack states only what differs: an industry pack that renames a site to a
branch is one line, and everything it does not mention keeps the shipped value.

Merge is deep for mappings; a list replaces unless the kind names a key to
merge it by; ``null`` removes a key. The digest is over the kind, the name and
the merged body, so two packs that resolve to the same thing are the same pack
wherever their files live, and a pinned reference (``kind:name@digest``)
refuses a pack whose content moved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..providers import digest
from .envelope import PackEnvelope, parse_ref, read_envelope
from .kinds import LintContext, PackKind, kind
from .sources import Located, find

MAX_DEPTH = 16


def merge(base: Any, over: Any, *, keys: Mapping[str, str] | None = None, path: str = "") -> Any:
    """*over* merged onto *base*: deep for mappings, replacing otherwise."""
    if isinstance(base, Mapping) and isinstance(over, Mapping):
        out = dict(base)
        for key, value in over.items():
            child = f"{path}.{key}" if path else str(key)
            if value is None:
                out.pop(key, None)
            elif key in out:
                out[key] = merge(out[key], value, keys=keys, path=child)
            else:
                out[key] = value
        return out
    field = (keys or {}).get(path)
    if field and isinstance(base, list) and isinstance(over, list):
        index = {item.get(field): position for position, item in enumerate(base) if isinstance(item, Mapping)}
        out_list = list(base)
        for item in over:
            at = index.get(item.get(field)) if isinstance(item, Mapping) else None
            if at is None:
                out_list.append(item)
            else:
                out_list[at] = merge(out_list[at], item, keys=keys, path=path)
        return out_list
    return over


@dataclass(frozen=True)
class ResolvedPack:
    """A pack ready to use: its validated body and how it came to be."""

    kind: str
    name: str
    body: Any
    """The kind's model instance."""
    data: dict[str, Any]
    """The merged body as JSON, which is what the digest and a recipe carry."""
    digest: str
    chain: tuple[str, ...]
    """The references merged, root first: ``("industry:default", "industry:healthcare")``."""
    origin: str
    title: str = ""
    description: str = ""

    @property
    def ref(self) -> str:
        return f"{self.kind}:{self.name}"

    @property
    def pinned(self) -> str:
        return f"{self.ref}@{self.digest}"

    @property
    def is_default(self) -> bool:
        """The shipped default, and only that one.

        A pack named ``default`` in a user or project root is a customisation
        like any other: it changes output, so it is recorded, linted against
        the shipped default and keyed by its digest. Judging by name alone let
        one change every build on a machine with nothing in the recipe to say so.
        """
        return self.name == kind(self.kind).default and self.origin == "builtin"


def _validate(pack_kind: PackKind, data: Mapping[str, Any]) -> BaseModel:
    if pack_kind.load is not None:
        return pack_kind.load(data)  # type: ignore[no-any-return]
    return pack_kind.model.model_validate(dict(data))


def _chain(envelope: PackEnvelope, located: Located | None, roots: Sequence[str | Path],
           depth: int, seen: tuple[str, ...]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """The merged body of *envelope* and everything below it, with the refs merged."""
    if depth > MAX_DEPTH:
        raise ValueError(f"pack {envelope.ref()} extends more than {MAX_DEPTH} levels deep")
    pack_kind = kind(envelope.kind)
    parents = list(envelope.extends)
    shipped_default = (located is not None and located.origin == "builtin"
                       and envelope.name == pack_kind.default)
    if pack_kind.default and not parents and not shipped_default:
        # Every pack layers on the default; a default outside the shipped root
        # layers on the one it shadows, so it states only what it changes.
        parents = [f"{envelope.kind}:{pack_kind.default}"]
    body: dict[str, Any] = {}
    chain: tuple[str, ...] = ()
    for parent in parents:
        ref = parse_ref(parent, kind=envelope.kind)
        if ref.path is not None:
            raise ValueError(f"pack {envelope.ref()} extends a file ({parent}); extend a kind:name so it replays")
        key = f"{ref.kind}:{ref.name}"
        below = -1
        if key == envelope.ref():
            # A pack extending its own name reaches the one it shadows: below
            # where it is stored, or, for a pack not stored yet (an upload, a
            # proposal, a file), the highest one of that name.
            below = located.rank if located is not None else -1
        elif key in seen:
            raise ValueError(f"pack {envelope.ref()} extends {key}, which extends it back")
        found = find(str(ref.kind), str(ref.name), roots=roots, below=below)
        if found is None:
            raise ValueError(f"pack {envelope.ref()} extends {parent}, which no pack root holds")
        parent_body, parent_chain = _chain(found.envelope, found, roots, depth + 1, (*seen, key))
        if ref.pin and digest({"kind": ref.kind, "name": ref.name, "body": parent_body}) != ref.pin:
            raise ValueError(f"pack {envelope.ref()} pins {parent}, whose content has changed")
        body = merge(body, parent_body, keys=pack_kind.merge_keys)
        chain += tuple(item for item in parent_chain if item not in chain)
    body = merge(body, envelope.body, keys=pack_kind.merge_keys)
    return body, (*chain, envelope.ref())


def resolve_envelope(envelope: PackEnvelope, *, roots: Sequence[str | Path] = (),
                     located: Located | None = None) -> ResolvedPack:
    """Resolve an envelope that is not (yet) stored anywhere: an upload or a proposal."""
    pack_kind = kind(envelope.kind)
    data, chain = _chain(envelope, located, roots, 0, (envelope.ref(),))
    try:
        body = _validate(pack_kind, data)
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(str(p) for p in item['loc']) or 'body'}: {item['msg']}"
                             for item in error.errors()[:8])
        raise ValueError(f"pack {envelope.ref()} does not fit the {pack_kind.name} model: {problems}") from None
    return ResolvedPack(kind=envelope.kind, name=envelope.name, body=body, data=data,
                        digest=digest({"kind": envelope.kind, "name": envelope.name, "body": data}),
                        chain=chain, origin=located.origin if located else "proposed",
                        title=envelope.title, description=envelope.description)


_CACHE: dict[tuple[str, tuple[str, ...]], tuple[tuple[Any, ...], ResolvedPack]] = {}


def _signature(roots: Sequence[str | Path]) -> tuple[Any, ...]:
    """Cheap change detection over the search path: each root's pack files and mtimes."""
    from .sources import search_path

    out: list[Any] = []
    for _, root in search_path(roots):
        if root.is_dir():
            out.extend((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(root.rglob("*.json")))
    return tuple(out)


def resolve(ref: str | Path, *, kind_name: str | None = None, roots: Sequence[str | Path] = ()) -> ResolvedPack:
    """Resolve a reference (``kind:name[@pin]``, a bare name with *kind_name*, or a path)."""
    from .sources import CONTEXT_ROOTS

    roots = tuple(roots) or CONTEXT_ROOTS.get()
    parsed = parse_ref(ref, kind=kind_name)
    root_key = tuple(str(r) for r in roots)
    signature = _signature(roots)
    cache_key = (str(parsed), root_key)
    held = _CACHE.get(cache_key)
    if held is not None and held[0] == signature:
        return held[1]
    if parsed.path is not None:
        envelope = read_envelope(Path(parsed.path))
        if kind_name is not None and envelope.kind != kind_name:
            raise ValueError(f"{parsed.path} is a {envelope.kind!r} pack; a {kind_name!r} pack is required here")
        resolved = resolve_envelope(envelope, roots=roots)
        resolved = ResolvedPack(**{**resolved.__dict__, "origin": "file"})
    else:
        located = find(str(parsed.kind), str(parsed.name), roots=roots)
        if located is None:
            raise KeyError(f"no pack {parsed.kind}:{parsed.name} in any pack root; `worldloom pack list {parsed.kind}` shows what is visible")
        resolved = resolve_envelope(located.envelope, roots=roots, located=located)
    if parsed.pin and parsed.pin != resolved.digest:
        raise ValueError(f"pack {parsed.kind}:{parsed.name} is pinned to {parsed.pin} but resolves to {resolved.digest}; its content changed")
    _CACHE[cache_key] = (signature, resolved)
    return resolved


def lint(resolved: ResolvedPack, *, roots: Sequence[str | Path] = ()) -> list[str]:
    """Every finding the kind's lint returns for *resolved*, against its default."""
    pack_kind = kind(resolved.kind)
    if pack_kind.lint is None:
        return []
    default = None
    if pack_kind.default:
        if resolved.name != pack_kind.default:
            default = resolve(f"{resolved.kind}:{pack_kind.default}", roots=roots).body
        elif not resolved.is_default:
            # A customised default is checked against the shipped one it shadows.
            default = shipped(resolved.kind).body
    context = LintContext(kind=resolved.kind, name=resolved.name, default=default,
                          resolve=lambda ref: resolve(ref, roots=roots).body)
    return list(pack_kind.lint(resolved.body, context))


def shipped(kind_name: str) -> ResolvedPack:
    """The kind's default exactly as shipped, whatever shadows it."""
    from .sources import search_path

    pack_kind = kind(kind_name)
    if pack_kind.default is None:
        raise KeyError(f"pack kind {kind_name!r} ships no default")
    path = search_path(())
    found = find(kind_name, pack_kind.default, below=len(path) - 2)
    if found is None or found.origin != "builtin":
        raise KeyError(f"no shipped {kind_name}:{pack_kind.default}")
    return resolve_envelope(found.envelope, located=found)


def refresh() -> None:
    """Forget cached resolutions and defaults (after an upload, or a test writing packs).

    A process that installs a pack refreshes itself; one that merely reads
    packs another process changed on disk sees the change on its next
    uncached resolution, and a default it already resolved on restart.
    """
    from .active import forget_defaults

    _CACHE.clear()
    forget_defaults()


__all__ = ["MAX_DEPTH", "ResolvedPack", "lint", "merge", "refresh", "resolve", "resolve_envelope", "shipped"]
