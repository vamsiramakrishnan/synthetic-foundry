"""Plan a massive agent query space, then materialise exactly what it needs."""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from . import spaces
from .connector_data import ConnectorDataset, generate_connector_data
from .covering import Parameter
from .ids import content_key
from .models import Model

if TYPE_CHECKING:
    from .world import World


CONNECTORS = (
    "jira",
    "confluence",
    "sharepoint",
    "drive",
    "servicenow",
    "salesforce",
    "email",
)

WORKFLOWS = (
    "incident_review",
    "risk_register",
    "steering_pack",
    "customer_health",
    "change_assurance",
    "executive_digest",
)

OUTPUTS = (
    "record",
    "page",
    "document",
    "workbook",
    "presentation",
    "chart",
    "email",
)

FAILURES = (
    "none",
    "ambiguous_join",
    "missing_stable_id",
    "permission_denied",
    "partial_write",
    "stale_source",
    "version_conflict",
)


class RecordRequirement(Model):
    connector: str
    entity: str
    minimum: int = Field(default=1, ge=1)
    state: str = "current"
    required_fields: list[str] = Field(default_factory=list)


class MutationRequirement(Model):
    connector: str
    entity: str
    operation: str
    preexisting_record: bool
    injected_failure: str = "none"
    idempotency_required: bool = True
    verify_after_write: bool = True


class PlannedQuery(Model):
    id: str
    query: str
    dimensions: dict[str, str]
    sources: list[RecordRequirement]
    mutation: MutationRequirement
    expected_content_verb: str
    expected_topology: str


class QueryFixture(Model):
    query_id: str
    input_record_ids: dict[str, list[str]]
    output_record_id: str | None = None
    injected_failure: str = "none"


class QueryDrivenCorpus(Model):
    plan: list[PlannedQuery]
    connector_data: ConnectorDataset
    fixtures: list[QueryFixture]
    strategy: str
    strength: int | None = None
    exhaustive_space: int


def _source_sets() -> tuple[str, ...]:
    values: list[str] = []
    for count in (1, 2, 3, 4, 6):
        values.extend("+".join(combo) for combo in itertools.combinations(CONNECTORS, count))
    return tuple(values)


def _write_targets() -> tuple[str, ...]:
    record_targets = (
        "jira",
        "confluence",
        "sharepoint",
        "drive",
        "servicenow",
        "salesforce",
    )
    values = [
        f"{connector}:{operation}"
        for connector in record_targets
        for operation in ("create", "update", "patch", "upsert")
    ]
    values.extend(("email:draft", "email:reply"))
    return tuple(values)


def query_space() -> spaces.BuildSpace:
    """Every declared permutation; constraints are encoded into compound axes."""
    return spaces.BuildSpace(
        (
            Parameter("workflow", WORKFLOWS),
            Parameter("source_set", _source_sets()),
            Parameter("write_target", _write_targets()),
            Parameter("output", OUTPUTS),
            Parameter(
                "audience",
                ("executive", "manager", "analyst", "operations", "customer"),
            ),
            Parameter(
                "content_verb",
                ("summarize", "extract", "compare", "reconcile", "generate", "convert"),
            ),
            Parameter("topology", ("chain", "fan_in", "fan_out", "diamond", "map_reduce")),
            Parameter("failure", FAILURES),
            Parameter("verification", ("readback", "cross_system", "checksum")),
        )
    )


def _rows(
    space: spaces.BuildSpace,
    strategy: Literal["covering", "exhaustive"],
    strength: int,
) -> Any:
    if strategy == "covering":
        yield from spaces.cover(space, strength=strength)
        return
    if strategy == "exhaustive":
        names = space.names
        for values in itertools.product(*(axis.values for axis in space.axes)):
            yield dict(zip(names, values, strict=True))
        return
    raise ValueError(f"unknown query planning strategy {strategy!r}")


def _entity(connector: str) -> str:
    return {
        "jira": "issue",
        "confluence": "page",
        "sharepoint": "file",
        "drive": "file",
        "servicenow": "incident",
        "salesforce": "case",
        "email": "message",
    }[connector]


