"""Compatibility adapter for the pre-ledger observation SDK.

The canonical implementation moved to :mod:`worldloom.fact_ledger` after
observer and transaction-time metadata became fields on ``CanonicalFact``.
New Worldloom code must import ``FactLedger`` from there. ``FactObservation``
and ``ledger_from_facts`` remain for one compatibility release only.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from pydantic import model_validator

from .fact_ledger import AmbiguousFactView, FactLedger
from .models import Authority, CanonicalFact, Model, Quantity


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


def ledger_from_facts(facts: Iterable[CanonicalFact]) -> FactLedger:
    """Deprecated compatibility spelling for ``FactLedger(facts)``."""

    return FactLedger(facts)


__all__ = [
    "AmbiguousFactView",
    "FactLedger",
    "FactObservation",
    "ledger_from_facts",
]
