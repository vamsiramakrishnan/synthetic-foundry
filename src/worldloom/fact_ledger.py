"""Canonical bitemporal reads over :class:`worldloom.models.CanonicalFact`.

Generation and validation need the complete append-only fact history. Consumers
that ask what was true, known, or visible need a resolved view.  This module is
the boundary between those two operations.

There is deliberately no observation shadow table here. Observer, source,
valid-time and transaction-time metadata live on ``CanonicalFact`` itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

from .models import AUTHORITY_RANK, CanonicalFact


class AmbiguousFactView(ValueError):
    """Equally authoritative facts disagree; a consumer must not guess."""


class FactLedger:
    """Immutable canonical fact history with explicit bitemporal resolution."""

    def __init__(self, facts: Iterable[CanonicalFact]) -> None:
        self._facts = tuple(facts)
        ids = [fact.id for fact in self._facts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate fact IDs in ledger")

    def __iter__(self) -> Iterator[CanonicalFact]:
        return iter(self._facts)

    def __len__(self) -> int:
        return len(self._facts)

    def known_at(self, tx_at: datetime) -> FactLedger:
        """All rows that existed in the transaction-time snapshot."""

        return FactLedger(fact for fact in self if fact.known_at(tx_at))

    def valid_at(self, valid_at: datetime) -> FactLedger:
        """All rows whose business-valid interval contains ``valid_at``."""

        return FactLedger(fact for fact in self if fact.holds_at(valid_at))

    def observed_by(self, observer: str) -> FactLedger:
        return FactLedger(fact for fact in self if fact.observer == observer)

    def from_system(self, source_system: str) -> FactLedger:
        return FactLedger(fact for fact in self if fact.source_system == source_system)

    def as_known(self, *, valid_at: datetime, tx_at: datetime) -> FactLedger:
        return self.valid_at(valid_at).known_at(tx_at)

    @staticmethod
    def _semantic_key(fact: CanonicalFact) -> tuple[str, str, str]:
        return fact.subject, fact.kind, fact.period or ""

    @staticmethod
    def _rank(fact: CanonicalFact) -> tuple[int, datetime]:
        return AUTHORITY_RANK[fact.authority], fact.recorded_at

    def view(self, observer: str, *, valid_at: datetime, tx_at: datetime) -> FactLedger:
        """Resolve one observer/time view of the append-only ledger.

        ``observer='*'`` is the explicit oracle view across channels. Legacy
        rows with no observer remain public unless marked ``source='latent'``.
        Supersession retires only a predecessor in the same semantic and source
        channel. Equal-rank disagreement is an error rather than an arbitrary
        identifier tie-break.
        """

        if not observer.strip():
            raise ValueError("observer must not be blank")
        rows = tuple(
            fact
            for fact in self.as_known(valid_at=valid_at, tx_at=tx_at)
            if fact.visible_to(observer)
        )
        by_id = {fact.id: fact for fact in rows}
        retired: set[str] = set()
        for fact in rows:
            predecessor = by_id.get(fact.supersedes or "")
            if predecessor is not None and (
                self._semantic_key(predecessor) == self._semantic_key(fact)
                and predecessor.observer == fact.observer
                and predecessor.source_system == fact.source_system
                and predecessor.source == fact.source
                and predecessor.recorded_at <= fact.recorded_at
            ):
                retired.add(predecessor.id)

        grouped: dict[tuple[str, str, str], list[CanonicalFact]] = {}
        for fact in rows:
            if fact.id not in retired:
                grouped.setdefault(self._semantic_key(fact), []).append(fact)

        winners: list[CanonicalFact] = []
        for key in sorted(grouped):
            group = sorted(grouped[key], key=lambda fact: fact.id)
            rank = max(self._rank(fact) for fact in group)
            peers = [fact for fact in group if self._rank(fact) == rank]
            winner = peers[0]
            for peer in peers[1:]:
                if peer.value != winner.value or peer.text_value != winner.text_value:
                    raise AmbiguousFactView(
                        f"{key}: {winner.id} and {peer.id} disagree"
                    )
            winners.append(winner)
        return FactLedger(winners)

    def best(self) -> CanonicalFact | None:
        return max(self._facts, key=self._rank) if self._facts else None

    def for_subject(self, subject: str, *, kind: str | None = None) -> FactLedger:
        return FactLedger(
            fact
            for fact in self
            if fact.subject == subject and (kind is None or fact.kind == kind)
        )

    def to_tuple(self) -> tuple[CanonicalFact, ...]:
        return self._facts


__all__ = ["AmbiguousFactView", "FactLedger"]
