"""A reference executor that runs eval steps through the emulated connectors.

``eval_reference.execute_reference`` walks an instance's steps with whatever
executor the caller supplies, and until now every caller supplied a stub. This
is the executor a campaign should use by default: each connector step projects
the candidate world into that connector's records, forks an emulator over them
with the definition's frozen clock, and calls the tool the step's operation
resolves to. A search returns the records the requirement's selector finds; a
write lands on the precondition record the constructive layer minted. The
proof is therefore a statement about the corpus and the emulator together: the
DAG is executable, every read found something, every write changed something.

Steps without a connector (a transform, a verification) are recorded as
executed with the oracle's evidence, because there is no tool surface for
them to go through; the assertion layer still requires them to appear in
order.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .connector_definition import (
    REFERENCE_CONNECTORS,
    ConnectorDefinition,
    load_connector_definition,
)
from .connector_emulator import ConnectorEmulator
from .eval_design import EvalStepSpec
from .eval_instances import EvalInstance
from .eval_reference import ExecutionStep, StepExecutor
from .predicates import Predicate
from .world import World

_READ = frozenset({"search", "get", "download", "find", "list", "query"})


def _records(world: World, connector: str) -> list[Any]:
    from .eval_candidates import _connector_records

    return _connector_records(world, connector)


def _search_predicates(world: World, connector: str) -> list[Predicate]:
    from .eval_witnesses import witness_payload

    seen: dict[str, Predicate] = {}
    for event in world.events:
        payload = witness_payload(event)
        if payload is None or payload["connector"] != connector or payload["role"] != "witness":
            continue
        fields = {key: value for key, value in payload["fields"].items() if key != "title"}
        predicate = Predicate.equalities(fields, entity=payload["entity"])
        seen.setdefault(predicate.model_dump_json(), predicate)
    return list(seen.values())


def _step_entity(definition: ConnectorDefinition, step: EvalStepSpec, operation: str) -> str:
    if step.entity:
        return definition.entity_members(step.entity)[0]
    for tool in definition.tools.values():
        if tool.op == operation and tool.entities:
            return tool.entities[0]
    return next(iter(definition.entities))


def emulator_executor(
    definitions: Mapping[str, ConnectorDefinition] | None = None,
) -> StepExecutor:
    """Build the executor. Definitions default to the built-in twelve."""

    loaded = dict(definitions or {})

    def definition_for(connector: str) -> ConnectorDefinition:
        if connector not in loaded:
            if connector not in REFERENCE_CONNECTORS:
                raise ValueError(f"no connector definition for {connector!r}")
            loaded[connector] = load_connector_definition(connector)
        return loaded[connector]

    def execute(world: World, step: EvalStepSpec, instance: EvalInstance) -> tuple[World, ExecutionStep]:
        operation = (step.operation or step.capability).lower()
        if not step.connector:
            if step.effect == "write":
                # A write with no surface to land on cannot be proven; saying
                # it happened would make every such eval pass by construction.
                raise ValueError(f"{step.id}: a write step needs a connector to execute against")
            return world, ExecutionStep(
                step_id=step.id, operation=step.operation or step.capability,
                output_ids=instance.oracle.fact_ids,
            )
        definition = definition_for(step.connector)
        records = _records(world, step.connector)
        emulator = ConnectorEmulator(definition, records).fork()
        entity = _step_entity(definition, step, "search" if operation in _READ else operation)
        if operation in _READ or step.effect in {"read", "verify"}:
            tool = definition.tool_for(entity, "search")
            predicates = _search_predicates(world, step.connector) or [Predicate(entity=entity)]
            hits: list[str] = []
            for predicate in predicates:
                page = emulator.call(tool, _node=step.id, entity=predicate.entity or entity,
                                     predicate=predicate, max_results=50)
                hits.extend(str(item.get("id") or item.get("key")) for item in page["items"])
                hits.extend(emulator.trace[-1].reads)
            if not hits:
                raise ValueError(f"{step.id}: search on {step.connector}/{entity} found nothing")
            backing = {fact for span in emulator.trace for fid in span.reads
                       for fact in emulator.records[fid].get("fact_ids", ())}
            outputs = tuple(sorted(set(hits) | backing | set(instance.oracle.fact_ids)))
            return world, ExecutionStep(step_id=step.id, operation=step.operation or step.capability,
                                        output_ids=outputs)
        # A write: land it on the precondition the constructive layer minted, or
        # on the first record of the entity when the eval brought its own.
        try:
            tool = definition.tool_for(entity, operation)
        except KeyError as error:
            raise ValueError(str(error)) from error
        targets = [fid for fid in emulator.by_entity.get(entity, ())
                   if emulator.records[fid].get("precondition_for")] or list(emulator.by_entity.get(entity, ()))
        if operation in {"create", "send", "post", "upload"}:
            result = emulator.call(tool, _node=step.id, entity=entity, name=f"{instance.spec_id} {step.id}",
                                   fields={"eval_instance_id": instance.id})
        elif not targets:
            raise ValueError(f"{step.id}: no {step.connector}/{entity} record to {operation}")
        elif operation in {"comment", "reply"}:
            result = emulator.call(tool, _node=step.id, id=targets[0], body=f"{instance.id} {step.id}")
        elif operation == "transition":
            workflow = definition.entities[entity].workflow
            if workflow is None:
                raise ValueError(f"{step.id}: {step.connector}/{entity} has no workflow to transition")
            current = str(emulator.records[targets[0]].get(workflow.field) or workflow.states[0])
            legal = workflow.transitions.get(workflow.canonical_state(current), ())
            state = legal[0] if legal else next((s for s in workflow.states if s != current), current)
            result = emulator.call(tool, _node=step.id, id=targets[0], state=state)
        else:
            result = emulator.call(tool, _node=step.id, id=targets[0], fields={"eval_instance_id": instance.id})
        span = emulator.trace[-1]
        del result
        return world, ExecutionStep(step_id=step.id, operation=step.operation or step.capability,
                                    input_ids=tuple(targets[:1]), effect_ids=tuple(span.writes))

    return execute


__all__ = ["emulator_executor"]
