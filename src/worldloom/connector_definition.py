"""Declarative connector contracts for executable agent evaluations.

A connector definition is the thin waist between Worldloom's canonical records
and every connector-specific consumer: loader, emulator, query compiler,
payload shaper, trace grader, MCP surface, and eval generation. Product
semantics live in data. Engines stay generic.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from pydantic import Field, model_validator

from .connector_projection import ConnectorRecordProjection
from .models import Model
from .predicates import Predicate, RelativeTime, evaluate

CONNECTOR_DEFINITION_SCHEMA: Literal["worldloom.connector-definition/v1"] = (
    "worldloom.connector-definition/v1"
)

ConnectorMaturity = Literal["ga", "beta", "eap", "product_surface"]
ConnectorFieldType = Literal[
    "text",
    "rich_text",
    "integer",
    "number",
    "boolean",
    "date",
    "datetime",
    "option",
    "multi_option",
    "user",
    "multi_user",
    "cascading",
    "reference",
    "url",
    "json",
]
ConnectorOperation = Literal[
    "search",
    "get",
    "create",
    "update",
    "comment",
    "transition",
    "transform",
    "delete",
    "move",
    "send",
    "reply",
    "forward",
    "post",
    "upload",
    "download",
    "invoke",
]


class ConnectorIdDefinition(Model):
    field: str
    pattern: str


class ConnectorFieldDefinition(Model):
    """One harvested or synthetic field in a connector entity schema."""

    id: str
    canonical: str
    name: str
    aliases: tuple[str, ...] = ()
    field_type: ConnectorFieldType = "text"
    options: tuple[str, ...] = ()
    required_for: tuple[str, ...] = ()
    screens: tuple[str, ...] = ()
    fill_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    cardinality: int | None = Field(default=None, ge=0)
    deprecated: bool = False
    queryable: bool = True
    writable: bool = True
    query_name: str | None = None
    payload_name: str | None = None
    average_bytes: int = Field(default=32, ge=0)
    present_when: Predicate | None = None

    @model_validator(mode="after")
    def _field_shape(self) -> ConnectorFieldDefinition:
        if self.field_type in {"option", "multi_option", "cascading"} and not self.options:
            raise ValueError(f"{self.id}: option-like fields need a non-empty option domain")
        if self.cardinality is not None and self.options and self.cardinality < len(self.options):
            raise ValueError(f"{self.id}: cardinality cannot be smaller than the option domain")
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"{self.id}: duplicate field options")
        # Population must depend only on this immutable record. A historical,
        # relational, or relative-time condition cannot be evaluated without a
        # context the payload shaper does not own.
        if self.present_when is not None and (
            self.present_when.as_of is not None
            or self.present_when.joins
            or any(isinstance(item.value, RelativeTime) for item in self.present_when.where)
        ):
            raise ValueError("field presence conditions must be record-local")
        return self

    def is_present(self, record: Mapping[str, Any]) -> bool:
        """Whether this record permits the field, independently of sparsity."""
        return self.present_when is None or evaluate(self.present_when, record)

    def valid_value(self, value: Any) -> bool:
        """Validate a populated value without conflating null with requiredness."""
        if value is None:
            return True
        if self.field_type in {"text", "rich_text", "reference", "url"}:
            return isinstance(value, str)
        if self.field_type == "boolean":
            return isinstance(value, bool)
        if self.field_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if self.field_type == "number":
            return (isinstance(value, int) and not isinstance(value, bool)) or (
                isinstance(value, float) and math.isfinite(value)
            )
        if self.field_type == "option":
            return isinstance(value, str) and value in self.options
        if self.field_type == "multi_option":
            return isinstance(value, (list, tuple)) and all(
                isinstance(item, str) and item in self.options for item in value
            )
        if self.field_type in {"date", "datetime"}:
            if not isinstance(value, str):
                return False
            try:
                if self.field_type == "date":
                    date.fromisoformat(value)
                else:
                    datetime.fromisoformat(value)
                return True
            except ValueError:
                return False
        if self.field_type == "user":
            return isinstance(value, str) or (
                isinstance(value, Mapping) and isinstance(value.get("id"), str)
            )
        if self.field_type == "multi_user":
            return isinstance(value, (list, tuple)) and all(
                isinstance(item, str) or (
                    isinstance(item, Mapping) and isinstance(item.get("id"), str)
                ) for item in value
            )
        if self.field_type == "cascading":
            if not isinstance(value, Mapping) or value.get("value") not in self.options:
                return False
            child = value.get("child")
            return child is None or (
                isinstance(child, Mapping) and child.get("value") in self.options
            )
        if self.field_type == "json":
            try:
                json.dumps(value, allow_nan=False)
                return True
            except (TypeError, ValueError):
                return False
        return False


class ConnectorWorkflow(Model):
    field: str
    states: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    strict: bool = True

    @model_validator(mode="after")
    def _closed_state_graph(self) -> ConnectorWorkflow:
        known = set(self.states)
        if not known:
            raise ValueError("connector workflow needs at least one state")
        unknown_sources = set(self.transitions) - known
        unknown_targets = {
            target
            for targets in self.transitions.values()
            for target in targets
            if target not in known
        }
        unknown_aliases = set(self.aliases.values()) - known
        if unknown_sources or unknown_targets or unknown_aliases:
            raise ValueError(
                "workflow references unknown states: "
                f"sources={sorted(unknown_sources)}, "
                f"targets={sorted(unknown_targets)}, "
                f"aliases={sorted(unknown_aliases)}"
            )
        return self

    def canonical_state(self, value: str) -> str:
        return self.aliases.get(value, value)


class ConnectorEntityDefinition(Model):
    kind: str
    ops: dict[str, str]
    workflow: ConnectorWorkflow | None = None
    required_on_create: tuple[str, ...] = ()
    searchable: str | tuple[str, ...] = "*"
    query_name: str | None = None


class ConnectorIdempotency(Model):
    key: tuple[str, ...]
    window_s: int = Field(ge=0)


class ConnectorToolDefinition(Model):
    op: ConnectorOperation
    entities: tuple[str, ...]
    params: dict[str, str]
    page_size: int = Field(ge=1)
    max_results: int = Field(ge=1)
    projection: bool = False
    idempotency: ConnectorIdempotency | None = None
    initial_state: str | None = None

    @model_validator(mode="after")
    def _valid_limits(self) -> ConnectorToolDefinition:
        if self.page_size > self.max_results:
            raise ValueError("tool page_size cannot exceed max_results")
        return self


class ConnectorValidationRule(Model):
    when: dict[str, str | int | float | bool | None]
    locked: tuple[str, ...]
    message: str


class ConnectorAclDefinition(Model):
    model: str
    archived_blocks_edit: bool = False


#: The operations a planner's `EntitySpec` may name (`enterprise_specs.Operation`).
CatalogOperation = Literal[
    "search", "list", "read", "create", "update", "patch", "upsert", "delete", "move",
    "comment", "attach", "link", "draft", "send", "reply", "forward",
]
#: The verbs a connector dataset declares for a record (`connector_data.ConnectorVerb`):
#: the planner's vocabulary without `move`, with `unlink`.
CatalogRecordVerb = Literal[
    "search", "list", "read", "create", "update", "patch", "upsert", "delete",
    "comment", "attach", "link", "unlink", "draft", "send", "reply", "forward",
]
#: What may be done with content once read (`ContentAction` and `ContentVerb`, one set).
CatalogContentVerb = Literal[
    "summarize", "extract", "classify", "compare", "reconcile", "transform", "generate", "render", "convert",
]


class ConnectorCatalogEntity(Model):
    """One entity as the planner and the connector dataset name it.

    The name (the key it is stored under) is a definition entity or one of
    its ``entity_aliases``: the planner speaks of Jira's ``issue`` and
    SharePoint's ``file``, the coarse alias, where the emulator serves the
    concrete ``bug``/``story`` or ``docx``/``pdf``.
    """

    stable_id: str | None = None
    """The field a fixture and a corpus record carry the record's handle in
    (Jira ``key``, ServiceNow ``sys_id``). Not the definition's ``id.field``,
    which is where the *emulator* keeps its ident; the two differ for every
    connector whose records predate the emulator. ``None`` takes the
    catalog's ``stable_id``, then ``id.field``."""
    operations: tuple[CatalogOperation, ...] | None = None
    """What a planned workflow may do to it, in the order the planner lists
    them. ``None`` takes the catalog's ``operations``, then derives them from
    the entity's ``ops`` (``connector_spec_from_definition``)."""
    formats: tuple[str, ...] = ()
    """The file formats a destination may write it as; empty is any."""
    record_verbs: tuple[CatalogRecordVerb, ...] | None = None
    """The verbs a corpus's connector dataset declares for its records. A
    capability exists only where this is stated: a connector nothing
    projects records for (Slack, the system of record) declares none, and
    a pack opts in by stating it."""
    content_verbs: tuple[CatalogContentVerb, ...] = ()
    """What the dataset says may be done with the record's content; only
    meaningful beside ``record_verbs``."""


