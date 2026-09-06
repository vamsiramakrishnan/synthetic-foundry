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

#: How a step's declared operation maps onto the vocabulary a definition's
#: entities use for their ops. Steps say what an agent does (``get``,
#: ``download``); entities say what a record supports (``read``,
#: ``extract``). Mapping here keeps the dispatch honest: a ``get`` step runs
#: the connector's get tool, never a search dressed up as one.
_SEARCH = frozenset({"search", "find", "list", "query"})
_READ = frozenset({"get", "read", "download", "extract"})


def _entity_op(operation: str) -> str:
    if operation in _SEARCH:
        return "search"
    if operation in {"get", "read", "download"}:
        return "read"
    return operation


def _records(world: World, connector: str) -> list[Any]:
    from .eval_candidates import _connector_records

    return _connector_records(world, connector)


def _witness_predicates(world: World, connector: str, entity: str | None) -> list[Predicate]:
    """The queries the constructive layer answered for *connector*, one per witness selector.

    Narrowed to the step's entity when the step names one: a design that
    constructs both an incident and a knowledge article on ServiceNow must not
    send the article's predicate to the incident search tool, which the
    emulator rightly refuses.
    """

    from .eval_witnesses import witness_payload

    seen: dict[str, Predicate] = {}
    for event in world.events:
        payload = witness_payload(event)
        if payload is None or payload["connector"] != connector or payload["role"] != "witness":
            continue
        if entity is not None and payload["entity"] != entity:
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
    """Build the executor. Definitions default to the built-in twelve.

    Connector state lives for one eval instance: the emulator for each
    connector is built on the instance's first step against it and reused by
    every later step, so a record a write step created is what a later read
    finds. A new instance id discards that state, which is the isolation
    ``execute_reference`` promises between instances.
    """

    loaded = dict(definitions or {})
    state: dict[str, ConnectorEmulator] = {}
    current_instance: list[str] = []

    def definition_for(connector: str) -> ConnectorDefinition:
        if connector not in loaded:
            if connector not in REFERENCE_CONNECTORS:
                raise ValueError(f"no connector definition for {connector!r}")
            loaded[connector] = load_connector_definition(connector)
        return loaded[connector]

    def emulator_for(world: World, connector: str, instance: EvalInstance) -> ConnectorEmulator:
        if current_instance != [instance.id]:
            state.clear()
            current_instance[:] = [instance.id]
        if connector not in state:
            state[connector] = ConnectorEmulator(definition_for(connector), _records(world, connector)).fork()
        return state[connector]

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
        emulator = emulator_for(world, step.connector, instance)
        entity_op = _entity_op(operation)
        entity = _step_entity(definition, step, "search" if entity_op in {"search", "read"} else entity_op)
        predicates = _witness_predicates(world, step.connector, step.entity and entity)

        def facts_behind(fids: list[str]) -> set[str]:
            return {fact for fid in fids for fact in emulator.records[fid].get("fact_ids", ())}

        if entity_op == "search" or (operation not in _READ and step.effect in {"read", "verify"}):
            hits: list[str] = []
            for predicate in predicates or [Predicate(entity=entity)]:
                target_entity = predicate.entity or entity
                tool = definition.tool_for(target_entity, "search")
                page = emulator.call(tool, _node=step.id, entity=target_entity, predicate=predicate, max_results=50)
                hits.extend(str(item.get("id") or item.get("key")) for item in page["items"])
                hits.extend(emulator.trace[-1].reads)
            if not hits:
                raise ValueError(f"{step.id}: search on {step.connector}/{entity} found nothing")
            reads = [fid for fid in hits if fid in emulator.records]
            outputs = tuple(sorted(set(hits) | facts_behind(reads) | set(instance.oracle.fact_ids)))
            return world, ExecutionStep(step_id=step.id, operation=step.operation or step.capability,
                                        output_ids=outputs)
        if entity_op in {"read", "extract"}:
            # A concrete read runs the connector's own read tool against one
            # record the design's witnesses identify, as an agent would after
            # a search; the proof exercises the payload path, not a stand-in.
            pool = list(emulator.by_entity.get(entity, ()))
            from .predicates import evaluate

            matching = [
                fid for fid in pool
                if not predicates or any(
                    evaluate(predicate, emulator._record_for_predicate(emulator.records[fid]), entity=entity)
                    for predicate in predicates if (predicate.entity or entity) == entity
                )
            ] or pool
            if not matching:
                raise ValueError(f"{step.id}: no {step.connector}/{entity} record to {operation}")
            try:
                tool = definition.tool_for(entity, entity_op)
            except KeyError as error:
                raise ValueError(str(error)) from error
            target = matching[0]
            emulator.call(tool, _node=step.id, id=target)
            outputs = tuple(sorted({target} | facts_behind([target]) | set(instance.oracle.fact_ids)))
            return world, ExecutionStep(step_id=step.id, operation=step.operation or step.capability,
                                        input_ids=(target,), output_ids=outputs)
        # A write: land it on the precondition the constructive layer minted, or
        # on the first record of the entity when the eval brought its own.
        try:
            tool = definition.tool_for(entity, operation)
        except KeyError as error:
            raise ValueError(str(error)) from error
        targets = [fid for fid in emulator.by_entity.get(entity, ())
                   if emulator.records[fid].get("precondition_for")] or list(emulator.by_entity.get(entity, ()))
        if operation in {"create", "send", "post", "upload"}:
            # The definition says which fields a create needs (Jira wants a
            # project). Take each from a record of the entity the world
            # already holds, or from the definition's own picklist, so the
            # proof creates what the product would accept, never a stub.
            required = definition.entities[entity].required_on_create
            sample = next((emulator.records[fid] for fid in emulator.by_entity.get(entity, ())), {})
            fields: dict[str, Any] = {"eval_instance_id": instance.id}
            for field in required:
                if field in {"name", "title", "entity"}:
                    continue
                value = sample.get(field)
                if value in (None, ""):
                    options = definition.options.get(field, ())
                    value = options[0] if options else instance.spec_id
                fields[field] = value
            emulator.call(tool, _node=step.id, entity=entity, name=f"{instance.spec_id} {step.id}",
                          fields=fields)
        elif not targets:
            raise ValueError(f"{step.id}: no {step.connector}/{entity} record to {operation}")
        elif operation in {"comment", "reply"}:
            emulator.call(tool, _node=step.id, id=targets[0], body=f"{instance.id} {step.id}")
        elif operation == "transition":
            workflow = definition.entities[entity].workflow
            if workflow is None:
                raise ValueError(f"{step.id}: {step.connector}/{entity} has no workflow to transition")
            current = str(emulator.records[targets[0]].get(workflow.field) or workflow.states[0])
            legal = workflow.transitions.get(workflow.canonical_state(current), ())
            state_name = legal[0] if legal else next((s for s in workflow.states if s != current), current)
            emulator.call(tool, _node=step.id, id=targets[0], state=state_name)
        else:
            emulator.call(tool, _node=step.id, id=targets[0], fields={"eval_instance_id": instance.id})
        span = emulator.trace[-1]
        return world, ExecutionStep(step_id=step.id, operation=step.operation or step.capability,
                                    input_ids=tuple(targets[:1]), effect_ids=tuple(span.writes))

    return execute


__all__ = ["emulator_executor"]
