"""In-memory MCP connector simulator with executable CRUD failure semantics."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .connector_data import ConnectorRecord
from .enterprise_corpus import EnterpriseCorpus, QueryFixture, StateOverride
from .ids import content_key


class ConnectorSimulator:
    def __init__(self, corpus: EnterpriseCorpus) -> None:
        self._records = {record.id: record.model_dump(mode="python") for record in corpus.connector_data.records}
        self._external = {record.external_id: record.id for record in corpus.connector_data.records}
        self._writes: dict[str, dict[str, Any]] = {}

    @property
    def records(self) -> tuple[ConnectorRecord, ...]:
        return tuple(ConnectorRecord.model_validate(item) for _, item in sorted(self._records.items()))

    def _overrides(self, fixture: Mapping[str, Any]) -> tuple[StateOverride, ...]:
        return tuple(StateOverride.model_validate(item) for item in fixture.get("overrides", ()))

    async def invoke(self, tool_name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        fixture = QueryFixture.model_validate(arguments["fixture"])
        operation = tool_name.rsplit(".", 1)[-1].replace("read_file", "read").replace("create_file", "create")
        connector = tool_name.split(".", 1)[0]
        overrides = self._overrides(arguments["fixture"])
        if operation in {"transform", "summarize", "extract", "compare", "reconcile", "generate", "render", "convert", "classify"}:
            return {"succeeded": True, "content": arguments["generation_requirement"], "fact_ids": []}
        if any(item.kind == "permission_denied" and item.connector == connector for item in overrides):
            return {"succeeded": False, "status": 403, "error": "permission_denied"}
        if operation in {"read", "readback", "search", "list"}:
            identifiers = [identifier for values in fixture.input_record_ids.values() for identifier in values]
            if fixture.destination_record_id:
                identifiers.append(fixture.destination_record_id)
            for dependency in arguments.get("dependencies", {}).values():
                if isinstance(dependency, Mapping) and dependency.get("record_id"):
                    identifiers.append(str(dependency["record_id"]))
            selected = [deepcopy(self._records[item]) for item in identifiers if item in self._records]
            for override in overrides:
                if override.kind == "stale_source" and selected:
                    selected[0]["fields"]["version"] = max(0, int(selected[0]["fields"].get("version", 1)) - 1)
                if override.kind == "missing_stable_id" and selected:
                    candidates = ("stable_id", "key", "sys_id", "id", "page_id", "item_id", "file_id", "message_id", "thread_id")
                    for field in candidates:
                        selected[0]["fields"].pop(field, None)
                if override.kind == "ambiguous_join" and selected:
                    selected.append(deepcopy(selected[0]))
            return {"succeeded": True, "records": selected, "record_id": selected[0]["id"] if selected else None, "fact_ids": sorted({fact for record in selected for fact in record.get("fact_ids", ())})}
        if operation in {"create", "update", "patch", "upsert", "draft", "send", "reply"}:
            if any(item.kind == "version_conflict" for item in overrides):
                return {"succeeded": False, "status": 409, "error": "version_conflict"}
            write_key = content_key("simulated-write", fixture.query_id, arguments["node_id"])
            if write_key in self._writes:
                return deepcopy(self._writes[write_key])
            if any(item.kind == "partial_write" for item in overrides):
                response = {"succeeded": False, "status": 207, "error": "partial_write", "completed_branches": 1}
                self._writes[write_key] = response
                return deepcopy(response)
            record_id = fixture.destination_record_id or content_key("simulated-record", fixture.query_id, connector)
            current = deepcopy(self._records.get(record_id, {}))
            current.update({"id": record_id, "connector": connector, "entity": arguments["entity"], "external_id": current.get("external_id", record_id), "title": current.get("title", f"Generated {arguments['entity']}"), "fields": {**current.get("fields", {}), "version": int(current.get("fields", {}).get("version", 0)) + 1, "last_query_id": fixture.query_id}, "fact_ids": current.get("fact_ids", []), "event_ids": current.get("event_ids", []), "source_artifact_ids": current.get("source_artifact_ids", [])})
            self._records[record_id] = current
            response = {"succeeded": True, "status": 200 if fixture.destination_record_id else 201, "record_id": record_id, "fact_ids": current["fact_ids"]}
            self._writes[write_key] = response
            return deepcopy(response)
        return {"succeeded": False, "status": 400, "error": f"unsupported operation {operation}"}