class ConnectorCatalog(Model):
    """How the planner and the connector dataset name a connector: build-time, never served.

    The emulator serves the definition's entities, tools and ids. The query
    planner (`enterprise_specs.ConnectorSpec`) and the corpus's connector
    dataset (`connector_data.CAPABILITIES`) speak a coarser, older
    vocabulary, and this block is where that vocabulary is stated, so both
    tables are derived from the definition instead of kept beside it. Every
    field is optional; an absent one takes the definition's own answer.
    """

    display_name: str | None = None
    """The name a prompt or a report uses (``Jira``), not the product the
    emulator imitates (``vendor_product``: ``Jira Cloud``). ``None`` takes
    ``vendor_product``."""
    content_actions: tuple[CatalogContentVerb, ...] = ("summarize", "extract")
    """What a planned workflow may do with this connector's content."""
    stable_id: str | None = None
    """The default ``stable_id`` for an entity that states none; ``None`` is ``id.field``."""
    operations: tuple[CatalogOperation, ...] | None = None
    """The default ``operations`` for an entity that states none."""
    entities: dict[str, ConnectorCatalogEntity] | None = None
    """The planner's entities, in the order it lists them. ``None`` is every
    definition entity, in definition order (the system of record's catalogue
    of record kinds, and every pack that states no catalog)."""


