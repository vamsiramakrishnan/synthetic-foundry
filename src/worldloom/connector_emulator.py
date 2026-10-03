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
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .connector_data import ConnectorRecord
from .connector_definition import ConnectorDefinition, ConnectorToolDefinition
from .connector_keys import SHAPED_IDENTITY_KEYS, freeze_key
from .connector_payload import shape_payload
from .connector_query import parse_native
from .ids import content_key
from .predicates import FieldPredicate, Predicate, PredicateOp, evaluate

if TYPE_CHECKING:
    from .evalrun.retrieval import ControlledRetrieval

#: The keys a product-shaped payload may carry its identity under
#: (``connector_keys``): the identity set ``shape_payload`` preserves under
#: projection, minus the non-scalar ones that are not handles.
_SHAPED_IDENTITY_KEYS = SHAPED_IDENTITY_KEYS


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
            # A record that names itself (a rendered SharePoint or Drive file:
            # `fields.name` is its file name, as the products' `name` is) keeps
            # that name; the title is the name only of a record with none. The
            # compiled row's snapshot reads the same key
            # (`enterprise_rows.runtime_records`), and when this overwrote it
            # with the title every search over a rendered file graded
            # `result_mismatch` for the reference agent itself.
            "name": record.fields.get("name") or record.title,
            "title": record.title,
            "fact_ids": list(record.fact_ids),
            "event_ids": list(record.event_ids),
            "source_artifact_ids": list(record.source_artifact_ids),
        }
    return copy.deepcopy(dict(record))


def _coerce_predicate(value: Predicate | Mapping[str, Any] | None, *, entity: str | None) -> Predicate:
    if value is None:
        return Predicate(entity=entity)
    if isinstance(value, Mapping) and "where" in value:
        value = Predicate.model_validate(value)
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


#: The two ways a search tool can execute a ``query`` string. ``native`` is the
#: vendor-language evaluator in ``worldloom.connectors.query`` and the default
#: (policy ``connectors.query.engine``): a pilot's call errors were mostly
#: valid vendor queries (SOQL ``ORDER BY ... LIMIT``, ServiceNow ``ORDERBY``,
#: JQL ``OR``) that the historical parser refused. ``predicate`` is that
#: historical conjunctive subset (``connector_query.parse_native``), still
#: selectable for a run that must reproduce an older ledger.
QUERY_ENGINES = ("predicate", "native")


