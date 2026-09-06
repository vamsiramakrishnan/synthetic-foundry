"""Materialize query-driven connector fixtures and score execution traces."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from pydantic import Field

from .connector_data import (
    ConnectorDataset,
    ConnectorProjectionRegistry,
    ConnectorRecord,
    generate_connector_data,
)
from .enterprise_queries import PlannedEnterpriseQuery
from .ids import content_key
from .models import Model

if TYPE_CHECKING:
    from .world import World


class StateOverride(Model):
    kind: str
    connector: str
    record_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class QueryFixture(Model):
    query_id: str
    input_record_ids: dict[str, tuple[str, ...]]
    destination_record_id: str | None
    overrides: tuple[StateOverride, ...]
    expected_side_effects: tuple[str, ...]


class EnterpriseCorpus(Model):
    queries: tuple[PlannedEnterpriseQuery, ...]
    connector_data: ConnectorDataset
    fixtures: tuple[QueryFixture, ...]


def _override(kind: str, query: PlannedEnterpriseQuery, record_ids: Mapping[str, tuple[str, ...]]) -> StateOverride:
    connector = query.generation.mutation.connector
    first = next((ids[0] for ids in record_ids.values() if ids), None)
    details_by_kind: dict[str, dict[str, Any]] = {
        "ambiguous_join": {"duplicate_candidate": first, "resolution": "human_review"},
        "missing_stable_id": {"remove_field": "stable_id", "resolution": "skip_and_report"},
        "permission_denied": {"principal": "requesting_actor", "access": "denied"},
        "partial_write": {"fail_after": 1, "rollback": False},
        "stale_source": {"version_delta": -1, "authoritative_copy_available": True},
        "version_conflict": {"etag": "newer-than-read", "expected_status": 409},
    }
    details = details_by_kind[kind]
    return StateOverride(kind=kind, connector=connector, record_id=first, details=details)


def _entity_matches(connector: str, requested: str, actual: str) -> bool:
    """Alias-aware: a source role asking for a ``file`` is met by a ``docx``.

    File connectors project one record per artifact and format, under the
    definition's entity for that format; the role vocabulary still says
    ``file``, which the definition resolves through its alias.
    """

    if requested == actual:
        return True
    from .connector_definition import REFERENCE_CONNECTORS, load_connector_definition

    if connector not in REFERENCE_CONNECTORS:
        return False
    try:
        return load_connector_definition(connector).entity_matches(requested, actual)
    except KeyError:
        return False


def materialize_corpus(
    world: World,
    queries: Iterable[PlannedEnterpriseQuery],
    *,
    projections: ConnectorProjectionRegistry | None = None,
    strict_sources: bool = False,
) -> EnterpriseCorpus:
    planned = tuple(queries)
    needed = tuple(sorted({requirement.connector for query in planned for requirement in query.generation.source_requirements} | {query.generation.mutation.connector for query in planned}))
    data = generate_connector_data(
        world, connectors=needed, projections=projections
    )
    records = list(data.records)
    stable_fields = {
        (capability.connector, capability.entity): capability.stable_id_field
        for capability in data.capabilities
    }
    required_pairs = sorted({(requirement.connector, requirement.entity) for query in planned for requirement in query.generation.source_requirements})
    for connector, entity in required_pairs:
        if any(record.connector == connector and _entity_matches(connector, entity, record.entity)
               for record in records):
            continue
        if strict_sources:
            raise ValueError(f"missing_source: {connector}:{entity}; generate operational evidence before planning this query")
        record_id = content_key("query-required-record", connector, entity, world.company.id)
        stable_field = stable_fields.get((connector, entity), "stable_id")
        records.append(ConnectorRecord(id=record_id, connector=connector, entity=entity, external_id=record_id, title=f"{world.company.name} {entity.replace('_', ' ')}", fields={"company_id": world.company.id, "period": world.period, stable_field: record_id, "generated_for_query_requirements": True}))
    destinations: dict[tuple[str, str], str] = {}
    for query in planned:
        mutation = query.generation.mutation
        if not mutation.preexisting_record:
            continue
        key = (mutation.connector, mutation.entity)
        if key in destinations:
            continue
        record_id = content_key("query-destination-record", *key, world.company.id)
        destinations[key] = record_id
        records.append(
            ConnectorRecord(
                id=record_id,
                connector=mutation.connector,
                entity=mutation.entity,
                external_id=record_id,
                title=f"Existing {mutation.entity.replace('_', ' ')} for {world.company.name}",
                fields={
                    stable_fields.get(
                        (mutation.connector, mutation.entity), "stable_id"
                    ): record_id,
                    "version": 1,
                    "etag": content_key("etag", record_id, "1"),
                    "manual_content": "Preserve this manually authored content.",
                },
            )
        )
    data = ConnectorDataset(capabilities=data.capabilities, records=records)
    fixtures: list[QueryFixture] = []
    for query in planned:
        inputs: dict[str, tuple[str, ...]] = {}
        for requirement in query.generation.source_requirements:
            matches = tuple(record.id for record in data.records if record.connector == requirement.connector and record.entity == requirement.entity)
            if strict_sources and len(matches) < requirement.minimum:
                raise ValueError(f"insufficient_sources: {requirement.connector}:{requirement.entity} needs {requirement.minimum}, found {len(matches)}")
            inputs[f"{requirement.connector}:{requirement.entity}"] = matches[: max(requirement.minimum, 3)]
        mutation = query.generation.mutation
        destination_id = destinations.get((mutation.connector, mutation.entity))
        overrides = tuple(_override(kind, query, inputs) for kind in query.generation.state_overrides)
        effects = (f"{mutation.operation}:{mutation.connector}:{mutation.entity}", f"verify:{mutation.connector}:{mutation.entity}")
        fixtures.append(QueryFixture(query_id=query.id, input_record_ids=inputs, destination_record_id=destination_id, overrides=overrides, expected_side_effects=effects))
    return EnterpriseCorpus(queries=planned, connector_data=data, fixtures=tuple(fixtures))


class TraceCall(Model):
    id: str
    connector: str
    operation: str
    entity: str
    depends_on: tuple[str, ...] = ()
    record_id: str | None = None
    fact_ids: tuple[str, ...] = ()
    succeeded: bool = True


class ScoreReport(Model):
    query_id: str
    total: float
    dag_order: float
    required_calls: float
    write_verification: float
    provenance: float
    idempotency: float
    failure_handling: float
    findings: tuple[str, ...] = ()


def score_trace(query: PlannedEnterpriseQuery, calls: Iterable[TraceCall]) -> ScoreReport:
    trace = tuple(calls)
    positions = {call.id: index for index, call in enumerate(trace)}
    findings: list[str] = []
    expected = query.expected_dag
    matched: dict[str, TraceCall] = {}
    for node in expected:
        match = next((call for call in trace if call.connector == node["connector"] and call.entity == node["entity"] and (call.operation == node["kind"] or node["connector"] == "model")), None)
        if match is not None:
            matched[node["id"]] = match
        else:
            findings.append(f"missing {node['id']} ({node['connector']}.{node['kind']})")
    valid_edges = 0
    edges = 0
    for node in expected:
        for dependency in node.get("depends_on", ()):
            edges += 1
            if dependency in matched and node["id"] in matched and positions[matched[dependency].id] < positions[matched[node["id"]].id]:
                valid_edges += 1
            else:
                findings.append(f"dependency {dependency} must precede {node['id']}")
    dag_order = valid_edges / edges if edges else 1.0
    required_calls = len(matched) / len(expected) if expected else 1.0
    writes = [call for call in trace if call.connector == query.generation.mutation.connector and call.operation == query.generation.mutation.operation]
    verifies = [call for call in trace if call.connector == query.generation.mutation.connector and call.operation in {"read", "readback", "cross_system"}]
    failure = query.dimensions.get("failure", "none")
    blocking_failures = {"missing_stable_id", "permission_denied", "version_conflict"}
    successful_writes = [call for call in writes if call.succeeded]
    if failure in blocking_failures:
        failure_handling = 1.0 if not successful_writes else 0.0
        write_verification = failure_handling
    elif failure == "partial_write":
        failure_handling = 1.0 if writes and any(not call.succeeded for call in writes) else 0.0
        write_verification = failure_handling
    else:
        failure_handling = 1.0
        write_verification = 1.0 if writes and verifies and positions[writes[-1].id] < positions[verifies[-1].id] else 0.0
    provenance = sum(bool(call.fact_ids or call.record_id) for call in trace) / len(trace) if trace else 0.0
    write_keys = [(call.connector, call.operation, call.entity, call.record_id) for call in writes]
    idempotency = 1.0 if len(write_keys) == len(set(write_keys)) else 0.0
    total = 0.25 * dag_order + 0.25 * required_calls + 0.15 * write_verification + 0.10 * provenance + 0.10 * idempotency + 0.15 * failure_handling
    return ScoreReport(query_id=query.id, total=round(total, 4), dag_order=round(dag_order, 4), required_calls=round(required_calls, 4), write_verification=write_verification, provenance=round(provenance, 4), idempotency=idempotency, failure_handling=failure_handling, findings=tuple(findings))


def validate_corpus(corpus: EnterpriseCorpus) -> tuple[str, ...]:
    findings: list[str] = []
    record_ids = {record.id for record in corpus.connector_data.records}
    if len(record_ids) != len(corpus.connector_data.records):
        findings.append("connector data: duplicate internal record ids")
    stable_fields = {
        (capability.connector, capability.entity): capability.stable_id_field
        for capability in corpus.connector_data.capabilities
    }
    for record in corpus.connector_data.records:
        stable_field = stable_fields.get((record.connector, record.entity))
        if stable_field and not record.fields.get(stable_field):
            findings.append(
                f"connector record {record.id}: missing stable field {stable_field}"
            )
    fixtures = {fixture.query_id: fixture for fixture in corpus.fixtures}
    for query in corpus.queries:
        fixture = fixtures.get(query.id)
        if fixture is None:
            findings.append(f"query {query.id}: missing fixture")
            continue
        for requirement in query.generation.source_requirements:
            key = f"{requirement.connector}:{requirement.entity}"
            if len(fixture.input_record_ids.get(key, ())) < requirement.minimum:
                findings.append(f"query {query.id}: unmet source requirement {key}")
            dangling = set(fixture.input_record_ids.get(key, ())) - record_ids
            if dangling:
                findings.append(
                    f"query {query.id}: dangling input records {sorted(dangling)}"
                )
        if (
            fixture.destination_record_id is not None
            and fixture.destination_record_id not in record_ids
        ):
            findings.append(
                f"query {query.id}: dangling destination record {fixture.destination_record_id}"
            )
        if query.generation.state_overrides and not fixture.overrides:
            findings.append(f"query {query.id}: failure dimension has no state override")
    return tuple(findings)