class ConnectorDefinition(Model):
    """One complete, versioned connector contract."""

    definition_schema: Literal["worldloom.connector-definition/v1"] = Field(
        default=CONNECTOR_DEFINITION_SCHEMA,
        alias="schema",
        serialization_alias="schema",
    )
    connector: str
    version: str
    vendor_product: str
    maturity: ConnectorMaturity = "ga"
    capability_notes: tuple[str, ...] = ()
    clock: str
    id: ConnectorIdDefinition
    payload_shape: str
    query_language: str
    query_fields: dict[str, str] = Field(default_factory=dict)
    acl: ConnectorAclDefinition
    errors: dict[str, tuple[int, str]]
    faults: tuple[str, ...] = ()
    options: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    custom_fields: dict[str, str] = Field(default_factory=dict)
    field_manifests: dict[str, tuple[ConnectorFieldDefinition, ...]] = Field(
        default_factory=dict
    )
    state_codes: dict[str, dict[str, int | str]] = Field(default_factory=dict)
    validation_rules: dict[str, tuple[ConnectorValidationRule, ...]] = Field(
        default_factory=dict
    )
    entities: dict[str, ConnectorEntityDefinition]
    entity_aliases: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    tools: dict[str, ConnectorToolDefinition]
    aliases: dict[str, str] = Field(default_factory=dict)
    record_projection: ConnectorRecordProjection | None = None
    """How a catalogue record appears on this connector (``sor.product_records``).

    A build-time concern, not part of the served contract: ``served_dict``
    leaves it out, so an evaluation row carries the definition an agent is
    served and nothing about how its records were derived."""
    catalog: ConnectorCatalog | None = None
    """How the planner and the connector dataset name this connector.

    Build-time like ``record_projection``: ``served_dict`` leaves it out. A
    definition without one (every connector pack written before it existed)
    gets the defaults each ``ConnectorCatalog`` field documents."""

    @model_validator(mode="after")
    def _closed_contract(self) -> ConnectorDefinition:
        entity_names = set(self.entities)
        tool_names = set(self.tools)
        for name, tool in self.tools.items():
            missing = set(tool.entities) - entity_names
            if missing:
                raise ValueError(f"tool {name!r} references unknown entities {sorted(missing)}")
            if tool.initial_state is not None:
                if tool.op not in {"create", "send", "post", "upload"}:
                    raise ValueError(f"tool {name!r}: initial_state requires a create operation")
                for entity in tool.entities:
                    workflow = self.entities[entity].workflow
                    if workflow is None or tool.initial_state not in workflow.states:
                        raise ValueError(f"tool {name!r}: initial_state is absent from {entity!r} workflow")
        for entity_name, entity_definition in self.entities.items():
            missing = set(entity_definition.ops.values()) - tool_names
            if missing:
                raise ValueError(
                    f"entity {entity_name!r} references unknown tools {sorted(missing)}"
                )
        alias_targets = {
            target for targets in self.entity_aliases.values() for target in targets
        }
        unknown_entity_aliases = alias_targets - entity_names
        if unknown_entity_aliases:
            raise ValueError(
                f"entity aliases reference unknown entities {sorted(unknown_entity_aliases)}"
            )
        overlapping_aliases = set(self.entity_aliases) & entity_names
        if overlapping_aliases:
            raise ValueError(
                f"entity aliases shadow canonical entities {sorted(overlapping_aliases)}"
            )
        bad_aliases = set(self.aliases.values()) - tool_names
        if bad_aliases:
            raise ValueError(f"aliases reference unknown tools {sorted(bad_aliases)}")
        unknown_manifests = set(self.field_manifests) - entity_names
        if unknown_manifests:
            raise ValueError(f"field manifests reference unknown entities {sorted(unknown_manifests)}")
        for manifest_entity, fields_for_entity in self.field_manifests.items():
            ids = [field.id for field in fields_for_entity]
            canonicals = [field.canonical for field in fields_for_entity]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{manifest_entity}: field ids must be unique")
            if len(canonicals) != len(set(canonicals)):
                raise ValueError(f"{manifest_entity}: canonical field names must be unique")
        for error_name in ("not_found", "denied", "validation", "bad_transition"):
            if error_name not in self.errors:
                raise ValueError(f"missing connector error contract {error_name!r}")
        if self.catalog is not None:
            findings = self._catalog_findings(self.catalog, entity_names)
            if findings:
                raise ValueError("; ".join(findings))
        return self

    def _catalog_findings(self, catalog: ConnectorCatalog, entity_names: set[str]) -> list[str]:
        """Why a catalog cannot be derived from, each naming the entity, the rule and the fix."""

        findings: list[str] = []
        for field_name in ("stable_id", "display_name"):
            if getattr(catalog, field_name) == "":
                findings.append(f"catalog.{field_name} is empty; state a name or leave it out to take the definition's")
        for field_name in ("content_actions", "operations"):
            values = getattr(catalog, field_name) or ()
            if len(set(values)) != len(values):
                findings.append(f"catalog.{field_name} repeats a value; state each once")
        for name, entry in (catalog.entities or {}).items():
            where = f"catalog.entities.{name}"
            if name not in entity_names and name not in self.entity_aliases:
                findings.append(f"{where}: {name!r} is neither an entity nor an entity alias of {self.connector}; "
                                "name a declared entity, or declare it under entity_aliases")
            if entry.stable_id == "":
                findings.append(f"{where}.stable_id is empty; state a field or leave it out to take {self.id.field!r}")
            for field_name in ("operations", "formats", "record_verbs", "content_verbs"):
                values = getattr(entry, field_name) or ()
                if len(set(values)) != len(values):
                    findings.append(f"{where}.{field_name} repeats a value; state each once")
            if entry.content_verbs and entry.record_verbs is None:
                findings.append(f"{where}: content_verbs without record_verbs declares content for a record the "
                                "dataset does not declare; state record_verbs, or drop content_verbs")
        return findings

    def catalog_entities(self) -> dict[str, ConnectorCatalogEntity]:
        """The catalog's entities, in planner order, each with its defaults filled from the catalog.

        ``stable_id`` is always resolved (catalog, then ``id.field``);
        ``operations`` stays ``None`` when neither the entity nor the catalog
        states it, because deriving it from ``ops`` is the planner's rule
        (``enterprise_specs.connector_spec_from_definition``), not the
        definition's.
        """

        catalog = self.catalog or ConnectorCatalog()
        stated = catalog.entities if catalog.entities is not None else {name: ConnectorCatalogEntity() for name in self.entities}
        return {
            name: entry.model_copy(update={
                "stable_id": entry.stable_id or catalog.stable_id or self.id.field,
                "operations": entry.operations if entry.operations is not None else catalog.operations,
            })
            for name, entry in stated.items()
        }

    @property
    def display_name(self) -> str:
        """The name a prompt uses: the catalog's, else the vendor product."""

        return (self.catalog.display_name if self.catalog is not None else None) or self.vendor_product

    def canonical_tool(self, name: str) -> str:
        canonical = self.aliases.get(name, name)
        if canonical not in self.tools:
            raise KeyError(f"unknown {self.connector} tool {name!r}")
        return canonical

    def tool(self, name: str) -> ConnectorToolDefinition:
        return self.tools[self.canonical_tool(name)]

    def entity_members(self, entity: str) -> tuple[str, ...]:
        """Canonical entity kinds represented by an alias or canonical name."""

        if entity in self.entities:
            return (entity,)
        try:
            return self.entity_aliases[entity]
        except KeyError as error:
            raise KeyError(f"unknown {self.connector} entity {entity!r}") from error

    def entity_matches(self, requested: str, actual: str) -> bool:
        return actual in self.entity_members(requested)

    def tool_for(self, entity: str, operation: str) -> str:
        members = self.entity_members(entity)
        targets = {
            self.entities[member].ops[operation]
            for member in members
            if operation in self.entities[member].ops
        }
        if not targets:
            raise KeyError(
                f"{self.connector}/{entity} does not define operation {operation!r}"
            )
        if len(targets) != 1:
            raise KeyError(
                f"{self.connector}/{entity} maps {operation!r} to multiple tools: "
                f"{sorted(targets)}"
            )
        return self.canonical_tool(targets.pop())

    def query_name_for(self, entity: str) -> str:
        members = self.entity_members(entity)
        names = {self.entities[member].query_name or member for member in members}
        if len(names) != 1:
            raise KeyError(
                f"{self.connector}/{entity} has multiple native query names: {sorted(names)}"
            )
        return names.pop()

    def fields_for(self, entity: str) -> tuple[ConnectorFieldDefinition, ...]:
        members = self.entity_members(entity)
        fields = self.field_manifests.get(members[0], ())
        if len(members) == 1:
            return fields
        # An alias can expose only fields whose full definitions agree across
        # every concrete member. This preserves authored overlays on aliases
        # without guessing which incompatible schema a record meant.
        others = [{field.id: field for field in self.field_manifests.get(member, ())} for member in members[1:]]
        return tuple(field for field in fields if all(manifest.get(field.id) == field for manifest in others))

    def resolve_field(self, entity: str, name: str) -> ConnectorFieldDefinition | None:
        folded = name.casefold()
        for field in self.fields_for(entity):
            names = (field.id, field.canonical, field.name, *field.aliases)
            if any(candidate.casefold() == folded for candidate in names):
                return field
        return None

    def with_fields(
        self,
        entity: str,
        fields_to_add: tuple[ConnectorFieldDefinition, ...],
    ) -> ConnectorDefinition:
        """Return a new definition with an immutable field-manifest overlay."""

        members = self.entity_members(entity)
        if len(members) != 1:
            raise ValueError(
                f"field manifests need one canonical entity, not alias {entity!r}"
            )
        canonical_entity = members[0]
        existing = {field.id: field for field in self.fields_for(canonical_entity)}
        for field in fields_to_add:
            existing[field.id] = field
        merged = tuple(sorted(existing.values(), key=lambda field: field.id))
        manifests = dict(self.field_manifests)
        manifests[canonical_entity] = merged
        compatibility = dict(self.custom_fields)
        query_fields = dict(self.query_fields)
        for field in merged:
            compatibility[field.canonical] = field.payload_name or field.id
            if field.queryable:
                query_fields[field.canonical] = field.query_name or field.id
        return self.model_copy(
            update={
                "field_manifests": manifests,
                "custom_fields": compatibility,
                "query_fields": query_fields,
            },
            deep=True,
        )

    def wire_dict(self) -> dict[str, object]:
        """Serialize using stable on-disk field names, not Python attribute names.

        An absent ``record_projection`` or ``catalog`` is left out rather than
        written as ``null``, so a definition that declares neither serialises
        exactly as it did before the fields existed.
        """

        out = self.model_dump(mode="json", by_alias=True)
        for build_time in ("record_projection", "catalog"):
            if out.get(build_time) is None:
                out.pop(build_time, None)
        return out

    def served_dict(self) -> dict[str, object]:
        """``wire_dict`` without the build-time ``record_projection`` and ``catalog``: what a row embeds."""

        out = self.wire_dict()
        out.pop("record_projection", None)
        out.pop("catalog", None)
        return out


