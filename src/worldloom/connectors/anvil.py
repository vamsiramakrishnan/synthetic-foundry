"""Serve a connector's records behind an Anvil contract: the operation mapping and the answer.

Anvil (``anvil simulate serve --provider-cmd``) owns a vendor API's surface:
paths, auth scopes, idempotency replay, injected faults, page envelopes and
error statuses. It hands every call that passes those gates to a state
provider as one normalized request (``operationId``, ``kind``, parameters by
location, ``body``, ``page``) and expects a record, a page or a domain error
back. This module is the half of a provider that knows Worldloom: it maps each
operation of the contract to a tool of the connector definition, turns the
request into that tool's arguments, runs the tool on the emulator's state, and
shapes what came back into the vendor's response.

The mapping is data, one file per contract under
``_data/connectors/anvil/<connector>.json`` (``worldloom.anvil-mapping/v1``):

``operations``
    Keyed by Anvil's ``operationId``. Each entry names a connector ``tool``,
    the ``args`` it takes (each read ``from`` a request location, ``body.*``,
    ``path.*``, ``query.*``, ``header.*`` or ``page.*``, optionally through a
    named ``transform``), and the ``result`` shape. An argument may instead be
    a constant (``{"value": ...}``) or an ``object`` assembled from several
    locations, and a read value may pass through a ``map`` of vendor values
    to the definition's (a ServiceNow table name to its entity) and a
    ``rename`` of an object's keys (a Graph property to the record's field).
    A result may carry an ``envelope``: the vendor's response body as a
    template whose ``$record``, ``$items``, ``$next``, ``$next_link``,
    ``$total``, ``$is_last``, ``$has_more`` and ``$args.<name>`` strings are
    filled in, and whose keys filled with a continuation that does not exist
    (the last page) are left out. An entry may instead be
    ``{"unmodelled": "<why>"}``: an operation the contract exposes and the
    connector has no state for, answered ``unsupported_operation``. ``route``
    (``"POST /path/{id}"``) matches an operation whose id differs, as it does
    when the contract was compiled under another service id; ``vendor`` is the
    vendor's own operationId, which a lint over the contract's AIR matches too.
``transitions``
    The vendor's workflow transition ids and names, each onto the
    definition's workflow state (``to``).
``error_body``
    The vendor's error body, with ``{message}`` filled in.

``lint_mapping`` refuses a mapping that leaves an exposed operation neither
mapped nor marked unmodelled, or that names a tool or argument the connector
definition does not declare; the provider runs it at the handshake, so Anvil
refuses to serve an unmapped contract rather than answering some operations
from nowhere.

Execution goes through a ``Backend``: an emulator directly (serving a corpus)
or an evaluation service run (serving one eval case, so node attribution and
designed failures apply). The same ``answer`` runs in the provider and in the
runner's replay of the Anvil trace, which is how a case served through Anvil
is graded by exactly the code that grades one served in process.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ..connector_emulator import ConnectorEmulator, ConnectorError

if TYPE_CHECKING:
    from ..connector_definition import ConnectorDefinition
    from .serving import ConnectorEvaluationService

MAPPING_SCHEMA = "worldloom.anvil-mapping/v1"
PROTOCOL_VERSION = 1

#: Anvil's error code for each status the emulator raises with.
_STATUS_CODES = {
    400: "validation_error",
    401: "auth_required",
    403: "permission_denied",
    404: "not_found",
    409: "conflict",
    413: "validation_error",
    422: "validation_error",
    429: "rate_limited",
    504: "upstream_timeout",
}

_LOCATIONS = ("body", "path", "query", "header", "page")
_ROUTE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) /\S*$")


class MappingError(ValueError):
    """A mapping file that cannot be read, or that the contract it serves refuses."""

    def __init__(self, message: str, findings: Sequence[str] = ()) -> None:
        super().__init__(message if not findings else f"{message}: " + "; ".join(findings))
        self.findings = tuple(findings)


class OperationRefused(Exception):
    """A request refused before any tool ran: the provider answers it as a domain error."""

    def __init__(self, code: str, message: str, *, upstream: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.upstream = upstream


# -- the mapping ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Arg:
    """One tool argument: read from the request (``source``), assembled (``parts``), or a constant."""

    source: str | None
    transform: str | None = None
    required: bool = False
    constant: Any = None
    parts: Mapping[str, Any] | None = None
    values: Mapping[str, Any] | None = None
    rename: Mapping[str, str] | None = None

    @property
    def label(self) -> str:
        return self.source.split(".")[-1] if self.source else "?"


@dataclass(frozen=True)
class OperationMap:
    operation_id: str
    tool: str | None = None
    args: Mapping[str, Arg] = field(default_factory=dict)
    result: Mapping[str, Any] = field(default_factory=dict)
    cursor: str | None = None
    route: str | None = None
    vendor: str | None = None
    unmodelled: str | None = None
    #: ``(location, {value: tool})``: an operation whose tool depends on the request,
    #: as ServiceNow's one Table API route serves every table.
    tool_by: tuple[str, Mapping[str, str]] | None = None

    @property
    def tools(self) -> tuple[str, ...]:
        """Every tool this entry can run."""

        if self.tool is None:
            return ()
        chosen = [self.tool, *(self.tool_by[1].values() if self.tool_by else ())]
        return tuple(dict.fromkeys(chosen))


@dataclass(frozen=True)
class AnvilMapping:
    connector: str
    service: str | None
    operations: Mapping[str, OperationMap]
    transitions: tuple[Mapping[str, str], ...] = ()
    error_body: Any = None

    @property
    def by_route(self) -> dict[str, OperationMap]:
        return {entry.route: entry for entry in self.operations.values() if entry.route}

    def entry(self, operation_id: str, *, method: str | None = None, path: str | None = None) -> OperationMap | None:
        """The entry for an operation: by id, else by ``METHOD path``."""

        found = self.operations.get(operation_id)
        if found is None and method and path:
            found = self.by_route.get(f"{method.upper()} {path}")
        return found


def _location(value: Any, what: str) -> None:
    if isinstance(value, Mapping) and set(value) == {"value"}:
        return
    if not isinstance(value, str) or value.split(".", 1)[0] not in _LOCATIONS:
        raise MappingError(f"{what} reads {value!r}; locations are {', '.join(_LOCATIONS)}, or a {{value}} constant")


def _arg(name: str, raw: Any, where: str) -> Arg:
    if isinstance(raw, str):
        raw = {"from": raw}
    if not isinstance(raw, Mapping) or sum(1 for key in ("from", "value", "object") if key in raw) != 1:
        raise MappingError(f"{where}: argument {name!r} needs one of `from`, `value` or `object`")
    transform = raw.get("transform")
    if transform is not None and transform not in TRANSFORMS:
        raise MappingError(f"{where}: argument {name!r} names unknown transform {transform!r}; known: {', '.join(sorted(TRANSFORMS))}")
    values, rename = raw.get("map"), raw.get("rename")
    for key, value in (("map", values), ("rename", rename)):
        if value is not None and not isinstance(value, Mapping):
            raise MappingError(f"{where}: argument {name!r}: `{key}` is an object")
    required = bool(raw.get("required", False))
    chosen = dict(values) if values else None
    renamed = dict(rename) if rename else None
    if "value" in raw:
        return Arg(source=None, constant=raw["value"], transform=transform, required=required, values=chosen, rename=renamed)
    if "object" in raw:
        parts = raw["object"]
        if not isinstance(parts, Mapping) or not parts:
            raise MappingError(f"{where}: argument {name!r}: `object` maps names to request locations")
        for key, location in parts.items():
            _location(location, f"{where}: argument {name!r}.{key}")
        return Arg(source=None, parts=dict(parts), transform=transform, required=required, values=chosen, rename=renamed)
    if not isinstance(raw["from"], str):
        raise MappingError(f"{where}: argument {name!r} needs a `from` location")
    source = str(raw["from"])
    if source.split(".", 1)[0] not in _LOCATIONS:
        raise MappingError(f"{where}: argument {name!r} reads {source!r}; locations are {', '.join(_LOCATIONS)}")
    return Arg(source=source, transform=transform, required=required, values=chosen, rename=renamed)


def parse_mapping(document: Mapping[str, Any], *, origin: str = "mapping") -> AnvilMapping:
    """Validate a ``worldloom.anvil-mapping/v1`` document."""

    if document.get("schema") != MAPPING_SCHEMA:
        raise MappingError(f"{origin}: schema must be {MAPPING_SCHEMA!r}")
    connector = document.get("connector")
    if not isinstance(connector, str) or not connector:
        raise MappingError(f"{origin}: `connector` is required")
    raw_operations = document.get("operations")
    if not isinstance(raw_operations, Mapping) or not raw_operations:
        raise MappingError(f"{origin}: `operations` must be a non-empty object")
    operations: dict[str, OperationMap] = {}
    for operation_id in sorted(raw_operations):
        raw = raw_operations[operation_id]
        where = f"{origin}: {operation_id}"
        if not isinstance(raw, Mapping):
            raise MappingError(f"{where}: an entry is an object")
        route = raw.get("route")
        if route is not None and (not isinstance(route, str) or not _ROUTE.match(route)):
            raise MappingError(f"{where}: route {route!r} must read 'METHOD /path'")
        vendor = raw.get("vendor")
        if raw.get("unmodelled") is not None:
            reason = raw["unmodelled"]
            if not isinstance(reason, str) or not reason.strip():
                raise MappingError(f"{where}: `unmodelled` states why, as text")
            if raw.get("tool") is not None:
                raise MappingError(f"{where}: an operation is mapped to a tool or unmodelled, not both")
            operations[operation_id] = OperationMap(operation_id, route=route, vendor=vendor, unmodelled=reason)
            continue
        tool = raw.get("tool")
        if not isinstance(tool, str) or not tool:
            raise MappingError(f"{where}: name the connector `tool`, or mark it `unmodelled` with a reason")
        args = raw.get("args") or {}
        if not isinstance(args, Mapping):
            raise MappingError(f"{where}: `args` is an object")
        result = raw.get("result") or {"shape": "record"}
        if isinstance(result, str):
            result = {"shape": result}
        if not isinstance(result, Mapping) or result.get("shape") not in SHAPES:
            raise MappingError(f"{where}: result shape must be one of {', '.join(sorted(SHAPES))}")
        cursor = raw.get("cursor")
        if cursor is not None and (not isinstance(cursor, str) or cursor.split(".", 1)[0] not in _LOCATIONS):
            raise MappingError(f"{where}: `cursor` is a request location")
        tool_by = raw.get("tool_by")
        chosen_by: tuple[str, Mapping[str, str]] | None = None
        if tool_by is not None:
            if (not isinstance(tool_by, Mapping) or not isinstance(tool_by.get("from"), str)
                    or tool_by["from"].split(".", 1)[0] not in _LOCATIONS or not isinstance(tool_by.get("map"), Mapping)):
                raise MappingError(f"{where}: `tool_by` reads a request location (`from`) and maps its values to tools (`map`)")
            chosen_by = (str(tool_by["from"]), {str(key): str(value) for key, value in tool_by["map"].items()})
        operations[operation_id] = OperationMap(
            operation_id, tool=tool, args={name: _arg(name, args[name], where) for name in sorted(args)},
            result=dict(result), cursor=cursor, route=route, vendor=vendor, tool_by=chosen_by,
        )
    transitions = tuple(dict(item) for item in document.get("transitions") or ())
    for item in transitions:
        if not {"id", "name", "to"} <= set(item):
            raise MappingError(f"{origin}: each transition needs id, name and to")
    service = document.get("service")
    return AnvilMapping(connector=connector, service=str(service) if service else None, operations=operations,
                        transitions=transitions, error_body=document.get("error_body"))


def mapping_path(connector: str) -> Any:
    """Where the shipped mapping for *connector* lives."""

    return files("worldloom").joinpath("_data", "connectors", "anvil", f"{connector}.json")


def shipped_mappings() -> tuple[str, ...]:
    """Every connector with a shipped Anvil mapping."""

    directory = files("worldloom").joinpath("_data", "connectors", "anvil")
    return tuple(sorted(entry.name[:-5] for entry in directory.iterdir() if entry.name.endswith(".json")))


def load_mapping(connector: str | None = None, *, path: str | Path | None = None) -> AnvilMapping:
    """The mapping at *path*, else the shipped one for *connector*."""

    if path is not None:
        source: Any = Path(path)
        origin = str(path)
    elif connector is not None:
        source = mapping_path(connector)
        origin = f"anvil/{connector}.json"
        if not source.is_file():
            raise MappingError(f"no Anvil mapping ships for connector {connector!r}; shipped: {', '.join(shipped_mappings()) or 'none'}")
    else:
        raise MappingError("name a connector or a mapping file")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MappingError(f"{origin}: {error}") from error
    mapping = parse_mapping(document, origin=origin)
    if connector is not None and mapping.connector != connector:
        raise MappingError(f"{origin} maps connector {mapping.connector!r}, not {connector!r}")
    return mapping


# -- the contract's operations -------------------------------------------------------------


@dataclass(frozen=True)
class ContractOperation:
    """One operation a contract serves, as the handshake or the AIR names it."""

    operation_id: str
    method: str | None = None
    path: str | None = None
    vendor: str | None = None
    kind: str | None = None

    @property
    def route(self) -> str | None:
        return f"{self.method.upper()} {self.path}" if self.method and self.path else None


def operations_from_table(table: Iterable[Mapping[str, Any]]) -> tuple[ContractOperation, ...]:
    """The ``operations`` of an ``initialize`` request."""

    return tuple(ContractOperation(str(item["operationId"]), method=item.get("method"), path=item.get("pathTemplate"),
                                   kind=item.get("kind"))
                 for item in table)


def operations_from_air(air: Mapping[str, Any], *, approved_only: bool = True) -> tuple[ContractOperation, ...]:
    """The operations of an AIR document (``air.json``), approved ones by default: what Anvil serves."""

    out = []
    for item in air.get("operations") or ():
        if approved_only and item.get("state") != "approved":
            continue
        source = item.get("sourceRef") or {}
        method = source.get("method")
        out.append(ContractOperation(str(item["id"]), method=str(method).upper() if method else None,
                                     path=source.get("path"), vendor=source.get("operationId")))
    return tuple(out)


def read_air(path: str | Path) -> dict[str, Any]:
    """A contract's AIR: a bundle directory, its ``air.json``, or its ``air.yaml`` (read from the ``air.json`` beside it).

    Every bundle Anvil writes carries both; the JSON one is read so no YAML
    parser is a dependency.
    """

    target = Path(path)
    if target.is_dir():
        target = target / "air.json"
    if target.suffix in {".yaml", ".yml"}:
        target = target.with_suffix(".json")
    if not target.is_file():
        raise MappingError(f"{target} does not exist; point at a bundle directory or its air.json")
    loaded = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or "operations" not in loaded:
        raise MappingError(f"{target} is not an AIR document")
    return loaded


def lint_mapping(mapping: AnvilMapping, operations: Sequence[ContractOperation],
                 definition: ConnectorDefinition | None = None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(errors, advisories)`` for serving *operations* through *mapping*.

    An error: an exposed operation neither mapped nor marked unmodelled, a
    tool the connector does not declare, an argument the tool does not take.
    An advisory: a mapped operation the contract does not expose (a profile
    that serves fewer operations than the mapping knows is fine).
    """

    errors: list[str] = []
    advisories: list[str] = []
    matched: set[str] = set()
    vendors = {entry.vendor: entry for entry in mapping.operations.values() if entry.vendor}
    for operation in operations:
        entry = mapping.entry(operation.operation_id, method=operation.method, path=operation.path)
        if entry is None and operation.vendor:
            entry = vendors.get(operation.vendor)
        if entry is None:
            errors.append(f"unmapped: {operation.operation_id} ({operation.route or 'no route'}) is exposed by the "
                          "contract and neither mapped to a tool nor marked unmodelled")
            continue
        matched.add(entry.operation_id)
    for entry in mapping.operations.values():
        if entry.operation_id not in matched:
            advisories.append(f"not_served: {entry.operation_id} is mapped but the contract does not expose it")
        if entry.unmodelled is not None or definition is None or entry.tool is None:
            continue
        for name in entry.tools:
            try:
                tool = definition.tool(definition.canonical_tool(name))
            except KeyError:
                errors.append(f"unknown_tool: {entry.operation_id} maps to {mapping.connector}.{name}, which the definition does not declare")
                continue
            unknown = sorted(set(entry.args) - set(tool.params))
            if unknown:
                errors.append(f"unknown_arguments: {entry.operation_id} passes {unknown} to {mapping.connector}.{name}")
    return tuple(errors), tuple(sorted(advisories))


