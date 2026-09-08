"""Admission precedes coverage, and exported proofs keep their executed inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from worldloom.connector_eval_runtime import run_eval_row
from worldloom.enterprise_corpus import validate_corpus
from worldloom.enterprise_io import load_exported_corpus
from worldloom.enterprise_qualification import digest, qualify_queries
from worldloom.enterprise_rows import runtime_records
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.enterprise_specs import ScenarioProfile
from worldloom.world import World


@pytest.fixture(scope="module")
def harness():
    scenario = ScenarioProfile.model_validate({
        "name": "qualified-incidents", "industry": "retail",
        "company_description": "Retail incident response.",
        "connectors": ["servicenow", "sharepoint"], "workflows": ["incident_pack"],
        "additional_workflows": [{
            "name": "incident_pack", "purpose": "incident pack", "process": "service_management",
            "sources": [{"connector": "servicenow", "entities": ["incident"]}],
            "destinations": [{"connector": "sharepoint", "entities": ["file"],
                              "operations": ["create"], "formats": ["docx"]}],
            "content_actions": ["extract"], "audiences": ["analyst", "manager"],
            "topologies": ["chain"], "verification": ["readback"],
            "prompt_template": "Prepare {purpose} for {audience}. Use {sources}. {failure_instruction}",
        }],
        "coverage": {"connector_counts": [1], "failures": ["none", "permission_denied"]},
    })
    return EnterpriseEvalHarness.from_world(World.load("examples/retail-close")).with_scenario(scenario)


def test_bounded_pool_exhaustion_and_output_cap_have_honest_coverage(harness) -> None:
    result = harness.take(1).qualify(pool_size=4)
    assert result.report.pool_count == result.report.eligible_count == 4
    assert result.report.pool_exhausted
    assert result.report.selected_count == 1
    assert result.report.eligible_coverage.complete
    assert not result.report.selected_coverage.complete
    assert result.report.selected_coverage.covered_interactions < result.report.requested_interactions
    bounded = harness.take(1).qualify(pool_size=2, max_selected=2)
    assert bounded.report.pool_count == bounded.report.selected_count == 2
    assert not bounded.report.pool_exhausted
    assert bounded.report.max_selected == 2


def test_designed_failure_is_eligible_when_its_actual_assertions_pass(harness) -> None:
    result = harness.qualify(pool_size=4)
    failures = {query.id for query in result.corpus.queries if query.generation.state_overrides}
    assert failures
    assert not result.report.refusals
    assert all(proof.grade["fails"] == [] for proof in result.proofs)
    assert all(any(span["error"] is not None for span in proof.spans)
               for proof in result.proofs if proof.query_id in failures)


def test_missing_source_refusal_preserves_requested_coverage(harness) -> None:
    queries, _ = harness.exhaustive().plan()
    valid = queries[0]
    missing = valid.model_copy(update={
        "id": "missing-source",
        "dimensions": {**valid.dimensions, "source_entities": "servicenow:change_request"},
        "generation": valid.generation.model_copy(update={"source_requirements": (
            valid.generation.source_requirements[0].model_copy(update={"entity": "change_request"}),
        )}),
    })
    result = qualify_queries(harness.world, (valid, missing), pool_size=2, pool_exhausted=True)
    assert result.report.eligible_query_ids == (valid.id,)
    assert result.report.refusals[0].query_id == missing.id
    assert result.report.refusals[0].stage == "preflight"
    assert not result.report.eligible_coverage.complete
    assert result.pool == (valid, missing)


def test_independent_validation_rejects_evidence_without_facts(harness, monkeypatch) -> None:
    import worldloom.enterprise_qualification as qualification

    materialize = qualification.materialize_corpus

    def invalid(*args, **kwargs):
        corpus = materialize(*args, **kwargs)
        data = corpus.connector_data.model_copy(update={"records": [
            record.model_copy(update={"fact_ids": []}) for record in corpus.connector_data.records
        ]})
        return corpus.model_copy(update={"connector_data": data})

    monkeypatch.setattr(qualification, "materialize_corpus", invalid)
    result = harness.qualify(pool_size=2)
    assert result.report.eligible_count == 0
    assert all(refusal.stage == "validation" for refusal in result.report.refusals)
    assert any("carries no fact" in refusal.detail for refusal in result.report.refusals)


def test_global_dataset_corruption_refuses_every_query(harness, monkeypatch) -> None:
    import worldloom.enterprise_qualification as qualification

    materialize = qualification.materialize_corpus

    def duplicate(*args, **kwargs):
        corpus = materialize(*args, **kwargs)
        records = corpus.connector_data.records
        data = corpus.connector_data.model_copy(update={"records": [*records, records[0]]})
        return corpus.model_copy(update={"connector_data": data})

    monkeypatch.setattr(qualification, "materialize_corpus", duplicate)
    result = harness.qualify(pool_size=2)
    assert result.report.shared_findings == ("connector data: duplicate internal record ids",)
    assert result.report.eligible_count == 0
    assert {refusal.query_id for refusal in result.report.refusals} == {query.id for query in result.pool}


def test_assertion_failure_is_not_admitted_just_because_the_row_executed(harness, monkeypatch) -> None:
    import worldloom.enterprise_qualification as qualification

    compile_rows = qualification.compile_rows

    def false_assertion(*args, **kwargs):
        compiled = compile_rows(*args, **kwargs)
        for row in compiled.rows:
            row["assertions"].append({"type": "reads_contain", "node": "read-0", "records": ["NOT-A-REAL-RECORD"]})
        return compiled

    monkeypatch.setattr(qualification, "compile_rows", false_assertion)
    result = harness.qualify(pool_size=2)
    assert result.report.eligible_count == 0
    assert {refusal.code for refusal in result.report.refusals} == {"assertions_failed"}


def test_export_preserves_exact_batch_and_proof_identities_without_rematerializing(harness, monkeypatch, tmp_path: Path) -> None:
    import worldloom.enterprise_qualification as qualification

    materialize = qualification.materialize_corpus
    batches = []

    def counted(*args, **kwargs):
        corpus = materialize(*args, **kwargs)
        batches.append(corpus)
        return corpus

    monkeypatch.setattr(qualification, "materialize_corpus", counted)
    result = harness.take(1).qualify(pool_size=4)
    assert len(batches) == 5  # Four strict preflights and one shared materialization.
    assert result.corpus.connector_data is batches[-1].connector_data
    output = result.export(tmp_path / "qualified")
    assert len(batches) == 5
    loaded = load_exported_corpus(output)
    assert loaded == result.corpus
    assert validate_corpus(loaded) == ()
    rows = [json.loads(line) for line in (output / "qualified-rows.jsonl").read_text().splitlines()]
    proofs = [json.loads(line) for line in (output / "proofs.jsonl").read_text().splitlines()]
    manifest = json.loads((output / "manifest.json").read_text())
    assert digest(loaded.connector_data) == manifest["connector_data_digest"]
    assert digest(loaded) == manifest["corpus_digest"]
    assert digest(rows) == manifest["rows_digest"]
    assert digest(proofs) == manifest["proofs_digest"]
    assert digest(json.loads((output / "qualification.json").read_text())) == manifest["qualification_digest"]
    assert digest([query.model_dump(mode="json") for query in result.pool]) == manifest["pool_digest"]
    records = runtime_records(loaded.connector_data.records)
    for row, proof, query, fixture in zip(rows, proofs, loaded.queries, loaded.fixtures, strict=True):
        assert proof["query_digest"] == digest(query)
        assert proof["fixture_digest"] == digest(fixture)
        assert proof["row_digest"] == digest(row)
        assert run_eval_row(row, records).grade == proof["grade"]


def test_export_overwrite_is_limited_to_prior_qualifications(harness, tmp_path: Path) -> None:
    result = harness.qualify(pool_size=2)
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError, match="not an enterprise qualification"):
        result.export(other, overwrite=True)
    assert (other / "keep.txt").read_text() == "keep"
    output = result.export(tmp_path / "qualified")
    with pytest.raises(FileExistsError, match="not empty"):
        result.export(output)
    (output / "stale.txt").write_text("stale")
    result.export(output, overwrite=True)
    assert not (output / "stale.txt").exists()


@pytest.mark.parametrize("target", ("data", "row", "proof", "pool", "report"))
def test_changed_inputs_or_proofs_cannot_be_exported(harness, tmp_path: Path, target: str) -> None:
    result = harness.qualify(pool_size=2)
    if target == "data":
        result.corpus.connector_data.records[0].fields["tampered"] = True
    elif target == "row":
        result.rows[0]["tampered"] = True
    elif target == "proof":
        result.proofs[0].grade["tampered"] = True
    elif target == "pool":
        result.pool[0].dimensions["audience"] = "tampered"
    else:
        result = replace(result, report=result.report.model_copy(update={"selected_count": 999}))
    with pytest.raises(ValueError, match="changed after execution"):
        result.export(tmp_path / "tampered")
    assert not (tmp_path / "tampered").exists()


def test_world_coherence_is_checked_before_any_materialization(harness, monkeypatch) -> None:
    import worldloom.enterprise_qualification as qualification
    from worldloom.validate import CoherenceError

    damaged = replace(harness.world, _facts=())
    assert not damaged.validate().ok

    def forbidden(*args, **kwargs):
        pytest.fail("materialized an invalid World")

    monkeypatch.setattr(qualification, "materialize_corpus", forbidden)
    with pytest.raises(CoherenceError):
        replace(harness, world=damaged).qualify(pool_size=2)


def test_declared_file_format_requires_actual_record_format_evidence(harness) -> None:
    queries, _ = harness.exhaustive().plan()
    query = queries[0]
    source = query.generation.source_requirements[0]
    unsupported = query.model_copy(update={"dimensions": {**query.dimensions, "input_formats": "pdf"}, "generation": query.generation.model_copy(update={
        "source_requirements": (source.model_copy(update={"input_format": "pdf"}),),
    })})
    result = qualify_queries(harness.world, (unsupported,), pool_size=1, pool_exhausted=True)
    assert result.report.eligible_count == 0
    assert result.report.refusals[0].code == "source_format_unsupported"


def test_invented_but_consistently_pinned_fact_ids_are_refused(harness, monkeypatch) -> None:
    import worldloom.enterprise_qualification as qualification

    materialize = qualification.materialize_corpus

    def invented(*args, **kwargs):
        corpus = materialize(*args, **kwargs)
        data = corpus.connector_data.model_copy(update={"records": [
            record.model_copy(update={"fact_ids": ["FACT-INVENTED"]}) for record in corpus.connector_data.records
        ]})
        fixtures = tuple(fixture.model_copy(update={"expected_fact_ids": ("FACT-INVENTED",)}) for fixture in corpus.fixtures)
        return corpus.model_copy(update={"connector_data": data, "fixtures": fixtures})

    monkeypatch.setattr(qualification, "materialize_corpus", invented)
    result = harness.qualify(pool_size=2)
    assert result.report.eligible_count == 0
    assert {refusal.code for refusal in result.report.refusals} == {"source_fact_unknown"}


def test_concrete_document_record_cannot_satisfy_a_pdf_request(harness, monkeypatch) -> None:
    import worldloom.enterprise_qualification as qualification

    materialize = qualification.materialize_corpus

    def document(*args, **kwargs):
        corpus = materialize(*args, **kwargs)
        data = corpus.connector_data.model_copy(update={"records": [
            record.model_copy(update={"fields": {**record.fields, "format": "docx"}})
            for record in corpus.connector_data.records
        ]})
        return corpus.model_copy(update={"connector_data": data})

    monkeypatch.setattr(qualification, "materialize_corpus", document)
    query = harness.exhaustive().plan()[0][0]
    query = query.model_copy(update={"dimensions": {**query.dimensions, "input_formats": "pdf"}, "generation": query.generation.model_copy(update={
        "source_requirements": (query.generation.source_requirements[0].model_copy(update={"input_format": "pdf"}),),
    })})
    result = qualify_queries(harness.world, (query,), pool_size=1, pool_exhausted=True)
    assert result.report.eligible_count == 0
    assert {refusal.code for refusal in result.report.refusals} == {"source_format_mismatch"}


def test_native_format_witness_uses_persisted_world_artifacts(harness, tmp_path: Path) -> None:
    from worldloom import RetailWorld
    from worldloom.scenarios import MonthEndClose

    query = harness.exhaustive().plan()[0][0]
    query = query.model_copy(update={"dimensions": {**query.dimensions, "input_formats": "markdown"}, "generation": query.generation.model_copy(update={
        "source_requirements": (query.generation.source_requirements[0].model_copy(update={"input_format": "markdown"}),),
    })})
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03", include_operational_incident=True)).render("markdown")
    world.export(tmp_path / "world")
    loaded = World.load(tmp_path / "world")
    result = qualify_queries(loaded, (query,), pool_size=1, pool_exhausted=True)
    assert result.report.eligible_count == 1, result.report.refusals
    assert not loaded._rendered
    assert result.proofs[0].native_artifacts
    for witness in result.proofs[0].native_artifacts:
        payload = (loaded.root / witness.path).read_bytes()
        assert witness.format == "markdown"
        assert witness.size_bytes == len(payload)
        assert witness.payload_digest == hashlib.sha256(payload).hexdigest()
    result.export(tmp_path / "qualification")
    proof = json.loads((tmp_path / "qualification" / "proofs.jsonl").read_text())
    assert proof["native_artifacts"] == [item.model_dump(mode="json") for item in result.proofs[0].native_artifacts]
    absent = replace(loaded, root=None)
    refused = qualify_queries(absent, (query,), pool_size=1, pool_exhausted=True)
    assert refused.report.eligible_count == 0
    assert {refusal.code for refusal in refused.report.refusals} == {"source_format_unsupported"}


def test_unknown_executor_status_does_not_admit_a_row(harness, monkeypatch) -> None:
    import worldloom.enterprise_qualification as qualification

    execute = qualification.run_eval_row

    def unknown_status(*args, **kwargs):
        result = execute(*args, **kwargs)
        return replace(result, grade={**result.grade, "status": "unsupported", "fails": []})

    monkeypatch.setattr(qualification, "run_eval_row", unknown_status)
    result = harness.qualify(pool_size=2)
    assert result.report.eligible_count == 0
    assert {refusal.stage for refusal in result.report.refusals} == {"execution"}


def _operational(vertical: str = "retail"):
    from worldloom import BankingWorld, RetailWorld
    from worldloom.synthesis import (
        IncidentRule,
        Simulator,
        banking,
        retail,
        with_parameters,
    )
    from worldloom.synthesis.connectors import operational_profile

    if vertical == "retail":
        world = RetailWorld(seed=8128).build()
        program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
        rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    else:
        world = BankingWorld(seed=8128).build()
        program = banking(borrowers=8, ticks=8)
        rule = IncidentRule(table="loan", signal="arrears", title="Payment arrears")
    scenario = operational_profile(vertical)
    scenario = scenario.model_copy(update={"coverage": scenario.coverage.model_copy(update={"failures": ("none",)})})
    return (EnterpriseEvalHarness.from_world(world).with_scenario(scenario)
            .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False))


@pytest.mark.parametrize(("vertical", "case_count"), (("retail", 17), ("banking", 9)))
def test_operational_case_coverage_survives_selection_and_cap(vertical: str, case_count: int) -> None:
    harness = _operational(vertical).with_operational_case_binding()
    result = harness.qualify(pool_size=24)
    assert result.report.eligible_count == 24, result.report.refusals
    assert result.report.requested_cases == case_count
    assert result.report.eligible_case_coverage.complete
    assert result.report.selected_case_coverage.complete
    assert result.report.selected_case_coverage.covered_interactions == case_count
    assert all("operational_case_ids" in query.dimensions for query in result.corpus.queries)
    capped = harness.take(1).qualify(pool_size=24)
    assert capped.report.selected_count == 1
    assert capped.report.selected_case_coverage.covered_interactions == 1
    assert len(capped.report.selected_case_coverage.holes) == case_count - 1
    assert not capped.report.selected_coverage.complete


def test_case_representatives_survive_identical_semantic_dimensions() -> None:
    from worldloom.connector_data import generate_connector_data
    from worldloom.synthesis.connectors import (
        OPERATIONAL_CASE_DIMENSIONS,
        bind_case_query,
    )

    harness = _operational()
    original = harness.exhaustive().take(1).plan()[0][0]
    queries = tuple(original.model_copy(update={"id": f"case-query-{index}"}) for index in range(3))
    data = generate_connector_data(harness.world, projections=harness.projections)

    def bind(query, ordinal):
        return bind_case_query(query, data.records, ordinal=ordinal)

    result = qualify_queries(harness.world, queries, pool_size=3, pool_exhausted=True,
                             projections=harness.projections, binder=bind)
    assert result.report.eligible_count == result.report.selected_count == 3
    assert result.report.selected_case_coverage.covered_interactions == 3
    assert result.report.excluded_dimensions == tuple(sorted(OPERATIONAL_CASE_DIMENSIONS))
    capped = qualify_queries(harness.world, queries, pool_size=3, pool_exhausted=True,
                             projections=harness.projections, binder=bind, max_selected=2)
    assert capped.report.selected_coverage.complete  # All three have identical semantics.
    assert capped.report.selected_case_coverage.covered_interactions == 2
    assert not capped.report.selected_case_coverage.complete


def test_case_binding_collects_one_refusal_per_unsupported_query(harness) -> None:
    result = harness.with_operational_case_binding().qualify(pool_size=2)
    assert result.report.eligible_count == 0
    assert len(result.report.refusals) == 2
    assert {refusal.stage for refusal in result.report.refusals} == {"binding"}
    assert {refusal.query_id for refusal in result.report.refusals} == {query.id for query in result.pool}


def test_malformed_case_metadata_is_a_visible_per_query_refusal(harness) -> None:
    query = harness.exhaustive().plan()[0][0]
    malformed = query.model_copy(update={"id": "malformed-case", "dimensions": {
        **query.dimensions, "operational_case_binding": "case-cohort/v1", "operational_case_ids": "broken",
    }})
    result = qualify_queries(harness.world, (query, malformed), pool_size=2, pool_exhausted=True)
    assert result.report.eligible_query_ids == (query.id,)
    assert len(result.report.refusals) == 1
    assert result.report.refusals[0].query_id == malformed.id
    assert result.report.refusals[0].stage == "preflight"


@pytest.mark.parametrize(("dimension", "value"), (
    ("input_formats", "pdf"), ("source_set", "drive"), ("source_entities", "drive:file"),
    ("destination", "jira"), ("destination_entity", "issue"), ("operation", "update"),
    ("output_format", "xlsx"), ("failure", "version_conflict"),
))
def test_coverage_labels_cannot_disagree_with_executable_requirements(harness, dimension: str, value: str) -> None:
    query = harness.exhaustive().plan()[0][0]
    drifted = query.model_copy(update={"id": "drifted", "dimensions": {**query.dimensions, dimension: value}})
    result = qualify_queries(harness.world, (query, drifted), pool_size=2, pool_exhausted=True)
    assert result.report.eligible_query_ids == (query.id,)
    assert {refusal.code for refusal in result.report.refusals} == {"dimension_contract_mismatch"}
    assert not result.report.eligible_coverage.complete
