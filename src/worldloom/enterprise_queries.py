"""Constraint-aware planning, fixture requirements, and query rendering."""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from .connector_definition import ConnectorFieldDefinition, load_connector_definition
from .enterprise_specs import (
    CoverageProfile,
    SourceRole,
    SpecRegistry,
    WorkflowSpec,
    builtin_registry,
)
from .ids import content_key
from .models import Model
from .predicates import Predicate, RelativeTime

if TYPE_CHECKING:
    from .world import World


class SourceRequirement(Model):
    connector: str
    entity: str
    minimum: int = Field(default=1, ge=1)
    input_format: str = "record"
    required_fields: tuple[str, ...] = ()
    field_definitions: tuple[ConnectorFieldDefinition, ...] = ()
    predicate: Predicate | None = None
    #: How the compiled search finds its records. ``fixture`` (the default,
    #: and what every corpus before this compiled to) binds the search to the
    #: fixture's exact identities (``id IN [...]``); ``predicate`` compiles
    #: the requirement's own predicate instead, so an agent that reads the
    #: request's rule can search by it, and the reads it must return are still
    #: the fixture's. Only meaningful with a predicate; the validator refuses
    #: the other combination.
    bind: Literal["fixture", "predicate"] = "fixture"

    @model_validator(mode="after")
    def _context_free_predicate(self) -> SourceRequirement:
        if self.bind == "predicate" and self.predicate is None:
            raise ValueError("bind='predicate' needs a predicate to bind the search to")
        if self.predicate is not None and (
            self.predicate.joins or self.predicate.as_of is not None
            or any(isinstance(item.value, RelativeTime) for item in self.predicate.where)
        ):
            raise ValueError("source predicates with joins, as_of or relative time require an explicit QueryContext")
        return self

    @model_serializer(mode="wrap")
    def _legacy_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Opt-in source binding must not alter historical query identities or
        # exported bytes. The wrap serializer also applies when nested in a DAG.
        data: dict[str, Any] = handler(self)
        if self.predicate is None:
            data.pop("predicate", None)
        if self.bind == "fixture":
            data.pop("bind", None)
        return data


class MutationRequirement(Model):
    connector: str
    entity: str
    operation: str
    output_format: str
    preexisting_record: bool
    verify_after_write: bool = True
    target_state: str | None = None
    target_state_field: str = "state"


class ArtifactRequirement(Model):
    format: str
    sections: tuple[str, ...] = ()
    sheets: tuple[str, ...] = ()
    slides: tuple[str, ...] = ()
    charts: tuple[str, ...] = ()


class GenerationRequirement(Model):
    process: str
    source_requirements: tuple[SourceRequirement, ...]
    mutation: MutationRequirement
    artifact: ArtifactRequirement | None = None
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


def _source_combinations(
    workflow: WorkflowSpec, profile: CoverageProfile
) -> Iterator[tuple[SourceRole, ...]]:
    roles = workflow.sources
    counts = sorted({min(count, len(roles)) for count in profile.connector_counts if count <= len(roles)} | {len(roles)})
    for count in counts:
        yield from itertools.combinations(roles, count)


def _source_variants(
    sources: tuple[SourceRole, ...], registry: SpecRegistry
) -> Iterator[tuple[tuple[str, str, str], ...]]:
    options = []
    for role in sources:
        connector = registry.connectors[role.connector]
        role_options = []
        for entity_name in role.entities:
            entity = connector.entity(entity_name)
            for input_format in entity.formats or ("record",):
                role_options.append((role.connector, entity_name, input_format))
        options.append(tuple(role_options))
    yield from itertools.product(*options)


def _rotated(values: Iterable[Any], key: str, slot: int) -> tuple[Any, ...]:
    ordered = tuple(values)
    if not ordered:
        return ()
    start = int(key[slot * 2 : slot * 2 + 4], 16) % len(ordered)
    return ordered[start:] + ordered[:start]


