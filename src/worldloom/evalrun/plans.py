"""Plan-only grading: the querying axis measured without executing anything.

``grade_plan`` grades the DAG an agent *executed*: the service attributes
each call to an expected node, and the plan axis reads recall, precision and
edge order off that attribution. That measures querying and execution
together. An agent that plans the right DAG and then fails to page a search,
or one that fumbles an id and never reaches its verify, scores the same
missing node either way, and a planner that emits a DAG without acting on it
has no wire to a grade at all.

This module is that wire. The planner under test receives what an agent
receives (the request, the persona, the tool catalog with its safety
annotations) and returns only a DAG: nodes naming tools, edges naming what
each call depends on. Nothing is executed, no state is touched, and the
grade is the same ``PlanGrade`` the executed axis produces, computed the
same way, so a plan-only run and an executed run of the same case set
compare on the plan axis and nowhere else. The trajectory and outcome axes
of a plan-only run are reported as unobserved, never as zeros that mean
something.

Matching is by tool name, greedy in the expected order, because a planner
cannot know the case's node ids and should not have to: ``jira.search_issues``
then ``sharepoint.create_file`` then ``sharepoint.get_file`` is a plan
whatever the nodes are called. Edges are graded as reachability through the
planned ``depends_on`` (with the expected DAG's transforms compressed out, as
``grade_plan`` does), so a planner that routes a write through an
intermediate node of its own still honours ``search -> write``. A designed
failure is a runtime discovery and does not shrink the expected plan; a
conditional shape's two branches are both expected, since which one runs is
a fact about results the planner has not seen.

Three planners ship on the pattern of the agents: ``ReferencePlanner``
returns each case's expected DAG and is the ceiling, ``ExecPlanner`` runs a
command once per case over the ``--exec`` seam with a
``worldloom.evalrun-plan/v1`` document on stdin, and ``ScriptedPlanner``
replays a ``worldloom.evalrun-plans/v1`` file written against
``evalrun requests --for plan``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import model_validator

from .. import packkit
from ..connectors.serving import ConnectorEvaluationService
from ..execseam import DEFAULT_TIMEOUT, ExecError, run_exec
from ..models import Model
from .contract import EvalCase
from .grading import (
    CaseScore,
    PlanGrade,
    _mean,
    _round,
    _tool_edges,
    unobserved_outcomes,
    unobserved_trajectory,
)
from .runner import CaseResult, RunReport, case_set_digest, safety_for
from .safety import OperationSafety

if TYPE_CHECKING:
    from ..packkit import ResolvedPack

PLAN_SCHEMA = "worldloom.evalrun-plan/v1"
PLANS_SCHEMA = "worldloom.evalrun-plans/v1"

def plan_instructions() -> list[str]:
    """What a planner is told, from the prompts in force (``evalrun.plan.rule.*``)."""
    return packkit.texts("evalrun.plan.rule.")


class PlannedNode(Model):
    id: str
    tool: str
    depends_on: tuple[str, ...] = ()
    entity: str = ""


class PlannedDag(Model):
    """What a planner returned: tools and the dependencies between them."""

    nodes: tuple[PlannedNode, ...]

    @model_validator(mode="after")
    def _well_formed(self) -> PlannedDag:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("planned node ids must be unique")
        known = set(ids)
        for node in self.nodes:
            for parent in node.depends_on:
                if parent not in known:
                    raise ValueError(f"planned node {node.id!r} depends on unknown node {parent!r}")
                if parent == node.id:
                    raise ValueError(f"planned node {node.id!r} depends on itself")
        for node in self.nodes:
            if node.id in self.ancestors(node.id):
                raise ValueError(f"planned node {node.id!r} is on a cycle")
        return self

    def ancestors(self, node_id: str) -> frozenset[str]:
        """Every node whose result ``node_id`` transitively depends on."""

        parents = {node.id: node.depends_on for node in self.nodes}
        seen: set[str] = set()
        frontier = list(parents.get(node_id, ()))
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(parents.get(current, ()))
        return frozenset(seen)


def parse_plan(document: Mapping[str, Any]) -> PlannedDag:
    """Read ``{"plan": {"nodes": [...]}}`` (or the bare ``{"nodes": [...]}``) into a ``PlannedDag``.

    A node without an ``id`` is numbered by position; ``depends_on`` may be a
    single id or a list. Anything else is a contract breach, reported as the
    planner's error rather than repaired.
    """

    body = document.get("plan", document)
    if not isinstance(body, Mapping) or not isinstance(body.get("nodes"), list):
        raise ValueError("plan must be {\"plan\": {\"nodes\": [...]}}")
    nodes: list[PlannedNode] = []
    for index, raw in enumerate(body["nodes"]):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("tool"), str) or not raw["tool"]:
            raise ValueError(f"planned node {index} needs a `tool`")
        depends = raw.get("depends_on") or ()
        if isinstance(depends, str):
            depends = (depends,)
        if not isinstance(depends, (list, tuple)) or not all(isinstance(value, str) for value in depends):
            raise ValueError(f"planned node {index} `depends_on` must be a list of ids")
        nodes.append(PlannedNode(id=str(raw.get("id") or f"n{index}"), tool=raw["tool"],
                                 depends_on=tuple(depends), entity=str(raw.get("entity") or "")))
    return PlannedDag(nodes=tuple(nodes))


def reference_plan(case: EvalCase) -> PlannedDag:
    """The case's expected DAG as a planner would state it: tool nodes, transforms compressed out."""

    edges = _tool_edges(case)
    return PlannedDag(nodes=tuple(
        PlannedNode(id=node.id, tool=f"{node.connector}.{node.tool}", entity=node.entity,
                    depends_on=tuple(source for source, target in edges if target == node.id))
        for node in case.plan.tool_nodes
    ))


