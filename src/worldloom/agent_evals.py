"""Business-grounded, state-changing MCP evaluation cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from .connector_data import ConnectorVerb, ContentVerb
from .ids import content_key
from .models import Model

if TYPE_CHECKING:
    from .world import World


class WorkflowNode(Model):
    id: str
    kind: Literal["mcp", "transform", "verify"]
    intent: str
    depends_on: list[str] = Field(default_factory=list)
    connector: str | None = None
    entity: str | None = None
    operation: str | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    expected_fact_ids: list[str] = Field(default_factory=list)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentEvaluationCase(Model):
    id: str
    workflow: str
    persona: str
    request: str
    topology: Literal["fan_in", "fan_out", "diamond", "map_reduce"]
    nodes: list[WorkflowNode]
    expected_fact_ids: list[str]
    source_artifact_ids: list[str]
    assertions: list[str]

    @model_validator(mode="after")
    def _closed_dag(self) -> AgentEvaluationCase:
        seen: set[str] = set()
        for node in self.nodes:
            missing = set(node.depends_on) - seen
            if missing:
                raise ValueError(
                    f"{self.id}: {node.id} depends on missing or later nodes {sorted(missing)}"
                )
            if node.id in seen:
                raise ValueError(f"{self.id}: duplicate node {node.id}")
            seen.add(node.id)
        if not self.expected_fact_ids:
            raise ValueError(f"{self.id}: no fact-grounded acceptance key")
        if not any(node.kind == "verify" for node in self.nodes):
            raise ValueError(f"{self.id}: mutation has no read-after-write verification")
        return self


class WorkflowSeed(Model):
    workflows: tuple[str, ...] = (
        "incident_review",
        "risk_register",
        "steering_pack",
        "customer_health",
        "change_assurance",
        "executive_digest",
    )
    destinations: tuple[str, ...] = ("sharepoint", "drive", "confluence", "email")
    max_cases: int = Field(default=100, ge=1)


_ENTITY = {
    "jira": "issue",
    "confluence": "page",
    "sharepoint": "file",
    "drive": "file",
    "servicenow": "incident",
    "salesforce": "case",
    "email": "message",
}

_SOURCE_TEXT = {
    "jira": "unresolved Jira issues",
    "confluence": "the latest approved Confluence pages",
    "sharepoint": "the current SharePoint records",
    "drive": "the latest working files in Drive",
    "servicenow": "linked ServiceNow incidents and changes",
    "salesforce": "escalated Salesforce cases and open opportunities",
    "email": "the programme email thread and its attachments",
}

_WORKFLOWS: dict[str, dict[str, Any]] = {
    "incident_review": {
        "persona": "service delivery lead",
        "sources": ("servicenow", "jira", "confluence"),
        "topology": "fan_in",
        "artifact": "incident review",
        "requirements": "confirmed cause, customer impact, linked defects, control gaps, owners, due dates, and source links",
    },
    "risk_register": {
        "persona": "programme director",
        "sources": ("sharepoint", "jira", "servicenow", "confluence"),
        "topology": "fan_in",
        "artifact": "risk register",
        "requirements": "matched, added, skipped, and ambiguous records while preserving manual mitigations and formulas",
    },
    "steering_pack": {
        "persona": "programme director",
        "sources": ("jira", "confluence", "sharepoint", "drive"),
        "topology": "diamond",
        "artifact": "steering committee deck",
        "requirements": "delivery risk, overdue actions, decisions required, a trend chart, and source links",
    },
    "customer_health": {
        "persona": "account director",
        "sources": ("salesforce", "servicenow", "jira", "drive"),
        "topology": "map_reduce",
        "artifact": "customer health review",
        "requirements": "recurring failures, unresolved commitments, revenue at risk, owners, next actions, and uncertain matches",
    },
    "change_assurance": {
        "persona": "change manager",
        "sources": ("servicenow", "jira", "confluence"),
        "topology": "fan_out",
        "artifact": "change assurance report",
        "requirements": "failed changes, linked defects, runbook gaps, remediation owners, due dates, and exceptions",
    },
    "executive_digest": {
        "persona": "programme director",
        "sources": ("email", "jira", "servicenow"),
        "topology": "fan_in",
        "artifact": "executive delivery digest",
        "requirements": "decisions, commitments, owners, deadlines, unresolved incidents, and links to the originating message or record",
    },
}


def _evidence(world: World) -> tuple[list[str], list[str]]:
    records = tuple(world.artifacts) or tuple(world.artifact_intents)
    selected = sorted(records, key=lambda item: item.id)[:12]
    artifact_ids = [item.id for item in selected]
    fact_ids: list[str] = []
    for item in selected:
        fact_ids.extend(
            getattr(item, "supporting_fact_ids", None)
            or getattr(item, "required_fact_ids", ())
            or ()
        )
    reachable = set(world.facts.ids())
    return artifact_ids, sorted(set(fact_ids) & reachable)[:64]


def _request(
    world: World, spec: dict[str, Any], destination: str, update: bool
) -> str:
    sources = [_SOURCE_TEXT[name] for name in spec["sources"]]
    source_clause = ", ".join(sources[:-1]) + f", and {sources[-1]}"
    if destination == "email":
        verb = "Reply with an updated" if update else "Draft an"
    else:
        verb = "Update the existing" if update else "Create a"
    period = world.period or "current"
    return (
        f"Prepare the {period} {spec['artifact']} for {world.company.name}. "
        f"Use {source_clause}. Reconcile records using the company, reporting "
        f"period, and stable linked-record identifiers. {verb} {spec['artifact']} "
        f"in {destination.title()}. Include {spec['requirements']}. Do not "
        f"overwrite manually entered content. Put uncertain matches in a review "
        f"section. Read the saved result back and report any branch that failed."
    )


def compile_agent_evals(
    world: World, seed: WorkflowSeed | None = None
) -> tuple[AgentEvaluationCase, ...]:
    """Compile business requests while keeping formats and MCP calls hidden."""
    seed = seed or WorkflowSeed()
    artifact_ids, fact_ids = _evidence(world)
    if not fact_ids:
        raise ValueError("agent evaluations require facts reachable from an artifact")
    cases: list[AgentEvaluationCase] = []
    for workflow in seed.workflows:
        try:
            spec = _WORKFLOWS[workflow]
        except KeyError:
            raise ValueError(f"unknown agent workflow {workflow!r}") from None
        for destination in seed.destinations:
            if destination not in _ENTITY:
                raise ValueError(f"unknown destination connector {destination!r}")
            for update in (False, True):
                nodes = [
                    WorkflowNode(
                        id=f"read-{index}",
                        kind="mcp",
                        intent=f"{connector}.{_ENTITY[connector]}.search",
                        connector=connector,
                        entity=_ENTITY[connector],
                        operation="search",
                        source_artifact_ids=artifact_ids,
                        expected_fact_ids=fact_ids,
                        arguments={"synthetic_namespace_only": True},
                    )
                    for index, connector in enumerate(spec["sources"], start=1)
                ]
                read_ids = [node.id for node in nodes]
                if "email" in spec["sources"]:
                    nodes.append(
                        WorkflowNode(
                            id="extract-email",
                            kind="transform",
                            intent=f"content.{ContentVerb.EXTRACT.value}",
                            depends_on=[
                                node.id for node in nodes if node.connector == "email"
                            ],
                            arguments={
                                "fields": [
                                    "decision",
                                    "commitment",
                                    "owner",
                                    "deadline",
                                    "record_reference",
                                ]
                            },
                        )
                    )
                    read_ids.append("extract-email")
                nodes.append(
                    WorkflowNode(
                        id="synthesise",
                        kind="transform",
                        intent=(
                            f"content.{ContentVerb.SUMMARIZE.value}"
                            if workflow == "executive_digest"
                            else f"workflow.{workflow}.{ContentVerb.RECONCILE.value}"
                        ),
                        depends_on=read_ids,
                        expected_fact_ids=fact_ids,
                        arguments={
                            "preserve_provenance": True,
                            "reject_ambiguous_joins": True,
                        },
                    )
                )
                nodes.append(
                    WorkflowNode(
                        id="generate",
                        kind="transform",
                        intent=f"content.{ContentVerb.GENERATE.value}",
                        depends_on=["synthesise"],
                        expected_fact_ids=fact_ids,
                        arguments={
                            "artifact": spec["artifact"],
                            "preserve_provenance": True,
                        },
                    )
                )
                operation = (
                    ConnectorVerb.REPLY.value
                    if destination == "email" and update
                    else ConnectorVerb.DRAFT.value
                    if destination == "email"
                    else ConnectorVerb.UPDATE.value
                    if update
                    else ConnectorVerb.CREATE.value
                )
                nodes.append(
                    WorkflowNode(
                        id="write-1",
                        kind="mcp",
                        intent=f"{destination}.{_ENTITY[destination]}.{operation}",
                        depends_on=["generate"],
                        connector=destination,
                        entity=_ENTITY[destination],
                        operation=operation,
                        expected_fact_ids=fact_ids,
                        arguments={
                            "idempotency_key": "${case.id}",
                            "synthetic_namespace_only": True,
                        },
                    )
                )
                nodes.append(
                    WorkflowNode(
                        id="verify-1",
                        kind="verify",
                        intent=f"{destination}.{_ENTITY[destination]}.read",
                        depends_on=["write-1"],
                        connector=destination,
                        entity=_ENTITY[destination],
                        operation="read",
                        expected_fact_ids=fact_ids,
                    )
                )
                key = content_key(
                    world.seed,
                    world.company.id,
                    world.period,
                    workflow,
                    destination,
                    update,
                )
                cases.append(
                    AgentEvaluationCase(
                        id=f"AEVAL-{key[:16].upper()}",
                        workflow=workflow,
                        persona=spec["persona"],
                        request=_request(world, spec, destination, update),
                        topology=spec["topology"],
                        nodes=nodes,
                        expected_fact_ids=fact_ids,
                        source_artifact_ids=artifact_ids,
                        assertions=[
                            "dag_is_acyclic",
                            "dependencies_respected",
                            "facts_preserved",
                            "provenance_preserved",
                            "side_effect_occurred",
                            "read_after_write",
                            "idempotent_retry",
                            "no_unrequested_connector",
                        ],
                    )
                )
                if len(cases) >= seed.max_cases:
                    return tuple(cases)
    return tuple(cases)


def export_agent_evals(
    world: World, destination: str | Path, seed: WorkflowSeed | None = None
) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for case in compile_agent_evals(world, seed):
            handle.write(
                json.dumps(case.model_dump(mode="json"), sort_keys=True) + "\n"
            )
    return target
