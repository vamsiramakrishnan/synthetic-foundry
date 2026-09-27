"""One tool surface from the contract: the tools Anvil projects for MCP, served in process through the mapping.

A live pilot found most of what it scored as agent failures were interface
failures: the in-process connector tools were hand written, a search took a
bare ``query: string`` with no grammar, while the same connector served
through Anvil exposed the vendor's real operations. Two serving paths, two
surfaces, and nothing holding them together. This module makes them one.

**The surface.** A compiled Anvil bundle (``worldloom contracts build``)
carries the contract's AIR; ``anvil_surface.mjs`` builds the bundle's MCP
server with Anvil's own ``buildMcpServer`` and converts each tool's input
schema with the MCP SDK's own converter, so every tool's name, title,
description, input schema, annotations and ``_meta`` are exactly what Anvil's
``tools/list`` serves (flat: every approved operation, no disclosure-ladder
lane cards). Beside each tool it records how Anvil carries a call to the
wire (each argument's wire name and location, the body's projection, whether
and how the simulator pages it, the page envelope, the declared statuses and
errors), read with Anvil's own functions. ``capture`` runs it once per
bundle and caches the document (``worldloom.contract-surface/v1``) under the
contracts cache by the bundle's AIR digest; the package ships one per locked
connector (``_data/connectors/anvil/surfaces/<connector>.json.gz``, made from
the committed trims with ``worldloom contracts surface --write``), so the
contract surface needs no Anvil to serve.

**The dispatch.** ``ContractSurface.invoke`` takes a call on that surface
(tool name, MCP arguments) and does what Anvil's MCP runtime, its simulator
and the Worldloom provider do between them, in process: it strips the
reserved controls, checks required inputs and the confirmation gate as the
runtime does, splits the arguments into the normalized provider request
(parameters by wire name and location, the body, the page) as the simulator
does, and runs that request through ``connectors.anvil.run_request``: the one
mapping dispatch the stdio provider and the Anvil replay also run. The
provider's answer is shaped as the simulator shapes it (the contract's
success status, its page envelope, its declared error statuses) and the
agent gets what Anvil's MCP server would give it: the response body, or
Anvil's structured error envelope, which never carries the vendor's prose.

**Carrying a plan.** ``ContractSurface.carry`` is the inverse, for a gold
plan whose nodes name connector tools: the operation the mapping reads the
call from, placed (``connectors.anvil.placements``) and then checked by
running the same forward mapping over it, so a node is carried only when the
operation gives back exactly its call. A node no exposed operation carries
is a gap, named.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import urllib.parse
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..connector_emulator import ConnectorError
from ..ids import content_key
from .anvil import (
    AnvilMapping,
    Backend,
    OperationMap,
    Refuse,
    expressible,
    load_mapping,
    placements,
    plan_call,
    read_air,
    run_request,
)

if TYPE_CHECKING:
    from ..connector_definition import ConnectorDefinition

SURFACE_SCHEMA = "worldloom.contract-surface/v1"
#: The surfaces a run can present: the hand-written connector tools, or the contract's.
SURFACES = ("native", "contract")
#: The simulator's page size for an operation whose contract states none
#: (``anvil simulate serve`` without ``--page-size``).
ANVIL_FALLBACK_PAGE_SIZE = 2
#: The reserved controls Anvil's MCP server adds to every tool.
DRY_RUN = "anvil_dry_run"
PROJECTION = "anvil_projection"
_DERIVED = frozenset({"budget_derived", "capped_by_upstream", "upstream_default"})
#: Result shapes answered from part of the record a tool returns, not the tool's own result.
_DERIVED_SHAPES = frozenset({"comment", "comments", "transitions"})
_SCRIPT = Path(__file__).with_name("anvil_surface.mjs")

#: Anvil's HTTP status for each error code, where the contract declares none.
_STATUS_FOR = {
    "validation_error": 400, "auth_required": 401, "permission_denied": 403, "not_found": 404, "conflict": 409,
    "rate_limited": 429, "upstream_timeout": 504, "upstream_unavailable": 503, "unsafe_retry_blocked": 409,
    "confirmation_required": 400, "idempotency_required": 400, "idempotency_ledger_unavailable": 503,
    "schema_mismatch": 502, "unsupported_operation": 404, "policy_denied": 403, "unknown_upstream_error": 500,
}
_ERROR_CODES = frozenset(_STATUS_FOR)
_RETRYABLE = frozenset({"rate_limited", "upstream_timeout", "upstream_unavailable"})


class SurfaceError(ValueError):
    """A contract surface that cannot be read, captured or served."""


class ContractCallError(ConnectorError):
    """A call on the contract surface that Anvil would have answered with an error envelope.

    ``code`` is the HTTP status the simulator served (as a ``ConnectorError``
    carries one), ``kind`` Anvil's error code, ``envelope`` exactly what
    Anvil's MCP server returns: ``{"error": {code, message, retryable,
    safe_to_retry, operation, trace_id, upstream}}``.
    """

    def __init__(self, status: int, envelope: Mapping[str, Any]) -> None:
        error = dict(envelope.get("error") or {})
        super().__init__(status, str(error.get("message") or ""), str(error.get("code") or "unknown_upstream_error"))
        self.envelope = dict(envelope)


def error_document(failure: ConnectorError) -> dict[str, Any]:
    """How an agent's transcript records a refused call: code, kind, message, and Anvil's envelope when it has one."""

    document: dict[str, Any] = {"code": failure.code, "kind": failure.kind, "message": failure.message}
    envelope = getattr(failure, "envelope", None)
    if envelope is not None:
        document["envelope"] = envelope
    return document


# -- the surface document ------------------------------------------------------------------


@dataclass(frozen=True)
class ContractTool:
    """One tool of the contract surface: Anvil's MCP definition and how a call reaches the wire."""

    connector: str
    definition: Mapping[str, Any]
    binding: Mapping[str, Any]
    examples: tuple[Mapping[str, Any], ...] = ()
    #: Why Anvil's converter refused this tool's schema, when it did; the
    #: schema is then the one Anvil assembles before conversion.
    unprojected: str | None = None

    @property
    def name(self) -> str:
        return str(self.definition["name"])

    @property
    def operation(self) -> str:
        return str(self.binding.get("operation") or "")

    @property
    def input_schema(self) -> Mapping[str, Any]:
        schema = self.definition.get("inputSchema")
        return schema if isinstance(schema, Mapping) else {}

    @property
    def properties(self) -> Mapping[str, Any]:
        found = self.input_schema.get("properties")
        return found if isinstance(found, Mapping) else {}