def grade_planned(case: EvalCase, plan: PlannedDag, *, safety: Mapping[str, OperationSafety] | None = None) -> PlanGrade:
    """Grade a stated DAG against the expected one, by tool name and reachability.

    The formula is ``grade_plan``'s: the mean of node recall, node precision,
    edge recall, and whether any write outside the plan was proposed. The
    expected set is every tool node of the case, blocked and conditional
    ones included, because a plan is what should exist given the request
    and not what a particular run's failures let happen.
    """

    if safety is None:
        from ..connector_definition import builtin_connector_definitions

        safety = safety_for(builtin_connector_definitions())
    expected = case.plan.tool_nodes
    unmatched = list(plan.nodes)
    matched: dict[str, str] = {}
    for node in expected:
        wanted = f"{node.connector}.{node.tool}"
        for index, planned in enumerate(unmatched):
            if planned.tool == wanted:
                matched[node.id] = planned.id
                del unmatched[index]
                break
    observed = tuple(node.id for node in expected if node.id in matched)
    missing = tuple(node.id for node in expected if node.id not in matched)
    node_recall = _round(len(observed) / len(expected)) if expected else 1.0
    node_precision = _round(len(matched) / len(plan.nodes)) if plan.nodes else (1.0 if not expected else 0.0)
    edges = [(a, b) for a, b in _tool_edges(case) if a in matched and b in matched]
    honoured = sum(1 for a, b in edges if matched[a] in plan.ancestors(matched[b]))
    edge_recall = _round(honoured / len(edges)) if edges else 1.0
    verifies = tuple(node for node in case.plan.of_kind("verify") if node in missing)
    extra_writes = sum(1 for planned in unmatched
                       if (posture := safety.get(planned.tool)) is not None and posture.effect.value == "mutation")
    score = _mean([node_recall, node_precision, edge_recall, 0.0 if extra_writes else 1.0])
    return PlanGrade(
        expected_nodes=tuple(node.id for node in expected), observed_nodes=observed, missing_nodes=missing,
        unattributed_calls=len(unmatched), node_recall=node_recall, node_precision=node_precision,
        edge_recall=edge_recall, missing_verify=verifies, extra_writes=extra_writes, planned_agreement=None,
        score=score, passed=not missing and not extra_writes and edge_recall == 1.0,
    )


