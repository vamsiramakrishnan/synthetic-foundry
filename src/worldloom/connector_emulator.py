"""One executable connector engine parameterised by a ConnectorDefinition.

No product behavior belongs here. Tool names, entity membership, paging, native
queries, workflow states, required fields, ACL model, errors, idempotency and
payload shape all come from the definition. The engine only interprets that
contract over canonical corpus records.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .connector_data import ConnectorRecord
from .connector_definition import ConnectorDefinition, ConnectorToolDefinition
from .connector_payload import shape_payload
from .connector_query import parse_native
from .ids import content_key
from .predicates import FieldPredicate, Predicate, PredicateOp, evaluate


class ConnectorError(RuntimeError):
    def __init__(self, code: int, message: str, kind: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.kind = kind


@dataclass(frozen=True)
class ConnectorSpan:
    id: str
    ordinal: int
    node: str | None
    tool: str
    args: dict[str, Any]
    consumed_from: tuple[str, ...]
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    items: int
    bytes: int
    error: dict[str, Any] | None
    actor: str


@dataclass
class _PendingSpan:
    id: str
    ordinal: int
    node: str | None
    tool: str
    args: dict[str, Any]
    consumed_from: tuple[str, ...]
    reads: list[str]
    writes: list[str]
    items: int
    bytes: int
    error: dict[str, Any] | None
    actor: str

    def freeze(self) -> ConnectorSpan:
        return ConnectorSpan(
            id=self.id,
            ordinal=self.ordinal,
            node=self.node,
            tool=self.tool,
            args=self.args,
            consumed_from=self.consumed_from,
            reads=tuple(self.reads),
            writes=tuple(self.writes),
            items=self.items,
            bytes=self.bytes,
            error=self.error,
            actor=self.actor,
        )


def _canonical_record(record: ConnectorRecord | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, ConnectorRecord):
        return {
            **copy.deepcopy(record.fields),
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
    return copy.deepcopy(dict(record))


def _coerce_predicate(value: Predicate | Mapping[str, Any] | None, *, entity: str | None) -> Predicate:
    if value is None:
        return Predicate(entity=entity)
    if isinstance(value, Predicate):
        if entity is None or value.entity is None or value.entity == entity:
            return value if value.entity is not None else value.model_copy(update={"entity": entity})
        raise ValueError(f"predicate entity {value.entity!r} does not match {entity!r}")
    clauses: list[FieldPredicate] = []
    op_map = {
        "=": PredicateOp.EQ,
        "==": PredicateOp.EQ,
        "eq": PredicateOp.EQ,
        "!=": PredicateOp.NE,
        "ne": PredicateOp.NE,
        ">": PredicateOp.GT,
        "gt": PredicateOp.GT,
        ">=": PredicateOp.GTE,
        "gte": PredicateOp.GTE,
        "<": PredicateOp.LT,
        "lt": PredicateOp.LT,
        "<=": PredicateOp.LTE,
        "lte": PredicateOp.LTE,
        "in": PredicateOp.IN,
        "contains": PredicateOp.CONTAINS,
    }
    for field, raw in sorted(value.items()):
        if isinstance(raw, (list, tuple)) and len(raw) == 2 and isinstance(raw[0], str):
            try:
                op = op_map[raw[0].lower()]
            except KeyError as error:
                raise ValueError(f"unsupported predicate operator {raw[0]!r}") from error
            operand: Any = raw[1]
            if op is PredicateOp.IN and isinstance(operand, list):
                operand = tuple(operand)
            clauses.append(FieldPredicate(field=field, op=op, value=operand))
        else:
            clauses.append(FieldPredicate(field=field, value=raw))
    return Predicate(entity=entity, where=tuple(clauses))


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))


class ConnectorEmulator:
    """Copy-on-write execution surface for one connector definition."""

    def __init__(
        self,
        definition: ConnectorDefinition,
        records: Iterable[ConnectorRecord | Mapping[str, Any]],
        *,
        acl: Mapping[str, Mapping[str, Any]] | None = None,
        faults: Mapping[str, Sequence[str]] | None = None,
        actor: str = "agent",
    ) -> None:
        self.definition = definition
        self.server = definition.connector
        canonical = (_canonical_record(record) for record in records)
        self.records = {
            str(record["fid"]): record
            for record in canonical
            if str(record.get("server") or self.server) == self.server
        }
        self.by_entity: dict[str, list[str]] = defaultdict(list)
        self.by_ident: dict[str, str] = {}
        for fid, record in self.records.items():
            entity = str(record.get("entity") or "record")
            self.by_entity[entity].append(fid)
            for key in ("ident", "external_id", "name", "title"):
                if record.get(key) not in (None, ""):
                    self.by_ident[str(record[key])] = fid
        self.acl = {key: dict(value) for key, value in (acl or {}).items()}
        self.faults = {key: tuple(value) for key, value in (faults or {}).items()}
        self.actor = actor
        self.trace: list[ConnectorSpan] = []
        self._call_ordinal = 0
        self._created = 0
        self._recent_creates: dict[tuple[Any, ...], str] = {}

    def fork(self) -> ConnectorEmulator:
        child = ConnectorEmulator.__new__(ConnectorEmulator)
        child.definition = self.definition
        child.server = self.server
        child.records = copy.deepcopy(self.records)
        child.by_entity = defaultdict(list, {key: list(value) for key, value in self.by_entity.items()})
        child.by_ident = dict(self.by_ident)
        child.acl = copy.deepcopy(self.acl)
        child.faults = dict(self.faults)
        child.actor = self.actor
        child.trace = []
        child._call_ordinal = 0
        child._created = 0
        child._recent_creates = {}
        return child

    def snapshot(self) -> str:
        payload = json.dumps(
            self.records,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:20]

    def _error(self, kind: str, **fmt: Any) -> ConnectorError:
        try:
            code, template = self.definition.errors[kind]
        except KeyError as error:
            raise ConnectorError(400, kind, kind) from error
        try:
            message = template.format(**fmt)
        except KeyError:
            message = template
        return ConnectorError(code, message, kind)

    def resolve(self, reference: Any) -> str:
        raw = str(reference)
        if raw in self.records:
            return raw
        if raw in self.by_ident:
            return self.by_ident[raw]
        folded = raw.casefold().removeprefix("case ")
        for ident, fid in self.by_ident.items():
            candidate = ident.casefold().removeprefix("case ")
            if candidate == folded:
                return fid
        raise self._error("not_found", id=raw)

    def _acl_entry(self, fid: str) -> Mapping[str, Any]:
        return self.acl.get(fid, {})

    def _visible(self, fid: str) -> bool:
        acl = self._acl_entry(fid)
        return not bool(acl.get("denied") or acl.get("hidden"))

    def _check_acl(self, fid: str, op: str) -> None:
        acl = self._acl_entry(fid)
        if not self._visible(fid):
            raise self._error("denied")
        if op in {"update", "transition", "comment", "delete", "transform"} and (
            acl.get("readonly") or acl.get("locked")
        ):
            raise self._error("denied")
        if (
            op in {"update", "comment"}
            and acl.get("archived")
            and self.definition.acl.archived_blocks_edit
        ):
            raise self._error("denied")

    def _pool(self, entity: str | None, tool: ConnectorToolDefinition) -> list[dict[str, Any]]:
        requested = tuple(tool.entities) if entity is None else (entity,)
        allowed = set(tool.entities)
        pool_ids: list[str] = []
        for requested_entity in requested:
            try:
                members = self.definition.entity_members(requested_entity)
            except KeyError as error:
                raise ConnectorError(400, f"Unknown entity '{requested_entity}'", "validation") from error
            if not set(members).issubset(allowed) and requested_entity not in allowed:
                raise ConnectorError(
                    400,
                    f"Entity '{requested_entity}' is not supported by this tool",
                    "validation",
                )
            # Old Worldloom projections can themselves carry an alias name such
            # as `issue`/`file`; include those records while specific new corpora
            # use the canonical member names.
            pool_ids.extend(self.by_entity.get(requested_entity, ()))
            for member in members:
                pool_ids.extend(self.by_entity.get(member, ()))
        seen: set[str] = set()
        return [
            self.records[fid]
            for fid in pool_ids
            if not (fid in seen or seen.add(fid)) and self._visible(fid)
        ]

    def _record_for_predicate(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **record,
            "id": record.get("fid"),
            "external_id": record.get("external_id") or record.get("ident"),
            "title": record.get("title") or record.get("name"),
            "connector": self.server,
        }

    def call(self, tool_name: str, **args: Any) -> Any:
        self._call_ordinal += 1
        canonical_name = self.definition.canonical_tool(tool_name)
        tool = self.definition.tool(canonical_name)
        node = args.pop("_node", None)
        consumed = tuple(args.pop("_consumed", ()))
        span = _PendingSpan(
            id=f"s{self._call_ordinal}",
            ordinal=self._call_ordinal,
            node=node,
            tool=f"{self.server}.{canonical_name}",
            args=copy.deepcopy(args),
            consumed_from=consumed,
            reads=[],
            writes=[],
            items=0,
            bytes=0,
            error=None,
            actor=self.actor,
        )
        try:
            active_faults = self.faults.get(canonical_name, ()) + self.faults.get("*", ())
            if "timeout" in active_faults:
                raise ConnectorError(504, "Gateway timeout", "timeout")
            if "rate_limit_429" in active_faults:
                raise ConnectorError(429, "Too many requests", "rate_limit")
            operation = getattr(self, f"_op_{tool.op}")
            result = operation(tool, span, **args)
            span.bytes = _json_bytes(result)
            return result
        except ConnectorError as error:
            span.error = {"code": error.code, "message": error.message, "kind": error.kind}
            raise
        finally:
            self.trace.append(span.freeze())

    def _op_search(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        query: str | None = None,
        predicate: Predicate | Mapping[str, Any] | None = None,
        fields: Sequence[str] | None = None,
        max_results: int | None = None,
        start_at: int = 0,
        entity: str | None = None,
        name: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if start_at < 0:
            raise ConnectorError(400, "start_at must be non-negative", "validation")
        active: Predicate | None = None
        if query and predicate is None:
            try:
                active = parse_native(self.definition, query, entity=entity)
            except ValueError as error:
                raise ConnectorError(400, str(error), "validation") from error
        elif predicate is not None:
            active = _coerce_predicate(predicate, entity=entity)
        pool = self._pool(entity, tool)
        if name is not None:
            hits = [
                record
                for record in pool
                if str(record.get("name")) == str(name)
                or str(record.get("ident")) == str(name)
            ]
        elif active is not None:
            hits = [
                record
                for record in pool
                if evaluate(
                    active,
                    self._record_for_predicate(record),
                    entity=str(record.get("entity")),
                )
            ]
        else:
            hits = pool
        requested = max_results or tool.page_size
        limit = min(requested, tool.page_size, tool.max_results)
        page = hits[start_at : start_at + limit]
        active_faults = self.faults.get(self.definition.canonical_tool(span.tool.split(".", 1)[1]), ())
        if "partial_page" in active_faults and len(page) > 2:
            page = page[:-1]
        span.reads.extend(str(record["fid"]) for record in page)
        span.items = len(page)
        return {
            "total": len(hits),
            "start_at": start_at,
            "max_results": limit,
            "is_last": start_at + limit >= len(hits),
            "native_query": query,
            "items": [shape_payload(self.definition, record, fields) for record in page],
        }

    def _op_get(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        fields: Sequence[str] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        fid = self.resolve(id)
        self._check_acl(fid, "get")
        record = self.records[fid]
        if not any(
            record.get("entity") == entity
            or self.definition.entity_matches(entity, str(record.get("entity")))
            for entity in tool.entities
        ):
            raise self._error("not_found", id=id)
        span.reads.append(fid)
        span.items = 1
        result = shape_payload(self.definition, record, fields)
        active_faults = self.faults.get(span.tool.split(".", 1)[1], ())
        if "truncated_content" in active_faults and isinstance(result.get("content"), str):
            content = result["content"]
            result["content"] = content[: max(1, len(content) // 3)]
            result["truncated"] = True
        return result

    def _provided_create_values(
        self,
        entity: str,
        name: str | None,
        parent: str | None,
        fields: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "entity": entity,
            "name": name,
            "title": name,
            "summary": name,
            "Name": name,
            "Subject": name,
            "short_description": name,
            "parent": parent,
            "parents": parent,
            "issuetype": entity,
            **fields,
        }

    def _op_create(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        entity: str | None = None,
        name: str | None = None,
        fields: Mapping[str, Any] | None = None,
        parent: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        selected = entity or tool.entities[0]
        try:
            members = self.definition.entity_members(selected)
        except KeyError as error:
            raise ConnectorError(400, f"Unknown entity '{selected}'", "validation") from error
        if len(members) != 1:
            raise ConnectorError(
                400,
                f"Create requires one concrete entity, not alias '{selected}'",
                "validation",
            )
        selected = members[0]
        if selected not in tool.entities:
            raise ConnectorError(400, f"Entity '{selected}' is not supported by this tool", "validation")
        values = self._provided_create_values(selected, name, parent, dict(fields or {}))
        entity_definition = self.definition.entities[selected]
        for required in entity_definition.required_on_create:
            if values.get(required) in (None, "", [], {}):
                raise self._error("validation", field=required)
        if tool.idempotency is not None:
            key = tuple(values.get(part) for part in tool.idempotency.key)
            replay = self._recent_creates.get((selected, *key))
            if replay is not None:
                span.writes.append(replay)
                span.items = 1
                result = shape_payload(self.definition, self.records[replay])
                result["idempotent_replay"] = True
                return result
        self._created += 1
        fid = f"new:{self.server[:2]}:{selected}:{self._created}"
        record = {
            "fid": fid,
            "server": self.server,
            "entity": selected,
            "name": name,
            "title": name,
            "ident": self._mint_ident(selected, values),
            "parent": parent,
            "created_by": self.actor,
            "created_at": self.definition.clock,
            "modified_at": self.definition.clock,
            **dict(fields or {}),
        }
        workflow = entity_definition.workflow
        if workflow is not None:
            record[workflow.field] = workflow.states[0]
        self.records[fid] = record
        self.by_entity[selected].append(fid)
        for value in (record.get("ident"), name):
            if value not in (None, ""):
                self.by_ident[str(value)] = fid
        if tool.idempotency is not None:
            key = tuple(values.get(part) for part in tool.idempotency.key)
            self._recent_creates[(selected, *key)] = fid
        span.writes.append(fid)
        span.items = 1
        return shape_payload(self.definition, record)

    def _validate_update(
        self,
        fid: str,
        fields: Mapping[str, Any],
        *,
        transition_only: bool = False,
    ) -> None:
        record = self.records[fid]
        entity = str(record.get("entity"))
        try:
            entity_definition = self.definition.entities[entity]
        except KeyError:
            return
        for rule in self.definition.validation_rules.get(entity, ()):
            if all(record.get(key) == value for key, value in rule.when.items()) and any(
                field in fields for field in rule.locked
            ):
                raise ConnectorError(400, rule.message, "validation")
        workflow = entity_definition.workflow
        if workflow is None:
            if transition_only:
                raise self._error("bad_transition", state=fields.get("state"))
            return
        if workflow.field not in fields:
            if transition_only:
                raise self._error("bad_transition", state=fields.get("state"))
            return
        current = workflow.canonical_state(str(record.get(workflow.field, workflow.states[0])))
        target = workflow.canonical_state(str(fields[workflow.field]))
        if target not in workflow.states:
            raise self._error("bad_transition", state=target)
        if workflow.strict and target not in workflow.transitions.get(current, ()) and target != current:
            raise self._error("bad_transition", state=target)

    def _op_update(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        fields: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        fid = self.resolve(id)
        self._check_acl(fid, "update")
        patch = dict(fields or {})
        self._validate_update(fid, patch)
        record = copy.deepcopy(self.records[fid])
        record.update(patch)
        record["modified_at"] = self.definition.clock
        record.setdefault("updates", []).append(patch)
        self.records[fid] = record
        span.writes.append(fid)
        span.items = 1
        return shape_payload(self.definition, record)

    def _op_transition(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        state: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        fid = self.resolve(id)
        self._check_acl(fid, "transition")
        record = self.records[fid]
        entity = str(record.get("entity"))
        definition = self.definition.entities.get(entity)
        if definition is None or definition.workflow is None or state is None:
            raise self._error("bad_transition", state=state)
        patch = {definition.workflow.field: state}
        self._validate_update(fid, patch, transition_only=True)
        updated = copy.deepcopy(record)
        updated.update(patch)
        updated["modified_at"] = self.definition.clock
        self.records[fid] = updated
        span.writes.append(fid)
        span.items = 1
        return shape_payload(self.definition, updated)

    def _op_comment(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        body: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        fid = self.resolve(id)
        self._check_acl(fid, "comment")
        record = copy.deepcopy(self.records[fid])
        record.setdefault("comments_added", []).append(
            {"body": body or "", "author": self.actor, "at": self.definition.clock}
        )
        record["modified_at"] = self.definition.clock
        self.records[fid] = record
        span.writes.append(fid)
        span.items = 1
        return shape_payload(self.definition, record)

    def _op_transform(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        format: str | None = None,
        dest: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        fid = self.resolve(id)
        self._check_acl(fid, "transform")
        source = self.records[fid]
        target_entity = format if format in self.definition.entities else str(source.get("entity"))
        create_tools = [
            candidate
            for candidate in self.definition.tools.values()
            if candidate.op == "create" and target_entity in candidate.entities
        ]
        if not create_tools:
            raise ConnectorError(400, f"No create tool for transform target {target_entity}", "validation")
        return self._op_create(
            create_tools[0],
            span,
            entity=target_entity,
            name=f"{source.get('name') or fid}.{format or 'copy'}",
            fields={"derived_from": fid},
            parent=dest,
        )

    def _op_delete(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        **_: Any,
    ) -> dict[str, Any]:
        fid = self.resolve(id)
        self._check_acl(fid, "delete")
        record = self.records.pop(fid)
        entity = str(record.get("entity"))
        self.by_entity[entity] = [candidate for candidate in self.by_entity[entity] if candidate != fid]
        self.by_ident = {key: value for key, value in self.by_ident.items() if value != fid}
        span.writes.append(fid)
        span.items = 1
        return {"deleted": fid}

    def _mint_ident(self, entity: str, values: Mapping[str, Any]) -> str:
        self._created = max(1, self._created)
        n = 5_000 + self._created
        pattern = self.definition.id.pattern
        if "{project}" in pattern:
            return pattern.replace("{project}", str(values.get("project") or "WL")).replace("{n}", str(n))
        if "{7d}" in pattern:
            return pattern.replace("{7d}", f"{n:07d}")
        if pattern == "18char":
            return hashlib.sha1(f"{self.server}:{entity}:{n}".encode()).hexdigest()[:15].upper() + "AAA"
        if pattern == "numeric":
            return str(900_000 + n)
        if pattern == "slack_timestamp":
            return f"{1_800_000_000 + n}.000001"
        if pattern.startswith("ari:cloud:"):
            return f"ari:cloud:worldloom::{entity}/{content_key(self.server, entity, n)[:16]}"
        return content_key(self.server, entity, n)[:34]


__all__ = ["ConnectorEmulator", "ConnectorError", "ConnectorSpan"]
