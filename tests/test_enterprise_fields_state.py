"""Outcome and field contracts survive planning, export, execution and tampering."""

from __future__ import annotations

from dataclasses import replace

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_definition import ConnectorFieldDefinition
from worldloom.connector_eval_runtime import run_eval_row
from worldloom.connector_trace import grade_trace
from worldloom.enterprise_corpus import materialize_corpus
from worldloom.enterprise_io import export_corpus, load_exported_corpus
from worldloom.enterprise_queries import plan_queries
from worldloom.enterprise_rows import compile_row, runtime_records
from worldloom.enterprise_specs import (
    ContentAction,
    CoverageProfile,
    DestinationRole,
    Operation,
    ScenarioProfile,
    SourceRole,
    SpecRegistry,
    WorkflowSpec,
    builtin_registry,
)
from worldloom.world import World

FIELD = ConnectorFieldDefinition(
    id="u_control_tier", canonical="control.tier", name="Control Tier",
    field_type="option", options=("Standard", "Restricted"),
    fill_rate=0.0, query_name="u_control_tier", payload_name="u_control_tier",
)


def _registry(*, required=True, destination="change_request", target_state=None, target_state_field="state"):
    original = builtin_registry()
    connector = original.connectors["servicenow"]
    connector = connector.model_copy(update={"entities": tuple(
        entity.model_copy(update={"field_definitions": (FIELD,)}) if entity.name == "incident" else entity
        for entity in connector.entities
    )})
    workflow = WorkflowSpec(
        name="controlled_change", purpose="controlled change review",
        sources=(SourceRole(connector="servicenow", entities=("incident",), required_fields=(FIELD.id,) if required else ()),),
        destinations=(DestinationRole(connector="servicenow", entities=(destination,), operations=(Operation.UPDATE,), target_state=target_state, target_state_field=target_state_field),),
        content_actions=(ContentAction.SUMMARIZE,), audiences=("operations",),
        topologies=("chain",), verification=("readback",),
        prompt_template="Review {sources}. {action_instruction} {output_label} in {destination}.",
    )
    return SpecRegistry((connector,), (workflow,), original.processes.values())


def _build(**kwargs):
    world = World.load("examples/retail-close")
    queries, report = plan_queries(world, registry=_registry(**kwargs), profile=CoverageProfile(strengths=1, connector_counts=(1,), failures=("none",)))
    corpus = materialize_corpus(world, tuple(queries))
    assert report and report.complete
    assert len(corpus.queries) == 1
    return corpus


def test_checked_state_is_executed_and_perturbing_expectation_fails():
    corpus = _build(required=False)
    query, fixture = corpus.queries[0], corpus.fixtures[0]
    assert query.generation.mutation.target_state == "assess"
    assert "'assess'" in query.query
    row = compile_row(query, fixture, runtime_records(corpus.connector_data.records))
    assertion = next(item for item in row["assertions"] if item["type"] == "state_equals")
    assert assertion["fixture"] == fixture.destination_record_id
    result = run_eval_row(row, runtime_records(corpus.connector_data.records))
    assert result.grade["status"] == "ok", result.grade
    assert result.post_state[fixture.destination_record_id]["state"] == "assess"
    assertion["state"] = "scheduled"
    changed = grade_trace(result.spans, row, post_state=result.post_state)
    assert "state_mismatch:write" in changed["fails"]


def test_checked_state_survives_an_authored_partial_write_error():
    planned = _build(required=False).queries[0]
    planned = planned.model_copy(update={
        "dimensions": {**planned.dimensions, "failure": "partial_write"},
        "generation": planned.generation.model_copy(update={"state_overrides": ("partial_write",)}),
    })
    corpus = materialize_corpus(World.load("examples/retail-close"), (planned,))
    records = runtime_records(corpus.connector_data.records)
    row = compile_row(planned, corpus.fixtures[0], records)
    result = run_eval_row(row, records)
    assert result.grade["status"] == "behavior", result.grade
    write = next(span for span in result.spans if span.node == "write")
    assert write.error["kind"] == "partial_write"
    assert write.writes == (corpus.fixtures[0].destination_record_id,)
    assertion = next(item for item in row["assertions"] if item["type"] == "state_equals")
    assertion["state"] = "scheduled"
    grade = grade_trace(result.spans, row, post_state=result.post_state)
    assert "state_mismatch:write" in grade["fails"]