# -- planners -----------------------------------------------------------------


class Planner(Protocol):
    """Anything that turns a plan request into a ``PlannedDag``. Raising is an error row."""

    name: str

    def plan(self, request: Mapping[str, Any]) -> PlannedDag: ...


class ReferencePlanner:
    """Each case's expected DAG, restated. The ceiling of the plan axis."""

    name = "plan:reference"

    def __init__(self, cases: Iterable[EvalCase]) -> None:
        self._cases = {case.id: case for case in cases}

    def plan(self, request: Mapping[str, Any]) -> PlannedDag:
        case = self._cases.get(str(request.get("case_id")))
        if case is None:
            raise ValueError(f"reference planner holds no case {request.get('case_id')!r}")
        return reference_plan(case)


class ExecPlanner:
    """A command run once per case over the ``--exec`` seam; it prints the plan.

    With *policy* (an ``agent`` pack), ``plan_cases`` builds each request
    under it: the ``agent`` block, the plan rules overlaid by ``plan_rules``,
    and the tool advice. The name carries the policy, and ``pack_record`` is
    what the run records as ``agent_pack``.
    """

    def __init__(self, command: str, *, timeout: float = DEFAULT_TIMEOUT, shell: bool = False, name: str | None = None,
                 policy: ResolvedPack | None = None) -> None:
        from .policy import agent_name, pack_record, require

        if policy is not None:
            policy = require(policy)
        self.command = command
        self.timeout = timeout
        self.shell = shell
        self.policy = policy
        self.pack_record = pack_record(policy) if policy is not None else None
        self.name = name or agent_name(f"plan:exec:{command.split()[0] if command.split() else command}", policy)

    def plan(self, request: Mapping[str, Any]) -> PlannedDag:
        try:
            reply = run_exec(self.command, dict(request), timeout=self.timeout, shell=self.shell)
        except ExecError as error:
            tail = getattr(error, "stderr_tail", "")
            raise RuntimeError(f"{error.code}: {error}" + (f"\n{tail}" if tail else "")) from error
        try:
            return parse_plan(reply.document)
        except ValueError as error:
            raise RuntimeError(f"exec_unparseable: {error}") from error


class ScriptedPlanner:
    """Replay a plans document: one stated DAG per case id."""

    def __init__(self, plans: Mapping[str, PlannedDag], *, name: str = "plan:scripted") -> None:
        self.name = name
        self._plans = dict(plans)

    def plan(self, request: Mapping[str, Any]) -> PlannedDag:
        plan = self._plans.get(str(request.get("case_id")))
        if plan is None:
            raise RuntimeError("not_attempted: the plans document holds no entry for this case")
        return plan