@dataclass(frozen=True)
class ContractSurface:
    """A connector's contract surface: its tools in Anvil's order, and the mapping that serves them."""

    connector: str
    service: str
    server_url: str
    tools: tuple[ContractTool, ...]
    mapping: AnvilMapping
    #: What the surface was projected from: the AIR digest and the Anvil build.
    source: Mapping[str, Any] = field(default_factory=dict)
    #: The page size for an operation whose contract states none (``simulate serve --page-size``).
    page_size: int = ANVIL_FALLBACK_PAGE_SIZE

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)

    def tool(self, name: str) -> ContractTool:
        for tool in self.tools:
            if tool.name == name:
                return tool
        raise KeyError(name)

    @property
    def digest(self) -> str:
        return content_key("contract-surface", json.dumps(
            {"connector": self.connector, "tools": [dict(tool.definition) for tool in self.tools],
             "bindings": {tool.name: dict(tool.binding) for tool in self.tools}, "page_size": self.page_size},
            sort_keys=True, default=str))

    def entry(self, tool: ContractTool) -> OperationMap | None:
        """The mapping entry that serves *tool*'s operation."""
        binding = tool.binding
        return self.mapping.entry(tool.operation, method=binding.get("method"), path=binding.get("path"))

    def maps_to(self, tool: ContractTool) -> str | None:
        entry = self.entry(tool)
        return f"{self.connector}.{entry.tool}" if entry is not None and entry.tool else None

    # -- what the agent is shown ---------------------------------------------------------

    def mcp_tools(self) -> list[dict[str, Any]]:
        """The tools as Anvil's MCP server lists them."""
        return [json.loads(json.dumps(tool.definition)) for tool in self.tools]

    def catalog(self, definition: ConnectorDefinition | None = None) -> list[dict[str, Any]]:
        """The tools as the turn protocol and the program client show them.

        Anvil's definition (``name``, ``title``, ``description``,
        ``inputSchema``, ``annotations``) as served, with the operation it
        calls, its arguments by name (``params``), Anvil's worked example
        and, for a tool whose mapped call reads a vendor query, the query
        language's grammar and examples (``query``) against the argument
        that carries it.
        """
        from .query.docs import query_help

        out = []
        for tool in self.tools:
            props = tool.properties
            entry: dict[str, Any] = {
                "name": tool.name, "connector": self.connector, "surface": "contract",
                "title": tool.definition.get("title"), "description": tool.definition.get("description"),
                "inputSchema": json.loads(json.dumps(tool.input_schema)),
                "annotations": dict(tool.definition.get("annotations") or {}),
                "operation": tool.operation, "method": tool.binding.get("method"), "path": tool.binding.get("path"),
                "params": {key: _json_type(value) for key, value in props.items()},
                "required": list(tool.input_schema.get("required") or ()),
            }
            if tool.examples:
                entry["examples"] = [dict(item) for item in tool.examples]
            mapped = self.entry(tool)
            if definition is not None and mapped is not None and mapped.tool and "query" in mapped.args:
                source = mapped.args["query"].source
                argument = self._argument_for(tool, source) if source else None
                try:
                    help = query_help(definition, mapped.tool)
                except KeyError:
                    help = None
                if help is not None and argument is not None:
                    entry["query"] = {**help, "argument": argument}
            out.append(entry)
        return out

    def _argument_for(self, tool: ContractTool, source: str) -> str | None:
        """The MCP argument (``key`` or ``body.field``) that carries request location *source*."""
        where, _, rest = source.partition(".")
        binding = tool.binding
        if where in {"path", "query", "header"}:
            for param in binding.get("params") or ():
                if param.get("in") == where and param.get("name") == rest:
                    return str(param["key"])
            return None
        body = binding.get("body") or {}
        if where == "body" and body:
            head = rest.split(".", 1)[0]
            if body.get("projection") == "fields":
                for item in body.get("fields") or ():
                    if item.get("name") == head:
                        return str(item["key"]) + rest[len(head):]
                return None
            return "body" + (f".{rest}" if rest else "")
        return None

    # -- a call ---------------------------------------------------------------------------

    def invoke(self, name: str, arguments: Mapping[str, Any], backend: Backend, *, request_id: str = "r1",
               refuse: Refuse | None = None) -> Any:
        """One call on this surface, answered as Anvil's MCP server answers it.

        Returns the response body; raises ``ContractCallError`` carrying
        Anvil's error envelope. The connector tool the mapping chooses runs on
        *backend* (a run's own service, so the call is graded as that tool);
        a request no tool ran for goes to *refuse*.
        """
        return self.dispatch(name, arguments, backend, request_id=request_id, refuse=refuse).body

    def dispatch(self, name: str, arguments: Mapping[str, Any], backend: Backend, *, request_id: str = "r1",
                 refuse: Refuse | None = None) -> Dispatched:
        tool = self.tool(name)
        binding = tool.binding
        args = dict(arguments)
        if args.pop(DRY_RUN, None) is True:
            request = self.request(tool, {k: v for k, v in args.items() if k in tool.properties}, request_id)
            return Dispatched(tool, request, None, _dry_run(tool, request))
        if args.pop(PROJECTION, None) is not None:
            raise ContractCallError(400, _envelope(binding, "validation_error", request_id, message=(
                f"{PROJECTION} is not served in process; call without it and read the fields you need")))
        # Anvil's MCP server validates with zod, which strips a key the schema does not name.
        args = {key: value for key, value in args.items() if key in tool.properties}
        missing = [key for key in _required_keys(binding) if args.get(key) in (None, "")]
        if missing:
            raise ContractCallError(400, _envelope(binding, "validation_error", request_id,
                                                   message=f"Missing required input: {', '.join(missing)}.",
                                                   details={"missing": missing}))
        confirmation = binding.get("confirmation") or {}
        keys = binding.get("safetyKeys") or {}
        if confirmation.get("required") and args.get(keys.get("confirm", "confirm")) is not True:
            risk = (binding.get("effect") or {}).get("risk")
            raise ContractCallError(400, _envelope(
                binding, "confirmation_required", request_id,
                message=confirmation.get("reason") or f"This operation is an unsafe {risk} mutation and requires confirmation.",
                required_flags=["--confirm"]))
        request = self.request(tool, args, request_id)
        answered = run_request(self.mapping, backend, request, refuse=refuse)
        status, body = self._shape(tool, request, answered.response)
        if 200 <= status < 300:
            return Dispatched(tool, request, answered, None if status == 204 else body)
        raise ContractCallError(status, _http_error(binding, status, body, request_id))

    def request(self, tool: ContractTool, args: Mapping[str, Any], request_id: str = "r1") -> dict[str, Any]:
        """The normalized provider request Anvil's simulator builds for *args* (``normalizeRequest``)."""
        binding = tool.binding
        params: dict[str, dict[str, Any]] = {"path": {}, "query": {}, "header": {}, "cookie": {}}
        for param in binding.get("params") or ():
            value = args.get(param["key"])
            if value is None:
                continue
            if param["in"] in params:
                params[param["in"]][param["name"]] = str(value) if param["in"] == "path" else value
        body: Any = None
        declared = binding.get("body")
        if declared and declared.get("projection") == "fields":
            fields = {item["name"]: args[item["key"]] for item in declared.get("fields") or ()
                      if args.get(item["key"]) is not None}
            body = fields or None
        elif declared and args.get("body") is not None:
            body = args["body"]
        effect = binding.get("effect") or {}
        return {
            "requestId": request_id, "operationId": tool.operation, "toolName": tool.name,
            "kind": binding.get("kind"), "action": effect.get("action"), "resource": effect.get("resource"),
            "method": binding.get("method"), "pathTemplate": binding.get("path"), "params": params, "body": body,
            "page": self._page(tool, params, body) if binding.get("paged") else None,
            "principal": None, "tenantId": None, "idempotencyKey": None,
        }

    def _page(self, tool: ContractTool, params: Mapping[str, Mapping[str, Any]], body: Any) -> dict[str, Any]:
        """The page the simulator asks the provider for (``providerPage``)."""
        binding = tool.binding
        pagination = binding.get("pagination") or {}

        def paging(name: str | None) -> Any:
            if name is None:
                return None
            if pagination.get("in") == "body":
                return body.get(name) if isinstance(body, Mapping) else None
            for location in ("query", "path", "header", "cookie"):
                if name in params.get(location, {}):
                    return params[location][name]
            return None

        cursor = paging(pagination.get("cursorParam"))
        if cursor in (None, "") and binding.get("odata"):
            cursor = paging("$skip")
        asked = paging(pagination.get("pageSizeParam"))
        try:
            size = int(asked) if asked is not None and int(asked) == float(asked) and int(asked) > 0 else 0
        except (TypeError, ValueError):
            size = 0
        if not size:
            derived = binding.get("pageSize") or {}
            size = int(derived["size"]) if derived.get("basis") in _DERIVED and derived.get("size") else self.page_size
        if pagination.get("maxPageSize") is not None:
            size = min(size, int(pagination["maxPageSize"]))
        return {"cursor": None if cursor in (None, "") else str(cursor), "size": size}

    def _shape(self, tool: ContractTool, request: Mapping[str, Any], raw: Mapping[str, Any]) -> tuple[int, Any]:
        """The HTTP status and body the simulator serves for the provider's answer."""
        binding = tool.binding
        page = request.get("page")
        if not raw.get("ok"):
            return _domain_error(binding, raw.get("error") or {})
        if page is not None:
            items = raw.get("items")
            if not isinstance(items, list):
                return _domain_error(binding, {"code": "schema_mismatch", "message": (
                    f"State provider answered {tool.operation}: a paged operation needs an 'items' array.")})
            if len(items) > int(page["size"]):
                return _domain_error(binding, {"code": "schema_mismatch", "message": (
                    f"State provider answered {tool.operation}: returned {len(items)} items for a page of "
                    f"{page['size']}; honour page.size and return a nextCursor.")})
            next_cursor = raw.get("nextCursor")
            cursor = next_cursor if isinstance(next_cursor, str) and next_cursor else None
            return _success_status(binding, {"items": items}), self._envelope(tool, request, items, cursor)
        output = raw.get("result")
        return _success_status(binding, output), output

    def _envelope(self, tool: ContractTool, request: Mapping[str, Any], items: list[Any], cursor: str | None) -> Any:
        """A page in the envelope the contract declares (the simulator's ``envelope``)."""
        binding = tool.binding
        pagination = binding.get("pagination") or {}
        shape = binding.get("envelope") or {}
        bare = bool(shape.get("bare"))
        following: str | None = cursor
        as_url = pagination.get("style") == "link" or (bare and pagination.get("in") != "body")
        if cursor is not None and as_url and pagination.get("cursorParam"):
            following = self._next_url(tool, request, str(pagination["cursorParam"]), cursor)
        if bare:
            return items
        body: dict[str, Any] = {}
        _set_path(body, str(shape.get("itemsField") or "items"), items)
        if following is not None:
            _set_path(body, str(pagination.get("nextField") or "next_cursor"), following)
        return body

    def _next_url(self, tool: ContractTool, request: Mapping[str, Any], cursor_param: str, cursor: str) -> str:
        """The continuation link: the request's own URL on the contract's server, with the cursor set."""
        params = request.get("params") or {}
        path = str(tool.binding.get("path") or "")
        for name, value in (params.get("path") or {}).items():
            path = path.replace("{" + str(name) + "}", urllib.parse.quote(str(value), safe=""))
        query: list[tuple[str, str]] = []
        for name, value in (params.get("query") or {}).items():
            if tool.binding.get("odata") and name == "$skip":
                continue
            if name == cursor_param:
                continue
            for item in value if isinstance(value, list) else [value]:
                query.append((str(name), _wire_text(item)))
        query.append((cursor_param, cursor))
        return self.server_url.rstrip("/") + path + "?" + urllib.parse.urlencode(query)

    # -- a gold call, carried ---------------------------------------------------------------

    def carry(self, tool: str, args: Mapping[str, Any], definition: ConnectorDefinition, *,
              record: Mapping[str, Any] | None = None) -> Carried:
        """The contract call that carries ``connector.<tool>(**args)``, checked; ``SurfaceError`` naming the gap.

        Each placement the mapping allows is turned into the arguments of the
        exposed tool for its operation and run forward through the same
        mapping (``plan_call``); the first whose forward call is exactly the
        call asked for carries it. A required coordinate the mapping never
        reads from the call (ServiceNow's table, Salesforce's sObject type) is
        the addressed *record*'s, as a client that fetched it would send.
        """
        wanted = expressible(definition, tool, args)
        if not wanted.get("start_at"):
            wanted.pop("start_at", None)  # the first page: no continuation to carry
        by_operation = {item.operation: item for item in self.tools}
        found, reasons = placements(self.mapping, tool, wanted, definition=definition,
                                    cursor=lambda entry: self._cursor_location(by_operation.get(entry.operation_id)))
        # An operation answered with the tool's own result first: one answered
        # from part of the record (its comments, its transitions) runs the
        # same tool for another question.
        found.sort(key=lambda placed: placed.entry.result.get("shape") in _DERIVED_SHAPES)
        for placed in found:
            exposed = by_operation.get(placed.entry.operation_id)
            if exposed is None:
                reasons.append(f"{placed.entry.operation_id} is not exposed by the {self.connector} contract")
                continue
            try:
                arguments = self._arguments(exposed, placed.params, placed.body)
                arguments.update(self._coordinates(exposed, arguments, definition, record))
            except ValueError as error:
                reasons.append(f"{placed.entry.operation_id}: {error}")
                continue
            request = self.request(exposed, arguments)
            try:
                planned = plan_call(self.mapping, placed.entry, request, definition)
            except Exception as error:  # an OperationRefused or a transform's refusal: this placement does not carry it
                reasons.append(f"{placed.entry.operation_id}: {error}")
                continue
            chosen = planned.tool
            record_chosen = placed.entry.tool_by is not None and placed.entry.tool_by[0].startswith("record.")
            if (chosen != tool and not (record_chosen and tool in placed.entry.tools)) \
                    or _canonical(planned.args) != _canonical(_taken(
                        definition, tool, {key: value for key, value in wanted.items() if key not in placed.dropped})):
                reasons.append(f"{placed.entry.operation_id} carries it as {self.connector}.{chosen}"
                               f"({_canonical(planned.args)}), not the call asked for")
                continue
            return Carried(exposed.name, arguments, placed.entry.operation_id)
        raise SurfaceError(f"no exposed {self.connector} operation carries {self.connector}.{tool}"
                           + (f": {'; '.join(reasons[:3])}" if reasons else ""))

    def _coordinates(self, tool: ContractTool, arguments: Mapping[str, Any], definition: ConnectorDefinition,
                     record: Mapping[str, Any] | None) -> dict[str, Any]:
        """Required path parameters no argument filled, named from the addressed record's type.

        The vendor's own name for the type when the mapping maps one to the
        record's entity elsewhere (``kb_knowledge`` for ``kb_article``,
        ``Account`` for ``account``), else the entity's query name.
        """
        entity = str((record or {}).get("entity") or "")
        out: dict[str, Any] = {}
        for param in tool.binding.get("params") or ():
            if not param.get("required") or param["key"] in arguments or param.get("in") != "path" or not entity:
                continue
            location = f"path.{param['name']}"
            named: Any = None
            for entry in self.mapping.operations.values():
                for spec in entry.args.values():
                    if spec.source == location and spec.values:
                        named = next((vendor for vendor, ours in spec.values.items() if ours == entity), named)
            if named is None:
                known = definition.entities.get(entity)
                named = known.query_name if known is not None and known.query_name else entity
            out[str(param["key"])] = named
        return out

    def _cursor_location(self, tool: ContractTool | None) -> str | None:
        if tool is None:
            return None
        pagination = tool.binding.get("pagination") or {}
        name = pagination.get("cursorParam")
        if not name:
            return None
        return f"body.{name}" if pagination.get("in") == "body" else f"query.{name}"

    def _arguments(self, tool: ContractTool, params: Mapping[str, Mapping[str, Any]], body: Any) -> dict[str, Any]:
        """The MCP arguments that make a request with *params* and *body* on *tool*."""
        binding = tool.binding
        out: dict[str, Any] = {}
        placed = {(where, name) for where, values in params.items() for name in values}
        known = {(param["in"], param["name"]): param["key"] for param in binding.get("params") or ()}
        for (where, name) in sorted(placed):
            key = known.get((where, name))
            if key is None:
                raise ValueError(f"the operation takes no {where} parameter {name!r}")
            out[key] = params[where][name]
        declared = binding.get("body")
        if body is not None:
            if not declared:
                raise ValueError("the operation takes no body")
            if declared.get("projection") == "fields":
                if not isinstance(body, Mapping):
                    raise ValueError("the body is a set of fields")
                fields = {item["name"]: item["key"] for item in declared.get("fields") or ()}
                for name, value in body.items():
                    if name not in fields:
                        raise ValueError(f"the operation's body has no field {name!r}")
                    out[fields[name]] = value
            else:
                out["body"] = body
        confirmation = binding.get("confirmation") or {}
        if confirmation.get("required"):
            out[(binding.get("safetyKeys") or {}).get("confirm", "confirm")] = True
        return out


