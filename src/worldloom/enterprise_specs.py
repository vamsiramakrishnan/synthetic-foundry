"""Authorable enterprise-agent specifications and built-in connector catalog."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .cascade import Brief, CascadeModel, Finding


class Operation(StrEnum):
    SEARCH = "search"
    LIST = "list"
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    PATCH = "patch"
    UPSERT = "upsert"
    DELETE = "delete"
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


class DestinationRole(CascadeModel):
    connector: str
    entities: tuple[str, ...]
    operations: tuple[Operation, ...]
    formats: tuple[str, ...] = ()


class WorkflowSpec(CascadeModel):
    name: str
    purpose: str
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
    max_candidates: int = Field(default=1_000_000, ge=1)


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
            for role in (*workflow.sources, *workflow.destinations):
                connector = self.connectors.get(role.connector)
                if connector is None:
                    findings.append(f"workflow {workflow.name}: replace unknown connector {role.connector}")
                    continue
                for entity in role.entities:
                    try:
                        connector.entity(entity)
                    except KeyError:
                        findings.append(f"workflow {workflow.name}: replace unknown {role.connector} entity {entity}")
        return tuple(findings)


def _entity(name: str, stable_id: str, operations: tuple[Operation, ...], *formats: str) -> EntitySpec:
    return EntitySpec(name=name, stable_id=stable_id, operations=operations, formats=formats)


READ = (Operation.SEARCH, Operation.LIST, Operation.READ)
MUTATE = (Operation.CREATE, Operation.UPDATE, Operation.PATCH, Operation.UPSERT)
FILES = ("docx", "xlsx", "pptx", "pdf", "csv", "html", "markdown")

BUILTIN_CONNECTORS = (
    ConnectorSpec(name="jira", display_name="Jira", entities=(_entity("issue", "key", READ + MUTATE + (Operation.COMMENT, Operation.ATTACH, Operation.LINK)),), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT)),
    ConnectorSpec(name="confluence", display_name="Confluence", entities=(_entity("page", "page_id", READ + MUTATE + (Operation.COMMENT, Operation.ATTACH), "html", "markdown", "pdf"),), content_actions=tuple(ContentAction)),
    ConnectorSpec(name="sharepoint", display_name="SharePoint", entities=(_entity("file", "item_id", READ + MUTATE + (Operation.DELETE,), *FILES), _entity("list_item", "item_id", READ + MUTATE)), content_actions=tuple(ContentAction)),
    ConnectorSpec(name="drive", display_name="Google Drive", entities=(_entity("file", "file_id", READ + MUTATE + (Operation.DELETE,), *FILES),), content_actions=tuple(ContentAction)),
    ConnectorSpec(name="servicenow", display_name="ServiceNow", entities=(_entity("incident", "sys_id", READ + MUTATE + (Operation.COMMENT, Operation.ATTACH)), _entity("change_request", "sys_id", READ + MUTATE + (Operation.COMMENT, Operation.ATTACH))), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT)),
    ConnectorSpec(name="salesforce", display_name="Salesforce", entities=(_entity("account", "id", READ + MUTATE), _entity("opportunity", "id", READ + MUTATE), _entity("case", "id", READ + MUTATE)), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.COMPARE)),
    ConnectorSpec(name="email", display_name="Email", entities=(_entity("message", "message_id", READ + (Operation.DRAFT, Operation.SEND, Operation.REPLY, Operation.FORWARD, Operation.ATTACH)), _entity("thread", "thread_id", READ)), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.CLASSIFY, ContentAction.GENERATE)),
)


def _workflow(name: str, purpose: str, sources: tuple[SourceRole, ...], destinations: tuple[DestinationRole, ...], actions: tuple[ContentAction, ...]) -> WorkflowSpec:
    return WorkflowSpec(
        name=name,
        purpose=purpose,
        sources=sources,
        destinations=destinations,
        content_actions=actions,
        audiences=("executive", "manager", "analyst", "operations", "customer"),
        prompt_template=(
            "Prepare the {period} {purpose} for {company}'s {audience} audience. "
            "Use {sources}. {action_instruction} {output_label} in {destination}. "
            "Reconcile records by stable identifiers, preserve source links and manually entered content, "
            "then {verification_instruction}.{failure_instruction}"
        ),
    )


BUILTIN_WORKFLOWS = (
    _workflow("incident_review", "incident review", (SourceRole(connector="servicenow", entities=("incident", "change_request")), SourceRole(connector="jira", entities=("issue",)), SourceRole(connector="email", entities=("thread",))), (DestinationRole(connector="confluence", entities=("page",), operations=MUTATE, formats=("html", "markdown")), DestinationRole(connector="sharepoint", entities=("file",), operations=MUTATE, formats=("docx", "xlsx", "pptx", "pdf")), DestinationRole(connector="email", entities=("message",), operations=(Operation.DRAFT, Operation.REPLY), formats=("html",))), (ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.RECONCILE, ContentAction.GENERATE)),
    _workflow("customer_health", "customer health review", (SourceRole(connector="salesforce", entities=("account", "opportunity", "case")), SourceRole(connector="email", entities=("thread",)), SourceRole(connector="drive", entities=("file",))), (DestinationRole(connector="salesforce", entities=("account", "opportunity", "case"), operations=(Operation.UPDATE, Operation.PATCH, Operation.UPSERT)), DestinationRole(connector="drive", entities=("file",), operations=MUTATE, formats=("xlsx", "pptx", "pdf")), DestinationRole(connector="email", entities=("message",), operations=(Operation.DRAFT, Operation.REPLY), formats=("html",))), (ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.COMPARE, ContentAction.GENERATE)),
    _workflow("change_assurance", "change assurance pack", (SourceRole(connector="servicenow", entities=("change_request", "incident")), SourceRole(connector="jira", entities=("issue",)), SourceRole(connector="confluence", entities=("page",))), (DestinationRole(connector="sharepoint", entities=("file",), operations=MUTATE, formats=("docx", "xlsx", "pptx", "pdf")), DestinationRole(connector="confluence", entities=("page",), operations=MUTATE, formats=("html", "markdown"))), (ContentAction.EXTRACT, ContentAction.RECONCILE, ContentAction.GENERATE, ContentAction.RENDER)),
    _workflow("executive_digest", "executive operating digest", tuple(SourceRole(connector=name, entities=(("thread",) if name == "email" else ("file",) if name in {"drive", "sharepoint"} else ("page",) if name == "confluence" else ("issue",) if name == "jira" else ("incident",) if name == "servicenow" else ("opportunity",))) for name in ("jira", "confluence", "sharepoint", "drive", "servicenow", "salesforce", "email")), (DestinationRole(connector="drive", entities=("file",), operations=MUTATE, formats=("docx", "xlsx", "pptx", "pdf")), DestinationRole(connector="sharepoint", entities=("file",), operations=MUTATE, formats=("docx", "xlsx", "pptx", "pdf")), DestinationRole(connector="email", entities=("message",), operations=(Operation.DRAFT, Operation.SEND), formats=("html",))), (ContentAction.SUMMARIZE, ContentAction.COMPARE, ContentAction.GENERATE, ContentAction.RENDER)),
)


BUILTIN_PROCESSES = (
    ProcessSpec(name="delivery_work", event_kinds=("task", "milestone", "work"), connector_entities={"jira": "issue"}, status_map={"planned": "To Do", "active": "In Progress", "completed": "Done"}),
    ProcessSpec(name="service_management", event_kinds=("incident", "outage", "degradation", "change"), connector_entities={"servicenow": "incident", "jira": "issue"}, status_map={"planned": "New", "active": "In Progress", "completed": "Resolved"}),
    ProcessSpec(name="customer_lifecycle", event_kinds=("sale", "renewal", "escalation", "support"), connector_entities={"salesforce": "opportunity", "email": "thread"}, status_map={"planned": "Prospecting", "active": "Qualification", "completed": "Closed Won"}),
)


def builtin_registry() -> SpecRegistry:
    return SpecRegistry(BUILTIN_CONNECTORS, BUILTIN_WORKFLOWS, BUILTIN_PROCESSES)


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