def parse_connector_definition(data: str | bytes) -> ConnectorDefinition:
    """Parse and validate one connector definition from JSON bytes or text."""

    raw = data.decode("utf-8") if isinstance(data, bytes) else data
    return ConnectorDefinition.model_validate(json.loads(raw))


#: Where the shipped definitions live, one ``<connector>.json`` each. A file
#: whose name starts with ``_`` is metadata about the directory, not a
#: connector.
_SHIPPED = ("_data", "connectors")


@lru_cache(maxsize=1)
def _shipped_connectors() -> tuple[str, ...]:
    """Every shipped definition, in reference order.

    The directory listing is what exists; ``_order.json`` only says in which
    order the reference list names them, because that order predates the
    listing (it is the order connectors were added, and error messages and
    ``connector_data`` iterate it). A definition the order file does not name
    follows the named ones alphabetically, so adding a connector is adding one
    file.
    """

    directory = files("worldloom").joinpath(*_SHIPPED)
    listed = sorted(entry.name[:-5] for entry in directory.iterdir()
                    if entry.name.endswith(".json") and not entry.name.startswith("_"))
    order = shipped_order("order")
    named = [name for name in order if name in listed]
    return (*named, *(name for name in listed if name not in named))


@lru_cache(maxsize=8)
def shipped_order(key: str) -> tuple[str, ...]:
    """One of the orders ``_order.json`` pins: ``order`` (the reference list),
    ``specs`` (the planner's registry) or ``capabilities`` (the connector
    dataset's ``connector/entity`` pairs). Each only orders; what exists is
    what the definitions declare."""

    directory = files("worldloom").joinpath(*_SHIPPED)
    return tuple(json.loads(directory.joinpath("_order.json").read_text(encoding="utf-8"))[key])