@dataclass(frozen=True)
class Carried:
    """A connector call carried on the contract surface: the tool, its MCP arguments, the operation."""

    tool: str
    arguments: dict[str, Any]
    operation: str


@dataclass(frozen=True)
class Dispatched:
    """One call on the contract surface: the request the simulator would make, the provider's answer, the body."""

    tool: ContractTool
    request: Mapping[str, Any]
    answered: Any
    body: Any


def _json_type(schema: Any) -> str:
    if not isinstance(schema, Mapping):
        return "any"
    kind = schema.get("type")
    if isinstance(kind, list):
        return "|".join(str(item) for item in kind)
    return str(kind or ("object" if "properties" in schema else "any"))


def _wire_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    keys = [path] if path.startswith("@") else path.split(".")
    cursor = target
    for key in keys[:-1]:
        nested = cursor.get(key)
        if not isinstance(nested, dict):
            nested = cursor[key] = {}
        cursor = nested
    cursor[keys[-1]] = value


def _required_keys(binding: Mapping[str, Any]) -> list[str]:
    """The inputs Anvil's runtime requires before anything is sent (``execute`` step 1)."""
    keys = [str(param["key"]) for param in binding.get("params") or () if param.get("required")]
    body = binding.get("body")
    if body:
        if body.get("projection") == "fields":
            keys.extend(str(item["key"]) for item in body.get("fields") or () if item.get("required"))
        elif body.get("required"):
            keys.append("body")
    return keys