def _row_lanes(
    registry: SpecRegistry, profile: CoverageProfile
) -> list[list[Iterator[dict[str, str]]]]:
    """Independent valid-row streams, one per semantic connector lane."""
    lanes_by_workflow: list[list[Iterator[dict[str, str]]]] = []
    for workflow in registry.workflows.values():
        workflow_lanes: list[Iterator[dict[str, str]]] = []
        for sources in _source_combinations(workflow, profile):
            for variants in _source_variants(sources, registry):
                source_set = "+".join(item[0] for item in variants)
                source_entities = "+".join(
                    f"{connector}:{entity}" for connector, entity, _ in variants
                )
                input_formats = "+".join(item[2] for item in variants)
                for destination in workflow.destinations:
                    spec = registry.connectors[destination.connector]
                    for entity_name in destination.entities:
                        entity = spec.entity(entity_name)
                        operations = tuple(
                            op for op in destination.operations if op in entity.operations
                        )
                        formats = destination.formats or entity.formats or ("record",)
                        lane_key = content_key(
                            "enterprise-lane", workflow.name, source_set,
                            source_entities, input_formats, destination.connector,
                            entity_name,
                        )
                        def lane(
                            *, workflow: WorkflowSpec = workflow,
                            source_set: str = source_set,
                            source_entities: str = source_entities,
                            input_formats: str = input_formats,
                            destination: str = destination.connector,
                            entity_name: str = entity_name,
                            operations: tuple = _rotated(operations, lane_key, 0),
                            formats: tuple = _rotated(formats, lane_key, 1),
                            actions: tuple = _rotated(workflow.content_actions, lane_key, 2),
                            audiences: tuple = _rotated(workflow.audiences, lane_key, 3),
                            topologies: tuple = _rotated(workflow.topologies, lane_key, 4),
                            failures: tuple = _rotated(profile.failures, lane_key, 5),
                            verification_policies: tuple = _rotated(workflow.verification, lane_key, 6),
                        ) -> Iterator[dict[str, str]]:
                            combinations = itertools.product(
                                operations, formats, actions, audiences, topologies,
                                failures, verification_policies,
                            )
                            for operation, output_format, action, audience, topology, failure, verification in combinations:
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
                                "input_formats": input_formats,
                                "destination": destination,
                                "destination_entity": entity_name,
                                "operation": operation.value,
                                "output_format": output_format,
                                "content_action": action.value,
                                "audience": audience,
                                "topology": topology,
                                "failure": failure,
                                "verification": verification,
                                }

                        workflow_lanes.append(lane())
        lanes_by_workflow.append(workflow_lanes)
    return lanes_by_workflow


def valid_rows(registry: SpecRegistry | None = None, profile: CoverageProfile | None = None) -> Iterator[dict[str, str]]:
    """Stream supported rows fairly across semantic connector lanes.

    Round-robin ordering makes a bounded exhaustive prefix representative: a
    2,000-row corpus reaches every workflow and connector shape instead of
    spending its whole budget inside the first workflow's first source tuple.
    """
    registry = registry or builtin_registry()
    profile = profile or CoverageProfile()
    # Two-level fairness: rotate workflows, then rotate semantic connector
    # lanes inside that workflow. This prevents a workflow with more possible
    # connector permutations from dominating every bounded prefix.
    active = deque(deque(group) for group in _row_lanes(registry, profile) if group)
    emitted = 0
    while active:
        workflow_lanes = active.popleft()
        row = None
        while workflow_lanes and row is None:
            lane = workflow_lanes.popleft()
            try:
                row = next(lane)
            except StopIteration:
                continue
            workflow_lanes.append(lane)
        if row is None:
            continue
        yield row
        emitted += 1
        if emitted > profile.max_candidates:
            raise ValueError(
                f"valid candidate count exceeds max_candidates={profile.max_candidates}; narrow the profile"
            )
        active.append(workflow_lanes)


def constrained_cover(rows: Iterable[dict[str, str]], strength: int) -> tuple[tuple[dict[str, str], ...], CoverageReport]:
    """One-pass deterministic t-way cover over valid rows only.

    A row is retained exactly when it introduces a previously unseen
    interaction. This is intentionally streaming: massive spaces do not keep
    every candidate and its interaction set resident in memory.
    """
    covered: set[tuple[tuple[str, str], ...]] = set()
    chosen: list[dict[str, str]] = []
    candidate_count = 0
    dimension_count: int | None = None
    for row in rows:
        candidate_count += 1
        if dimension_count is None:
            dimension_count = len(row)
            if strength > dimension_count:
                raise ValueError("coverage strength exceeds dimension count")
        interactions = _subsets(row, strength)
        if interactions - covered:
            chosen.append(row)
            covered.update(interactions)
    if candidate_count == 0:
        return (), CoverageReport(strength=strength, candidates=0, selected=0, required_interactions=0, covered_interactions=0)
    report = CoverageReport(strength=strength, candidates=candidate_count, selected=len(chosen), required_interactions=len(covered), covered_interactions=len(covered))
    return tuple(chosen), report