REFERENCE_CONNECTORS = _shipped_connectors()
"""The shipped connectors, in reference order. Connector packs extend this
list at run time (``reference_connectors``); the constant is the shipped set
only, so importing it never reads a user's pack roots."""


# ---------------------------------------------------------------------------
# Connector packs
# ---------------------------------------------------------------------------
#
# A connector pack (``connector:<name>``, body = a ConnectorDefinition) is found
# on the pack search path like any other kind. Its name is the connector name.
#
# The shadowing rule: a pack whose name is NOT a shipped connector is visible
# from every root (a caller's ``--pack-root``, ``WORLDLOOM_PACK_PATH``, the
# user's ``~/.worldloom/packs``). A pack named like a shipped connector
# replaces it only when it is explicitly in force (``packkit.use`` /
# ``--pack connector:jira``) or sits in a root the caller named for this run
# (``--pack-root``, a Studio workspace). A ``jira.json`` left in the user's home
# or on the environment path is ignored, so a default build and every shipped
# connector stay what they are unless the command that runs says otherwise.


def _pack_definition(name: str) -> ConnectorDefinition | None:
    from . import packkit

    held = packkit.active("connector")
    if held is not None and held.name == name:
        body: ConnectorDefinition = held.body
        return body
    if name in REFERENCE_CONNECTORS:
        if not any(origin == "root" for origin, _ in packkit.search_path()):
            return None
        located = packkit.find("connector", name)
        if located is None or located.origin != "root":
            return None
    elif packkit.find("connector", name) is None:
        return None
    resolved: ConnectorDefinition = packkit.resolve(f"connector:{name}").body
    return resolved