def _success_status(binding: Mapping[str, Any], output: Any) -> int:
    """The simulator's success status: the contract's declared one, else 201 for a create and 200 otherwise."""
    declared = [int(item) for item in binding.get("successStatuses") or ()]
    with_body = [item for item in declared if item != 204]
    empty = output is None
    if 204 in declared and (empty or not with_body):
        return 204
    if with_body:
        return with_body[0]
    return 201 if binding.get("kind") == "create" else 200


def _domain_error(binding: Mapping[str, Any], error: Mapping[str, Any]) -> tuple[int, Any]:
    """The status and body the simulator serves for a provider's domain error (``mapDomainError``)."""
    raw = str(error.get("code") or "")
    code = raw if raw in _ERROR_CODES else "unknown_upstream_error"
    errors = list(binding.get("errors") or ())
    upstream = error.get("upstreamCode")
    declared = None
    if upstream is not None:
        declared = next((item for item in errors if (item.get("upstream") or {}).get("code") == upstream), None)
    if declared is None:
        declared = next((item for item in errors if item.get("code") == code), None)
    code = str(declared.get("code")) if declared is not None else code
    message = error.get("message") or (declared or {}).get("message") or code
    upstream_code = upstream if upstream is not None else ((declared or {}).get("upstream") or {}).get("code")
    status = error.get("status") or ((declared or {}).get("upstream") or {}).get("httpStatus") or _STATUS_FOR[code]
    body = error.get("body") if error.get("body") is not None else {"error": {"code": upstream_code or code,
                                                                             "message": message}}
    return int(status), body


