"""Constraint-aware planning, fixture requirements, and query rendering."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from .enterprise_specs import (
    CoverageProfile,
    SpecRegistry,
    WorkflowSpec,
    builtin_registry,
)
from .ids import content_key
from .models import Model

if TYPE_CHECKING:
    from .world import World


class SourceRequirement(Model):
    connector: str
    entity: str
    minimum: int = Field(default=1, ge=1)
    required_fields: tuple[str, ...] = ()


class MutationRequirement(Model):
    connector: str
    entity: str
    operation: str
    output_format: str
    preexisting_record: bool
    verify_after_write: bool = True


class GenerationRequirement(Model):
    process: str
    source_requirements: tuple[SourceRequirement, ...]
    mutation: MutationRequirement
    state_overrides: tuple[str, ...] = ()


class PlannedEnterpriseQuery(Model):
    id: str
    workflow: str
    query: str
    dimensions: dict[str, str]
    generation: GenerationRequirement
    expected_dag: tuple[dict[str, Any], ...]

    @model_validator(mode="after")
    def _closed_dag(self) -> PlannedEnterpriseQuery:
        seen: set[str] = set()
        for node in self.expected_dag:
            missing = set(node.get("depends_on", ())) - seen
            if missing:
                raise ValueError(f"DAG node {node['id']} has unresolved dependencies {sorted(missing)}")
            seen.add(node["id"])
        return self


class CoverageReport(Model):
    strength: int
    candidates: int
    selected: int
    required_interactions: int
    covered_interactions: int
    holes: tuple[tuple[tuple[str, str], ...], ...] = ()

    @property
    def complete(self) -> bool:
        return not self.holes


def _subsets(row: Mapping[str, str], strength: int) -> set[tuple[tuple[str, str], ...]]:
    return {
        tuple((key, row[key]) for key in keys)
        for keys in itertools.combinations(sorted(row), strength)
    }


def _source_combinations(workflow: WorkflowSpec, profile: CoverageProfile) -> Iterator[tuple[Any, ...]]:
    roles = workflow.sources
    counts = sorted({min(count, len(roles)) for count in profile.connector_counts if count <= len(roles)} | {len(roles)})
    for count in counts:
        yield from itertools.combinations(roles, count)


def valid_rows(registry: SpecRegistry | None = None, profile: CoverageProfile | None = None) -> Iterator[dict[str, str]]:
    """Stream only rows supported by the selected workflow and connector specs."""
    registry = registry or builtin_registry()
    profile = profile or CoverageProfile()
    emitted = 0
    for workflow in registry.workflows.values():
        for sources in _source_combinations(workflow, profile):
            source_set = "+".join(role.connector for role in sources)
            source_entities = "+".join(f"{role.connector}:{role.entities[0]}" for role in sources)
            for destination in workflow.destinations:
                spec = registry.connectors[destination.connector]
                for entity_name in destination.entities:
                    entity = spec.entity(entity_name)
                    operations = tuple(op for op in destination.operations if op in entity.operations)
                    formats = destination.formats or entity.formats or ("record",)
                    for operation, output_format, action, audience, topology, failure, verification in itertools.product(
                        operations,
                        formats,
                        workflow.content_actions,
                        workflow.audiences,
                        workflow.topologies,
                        profile.failures,
                        workflow.verification,
                    ):
                        if operation.value in {"update", "patch"} and failure == "missing_stable_id":
                            continue
                        if failure == "version_conflict" and operation.value not in {"update", "patch", "upsert"}:
                            continue
                        if output_format == "xlsx" and action.value not in {"extract", "compare", "reconcile", "generate", "render"}:
                            continue
                        yield {
                            "workflow": workflow.name,
                            "source_set": source_set,
                            "source_entities": source_entities,
                            "destination": destination.connector,
                            "destination_entity": entity_name,
                            "operation": operation.value,
                            "output_format": output_format,
                            "content_action": action.value,
                            "audience": audience,
                            "topology": topology,
                            "failure": failure,
                            "verification": verification,
                        }
                        emitted += 1
                        if emitted > profile.max_candidates:
                            raise ValueError(f"valid candidate count exceeds max_candidates={profile.max_candidates}; narrow the profile")


def constrained_cover(rows: Iterable[dict[str, str]], strength: int) -> tuple[tuple[dict[str, str], ...], CoverageReport]:
    """Deterministic greedy t-way cover over valid rows only."""
    candidates = tuple(rows)
    if not candidates:
        return (), CoverageReport(strength=strength, candidates=0, selected=0, required_interactions=0, covered_interactions=0)
    if strength > len(candidates[0]):
        raise ValueError("coverage strength exceeds dimension count")
    row_interactions = tuple(_subsets(row, strength) for row in candidates)
    uncovered = set().union(*row_interactions)
    required = len(uncovered)
    chosen: list[dict[str, str]] = []
    remaining = set(range(len(candidates)))
    while uncovered:
        best = max(remaining, key=lambda index: (len(row_interactions[index] & uncovered), -index))
        gain = row_interactions[best] & uncovered
        if not gain:
            break
        chosen.append(candidates[best])
        uncovered.difference_update(gain)
        remaining.remove(best)
    report = CoverageReport(strength=strength, candidates=len(candidates), selected=len(chosen), required_interactions=required, covered_interactions=required - len(uncovered), holes=tuple(sorted(uncovered)))
    return tuple(chosen), report


def _process_for(row: Mapping[str, str]) -> str:
    if row["workflow"] in {"incident_review", "change_assurance"}:
        return "service_management"
    if row["workflow"] == "customer_health":
        return "customer_lifecycle"
    return "delivery_work"


def _render(world: World, workflow: WorkflowSpec, row: Mapping[str, str]) -> str:
    source_names = [registry_name.replace("servicenow", "ServiceNow").replace("sharepoint", "SharePoint").replace("jira", "Jira").replace("salesforce", "Salesforce").replace("confluence", "Confluence").replace("drive", "Drive").replace("email", "email") for registry_name in row["source_set"].split("+")]
    sources = source_names[0] if len(source_names) == 1 else ", ".join(source_names[:-1]) + f", and {source_names[-1]}"
    operation = row["operation"]
    action_instruction = {
        "create": "Create a new",
        "update": "Update the existing",
        "patch": "Change only the affected fields in the",
        "upsert": "Create the record if it is missing, otherwise update the",
        "draft": "Draft a",
        "send": "Send a",
        "reply": "Reply in the existing thread with a",
    }[operation]
    failure_instruction = {
        "none": "",
        "ambiguous_join": " Put ambiguous matches in a review section; do not guess.",
        "missing_stable_id": " Skip records without stable identifiers and report them.",
        "permission_denied": " Report inaccessible sources and do not broaden access.",
        "partial_write": " Report completed and incomplete write branches separately.",
        "stale_source": " Prefer the authoritative current version and identify stale evidence.",
        "version_conflict": " Do not overwrite a newer version; return the conflict for review.",
    }[row["failure"]]
    return workflow.prompt_template.format(period=world.period or "current-period", purpose=workflow.purpose, company=world.company.name, audience=row["audience"], sources=sources, action_instruction=action_instruction, output_label=row["output_format"].upper() if row["output_format"] != "record" else row["destination_entity"].replace("_", " "), destination=row["destination"].replace("servicenow", "ServiceNow").replace("sharepoint", "SharePoint").title(), verification_instruction="read the saved result back and verify the change" if row["verification"] == "readback" else "verify the result against the authoritative source", failure_instruction=failure_instruction)


def _plan(world: World, row: dict[str, str], registry: SpecRegistry) -> PlannedEnterpriseQuery:
    workflow = registry.workflows[row["workflow"]]
    sources = tuple(SourceRequirement(connector=value.split(":", 1)[0], entity=value.split(":", 1)[1]) for value in row["source_entities"].split("+"))
    mutation = MutationRequirement(connector=row["destination"], entity=row["destination_entity"], operation=row["operation"], output_format=row["output_format"], preexisting_record=row["operation"] in {"update", "patch", "upsert", "reply"})
    states = () if row["failure"] == "none" else (row["failure"],)
    read_nodes = tuple({"id": f"read-{index}", "kind": "read", "connector": source.connector, "entity": source.entity, "depends_on": []} for index, source in enumerate(sources))
    transform = {"id": "transform", "kind": row["content_action"], "connector": "model", "entity": row["output_format"], "depends_on": [node["id"] for node in read_nodes]}
    write = {"id": "write", "kind": row["operation"], "connector": row["destination"], "entity": row["destination_entity"], "depends_on": ["transform"]}
    verify = {"id": "verify", "kind": row["verification"], "connector": row["destination"], "entity": row["destination_entity"], "depends_on": ["write"]}
    identifier = content_key("enterprise-query", *[f"{key}={row[key]}" for key in sorted(row)])
    return PlannedEnterpriseQuery(id=identifier, workflow=workflow.name, query=_render(world, workflow, row), dimensions=row, generation=GenerationRequirement(process=_process_for(row), source_requirements=sources, mutation=mutation, state_overrides=states), expected_dag=read_nodes + (transform, write, verify))


def plan_queries(
    world: World,
    *,
    registry: SpecRegistry | None = None,
    profile: CoverageProfile | None = None,
    strategy: Literal["covering", "exhaustive"] = "covering",
    limit: int | None = None,
) -> tuple[Iterator[PlannedEnterpriseQuery], CoverageReport | None]:
    registry = registry or builtin_registry()
    profile = profile or CoverageProfile()
    findings = registry.review()
    if findings:
        raise ValueError("invalid registry: " + "; ".join(findings))
    rows: Iterable[dict[str, str]] = valid_rows(registry, profile)
    report = None
    if strategy == "covering":
        selected, report = constrained_cover(rows, profile.strengths)
        rows = selected
    if limit is not None:
        rows = itertools.islice(rows, limit)
    return (_plan(world, row, registry) for row in rows), report
