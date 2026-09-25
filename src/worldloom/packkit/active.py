"""Which packs are in force, and the three calls the rest of the code makes.

Code never opens a pack file. It asks:

- ``text("studio.interview.role")`` for a prompt, instruction or sentence,
  from the active prompts pack, overridden by the active industry, with the
  industry's ``{{term:…}}`` words filled in;
- ``policy("studio.pool_size")`` for a default a run is governed by;
- ``terms()`` / ``term("site")`` for a word the industry says differently.

Which packs are in force is a context (``use``), not an argument threaded
through every call: a CLI flag, a Studio project or a recipe opens one around
the work it governs, and everything underneath reads the same packs. Outside
any ``use`` the kind's default pack is in force, and the default packs hold
exactly the literals the code held, so a build that names no pack is
byte-identical to one made before packs existed.

A pack that changes what a seed generates must replay without its file:
``recorded()`` is what a recipe stores (reference, digest and merged body of
every non-default pack in force) and ``use_recorded`` reinstates it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ..providers import digest
from .kinds import kind, kinds
from .models import PLACEHOLDER, IndustryPack, PolicyPack, PromptsPack
from .resolve import ResolvedPack, resolve
from .sources import CONTEXT_ROOTS as _ROOTS
from .terms import fill_terms
from .terms import term as _term

_ACTIVE: ContextVar[Mapping[str, ResolvedPack] | None] = ContextVar("worldloom_active_packs", default=None)
_DEFAULTS: dict[tuple[str, tuple[str, ...]], ResolvedPack] = {}


def roots() -> tuple[str, ...]:
    return _ROOTS.get()


@contextmanager
def use(*refs: str | Path | ResolvedPack | None, roots: Sequence[str | Path] = ()) -> Iterator[Mapping[str, ResolvedPack]]:
    """Put packs in force for the enclosed work, on top of any already in force.

    ``None`` entries are skipped, so a caller passes an optional flag straight
    through. Two packs of one kind in one call is a refusal: which one wins
    would otherwise be argument order.
    """
    root_tuple = tuple(str(r) for r in roots) or _ROOTS.get()
    chosen: dict[str, ResolvedPack] = {}
    for ref in refs:
        if ref is None:
            continue
        pack = ref if isinstance(ref, ResolvedPack) else resolve(ref, roots=root_tuple)
        if pack.kind in chosen:
            raise ValueError(f"two {pack.kind} packs in one use(): {chosen[pack.kind].ref} and {pack.ref}")
        chosen[pack.kind] = pack
    token = _ACTIVE.set({**(_ACTIVE.get() or {}), **chosen})
    root_token = _ROOTS.set(root_tuple)
    try:
        yield _ACTIVE.get() or {}
    finally:
        _ACTIVE.reset(token)
        _ROOTS.reset(root_token)


def active(kind_name: str) -> ResolvedPack | None:
    """The pack of *kind_name* in force, else the kind's default, else ``None``."""
    held = (_ACTIVE.get() or {}).get(kind_name)
    if held is not None:
        return held
    default = kind(kind_name).default
    if default is None:
        return None
    key = (kind_name, _ROOTS.get())
    if key not in _DEFAULTS:
        _DEFAULTS[key] = resolve(f"{kind_name}:{default}", roots=_ROOTS.get())
    return _DEFAULTS[key]


def forget_defaults() -> None:
    _DEFAULTS.clear()


def customised_defaults() -> dict[str, str]:
    """Each kind whose default in force is not the shipped one, to that default's digest.

    A user's ``~/.worldloom/packs/prompts/default.json`` (or a root's)
    changes what every build under it produces without anyone naming it, so
    whatever keys work by identity (a Studio snapshot, a recipe) has to count
    it. Empty on a machine that only has the shipped defaults.
    """
    out: dict[str, str] = {}
    for pack_kind in kinds():
        if pack_kind.default is None:
            continue
        pack = active_default(pack_kind.name)
        if pack is not None and not pack.is_default:
            out[pack_kind.name] = pack.digest
    return out


def active_default(kind_name: str) -> ResolvedPack | None:
    """The kind's default as the search path resolves it, ignoring what ``use`` put in force."""
    token = _ACTIVE.set({})
    try:
        return active(kind_name)
    finally:
        _ACTIVE.reset(token)