def _query_engine(stated: str | None) -> str:
    """The engine a new emulator uses: *stated*, else the policy ``connectors.query.engine``."""

    if stated is None:
        from . import packkit

        try:
            stated = str(packkit.policy("connectors.query.engine"))
        except KeyError:
            stated = "native"
    if stated not in QUERY_ENGINES:
        raise ValueError(f"unknown query engine {stated!r}; expected one of {', '.join(QUERY_ENGINES)}")
    return stated


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
        query_engine: str | None = None,
        retrieval: ControlledRetrieval | None = None,
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
            self._index_references(fid, record)
        self.acl = {key: dict(value) for key, value in (acl or {}).items()}
        self.faults = {key: tuple(value) for key, value in (faults or {}).items()}
        self.actor = actor
        self.query_engine = _query_engine(query_engine)
        self.trace: list[ConnectorSpan] = []
        self._call_ordinal = 0
        self._created = 0
        self._recent_creates: dict[tuple[Any, ...], str] = {}
        self.retrieval = retrieval
        if self.retrieval is not None:
            self.retrieval.bind(definition)

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
        child.query_engine = self.query_engine
        child.trace = []
        child._call_ordinal = 0
        child._created = 0
        child._recent_creates = {}
        child.retrieval = self.retrieval.fork() if self.retrieval is not None else None
        return child

    def transaction(self, *, fresh: bool = False) -> ConnectorEmulator:
        """A copy one call may change, for the caller to commit or drop.

        Every handler replaces a record rather than changing it in place (an
        update deep-copies the record it patches), so the copy shares the
        record dicts and copies only the containers a call changes: the
        record map, the entity and identifier indexes, the idempotency keys
        and the trace. Deep-copying the whole state for every tool call was
        most of an evalrun on a company with tens of thousands of records.
        `fresh` starts the copy with an empty trace and counters, as `fork`
        does, for a new run over the same state.
        """
        child = copy.copy(self)
        child.records = dict(self.records)
        child.by_entity = defaultdict(list, {key: list(value) for key, value in self.by_entity.items()})
        child.by_ident = dict(self.by_ident)
        child._recent_creates = dict(self._recent_creates)
        child.trace = [] if fresh else list(self.trace)
        child.retrieval = self.retrieval.fork(fresh=fresh) if self.retrieval is not None else None
        if fresh:
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
        except (KeyError, IndexError, ValueError, AttributeError):
            # An uploaded connector's error text is data: one that does not
            # format is shown as written rather than escaping the emulator.
            message = template
        return ConnectorError(code, message, kind)

    def _index_references(self, fid: str, record: Mapping[str, Any]) -> None:
        """Every name a caller may legitimately hand back for this record.

        The canonical keys first; then the connector's *native* id, which is
        the one the emulator itself emits. ``shape_payload`` mints a
        product-shaped id per record (Jira's numeric issue id, a Confluence
        page id, a ServiceNow ``sys_id``) and every search page and read reply
        carries it — so an agent that does what a real agent does, feeding an
        item's ``id`` from one page into the next tool, was refused with
        ``not_found`` by the very emulator that had just returned that id.
        ``tests/test_connector_eval_runtime.py`` caught it on a two-item
        Jira ``for_each``: the runtime prefers ``item["id"]`` over ``key``,
        exactly as a trace would, and ``add_comment`` 404'd on both.

        Ident-style keys stay ahead of the native id in ``resolve`` only by
        insertion order; the two never collide, because a native id is a
        content address of the fid and an ident is a product key.
        """
        for key in ("ident", "external_id", "name", "title"):
            if record.get(key) not in (None, ""):
                self.by_ident[str(record[key])] = fid
        # Every identity a shaped payload can carry, not only ``id``: ServiceNow
        # answers with ``sys_id`` and ``number``, Salesforce with ``Id``, Slack
        # with ``ts``, Jira with ``key`` beside ``id``. Indexing ``id`` alone
        # left ServiceNow exactly where it was, ``search_records`` handing out
        # a ``sys_id`` that ``get_record`` refused; a review caught it on the
        # first fix.
        shaped = shape_payload(self.definition, record)
        for key in _SHAPED_IDENTITY_KEYS:
            native = shaped.get(key)
            if isinstance(native, (str, int)) and not isinstance(native, bool) and native != "":
                self.by_ident.setdefault(str(native), fid)

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
        if entity is None:
            # A search that names no type (a vendor's JQL through its
            # contract takes none) covers every record the tool handles,
            # those stored under an alias the tool's types make up included:
            # an `issue` record is a Jira issue whichever query finds it.
            for alias, members in sorted(self.definition.entity_aliases.items()):
                if set(members) <= allowed:
                    pool_ids.extend(self.by_entity.get(alias, ()))
        seen: set[str] = set()
        visible: list[dict[str, Any]] = []
        for fid in pool_ids:
            if fid in seen:
                continue
            seen.add(fid)
            if self._visible(fid):
                visible.append(self.records[fid])
        return visible

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
        result: Any = None
        try:
            if self.retrieval is not None:
                self.retrieval.before_call(canonical_name)
            write_ops = {
                "create",
                "update",
                "move",
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
            active_faults = self.faults.get(canonical_name, ()) + self.faults.get("*", ()) + self.faults.get(f"@node:{node}", ())
            if tool.op in write_ops:
                active_faults += self.faults.get("@write", ())
            if args.get("id") is not None:
                try:
                    fault_record = self.resolve(args["id"])
                except ConnectorError:
                    pass  # The operation owns its normal not-found response.
                else:
                    active_faults += self.faults.get(f"@record:{fault_record}", ())
                    if tool.op in write_ops:
                        active_faults += self.faults.get(f"@record_write:{fault_record}", ())
            if "timeout" in active_faults:
                raise ConnectorError(504, "Gateway timeout", "timeout")
            if "rate_limit_429" in active_faults:
                raise ConnectorError(429, "Too many requests", "rate_limit")
            if "missing_stable_id" in active_faults:
                raise ConnectorError(422, "Source record has no stable identifier", "missing_stable_id")
            if "permission_denied" in active_faults:
                raise self._error("denied")
            if tool.op in write_ops and "version_conflict" in active_faults:
                raise ConnectorError(409, "Version conflict", "version_conflict")
            handler_op = {
                "send": "create",
                "post": "create",
                "upload": "create",
                "download": "get",
            }.get(tool.op, tool.op)
            operation = getattr(self, f"_op_{handler_op}")
            result = operation(tool, span, **args)
            if tool.op in write_ops and "partial_write" in active_faults:
                # The side effect committed but the operation did not finish
                # successfully. Preserve writes and post-state for reconciliation;
                # raising before the handler was a refusal, not a partial write.
                raise ConnectorError(207, "Write applied; completion failed", "partial_write")
            span.bytes = _json_bytes(result)
            return result
        except ConnectorError as error:
            span.error = {"code": error.code, "message": error.message, "kind": error.kind}
            raise
        finally:
            frozen = span.freeze()
            self.trace.append(frozen)
            if self.retrieval is not None:
                self.retrieval.observe(frozen, result, self.records)

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
        if max_results is not None and max_results < 1:
            raise ConnectorError(400, "max_results must be positive", "validation")
        controlled = self.retrieval is not None and self.retrieval.applies(span.tool.split(".", 1)[1])
        active: Predicate | None = None
        native = (
            self._native_search(tool, span.tool.split(".", 1)[1], query, entity)
            if not controlled and query and predicate is None and name is None and self.query_engine == "native"
            else None
        )
        if controlled:
            from .evalrun.retrieval import UnsupportedControlledQuery

            assert self.retrieval is not None
            try:
                active = self.retrieval.parse(query=query, predicate=predicate, entity=entity, name=name)
                pool = self._pool(active.entity or entity, tool)
                hits = self.retrieval.select(active, [self._record_for_predicate(record) for record in pool])
            except UnsupportedControlledQuery as error:
                raise ConnectorError(400, str(error), "unsupported_query") from error
            except ValueError as error:
                raise ConnectorError(400, str(error), "validation") from error
        elif native is not None:
            hits, projection = native
            fields = fields or projection or None
        elif query and predicate is None:
            try:
                active = parse_native(self.definition, query, entity=entity)
            except ValueError as error:
                raise ConnectorError(400, str(error), "validation") from error
        elif predicate is not None:
            active = _coerce_predicate(predicate, entity=entity)
        if active is not None and active.entity is not None and active.entity not in self.definition.entities:
            # The requested entity is an alias (`file` over docx, xlsx, ...).
            # The pool below already holds exactly its members, and a
            # predicate carrying the alias name would match none of them —
            # every `where` search under an alias returned nothing until this.
            active = active.model_copy(update={"entity": None})
        if native is None and not controlled:
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
        result: dict[str, Any] = {
            "total": len(hits),
            "start_at": start_at,
            "max_results": limit,
            "is_last": start_at + limit >= len(hits),
            "native_query": query,
            "items": [shape_payload(self.definition, record, fields) for record in page],
        }
        if controlled:
            assert self.retrieval is not None
            result["retrieval"] = self.retrieval.public_info()
        return result

    def _native_search(
        self,
        tool: ConnectorToolDefinition,
        tool_name: str,
        query: str,
        entity: str | None,
    ) -> tuple[list[dict[str, Any]], tuple[str, ...]] | None:
        """Run *query* in the tool's own vendor language, or ``None`` to fall back.

        Only reached under the ``native`` engine. A tool whose language the
        evaluator does not parse (GraphQL, Rovo search, the system of record's
        predicate language) keeps the historical path rather than refusing a
        query it used to answer. A query the vendor would refuse is refused
        with the vendor's status and message.
        """
        from .connectors.query import QueryError, connector_search, tool_language

        if tool_language(self.definition, tool_name) is None:
            return None
        by_fid: dict[str, dict[str, Any]] = {}

        def pool(chosen: str | None) -> list[dict[str, Any]]:
            records = self._pool(chosen, tool)
            view = []
            for record in records:
                by_fid[str(record["fid"])] = record
                view.append(self._record_for_predicate(record))
            return view

        try:
            found = connector_search(self.definition, tool_name, query, pool=pool, entity=entity, user=self.actor)
        except QueryError as error:
            raise ConnectorError(error.status, error.message, "validation") from error
        hits = [by_fid[str(found.records[index]["fid"])] for index in found.result.matches]
        return hits, found.result.select

    def _entity_admits(self, tool: ConnectorToolDefinition, stored: str) -> bool:
        """Whether *tool* handles a record stored under the entity *stored*.

        Alias resolution has to run in both directions here, and only one of
        them used to. A tool's `entities` are canonical by construction (the
        closed-contract validator refuses any that are not), while a generated
        record carries whatever entity the planner named, which for a
        destination is usually the alias -- `file` rather than `docx`.
        `entity_matches(requested, actual)` resolves aliases in the *requested*
        position only, so asking it whether the `docx` tool admits a `file`
        record answered no, and every get against a planned destination 404'd
        while the record sat right there.

        Widening the stored side rather than minting concrete entities in
        `connector_data` is deliberate: the record bytes are what a seed
        produces, so changing them would be a Generation change, and this
        answers the same question without moving a single generated byte.
        """

        for entity in tool.entities:
            if stored == entity:
                return True
            for requested, actual in ((entity, stored), (stored, entity)):
                try:
                    if self.definition.entity_matches(requested, actual):
                        return True
                except KeyError:
                    # An entity the definition does not declare at all. Not this
                    # method's business to report; the caller raises not_found.
                    continue
        return False

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
        if not self._entity_admits(tool, str(record.get("entity"))):
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
                # The connector's own validation text is a duplicate-title
                # message for Confluence, which sent a real agent hunting for
                # a page that never existed. A missing field is named.
                code, _template = self.definition.errors.get("validation", (400, ""))
                raise ConnectorError(code, f"Required field '{required}' is missing on create of {selected}", "validation")
        if tool.idempotency is not None:
            key = tuple(freeze_key(values.get(part)) for part in tool.idempotency.key)
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
            record[workflow.field] = tool.initial_state or workflow.states[0]
        self.records[fid] = record
        self.by_entity[selected].append(fid)
        self._index_references(fid, record)
        if tool.idempotency is not None:
            key = tuple(freeze_key(values.get(part)) for part in tool.idempotency.key)
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

    def _op_move(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        parent: Any = None,
        fields: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Re-parent a record into a container the same connector holds.

        The record stays what it was — same identity, same body — and only
        its place changes, which is what makes a move reversible and
        naturally idempotent (``evalrun.safety``). The destination must be a
        container the definition knows (a folder, a mail folder); moving into
        a document is refused as validation, and into nothing as not found,
        so an agent that guessed a folder id learns which of the two it got
        wrong.
        """
        fid = self.resolve(id)
        self._check_acl(fid, "update")
        target = parent if parent is not None else (fields or {}).get("parent")
        if target in (None, ""):
            raise self._error("validation", field="parent")
        destination = self.resolve(target)
        container = self.definition.entities.get(str(self.records[destination].get("entity")))
        if container is None or container.kind != "container":
            raise ConnectorError(
                400, f"'{target}' is not a folder this connector can move a record into", "validation",
            )
        if destination == fid:
            raise ConnectorError(400, "a record cannot be moved into itself", "validation")
        record = copy.deepcopy(self.records[fid])
        patch = {"parent": destination}
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

    def _op_reply(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        body: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        parent_fid = self.resolve(id)
        self._check_acl(parent_fid, "comment")
        parent = self.records[parent_fid]
        entity = str(parent.get("entity"))
        if entity not in tool.entities:
            raise self._error("not_found", id=id)
        self._created += 1
        fid = f"new:{self.server[:2]}:{entity}:{self._created}"
        record = {
            "fid": fid,
            "server": self.server,
            "entity": entity,
            "name": body or "Reply",
            "title": body or "Reply",
            "text": body or "",
            "body": body or "",
            "reply_to": parent_fid,
            "thread_id": parent.get("thread_id") or parent.get("conversation") or parent_fid,
            "parent": parent_fid,
            "created_by": self.actor,
            "created_at": self.definition.clock,
            "modified_at": self.definition.clock,
        }
        self.records[fid] = record
        self.by_entity[entity].append(fid)
        self._index_references(fid, record)
        span.reads.append(parent_fid)
        span.writes.append(fid)
        span.items = 1
        return shape_payload(self.definition, record)

    def _op_forward(
        self,
        tool: ConnectorToolDefinition,
        span: _PendingSpan,
        *,
        id: Any = None,
        to: Sequence[str] | None = None,
        body: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        source_fid = self.resolve(id)
        self._check_acl(source_fid, "get")
        source = self.records[source_fid]
        entity = str(source.get("entity"))
        if entity not in tool.entities:
            raise self._error("not_found", id=id)
        self._created += 1
        fid = f"new:{self.server[:2]}:{entity}:{self._created}"
        subject = str(source.get("subject") or source.get("name") or source.get("title") or "Forward")
        record = copy.deepcopy(source)
        record.update(
            fid=fid,
            ident=None,
            external_id=None,
            name=f"Fwd: {subject}",
            title=f"Fwd: {subject}",
            subject=f"Fwd: {subject}",
            body=body or source.get("body") or source.get("text") or "",
            text=body or source.get("text") or source.get("body") or "",
            to=list(to or ()),
            forwarded_from=source_fid,
            created_by=self.actor,
            created_at=self.definition.clock,
            modified_at=self.definition.clock,
        )
        self.records[fid] = record
        self.by_entity[entity].append(fid)
        self._index_references(fid, record)
        span.reads.append(source_fid)
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
        digits = re.search(r"\{(\d+)d\}", pattern)
        if digits:
            width = int(digits.group(1))
            return pattern.replace(digits.group(0), f"{n:0{width}d}")
        if pattern == "18char":
            return hashlib.sha1(f"{self.server}:{entity}:{n}".encode()).hexdigest()[:15].upper() + "AAA"
        if pattern == "numeric":
            return str(900_000 + n)
        if pattern == "slack_timestamp":
            return f"{1_800_000_000 + n}.000001"
        if pattern.startswith("ari:cloud:"):
            return f"ari:cloud:worldloom::{entity}/{content_key(self.server, entity, n)[:16]}"
        return content_key(self.server, entity, n)[:34]


__all__ = ["QUERY_ENGINES", "ConnectorEmulator", "ConnectorError", "ConnectorSpan"]
