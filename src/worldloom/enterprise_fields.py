"""Bind authored field requirements to the existing connector schema and predicates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from .connector_data import ConnectorRecord
from .connector_definition import (
    ConnectorDefinition,
    ConnectorFieldDefinition,
    builtin_connector_definitions,
    load_connector_definition,
)
from .enterprise_queries import PlannedEnterpriseQuery, SourceRequirement
from .predicates import FieldPredicate, Predicate, PredicateOp

if TYPE_CHECKING:
    from .enterprise_specs import SpecRegistry, WorkflowSpec


def _overlay(
    definition: ConnectorDefinition, entity: str, fields: tuple[ConnectorFieldDefinition, ...]
) -> ConnectorDefinition:
    # Role aliases are valid authoring targets. The same manifest applies to
    # each concrete member so predicates and projections resolve consistently.
    for member in definition.entity_members(entity):
        definition = definition.with_fields(member, fields)
    return definition


def source_requirement(
    *, connector: str, entity: str, input_format: str,
    registry: SpecRegistry, workflow: WorkflowSpec,
) -> SourceRequirement:
    spec = registry.connectors[connector].entity(entity)
    roles = [role for role in workflow.sources if role.connector == connector and entity in role.entities]
    requested = sorted(set(spec.required_fields) | {field for role in roles for field in role.required_fields})
    if not requested and not spec.field_definitions:
        return SourceRequirement(connector=connector, entity=entity, input_format=input_format,
                                 minimum=max((role.minimum for role in roles), default=1))
    definition = load_connector_definition(connector)
    definition = _overlay(definition, entity, spec.field_definitions)
    members = definition.entity_members(entity)
    fields = {field.canonical: field for member in members for field in definition.fields_for(member)}
    required: list[str] = []
    for name in requested:
        resolved = next((field for field in fields.values() if name in (field.id, field.canonical, field.name, field.query_name, field.payload_name, *field.aliases)), None)
        if resolved is not None:
            if not resolved.queryable:
                raise ValueError(f"required field {connector}/{entity}/{name} is not queryable")
            required.append(resolved.canonical)
        elif name in definition.query_fields:
            required.append(name)
        else:
            raise ValueError(f"required field {connector}/{entity}/{name} has no authored definition")
    if required:
        definition.tool_for(entity, "search")
    return SourceRequirement(
        connector=connector, entity=entity, input_format=input_format,
        minimum=max((role.minimum for role in roles), default=1),
        required_fields=tuple(sorted(set(required))),
        field_definitions=tuple(sorted(spec.field_definitions, key=lambda field: field.id)),
    )


def query_connector_definitions(
    queries: Iterable[PlannedEnterpriseQuery],
    definitions: Mapping[str, ConnectorDefinition] | None = None,
) -> dict[str, ConnectorDefinition]:
    """Rebuild the exact authored manifests after JSONL export and replay."""
    available = dict(definitions if definitions is not None else builtin_connector_definitions())
    authored: dict[tuple[str, str, str], ConnectorFieldDefinition] = {}
    for query in queries:
        for requirement in query.generation.source_requirements:
            if not requirement.field_definitions:
                continue
            definition = available.get(requirement.connector)
            if definition is None:
                raise ValueError(f"missing connector definition: {requirement.connector}")
            for member in definition.entity_members(requirement.entity):
                for field in requirement.field_definitions:
                    key = (requirement.connector, member, field.id)
                    if key in authored and authored[key] != field:
                        raise ValueError(f"conflicting field definition: {'/'.join(key)}")
                    authored[key] = field
            available[requirement.connector] = _overlay(definition, requirement.entity, requirement.field_definitions)
    return dict(sorted(available.items()))


def enrich_required_fields(
    records: Iterable[ConnectorRecord], queries: Iterable[PlannedEnterpriseQuery],
) -> list[ConnectorRecord]:
    """Materialize required values once, using the payload synthesizer's rules."""
    from .connector_payload import manifest_value

    planned = tuple(queries)
    definitions = query_connector_definitions(planned)
    requirements = tuple(source for query in planned for source in query.generation.source_requirements if source.required_fields)
    out: list[ConnectorRecord] = []
    for record in records:
        definition = definitions.get(record.connector)
        fields = dict(record.fields)
        if definition is not None:
            for requirement in requirements:
                if requirement.connector != record.connector:
                    continue
                members = set(definition.entity_members(requirement.entity))
                actual = set(definition.entity_members(record.entity))
                if not members.intersection(actual):
                    continue
                for name in requirement.required_fields:
                    field = next((definition.resolve_field(member, name) for member in sorted(actual) if definition.resolve_field(member, name) is not None), None)
                    if field is None:
                        if fields.get(name) is not None:
                            continue
                        raise ValueError(f"required source field {record.connector}/{record.entity}/{name} has no value in {record.id}")
                    canonical_record = {**fields, "fid": record.id, "entity": record.entity, "connector": record.connector}
                    label = f"{record.connector}/{record.entity}/{name} on {record.id}"
                    if not field.is_present(canonical_record):
                        raise ValueError(f"required source field {label} is absent by its presence predicate")
                    existing = [fields[key] for key in dict.fromkeys((field.canonical, field.id, field.payload_name)) if key is not None and key in fields]
                    if any(not field.valid_value(value) for value in existing):
                        raise ValueError(f"required source field {label} has an invalid authored value")
                    if existing and any(value != existing[0] for value in existing[1:]):
                        raise ValueError(f"required source field {label} has conflicting canonical and native values")
                    value = manifest_value(definition, canonical_record, field, required=True)
                    if value is None:
                        raise ValueError(f"required source field {label} has an explicit null value")
                    if not field.valid_value(value):
                        raise ValueError(f"required source field {label} has an invalid synthesized value")
                    fields[name] = value
        out.append(record.model_copy(update={"fields": fields}) if fields != record.fields else record)
    return out


def required_field_payload(
    requirement: SourceRequirement, definition: ConnectorDefinition,
) -> dict[str, Any]:
    """A real filter and native projection, using the shared predicate algebra."""
    members = definition.entity_members(requirement.entity)
    projection: list[str] = []
    for name in requirement.required_fields:
        field = next((definition.resolve_field(member, name) for member in members if definition.resolve_field(member, name) is not None), None)
        projection.append((field.payload_name or field.id) if field else definition.query_fields.get(name, name))
    return {
        "predicate": Predicate(where=tuple(FieldPredicate(field=name, op=PredicateOp.NE, value=None) for name in requirement.required_fields)).model_dump(mode="json"),
        "fields": sorted(set(projection)),
    }


__all__ = ["enrich_required_fields", "query_connector_definitions", "required_field_payload", "source_requirement"]
