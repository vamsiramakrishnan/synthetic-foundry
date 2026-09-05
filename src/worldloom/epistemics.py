"""Bitemporal, per-observer views over Worldloom facts.

This module is additive: existing ``CanonicalFact`` remains the durable truth
record, while ``FactObservation`` adds transaction time and observer identity so
an eval can distinguish what was true, what a system recorded, and what an
actor believed at a point in time.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from pydantic import model_validator

from .models import AUTHORITY_RANK, Authority, CanonicalFact, Model, Quantity


class FactObservation(Model):
    """One observer's recorded claim about a valid-time fact."""

    id: str
    fact_id: str
    kind: str
    subject: str
    period: str | None = None
    value: Quantity | None = None
    text_value: str | None = None
    source_system: str | None = None
    observer_id: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    recorded_at: datetime
    authority: Authority
    supersedes: str | None = None

    @model_validator(mode="after")
    def _valid(self) -> FactObservation:
        if self.value is None and self.text_value is None:
            raise ValueError(f"{self.id}: observation needs a value")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError(f"{self.id}: valid_to precedes valid_from")
        return self

    def holds_at(self, moment: datetime) -> bool:
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment < self.valid_to

    def known_at(self, moment: datetime) -> bool:
        return self.recorded_at <= moment

    @classmethod
    def from_fact(cls, fact: CanonicalFact) -> FactObservation:
        """Lift a legacy canonical fact without changing existing corpora.

        Legacy facts have no separate transaction time. Treat their valid-from
        instant as the moment they entered the ledger and preserve source-system
        provenance. New generators should emit explicit observations instead.
        """

        return cls(
            id=f"obs:{fact.id}",
            fact_id=fact.id,
            kind=fact.kind,
            subject=fact.subject,
            period=fact.period,
            value=fact.value,
            text_value=fact.text_value,
            source_system=fact.source_system,
            observer_id=None,
            valid_from=fact.valid_from,
            valid_to=fact.valid_to,
            recorded_at=fact.valid_from,
            authority=fact.authority,
            supersedes=fact.supersedes,
        )


class FactLedger:
    """Immutable query surface for bitemporal enterprise knowledge."""

    def __init__(self, observations: Iterable[FactObservation]) -> None:
        self._observations = tuple(observations)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._observations)

    def __len__(self) -> int:
        return len(self._observations)

    def known_at(self, recorded_at: datetime) -> FactLedger:
        """Claims that had entered the ledger by transaction time."""
        return FactLedger(item for item in self if item.known_at(recorded_at))

    def valid_at(self, valid_at: datetime) -> FactLedger:
        """Claims about state that held at the requested valid time."""
        return FactLedger(item for item in self if item.holds_at(valid_at))

    def observed_by(self, observer_id: str) -> FactLedger:
        return FactLedger(item for item in self if item.observer_id == observer_id)

    def from_system(self, source_system: str) -> FactLedger:
        return FactLedger(item for item in self if item.source_system == source_system)

    def as_known(self, *, valid_at: datetime, recorded_at: datetime) -> FactLedger:
        """Bitemporal cut: what was known by one time about another time."""
        return self.valid_at(valid_at).known_at(recorded_at)

    def best(self) -> FactObservation | None:
        """Most authoritative/latest observation in this already-filtered cut."""
        if not self._observations:
            return None
        return max(
            self._observations,
            key=lambda item: (AUTHORITY_RANK[item.authority], item.recorded_at, item.id),
        )

    def for_subject(self, subject: str, *, kind: str | None = None) -> FactLedger:
        return FactLedger(
            item
            for item in self
            if item.subject == subject and (kind is None or item.kind == kind)
        )

    def to_tuple(self) -> tuple[FactObservation, ...]:
        return self._observations


def ledger_from_facts(facts: Iterable[CanonicalFact]) -> FactLedger:
    """Compatibility bridge for existing worlds."""
    return FactLedger(FactObservation.from_fact(fact) for fact in facts)


__all__ = ["FactLedger", "FactObservation", "ledger_from_facts"]