def industry() -> IndustryPack:
    pack = active("industry")
    assert pack is not None
    body: IndustryPack = pack.body
    return body


def terms() -> dict[str, str]:
    """The colloquial vocabulary in force."""
    return dict(industry().terms)


def term(token: str) -> str:
    """One word in force: ``term("site")``, ``term("Sites")``."""
    return _term(token, industry().terms)


def template(key: str) -> str:
    """The prompt or sentence *key*, with the industry's terms filled and caller placeholders left.

    Callers that already ``.format(...)`` a template keep doing so; the
    returned string is today's literal whenever no pack changed it.
    """
    pack = active("prompts")
    assert pack is not None
    prompts: PromptsPack = pack.body
    chosen = industry().prompts.get(key)
    if chosen is None:
        try:
            chosen = prompts.texts[key]
        except KeyError:
            raise KeyError(f"no prompt {key!r} in {pack.ref}; the shipped keys are listed by "
                           "`worldloom pack show prompts:default`") from None
    return fill_terms(chosen, industry().terms)


def text(key: str, /, **values: Any) -> str:
    """*key*'s template with ``{name}`` placeholders filled from *values*.

    Only the placeholders named in *values* are replaced, and nothing else in
    the text is interpreted, so a template may contain JSON, ``{{fact:ID}}``
    examples or a literal brace without escaping.
    """
    out = template(key)
    if not values:
        return out
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), out)


def texts(prefix: str) -> list[str]:
    """Every text whose key starts with *prefix*, in key order, filled: for instruction lists."""
    pack = active("prompts")
    assert pack is not None
    prompts: PromptsPack = pack.body
    keys = sorted({k for k in prompts.texts if k.startswith(prefix)} | {k for k in industry().prompts if k.startswith(prefix)})
    return [template(k) for k in keys]


def policy(key: str) -> Any:
    """The policy value *key* in force: the industry's override, else the policy pack's."""
    overrides = industry().policy
    if key in overrides:
        return overrides[key]
    pack = active("policy")
    assert pack is not None
    values: PolicyPack = pack.body
    try:
        return values.values[key]
    except KeyError:
        raise KeyError(f"no policy {key!r} in {pack.ref}") from None


def recorded() -> dict[str, dict[str, Any]]:
    """Every non-default pack in force, as a recipe stores it (empty when none is).

    Empty for a default build, so a recipe written before packs existed and
    one written by a build that names no pack are the same recipe.
    """
    in_force: dict[str, ResolvedPack] = dict(_ACTIVE.get() or {})
    for pack_kind in kinds():
        # A customised default is in force without anyone naming it; it is
        # recorded like a named pack so the corpus replays where it is absent.
        if pack_kind.default is not None and pack_kind.name not in in_force:
            pack = active(pack_kind.name)
            if pack is not None:
                in_force[pack_kind.name] = pack
    out: dict[str, dict[str, Any]] = {}
    for kind_name, pack in sorted(in_force.items()):
        if pack.is_default:
            continue
        out[kind_name] = {"ref": pack.ref, "digest": pack.digest, "chain": list(pack.chain), "body": pack.data}
    return out


@contextmanager
def use_recorded(record: Mapping[str, Mapping[str, Any]] | None) -> Iterator[None]:
    """Reinstate what ``recorded`` stored, from the stored bodies alone (no files)."""
    if not record:
        yield
        return
    packs: list[ResolvedPack] = []
    for kind_name, entry in sorted(record.items()):
        pack_kind = kind(kind_name)
        data = dict(entry["body"])
        body = pack_kind.load(data) if pack_kind.load is not None else pack_kind.model.model_validate(data)
        name = str(entry["ref"]).split(":", 1)[1]
        stored = digest({"kind": kind_name, "name": name, "body": data})
        if stored != entry["digest"]:
            raise ValueError(f"recorded {kind_name} pack {entry['ref']} does not match its digest; the recipe was edited")
        packs.append(ResolvedPack(kind=kind_name, name=name, body=body, data=data, digest=stored,
                                  chain=tuple(entry.get("chain", ())), origin="recipe"))
    with use(*packs):
        yield


__all__ = ["active", "active_default", "customised_defaults", "forget_defaults", "industry", "policy", "recorded", "roots", "term", "template", "terms",
           "text", "texts", "use", "use_recorded"]