# -- reading a request ---------------------------------------------------------------------


_MISSING: Any = object()


def read_location(request: Mapping[str, Any], source: str) -> Any:
    """The value at ``body.a.b`` / ``path.x`` / ``query.x`` / ``header.x`` / ``page.cursor``."""

    head, _, rest = source.partition(".")
    if head == "body":
        current: Any = request.get("body")
    elif head == "page":
        current = request.get("page")
    else:
        current = (request.get("params") or {}).get(head)
    for part in rest.split(".") if rest else ():
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return _MISSING if current is None else current


def read_arg(request: Mapping[str, Any], spec: Arg) -> Any:
    """One argument's raw value: its location's, its constant, or the object its parts assemble."""

    if spec.parts is not None:
        out: dict[str, Any] = {}
        for key, location in spec.parts.items():
            value = location["value"] if isinstance(location, Mapping) else read_location(request, location)
            if value is not _MISSING:
                out[key] = value
        return out if out else _MISSING
    if spec.source is None:
        return spec.constant
    return read_location(request, spec.source)


def adf_text(value: Any) -> str:
    """Plain text of an Atlassian Document Format node (or a string, as given)."""

    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        if value.get("type") == "text":
            return str(value.get("text") or "")
        parts = [adf_text(child) for child in value.get("content") or ()]
        joiner = "\n" if value.get("type") == "doc" else ""
        return joiner.join(part for part in parts if part)
    if isinstance(value, list):
        return "".join(adf_text(item) for item in value)
    return "" if value is None else str(value)


