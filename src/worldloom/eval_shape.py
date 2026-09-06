"""Bind real-world eval shape to the connector contracts that execute it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .connector_definition import ConnectorDefinition
from .connector_fields import synthesize_custom_fields
from .eval_design import EvalShape, RecordShapeRequirement


@dataclass(frozen=True)
class RecordShapeApplication:
    connector: str
    entity: str
    requested_custom_fields: int
    existing_custom_fields: int
    added_custom_fields: int
    total_manifest_fields: int


def _apply_record_requirement(
    definition: ConnectorDefinition,
    requirement: RecordShapeRequirement,
    *,
    seed: int,
) -> tuple[ConnectorDefinition, RecordShapeApplication]:
    if requirement.entity not in definition.entities:
        raise ValueError(
            f"shape references unknown {requirement.connector} entity {requirement.entity!r}"
        )
    existing = definition.fields_for(requirement.entity)
    needed = max(0, requirement.custom_fields - len(existing))
    widened = definition
    if needed:
        # Start above every existing numeric suffix when possible, but keep a
        # deterministic floor. Imported customer ids remain untouched.
        start = 10_000
        numeric = []
        for field in existing:
            suffix = "".join(ch for ch in field.id if ch.isdigit())
            if suffix:
                numeric.append(int(suffix))
        if numeric:
            start = max(start, max(numeric) + 1)
        generated = synthesize_custom_fields(
            connector=requirement.connector,
            entity=requirement.entity,
            count=needed,
            seed=seed,
            start=start,
        )
        widened = definition.with_fields(requirement.entity, generated)
    final = widened.fields_for(requirement.entity)
    if len(final) < requirement.custom_fields:
        raise ValueError(
            f"could not satisfy custom-field shape for {requirement.connector}/"
            f"{requirement.entity}: {len(final)} < {requirement.custom_fields}"
        )
    return widened, RecordShapeApplication(
        connector=requirement.connector,
        entity=requirement.entity,
        requested_custom_fields=requirement.custom_fields,
        existing_custom_fields=len(existing),
        added_custom_fields=needed,
        total_manifest_fields=len(final),
    )


def shape_connector_definitions(
    shape: EvalShape,
    definitions: Mapping[str, ConnectorDefinition],
    *,
    seed: int,
) -> tuple[dict[str, ConnectorDefinition], tuple[RecordShapeApplication, ...]]:
    """Return definitions specialized for one candidate's record-shape contract."""

    result = dict(definitions)
    applications: list[RecordShapeApplication] = []
    for requirement in shape.records:
        try:
            definition = result[requirement.connector]
        except KeyError as error:
            raise ValueError(
                f"shape references unavailable connector {requirement.connector!r}"
            ) from error
        widened, application = _apply_record_requirement(
            definition,
            requirement,
            seed=seed,
        )
        result[requirement.connector] = widened
        applications.append(application)
    return dict(sorted(result.items())), tuple(applications)


__all__ = ["RecordShapeApplication", "shape_connector_definitions"]