def _shipped_definition(name: str) -> ConnectorDefinition:
    resource = files("worldloom").joinpath(*_SHIPPED, f"{name}.json")
    return parse_connector_definition(resource.read_text(encoding="utf-8"))


def shipped_connector_definition(name: str) -> ConnectorDefinition:
    """The shipped definition of *name*, whatever pack is in force or in view.

    The tables derived from a catalog (the planner's builtin specs, the
    connector dataset's capabilities) read this, never
    ``load_connector_definition``: a pack named like a shipped connector
    changes what is served, not the vocabulary a build plans in.
    """

    if name not in REFERENCE_CONNECTORS:
        raise ValueError(f"unknown built-in connector definition {name!r}")
    return _shipped_definition(name)


def reference_connectors() -> tuple[str, ...]:
    """The shipped connectors in reference order, then every visible connector pack by name."""

    from . import packkit

    extra = {located.envelope.name for located in packkit.discover("connector")}
    held = packkit.active("connector")
    if held is not None:
        extra.add(held.name)
    return (*REFERENCE_CONNECTORS, *sorted(extra - set(REFERENCE_CONNECTORS)))


def is_reference_connector(name: str) -> bool:
    """Whether *name* is a shipped connector or a visible connector pack.

    The shipped set answers without touching a pack root, which is the case on
    every default path; only an unknown name looks further.
    """

    return name in REFERENCE_CONNECTORS or _pack_definition(name) is not None


