"""Declarative connector contracts for executable agent evaluations.

A connector definition is the thin waist between Worldloom's canonical records
and every connector-specific consumer: loader, emulator, query compiler,
payload shaper, trace grader, MCP surface, and eval generation. Product
semantics live in data. Engines stay generic.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Literal

from pydantic import Field, model_validator

from .models import Model

CONNECTOR_DEFINITION_SCHEMA = "worldloom.connector-definition/v1"
REFERENCE_CONNECTORS = (
    "jira",
    "servicenow",
    "salesforce",
    "confluence",
    "sharepoint",
    "drive",
)


class ConnectorIdDefinition(Model):
    field: str
    pattern: str


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
    op: Literal[
        "search",
        "get",
        "create",
        "update",
        "comment",
        "transition",
        "transform",
        "delete",
    ]
    entities: tuple[str, ...]
    params: dict[str, str]
    page_size: int = Field(ge=1)
    max_results: int = Field(ge=1)
    projection: bool = False
    idempotency: ConnectorIdempotency | None = None

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
    state_codes: dict[str, dict[str, int | str]] = Field(default_factory=dict)
    validation_rules: dict[str, tuple[ConnectorValidationRule, ...]] = Field(
        default_factory=dict
    )
    entities: dict[str, ConnectorEntityDefinition]
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
        for entity_name, entity in self.entities.items():
            missing = set(entity.ops.values()) - tool_names
            if missing:
                raise ValueError(
                    f"entity {entity_name!r} references unknown tools {sorted(missing)}"
                )
        bad_aliases = set(self.aliases.values()) - tool_names
        if bad_aliases:
            raise ValueError(f"aliases reference unknown tools {sorted(bad_aliases)}")
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

    def tool_for(self, entity: str, operation: str) -> str:
        try:
            target = self.entities[entity].ops[operation]
        except KeyError as error:
            raise KeyError(
                f"{self.connector}/{entity} does not define operation {operation!r}"
            ) from error
        return self.canonical_tool(target)

    def query_name_for(self, entity: str) -> str:
        try:
            definition = self.entities[entity]
        except KeyError as error:
            raise KeyError(f"unknown {self.connector} entity {entity!r}") from error
        return definition.query_name or entity

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
    "ConnectorIdDefinition",
    "ConnectorIdempotency",
    "ConnectorToolDefinition",
    "ConnectorValidationRule",
    "ConnectorWorkflow",
    "builtin_connector_definitions",
    "load_connector_definition",
    "parse_connector_definition",
]