def _render(world: World, workflow: WorkflowSpec, row: Mapping[str, str]) -> str:
    formats = row["input_formats"].split("+")
    entities = [value.split(":", 1)[1] for value in row["source_entities"].split("+")]
    source_names = []
    for connector, entity, input_format in zip(
        row["source_set"].split("+"), entities, formats, strict=True
    ):
        display = connector.replace("servicenow", "ServiceNow").replace("sharepoint", "SharePoint").replace("jira", "Jira").replace("salesforce", "Salesforce").replace("confluence", "Confluence").replace("drive", "Drive").replace("email", "email")
        format_label = {
            "xlsx": "Excel workbook",
            "pptx": "presentation",
            "docx": "Word document",
            "pdf": "PDF",
            "csv": "CSV export",
            "html": "page",
            "markdown": "page",
            "record": entity.replace("_", " "),
        }.get(input_format, input_format)
        source_names.append(f"the relevant {display} {format_label}")
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


def _mutation_state(workflow: WorkflowSpec, row: Mapping[str, str]) -> tuple[str | None, str]:
    """Derive a legal update outcome from the authored connector workflow."""
    role = next(
        role for role in workflow.destinations
        if role.connector == row["destination"] and row["destination_entity"] in role.entities
    )
    if row["operation"] not in {"update", "patch", "upsert"}:
        if role.target_state is not None:
            raise ValueError("target_state requires an update, patch, or existing-record upsert")
        return None, "state"
    try:
        definition = load_connector_definition(role.connector)
        workflows = [definition.entities[name].workflow for name in definition.entity_members(row["destination_entity"])]
    except (KeyError, ValueError):
        workflows = []
    if role.target_state is not None:
        for item in workflows:
            if item is None:
                continue
            target = item.canonical_state(role.target_state)
            if role.target_state_field != item.field or target not in item.states:
                raise ValueError(f"invalid authored target state for {role.connector}/{row['destination_entity']}")
            if item.strict and target != item.states[0] and target not in item.transitions.get(item.states[0], item.states):
                raise ValueError(f"authored target state is not reachable from the destination fixture's initial state: {target}")
        target = next((item.canonical_state(role.target_state) for item in workflows if item is not None), role.target_state)
        return target, role.target_state_field
    outcomes = {
        (item.states[1], item.field)
        for item in workflows if item is not None and len(item.states) > 1
        and (not item.strict or item.states[1] in item.transitions.get(item.states[0], item.states))
    }
    if len(outcomes) == 1 and all(item is not None for item in workflows):
        return next(iter(outcomes))
    return None, "state"