def _observed_code(body: Any) -> str | None:
    if not isinstance(body, Mapping):
        return None
    if isinstance(body.get("code"), str):
        return str(body["code"])
    inner = body.get("error")
    if isinstance(inner, Mapping) and isinstance(inner.get("code"), str):
        return str(inner["code"])
    for entry in body.get("errors") or () if isinstance(body.get("errors"), list) else ():
        if isinstance(entry, Mapping) and isinstance(entry.get("code"), str):
            return str(entry["code"])
    return None


def _status_code(status: int) -> str:
    """Anvil's runtime ``httpStatusToErrorCode``."""
    known = {400: "validation_error", 422: "validation_error", 401: "auth_required", 403: "permission_denied",
             404: "not_found", 410: "not_found", 408: "upstream_timeout", 409: "conflict", 429: "rate_limited",
             502: "upstream_unavailable", 503: "upstream_unavailable", 504: "upstream_timeout"}
    if status in known:
        return known[status]
    return "unknown_upstream_error" if status >= 500 or status < 400 else "validation_error"


def _http_error(binding: Mapping[str, Any], status: int, body: Any, request_id: str) -> dict[str, Any]:
    """Anvil's runtime envelope for a non-2xx response (``httpResponseError``): declared semantics, never raw prose."""
    observed = _observed_code(body)
    errors = [item for item in binding.get("errors") or () if (item.get("upstream") or {}).get("httpStatus") == status]
    declared = None
    if observed is not None:
        declared = next((item for item in errors if (item.get("upstream") or {}).get("code") == observed), None)
    if declared is None:
        declared = next((item for item in errors if (item.get("upstream") or {}).get("code") is None), None)
    code = str(declared.get("code")) if declared is not None else _status_code(status)
    retryable = bool(declared.get("retryable")) if declared is not None and "retryable" in declared \
        else code in _RETRYABLE
    retry_safe = (binding.get("retries") or {}).get("mode") == "safe"
    safe = retry_safe and (bool(declared["safeToRetry"]) if declared is not None and "safeToRetry" in declared
                           else retryable)
    upstream: dict[str, Any] = {"status": status}
    declared_upstream = (declared or {}).get("upstream") or {}
    if declared_upstream.get("code") and observed == declared_upstream.get("code"):
        upstream["code"] = declared_upstream["code"]
    message = (declared or {}).get("message") or f"Upstream returned {status} for {binding.get('operation')}."
    details = None
    recovery = (declared or {}).get("recovery")
    if isinstance(recovery, Mapping):
        details = {"recovery_action": recovery.get("action"),
                   **({"field_path": recovery["fieldPath"]} if recovery.get("fieldPath") else {})}
    return _envelope(binding, code, request_id, message=message, retryable=retryable, safe=safe, upstream=upstream,
                     details=details)