def load_plans(path: Path) -> dict[str, PlannedDag]:
    """Read a plans document (or the bare ``{case_id: {nodes}}`` form)."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    body = raw.get("cases") if raw.get("schema") == PLANS_SCHEMA else raw
    if not isinstance(body, dict) or not all(isinstance(value, dict) for value in body.values()):
        raise ValueError(f"{path}: expected {{case_id: {{nodes: [...]}}}}")
    plans: dict[str, PlannedDag] = {}
    for case_id, entry in body.items():
        try:
            plans[str(case_id)] = parse_plan(entry)
        except ValueError as error:
            raise ValueError(f"{path}: case {case_id!r}: {error}") from error
    return plans


# -- the run --------------------------------------------------------------------


def plan_request(case: EvalCase, catalog: Iterable[Mapping[str, Any]], *, principal: str = "agent",
                 policy: ResolvedPack | None = None) -> dict[str, Any]:
    """What the planner may know: the request and the tools, nothing about the expected DAG.

    Under *policy* (an ``agent`` pack) the request gains the ``agent`` block,
    its ``instructions`` are the plan rules overlaid by ``plan_rules`` (the
    rule stating the plan shape is locked) and advised tools gain
    ``description`` and ``hints``; without one it is unchanged.
    """

    tools = [dict(tool) for tool in catalog]
    if policy is None:
        return {"schema": PLAN_SCHEMA, "case_id": case.id, "query": case.query, "persona": case.persona,
                "principal": principal, "tools": tools, "instructions": plan_instructions()}
    from .policy import advise, agent_block, plan_rules, require

    policy = require(policy)
    return {"schema": PLAN_SCHEMA, "case_id": case.id, "query": case.query, "persona": case.persona,
            "principal": principal, "tools": advise(tools, policy.body), "instructions": plan_rules(policy.body),
            "agent": agent_block(policy)}


def _catalogs(service: ConnectorEvaluationService, cases: Iterable[EvalCase], principal: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        begun = service.begin(principal, case.id)
        try:
            out[case.id] = [dict(tool) for tool in service.tool_catalog(principal, str(begun["run_id"]))]
        finally:
            service.end(principal, str(begun["run_id"]))
    return out


def plan_requests_document(service: ConnectorEvaluationService, cases: Iterable[EvalCase], *, principal: str = "agent") -> dict[str, Any]:
    """Every case as a plan request a harness can answer offline."""

    from .harness import REQUESTS_SCHEMA

    listed = list(cases)
    catalogs = _catalogs(service, listed, principal)
    entries = [{"case_id": case.id, "query": case.query, "persona": case.persona, "principal": principal,
                "tools": catalogs[case.id]} for case in listed]
    return {"schema": REQUESTS_SCHEMA, "for": "plan", "instructions": plan_instructions(), "cases": entries,
            "response_schema": {
                "schema": PLANS_SCHEMA,
                "cases": {"<case_id>": {"nodes": [{"id": "<id>", "tool": "<connector.tool>", "depends_on": ["<id>"], "entity": "<entity>"}]}},
            }}


def plan_cases(service: ConnectorEvaluationService, cases: Iterable[EvalCase], planner: Planner, *,
               principal: str = "agent") -> RunReport:
    """Ask the planner for every case's DAG and grade the plan axis. Nothing runs.

    The catalog each planner sees comes from a begun-and-ended run, exactly
    what an executing agent would be handed. A planner that raises, exits
    non-zero or returns something that is not a plan is an error row.
    """

    listed = list(cases)
    safety = safety_for(service.definitions)
    catalogs = _catalogs(service, listed, principal)
    results: list[CaseResult] = []
    for case in listed:
        request = plan_request(case, catalogs[case.id], principal=principal, policy=getattr(planner, "policy", None))
        try:
            planned = planner.plan(request)
        except Exception as error:  # the planner is untrusted; its failure is a row, not ours
            results.append(CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions, shape=case.plan.shape,
                                      agent=planner.name, status="error", error=f"{type(error).__name__}: {error}"))
            continue
        grade = grade_planned(case, planned, safety=safety)
        score = CaseScore(plan=grade, trajectory=unobserved_trajectory(), outcomes=unobserved_outcomes(),
                          assertion_status="unobserved", assertion_fails=(), observed=("plan",),
                          score=grade.score, passed=grade.passed)
        results.append(CaseResult(
            case_id=case.id, query=case.query, dimensions=case.dimensions, shape=case.plan.shape, agent=planner.name,
            status="graded", score=score, notes=("plan only: nothing was executed; trajectory and outcomes are unobserved",),
        ))
    return RunReport(agent=planner.name, principal=principal, case_set=case_set_digest(listed), results=tuple(results),
                     agent_pack=getattr(planner, "pack_record", None))


__all__ = [
    "PLAN_SCHEMA",
    "PLANS_SCHEMA",
    "ExecPlanner",
    "PlannedDag",
    "PlannedNode",
    "Planner",
    "ReferencePlanner",
    "ScriptedPlanner",
    "grade_planned",
    "load_plans",
    "parse_plan",
    "plan_cases",
    "plan_instructions",
    "plan_request",
    "plan_requests_document",
    "reference_plan",
]
