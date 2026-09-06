"""Compatibility execution of enterprise eval fixtures on ConnectorEmulator.

The old enterprise simulator carried its own generic CRUD model.  This adapter
keeps only what is specific to those historical eval fixtures: translating their
generic DAG arguments and compiling deliberate failure-state overlays. Product
semantics, payloads, workflows, ACL checks, idempotency and traces belong to the
canonical :class:`worldloom.connector_emulator.ConnectorEmulator`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from ..connector_data import ConnectorRecord
from ..connector_definition import ConnectorDefinition, load_connector_definition
from ..connector_emulator import ConnectorEmulator, ConnectorError
from ..enterprise_corpus import EnterpriseCorpus, QueryFixture, StateOverride
from ..ids import content_key

_READ_OPERATIONS = frozenset({"search", "get", "read", "extract", "download"})
_WRITE_OPERATIONS = frozenset(
    {
        "create",
        "update",
        "transition",
        "comment",
        "delete",
        "transform",
        "send",
        "post",
        "reply",
        "forward",
        "upload",
    }
)
_MODEL_OPERATIONS = frozenset(
    {
        "transform",
        "summarize",
        "extract",
        "compare",
        "reconcile",
        "generate",
        "render",
        "convert",
        "classify",
    }
)
_STABLE_ID_FIELDS = (
    "stable_id",
    "key",
    "sys_id",
    "id",
    "page_id",
    "item_id",
    "file_id",
    "message_id",
    "thread_id",
)


def _override_rows(fixture: QueryFixture, connector: str) -> tuple[StateOverride, ...]:
    return tuple(item for item in fixture.overrides if item.connector == connector)


def _internal_id(record: Mapping[str, Any]) -> str:
    return str(record.get("fid") or record.get("id"))


def _record_fact_ids(record: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(value) for value in record.get("fact_ids", ()))


class EnterpriseConnectorRuntime:
    """Query-isolated compatibility runtime backed by connector definitions."""

    def __init__(self, corpus: EnterpriseCorpus) -> None:
        self._corpus = corpus
        self._source: dict[str, tuple[ConnectorRecord, ...]] = {}
        for record in corpus.connector_data.records:
            self._source.setdefault(record.connector, ())
            self._source[record.connector] = (*self._source[record.connector], record)
        self._queries: dict[tuple[str, str], ConnectorEmulator] = {}
        self._latest: tuple[str, str] | None = None

    @property
    def records(self) -> tuple[ConnectorRecord, ...]:
        """Compatibility view of the most recently exercised query state."""

        materialized: dict[tuple[str, str], ConnectorRecord] = {
            (record.connector, record.id): record
            for records in self._source.values()
            for record in records
        }
        if self._latest is not None:
            connector = self._latest[1]
            emulator = self._queries[self._latest]
            for fid, record in emulator.records.items():
                materialized[(connector, fid)] = ConnectorRecord(
                    id=fid,
                    connector=connector,
                    entity=str(record.get("entity") or "record"),
                    external_id=str(
                        record.get("external_id") or record.get("ident") or fid
                    ),
                    title=str(record.get("title") or record.get("name") or fid),
                    fields={
                        key: deepcopy(value)
                        for key, value in record.items()
                        if key
                        not in {
                            "fid",
                            "server",
                            "entity",
                            "ident",
                            "external_id",
                            "name",
                            "title",
                            "fact_ids",
                            "event_ids",
                            "source_artifact_ids",
                        }
                    },
                    fact_ids=tuple(record.get("fact_ids", ())),
                    event_ids=tuple(record.get("event_ids", ())),
                    source_artifact_ids=tuple(record.get("source_artifact_ids", ())),
                )
        return tuple(record for _, record in sorted(materialized.items()))

    @staticmethod
    def _definition_tool(
        definition: ConnectorDefinition,
        requested: str,
        entity: str,
    ) -> str:
        try:
            return definition.canonical_tool(requested)
        except KeyError:
            legacy = requested.removeprefix("read_").removeprefix("get_")
            if requested.startswith(("read_", "get_")):
                operation = "read"
            elif requested.startswith(("create_", "upload_")):
                operation = "create"
            elif requested.startswith("update_"):
                operation = "update"
            elif requested.startswith("delete_"):
                operation = "delete"
            elif requested.startswith(("search_", "list_")):
                operation = "search"
            else:
                operation = legacy
            return definition.tool_for(entity, operation)

    @staticmethod
    def _concrete_entity(
        definition: ConnectorDefinition,
        entity: str,
        generation: Mapping[str, Any],
        dependencies: Mapping[str, Any],
        emulator: ConnectorEmulator,
    ) -> str:
        members = definition.entity_members(entity)
        if len(members) == 1:
            return members[0]
        mutation = generation.get("mutation")
        output_format = mutation.get("output_format") if isinstance(mutation, Mapping) else None
        if isinstance(output_format, str) and output_format in members:
            return output_format
        for dependency in dependencies.values():
            if not isinstance(dependency, Mapping) or not dependency.get("record_id"):
                continue
            try:
                fid = emulator.resolve(dependency["record_id"])
            except ConnectorError:
                continue
            actual = str(emulator.records[fid].get("entity"))
            if actual in members:
                return actual
        raise ConnectorError(
            400,
            f"legacy entity alias {entity!r} needs one concrete member from {sorted(members)}",
            "validation",
        )

    def _query_emulator(
        self,
        connector: str,
        fixture: QueryFixture,
        generation: Mapping[str, Any],
    ) -> ConnectorEmulator:
        key = (fixture.query_id, connector)
        existing = self._queries.get(key)
        if existing is not None:
            self._latest = key
            return existing

        definition = load_connector_definition(connector)
        records = [record.model_dump(mode="python") for record in self._source.get(connector, ())]
        overrides = _override_rows(fixture, connector)
        for override in overrides:
            if override.record_id is None:
                continue
            target = next(
                (record for record in records if record.get("id") == override.record_id),
                None,
            )
            if target is None:
                continue
            fields = target.setdefault("fields", {})
            if override.kind == "stale_source":
                fields["version"] = max(0, int(fields.get("version", 1)) - 1)
            elif override.kind == "missing_stable_id":
                for field in _STABLE_ID_FIELDS:
                    fields.pop(field, None)
            elif override.kind == "ambiguous_join":
                duplicate = deepcopy(target)
                duplicate["id"] = content_key(
                    "ambiguous-enterprise-record", fixture.query_id, override.record_id
                )
                duplicate["external_id"] = duplicate["id"]
                records.append(duplicate)

        faults: dict[str, Sequence[str]] = {}
        acl: dict[str, dict[str, Any]] = {}
        for override in overrides:
            if override.kind == "permission_denied":
                if override.record_id is not None:
                    acl[override.record_id] = {"denied": True}
                else:
                    faults["*"] = (*faults.get("*", ()), "permission_denied")
            elif override.kind in {"version_conflict", "partial_write"}:
                mutation = generation.get("mutation")
                if not isinstance(mutation, Mapping):
                    continue
                mutation_entity = str(mutation.get("entity") or "record")
                mutation_operation = str(mutation.get("operation") or "update")
                if mutation_operation == "readback":
                    mutation_operation = "read"
                try:
                    tool = definition.tool_for(mutation_entity, mutation_operation)
                except KeyError:
                    tool = "*"
                faults[tool] = (*faults.get(tool, ()), override.kind)

        emulator = ConnectorEmulator(
            definition,
            records,
            acl=acl,
            faults=faults,
        )
        self._queries[key] = emulator
        self._latest = key
        return emulator

    @staticmethod
    def _target_id(
        fixture: QueryFixture,
        dependencies: Mapping[str, Any],
    ) -> str | None:
        for dependency in reversed(tuple(dependencies.values())):
            if isinstance(dependency, Mapping) and dependency.get("record_id"):
                return str(dependency["record_id"])
        if fixture.destination_record_id:
            return fixture.destination_record_id
        return next(
            (
                record_id
                for values in fixture.input_record_ids.values()
                for record_id in values
            ),
            None,
        )

    @staticmethod
    def _response(
        emulator: ConnectorEmulator,
        payload: Any,
        *,
        status: int = 200,
    ) -> Mapping[str, Any]:
        span = emulator.trace[-1]
        ids = (*span.writes, *span.reads)
        first = ids[0] if ids else None
        facts = sorted(
            {
                fact
                for fid in ids
                if fid in emulator.records
                for fact in _record_fact_ids(emulator.records[fid])
            }
        )
        records = [deepcopy(emulator.records[fid]) for fid in span.reads if fid in emulator.records]
        return {
            "succeeded": span.error is None,
            "status": status,
            "record_id": first,
            "fact_ids": facts,
            "records": records,
            "payload": payload,
        }

    async def invoke(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        connector, _, requested_tool = tool_name.partition(".")
        generation = arguments.get("generation_requirement")
        generation_map = generation if isinstance(generation, Mapping) else {}
        if connector in {"model", "content"} or requested_tool in _MODEL_OPERATIONS:
            return {
                "succeeded": True,
                "content": generation_map,
                "fact_ids": [],
            }

        fixture = QueryFixture.model_validate(arguments["fixture"])
        emulator = self._query_emulator(connector, fixture, generation_map)
        definition = emulator.definition
        entity = str(arguments.get("entity") or "record")
        dependencies = arguments.get("dependencies")
        dependency_map = dependencies if isinstance(dependencies, Mapping) else {}
        try:
            canonical_tool = self._definition_tool(definition, requested_tool, entity)
            tool = definition.tool(canonical_tool)
            concrete = self._concrete_entity(
                definition,
                entity,
                generation_map,
                dependency_map,
                emulator,
            )
            target = self._target_id(fixture, dependency_map)
            node_id = str(arguments.get("node_id") or "")
            common = {"_node": node_id}
            if tool.op in {"create", "send", "post", "upload"}:
                payload = emulator.call(
                    canonical_tool,
                    entity=concrete,
                    name=f"Generated {concrete} for {fixture.query_id}",
                    fields={
                        "last_query_id": fixture.query_id,
                        "version": 1,
                        "body": f"Generated by {fixture.query_id}",
                        "text": f"Generated by {fixture.query_id}",
                    },
                    parent="worldloom-eval",
                    **common,
                )
                return self._response(emulator, payload, status=201)
            if tool.op in _READ_OPERATIONS:
                if tool.op == "search":
                    payload = emulator.call(
                        canonical_tool,
                        entity=entity,
                        **common,
                    )
                else:
                    if target is None:
                        return {"succeeded": True, "status": 200, "records": [], "fact_ids": []}
                    payload = emulator.call(canonical_tool, id=target, **common)
                return self._response(emulator, payload)
            if target is None:
                raise ConnectorError(404, "No target record", "not_found")
            if tool.op == "update":
                payload = emulator.call(
                    canonical_tool,
                    id=target,
                    fields={"last_query_id": fixture.query_id},
                    **common,
                )
            elif tool.op == "transition":
                workflow = definition.entities[concrete].workflow
                if workflow is None or len(workflow.states) < 2:
                    raise ConnectorError(400, "No legal transition target", "bad_transition")
                payload = emulator.call(
                    canonical_tool,
                    id=target,
                    state=workflow.states[1],
                    **common,
                )
            elif tool.op in {"comment", "reply"}:
                payload = emulator.call(
                    canonical_tool,
                    id=target,
                    body=f"Worldloom eval {fixture.query_id}",
                    **common,
                )
            elif tool.op == "delete":
                payload = emulator.call(canonical_tool, id=target, **common)
            elif tool.op in {"transform", "forward"}:
                payload = emulator.call(
                    canonical_tool,
                    id=target,
                    format=(
                        generation_map.get("mutation", {}).get("output_format")
                        if isinstance(generation_map.get("mutation"), Mapping)
                        else None
                    ),
                    dest="worldloom-eval",
                    **common,
                )
            else:
                raise ConnectorError(
                    400,
                    f"unsupported compatibility operation {tool.op}",
                    "validation",
                )
            return self._response(emulator, payload)
        except ConnectorError as error:
            return {
                "succeeded": False,
                "status": error.code,
                "error": error.kind,
                "message": error.message,
                "fact_ids": [],
            }


__all__ = ["EnterpriseConnectorRuntime"]
