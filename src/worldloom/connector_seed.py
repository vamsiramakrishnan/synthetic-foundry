"""Connector-neutral seed manifests derived from ConnectorDefinition.

The manifest describes desired synthetic connector state. A local emulator can
hydrate it directly; a tenant adapter can use ``create_tool`` where the product
surface exposes one. Read-only/product-search surfaces remain fixture-only
rather than gaining invented write APIs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import Field

from .connector_data import ConnectorRecord
from .connector_definition import ConnectorDefinition
from .connector_emulator import ConnectorEmulator
from .connector_payload import shape_payload
from .models import Model

CONNECTOR_SEED_SCHEMA: Literal["worldloom.connector-seed/v1"] = (
    "worldloom.connector-seed/v1"
)


class ConnectorSeedRecord(Model):
    fid: str
    connector: str
    entity: str
    external_id: str
    name: str
    canonical: dict[str, Any]
    create_tool: str | None = None
    fixture_only: bool = False
    native_payload_bytes: int = 0
    digest: str


class ConnectorSeedManifest(Model):
    manifest_schema: Literal["worldloom.connector-seed/v1"] = Field(
        default=CONNECTOR_SEED_SCHEMA,
        alias="schema",
        serialization_alias="schema",
    )
    connector: str
    definition_version: str
    records: tuple[ConnectorSeedRecord, ...]

    def wire_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def _canonical(record: ConnectorRecord | Mapping[str, Any], connector: str) -> dict[str, Any]:
    if isinstance(record, ConnectorRecord):
        return {
            **record.fields,
            "fid": record.id,
            "server": record.connector,
            "entity": record.entity,
            "ident": record.external_id,
            "external_id": record.external_id,
            "name": record.title,
            "title": record.title,
            "fact_ids": list(record.fact_ids),
            "event_ids": list(record.event_ids),
            "source_artifact_ids": list(record.source_artifact_ids),
        }
    value = dict(record)
    value.setdefault("server", connector)
    value.setdefault("fid", str(value.get("id") or value.get("external_id") or value.get("ident")))
    return value


def _digest(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def compile_seed_manifest(
    definition: ConnectorDefinition,
    records: Iterable[ConnectorRecord | Mapping[str, Any]],
) -> ConnectorSeedManifest:
    """Validate records against a connector definition and compile loader metadata."""

    output: list[ConnectorSeedRecord] = []
    for source in records:
        record = _canonical(source, definition.connector)
        if str(record.get("server")) != definition.connector:
            continue
        entity = str(record.get("entity") or "")
        try:
            definition.entity_members(entity)
        except KeyError as error:
            raise ValueError(
                f"seed record {record.get('fid')!r} uses unknown "
                f"{definition.connector} entity {entity!r}"
            ) from error
        create_tool: str | None = None
        try:
            create_tool = definition.tool_for(entity, "create")
        except KeyError:
            pass
        payload = shape_payload(definition, record)
        fid = str(record["fid"])
        external_id = str(
            record.get("ident") or record.get("external_id") or payload.get("id") or fid
        )
        name = str(record.get("name") or record.get("title") or external_id)
        output.append(
            ConnectorSeedRecord(
                fid=fid,
                connector=definition.connector,
                entity=entity,
                external_id=external_id,
                name=name,
                canonical=record,
                create_tool=create_tool,
                fixture_only=create_tool is None,
                native_payload_bytes=len(
                    json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
                ),
                digest=_digest(record),
            )
        )
    return ConnectorSeedManifest(
        connector=definition.connector,
        definition_version=definition.version,
        records=tuple(sorted(output, key=lambda item: item.fid)),
    )


def hydrate_emulator(
    definition: ConnectorDefinition,
    manifest: ConnectorSeedManifest,
    *,
    acl: Mapping[str, Mapping[str, Any]] | None = None,
) -> ConnectorEmulator:
    """Hydrate the generic emulator from the same manifest a tenant loader reads."""

    if manifest.connector != definition.connector:
        raise ValueError(
            f"seed manifest is for {manifest.connector!r}, not {definition.connector!r}"
        )
    return ConnectorEmulator(
        definition,
        (record.canonical for record in manifest.records),
        acl=acl,
    )


__all__ = [
    "CONNECTOR_SEED_SCHEMA",
    "ConnectorSeedManifest",
    "ConnectorSeedRecord",
    "compile_seed_manifest",
    "hydrate_emulator",
]
