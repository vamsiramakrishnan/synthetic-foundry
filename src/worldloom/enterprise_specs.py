"""Authorable enterprise-agent specifications and built-in connector catalog."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from . import packkit
from .cascade import Brief, CascadeModel, Finding, load, refuse
from .connector_definition import (
    REFERENCE_CONNECTORS,
    ConnectorDefinition,
    ConnectorFieldDefinition,
    builtin_connector_definitions,
    reference_connectors,
    shipped_connector_definition,
    shipped_order,
)


class Operation(StrEnum):
    SEARCH = "search"
    LIST = "list"
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    PATCH = "patch"
    UPSERT = "upsert"
    DELETE = "delete"
    MOVE = "move"
    COMMENT = "comment"
    ATTACH = "attach"
    LINK = "link"
    DRAFT = "draft"
    SEND = "send"
    REPLY = "reply"
    FORWARD = "forward"


class ContentAction(StrEnum):
    SUMMARIZE = "summarize"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    COMPARE = "compare"
    RECONCILE = "reconcile"
    TRANSFORM = "transform"
    GENERATE = "generate"
    RENDER = "render"
    CONVERT = "convert"


class EntitySpec(CascadeModel):
    name: str
    stable_id: str
    operations: tuple[Operation, ...]
    formats: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    field_definitions: tuple[ConnectorFieldDefinition, ...] = ()

    @model_validator(mode="after")
    def _unique_fields(self) -> EntitySpec:
        for attribute in ("id", "canonical"):
            values = [getattr(field, attribute) for field in self.field_definitions]
            if len(values) != len(set(values)):
                raise ValueError(f"{self.name}: field {attribute} values must be unique")
        return self


class ConnectorSpec(CascadeModel):
    name: str
    display_name: str
    entities: tuple[EntitySpec, ...]
    content_actions: tuple[ContentAction, ...] = ()

    def entity(self, name: str) -> EntitySpec:
        for entity in self.entities:
            if entity.name == name:
                return entity
        raise KeyError(f"{self.name} has no entity {name!r}")


class SourceRole(CascadeModel):
    connector: str
    entities: tuple[str, ...]
    operations: tuple[Operation, ...] = (Operation.SEARCH, Operation.READ)
    minimum: int = Field(default=1, ge=1)
    required_fields: tuple[str, ...] = ()


class DestinationRole(CascadeModel):
    connector: str
    entities: tuple[str, ...]
    operations: tuple[Operation, ...]
    formats: tuple[str, ...] = ()
    target_state: str | None = None
    target_state_field: str = "state"


class WorkflowSpec(CascadeModel):
    name: str
    purpose: str
    process: str = "delivery_work"
    sources: tuple[SourceRole, ...]
    destinations: tuple[DestinationRole, ...]
    content_actions: tuple[ContentAction, ...]
    audiences: tuple[str, ...]
    topologies: tuple[str, ...] = ("chain", "fan_in", "fan_out", "diamond")
    verification: tuple[str, ...] = ("readback", "cross_system")
    prompt_template: str

    @model_validator(mode="after")
    def _has_roles(self) -> WorkflowSpec:
        if not self.sources or not self.destinations:
            raise ValueError("workflow requires source and destination roles")
        return self


class ProcessSpec(CascadeModel):
    name: str
    event_kinds: tuple[str, ...]
    connector_entities: dict[str, str]
    status_map: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class CoverageProfile(CascadeModel):
    name: str = "enterprise-default"
    strengths: int = Field(default=2, ge=1, le=4)
    connector_counts: tuple[int, ...] = (1, 2, 4, 6)
    failures: tuple[str, ...] = (
        "none",
        "ambiguous_join",
        "missing_stable_id",
        "permission_denied",
        "partial_write",
        "stale_source",
        "version_conflict",
    )
    max_candidates: int = Field(default=10_000_000, ge=1)


class EnterpriseEvalSpec(CascadeModel):
    connectors: tuple[ConnectorSpec, ...]
    workflows: tuple[WorkflowSpec, ...]
    processes: tuple[ProcessSpec, ...]
    coverage: CoverageProfile = Field(default_factory=CoverageProfile)


class ScenarioProfile(CascadeModel):
    name: str
    industry: str
    company_description: str
    workflows: tuple[str, ...] = ()
    additional_workflows: tuple[WorkflowSpec, ...] = ()
    additional_connectors: tuple[ConnectorSpec, ...] = ()
    additional_processes: tuple[ProcessSpec, ...] = ()
    connectors: tuple[str, ...] = ()
    vocabulary: dict[str, str] = Field(default_factory=dict)
    coverage: CoverageProfile = Field(default_factory=CoverageProfile)


class SpecRegistry:
    """Explicit registry; callers can replace every built-in decision."""

    def __init__(
        self,
        connectors: Iterable[ConnectorSpec] = (),
        workflows: Iterable[WorkflowSpec] = (),
        processes: Iterable[ProcessSpec] = (),
    ) -> None:
        self.connectors = {item.name: item for item in connectors}
        self.workflows = {item.name: item for item in workflows}
        self.processes = {item.name: item for item in processes}

    def review(self) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for workflow in self.workflows.values():
            for role in workflow.sources:
                connector = self.connectors.get(role.connector)
                if connector is None:
                    findings.append(f"workflow {workflow.name}: replace unknown connector {role.connector}")
                    continue
                for entity in role.entities:
                    try:
                        entity_spec = connector.entity(entity)
                    except KeyError:
                        findings.append(f"workflow {workflow.name}: replace unknown {role.connector} entity {entity}")
                        continue
                    if entity_spec.required_fields or entity_spec.field_definitions or role.required_fields:
                        from .enterprise_fields import source_requirement

                        try:
                            source_requirement(connector=role.connector, entity=entity, input_format="record", registry=self, workflow=workflow)
                        except (ValueError, KeyError) as error:
                            findings.append(f"workflow {workflow.name}: {error}")
                    unsupported = set(role.operations) - set(entity_spec.operations)
                    if unsupported:
                        findings.append(
                            f"workflow {workflow.name}: remove unsupported {role.connector}.{entity} source operations {sorted(item.value for item in unsupported)}"
                        )
            for destination in workflow.destinations:
                connector = self.connectors.get(destination.connector)
                if connector is None:
                    findings.append(f"workflow {workflow.name}: replace unknown connector {destination.connector}")
                    continue
                for entity in destination.entities:
                    try:
                        entity_spec = connector.entity(entity)
                    except KeyError:
                        findings.append(f"workflow {workflow.name}: replace unknown {destination.connector} entity {entity}")
                        continue
                    unsupported = set(destination.operations) - set(entity_spec.operations)
                    if unsupported:
                        findings.append(
                            f"workflow {workflow.name}: remove unsupported {destination.connector}.{entity} destination operations {sorted(item.value for item in unsupported)}"
                        )
                    unsupported_formats = set(destination.formats) - set(entity_spec.formats)
                    if entity_spec.formats and unsupported_formats:
                        findings.append(
                            f"workflow {workflow.name}: remove unsupported {destination.connector}.{entity} formats {sorted(unsupported_formats)}"
                        )
        return tuple(findings)


READ = (Operation.SEARCH, Operation.LIST, Operation.READ)
MUTATE = (Operation.CREATE, Operation.UPDATE, Operation.PATCH, Operation.UPSERT)
#: Operations that address a record which must already exist at the
#: destination. The planner materialises a destination fixture for these;
#: a create, draft or send makes its own record.
RECORD_ADDRESSED = (Operation.UPDATE, Operation.PATCH, Operation.UPSERT, Operation.DELETE, Operation.MOVE,
                    Operation.COMMENT, Operation.ATTACH, Operation.LINK, Operation.REPLY, Operation.FORWARD)


#: A definition operation that is the same act as a spec `Operation`. A
#: definition's `post` and `upload` make a record, so they read as `create`.
_DEFINITION_OPERATIONS = {**{item.value: item for item in Operation}, "post": Operation.CREATE, "upload": Operation.CREATE}


def _derived_operations(definition: ConnectorDefinition, entity: str) -> tuple[Operation, ...]:
    """What an entity the catalog states no operations for may do: read, and write through each tool its ops map.

    `patch` and `upsert`, which no definition carries, stay off, so a
    workflow asking for one is reported by `review()` instead of planned. An
    alias (Jira's `issue`) writes through what any of its members does.
    """

    ops = {op for member in definition.entity_members(entity) for op in definition.entities[member].ops}
    writes = {_DEFINITION_OPERATIONS[op] for op in ops if op in _DEFINITION_OPERATIONS} - set(READ)
    writes -= {Operation.PATCH, Operation.UPSERT}
    return READ + tuple(item for item in Operation if item in writes)


def connector_spec_from_definition(definition: ConnectorDefinition) -> ConnectorSpec:
    """The planner's spec for a connector, read from its definition's `catalog`.

    Every shipped connector's spec is this (`BUILTIN_CONNECTORS`), and so is
    a connector pack's. What the catalog states wins: the display name a
    prompt uses (``Jira``, where the product is ``Jira Cloud``), the coarse
    entity the planner names (``issue``, where the emulator serves issue
    types), the stable id a fixture carries (``key``, where the emulator's
    ident is ``ident``) and the operations in the order a planned row lists
    them. What it leaves out is derived: every definition entity, keyed by
    the definition's identity field, reading as `search`/`list`/`read` and
    writing through each tool its entity maps (`_derived_operations`), named
    by `vendor_product`, content `summarize` and `extract`.
    """

    catalog = definition.catalog
    entities = tuple(
        EntitySpec(
            name=name,
            stable_id=str(entry.stable_id),
            operations=(tuple(Operation(op) for op in entry.operations) if entry.operations is not None
                        else _derived_operations(definition, name)),
            formats=entry.formats,
        )
        for name, entry in definition.catalog_entities().items()
    )
    actions = catalog.content_actions if catalog is not None else ("summarize", "extract")
    return ConnectorSpec(name=definition.connector, display_name=definition.display_name, entities=entities,
                         content_actions=tuple(ContentAction(action) for action in actions))


def _builtin_connectors() -> tuple[ConnectorSpec, ...]:
    """Every shipped connector's spec, in the registry order ``_order.json`` pins.

    Every planned query row iterates this order, so it is stated rather than
    derived; a shipped connector the order does not name follows in
    reference order. Maturity is not a gate: the definitions expose `rovo`
    (product_surface) and `teamwork_graph` (eap) unconditionally and the
    binding carries the maturity through as data, so the specs follow suit.
    """

    pinned = [name for name in shipped_order("specs") if name in REFERENCE_CONNECTORS]
    names = (*pinned, *(name for name in REFERENCE_CONNECTORS if name not in pinned))
    return tuple(connector_spec_from_definition(shipped_connector_definition(name)) for name in names)


BUILTIN_CONNECTORS = _builtin_connectors()
"""The planner's builtin connector specs, derived from each shipped
definition's ``catalog``. ``tests/test_connector_tables.py`` pins them to the
literal tuple they replaced. That tuple sat beside the definitions and
silently disagreed with them (``Jira`` against ``Jira Cloud``, ``issue``
against the issue types, ``key`` against ``ident``); the disagreements are
now fields a catalog states, and a pack states its own."""


def _connectors() -> tuple[ConnectorSpec, ...]:
    """`BUILTIN_CONNECTORS`, then a derived spec for every connector pack in view.

    Without a pack in view this is `BUILTIN_CONNECTORS` itself, so a default
    registry is unchanged. A pack named like a builtin connector keeps the
    builtin spec: the spec is the planner's vocabulary, and a shadowing pack
    changes what is served, not which workflows can be planned.
    """
    known = {spec.name for spec in BUILTIN_CONNECTORS}
    extra = tuple(name for name in reference_connectors() if name not in known)
    if not extra:
        return BUILTIN_CONNECTORS
    definitions = builtin_connector_definitions(extra)
    return (*BUILTIN_CONNECTORS, *(connector_spec_from_definition(definitions[name]) for name in extra))


def _workflow(name: str, purpose: str, sources: tuple[SourceRole, ...], destinations: tuple[DestinationRole, ...], actions: tuple[ContentAction, ...], prompt_template: str) -> WorkflowSpec:
    return WorkflowSpec(
        name=name,
        purpose=purpose,
        process=(
            "service_management"
            if name in {"incident_review", "change_assurance"}
            else "customer_lifecycle" if name == "customer_health" else "delivery_work"
        ),
        sources=sources,
        destinations=destinations,
        content_actions=actions,
        audiences=("executive", "manager", "analyst", "operations", "customer"),
        prompt_template=prompt_template,
    )


def _builtin_workflows() -> tuple[WorkflowSpec, ...]:
    """The builtin workflows, their prompt template read from the prompts pack in force.

    Read per registry rather than once at import, so an industry pack that
    rewords `enterprise.workflow.prompt` reaches the queries planned under it.
    """
    return _workflows_for(packkit.template("enterprise.workflow.prompt"))


@lru_cache(maxsize=8)
def _workflows_for(prompt_template: str) -> tuple[WorkflowSpec, ...]:
    return (
        _workflow("incident_review", "incident review", (SourceRole(connector="servicenow", entities=("incident", "change_request")), SourceRole(connector="jira", entities=("issue",)), SourceRole(connector="email", entities=("thread",))), (DestinationRole(connector="confluence", entities=("page",), operations=MUTATE, formats=("html", "markdown")), DestinationRole(connector="sharepoint", entities=("file",), operations=MUTATE, formats=("docx", "xlsx", "pptx", "pdf")), DestinationRole(connector="email", entities=("message",), operations=(Operation.DRAFT, Operation.REPLY), formats=("html",))), (ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.RECONCILE, ContentAction.GENERATE), prompt_template),
        _workflow("customer_health", "customer health review", (SourceRole(connector="salesforce", entities=("account", "opportunity", "case")), SourceRole(connector="email", entities=("thread",)), SourceRole(connector="drive", entities=("file",))), (DestinationRole(connector="salesforce", entities=("account", "opportunity", "case"), operations=(Operation.UPDATE, Operation.PATCH, Operation.UPSERT)), DestinationRole(connector="drive", entities=("file",), operations=MUTATE, formats=("xlsx", "pptx", "pdf")), DestinationRole(connector="email", entities=("message",), operations=(Operation.DRAFT, Operation.REPLY), formats=("html",))), (ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.COMPARE, ContentAction.GENERATE), prompt_template),
        _workflow("change_assurance", "change assurance pack", (SourceRole(connector="servicenow", entities=("change_request", "incident")), SourceRole(connector="jira", entities=("issue",)), SourceRole(connector="confluence", entities=("page",))), (DestinationRole(connector="sharepoint", entities=("file",), operations=MUTATE, formats=("docx", "xlsx", "pptx", "pdf")), DestinationRole(connector="confluence", entities=("page",), operations=MUTATE, formats=("html", "markdown"))), (ContentAction.EXTRACT, ContentAction.RECONCILE, ContentAction.GENERATE, ContentAction.RENDER), prompt_template),
        _workflow("executive_digest", "executive operating digest", tuple(SourceRole(connector=name, entities=(("thread",) if name == "email" else ("file",) if name in {"drive", "sharepoint"} else ("page",) if name == "confluence" else ("issue",) if name == "jira" else ("incident",) if name == "servicenow" else ("opportunity",))) for name in ("jira", "confluence", "sharepoint", "drive", "servicenow", "salesforce", "email")), (DestinationRole(connector="drive", entities=("file",), operations=MUTATE, formats=("docx", "xlsx", "pptx", "pdf")), DestinationRole(connector="sharepoint", entities=("file",), operations=MUTATE, formats=("docx", "xlsx", "pptx", "pdf")), DestinationRole(connector="email", entities=("message",), operations=(Operation.DRAFT, Operation.SEND), formats=("html",))), (ContentAction.SUMMARIZE, ContentAction.COMPARE, ContentAction.GENERATE, ContentAction.RENDER), prompt_template),
    )


BUILTIN_WORKFLOWS = _builtin_workflows()
"""The builtin workflows under the shipped prompts; `builtin_registry` reads the packs in force."""


BUILTIN_PROCESSES = (
    ProcessSpec(name="delivery_work", event_kinds=("task", "milestone", "work"), connector_entities={"jira": "issue"}, status_map={"planned": "To Do", "active": "In Progress", "completed": "Done"}),
    ProcessSpec(name="service_management", event_kinds=("incident", "outage", "degradation", "change"), connector_entities={"servicenow": "incident", "jira": "issue"}, status_map={"planned": "New", "active": "In Progress", "completed": "Resolved"}),
    ProcessSpec(name="customer_lifecycle", event_kinds=("sale", "renewal", "escalation", "support"), connector_entities={"salesforce": "opportunity", "email": "thread"}, status_map={"planned": "Prospecting", "active": "Qualification", "completed": "Closed Won"}),
)


def builtin_registry() -> SpecRegistry:
    return SpecRegistry(_connectors(), _builtin_workflows(), BUILTIN_PROCESSES)


def canonical_action(value: str, *, content: bool = False) -> str:
    lowered = value.strip().lower()
    if lowered == "modify":
        return ContentAction.TRANSFORM if content else Operation.UPDATE
    valid: set[str] = {item.value for item in (ContentAction if content else Operation)}
    if lowered not in valid:
        raise ValueError(f"unknown {'content action' if content else 'operation'} {value!r}")
    return lowered


def brief_registry(registry: SpecRegistry) -> Brief:
    return Brief(stage="registry", asks="Review or extend the enterprise connector, workflow, and process specifications.", context={"connectors": sorted(registry.connectors), "workflows": sorted(registry.workflows), "processes": sorted(registry.processes)})


def registry_from_dict(payload: dict[str, Any]) -> SpecRegistry:
    return SpecRegistry(
        (ConnectorSpec.model_validate(item) for item in payload.get("connectors", ())),
        (WorkflowSpec.model_validate(item) for item in payload.get("workflows", ())),
        (ProcessSpec.model_validate(item) for item in payload.get("processes", ())),
    )


def load_enterprise_spec(
    source: str | Path | dict[str, Any],
) -> EnterpriseEvalSpec:
    spec = load(source, EnterpriseEvalSpec)
    findings = SpecRegistry(spec.connectors, spec.workflows, spec.processes).review()
    if findings:
        refuse("enterprise evaluation specification", findings)
    return spec


def builtin_spec() -> EnterpriseEvalSpec:
    return EnterpriseEvalSpec(
        connectors=_connectors(),
        workflows=_builtin_workflows(),
        processes=BUILTIN_PROCESSES,
    )


def apply_scenario_profile(
    registry: SpecRegistry, profile: ScenarioProfile
) -> SpecRegistry:
    merged_connectors = {**registry.connectors}
    merged_connectors.update({item.name: item for item in profile.additional_connectors})
    merged_workflows = {**registry.workflows}
    merged_workflows.update(
        {workflow.name: workflow for workflow in profile.additional_workflows}
    )
    merged_processes = {**registry.processes}
    merged_processes.update(
        {process.name: process for process in profile.additional_processes}
    )
    # A name this registry does not hold is a typo, and it used to behave like
    # a filter that matched nothing: `connectors: ["sharepont"]` planned zero
    # candidates, wrote an empty corpus and exited 0. A selection that silently
    # selects nothing is the worst failure this surface has, because the build
    # succeeds and the eval set tests nothing. Every unknown name is named at
    # once, the way `review()` reports below.
    unknown = [
        f"unknown connector {name!r}"
        for name in sorted(set(profile.connectors) - set(merged_connectors))
    ] + [
        f"unknown workflow {name!r}"
        for name in sorted(set(profile.workflows) - set(merged_workflows))
    ]
    if unknown:
        refuse("enterprise scenario profile", unknown)

    connectors = set(profile.connectors) or set(merged_connectors)
    workflows = set(profile.workflows) or set(merged_workflows)
    selected_workflows = []
    for workflow in merged_workflows.values():
        if workflow.name not in workflows:
            continue
        sources = tuple(role for role in workflow.sources if role.connector in connectors)
        destinations = tuple(
            role for role in workflow.destinations if role.connector in connectors
        )
        if not sources or not destinations:
            continue
        selected_workflows.append(
            workflow.model_copy(
                update={
                    "sources": sources,
                    "destinations": destinations,
                    "purpose": _replace_vocabulary(
                        workflow.purpose, profile.vocabulary
                    ),
                    "prompt_template": _replace_vocabulary(
                        workflow.prompt_template, profile.vocabulary
                    ),
                }
            )
        )
    selected = SpecRegistry(
        (item for name, item in merged_connectors.items() if name in connectors),
        selected_workflows,
        merged_processes.values(),
    )
    if not selected_workflows:
        # Every name resolved, and the cross of them still admits nothing: a
        # workflow whose sources or destinations all sit outside the chosen
        # connectors is dropped at the `continue` above. Same silent-empty
        # outcome as an unknown name, reached a different way, so it is refused
        # in the same place rather than left to surface as `queries: 0`.
        refuse(
            "enterprise scenario profile",
            [
                "no workflow survives this selection: "
                f"connectors {sorted(connectors)} cover neither the sources nor"
                f" the destinations of workflows {sorted(workflows)}"
            ],
        )
    findings = selected.review()
    if findings:
        refuse("enterprise scenario profile", findings)
    return selected


def _replace_vocabulary(value: str, vocabulary: dict[str, str]) -> str:
    rendered = value
    for source, replacement in sorted(
        vocabulary.items(), key=lambda item: (-len(item[0]), item[0])
    ):
        rendered = rendered.replace(source.replace("_", " "), replacement)
    return rendered