def test_matching_preexisting_state_is_insufficient_without_a_successful_write():
    corpus = _build(required=False)
    row = compile_row(corpus.queries[0], corpus.fixtures[0], runtime_records(corpus.connector_data.records))
    result = run_eval_row(row, runtime_records(corpus.connector_data.records))
    for variant in ("missing", "error", "wrong_target"):
        spans = []
        for span in result.spans:
            if span.node != "write":
                spans.append(span)
            elif variant == "error":
                spans.append(replace(span, error={"code": 403, "kind": "denied"}))
            elif variant == "wrong_target":
                spans.append(replace(span, writes=("another-record",)))
        grade = grade_trace(spans, row, post_state=result.post_state)
        assert "state_not_written:write" in grade["fails"], (variant, grade)


def test_required_fields_reach_values_request_filter_projection_assertion_and_replay(tmp_path):
    corpus = _build()
    query, fixture = corpus.queries[0], corpus.fixtures[0]
    requirement = query.generation.source_requirements[0]
    assert requirement.required_fields == (FIELD.canonical,)
    assert FIELD.canonical in query.query
    inputs = set(fixture.input_record_ids["servicenow:incident"])
    assert inputs
    assert all(record.fields[FIELD.canonical] in FIELD.options for record in corpus.connector_data.records if record.id in inputs)
    export_corpus(corpus, tmp_path)
    reloaded = load_exported_corpus(tmp_path)
    records = runtime_records(reloaded.connector_data.records)
    row = compile_row(reloaded.queries[0], reloaded.fixtures[0], records)
    read = next(node for node in row["expected_dag"]["nodes"] if node["id"] == "read-0")
    assert read["payload"]["fields"] == [FIELD.id]
    assert read["payload"]["predicate"]["where"] == [{"field": FIELD.canonical, "op": "ne", "value": None}]
    result = run_eval_row(row, records)
    assert result.grade["status"] == "ok", result.grade
    assert "connector_definitions" in row
    # Returning the right ids with an unfiltered, broad read does not prove use.
    spans = tuple(replace(span, args={key: value for key, value in span.args.items() if key not in {"predicate", "fields"}}) if span.node == "read-0" else span for span in result.spans)
    grade = grade_trace(spans, row, post_state=result.post_state)
    assert "fields_not_used:read-0" in grade["fails"]
    assert _build().model_dump(mode="json") == corpus.model_dump(mode="json")


def test_field_predicate_excludes_a_record_whose_required_value_was_removed():
    corpus = _build()
    records = list(runtime_records(corpus.connector_data.records))
    row = compile_row(corpus.queries[0], corpus.fixtures[0], records)
    target = corpus.fixtures[0].input_record_ids["servicenow:incident"][0]
    records = [dict(record, **{FIELD.canonical: None}) if record["fid"] == target else record for record in records]
    result = run_eval_row(row, records)
    assert result.grade["status"] == "fail"
    assert target not in {record for span in result.spans if span.node == "read-0" for record in span.reads}


def test_unknown_and_nonqueryable_authored_fields_are_refused():
    registry = _registry()
    workflow = next(iter(registry.workflows.values()))
    role = workflow.sources[0].model_copy(update={"required_fields": ("does_not_exist",)})
    registry.workflows[workflow.name] = workflow.model_copy(update={"sources": (role,)})
    world = World.load("examples/retail-close")
    with pytest.raises(ValueError, match="has no authored definition"):
        plan_queries(world, registry=registry, strategy="exhaustive", limit=1)