def _envelope(binding: Mapping[str, Any], code: str, request_id: str, *, message: str, retryable: bool = False,
              safe: bool = False, upstream: Mapping[str, Any] | None = None, details: Any = None,
              required_flags: Sequence[str] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message, "retryable": retryable, "safe_to_retry": safe,
                             "operation": binding.get("operation"), "trace_id": f"trace_{request_id}"}
    if upstream is not None:
        error["upstream"] = dict(upstream)
    if required_flags:
        error["required_flags"] = list(required_flags)
    if details is not None:
        error["details"] = details
    return {"error": error}


def _dry_run(tool: ContractTool, request: Mapping[str, Any]) -> dict[str, Any]:
    params = request.get("params") or {}
    return {"dry_run": True, "operation": tool.operation, "method": request.get("method"),
            "path": request.get("pathTemplate"), "path_params": dict(params.get("path") or {}),
            "query": dict(params.get("query") or {}), "body": request.get("body")}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _taken(definition: ConnectorDefinition, tool: str, args: Mapping[str, Any]) -> dict[str, Any]:
    try:
        params = definition.tool(definition.canonical_tool(tool)).params
    except KeyError:
        return dict(args)
    return {name: value for name, value in args.items() if name in params}


# -- reading and capturing ---------------------------------------------------------------