def _plan(world: World, row: dict[str, str], registry: SpecRegistry) -> PlannedEnterpriseQuery:
    workflow = registry.workflows[row["workflow"]]
    input_formats = row["input_formats"].split("+")
    from .enterprise_fields import source_requirement

    sources = tuple(
        source_requirement(
            connector=value.split(":", 1)[0],
            entity=value.split(":", 1)[1],
            input_format=input_format,
            registry=registry,
            workflow=workflow,
        )
        for value, input_format in zip(
            row["source_entities"].split("+"), input_formats, strict=True
        )
    )
    target_state, target_state_field = _mutation_state(workflow, row)
    mutation = MutationRequirement(connector=row["destination"], entity=row["destination_entity"], operation=row["operation"], output_format=row["output_format"], preexisting_record=row["operation"] in {"update", "patch", "upsert", "reply"}, target_state=target_state, target_state_field=target_state_field)
    artifact = {
        "xlsx": ArtifactRequirement(format="xlsx", sheets=("Summary", "Detail", "Exceptions", "Provenance"), charts=("status_breakdown", "period_trend")),
        "pptx": ArtifactRequirement(format="pptx", slides=("Title", "Executive summary", "Metrics", "Risks", "Actions", "Sources"), charts=("status_breakdown", "period_trend")),
        "docx": ArtifactRequirement(format="docx", sections=("Executive summary", "Findings", "Risks", "Actions", "Sources")),
        "pdf": ArtifactRequirement(format="pdf", sections=("Executive summary", "Findings", "Risks", "Actions", "Sources")),
        "csv": ArtifactRequirement(format="csv", sections=("detail_rows",)),
        "html": ArtifactRequirement(format="html", sections=("Summary", "Findings", "Actions", "Sources")),
        "markdown": ArtifactRequirement(format="markdown", sections=("Summary", "Findings", "Actions", "Sources")),
    }.get(row["output_format"])
    states = () if row["failure"] == "none" else (row["failure"],)
    read_nodes: tuple[dict[str, Any], ...] = tuple({"id": f"read-{index}", "kind": "search" if source.required_fields else "read", "connector": source.connector, "entity": source.entity, "depends_on": []} for index, source in enumerate(sources))
    transform = {"id": "transform", "kind": row["content_action"], "connector": "model", "entity": row["output_format"], "depends_on": [node["id"] for node in read_nodes]}
    write = {"id": "write", "kind": row["operation"], "connector": row["destination"], "entity": row["destination_entity"], "depends_on": ["transform"]}
    verify = {"id": "verify", "kind": row["verification"], "connector": row["destination"], "entity": row["destination_entity"], "depends_on": ["write"]}
    request = _render(world, workflow, row)
    for source in sources:
        if source.required_fields:
            request += f" Filter {source.connector}/{source.entity} to records with non-null {', '.join(source.required_fields)} and include those fields in the result."
    if mutation.target_state is not None:
        request += f" Set {mutation.connector}/{mutation.entity} {mutation.target_state_field} to {mutation.target_state!r}."
    contract = tuple(source.model_dump_json() for source in sources if source.required_fields or source.field_definitions)
    if mutation.target_state is not None:
        contract += (mutation.model_dump_json(),)
    identifier = content_key("enterprise-query", *[f"{key}={row[key]}" for key in sorted(row)], *contract)
    return PlannedEnterpriseQuery(id=identifier, workflow=workflow.name, query=request, dimensions=row, generation=GenerationRequirement(process=workflow.process, source_requirements=sources, mutation=mutation, artifact=artifact, state_overrides=states), expected_dag=read_nodes + (transform, write, verify))


def plan_queries(
    world: World,
    *,
    registry: SpecRegistry | None = None,
    profile: CoverageProfile | None = None,
    strategy: Literal["covering", "exhaustive"] = "covering",
    limit: int | None = None,
    shard_index: int | None = None,
    shard_count: int | None = None,
    dag_shapes: tuple[str, ...] = (),
) -> tuple[Iterator[PlannedEnterpriseQuery], CoverageReport | None]:
    registry = registry or builtin_registry()
    profile = profile or CoverageProfile()
    findings = registry.review()
    if findings:
        raise ValueError("invalid registry: " + "; ".join(findings))
    rows: Iterable[dict[str, str]] = valid_rows(registry, profile)
    if dag_shapes:
        from .enterprise_dag_planning import compatible_shapes

        def expanded(candidates: Iterable[dict[str, str]]) -> Iterator[dict[str, str]]:
            emitted = False
            for candidate in candidates:
                for shape in compatible_shapes(candidate, dag_shapes):
                    emitted = True
                    yield {**candidate, "dag_shape": shape}
            if not emitted:
                raise ValueError("requested DAG shapes admit no executable workflow")

        rows = expanded(rows)
    report = None
    if strategy == "covering":
        selected, report = constrained_cover(rows, profile.strengths)
        rows = selected
    if (shard_index is None) != (shard_count is None):
        raise ValueError("shard_index and shard_count must be supplied together")
    if shard_index is not None and shard_count is not None:
        if shard_count < 1 or not 0 <= shard_index < shard_count:
            raise ValueError("shard requires count >= 1 and 0 <= index < count")
        rows = itertools.islice(rows, shard_index, None, shard_count)
    if limit is not None:
        rows = itertools.islice(rows, limit)
    def planned(row: dict[str, str]) -> PlannedEnterpriseQuery:
        query = _plan(world, row, registry)
        if dag_shapes:
            from .enterprise_dag_planning import apply_dag_shape
            query = apply_dag_shape(query, row["dag_shape"])
        return query

    return (planned(row) for row in rows), report
