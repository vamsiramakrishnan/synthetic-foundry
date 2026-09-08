"""Connector-neutral execution adapter with resumable deterministic checkpoints.

Explicit MCP bindings remain a deployment override. When no override is present,
Worldloom resolves the tool from the canonical ConnectorDefinition so eval
execution, emulation, and capability discovery share one source of truth.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from .connector_definition import load_connector_definition
from .enterprise_corpus import QueryFixture, TraceCall
from .enterprise_queries import PlannedEnterpriseQuery
from .ids import content_key
from .models import Model


class MCPInvoker(Protocol):
    def __call__(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> Awaitable[Mapping[str, Any]]: ...


class ToolBinding(Model):
    connector: str
    operation: str
    entity: str
    tool_name: str
    argument_map: dict[str, str] = Field(default_factory=dict)


_LEGACY_OPERATIONS = {
    "readback": "read",
    "cross_system": "read",
    "list": "search",
    "patch": "update",
    "draft": "create",
}


def canonical_operation(operation: str, *, preexisting_record: bool | None = None) -> str:
    """Resolve a planned verb using its fixture's declared precondition.

    Upsert has no unconditional tool alias. The planner fixes whether the
    destination already exists, so the reference trajectory selects that arm;
    callers without that information must retain the ambiguity as a refusal.
    """
    if operation == "upsert":
        if preexisting_record is None:
            raise ValueError("upsert requires an explicit preexisting_record precondition")
        return "update" if preexisting_record else "create"
    return _LEGACY_OPERATIONS.get(operation, operation)


class RunnerConfig(Model):
    """External tool overrides layered over the installed connector definitions."""

    bindings: tuple[ToolBinding, ...] = ()
    model_tool: str = "content.transform"

    def resolve(
        self, connector: str, operation: str, entity: str, *,
        concrete_hint: str | None = None,
        preexisting_record: bool | None = None,
    ) -> str:
        if connector == "model":
            return self.model_tool
        for binding in self.bindings:
            if (binding.connector, binding.operation, binding.entity) == (
                connector,
                operation,
                entity,
            ):
                return binding.tool_name
        definition = load_connector_definition(connector)
        canonical = canonical_operation(operation, preexisting_record=preexisting_record)
        try:
            members = definition.entity_members(entity)
            concrete = concrete_hint if concrete_hint in members else entity
            tool = definition.tool_for(concrete, canonical)
        except KeyError as error:
            raise KeyError(
                f"no connector tool for {connector}.{operation}.{entity}"
            ) from error
        return f"{connector}.{tool}"


class ExecutionResult(Model):
    query_id: str
    calls: tuple[TraceCall, ...]
    outputs: dict[str, Any]
    completed: bool
    finding: str | None = None


def shard_queries(
    queries: tuple[PlannedEnterpriseQuery, ...], index: int, count: int
) -> tuple[PlannedEnterpriseQuery, ...]:
    if count < 1 or not 0 <= index < count:
        raise ValueError("shard requires count >= 1 and 0 <= index < count")
    return tuple(
        query for position, query in enumerate(queries) if position % count == index
    )


async def execute_query(
    query: PlannedEnterpriseQuery,
    fixture: QueryFixture,
    config: RunnerConfig,
    invoke: MCPInvoker,
    *,
    checkpoint: Callable[[ExecutionResult], None] | None = None,
) -> ExecutionResult:
    outputs: dict[str, Any] = {}
    calls: list[TraceCall] = []
    for node in query.expected_dag:
        dependencies = tuple(node.get("depends_on", ()))
        if any(dependency not in outputs for dependency in dependencies):
            result = ExecutionResult(
                query_id=query.id,
                calls=tuple(calls),
                outputs=outputs,
                completed=False,
                finding=f"unresolved dependencies for {node['id']}",
            )
            if checkpoint:
                checkpoint(result)
            return result
        mutation = query.generation.mutation
        is_destination = (node["connector"], node["entity"]) == (
            mutation.connector, mutation.entity
        )
        tool_name = config.resolve(
            node["connector"], node["kind"], node["entity"],
            concrete_hint=mutation.output_format if is_destination else None,
            preexisting_record=mutation.preexisting_record if is_destination else None,
        )
        arguments: dict[str, Any] = {
            "query_id": query.id,
            "node_id": node["id"],
            "entity": node["entity"],
            "dependencies": {
                dependency: outputs[dependency] for dependency in dependencies
            },
            "fixture": fixture.model_dump(mode="json"),
            "generation_requirement": query.generation.model_dump(mode="json"),
        }
        response = dict(await invoke(tool_name, arguments))
        outputs[node["id"]] = response
        calls.append(
            TraceCall(
                id=content_key("trace-call", query.id, node["id"]),
                connector=node["connector"],
                operation=node["kind"],
                entity=node["entity"],
                depends_on=dependencies,
                record_id=response.get("record_id"),
                record_ids=tuple(response.get("record_ids", ())),
                fact_ids=tuple(response.get("fact_ids", ())),
                evidence_ids=tuple(response.get("evidence_ids", ())),
                succeeded=bool(response.get("succeeded", True)),
            )
        )
        partial = ExecutionResult(
            query_id=query.id,
            calls=tuple(calls),
            outputs=outputs,
            completed=False,
        )
        if checkpoint:
            checkpoint(partial)
        if not calls[-1].succeeded:
            return partial.model_copy(update={"finding": f"node {node['id']} failed"})
    result = ExecutionResult(
        query_id=query.id,
        calls=tuple(calls),
        outputs=outputs,
        completed=True,
    )
    if checkpoint:
        checkpoint(result)
    return result


def json_checkpoint(path: Path) -> Callable[[ExecutionResult], None]:
    """Return an atomic checkpoint writer safe for resume after interruption."""

    def write(result: ExecutionResult) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            result.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)

    return write


def load_checkpoint(path: Path) -> ExecutionResult | None:
    if not path.exists():
        return None
    return ExecutionResult.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
