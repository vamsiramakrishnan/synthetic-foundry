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
    world: type[Any]
    """The world builder — ``RetailWorld``, ``BankingWorld`` — accepting
    ``(seed, archetype, employees, annual_revenue)`` keyword arguments."""
    single_episode: Callable[[str], Any] | None = None
    """``period -> scenario`` for a domain whose build runs exactly one
    episode. ``None`` for retail, whose close loop the CLI drives itself."""
    period_step_months: int = 1
    """How many months apart consecutive ``--periods`` runs land for a
    single-episode domain. Core, not banking, is what ``cli.py`` may name —
    the thin-waist ratchet test forbids "quarter" in core code — so the
    stepping arithmetic is generic and each domain states its own cadence
    here; banking registers 3."""
    max_periods: int | None = None
    """The most consecutive runs this domain's built-in episode supports, or
    ``None`` for no limit.

    Declared rather than discovered by crashing, which is what this replaced.
    One shipped domain's episode raises on a second consecutive run because the
    half of it that supersedes the first run's estimates is unimplemented — and
    that refusal lived only inside the scenario, so the single thing a *planner*
    needed to know was reachable only by building a corpus and reading a
    traceback. ``tools/sweep.py`` responded the way anything would: it collapsed
    ``--periods`` to 1 for **every** single-episode domain, citing a CLI refusal
    that no longer exists.

    The cost of that was measured, not theoretical. Two of the three
    single-episode domains build and validate clean at three and four
    consecutive runs — between 2,672 and 5,525 checks — and the determinism
    sweep has never once compared two builds of either beyond a single period,
    which is precisely where a carry-forward defect would live.

    The scenario still enforces its own limit; this is the declaration that lets
    a planner read it, and it is the domain's to state for the same reason
    ``period_step_months`` is. A domain that raises without declaring is the bug
    this field exists to make impossible to reintroduce quietly."""
    default_archetype: str = ""
    """Which of ``archetype_keys`` this domain builds when a caller names the
    *domain* rather than an archetype — what ``worldloom mosaic --engine`` picks.

    Stated by the domain for the same reason ``period_step_months`` is: core is
    forbidden from naming a vertical, so it cannot hold a map from a domain's
    name to one of its archetype keys. Deriving it instead — the lowest sorted
    key, say — would silently pick whichever archetype happens to sort first,
    which for a domain owning more than one is not the one it builds by
    default, and nothing would say that had happened."""

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
    """The domain that owns *key*, or ``None`` for an unclaimed archetype.

    A key may be qualified with a vocabulary (``"midsize_adi+mutual_bank"`` —
    see ``worldloom.vocabulary``), and the qualifier is stripped before the
    lookup because it names *words*, not a vertical: a bank that calls its
    divisions Member Banking and Community Business is still built by the
    banking engine. Stripping here rather than at each call site is what keeps
    ``Domain.archetype_keys`` a set of shapes — a domain enumerating its
    archetypes crossed with every vocabulary would be a registry that grew when
    somebody added a name to a word list.
    """
    from .vocabulary import QUALIFIER

    base = key.partition(QUALIFIER)[0]
    for domain in _DOMAINS.values():
        if base in domain.archetype_keys:
            return domain
    return None


def by_name(name: str) -> Domain | None:
    """The domain registered as *name* — how a pack's ``base`` resolves."""
    return _DOMAINS.get(name)


def names() -> list[str]:
    """Every registered domain name."""
    return sorted(_DOMAINS)