def test_authored_profile_reaches_cli_without_a_second_manifest_file(tmp_path):
    registry = _registry()
    profile = ScenarioProfile(
        name="controls", industry="retail", company_description="Retail operations",
        connectors=("servicenow",), workflows=("controlled_change",),
        additional_connectors=tuple(registry.connectors.values()),
        additional_workflows=tuple(registry.workflows.values()),
        coverage=CoverageProfile(strengths=1, connector_counts=(1,), failures=("none",)),
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(profile.model_dump_json())
    output = tmp_path / "queries.jsonl"
    result = CliRunner().invoke(app, ["enterprise-evals", "plan", "examples/retail-close", "--profile", str(profile_path), "--strength", "1", str(output)])
    assert result.exit_code == 0, result.output
    assert FIELD.canonical in output.read_text()


def test_explicit_state_field_checks_an_entity_without_a_workflow():
    registry = _registry(required=False)
    registry.connectors["salesforce"] = builtin_registry().connectors["salesforce"]
    workflow = next(iter(registry.workflows.values()))
    registry.workflows[workflow.name] = workflow.model_copy(update={"destinations": (
        DestinationRole(connector="salesforce", entities=("account",), operations=(Operation.UPDATE,), target_state="reviewed", target_state_field="review_status"),
    )})
    queries, _ = plan_queries(World.load("examples/retail-close"), registry=registry, strategy="exhaustive", profile=CoverageProfile(failures=("none",)), limit=1)
    corpus = materialize_corpus(World.load("examples/retail-close"), tuple(queries))
    records = runtime_records(corpus.connector_data.records)
    row = compile_row(corpus.queries[0], corpus.fixtures[0], records)
    result = run_eval_row(row, records)
    assert result.grade["status"] == "ok", result.grade
    destination = corpus.fixtures[0].destination_record_id
    assert result.post_state[destination]["review_status"] == "reviewed"


def test_required_custom_field_on_an_alias_reaches_native_payload():
    from worldloom.connector_emulator import ConnectorEmulator
    from worldloom.enterprise_fields import (
        query_connector_definitions,
        required_field_payload,
    )

    registry = _registry()
    connector = builtin_registry().connectors["jira"]
    field = FIELD.model_copy(update={"id": "customfield_10499", "payload_name": "customfield_10499", "query_name": "cf[10499]"})
    connector = connector.model_copy(update={"entities": (connector.entities[0].model_copy(update={"field_definitions": (field,), "required_fields": (field.canonical,)}),)})
    registry.connectors["jira"] = connector
    workflow = next(iter(registry.workflows.values()))
    registry.workflows[workflow.name] = workflow.model_copy(update={"sources": (SourceRole(connector="jira", entities=("issue",)),)})
    queries, _ = plan_queries(World.load("examples/retail-close"), registry=registry, strategy="exhaustive", profile=CoverageProfile(failures=("none",)), limit=1)
    corpus = materialize_corpus(World.load("examples/retail-close"), tuple(queries))
    definitions = query_connector_definitions(corpus.queries)
    requirement = corpus.queries[0].generation.source_requirements[0]
    emulator = ConnectorEmulator(definitions["jira"], corpus.connector_data.records)
    response = emulator.call(definitions["jira"].tool_for("issue", "search"), entity="issue", **required_field_payload(requirement, definitions["jira"]))
    assert response["items"]
    assert all(item["fields"][field.id] in field.options for item in response["items"])
    row = compile_row(corpus.queries[0], corpus.fixtures[0], runtime_records(corpus.connector_data.records))
    assert run_eval_row(row, runtime_records(corpus.connector_data.records)).grade["status"] == "ok"


def test_compatibility_simulator_applies_the_same_filter_and_target_state():
    import asyncio

    from worldloom.connectors.enterprise import EnterpriseConnectorRuntime
    from worldloom.enterprise_runner import RunnerConfig, execute_query

    corpus = _build()
    runtime = EnterpriseConnectorRuntime(corpus)
    result = asyncio.run(execute_query(corpus.queries[0], corpus.fixtures[0], RunnerConfig(), runtime.invoke))
    assert result.completed, result.finding
    read_records = result.outputs["read-0"]["records"]
    assert read_records and all(record[FIELD.canonical] in FIELD.options for record in read_records)
    assert all(item[FIELD.id] in FIELD.options for item in result.outputs["read-0"]["payload"]["items"])
    destination = next(record for record in runtime.records if record.id == corpus.fixtures[0].destination_record_id)
    assert destination.fields["state"] == "assess"


def test_nonqueryable_required_field_is_refused_before_planning():
    registry = _registry()
    connector = registry.connectors["servicenow"]
    registry.connectors["servicenow"] = connector.model_copy(update={"entities": tuple(
        entity.model_copy(update={"field_definitions": (FIELD.model_copy(update={"queryable": False}),)}) if entity.name == "incident" else entity
        for entity in connector.entities
    )})
    with pytest.raises(ValueError, match="not queryable"):
        plan_queries(World.load("examples/retail-close"), registry=registry, strategy="exhaustive", limit=1)


@pytest.mark.parametrize(("assertion", "failure"), [("state_equals", "state_unavailable"), ("deleted", "deletion_unverified")])
def test_post_state_assertions_cannot_pass_without_authoritative_state(assertion, failure):
    corpus = _build(required=False)
    row = compile_row(corpus.queries[0], corpus.fixtures[0], runtime_records(corpus.connector_data.records))
    result = run_eval_row(row, runtime_records(corpus.connector_data.records))
    row["assertions"] = [{"type": assertion, "node": "write", "state": "assess", "fixture": corpus.fixtures[0].destination_record_id}]
    grade = grade_trace(result.spans, row)
    assert grade["fails"] == [f"{failure}:write"]


def test_explicit_target_must_be_reachable_from_the_fixture_initial_state():
    with pytest.raises(ValueError, match="not reachable"):
        _build(required=False, target_state="closed")


@pytest.mark.parametrize(("key", "value"), [(FIELD.canonical, "Not an option"), (FIELD.id, 42), (FIELD.id, None)])
def test_invalid_existing_field_values_are_refused_and_preserved(key, value):
    from worldloom.enterprise_fields import enrich_required_fields

    corpus = _build()
    source = next(record for record in corpus.connector_data.records if record.id in corpus.fixtures[0].input_record_ids["servicenow:incident"])
    changed = {name: held for name, held in source.fields.items() if name != FIELD.canonical}
    changed[key] = value
    record = source.model_copy(update={"fields": changed})
    before = record.model_dump(mode="json")
    with pytest.raises(ValueError, match=r"invalid authored value|explicit null value"):
        enrich_required_fields((record,), corpus.queries)
    assert record.model_dump(mode="json") == before


def test_existing_value_cannot_override_a_false_presence_predicate():
    from worldloom.enterprise_fields import enrich_required_fields
    from worldloom.predicates import Predicate

    corpus = _build()
    query = corpus.queries[0]
    source = query.generation.source_requirements[0]
    field = FIELD.model_copy(update={"present_when": Predicate.equalities({"allowed": True})})
    source = source.model_copy(update={"field_definitions": (field,)})
    query = query.model_copy(update={"generation": query.generation.model_copy(update={"source_requirements": (source,)})})
    with pytest.raises(ValueError, match="presence predicate"):
        enrich_required_fields(corpus.connector_data.records, (query,))


def test_conflicting_native_and_canonical_values_are_refused():
    from worldloom.enterprise_fields import enrich_required_fields

    corpus = _build()
    source = next(record for record in corpus.connector_data.records if record.id in corpus.fixtures[0].input_record_ids["servicenow:incident"])
    source = source.model_copy(update={"fields": {**source.fields, FIELD.canonical: FIELD.options[0], FIELD.id: FIELD.options[1]}})
    with pytest.raises(ValueError, match="conflicting canonical and native"):
        enrich_required_fields((source,), corpus.queries)
