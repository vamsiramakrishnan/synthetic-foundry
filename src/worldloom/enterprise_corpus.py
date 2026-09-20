"""Materialize query-driven connector fixtures and score execution traces."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from pydantic import Field

from .connector_data import (
    ConnectorDataset,
    ConnectorProjectionRegistry,
    ConnectorRecord,
    generate_connector_data,
)
from .enterprise_evidence import carries_evidence, observation_evidence
from .enterprise_grounding import entity_matches
from .enterprise_queries import PlannedEnterpriseQuery, SourceRequirement
from .ids import content_key
from .models import Model
from .predicates import evaluate

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
    expected_fact_ids: tuple[str, ...] = ()
    expected_evidence_ids: tuple[str, ...] = ()


class EnterpriseCorpus(Model):
    queries: tuple[PlannedEnterpriseQuery, ...]
    connector_data: ConnectorDataset
    fixtures: tuple[QueryFixture, ...]


def _override(
    kind: str,
    query: PlannedEnterpriseQuery,
    record_ids: Mapping[str, tuple[str, ...]],
    destination_record_id: str | None,
) -> StateOverride:
    # Source defects belong to evidence. Write defects belong to the mutation's
    # record (or its create operation when no record exists yet). Crossing those
    # namespaces made destination ACLs name a foreign source id and never fire.
    source_side = kind in {"ambiguous_join", "missing_stable_id", "stale_source"}
    source = next(((key, ids[0]) for key, ids in sorted(record_ids.items()) if ids), None)
    connector = query.generation.mutation.connector
    target = destination_record_id
    if source_side and source is not None:
        connector = source[0].split(":", 1)[0]
        target = source[1]
    details_by_kind: dict[str, dict[str, Any]] = {
        "ambiguous_join": {"duplicate_candidate": target, "resolution": "human_review"},
        "missing_stable_id": {"remove_field": "stable_id", "resolution": "skip_and_report"},
        "permission_denied": {"principal": "requesting_actor", "access": "denied"},
        "partial_write": {"fail_after": 1, "rollback": False},
        "stale_source": {"version_delta": -1, "authoritative_copy_available": True},
        "version_conflict": {"etag": "newer-than-read", "expected_status": 409},
    }
    return StateOverride(kind=kind, connector=connector, record_id=target, details=details_by_kind[kind])


def source_matches(requirement: SourceRequirement, record: ConnectorRecord) -> bool:
    """The same source contract used by materialization and independent review."""
    if (record.connector != requirement.connector
            or not entity_matches(requirement.connector, requirement.entity, record.entity)):
        return False
    if requirement.predicate is None:
        return True
    # Envelope identity cannot be shadowed by caller-controlled native fields.
    fields = {**record.fields, "id": record.id, "external_id": record.external_id,
              "title": record.title, "connector": record.connector, "entity": record.entity}
    return evaluate(requirement.predicate, fields)


def operational_case_ids(query: PlannedEnterpriseQuery) -> tuple[str, ...]:
    """Read the opt-in cohort contract, never infer one from matching records."""
    if "operational_case_binding" not in query.dimensions:
        return ()
    if query.dimensions["operational_case_binding"] != "case-cohort/v1":
        raise ValueError("unsupported operational case binding")
    try:
        cases = json.loads(query.dimensions["operational_case_ids"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid operational_case_ids") from error
    if (not isinstance(cases, list) or not 1 <= len(cases) <= 128
            or not all(isinstance(case, str) and case for case in cases)
            or cases != sorted(set(cases))):
        raise ValueError("operational_case_ids must be one to 128 distinct sorted case IDs")
    return tuple(cases)


def operational_record_case_id(record: ConnectorRecord) -> str:
    """Verify a case label against the episode that its observations identify."""
    from .synthesis.compiler import digest

    evidence, findings = observation_evidence(record.fields)
    if findings or not evidence:
        raise ValueError(f"{record.id}: {findings or ('no operational observations',)}")
    provenance = record.fields["synthesis_provenance"]
    expected = digest(["episode/v1", provenance["recipe_digest"], provenance["trigger"],
                       record.fields["history"][0]["record_id"]])
    if record.fields.get("case_id") != expected:
        raise ValueError(f"{record.id}: case_id does not identify its observation episode")
    return expected


def _select_sources(
    records: list[ConnectorRecord], minimum: int, cases: tuple[str, ...],
) -> tuple[str, ...]:
    # Evidence first. The validator accepts a selected record only when
    # `carries_evidence` holds, and a pool of thirty-eight issues with one
    # fact-less record put that record first for twenty queries, each of which
    # the validator then refused. The sort is stable over the existing order
    # (the pool's own order here, record id below), so a pool whose leading
    # records all carry evidence selects exactly what it selected before. A
    # record without evidence is taken only when no evidence-bearing one is left.
    if not cases:
        ranked = sorted(records, key=lambda record: not carries_evidence(record))
        return tuple(record.id for record in ranked[:minimum])
    # A connector may carry several messages for one case. Picking a plain
    # prefix could meet the record count while silently omitting another case.
    chosen: list[str] = []
    ordered = sorted(records, key=lambda record: (not carries_evidence(record), record.id))
    for case in cases:
        match = next((record for record in ordered if record.fields.get("case_id") == case), None)
        if match is None:
            raise ValueError(f"missing_case_source: {case}")
        operational_record_case_id(match)
        chosen.append(match.id)
    for record in ordered:
        if len(chosen) >= minimum:
            break
        if record.id not in chosen:
            chosen.append(record.id)
    return tuple(chosen)


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
    # How many records a pair must supply is the largest minimum any planned row
    # asks of it, not one. A shape that maps over its sources (`map_read`) or
    # needs a witness for both branches (`conditional`) raises that minimum to
    # two, and topping the pool up to exactly one left those rows materializing
    # and then refusing to compile — which is why they were opt-in.
    demanded: dict[tuple[str, str], int] = {}
    for query in planned:
        for requirement in query.generation.source_requirements:
            key = (requirement.connector, requirement.entity)
            demanded[key] = max(demanded.get(key, 1), requirement.minimum)
    for connector, entity in required_pairs:
        matching = [record for record in records
                    if record.connector == connector and entity_matches(connector, entity, record.entity)]
        present = len(matching)
        shortfall = demanded.get((connector, entity), 1) - present
        if shortfall <= 0:
            continue
        # A row that filters its sources by a predicate must read real evidence:
        # a filler record satisfies the count and not the claim, so the honest
        # answer is still a refusal that names what is short.
        if strict_sources or any(requirement.predicate is not None for query in planned
                                 for requirement in query.generation.source_requirements
                                 if (requirement.connector, requirement.entity) == (connector, entity)):
            raise ValueError(
                f"missing_source: {connector}:{entity} has {present} record(s) and a planned row"
                f" needs {demanded[(connector, entity)]}; generate operational evidence"
                " before planning this query"
            )
        # A tripwire, where a filler record used to be minted. The filler met
        # the count and carried no fact, so the validator refused it and the
        # whole export aborted at the last step. The planner now refuses a
        # source the world cannot ground before a row is planned over it, so a
        # query reaching this line is a planning defect, and the refusal names
        # the query and the source instead of hiding the defect in a record.
        short = sorted({
            query.id for query in planned for requirement in query.generation.source_requirements
            if (requirement.connector, requirement.entity) == (connector, entity) and requirement.minimum > present
        })
        grounded = sum(carries_evidence(record) for record in matching)
        named = ", ".join(short[:3]) + (f" and {len(short) - 3} more" if len(short) > 3 else "")
        raise ValueError(
            f"ungroundable_source: query {named} needs {demanded[(connector, entity)]} {connector}:{entity}"
            f" record(s) for evidence and this world has {present} ({grounded} carrying evidence);"
            " plan against the world's groundable inventory instead of minting evidence"
        )
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
    from .enterprise_fields import enrich_required_fields

    records = enrich_required_fields(records, planned)
    data = ConnectorDataset(capabilities=data.capabilities, records=records)
    by_id = {record.id: record for record in data.records}
    destination_ids = set(destinations.values())
    fixtures: list[QueryFixture] = []
    for query in planned:
        inputs: dict[str, tuple[str, ...]] = {}
        cases = operational_case_ids(query)
        for requirement in query.generation.source_requirements:
            matches = [record for record in data.records
                       if record.id not in destination_ids and source_matches(requirement, record)
                       and (not cases or record.fields.get("case_id") in cases)]
            if (strict_sources or requirement.predicate is not None or cases) and len(matches) < requirement.minimum:
                raise ValueError(f"insufficient_sources: {requirement.connector}:{requirement.entity} needs {requirement.minimum}, found {len(matches)}")
            inputs[f"{requirement.connector}:{requirement.entity}"] = _select_sources(matches, requirement.minimum, cases)
        mutation = query.generation.mutation
        # The shared record pool also contains targets required by other rows.
        # A create must not inherit an update row's preexisting destination.
        destination_id = (
            destinations.get((mutation.connector, mutation.entity))
            if mutation.preexisting_record else None
        )
        overrides = tuple(_override(kind, query, inputs, destination_id) for kind in query.generation.state_overrides)
        effects = (f"{mutation.operation}:{mutation.connector}:{mutation.entity}", f"verify:{mutation.connector}:{mutation.entity}")
        expected_facts = tuple(sorted({fact for ids in inputs.values() for rid in ids for fact in by_id[rid].fact_ids}))
        expected_evidence = tuple(sorted({evidence for ids in inputs.values() for rid in ids for evidence in observation_evidence(by_id[rid].fields)[0]}))
        fixtures.append(QueryFixture(query_id=query.id, input_record_ids=inputs, destination_record_id=destination_id, overrides=overrides, expected_side_effects=effects, expected_fact_ids=expected_facts, expected_evidence_ids=expected_evidence))
    return EnterpriseCorpus(queries=planned, connector_data=data, fixtures=tuple(fixtures))


class TraceCall(Model):
    id: str
    connector: str
    operation: str
    entity: str
    depends_on: tuple[str, ...] = ()
    record_id: str | None = None
    record_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
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


def score_trace(
    query: PlannedEnterpriseQuery,
    calls: Iterable[TraceCall],
    *,
    fixture: QueryFixture | None = None,
) -> ScoreReport:
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
    if fixture is not None and fixture.query_id != query.id:
        raise ValueError(f"fixture {fixture.query_id} does not belong to query {query.id}")
    expected_facts = set(fixture.expected_fact_ids) if fixture is not None else set()
    expected_evidence = set(fixture.expected_evidence_ids) if fixture is not None else set()
    source_records = {
        (key.split(":", 1)[0], rid)
        for key, ids in (fixture.input_record_ids.items() if fixture is not None else ())
        for rid in ids
    }
    observed_facts = {
        fact
        for call in trace
        if call.succeeded and call.operation in {"read", "get", "search", "extract", "download", "list"} and all((call.connector, rid) in source_records for rid in (call.record_ids or (call.record_id,)))
        for fact in call.fact_ids
    }
    observed_evidence = {
        evidence for call in trace
        if call.succeeded and call.operation in {"read", "get", "search", "extract", "download", "list"} and all((call.connector, rid) in source_records for rid in (call.record_ids or (call.record_id,)))
        for evidence in call.evidence_ids
    }
    # Distinct namespaces prevent operational observations from impersonating
    # World facts. Padding either set with invented ids lowers precision.
    wanted = {("fact", value) for value in expected_facts} | {("observation", value) for value in expected_evidence}
    observed = {("fact", value) for value in observed_facts} | {("observation", value) for value in observed_evidence}
    provenance = len(wanted & observed) / len(wanted | observed) if wanted else 0.0
    if fixture is None:
        findings.append("provenance unverified: expected fact fixture was not supplied")
    elif not wanted:
        findings.append("provenance unverified: evidence carries no expected facts or observations")
    if expected_facts - observed_facts:
        findings.append(f"missing expected facts {sorted(expected_facts - observed_facts)}")
    if observed_facts - expected_facts:
        findings.append(f"unexpected facts {sorted(observed_facts - expected_facts)}")
    if expected_evidence - observed_evidence:
        findings.append(f"missing expected observations {sorted(expected_evidence - observed_evidence)}")
    if observed_evidence - expected_evidence:
        findings.append(f"unexpected observations {sorted(observed_evidence - expected_evidence)}")
    write_keys = [(call.connector, call.operation, call.entity, call.record_id) for call in writes]
    idempotency = 1.0 if len(write_keys) == len(set(write_keys)) else 0.0
    total = 0.25 * dag_order + 0.25 * required_calls + 0.15 * write_verification + 0.10 * provenance + 0.10 * idempotency + 0.15 * failure_handling
    return ScoreReport(query_id=query.id, total=round(total, 4), dag_order=round(dag_order, 4), required_calls=round(required_calls, 4), write_verification=write_verification, provenance=round(provenance, 4), idempotency=idempotency, failure_handling=failure_handling, findings=tuple(findings))


def validate_corpus(corpus: EnterpriseCorpus) -> tuple[str, ...]:
    findings: list[str] = []
    by_id = {record.id: record for record in corpus.connector_data.records}
    record_ids = set(by_id)
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
        try:
            cases = operational_case_ids(query)
        except ValueError as error:
            findings.append(f"query {query.id}: {error}")
            cases = ()
        for requirement in query.generation.source_requirements:
            key = f"{requirement.connector}:{requirement.entity}"
            selected = fixture.input_record_ids.get(key, ())
            if len(set(selected)) < requirement.minimum:
                findings.append(f"query {query.id}: unmet source requirement {key}")
            if len(set(selected)) != len(selected):
                findings.append(f"query {query.id}: duplicate input records {key}")
            dangling = set(fixture.input_record_ids.get(key, ())) - record_ids
            if dangling:
                findings.append(
                    f"query {query.id}: dangling input records {sorted(dangling)}"
                )
            for identifier in selected:
                source_record = by_id.get(identifier)
                if source_record is None:
                    continue
                try:
                    matches = source_matches(requirement, source_record)
                except ValueError as error:
                    findings.append(f"query {query.id}: invalid source predicate {key}: {error}")
                    continue
                if not matches:
                    findings.append(f"query {query.id}: source predicate mismatch {key}: {identifier}")
                if cases:
                    try:
                        operational_record_case_id(source_record)
                    except ValueError as error:
                        findings.append(f"query {query.id}: invalid operational case {key}: {error}")
            if cases and {by_id[rid].fields.get("case_id") for rid in selected if rid in by_id} != set(cases):
                findings.append(f"query {query.id}: source case cohort mismatch {key}")
        observed_facts: set[str] = set()
        observed_evidence: set[str] = set()
        for key, inputs in sorted(fixture.input_record_ids.items()):
            for rid in inputs:
                evidence_record = by_id.get(rid)
                if evidence_record is None:
                    continue
                observed_facts.update(evidence_record.fact_ids)
                evidence_ids, evidence_findings = observation_evidence(evidence_record.fields)
                observed_evidence.update(evidence_ids)
                if not carries_evidence(evidence_record):
                    findings.append(f"query {query.id}: evidence {rid} carries no fact ({key})")
                for finding in evidence_findings:
                    findings.append(f"query {query.id}: evidence {rid}: {finding}")
        if observed_facts != set(fixture.expected_fact_ids):
            findings.append(f"query {query.id}: evidence facts differ from pinned expected_fact_ids; rematerialize legacy fixtures")
        if observed_evidence != set(fixture.expected_evidence_ids):
            findings.append(f"query {query.id}: operational evidence differs from pinned observations")
        if (
            fixture.destination_record_id is not None
            and fixture.destination_record_id not in record_ids
        ):
            findings.append(
                f"query {query.id}: dangling destination record {fixture.destination_record_id}"
            )
        for override in fixture.overrides:
            if override.record_id is not None:
                override_record = by_id.get(override.record_id)
                if override_record is None or override_record.connector != override.connector:
                    findings.append(f"query {query.id}: override {override.kind} targets absent {override.connector} record {override.record_id}")
        if query.generation.state_overrides and not fixture.overrides:
            findings.append(f"query {query.id}: failure dimension has no state override")
    return tuple(findings)
