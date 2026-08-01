"""The domain registry: which world builds an archetype, and what a build runs.

The fourth registration seam, beside the validator check groups, the artifact
types, and the archetypes themselves. Before it existed, two places in core
named banking explicitly — the CLI's build dispatch and the recipe rebuilder —
which meant a third vertical would edit core twice for pure bookkeeping. Now a
domain module registers once, at import, and both callers resolve through the
archetype key.

Registration happens at package import (``worldloom/__init__`` imports every
domain module) for the same reason the other seams demand it: a corpus whose
recipe can only be rebuilt in processes that happened to import the right
module is a corpus that rebuilds on some machines, and determinism that
depends on import order is not determinism.

``single_episode`` is deliberately narrow. A domain whose build is "construct
the world, run one episode for the period" describes itself with one callable.
Retail's build path is not that — it loops consecutive closes and threads
incident/comparatives/actor flags through them — and flattening those flags
into this interface would force every future domain to answer questions only
the close asks. So retail registers with ``single_episode=None`` and keeps its
bespoke CLI path; the generalisation, if a third vertical ever wants a
multi-episode build, gets designed against that vertical's real needs rather
than guessed here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Domain:
    """One vertical: its name, the archetypes it owns, and how it builds."""

    name: str
    archetype_keys: frozenset[str]
    world: type
    """The world builder — ``RetailWorld``, ``BankingWorld`` — accepting
    ``(seed, archetype, employees, annual_revenue)`` keyword arguments."""
    single_episode: Callable[[str], Any] | None = None
    """``period -> scenario`` for a domain whose build runs exactly one
    episode. ``None`` for retail, whose close loop the CLI drives itself."""
    consulted_targets: tuple[tuple[str, str], ...] = ()
    """The lore-constraint targets this engine's generators actually read,
    as ``(target, what it changes)`` pairs. Published so a pack author — human
    or agent — can see which lore is load-bearing and which would be carried
    but inert; ``worldloom pack check`` lints against this."""
    system_slots: tuple[tuple[str, str], ...] = ()
    """The engine's system slots a pack may re-brand, as ``(slot, what the
    system is)`` pairs. Brands only — the concept each slot plays in the
    episode is the engine's."""
    role_keys: tuple[str, ...] = ()
    """The engine's fixed role keys, for voice overrides and persona-trait
    lore. Per-unit roles are derived from the pack's own unit keys plus
    ``unit_role_suffixes``."""
    unit_role_suffixes: tuple[str, ...] = ()
    """Suffixes of the roles minted per business unit (``_md`` everywhere;
    retail adds ``_bp`` and ``_buyer``)."""
    episode_text: tuple[tuple[str, str], ...] = ()
    """The engine's surface-text templates as ``(key, default)`` pairs — every
    event sentence and prose fact the episode states. A pack overrides by key
    through ``episode_text``; slots are checked against the default's."""
    evaluation_text: tuple[tuple[str, str], ...] = ()
    """The engine's evaluation-taxonomy templates as ``(key, default)``
    pairs — every question and authored answer the benchmark asks, the same
    seam as ``episode_text`` but over the evaluation set rather than the
    episode: a pack that re-voices the episode's narration but not its own
    benchmark still asks about "merchandise category" in an insurer's world.
    A pack overrides by key through ``evaluation_text``; slots are checked
    against the default's, exactly as ``episode_text``'s are."""


_DOMAINS: dict[str, Domain] = {}


def register_domain(domain: Domain) -> None:
    """Register a domain. Re-registering an equal domain is a harmless reload;
    two different domains under one name, or two domains claiming one
    archetype, would make a build's meaning depend on import order — refused.
    """
    existing = _DOMAINS.get(domain.name)
    if existing is not None:
        if existing == domain:
            return
        raise ValueError(f"a different domain is already registered as {domain.name!r}")
    for other in _DOMAINS.values():
        claimed = other.archetype_keys & domain.archetype_keys
        if claimed:
            raise ValueError(
                f"archetype(s) {sorted(claimed)} already belong to domain {other.name!r}"
            )
    _DOMAINS[domain.name] = domain


def for_archetype(key: str) -> Domain | None:
    """The domain that owns *key*, or ``None`` for an unclaimed archetype."""
    for domain in _DOMAINS.values():
        if key in domain.archetype_keys:
            return domain
    return None


def by_name(name: str) -> Domain | None:
    """The domain registered as *name* — how a pack's ``base`` resolves."""
    return _DOMAINS.get(name)


def names() -> list[str]:
    """Every registered domain name."""
    return sorted(_DOMAINS)
