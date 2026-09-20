"""Compile enterprise fixture failures once for both connector execution paths."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from .connector_definition import ConnectorDefinition
from .connector_emulator import ConnectorEmulator
from .enterprise_corpus import StateOverride
from .ids import content_key

_SOURCE_KINDS = frozenset({"ambiguous_join", "missing_stable_id", "stale_source"})
_WRITE_KINDS = frozenset({"permission_denied", "version_conflict", "partial_write"})
_READ_OPS = frozenset({"get", "read", "search", "extract", "download", "readback", "cross_system"})
_STABLE_FIELDS = ("stable_id", "key", "sys_id", "id", "page_id", "item_id", "file_id", "message_id", "thread_id")


def build_query_emulator(
    definition: ConnectorDefinition,
    records: Iterable[Mapping[str, Any]],
    *,
    overrides: Iterable[StateOverride | Mapping[str, Any]] = (),
    mutation_nodes: Iterable[Mapping[str, Any]] = (),
    query_id: str = "",
    acl: Mapping[str, Mapping[str, Any]] | None = None,
) -> ConnectorEmulator:
    """Create query-isolated state with connector- and node-scoped injections.

    A destination create has no record to deny. A wildcard connector fault also
    denies its source reads, so the fault must name the write node. Existing
    targets are checked eagerly: a foreign fid is a broken fixture, never an
    injection silently skipped by the emulator.
    """
    materialized = [deepcopy(dict(record)) for record in records]
    by_id = {
        str(record["fid"]): record
        for record in materialized
        if record.get("fid") and record.get("server", definition.connector) == definition.connector
    }
    nodes = tuple(node for node in mutation_nodes if node.get("server", node.get("connector")) == definition.connector)
    faults: dict[str, tuple[str, ...]] = {}
    permissions = {fid: dict(value) for fid, value in (acl or {}).items()}

    def add_fault(node_id: str, kind: str) -> None:
        key = f"@node:{node_id}"
        faults[key] = (*faults.get(key, ()), kind)

    for raw in overrides:
        override = raw if isinstance(raw, StateOverride) else StateOverride.model_validate(raw)
        if override.connector != definition.connector:
            continue
        target = by_id.get(override.record_id) if override.record_id is not None else None
        if override.record_id is not None and target is None:
            raise ValueError(f"override {override.kind} targets absent {definition.connector} record {override.record_id}")
        if override.kind in _SOURCE_KINDS and target is None:
            raise ValueError(f"source override {override.kind} requires a record")
        if override.kind == "stale_source" and target is not None:
            fields = target.get("fields")
            source = fields if isinstance(fields, dict) else target
            source["version"] = max(0, int(source.get("version", 1)) - 1)
            target["version"] = source["version"]
        elif override.kind == "ambiguous_join" and target is not None:
            duplicate = deepcopy(target)
            duplicate_id = content_key("ambiguous-enterprise-record", query_id, str(override.record_id))
            duplicate.update(fid=duplicate_id, ident=duplicate_id, external_id=duplicate_id)
            materialized.append(duplicate)
        elif override.kind == "missing_stable_id" and target is not None:
            fields = target.get("fields")
            for field in _STABLE_FIELDS:
                target.pop(field, None)
                if isinstance(fields, dict):
                    fields.pop(field, None)
            matching = [
                node for node in nodes
                if str(node.get("op", node.get("kind", ""))) in _READ_OPS
                and (
                    override.record_id in (set(node.get("fixtures", ())) | {node.get("fixture")})
                    or (not node.get("fixture") and not node.get("fixtures") and not node.get("depends_on")
                    and str(node.get("op", node.get("kind", ""))) not in {"readback", "cross_system"}
                    and definition.entity_matches(str(node.get("entity", "")), str(target.get("entity", ""))))
                )
            ]
            for node in matching:
                add_fault(str(node["id"]), override.kind)
        elif override.kind in _WRITE_KINDS:
            # The named node is the planned failure point, not an access-control
            # boundary. External agents can call another tool or omit `_node`.
            if override.record_id is not None:
                key = f"@record_write:{override.record_id}"
                faults[key] = (*faults.get(key, ()), override.kind)
                if override.kind == "permission_denied":
                    permissions[override.record_id] = {**permissions.get(override.record_id, {}), "readonly": True}
            else:
                faults["@write"] = (*faults.get("@write", ()), override.kind)
            writes = [
                node for node in nodes
                if str(node.get("op", node.get("kind", ""))) not in _READ_OPS
                and (node.get("fixture") in (None, override.record_id) or override.record_id is None)
            ]
            if not writes:
                raise ValueError(f"override {override.kind} has no mutation node on {definition.connector}")
            for node in writes:
                add_fault(str(node["id"]), override.kind)
        elif override.kind not in _SOURCE_KINDS:
            raise ValueError(f"unknown enterprise failure override {override.kind!r}")
    return ConnectorEmulator(definition, materialized, acl=permissions, faults=faults)


__all__ = ["build_query_emulator", "compile_failure_contract"]


def compile_failure_contract(row: Mapping[str, Any]) -> dict[str, Any]:
    """State expected failures explicitly and remove unreachable obligations.

    Every accepted error names its exact node and kind. Only that node's
    descendants become optional; a failure cannot excuse an independent branch
    or make a different connector error pass.
    """
    compiled = deepcopy(dict(row))
    dag = compiled.get("expected_dag", {})
    nodes = dag.get("nodes", ())
    edges = dag.get("edges", ())
    failures: dict[str, str] = {}
    for raw in compiled.get("state_overrides", ()):
        override = StateOverride.model_validate(raw)
        if override.kind not in _WRITE_KINDS | {"missing_stable_id"}:
            continue
        for node in nodes:
            if node.get("server", node.get("connector")) != override.connector:
                continue
            op = str(node.get("op", node.get("kind", "")))
            source_ids = set(node.get("fixtures", ())) | {node.get("fixture")}
            if override.kind == "missing_stable_id":
                selected = op in _READ_OPS and override.record_id in source_ids
            else:
                selected = op not in _READ_OPS and (node.get("fixture") in (None, override.record_id) or override.record_id is None)
            if selected:
                failures[str(node["id"])] = "denied" if override.kind == "permission_denied" else override.kind
    descendants: set[str] = set()
    frontier = set(failures)
    while frontier:
        next_nodes = {str(target) for source, target in edges if str(source) in frontier} - descendants
        descendants.update(next_nodes)
        frontier = next_nodes
    for node in nodes:
        if str(node["id"]) in descendants:
            node["optional"] = True
    original = list(compiled.get("assertions", ()))
    by_node = {str(node["id"]): node for node in nodes}
    for node_id, kind in sorted(failures.items()):
        if node_id in descendants:
            continue
        node = by_node[node_id]
        blocked: set[str] = set()
        frontier = {node_id}
        while frontier:
            next_nodes = {str(target) for source, target in edges if str(source) in frontier} - blocked
            blocked.update(next_nodes)
            frontier = next_nodes
        assertion: dict[str, Any] = {
            "type": "failure_at", "node": node_id, "kind": kind,
            "writes_persist": kind == "partial_write", "blocked_nodes": sorted(blocked),
        }
        operation = node.get("resolved_operation", node.get("op"))
        creates = operation in {"create", "send", "draft", "post", "upload", "reply", "forward", "transform"}
        if node.get("fixture") and not creates:
            assertion["fixture"] = node["fixture"]
        elif kind == "partial_write" and creates:
            # Only a write that makes a record has a created record to check.
            # A delete or update whose id is bound from an earlier read has
            # no fixture here and makes nothing; its persisted effect is
            # graded by the `deleted` or state assertion that names it.
            created: dict[str, Any] = {"server": node.get("server"), "entity": node.get("entity")}
            relation = {"reply": "reply_to", "forward": "forwarded_from", "transform": "derived_from"}.get(str(operation))
            if relation and node.get("fixture"):
                created[relation] = node["fixture"]
            else:
                created["name"] = (node.get("payload") or {}).get("name")
            assertion["created_record"] = created
        original.append(assertion)
    compiled["assertions"] = original
    return compiled