def _option(value: Any) -> Any:
    """A Jira option object (``{"key"}``, ``{"accountId"}``, ``{"name"}``, ``{"value"}``, ``{"id"}``) as its scalar."""

    if isinstance(value, Mapping):
        if value.get("type") == "doc":
            return adf_text(value)
        for key in ("key", "accountId", "name", "value", "id"):
            if key in value:
                return value[key]
    if isinstance(value, list):
        return [_option(item) for item in value]
    return value


def _entity(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """A vendor type name (``Task``, ``Sub-task``) as the definition's entity."""

    text = str(_option(value))
    folded = re.sub(r"[^a-z0-9]", "", text.casefold())
    for name, entity in definition.entities.items():
        for candidate in (name, entity.query_name or name):
            if re.sub(r"[^a-z0-9]", "", candidate.casefold()) == folded:
                return name
    for alias in definition.entity_aliases:
        if re.sub(r"[^a-z0-9]", "", alias.casefold()) == folded:
            return alias
    return text


def _jira_fields(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """A Jira REST ``fields`` object as the record's own fields.

    Option objects become their scalar, ``customfield_*`` becomes the
    canonical name the definition's ``custom_fields`` gives it, a status
    name becomes the workflow state its alias names, ADF becomes text, and
    ``issuetype`` is dropped because the create's ``entity`` carries it.
    """

    if not isinstance(value, Mapping):
        raise OperationRefused("validation_error", "`fields` must be an object", upstream="validation")
    custom = {payload: canonical for canonical, payload in definition.custom_fields.items()}
    out: dict[str, Any] = {}
    for key in sorted(value):
        if key == "issuetype":
            continue
        name = custom.get(key, key)
        scalar = _option(value[key])
        if name == "status" and isinstance(scalar, str):
            scalar = _state(definition, scalar)
        out[name] = scalar
    return out


def _state(definition: ConnectorDefinition, value: str) -> str:
    for entity in definition.entities.values():
        if entity.workflow is not None and value in entity.workflow.aliases:
            return entity.workflow.aliases[value]
    return value


def _csv(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    items = value if isinstance(value, list) else str(value).split(",")
    names = [str(item).strip() for item in items if str(item).strip()]
    if not names or any(name.startswith("*") for name in names):
        return _MISSING
    return names


def _int(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise OperationRefused("validation_error", f"expected an integer, got {value!r}", upstream="validation") from error


def _text(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    return adf_text(value)


def _assignee(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """An assign body (``{"accountId": ...}``, ``null`` to unassign) as the record's ``assignee`` field."""

    return {"assignee": _option(value) if value not in ({}, "") else None}


def _transition(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """A transition id or name as the workflow state it leads to; an unknown one passes through to be refused."""

    raw = str(_option(value))
    for item in mapping.transitions:
        if raw in (str(item["id"]), str(item["name"])):
            return str(item["to"])
    return raw


def vendor_value(value: Any) -> Any:
    """A vendor's wrapped scalar as the scalar: a Graph recipient as its address, an item body as its content.

    ``{"emailAddress": {"address": a}}`` is ``a``; ``{"contentType", "content"}``
    is the content; a ServiceNow reference ``{"value", "display_value"}`` is its
    value; a list is each of its items. Anything else is as given.
    """

    if isinstance(value, list):
        return [vendor_value(item) for item in value]
    if isinstance(value, Mapping):
        if isinstance(value.get("emailAddress"), Mapping):
            return value["emailAddress"].get("address")
        if "content" in value and set(value) <= {"content", "contentType"}:
            return value["content"]
        if "value" in value and set(value) <= {"value", "display_value", "link"}:
            return value["value"]
    return value


def _fields(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """A vendor body object as the record's fields, each value unwrapped (``vendor_value``)."""

    if not isinstance(value, Mapping):
        raise OperationRefused("validation_error", "the request body must be an object", upstream="validation")
    return {str(key): vendor_value(item) for key, item in value.items()}


def _flatten(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    return vendor_value(value)


def _odata(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """Graph's query options (``$filter``, ``$search``, ``$orderby``, ``$select``) as one option string."""

    if not isinstance(value, Mapping):
        return str(value)
    parts = [f"{key}={value[key]}" for key in value if value[key] not in (None, "")]
    return "&".join(parts) if parts else _MISSING


def _cql_literal(value: Any) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _cql(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """Confluence v2 list filters (``title``, ``status``, a constant ``type``) as the CQL the v1 search would take."""

    if not isinstance(value, Mapping):
        return str(value)
    clauses = []
    for key, item in value.items():
        if isinstance(item, list):
            clauses.append(f"{key} IN (" + ", ".join(_cql_literal(entry) for entry in item) + ")")
        else:
            clauses.append(f"{key} = {_cql_literal(item)}")
    return " AND ".join(clauses)


def _slack_in(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """A channel id as the Slack search modifier that scopes to it: a channel's history is a search in it."""

    return f"in:{value}"


def locator(query: Any, offset: int) -> str:
    """A continuation that carries its query (Salesforce's ``nextRecordsUrl``): the query, base64url, then the offset."""

    encoded = base64.urlsafe_b64encode(str(query or "").encode("utf-8")).decode("ascii").rstrip("=")
    return f"{encoded}-{offset}"


def _locator_query(definition: ConnectorDefinition, value: Any, mapping: AnvilMapping) -> Any:
    """The query a ``locator`` carries."""

    encoded = str(value).rsplit("-", 1)[0]
    try:
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise OperationRefused("validation_error", f"The locator {value!r} is not one this service issued.",
                               upstream="invalid_cursor") from error


TRANSFORMS: Mapping[str, Callable[[Any, Any, AnvilMapping], Any]] = {
    "assignee": _assignee,
    "cql": _cql,
    "csv": _csv,
    "entity": _entity,
    "fields": _fields,
    "flatten": _flatten,
    "int": _int,
    "jira_fields": _jira_fields,
    "locator_query": _locator_query,
    "odata": _odata,
    "slack_in": _slack_in,
    "text": _text,
    "transition": _transition,
}


@dataclass(frozen=True)
class PlannedCall:
    """What one request becomes: a connector tool and its arguments."""

    tool: str
    args: dict[str, Any]
    start_at: int = 0


def plan_call(mapping: AnvilMapping, entry: OperationMap, request: Mapping[str, Any],
              definition: ConnectorDefinition) -> PlannedCall:
    """The tool call *request* becomes under *entry*, or ``OperationRefused``."""

    if entry.unmodelled is not None or entry.tool is None:
        raise OperationRefused("unsupported_operation",
                               f"{entry.operation_id} is not modelled by the {mapping.connector} connector: {entry.unmodelled}")
    args: dict[str, Any] = {}
    for name, spec in entry.args.items():
        value = read_arg(request, spec)
        if value is not _MISSING and spec.transform is not None:
            value = TRANSFORMS[spec.transform](definition, value, mapping)
        if value is not _MISSING and spec.values is not None and isinstance(value, str | int):
            value = spec.values.get(str(value), value)
        if value is not _MISSING and spec.rename is not None and isinstance(value, Mapping):
            value = {spec.rename.get(key, key): item for key, item in value.items()}
        if value is _MISSING:
            if spec.required:
                raise OperationRefused("validation_error", f"Field '{spec.label if spec.source else name}' is required.",
                                       upstream="validation")
            continue
        args[name] = value
    start_at = 0
    page = request.get("page")
    shape = entry.result.get("shape")
    if isinstance(page, Mapping):
        start_at = _offset(page.get("cursor"))
        if shape == "page":
            args["start_at"] = start_at
            args["max_results"] = int(page.get("size") or 1)
        elif shape in {"list", "token_page"} and start_at:
            # Only what the client sent becomes an argument: a size Anvil
            # defaulted is applied to the answer, so the call graded is the
            # call an in-process agent sending the same request would make.
            args["start_at"] = start_at
    elif entry.cursor is not None:
        token = read_location(request, entry.cursor)
        start_at = _offset(None if token is _MISSING else token)
        if start_at and shape in {"page", "token_page", "list"}:
            args["start_at"] = start_at
    tool = entry.tool
    if entry.tool_by is not None:
        chosen = read_location(request, entry.tool_by[0])
        tool = entry.tool_by[1].get(str(chosen), tool) if chosen is not _MISSING else tool
    return PlannedCall(tool=tool, args=args, start_at=start_at)


def _offset(cursor: Any) -> int:
    """A cursor this provider minted: the decimal offset of the next item, alone or ending a query locator."""

    if cursor in (None, ""):
        return 0
    text = str(cursor).rsplit("-", 1)[-1]
    if not text.isdigit():
        raise OperationRefused("validation_error", f"The cursor {str(cursor)!r} is not one this service issued.",
                               upstream="invalid_cursor")
    return int(text)


# -- executing -----------------------------------------------------------------------------


class Backend(Protocol):
    """Where a planned call runs."""

    @property
    def definition(self) -> ConnectorDefinition: ...

    def call(self, tool: str, args: Mapping[str, Any]) -> Any: ...

    def record(self, reference: Any) -> Mapping[str, Any] | None: ...

    def snapshot(self) -> dict[str, dict[str, Any]]: ...


class EmulatorBackend:
    """A connector emulator's own state: serving a corpus."""

    def __init__(self, emulator: ConnectorEmulator) -> None:
        self.emulator = emulator

    @property
    def definition(self) -> ConnectorDefinition:
        return self.emulator.definition

    def call(self, tool: str, args: Mapping[str, Any]) -> Any:
        return self.emulator.call(tool, **dict(args))

    def record(self, reference: Any) -> Mapping[str, Any] | None:
        try:
            return self.emulator.records[self.emulator.resolve(reference)]
        except ConnectorError:
            return None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Every record by fid, as the evaluation service's ``snapshot`` gives it."""
        return {fid: dict(record) for fid, record in sorted(self.emulator.records.items())}


class ServiceBackend:
    """One run of an evaluation service: serving an eval case, attribution and designed failures included."""

    def __init__(self, service: ConnectorEvaluationService, principal: str, run_id: str, connector: str) -> None:
        self.service = service
        self.principal = principal
        self.run_id = run_id
        self.connector = connector

    @property
    def definition(self) -> ConnectorDefinition:
        return self.service.definitions[self.connector]

    def call(self, tool: str, args: Mapping[str, Any]) -> Any:
        return self.service.call(self.principal, self.run_id, f"{self.connector}.{tool}", args)

    def record(self, reference: Any) -> Mapping[str, Any] | None:
        return self.service.lookup(self.principal, self.run_id, self.connector, reference)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return self.service.snapshot(self.principal, self.run_id)


@dataclass(frozen=True)
class Answer:
    """A provider answer, and whether a connector tool ran to produce it."""

    response: dict[str, Any]
    called: bool
    tool: str | None = None
    args: Mapping[str, Any] | None = None


def answer(mapping: AnvilMapping, backend: Backend, request: Mapping[str, Any]) -> Answer:
    """Answer one normalized Anvil request from *backend*'s state."""

    from .serving import ServingError

    entry = mapping.entry(str(request.get("operationId")), method=request.get("method"), path=request.get("pathTemplate"))
    if entry is None:
        return Answer(_refusal("unsupported_operation", f"{request.get('operationId')} has no mapping for connector "
                                                        f"{mapping.connector}"), called=False)
    try:
        planned = plan_call(mapping, entry, request, backend.definition)
    except OperationRefused as refused:
        return Answer(_refusal(refused.code, refused.message, upstream=refused.upstream, mapping=mapping),
                      called=False, tool=entry.tool)
    try:
        result = backend.call(planned.tool, planned.args)
        response = _shape(mapping, entry, backend, request, planned, result)
    except ConnectorError as error:
        response = _connector_error(mapping, error)
    except ServingError as error:
        response = _refusal("validation_error", str(error), upstream="serving", mapping=mapping)
    except OperationRefused as refused:
        response = _refusal(refused.code, refused.message, upstream=refused.upstream, mapping=mapping)
    return Answer(response, called=True, tool=planned.tool, args=planned.args)


def _refusal(code: str, message: str, *, upstream: str | None = None, mapping: AnvilMapping | None = None,
             status: int | None = None, body: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if upstream:
        error["upstreamCode"] = upstream
    if status is not None:
        error["status"] = status
    if body is None and mapping is not None and mapping.error_body is not None:
        body = _fill(mapping.error_body, message)
    if body is not None:
        error["body"] = body
    return {"ok": False, "error": error}


def _fill(template: Any, message: str) -> Any:
    if isinstance(template, str):
        return template.replace("{message}", message)
    if isinstance(template, list):
        return [_fill(item, message) for item in template]
    if isinstance(template, Mapping):
        return {key: _fill(value, message) for key, value in template.items()}
    return template


def _connector_error(mapping: AnvilMapping, error: ConnectorError) -> dict[str, Any]:
    from .query import QueryError

    code = _STATUS_CODES.get(error.code, "upstream_unavailable" if error.code >= 500 or error.code == 207 else "validation_error")
    cause = error.__cause__
    body = cause.body if isinstance(cause, QueryError) else None
    # Slack answers its errors with 200 and `{"ok": false}`: the vendor status is the one served.
    status = error.code if 200 <= error.code < 600 and error.code != 207 else None
    return _refusal(code, error.message, upstream=error.kind, mapping=mapping, status=status, body=body)


# -- shaping the answer --------------------------------------------------------------------


def _page_answer(items: list[Any], start: int, request: Mapping[str, Any], is_last: bool) -> dict[str, Any]:
    """One page as the protocol wants it: at most ``page.size`` items, and the offset after them."""

    page = request.get("page")
    size = int(page.get("size") or 0) if isinstance(page, Mapping) else 0
    if size and len(items) > size:
        # The tool ran with the client's own size (or its default), which can
        # exceed the page Anvil asked for; the rest stay reachable by cursor.
        items, is_last = items[:size], False
    return {"ok": True, "items": items, "nextCursor": None if is_last else str(start + len(items))}


def _slice(items: list[Any], planned: PlannedCall, request: Mapping[str, Any], key: str) -> dict[str, Any]:
    page = request.get("page")
    if isinstance(page, Mapping):
        size = max(1, int(page.get("size") or 1))
        chosen = items[planned.start_at:planned.start_at + size]
        return _page_answer(chosen, planned.start_at, request, planned.start_at + size >= len(items))
    return {"ok": True, "result": {key: items}}


_DROP: Any = object()


def _fill_envelope(template: Any, context: Mapping[str, Any]) -> Any:
    """*template* with its ``$name`` strings replaced from *context*; a key whose value is dropped is left out."""

    if isinstance(template, str) and template.startswith("$"):
        name, _, path = template[1:].partition(".")
        if name not in context:
            return template
        value = context[name]
        for part in path.split(".") if path else ():
            value = value.get(part, _DROP) if isinstance(value, Mapping) else _DROP
        return value
    if isinstance(template, list):
        return [item for item in (_fill_envelope(item, context) for item in template) if item is not _DROP]
    if isinstance(template, Mapping):
        out = {}
        for key, value in template.items():
            filled = _fill_envelope(value, context)
            if filled is not _DROP:
                out[key] = filled
        return out
    return template


def _list_body(spec: Mapping[str, Any], planned: PlannedCall, result: Mapping[str, Any]) -> dict[str, Any]:
    items = list(result.get("items") or ())
    start = int(result.get("start_at") or 0)
    last = bool(result.get("is_last"))
    after = start + len(items)
    next_cursor: Any = _DROP if last else (locator(planned.args.get("query"), after)
                                           if spec.get("cursor") == "locator" else str(after))
    link = spec.get("next_link")
    next_link: Any = _DROP
    if not last and isinstance(link, str):
        next_link = link.replace("{cursor}", str(next_cursor))
    context = {"items": items, "total": result.get("total"), "is_last": last, "has_more": not last,
               "next": next_cursor, "next_link": next_link, "args": dict(planned.args)}
    envelope = spec.get("envelope") or {spec.get("items", "items"): "$items", "total": "$total"}
    filled: dict[str, Any] = _fill_envelope(envelope, context)
    return filled


def _shape(mapping: AnvilMapping, entry: OperationMap, backend: Backend, request: Mapping[str, Any],
           planned: PlannedCall, result: Any) -> dict[str, Any]:
    spec = entry.result
    shape = spec.get("shape")
    envelope = spec.get("envelope")
    if shape in {"list", "token_page"}:
        # Anvil pages an operation whose continuation it reads from the
        # contract (a body token too, since it learned Jira's
        # `nextPageToken`): it then asks for one page and writes the vendor's
        # envelope itself.
        if isinstance(request.get("page"), Mapping):
            return _page_answer(list(result.get("items") or ()), int(result.get("start_at") or 0), request,
                                bool(result.get("is_last")))
        if shape == "list":
            return {"ok": True, "result": _list_body(spec, planned, result)}
    if envelope is not None and shape in {"record", "pick", "empty"}:
        base = result if shape == "record" else (
            {key: result.get(key) for key in spec.get("keys") or () if key in result} if shape == "pick" else None)
        return {"ok": True, "result": _fill_envelope(envelope, {"record": base, "args": dict(planned.args)})}
    if shape == "page":
        items = list(result.get("items") or ())
        start = int(result.get("start_at") or 0)
        if isinstance(request.get("page"), Mapping):
            return _page_answer(items, start, request, bool(result.get("is_last")))
        return {"ok": True, "result": {spec.get("items", "items"): items, "total": result.get("total")}}
    if shape == "token_page":
        items = list(result.get("items") or ())
        start = int(result.get("start_at") or 0)
        body: dict[str, Any] = {spec.get("items", "items"): items, spec.get("last", "isLast"): bool(result.get("is_last"))}
        if not result.get("is_last"):
            body[spec.get("next", "nextPageToken")] = str(start + len(items))
        return {"ok": True, "result": body}
    if shape == "record":
        return {"ok": True, "result": result}
    if shape == "pick":
        keys = tuple(spec.get("keys") or ())
        return {"ok": True, "result": {key: result.get(key) for key in keys if key in result}}
    if shape == "empty":
        return {"ok": True, "result": None}
    reference = planned.args.get("id")
    record = backend.record(reference) if reference is not None else None
    if record is None:
        raise OperationRefused("not_found", f"{reference} has no record to read back", upstream="not_found")
    if shape == "comment":
        comments = _comments(record)
        if not comments:
            raise OperationRefused("upstream_unavailable", "the comment was not recorded", upstream="comment")
        return {"ok": True, "result": comments[-1]}
    if shape == "comments":
        return _slice(_comments(record), planned, request, spec.get("items", "comments"))
    if shape == "transitions":
        return _slice(_transitions(mapping, backend.definition, record), planned, request, spec.get("items", "transitions"))
    raise OperationRefused("upstream_unavailable", f"unknown result shape {shape!r}")


def _comments(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A record's comments as the vendor lists them: the ones it carried, then the ones added."""

    raw = [*(record.get("comments") or ()), *(record.get("comments_added") or ())]
    out = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, Mapping):
            body = adf_text(item.get("body") or item.get("text") or "")
            author = str(item.get("author") or item.get("by") or "")
            at = item.get("at") or item.get("created") or item.get("created_at")
        else:
            body, author, at = str(item), "", None
        out.append({"id": str(10000 + index), "body": body,
                    "author": {"accountId": author, "displayName": author}, "created": at, "updated": at})
    return out


def _transitions(mapping: AnvilMapping, definition: ConnectorDefinition, record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The transitions the record's workflow allows from where it stands, in the mapping's order."""

    entity = definition.entities.get(str(record.get("entity")))
    workflow = entity.workflow if entity is not None else None
    if workflow is None:
        return []
    current = workflow.canonical_state(str(record.get(workflow.field, workflow.states[0])))
    allowed = set(workflow.transitions.get(current, ()))
    return [{"id": str(item["id"]), "name": str(item["name"]), "to": {"name": str(item["name"])}}
            for item in mapping.transitions if str(item["to"]) in allowed]


SHAPES = frozenset({"page", "list", "token_page", "record", "pick", "empty", "comment", "comments", "transitions"})


__all__ = [
    "MAPPING_SCHEMA",
    "PROTOCOL_VERSION",
    "SHAPES",
    "TRANSFORMS",
    "AnvilMapping",
    "Answer",
    "Arg",
    "Backend",
    "ContractOperation",
    "EmulatorBackend",
    "MappingError",
    "OperationMap",
    "OperationRefused",
    "PlannedCall",
    "ServiceBackend",
    "adf_text",
    "answer",
    "locator",
    "lint_mapping",
    "load_mapping",
    "mapping_path",
    "operations_from_air",
    "operations_from_table",
    "parse_mapping",
    "plan_call",
    "read_air",
    "read_arg",
    "read_location",
    "shipped_mappings",
    "vendor_value",
]