def parse_surface(document: Mapping[str, Any], *, mapping: AnvilMapping | None = None,
                  page_size: int = ANVIL_FALLBACK_PAGE_SIZE, origin: str = "surface") -> ContractSurface:
    """A ``worldloom.contract-surface/v1`` document as a surface served through its connector's mapping."""
    if document.get("schema") != SURFACE_SCHEMA:
        raise SurfaceError(f"{origin}: schema must be {SURFACE_SCHEMA!r}")
    connector = str(document.get("connector") or "")
    if not connector:
        raise SurfaceError(f"{origin}: `connector` is required")
    bindings = document.get("bindings") or {}
    examples = document.get("examples") or {}
    failed = document.get("failed") or {}
    tools = tuple(ContractTool(connector, dict(item), dict(bindings.get(item["name"]) or {}),
                               tuple(examples.get(item["name"]) or ()), failed.get(item["name"]))
                  for item in document.get("tools") or ())
    if not tools:
        raise SurfaceError(f"{origin}: the surface lists no tools")
    return ContractSurface(connector=connector, service=str(document.get("service") or connector),
                           server_url=str(document.get("server_url") or ""), tools=tools,
                           mapping=mapping or load_mapping(connector), source=dict(document.get("source") or {}),
                           page_size=page_size)


def shipped_path(connector: str) -> Any:
    return files("worldloom").joinpath("_data", "connectors", "anvil", "surfaces", f"{connector}.json.gz")


def shipped_surfaces() -> tuple[str, ...]:
    """Every connector the package ships a contract surface for."""
    directory = files("worldloom").joinpath("_data", "connectors", "anvil", "surfaces")
    if not directory.is_dir():
        return ()
    return tuple(sorted(entry.name.removesuffix(".json.gz") for entry in directory.iterdir()
                        if entry.name.endswith(".json.gz")))


@cache
def _shipped_document(connector: str) -> dict[str, Any]:
    source = shipped_path(connector)
    if not source.is_file():
        raise SurfaceError(f"no contract surface ships for {connector!r}; shipped: {', '.join(shipped_surfaces()) or 'none'}")
    loaded: dict[str, Any] = json.loads(gzip.decompress(source.read_bytes()).decode("utf-8"))
    return loaded


def shipped_surface(connector: str, *, page_size: int = ANVIL_FALLBACK_PAGE_SIZE) -> ContractSurface:
    """The surface the package ships for *connector*, projected from the committed trim of its locked contract."""
    return parse_surface(_shipped_document(connector), page_size=page_size, origin=f"surfaces/{connector}.json.gz")


def _cli_entry(anvil: Sequence[str]) -> tuple[str, str]:
    """``(node, cli entry script)`` for an Anvil command: ``node .../bin-anvil.js``, or ``anvil`` on PATH."""
    parts = list(anvil)
    if len(parts) >= 2 and parts[-1].endswith((".js", ".mjs", ".cjs")):
        return parts[0], parts[-1]
    found = shutil.which(parts[-1]) if parts else None
    if not found:
        raise SurfaceError(f"cannot find the Anvil CLI entry for {' '.join(parts)!r}")
    node = shutil.which("node") or "node"
    return node, os.path.realpath(found)


def air_digest(bundle: str | Path) -> str:
    return content_key("anvil-contract", json.dumps(read_air(bundle), sort_keys=True, default=str))


def project(bundle: str | Path, connector: str, *, anvil: Sequence[str]) -> dict[str, Any]:
    """Anvil's MCP projection of *bundle* for *connector*, as a surface document (runs Anvil once)."""
    path = Path(bundle)
    if path.is_file():
        path = path.parent
    node, entry = _cli_entry(anvil)
    try:
        done = subprocess.run([node, str(_SCRIPT), str(path), entry], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SurfaceError(f"{connector}: could not project {path}: {error}") from error
    if done.returncode != 0:
        tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-8:])
        raise SurfaceError(f"{connector}: projecting {path} exited {done.returncode}: {tail}")
    projected = json.loads(done.stdout)
    examples: dict[str, list[dict[str, Any]]] = {}
    directory = path / "skill" / "examples"
    for binding in (projected.get("bindings") or {}).values():
        example = directory / f"{binding.get('canonical')}.json"
        if example.is_file():
            loaded = json.loads(example.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping) and isinstance(loaded.get("input"), Mapping):
                examples.setdefault(str(loaded.get("tool")), []).append(dict(loaded["input"]))
    air = read_air(path)
    source = (air.get("service") or {}).get("source") or {}
    return {
        "schema": SURFACE_SCHEMA, "connector": connector, "service": projected.get("service"),
        "server_url": projected.get("serverUrl"),
        "source": {"air_digest": air_digest(path), "anvil_version": air.get("anvilVersion"),
                   "snapshot": source.get("sourceHash"), "profile": (source.get("profile") or {}).get("digest")},
        "tools": projected.get("tools") or [], "bindings": projected.get("bindings") or {},
        "failed": projected.get("failed") or {}, "examples": dict(sorted(examples.items())),
    }


