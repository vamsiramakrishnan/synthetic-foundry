"""Compatibility adapter for the pre-ledger observation SDK.

The canonical implementation is :mod:`worldloom.fact_ledger`. New Worldloom
code imports ``FactLedger`` from there and operates directly on ``CanonicalFact``.
This module keeps the old ``FactObservation`` + generic ``FactLedger`` surface for
one compatibility release; it is not used by generation, rendering, or evals.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import model_validator

from .fact_ledger import (
    AmbiguousFactView,
)
from .fact_ledger import (
    FactLedger as CanonicalFactLedger,
)
from .models import AUTHORITY_RANK, Authority, CanonicalFact, Model, Quantity


class FactObservation(Model):
    """Deprecated input adapter; observations are no longer a second database."""

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
    tx_to: datetime | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _valid(self) -> FactObservation:
        if self.value is None and self.text_value is None:
            raise ValueError(f"{self.id}: observation needs a value")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError(f"{self.id}: valid_to precedes valid_from")
        if self.tx_to is not None and self.tx_to <= self.recorded_at:
            raise ValueError(f"{self.id}: tx_to must follow recorded_at")
        return self

    @property
    def observer(self) -> str | None:
        return self.observer_id

    def holds_at(self, moment: datetime) -> bool:
        return self.valid_from <= moment and (
            self.valid_to is None or moment < self.valid_to
        )

    def known_at(self, moment: datetime) -> bool:
        return self.recorded_at <= moment and (
            self.tx_to is None or moment < self.tx_to
        )

    def visible_to(self, observer: str) -> bool:
        return observer == "*" or self.observer == observer or (
            self.observer is None and self.source != "latent"
        )

    @classmethod
    def from_fact(cls, fact: CanonicalFact) -> FactObservation:
        return cls(
            id=f"obs:{fact.id}",
            fact_id=fact.id,
            kind=fact.kind,
            subject=fact.subject,
            period=fact.period,
            value=fact.value,
            text_value=fact.text_value,
            source_system=fact.source_system,
            observer_id=fact.observer,
            valid_from=fact.valid_from,
            valid_to=fact.valid_to,
            recorded_at=fact.recorded_at,
            authority=fact.authority,
            supersedes=fact.supersedes,
            tx_to=fact.tx_to,
            source=fact.source,
        )


FactRow = TypeVar("FactRow", CanonicalFact, FactObservation)


class FactLedger(Generic[FactRow]):
    """Deprecated generic observation ledger retained for source compatibility.

    CanonicalFact callers should use :class:`worldloom.fact_ledger.FactLedger`.
    Keeping this class here prevents a source-breaking change for early SDK users
    without leaving any internal Worldloom path dependent on the observation shim.
    """

    def __init__(self, observations: Iterable[FactRow]) -> None:
        self._observations: tuple[FactRow, ...] = tuple(observations)
        ids = [item.id for item in self._observations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate fact/observation IDs in ledger")

    def __iter__(self) -> Iterator[FactRow]:
        return iter(self._observations)

    def __len__(self) -> int:
        return len(self._observations)

    def known_at(self, recorded_at: datetime) -> FactLedger[FactRow]:
        return FactLedger(item for item in self if item.known_at(recorded_at))

    def valid_at(self, valid_at: datetime) -> FactLedger[FactRow]:
        return FactLedger(item for item in self if item.holds_at(valid_at))

    def observed_by(self, observer_id: str) -> FactLedger[FactRow]:
        return FactLedger(item for item in self if item.observer == observer_id)

    def from_system(self, source_system: str) -> FactLedger[FactRow]:
        return FactLedger(
            item for item in self if item.source_system == source_system
        )

    def as_known(
        self, *, valid_at: datetime, recorded_at: datetime
    ) -> FactLedger[FactRow]:
        return self.valid_at(valid_at).known_at(recorded_at)

    @staticmethod
    def _semantic_key(item: FactRow) -> tuple[str, str, str]:
        return item.subject, item.kind, item.period or ""

    @staticmethod
    def _rank(item: FactRow) -> tuple[int, datetime]:
        return AUTHORITY_RANK[item.authority], item.recorded_at

    def view(
        self, observer: str, *, valid_at: datetime, tx_at: datetime
    ) -> FactLedger[FactRow]:
        if not observer.strip():
            raise ValueError("observer must not be blank")
        rows = tuple(
            item
            for item in self.as_known(valid_at=valid_at, recorded_at=tx_at)
            if item.visible_to(observer)
        )
        by_id = {item.id: item for item in rows}
        retired: set[str] = set()
        for item in rows:
            previous = by_id.get(item.supersedes or "")
            if previous is not None and (
                self._semantic_key(previous) == self._semantic_key(item)
                and previous.observer == item.observer
                and previous.source_system == item.source_system
                and previous.source == item.source
                and previous.recorded_at <= item.recorded_at
            ):
                retired.add(previous.id)

        grouped: dict[tuple[str, str, str], list[FactRow]] = {}
        for item in rows:
            if item.id not in retired:
                grouped.setdefault(self._semantic_key(item), []).append(item)

        winners: list[FactRow] = []
        for key in sorted(grouped):
            group = sorted(grouped[key], key=lambda item: item.id)
            rank = max(self._rank(item) for item in group)
            peers = [item for item in group if self._rank(item) == rank]
            winner = peers[0]
            for peer in peers[1:]:
                if peer.value != winner.value or peer.text_value != winner.text_value:
                    raise AmbiguousFactView(
                        f"{key}: {winner.id} and {peer.id} disagree"
                    )
            winners.append(winner)
        return FactLedger(winners)

    def best(self) -> FactRow | None:
        return (
            max(self._observations, key=self._rank)
            if self._observations
            else None
        )

    def for_subject(
        self, subject: str, *, kind: str | None = None
    ) -> FactLedger[FactRow]:
        return FactLedger(
            item
            for item in self
            if item.subject == subject and (kind is None or item.kind == kind)
        )

    def to_tuple(self) -> tuple[FactRow, ...]:
        return self._observations


def ledger_from_facts(facts: Iterable[CanonicalFact]) -> CanonicalFactLedger:
    """Deprecated spelling for ``worldloom.fact_ledger.FactLedger(facts)``."""

    return CanonicalFactLedger(facts)


__all__ = [
    "AmbiguousFactView",
    "FactLedger",
    "FactObservation",
    "ledger_from_facts",
]
