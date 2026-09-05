"""Compile abstract eval steps against connector definitions.

Eval generation says *what* operation is required. The connector definition says
which concrete tool performs it, what paging/projection behavior it has, and
which workflow states are legal. This module is the only join between those two
contracts.
"""

from __future__ import annotations

from collections.abc import Mapping

from .connector_definition import (
    ConnectorDefinition,
    ConnectorMaturity,
    builtin_connector_definitions,
)
from .eval_design import EvalSpec, EvalStepSpec
from .eval_shape import shape_connector_definitions
from .models import Model


class EvalToolBinding(Model):
    step_id: str
    connector: str
    entity: str
    operation: str
    tool: str
    page_size: int
    max_results: int
    projection: bool
    query_language: str
    maturity: ConnectorMaturity
    workflow_field: str | None = None
    workflow_states: tuple[str, ...] = ()

    @property
    def qualified_tool(self) -> str:
        return f"{self.connector}.{self.tool}"


def _infer_entity(spec: EvalSpec, step: EvalStepSpec) -> str | None:
    if step.entity is not None:
        return step.entity
    candidates = {
        requirement.entity
        for requirement in (*spec.shape.records, *spec.shape.threads)
        if requirement.connector == step.connector
    }
    for requirement in spec.requirements:
        if requirement.selector.get("connector") == step.connector:
            value = requirement.selector.get("entity")
            if isinstance(value, str):
                candidates.add(value)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _infer_operation(step: EvalStepSpec) -> str | None:
    if step.operation is not None:
        return step.operation
    if step.capability in {
        "search",
        "read",
        "extract",
        "create",
        "update",
        "transition",
        "comment",
        "transform",
        "delete",
    }:
        return step.capability
    if step.effect == "write":
        return "update"
    return None


def _validate_shape(
    spec: EvalSpec,
    definitions: Mapping[str, ConnectorDefinition],
) -> None:
    for requirement in (*spec.shape.records, *spec.shape.threads):
        try:
            definition = definitions[requirement.connector]
        except KeyError as error:
            raise ValueError(
                f"{spec.id}: shape references unknown connector {requirement.connector!r}"
            ) from error
        try:
            definition.entity_members(requirement.entity)
        except KeyError as error:
            raise ValueError(
                f"{spec.id}: shape references unknown "
                f"{requirement.connector}/{requirement.entity}"
            ) from error
    for requirement in spec.shape.records:
        if not requirement.projection_required:
            continue
        definition = definitions[requirement.connector]
        members = definition.entity_members(requirement.entity)
        relevant = [
            tool
            for tool in definition.tools.values()
            if tool.projection and any(member in tool.entities for member in members)
        ]
        if not relevant:
            raise ValueError(
                f"{spec.id}: projection required for {requirement.connector}/"
                f"{requirement.entity}, but its definition exposes no projected read/search tool"
            )


def bind_eval_connectors(
    spec: EvalSpec,
    *,
    definitions: Mapping[str, ConnectorDefinition] | None = None,
    candidate_seed: int | None = None,
    require_complete: bool = True,
) -> tuple[EvalToolBinding, ...]:
    """Resolve every connector step to one concrete, definition-owned tool."""

    available = dict(definitions or builtin_connector_definitions())
    if candidate_seed is not None and not spec.shape.empty:
        available, _ = shape_connector_definitions(
            spec.shape,
            available,
            seed=candidate_seed,
        )
    _validate_shape(spec, available)

    bindings: list[EvalToolBinding] = []
    for step in spec.steps:
        if step.connector is None:
            continue
        try:
            definition = available[step.connector]
        except KeyError as error:
            raise ValueError(
                f"{spec.id}/{step.id}: unknown connector {step.connector!r}"
            ) from error
        entity = _infer_entity(spec, step)
        operation = _infer_operation(step)
        if entity is None or operation is None:
            if require_complete:
                missing = []
                if entity is None:
                    missing.append("entity")
                if operation is None:
                    missing.append("operation")
                raise ValueError(
                    f"{spec.id}/{step.id}: connector binding needs {', '.join(missing)}"
                )
            continue
        try:
            tool_name = definition.tool_for(entity, operation)
        except KeyError as error:
            raise ValueError(f"{spec.id}/{step.id}: {error.args[0]}") from error
        tool = definition.tool(tool_name)
        members = definition.entity_members(entity)
        workflows = [definition.entities[member].workflow for member in members]
        workflows = [workflow for workflow in workflows if workflow is not None]
        workflow_field: str | None = None
        states: tuple[str, ...] = ()
        if workflows:
            fields = {workflow.field for workflow in workflows}
            state_sets = {workflow.states for workflow in workflows}
            if len(fields) == 1:
                workflow_field = next(iter(fields))
            if len(state_sets) == 1:
                states = next(iter(state_sets))
        bindings.append(
            EvalToolBinding(
                step_id=step.id,
                connector=step.connector,
                entity=entity,
                operation=operation,
                tool=tool_name,
                page_size=tool.page_size,
                max_results=tool.max_results,
                projection=tool.projection,
                query_language=definition.query_language,
                maturity=definition.maturity,
                workflow_field=workflow_field,
                workflow_states=states,
            )
        )
    return tuple(bindings)


__all__ = ["EvalToolBinding", "bind_eval_connectors"]