def cached_path(bundle: str | Path, cache_root: Path | None = None) -> Path:
    from .contracts import default_cache

    return (cache_root or default_cache()) / "surfaces" / f"{air_digest(bundle)[:32]}.json"


def bundle_surface(bundle: str | Path, connector: str, *, anvil: Sequence[str] | None = None,
                   cache_root: Path | None = None, page_size: int = ANVIL_FALLBACK_PAGE_SIZE) -> ContractSurface:
    """*bundle*'s surface: from the cache by its AIR digest, else projected once with *anvil* and cached."""
    target = cached_path(bundle, cache_root)
    if target.is_file():
        document = json.loads(target.read_text(encoding="utf-8"))
        if document.get("connector") == connector:
            return parse_surface(document, page_size=page_size, origin=str(target))
    if anvil is None:
        from ..evalrun.anvil import find_anvil

        anvil = find_anvil()
        if not anvil:
            raise SurfaceError(f"{connector}: {bundle} has no cached surface and no Anvil CLI to project it")
    document = project(bundle, connector, anvil=anvil)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    return parse_surface(document, page_size=page_size, origin=str(target))


def write_shipped(document: Mapping[str, Any], target: str | Path) -> Path:
    """A surface document gzipped deterministically (no timestamp), as the package ships it."""
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    return path


@dataclass(frozen=True)
class ContractSurfaces:
    """The contract surfaces a run presents, per connector; a connector without one keeps its own tools."""

    surfaces: Mapping[str, ContractSurface]

    @property
    def connectors(self) -> tuple[str, ...]:
        return tuple(sorted(self.surfaces))

    def get(self, connector: str) -> ContractSurface | None:
        return self.surfaces.get(connector)

    def identity(self) -> dict[str, Any]:
        return {"surface": "contract",
                "contracts": {name: surface.digest for name, surface in sorted(self.surfaces.items())}}


def load_surfaces(connectors: Sequence[str], *, bundles: Mapping[str, str | Path] | None = None,
                  anvil: Sequence[str] | None = None, page_size: int = ANVIL_FALLBACK_PAGE_SIZE) -> ContractSurfaces:
    """The contract surface of each of *connectors* that has one: from its bundle when given, else the shipped one."""
    out: dict[str, ContractSurface] = {}
    shipped = set(shipped_surfaces())
    for connector in sorted(set(connectors)):
        if bundles and connector in bundles:
            out[connector] = bundle_surface(bundles[connector], connector, anvil=anvil, page_size=page_size)
        elif connector in shipped:
            out[connector] = shipped_surface(connector, page_size=page_size)
    return ContractSurfaces(out)


# -- which surface a service presents ------------------------------------------------------

_SURFACE: ContextVar[Any] = ContextVar("worldloom_connector_surface", default=None)


@contextmanager
def serving_surface(choice: str | ContractSurfaces | None) -> Iterator[None]:
    """Services built inside this block present *choice*: ``native``, ``contract``, or given surfaces."""
    token = _SURFACE.set(choice)
    try:
        yield
    finally:
        _SURFACE.reset(token)


def surface_in_force() -> Any:
    """The surface a service presents when it is not told: the block's (``serving_surface``), else the policy's.

    The policy is ``connectors.surface``; ``native`` by default.
    """
    held = _SURFACE.get()
    if held is not None:
        return held
    from .. import packkit

    try:
        return packkit.policy("connectors.surface")
    except KeyError:
        return "native"


def resolve_surfaces(choice: Any, connectors: Sequence[str]) -> ContractSurfaces | None:
    """The contract surfaces for *connectors* under *choice*, or ``None`` for the native surface.

    A connector the given surfaces leave out is served on its shipped
    surface when one ships, and on its own tools otherwise.
    """
    chosen = choice if choice is not None else surface_in_force()
    if chosen == "native":
        return None
    if isinstance(chosen, ContractSurfaces):
        picked = {name: held for name, held in chosen.surfaces.items() if name in set(connectors)}
        rest = load_surfaces([name for name in connectors if name not in picked])
        return ContractSurfaces({**rest.surfaces, **picked})
    if chosen == "contract":
        return load_surfaces(connectors)
    raise SurfaceError(f"surface: one of {', '.join(SURFACES)}, not {chosen!r}")


__all__ = [
    "ANVIL_FALLBACK_PAGE_SIZE",
    "SURFACES",
    "SURFACE_SCHEMA",
    "Carried",
    "ContractCallError",
    "ContractSurface",
    "ContractSurfaces",
    "ContractTool",
    "Dispatched",
    "SurfaceError",
    "air_digest",
    "bundle_surface",
    "cached_path",
    "error_document",
    "load_surfaces",
    "resolve_surfaces",
    "serving_surface",
    "surface_in_force",
    "parse_surface",
    "project",
    "shipped_path",
    "shipped_surface",
    "shipped_surfaces",
    "write_shipped",
]
