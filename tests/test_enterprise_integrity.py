"""Faults and grounding must survive planning, materialization and execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorError
from worldloom.enterprise_corpus import (
    EnterpriseCorpus,
    QueryFixture,
    StateOverride,
    TraceCall,
    materialize_corpus,
    score_trace,
    validate_corpus,
)
from worldloom.enterprise_failures import build_query_emulator
from worldloom.enterprise_io import export_corpus, load_exported_corpus
from worldloom.enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from worldloom.enterprise_rows import runtime_records
from worldloom.enterprise_runner import RunnerConfig, execute_query
from worldloom.enterprise_simulator import ConnectorSimulator
from worldloom.world import World


def query(failure: str = "none", operation: str = "update") -> PlannedEnterpriseQuery:
    return PlannedEnterpriseQuery(
        id=f"integrity-{failure}-{operation}", workflow="incident-followup",
        query="Read the incident evidence, save its report and verify the result.",
        dimensions={"failure": failure},
        generation=GenerationRequirement(
            process="service_management",
            source_requirements=(SourceRequirement(connector="servicenow", entity="incident"),),
            mutation=MutationRequirement(connector="sharepoint", entity="file", operation=operation,
                output_format="docx", preexisting_record=operation == "update"),
            state_overrides=() if failure == "none" else (failure,),
        ),
        expected_dag=(
            {"id": "read", "connector": "servicenow", "entity": "incident", "kind": "read", "depends_on": []},
            {"id": "transform", "connector": "model", "entity": "docx", "kind": "generate", "depends_on": ["read"]},
            {"id": "write", "connector": "sharepoint", "entity": "file", "kind": operation, "depends_on": ["transform"]},
            {"id": "verify", "connector": "sharepoint", "entity": "file", "kind": "readback", "depends_on": ["write"]},
        ),
    )


def corpus_for(*queries: PlannedEnterpriseQuery) -> EnterpriseCorpus:
    return materialize_corpus(World.load(Path("examples/retail-close")), queries)


@pytest.mark.parametrize("operation", ("create", "upsert"))
def test_create_does_not_inherit_another_querys_update_destination(operation: str) -> None:
    from worldloom.connector_eval_runtime import run_eval_row
    from worldloom.enterprise_rows import compile_row

    created, updated = query("partial_write", operation), query(operation="update")
    corpus = corpus_for(created, updated)
    create_fixture, update_fixture = corpus.fixtures
    assert create_fixture.destination_record_id is None
    assert create_fixture.overrides[0].record_id is None
    assert update_fixture.destination_record_id is not None
    records = runtime_records(corpus.connector_data.records)
    result = run_eval_row(compile_row(created, create_fixture, records), records)
    assert result.grade["status"] == "behavior", result.grade
    writes = {rid for span in result.spans for rid in span.writes}
    assert len(writes) == 1
    assert update_fixture.destination_record_id not in writes


@pytest.mark.parametrize("failure", ["permission_denied", "version_conflict", "partial_write"])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_materialized_destination_failures_block_the_named_write(failure: str, operation: str) -> None:
    corpus = corpus_for(query(failure, operation))
    fixture = corpus.fixtures[0]
    override = fixture.overrides[0]
    assert override.connector == "sharepoint"
    assert override.record_id == fixture.destination_record_id
    assert not validate_corpus(corpus)
    result = asyncio.run(execute_query(corpus.queries[0], fixture, RunnerConfig(), ConnectorSimulator(corpus).invoke))
    assert result.finding == "node write failed"
    assert result.calls[0].succeeded, "injection must not block the earlier source read"
    assert result.outputs["write"]["error"] == ("denied" if failure == "permission_denied" else failure)
    assert "verify" not in result.outputs
    healthy = corpus_for(query(operation=operation))
    successful = asyncio.run(execute_query(healthy.queries[0], healthy.fixtures[0], RunnerConfig(), ConnectorSimulator(healthy).invoke))
    assert successful.completed


@pytest.mark.parametrize("failure", ["ambiguous_join", "stale_source", "missing_stable_id"])
def test_materialized_source_failures_name_a_source_record(failure: str) -> None:
    corpus = corpus_for(query(failure))
    fixture = corpus.fixtures[0]
    override = fixture.overrides[0]
    assert override.connector == "servicenow"
    assert override.record_id in fixture.input_record_ids["servicenow:incident"]
    emulator = build_query_emulator(load_connector_definition("servicenow"), runtime_records(corpus.connector_data.records),
        overrides=fixture.overrides, mutation_nodes=corpus.queries[0].expected_dag, query_id=fixture.query_id)
    record = emulator.records[override.record_id]
    if failure == "ambiguous_join":
        assert len(emulator.records) == 1 + sum(r.connector == "servicenow" for r in corpus.connector_data.records)
    elif failure == "stale_source":
        assert record.get("version", record.get("fields", {}).get("version")) == 0
    else:
        result = asyncio.run(execute_query(corpus.queries[0], fixture, RunnerConfig(), ConnectorSimulator(corpus).invoke))
        assert result.finding == "node read failed"
        assert "write" not in result.outputs
        assert score_trace(corpus.queries[0], result.calls, fixture=fixture).failure_handling == 1.0


def test_foreign_override_record_is_refused_instead_of_silently_ignored() -> None:
    corpus = corpus_for(query("permission_denied"))
    fixture = corpus.fixtures[0]
    broken = fixture.overrides[0].model_copy(update={"record_id": fixture.input_record_ids["servicenow:incident"][0]})
    with pytest.raises(ValueError, match="targets absent sharepoint record"):
        build_query_emulator(load_connector_definition("sharepoint"), runtime_records(corpus.connector_data.records),
            overrides=(broken,), mutation_nodes=corpus.queries[0].expected_dag)


def test_node_scoped_create_denial_preserves_reads_on_same_connector() -> None:
    corpus = corpus_for(query("permission_denied"))
    fixture = corpus.fixtures[0]
    records = runtime_records(corpus.connector_data.records)
    nodes = (
        {"id": "source", "server": "sharepoint", "entity": "file", "op": "read"},
        {"id": "save", "server": "sharepoint", "entity": "file", "op": "create"},
    )
    emulator = build_query_emulator(load_connector_definition("sharepoint"), records,
        overrides=(StateOverride(kind="permission_denied", connector="sharepoint"),), mutation_nodes=nodes)
    assert emulator.call("get_file", id=fixture.destination_record_id, _node="source")
    with pytest.raises(ConnectorError) as error:
        emulator.call("create_file", entity="docx", name="report", _node="save")
    assert error.value.code == 403


def test_expected_facts_are_exact_sorted_union_and_roundtrip(tmp_path: Path) -> None:
    corpus = corpus_for(query())
    fixture = corpus.fixtures[0]
    by_id = {record.id: record for record in corpus.connector_data.records}
    expected = tuple(sorted({fact for values in fixture.input_record_ids.values() for rid in values for fact in by_id[rid].fact_ids}))
    assert expected
    assert fixture.expected_fact_ids == expected
    export_corpus(corpus, tmp_path)
    assert load_exported_corpus(tmp_path).fixtures[0].expected_fact_ids == expected


def test_provenance_requires_the_expected_facts_and_successful_evidence_reads() -> None:
    planned = query()
    fixture = QueryFixture(query_id=planned.id, input_record_ids={"servicenow:incident": ("source",)},
        destination_record_id=None, overrides=(), expected_side_effects=(), expected_fact_ids=("F1", "F2"))
    call = TraceCall(id="read", connector="servicenow", entity="incident", operation="read", record_id="source", fact_ids=("F1", "F2"))
    assert score_trace(planned, (call,), fixture=fixture).provenance == 1.0
    assert score_trace(planned, (call.model_copy(update={"fact_ids": ("F1",)}),), fixture=fixture).provenance == 0.5
    for update in ({"fact_ids": ()}, {"fact_ids": ("wrong",)}, {"record_id": "other"}, {"succeeded": False}, {"connector": "model"}):
        assert score_trace(planned, (call.model_copy(update=update),), fixture=fixture).provenance == 0.0
    padded = score_trace(planned, (call.model_copy(update={"fact_ids": ("F1", "F2", "wrong")}),), fixture=fixture)
    assert padded.provenance == 0.6667
    assert "unexpected facts ['wrong']" in padded.findings
    assert score_trace(planned, (call,)).provenance == 0.0
    assert score_trace(query("permission_denied"), ()).failure_handling == 1.0


def test_validate_reports_unanswerable_placeholder_without_changing_default_materialization() -> None:
    planned = query()
    source = SourceRequirement(connector="servicenow", entity="change_request")
    planned = planned.model_copy(update={"generation": planned.generation.model_copy(update={"source_requirements": (source,)})})
    world = World.load(Path("examples/retail-close"))
    corpus = materialize_corpus(world, (planned,))
    assert any("carries no fact (servicenow:change_request)" in finding for finding in validate_corpus(corpus))
    with pytest.raises(ValueError, match="missing_source"):
        materialize_corpus(world, (planned,), strict_sources=True)


def test_simulate_reports_each_cause_and_continues_after_harness_error(tmp_path: Path) -> None:
    good, blocked, source_failure, broken = query(), query("permission_denied"), query("missing_stable_id"), query("version_conflict")
    bad_dag = (dict(broken.expected_dag[0], connector="no-such-connector"), *broken.expected_dag[1:])
    broken = broken.model_copy(update={"expected_dag": bad_dag})
    corpus = corpus_for(good, blocked, source_failure, broken)
    export_corpus(corpus, tmp_path)
    result = CliRunner().invoke(app, ["enterprise-evals", "simulate", str(tmp_path)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert {key: report[key] for key in ("completed", "blocked_at_designed_write", "stopped_before_failure_point", "raised")} == {
        "completed": 1, "blocked_at_designed_write": 1, "stopped_before_failure_point": 1, "raised": 1,
    }
    assert report["results"][1]["finding"] == "node write failed"
    assert report["results"][2]["finding"] == "node read failed"
    assert "no-such-connector" in report["results"][3]["finding"]


def operational_corpus() -> EnterpriseCorpus:
    from worldloom import MonthEndClose, RetailWorld
    from worldloom.enterprise_sdk import EnterpriseEvalHarness
    from worldloom.synthesis import (
        IncidentRule,
        Simulator,
        operational_profile,
        retail,
        with_parameters,
    )

    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    simulation = Simulator(with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15}))
    corpus, _ = EnterpriseEvalHarness.from_world(world).with_scenario(operational_profile("retail")).with_operational_data(
        simulation, IncidentRule(table="inventory", signal="lost", title="Stock availability"), include_world_records=False,
    ).take(2).build()
    return corpus


def test_operational_evidence_is_pinned_without_impersonating_world_facts() -> None:
    from worldloom.enterprise_evidence import observation_evidence

    corpus = operational_corpus()
    assert not validate_corpus(corpus)
    fixture = corpus.fixtures[0]
    assert not fixture.expected_fact_ids
    assert fixture.expected_evidence_ids and all(evidence.startswith("SYNOBS:") for evidence in fixture.expected_evidence_ids)
    by_id = {record.id: record for record in corpus.connector_data.records}
    calls = tuple(
        TraceCall(id=f"read-{index}", connector=record.connector, operation="read", entity=record.entity,
            record_id=rid, evidence_ids=observation_evidence(record.fields)[0])
        for index, rid in enumerate(sorted({rid for ids in fixture.input_record_ids.values() for rid in ids}))
        for record in (by_id[rid],)
    )
    assert score_trace(corpus.queries[0], calls, fixture=fixture).provenance == 1.0
    wrong_namespace = tuple(call.model_copy(update={"fact_ids": call.evidence_ids, "evidence_ids": ()}) for call in calls)
    assert score_trace(corpus.queries[0], wrong_namespace, fixture=fixture).provenance == 0.0
    assert score_trace(corpus.queries[0], (), fixture=fixture).provenance == 0.0


@pytest.mark.parametrize("damage", ["digest", "scope", "missing_history", "extra_source", "changed_value", "removed_observation"])
def test_operational_provenance_rejects_malformed_or_tampered_history(damage: str) -> None:
    from copy import deepcopy

    corpus = operational_corpus()
    selected = next(iter(corpus.fixtures[0].input_record_ids.values()))[0]
    record = next(record for record in corpus.connector_data.records if record.id == selected)
    fields = deepcopy(record.fields)
    provenance = fields["synthesis_provenance"]
    if damage == "digest":
        provenance["recipe_digest"] = "present-but-not-a-digest"
    elif damage == "scope":
        provenance["scope"] = "macro_reconciliation"
    elif damage == "missing_history":
        fields["history"] = []
    elif damage == "extra_source":
        provenance["source_record_ids"].append("ROW-INVENTED")
    elif damage == "changed_value":
        fields["history"][0]["values"]["lost"] += 1
    else:
        fields["history"].pop()
        provenance["source_record_ids"].pop()
    records = [item.model_copy(update={"fields": fields}) if item.id == selected else item for item in corpus.connector_data.records]
    damaged = corpus.model_copy(update={"connector_data": corpus.connector_data.model_copy(update={"records": records})})
    findings = validate_corpus(damaged)
    assert findings, damage
    if damage == "changed_value":
        assert any("differs from pinned observations" in finding for finding in findings)


@pytest.mark.parametrize("failure", ["permission_denied", "version_conflict", "partial_write", "missing_stable_id"])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_compiled_failures_grade_the_exact_stage_and_block_only_its_descendants(failure: str, operation: str) -> None:
    from worldloom.connector_eval_runtime import run_eval_row
    from worldloom.enterprise_rows import compile_row

    corpus = corpus_for(query(failure, operation))
    records = runtime_records(corpus.connector_data.records)
    row = compile_row(corpus.queries[0], corpus.fixtures[0], records)
    result = run_eval_row(row, records)
    expected_node = "read" if failure == "missing_stable_id" else "write"
    assert next(span for span in result.spans if span.error).node == expected_node
    assert result.grade["status"] == "behavior", result.grade
    assert not any(span.node == "verify" for span in result.spans)
    write_spans = [span for span in result.spans if span.writes]
    if failure == "partial_write":
        assert write_spans
        assert write_spans[0].error["kind"] == "partial_write"
        assert all(fid in result.post_state for span in write_spans for fid in span.writes)
    else:
        assert not write_spans


def test_partial_write_commits_state_but_cannot_satisfy_an_unrelated_target_or_continue() -> None:
    from dataclasses import replace

    from worldloom.connector_eval_runtime import run_eval_row
    from worldloom.connector_trace import grade_trace
    from worldloom.enterprise_rows import compile_row

    corpus = corpus_for(query("partial_write"))
    records = runtime_records(corpus.connector_data.records)
    row = compile_row(corpus.queries[0], corpus.fixtures[0], records)
    result = run_eval_row(row, records)
    failed = next(span for span in result.spans if span.error)
    wrong = tuple(replace(span, writes=("wrong-record",)) if span is failed else span for span in result.spans)
    assert "failure_target_mismatch:write" in grade_trace(wrong, row, post_state=result.post_state)["fails"]
    assert "failure_post_state_missing:write" in grade_trace(result.spans, row)["fails"]
    continued = (*result.spans, replace(failed, id="extra", node="verify", error=None))
    assert "executed_after_failure:verify" in grade_trace(continued, row, post_state=result.post_state)["fails"]


def test_destination_denial_cannot_be_bypassed_by_omitting_node_attribution() -> None:
    corpus = corpus_for(query("permission_denied"))
    fixture = corpus.fixtures[0]
    emulator = build_query_emulator(load_connector_definition("sharepoint"), runtime_records(corpus.connector_data.records),
        overrides=fixture.overrides, mutation_nodes=corpus.queries[0].expected_dag)
    for metadata in ({}, {"_node": "another-node"}):
        with pytest.raises(ConnectorError) as error:
            emulator.call("update_file", id=fixture.destination_record_id, fields={"changed": True}, **metadata)
        assert error.value.kind == "denied"
    assert not any(span.writes for span in emulator.trace)


def test_standalone_score_cli_can_supply_the_expected_fixture(tmp_path: Path) -> None:
    corpus = corpus_for(query())
    result = asyncio.run(execute_query(corpus.queries[0], corpus.fixtures[0], RunnerConfig(), ConnectorSimulator(corpus).invoke))
    query_path, fixture_path, trace_path = (tmp_path / name for name in ("query.json", "fixture.json", "trace.json"))
    query_path.write_text(corpus.queries[0].model_dump_json())
    fixture_path.write_text(corpus.fixtures[0].model_dump_json())
    trace_path.write_text(json.dumps([call.model_dump(mode="json") for call in result.calls]))
    response = CliRunner().invoke(app, ["enterprise-evals", "score", str(query_path), str(trace_path), "--fixture", str(fixture_path)])
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["provenance"] == 1.0


def test_multiple_required_sources_are_all_read_in_both_runtimes() -> None:
    from worldloom.connector_data import ConnectorProjectionRegistry, ConnectorRecord
    from worldloom.connector_eval_runtime import run_eval_row
    from worldloom.enterprise_rows import compile_row

    world = World.load(Path("examples/retail-close"))
    planned = query()
    planned = planned.model_copy(update={"generation": planned.generation.model_copy(update={
        "source_requirements": (SourceRequirement(connector="servicenow", entity="incident", minimum=2),),
    })})
    actual_facts = [fact.id for fact in world.facts[:2]]
    projections = ConnectorProjectionRegistry({
        "servicenow": lambda world: [ConnectorRecord(id=f"source-{index}", external_id=f"INC{index}",
            connector="servicenow", entity="incident", title=f"Incident {index}", fields={"sys_id": f"native-{index}"},
            fact_ids=[fact]) for index, fact in enumerate(actual_facts)],
        "sharepoint": lambda world: [],
    })
    corpus = materialize_corpus(world, (planned,), projections=projections, strict_sources=True)
    assert len(corpus.fixtures[0].input_record_ids["servicenow:incident"]) == 2
    legacy = asyncio.run(execute_query(planned, corpus.fixtures[0], RunnerConfig(), ConnectorSimulator(corpus).invoke))
    assert legacy.completed
    assert score_trace(planned, legacy.calls, fixture=corpus.fixtures[0]).provenance == 1.0
    records = runtime_records(corpus.connector_data.records)
    compiled = run_eval_row(compile_row(planned, corpus.fixtures[0], records), records)
    assert compiled.grade["status"] == "ok", compiled.grade
    assert {rid for span in compiled.spans if span.node == "read" for rid in span.reads} == {"source-0", "source-1"}


def test_validate_rejects_fact_oracle_drift_and_legacy_unpinned_fixtures() -> None:
    corpus = corpus_for(query())
    for expected in ((), ("invented",)):
        modified = corpus.model_copy(update={"fixtures": (corpus.fixtures[0].model_copy(update={"expected_fact_ids": expected}),)})
        assert any("differ from pinned expected_fact_ids" in finding for finding in validate_corpus(modified))


def test_read_then_write_same_record_preserves_the_designed_write_failure_point() -> None:
    corpus = corpus_for(query("permission_denied"))
    fixture = corpus.fixtures[0]
    emulator = build_query_emulator(load_connector_definition("sharepoint"), runtime_records(corpus.connector_data.records),
        overrides=fixture.overrides, mutation_nodes=corpus.queries[0].expected_dag)
    assert emulator.call("get_file", id=fixture.destination_record_id, _node="source")
    with pytest.raises(ConnectorError) as error:
        emulator.call("update_file", id=fixture.destination_record_id, fields={"state": "closed"}, _node="write")
    assert error.value.kind == "denied"
    assert emulator.trace[0].error is None


def test_expected_failure_does_not_excuse_another_error_at_the_same_node() -> None:
    from dataclasses import replace

    from worldloom.connector_eval_runtime import run_eval_row
    from worldloom.connector_trace import grade_trace
    from worldloom.enterprise_rows import compile_row

    corpus = corpus_for(query("permission_denied"))
    records = runtime_records(corpus.connector_data.records)
    row = compile_row(corpus.queries[0], corpus.fixtures[0], records)
    result = run_eval_row(row, records)
    denied = next(span for span in result.spans if span.error)
    broken = (*result.spans, replace(denied, id="additional", error={"kind": "timeout", "code": 504}))
    assert "unexpected_error:write" in grade_trace(broken, row, post_state=result.post_state)["fails"]