def load_connector_definition(name: str) -> ConnectorDefinition:
    """Load one connector definition by semantic connector name.

    A connector pack in force (or in a named root) comes first under the
    shadowing rule above; otherwise the shipped definition; otherwise a
    visible connector pack of that name.
    """

    pack = _pack_definition(name)
    if pack is not None:
        return pack
    if name not in REFERENCE_CONNECTORS:
        raise ValueError(f"unknown built-in connector definition {name!r}")
    return _shipped_definition(name)


def builtin_connector_definitions(
    names: tuple[str, ...] | None = None,
) -> dict[str, ConnectorDefinition]:
    """Every reference connector's definition (shipped and packs), by name."""

    chosen = reference_connectors() if names is None else names
    definitions = {name: load_connector_definition(name) for name in chosen}
    return dict(sorted(definitions.items()))


__all__ = [
    "CONNECTOR_DEFINITION_SCHEMA",
    "REFERENCE_CONNECTORS",
    "CatalogContentVerb",
    "CatalogOperation",
    "CatalogRecordVerb",
    "ConnectorAclDefinition",
    "ConnectorCatalog",
    "ConnectorCatalogEntity",
    "ConnectorDefinition",
    "ConnectorEntityDefinition",
    "ConnectorFieldDefinition",
    "ConnectorFieldType",
    "ConnectorIdDefinition",
    "ConnectorIdempotency",
    "ConnectorMaturity",
    "ConnectorOperation",
    "ConnectorRecordProjection",
    "ConnectorToolDefinition",
    "ConnectorValidationRule",
    "ConnectorWorkflow",
    "builtin_connector_definitions",
    "is_reference_connector",
    "load_connector_definition",
    "parse_connector_definition",
    "reference_connectors",
    "shipped_connector_definition",
    "shipped_order",
]
