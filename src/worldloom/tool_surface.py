"""Corpus-backed connector tool surfaces for executable evals.

This emulates the verbs Worldloom exposes, not Jira/ServiceNow products. A
session is a mutable fork over deterministic ``ConnectorRecord`` values. New
sessions created from the same dataset start from identical state; writes in one
fork cannot contaminate another evaluation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .connector_data import (
    CAPABILITIES,
    ConnectorDataset,
    ConnectorRecord,
    ConnectorVerb,
    generate_connector_data,
)
from .ids import content_key
from .models import Model
from .world import World


class ToolEffect(Model):
    id: str
    verb: ConnectorVerb
    connector: str
    entity: str
    external_id: str


@dataclass(frozen=True)
class ToolResult:
    records: tuple[ConnectorRecord, ...]
    effects: tuple[ToolEffect, ...] = ()


class ToolSurface:
    """Forkable exact-match CRUD surface over connector projections."""

    def __init__(self, dataset: ConnectorDataset) -> None:
        self._dataset = dataset
        self._initial = tuple(record.model_copy(deep=True) for record in dataset.records)

    @classmethod
    def from_world(cls, world: World) -> ToolSurface:
        return cls(generate_connector_data(world))

    def fork(self) -> ToolSession:
        return ToolSession(self._dataset, self._initial)


class ToolSession:
    def __init__(self, dataset: ConnectorDataset, records: tuple[ConnectorRecord, ...]) -> None:
        self._capabilities = {
            (cap.connector, cap.entity): cap for cap in dataset.capabilities
        }
        self._records: dict[tuple[str, str, str], ConnectorRecord] = {
            (record.connector, record.entity, record.external_id): record.model_copy(deep=True)
            for record in records
        }
        self._counter = 0

    def _require(self, connector: str, entity: str, verb: ConnectorVerb) -> None:
        capability = self._capabilities.get((connector, entity))
        if capability is None:
            known = sorted(f"{item.connector}/{item.entity}" for item in CAPABILITIES)
            raise ValueError(f"unsupported tool surface {connector}/{entity}; known={known}")
        if verb not in capability.verbs:
            raise ValueError(f"{connector}/{entity} does not support {verb.value}")

    @staticmethod
    def _matches(record: ConnectorRecord, criteria: Mapping[str, Any]) -> bool:
        for key, expected in criteria.items():
            if key in {"id", "external_id", "title", "connector", "entity"}:
                actual = getattr(record, key)
            else:
                actual = record.fields.get(key)
            if actual != expected:
                return False
        return True

    def search(self, connector: str, entity: str, **criteria: Any) -> ToolResult:
        self._require(connector, entity, ConnectorVerb.SEARCH)
        matches = tuple(
            record
            for key, record in sorted(self._records.items())
            if key[0] == connector
            and key[1] == entity
            and self._matches(record, criteria)
        )
        return ToolResult(records=matches)

    def read(self, connector: str, entity: str, external_id: str) -> ToolResult:
        self._require(connector, entity, ConnectorVerb.READ)
        record = self._records.get((connector, entity, external_id))
        if record is None:
            return ToolResult(records=())
        return ToolResult(records=(record,))

    def create(
        self,
        connector: str,
        entity: str,
        *,
        external_id: str,
        title: str,
        fields: Mapping[str, Any],
    ) -> ToolResult:
        self._require(connector, entity, ConnectorVerb.CREATE)
        key = (connector, entity, external_id)
        if key in self._records:
            raise ValueError(f"record already exists: {connector}/{entity}/{external_id}")
        self._counter += 1
        record = ConnectorRecord(
            id=f"tool:{content_key(connector, entity, external_id)[:20]}",
            connector=connector,
            entity=entity,
            external_id=external_id,
            title=title,
            fields=dict(fields),
        )
        self._records[key] = record
        effect = ToolEffect(
            id=f"effect:{content_key('create', connector, entity, external_id, self._counter)[:20]}",
            verb=ConnectorVerb.CREATE,
            connector=connector,
            entity=entity,
            external_id=external_id,
        )
        return ToolResult(records=(record,), effects=(effect,))

    def update(
        self,
        connector: str,
        entity: str,
        external_id: str,
        *,
        fields: Mapping[str, Any],
    ) -> ToolResult:
        self._require(connector, entity, ConnectorVerb.UPDATE)
        key = (connector, entity, external_id)
        current = self._records.get(key)
        if current is None:
            raise KeyError(f"record not found: {connector}/{entity}/{external_id}")
        merged = dict(current.fields)
        merged.update(fields)
        updated = current.model_copy(update={"fields": merged}, deep=True)
        self._records[key] = updated
        self._counter += 1
        effect = ToolEffect(
            id=f"effect:{content_key('update', connector, entity, external_id, self._counter)[:20]}",
            verb=ConnectorVerb.UPDATE,
            connector=connector,
            entity=entity,
            external_id=external_id,
        )
        return ToolResult(records=(updated,), effects=(effect,))


__all__ = ["ToolEffect", "ToolResult", "ToolSession", "ToolSurface"]
