"""Real case cohorts remain executable and independently checkable after export."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from worldloom import BankingWorld, RetailWorld
from worldloom.connector_data import (
    ConnectorProjectionRegistry,
    generate_connector_data,
)
from worldloom.connector_eval_runtime import run_eval_row
from worldloom.enterprise_corpus import (
    materialize_corpus,
    operational_case_ids,
    validate_corpus,
)
from worldloom.enterprise_evidence import observation_evidence
from worldloom.enterprise_io import (
    export_corpus,
    export_queries,
    iter_queries,
    load_exported_corpus,
)
from worldloom.enterprise_queries import SourceRequirement
from worldloom.enterprise_rows import compile_rows, runtime_records
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.predicates import (
    AsOf,
    FieldPredicate,
    JoinPredicate,
    Predicate,
    RelativeTime,
)
from worldloom.synthesis import (
    IncidentRule,
    Simulator,
    SynthesisError,
    banking,
    retail,
    with_parameters,
)
from worldloom.synthesis.connectors import (
    OPERATIONAL_CASE_DIMENSIONS,
    bind_case_queries,
    bind_case_query,
    operational_profile,
)


def _operational(vertical: str = "retail", dag_shape: str | None = None):
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
    harness = (EnterpriseEvalHarness.from_world(world).with_scenario(scenario)
               .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
               .exhaustive().take(24))
    if dag_shape:
        harness = harness.with_dag_grammar(dag_shape)
    queries, _ = harness.plan()
    connectors = tuple(sorted({source.connector for query in queries for source in query.generation.source_requirements}
                              | {query.generation.mutation.connector for query in queries}))
    data = generate_connector_data(world, connectors=connectors, projections=harness.projections)
    return harness, queries, data.records


@pytest.mark.parametrize("vertical", ("retail", "banking"))
@pytest.mark.parametrize("dag_shape", (None, "map_read"))
def test_case_binding_increases_coverage_and_reloads_executable(vertical: str, dag_shape: str | None, tmp_path: Path) -> None:
    harness, queries, records = _operational(vertical, dag_shape)
    bound = bind_case_queries(queries, records)
    assert bound == bind_case_queries(queries, reversed(records))
    corpus = materialize_corpus(harness.world, bound, projections=harness.projections, strict_sources=True)
    baseline = materialize_corpus(harness.world, queries, projections=harness.projections, strict_sources=True)
    by_id = {record.id: record for record in corpus.connector_data.records}
    cases = {by_id[rid].fields["case_id"] for fixture in corpus.fixtures for ids in fixture.input_record_ids.values() for rid in ids}
    old_cases = {by_id[rid].fields["case_id"] for fixture in baseline.fixtures for ids in fixture.input_record_ids.values() for rid in ids}
    assert len(cases) > len(old_cases)
    assert len(cases) == (17 if vertical == "retail" else 9)
    for query, original, fixture in zip(bound, queries, corpus.fixtures, strict=True):
        expected = operational_case_ids(query)
        assert len(expected) == (2 if dag_shape == "map_read" else 1)
        assert query.id != original.id
        assert query.dimensions["operational_base_query_id"] == original.id
        assert OPERATIONAL_CASE_DIMENSIONS <= query.dimensions.keys()
        for selected in fixture.input_record_ids.values():
            assert {by_id[rid].fields["case_id"] for rid in selected} == set(expected)
            assert all(by_id[rid].title in query.query for rid in selected)
            assert all(by_id[rid].external_id in query.query for rid in selected if by_id[rid].external_id not in expected)
        assert all(case not in query.query for case in expected)
        assert fixture.expected_evidence_ids
        assert not fixture.expected_fact_ids
    assert validate_corpus(corpus) == ()
    export_corpus(corpus, tmp_path)
    loaded = load_exported_corpus(tmp_path)
    assert loaded == corpus
    assert validate_corpus(loaded) == ()
    runtime = runtime_records(loaded.connector_data.records)
    compiled = compile_rows(loaded.queries, loaded.fixtures, runtime)
    assert compiled.refusals == (), compiled.reasons()
    for row in compiled.rows:
        result = run_eval_row(row, runtime)
        assert result.grade["fails"] == [], (row["id"], result.grade)
        assert all(span.error is None for span in result.spans)


def test_unbound_query_bytes_remain_exact_and_roundtrip(tmp_path: Path) -> None:
    world = RetailWorld(seed=8128).build()
    queries, _ = EnterpriseEvalHarness.from_world(world).with_scenario(operational_profile("retail")).take(3).plan()
    path = tmp_path / "queries.jsonl"
    export_queries(queries, path)
    original = path.read_bytes()
    assert len(original) == 5092
    assert hashlib.sha256(original).hexdigest() == "c3a48c77d2545ea72bb5530e64236b4832445d68fbde13b39416b67691553b4c"
    assert b'"predicate"' not in original
    assert all("predicate" not in source for query in queries for source in query.model_dump()["generation"]["source_requirements"])
    loaded = tuple(iter_queries(path))
    export_queries(loaded, path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("predicate", (
    Predicate(as_of=AsOf()),
    Predicate(joins=(JoinPredicate(field="parent_id", predicate=Predicate()),)),
    Predicate(where=(FieldPredicate(field="opened_at", value=RelativeTime(days=-1)),)),
))
def test_context_dependent_source_predicates_refuse(predicate: Predicate) -> None:
    with pytest.raises(ValueError, match="explicit QueryContext"):
        SourceRequirement(connector="jira", entity="issue", predicate=predicate)


def test_case_budget_and_missing_counterpart_refuse() -> None:
    harness, queries, records = _operational(dag_shape="map_read")
    query = queries[0]
    with pytest.raises(SynthesisError, match="case_binding_budget"):
        bind_case_query(query, records, max_cases=1)
    bound = bind_case_query(query, records)
    with pytest.raises(SynthesisError, match="case_binding_applied"):
        bind_case_query(bound, records)
    source = bound.generation.source_requirements[0]
    case = operational_case_ids(bound)[0]
    remaining = [record for record in records if not (record.connector == source.connector and record.fields.get("case_id") == case)]
    projections = ConnectorProjectionRegistry({name: lambda world, name=name: [record for record in remaining if record.connector == name]
                                               for name in sorted({record.connector for record in records})})
    # Predicate binding forbids fallback sources even without strict_sources.
    with pytest.raises(ValueError, match=r"insufficient_sources|missing_case_source"):
        materialize_corpus(harness.world, (bound,), projections=projections)
    corpus = materialize_corpus(harness.world, (bound,), projections=harness.projections)
    retained = {record.id for record in remaining}
    missing = corpus.model_copy(update={"connector_data": corpus.connector_data.model_copy(update={
        "records": [record for record in corpus.connector_data.records if record.id in retained],
    })})
    assert any("dangling input records" in finding for finding in validate_corpus(missing))
    only_one_case = [record for record in records if record.fields.get("case_id") == case]
    with pytest.raises(SynthesisError, match="insufficient_case_cohort"):
        bind_case_query(query, only_one_case)


def test_wrong_case_substitution_is_rejected_even_when_observations_are_repinned() -> None:
    harness, queries, records = _operational()
    bound = bind_case_query(queries[0], records)
    corpus = materialize_corpus(harness.world, (bound,), projections=harness.projections, strict_sources=True)
    fixture = corpus.fixtures[0]
    by_id = {record.id: record for record in corpus.connector_data.records}
    key, selected = next(iter(fixture.input_record_ids.items()))
    source = by_id[selected[0]]
    wrong = next(record for record in records if record.connector == source.connector and record.entity == source.entity
                 and record.fields["case_id"] != source.fields["case_id"])
    inputs = {**fixture.input_record_ids, key: (wrong.id,)}
    evidence = tuple(sorted({identifier for ids in inputs.values() for rid in ids for identifier in observation_evidence(by_id[rid].fields)[0]}))
    changed = fixture.model_copy(update={"input_record_ids": inputs, "expected_evidence_ids": evidence})
    findings = validate_corpus(corpus.model_copy(update={"fixtures": (changed,)}))
    assert any("source predicate mismatch" in finding for finding in findings)
    assert any("source case cohort mismatch" in finding for finding in findings)
    assert not any("pinned observations" in finding for finding in findings)
    # Relabelling another real episode must not make it the requested case,
    # even when its content-addressed observations were freshly pinned.
    relabelled = wrong.model_copy(update={"fields": {**wrong.fields, "case_id": source.fields["case_id"]}})
    changed_data = corpus.connector_data.model_copy(update={"records": [
        relabelled if record.id == wrong.id else record for record in corpus.connector_data.records
    ]})
    findings = validate_corpus(corpus.model_copy(update={"fixtures": (changed,), "connector_data": changed_data}))
    assert any("case_id does not identify its observation episode" in finding for finding in findings)


def test_binder_rejects_case_label_unrelated_to_real_episode() -> None:
    _, queries, records = _operational()
    source = queries[0].generation.source_requirements[0]
    original = next(record for record in records if record.connector == source.connector and record.entity == source.entity)
    corrupt = original.model_copy(update={"fields": {**original.fields, "case_id": "invented-case"}})
    with pytest.raises(SynthesisError, match="case_id does not identify"):
        bind_case_query(queries[0], [corrupt if record.id == original.id else record for record in records])


def test_generic_predicate_filters_sources_and_cannot_fall_back() -> None:
    harness, queries, _ = _operational()
    query = queries[0]
    sources = tuple(source.model_copy(update={"predicate": Predicate.equalities({"status": "resolved"})})
                    for source in query.generation.source_requirements)
    filtered = query.model_copy(update={"generation": query.generation.model_copy(update={"source_requirements": sources})})
    corpus = materialize_corpus(harness.world, (filtered,), projections=harness.projections)
    by_id = {record.id: record for record in corpus.connector_data.records}
    assert all(by_id[rid].fields["status"] == "resolved" for ids in corpus.fixtures[0].input_record_ids.values() for rid in ids)
    assert validate_corpus(corpus) == ()
    impossible = tuple(source.model_copy(update={"predicate": Predicate.equalities({"case_id": "absent"})}) for source in sources)
    absent = query.model_copy(update={"generation": query.generation.model_copy(update={"source_requirements": impossible})})
    with pytest.raises(ValueError, match="insufficient_sources"):
        materialize_corpus(harness.world, (absent,), projections=harness.projections)
