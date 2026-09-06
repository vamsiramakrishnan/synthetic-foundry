"""Execute eval rows through the same connector definitions used everywhere else.

This is the bridge from a generated evaluation DAG to the generic emulator. It
contains no Jira/Slack/Graph product branches: the node names a connector and a
tool; the definition owns the tool's operation, paging, workflow and payload
semantics. Historical invalid rows remain visible as runtime/grade failures.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .connector_data import ConnectorRecord
from .connector_definition import ConnectorDefinition, builtin_connector_definitions
from .connector_emulator import ConnectorEmulator, ConnectorError, ConnectorSpan
from .connector_trace import grade_trace
from .eval_design import EvalShape

_CREATE_OPS = frozenset({"create", "send", "post", "upload"})
_READ_OPS = frozenset({"search", "get", "download"})
_BODY_OPS = frozenset({"comment", "reply"})


@dataclass(frozen=True)
class EvalRuntimeResult:
    grade: Mapping[str, Any]
    spans: tuple[ConnectorSpan, ...]
    behaviors: tuple[str, ...]
    post_state: Mapping[str, Mapping[str, Any]]


def _record_dict(record: ConnectorRecord | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, ConnectorRecord):
        return {
            "fid": record.id,
            "server": record.connector,
            "entity": record.entity,
            "ident": record.external_id,
            "external_id": record.external_id,
            "name": record.title,
            "title": record.title,
            **record.fields,
        }
    return dict(record)


def _reference(record: Mapping[str, Any] | None, payload: Mapping[str, Any]) -> Any:
    if record is not None:
        for key in ("ident", "external_id", "key", "number", "id", "name", "title", "fid"):
            if record.get(key) not in (None, ""):
                return record[key]
    for key in ("id", "ref_override", "name", "title"):
        if payload.get(key) not in (None, ""):
            return payload[key]
    return None


def _write_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    explicit = payload.get("fields")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    excluded = {
        "predicate",
        "query",
        "id",
        "name",
        "title",
        "parent",
        "dest",
        "body",
        "note",
        "state",
        "format",
        "fmt",
        "to",
        "fields",
        "max_results",
        "start_at",
    }
    return {key: value for key, value in payload.items() if key not in excluded}


def _page_search(
    emulator: ConnectorEmulator,
    tool_name: str,
    *,
    node_id: str,
    consumed: Sequence[str],
    entity: str | None,
    payload: Mapping[str, Any],
    collect_span: Any,
) -> list[Any]:
    tool = emulator.definition.tool(tool_name)
    start = int(payload.get("start_at", 0) or 0)
    requested = int(payload.get("max_results", tool.max_results) or tool.max_results)
    requested = min(requested, tool.max_results)
    items: list[Any] = []
    while len(items) < requested:
        page_limit = min(tool.page_size, requested - len(items))
        kwargs: dict[str, Any] = {
            "_node": node_id,
            "_consumed": consumed,
            "entity": entity,
            "max_results": page_limit,
            "start_at": start,
        }
        for key in ("predicate", "query", "fields", "name"):
            if key in payload:
                kwargs[key] = payload[key]
        page = emulator.call(tool_name, **kwargs)
        collect_span(emulator.trace[-1])
        page_items = list(page.get("items", ()))
        items.extend(page_items)
        if page.get("is_last") or not page_items:
            break
        start += int(page.get("max_results") or page_limit)
    return items


def run_eval_row(
    row: Mapping[str, Any],
    records: Iterable[ConnectorRecord | Mapping[str, Any]],
    *,
    acl: Mapping[str, Mapping[str, Any]] | None = None,
    definitions: Mapping[str, ConnectorDefinition] | None = None,
    shape: EvalShape | None = None,
) -> EvalRuntimeResult:
    """Execute one eval row and grade its standardized trace.

    The row uses the evalgen shape: ``expected_dag.nodes`` name ``server``,
    ``tool``, ``entity`` and payload. Tool operations are *not* trusted from the
    row; they are read from the connector definition.
    """

    materialized_records = tuple(_record_dict(record) for record in records)
    by_fid = {str(record.get("fid")): record for record in materialized_records if record.get("fid")}
    available = dict(definitions or builtin_connector_definitions())
    nodes = tuple(row.get("expected_dag", {}).get("nodes", ()))
    edges = tuple(row.get("expected_dag", {}).get("edges", ()))
    servers = {str(node.get("server")) for node in nodes if node.get("server")}
    missing = servers - set(available)
    if missing:
        raise ValueError(f"eval row references connectors with no definition: {sorted(missing)}")
    emulators = {
        server: ConnectorEmulator(available[server], materialized_records, acl=acl)
        for server in sorted(servers)
    }
    parents = {
        str(node["id"]): tuple(str(source) for source, target in edges if str(target) == str(node["id"]))
        for node in nodes
    }
    outputs: dict[str, list[Any]] = {}
    node_span_ids: dict[str, list[str]] = {}
    spans: list[ConnectorSpan] = []
    behaviors: list[str] = []
    stopped = False

    def collect(local: ConnectorSpan) -> None:
        global_id = f"s{len(spans) + 1}"
        spans.append(replace(local, id=global_id))

    for node in nodes:
        node_id = str(node["id"])
        if stopped or "gated" in set(node.get("flags", ())):
            continue
        server = str(node["server"])
        emulator = emulators[server]
        tool_name = str(node["tool"])
        tool = emulator.definition.tool(tool_name)
        payload = dict(node.get("payload") or {})
        entity = str(node["entity"]) if node.get("entity") else None
        parent_ids = parents[node_id]
        consumed = tuple(span_id for parent in parent_ids for span_id in node_span_ids.get(parent, ()))
        fixture = by_fid.get(str(node.get("fixture"))) if node.get("fixture") else None
        reference = _reference(fixture, payload)
        iterations: list[Any | None] = [None]
        if node.get("for_each"):
            iterations = list(outputs.get(parent_ids[0], ())) if parent_ids else []
            if not iterations:
                behaviors.append("no_items")
                continue
        before = len(spans)
        made: list[Any] = []
        try:
            if tool.op == "search":
                items = _page_search(
                    emulator,
                    tool_name,
                    node_id=node_id,
                    consumed=consumed,
                    entity=entity,
                    payload=payload,
                    collect_span=collect,
                )
                made.extend(
                    item.get("id") or item.get("key") or item.get("number") or item.get("name")
                    for item in items
                )
                if not items:
                    behaviors.append("empty_search")
            elif tool.op in _READ_OPS:
                result = emulator.call(
                    tool_name,
                    _node=node_id,
                    _consumed=consumed,
                    id=reference,
                    fields=payload.get("fields"),
                )
                collect(emulator.trace[-1])
                if isinstance(result, Mapping):
                    made.append(
                        result.get("id")
                        or result.get("key")
                        or result.get("number")
                        or reference
                    )
            else:
                for item in iterations:
                    target = item if item is not None else reference
                    common = {"_node": node_id, "_consumed": consumed}
                    if tool.op in _CREATE_OPS:
                        result = emulator.call(
                            tool_name,
                            **common,
                            entity=entity,
                            name=(f"{payload.get('name')} ({item})" if item is not None and payload.get("name") else payload.get("name")),
                            fields=_write_fields(payload),
                            parent=payload.get("parent") or payload.get("dest"),
                        )
                    elif tool.op == "update":
                        result = emulator.call(tool_name, **common, id=target, fields=_write_fields(payload))
                    elif tool.op in _BODY_OPS:
                        result = emulator.call(
                            tool_name,
                            **common,
                            id=target,
                            body=payload.get("body") or payload.get("note") or "update",
                        )
                    elif tool.op == "forward":
                        result = emulator.call(
                            tool_name,
                            **common,
                            id=target,
                            to=payload.get("to") or (),
                            body=payload.get("body") or payload.get("note"),
                        )
                    elif tool.op == "transition":
                        result = emulator.call(
                            tool_name,
                            **common,
                            id=target,
                            state=payload.get("state"),
                        )
                    elif tool.op == "delete":
                        result = emulator.call(tool_name, **common, id=target)
                    elif tool.op == "transform":
                        result = emulator.call(
                            tool_name,
                            **common,
                            id=target,
                            format=payload.get("format") or payload.get("fmt"),
                            dest=payload.get("dest"),
                        )
                    elif tool.op == "invoke":
                        raise ValueError(
                            f"{server}.{tool_name} declares invoke but no generic invocation result contract"
                        )
                    else:
                        raise ValueError(f"unsupported connector operation {tool.op!r}")
                    collect(emulator.trace[-1])
                    if isinstance(result, Mapping):
                        made.append(
                            result.get("id")
                            or result.get("key")
                            or result.get("number")
                            or target
                        )
        except ConnectorError as error:
            collect(emulator.trace[-1])
            if error.code == 403:
                behaviors.append("denial_surfaced")
            elif error.code == 404 or error.kind == "not_found":
                behaviors.append("report_not_found")
            elif error.kind in {"timeout", "rate_limit"}:
                behaviors.append("branch_failed")
            else:
                behaviors.append("validation_error")
        node_span_ids[node_id] = [span.id for span in spans[before:]]
        outputs[node_id] = made

        flags = set(node.get("flags", ()))
        if flags & {"ambiguous", "misattributed_system"}:
            behaviors.append("clarify")
            stopped = True

    post_state: dict[str, Mapping[str, Any]] = {}
    for emulator in emulators.values():
        post_state.update(emulator.records)
    grade = grade_trace(
        spans,
        row,
        post_state=post_state,
        behaviors=behaviors,
        shape=shape,
    )
    return EvalRuntimeResult(
        grade=grade,
        spans=tuple(spans),
        behaviors=tuple(behaviors),
        post_state=post_state,
    )


__all__ = ["EvalRuntimeResult", "run_eval_row"]