def _query(world: World, row: dict[str, str]) -> str:
    sources = row["source_set"].split("+")
    source_names = {
        "jira": "unresolved Jira issues",
        "confluence": "approved Confluence pages",
        "sharepoint": "the current SharePoint register",
        "drive": "the latest working files in Drive",
        "servicenow": "linked ServiceNow incidents and changes",
        "salesforce": "open Salesforce opportunities and escalated cases",
        "email": "the relevant email threads and attachments",
    }
    source_text = [source_names[name] for name in sources]
    joined = (
        source_text[0]
        if len(source_text) == 1
        else ", ".join(source_text[:-1]) + f", and {source_text[-1]}"
    )
    destination, operation = row["write_target"].split(":")
    action = {
        "create": "Create a new",
        "update": "Update the existing",
        "patch": "Change only the affected fields in the",
        "upsert": "Create or update the",
        "draft": "Draft an",
        "reply": "Reply to the existing thread with an updated",
    }[operation]
    failure_clause = {
        "none": "",
        "ambiguous_join": " Put ambiguous matches in a review section; do not guess.",
        "missing_stable_id": " Skip records without a stable identifier and report them.",
        "permission_denied": " If a source is inaccessible, report it and do not broaden permissions.",
        "partial_write": " If any write fails, report the completed and incomplete branches separately.",
        "stale_source": " Prefer the current authoritative record and identify stale sources.",
        "version_conflict": " Do not overwrite a newer version; report the conflict.",
    }[row["failure"]]
    return (
        f"Prepare the {world.period or 'current'} {row['workflow'].replace('_', ' ')} "
        f"for {world.company.name}'s {row['audience']} audience. Use {joined}. "
        f"Reconcile records using stable "
        f"linked-record identifiers and the reporting period. {action} {row['output']} "
        f"in {destination.title()}. Preserve source links and manually entered content. "
        f"Read the saved result back and verify the change.{failure_clause}"
    )


def plan_query_set(
    world: World,
    *,
    strategy: Literal["covering", "exhaustive"] = "covering",
    strength: int = 2,
    limit: int | None = None,
) -> tuple[PlannedQuery, ...]:
    """Plan first. No connector record is generated until this returns."""
    space = query_space()
    plans = []
    for index, row in enumerate(_rows(space, strategy, strength)):
        if limit is not None and index >= limit:
            break
        source_connectors = row["source_set"].split("+")
        destination, operation = row["write_target"].split(":")
        key = content_key(
            world.seed,
            world.company.id,
            world.period,
            *(row[name] for name in space.names),
        )
        plans.append(
            PlannedQuery(
                id=f"QPLAN-{key[:16].upper()}",
                query=_query(world, row),
                dimensions=dict(row),
                sources=[
                    RecordRequirement(
                        connector=connector,
                        entity=_entity(connector),
                        state="stale" if row["failure"] == "stale_source" else "current",
                        required_fields=["stable_id", "title", "updated_at", "source_links"],
                    )
                    for connector in source_connectors
                ],
                mutation=MutationRequirement(
                    connector=destination,
                    entity=_entity(destination),
                    operation=operation,
                    preexisting_record=operation in {"update", "patch", "upsert", "reply"},
                    injected_failure=row["failure"],
                ),
                expected_content_verb=row["content_verb"],
                expected_topology=row["topology"],
            )
        )
    return tuple(plans)


def _pick(records: list[Any], query_id: str) -> Any:
    if not records:
        raise ValueError(f"query plan requires a connector with no generated records: {query_id}")
    return records[int(content_key(query_id), 16) % len(records)]


def generate_from_query_plan(
    world: World, plans: tuple[PlannedQuery, ...]
) -> QueryDrivenCorpus:
    """Materialise connector records and mutation fixtures demanded by the plan."""
    required = tuple(
        connector
        for connector in CONNECTORS
        if any(
            connector in {source.connector for source in plan.sources}
            or connector == plan.mutation.connector
            for plan in plans
        )
    )
    dataset = generate_connector_data(world, connectors=required)
    by_connector = {
        connector: dataset.for_connector(connector) for connector in required
    }
    fixtures = []
    for plan in plans:
        inputs = {
            source.connector: [
                _pick(by_connector[source.connector], plan.id).id
            ]
            for source in plan.sources
        }
        output = None
        if plan.mutation.preexisting_record:
            output = _pick(by_connector[plan.mutation.connector], plan.id + ":output").id
        fixtures.append(
            QueryFixture(
                query_id=plan.id,
                input_record_ids=inputs,
                output_record_id=output,
                injected_failure=plan.mutation.injected_failure,
            )
        )
    return QueryDrivenCorpus(
        plan=list(plans),
        connector_data=dataset,
        fixtures=fixtures,
        strategy="planned",
        exhaustive_space=query_space().exhaustive,
    )


def build_query_driven_corpus(
    world: World,
    *,
    strategy: Literal["covering", "exhaustive"] = "covering",
    strength: int = 2,
    limit: int | None = None,
) -> QueryDrivenCorpus:
    plans = plan_query_set(
        world, strategy=strategy, strength=strength, limit=limit
    )
    result = generate_from_query_plan(world, plans)
    return result.model_copy(
        update={
            "strategy": strategy,
            "strength": strength if strategy == "covering" else None,
        }
    )


def query_space_size() -> int:
    return math.prod(len(axis.values) for axis in query_space().axes)
