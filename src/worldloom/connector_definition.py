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
from importlib.resources import files
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import Model
from .predicates import Predicate, RelativeTime, evaluate

CONNECTOR_DEFINITION_SCHEMA: Literal["worldloom.connector-definition/v1"] = (
    "worldloom.connector-definition/v1"
)
REFERENCE_CONNECTORS = (
    "jira",
    "servicenow",
    "salesforce",
    "confluence",
    "sharepoint",
    "drive",
    "outlook",
    "email",
    "onedrive",
    "teams",
    "slack",
    "teamwork_graph",
    "rovo",
    "sor",
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
        return self

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
        """Serialize using stable on-disk field names, not Python attribute names."""

        return self.model_dump(mode="json", by_alias=True)


def parse_connector_definition(data: str | bytes) -> ConnectorDefinition:
    """Parse and validate one connector definition from JSON bytes or text."""

    raw = data.decode("utf-8") if isinstance(data, bytes) else data
    return ConnectorDefinition.model_validate(json.loads(raw))


def load_connector_definition(name: str) -> ConnectorDefinition:
    """Load one built-in connector definition by semantic connector name."""

    resource = files("worldloom").joinpath("_data", "connectors", f"{name}.json")
    if not resource.is_file():
        raise ValueError(f"unknown built-in connector definition {name!r}")
    return parse_connector_definition(resource.read_text(encoding="utf-8"))


def builtin_connector_definitions(
    names: tuple[str, ...] = REFERENCE_CONNECTORS,
) -> dict[str, ConnectorDefinition]:
    definitions = {name: load_connector_definition(name) for name in names}
    return dict(sorted(definitions.items()))


__all__ = [
    "CONNECTOR_DEFINITION_SCHEMA",
    "REFERENCE_CONNECTORS",
    "ConnectorAclDefinition",
    "ConnectorDefinition",
    "ConnectorEntityDefinition",
    "ConnectorFieldDefinition",
    "ConnectorFieldType",
    "ConnectorIdDefinition",
    "ConnectorIdempotency",
    "ConnectorMaturity",
    "ConnectorOperation",
    "ConnectorToolDefinition",
    "ConnectorValidationRule",
    "ConnectorWorkflow",
    "builtin_connector_definitions",
    "load_connector_definition",
    "parse_connector_definition",
]
