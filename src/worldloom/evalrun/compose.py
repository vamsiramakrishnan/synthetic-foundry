"""Anvil's composite flows on the plan axis, in both directions.

Anvil composes several connectors into one SDK whose ``Flow`` is a DAG of
operation calls (Anvil ADR-0031): ``anvil.compose-flow/v1`` is the flow as
written, ``anvil.compose-plan/v1`` is what ``flow.plan()`` returns. Both name
Anvil operation ids (``jira.jql.search``); a Worldloom plan names connector
tools (``jira.search_issues``). The shipped Anvil mappings
(``_data/connectors/anvil/<connector>.json``) are the dictionary between the
two, so this module needs nothing else:

* ``planned_from_compose`` reads a flow or a plan into a ``PlannedDag``, so a
  planner (``--exec``, a scripted plans file) may answer with a composite
  flow and be graded by ``grade_planned`` exactly as a native plan is. An
  operation no mapping knows stays ``<connector>.<operation>`` and is graded
  as the unmatched node it is, never dropped.
* ``flow_from_case`` writes a case's expected DAG as a composite flow: each
  tool node becomes a step on the operation its mapping serves that tool
  with, the payload becomes its arguments by wire name, and the DAG's edges
  (transforms compressed out) become ``after``. The flow states the gold
  plan in Anvil's terms; it is a reference, not a script: values a step
  would read from an earlier step's result are not in the gold DAG, so a
  required input the payload does not give is reported with the step.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..connectors.anvil import AnvilMapping, MappingError, OperationMap, load_mapping
from .contract import EvalCase
from .grading import _tool_edges
from .plans import PlannedDag, PlannedNode

FLOW_SCHEMA = "anvil.compose-flow/v1"
PLAN_SCHEMA = "anvil.compose-plan/v1"
FLOWS_SCHEMA = "worldloom.compose-flows/v1"
SCHEMAS = frozenset({FLOW_SCHEMA, PLAN_SCHEMA})

MappingSource = Callable[[str], AnvilMapping | None]


def is_compose_document(document: Mapping[str, Any]) -> bool:
    """Whether *document* (or its ``plan``) is an Anvil composite flow or plan."""

    body = document.get("plan", document)
    return isinstance(body, Mapping) and body.get("schema") in SCHEMAS


def shipped_mapping(connector: str) -> AnvilMapping | None:
    try:
        return load_mapping(connector)
    except MappingError:
        return None


def _cached(source: MappingSource) -> MappingSource:
    seen: dict[str, AnvilMapping | None] = {}

    def lookup(connector: str) -> AnvilMapping | None:
        if connector not in seen:
            seen[connector] = source(connector)
        return seen[connector]

    return lookup


def _refs(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        if "$ref" in value:
            return [str(value["$ref"])]
        return [ref for child in value.values() for ref in _refs(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in _refs(child)]
    return []


def _connector_and_operation(raw: Mapping[str, Any]) -> tuple[str, str]:
    operation = str(raw.get("operation") or "")
    connector = raw.get("connector")
    if not connector and ":" in operation:
        connector, operation = operation.split(":", 1)
    if not connector:
        connector = operation.split(".", 1)[0]
    if not operation or not connector:
        raise ValueError(f"composite step {raw.get('id')!r} names no operation")
    return str(connector), operation


def _wire(location: str | None) -> str:
    return location.split(".")[-1] if location else ""


def _tool_for(entry: OperationMap, args: Mapping[str, Any]) -> str | None:
    if entry.tool is None:
        return None
    if entry.tool_by is None:
        return entry.tool
    value = args.get(_wire(entry.tool_by[0]))
    if value is None or isinstance(value, Mapping):
        return entry.tool
    choices = entry.tool_by[1]
    return choices.get(str(value), choices.get("*", entry.tool))


def planned_from_compose(document: Mapping[str, Any], *, mappings: MappingSource | None = None) -> PlannedDag:
    """A composite flow or plan as a ``PlannedDag`` of ``connector.tool`` nodes."""

    body = document.get("plan", document)
    if not isinstance(body, Mapping) or body.get("schema") not in SCHEMAS:
        raise ValueError(f"expected an {FLOW_SCHEMA} or {PLAN_SCHEMA} document")
    lookup = _cached(mappings or shipped_mapping)
    raw_nodes = body.get("nodes") if body["schema"] == PLAN_SCHEMA else body.get("steps")
    if not isinstance(raw_nodes, list):
        raise ValueError("a composite plan lists `nodes`; a composite flow lists `steps`")
    nodes: list[PlannedNode] = []
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, Mapping):
            raise ValueError(f"composite step {index} is not an object")
        connector, operation = _connector_and_operation(raw)
        if "depends_on" in raw:
            depends = [str(dep) for dep in raw.get("depends_on") or ()]
        else:
            depends = []
            for dep in [*_refs(raw.get("args")), *_refs(raw.get("for_each")), *_refs(raw.get("when")),
                        *(str(a) for a in raw.get("after") or ())]:
                if dep not in depends:
                    depends.append(dep)
        mapping = lookup(connector)
        entry = mapping.entry(operation) if mapping is not None else None
        raw_args = raw.get("args")
        args: Mapping[str, Any] = raw_args if isinstance(raw_args, Mapping) else {}
        tool = _tool_for(entry, args) if entry is not None else None
        nodes.append(PlannedNode(
            id=str(raw.get("id") or f"n{index}"),
            tool=f"{mapping.connector if mapping else connector}.{tool or operation}",
            depends_on=tuple(depends),
        ))
    return PlannedDag(nodes=tuple(nodes))


def _operation_for(mapping: AnvilMapping, tool: str) -> OperationMap | None:
    """The operation that serves *tool*: one that serves only it first, then one that can choose it."""

    plain = [entry for entry in mapping.operations.values() if entry.tool == tool and entry.tool_by is None]
    if plain:
        return plain[0]
    chosen = [entry for entry in mapping.operations.values() if tool in entry.tools]
    return chosen[0] if chosen else None


def _arguments(entry: OperationMap, tool: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in payload.items():
        spec = entry.args.get(name)
        wire = _wire(spec.source) if spec is not None and spec.source else name
        out[wire] = value
    if entry.tool_by is not None and entry.tool != tool:
        location, choices = entry.tool_by
        for value, chosen in choices.items():
            if chosen == tool and value != "*":
                out.setdefault(_wire(location), value)
                break
    return out


def flow_from_case(case: EvalCase, *, mappings: MappingSource | None = None) -> dict[str, Any]:
    """The case's expected DAG as an ``anvil.compose-flow/v1`` document.

    Adds ``unmapped`` (tool nodes no mapping serves) and per-step
    ``needs`` (required inputs the gold payload does not give), so a reader
    sees exactly how far the gold plan translates.
    """

    lookup = _cached(mappings or shipped_mapping)
    raw_nodes = {str(node.get("id")): node for node in (case.row.get("expected_dag") or {}).get("nodes") or ()
                 if isinstance(node, Mapping)}
    edges = _tool_edges(case)
    steps: list[dict[str, Any]] = []
    unmapped: list[dict[str, str]] = []
    for node in case.plan.tool_nodes:
        mapping = lookup(node.connector)
        entry = _operation_for(mapping, node.tool) if mapping is not None else None
        if mapping is None or entry is None:
            unmapped.append({"node": node.id, "tool": f"{node.connector}.{node.tool}",
                             "reason": "no Anvil mapping ships for this connector" if mapping is None
                             else "no mapped operation serves this tool"})
            continue
        payload = raw_nodes.get(node.id, {}).get("payload")
        args = _arguments(entry, node.tool, payload if isinstance(payload, Mapping) else {})
        step: dict[str, Any] = {"id": node.id, "operation": entry.operation_id, "connector": mapping.connector,
                                "args": args}
        after = [source for source, target in edges if target == node.id]
        if after:
            step["after"] = after
        needs = sorted(_wire(spec.source) for name, spec in entry.args.items()
                       if spec.required and spec.source and _wire(spec.source) not in args)
        if needs:
            step["needs"] = needs
        if node.kind == "write":
            step["confirm"] = True
        steps.append(step)
    kept = {step["id"] for step in steps}
    for step in steps:
        if "after" in step:
            step["after"] = [dep for dep in step["after"] if dep in kept]
            if not step["after"]:
                del step["after"]
    flow: dict[str, Any] = {"schema": FLOW_SCHEMA, "name": case.id, "steps": steps}
    if unmapped:
        flow["unmapped"] = unmapped
    return flow


def flows_document(cases: Iterable[EvalCase], *, mappings: MappingSource | None = None) -> dict[str, Any]:
    """Every case's gold flow, keyed by case id (``worldloom.compose-flows/v1``)."""

    lookup = _cached(mappings or shipped_mapping)
    return {"schema": FLOWS_SCHEMA, "flows": {case.id: flow_from_case(case, mappings=lookup) for case in cases}}
