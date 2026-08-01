"""Deterministic identifiers.

Every entity, fact, event, artifact, and evaluation case carries a stable ID.
IDs are part of the corpus contract: an evaluation case cites fact IDs, an
artifact cites the facts that justify it, and a world regenerated from the same
seed must mint the same IDs in the same order.

Two ways to get an ID:

``format_id``
    Hand-assigned, for the golden episode fixture. ``format_id("FACT", 42)``.

``Minter``
    Deterministic minting for generated worlds. Sequence per prefix, seeded, so
    the *n*-th fact of a run is always ``FACT-<n>``. No randomness, no clock, no
    UUIDs — those would break replay.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# Prefix is the first segment only, so ``ART-SNOW-001`` is an ``ART`` whose
# suffix happens to be compound. Reference checks compare on the prefix, and a
# renderer-specific suffix must not change what kind of thing an ID names.
ID_PATTERN = re.compile(r"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<suffix>[A-Z0-9]+(?:-[A-Z0-9]+)*)$")

#: Prefixes reserved by the core model. Domain packs may add their own.
CORE_PREFIXES = frozenset(
    {
        "CO",  # company
        "BU",  # business unit
        "PERSON",
        "TEAM",
        "SYS",  # system of record
        "SVC",  # runtime service
        "CC",  # cost centre
        "CAT",  # merchandise category
        "SITE",  # store or distribution centre
        "PERSONA",
        "LORE",
        "FACT",
        "EV",  # event
        "ART",  # artifact
        "EVAL",
        "POLICY",
        "ERR",  # intentional error
        "GEN",  # generation ledger entry
        # The actor layer. Separate prefixes rather than reusing "EV"/"FACT"
        # because these are records *about* the world's records — who knew a
        # fact, who was told one — and an id that cannot be told apart from the
        # thing it describes is one that will eventually be.
        "OBS",  # epistemic observation: one person learning one fact
        "AOBS",  # the bounded projection handed to one actor
        "INV",  # actor invocation
        "MSG",  # message between employees
        "TASK",  # obligation
        "ALOG",  # execution ledger entry
    }
)


def format_id(prefix: str, number: int, *, width: int = 4) -> str:
    """Format a zero-padded identifier: ``format_id("FACT", 42) -> 'FACT-0042'``."""
    if number < 0:
        raise ValueError(f"id number must be non-negative, got {number}")
    return f"{prefix}-{number:0{width}d}"


def parse_id(value: str) -> tuple[str, str]:
    """Split an identifier into ``(prefix, suffix)``.

    Raises ``ValueError`` if the value is not a well-formed identifier. Used by
    the validator to check that every reference points at the right *kind* of
    thing — a fact referencing ``PERSON-0003`` where a service belongs is a
    coherence bug, and it should be caught by shape before it is caught by
    lookup.
    """
    match = ID_PATTERN.match(value)
    if not match:
        raise ValueError(f"malformed identifier: {value!r}")
    return match.group("prefix"), match.group("suffix")


def id_prefix(value: str) -> str:
    """Return just the prefix of an identifier."""
    return parse_id(value)[0]


def is_id(value: str) -> bool:
    """Whether *value* is a well-formed identifier."""
    return bool(ID_PATTERN.match(value))


def highest_numeric_suffix(prefix: str, ids: Iterable[str]) -> int:
    """The largest ``<prefix>-<digits>`` suffix among *ids*, or 0 if none.

    Ignores any id sharing *prefix* whose suffix is not a bare number, rather
    than raising on it — a scratch id minted by a different scheme under the
    same prefix (a narration checkpoint's ``GEN-CKPT-<hex>``, see
    ``narrative/compiler.py``; a foreign provider's ledger entry, see
    ``test_foreign_ledger_entries_are_harmless_to_replay``) must not stop a
    legitimate sequence from continuing, or worse, crash it.

    Used wherever an id sequence has to keep counting across independent
    calls rather than being minted whole by one ``Minter`` from a single seed:
    ``compiler.narrate``'s ``GEN`` sequence and ``compiler/handshake.py``'s
    plan ``accept()`` both grow a ledger that may already carry ids from an
    earlier, separate pass — restarting either at 1 would mint an id some
    already-recorded entry owns.
    """
    highest = 0
    needle = f"{prefix}-"
    for value in ids:
        if not value.startswith(needle):
            continue
        suffix = value.rsplit("-", 1)[1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest


def content_key(*parts: object) -> str:
    """A stable content-addressed key for the generation ledger.

    Deliberately not ``hash()`` — Python's string hash is randomised per process,
    which would make ledger keys differ between runs and defeat replay. See
    ``docs/generation-model.md`` for the ledger contract.
    """
    joined = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


@dataclass
class Minter:
    """Deterministic per-prefix ID sequences.

    Order of calls determines IDs, so generators must be deterministic in their
    traversal order for a seed to reproduce a corpus.
    """

    width: int = 4
    _counters: dict[str, int] = field(default_factory=dict)

    def next(self, prefix: str) -> str:
        """Mint the next ID for *prefix*."""
        number = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = number
        return format_id(prefix, number, width=self.width)

    def peek(self, prefix: str) -> int:
        """How many IDs have been minted for *prefix*."""
        return self._counters.get(prefix, 0)

    def reset(self) -> None:
        """Clear all sequences."""
        self._counters.clear()
