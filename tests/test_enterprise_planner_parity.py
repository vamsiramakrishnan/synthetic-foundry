"""Real query-first behaviors have one grounded, executable enterprise SDK."""
from __future__ import annotations

from dataclasses import replace

import pytest

from worldloom.connector_eval_runtime import run_eval_row
from worldloom.enterprise_corpus import validate_corpus
from worldloom.enterprise_evidence import carries_evidence
from worldloom.enterprise_rows import compile_rows, runtime_records
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.enterprise_specs import (
    ContentAction,
    CoverageProfile,
    DestinationRole,
    Operation,
    SourceRole,
    SpecRegistry,
    WorkflowSpec,
    builtin_registry,
)
from worldloom.world import World


@pytest.fixture(scope="module")
def world() -> World:
    return World.load("retail-close")


def _registry(count: int = 3, *, formats: tuple[str, ...] = ("docx", "xlsx", "pptx")) -> SpecRegistry:
    original = builtin_registry()
    sources = (("jira", "issue"), ("servicenow", "incident"), ("salesforce", "case"),
               ("confluence", "page"), ("drive", "file"), ("sharepoint", "file"))
    workflow = WorkflowSpec(name="evidence_review", purpose="company evidence review",
        sources=tuple(SourceRole(connector=connector, entities=(entity,)) for connector, entity in sources[:count]),
        destinations=(DestinationRole(connector="sharepoint", entities=("file",),
            operations=(Operation.CREATE, Operation.UPDATE), formats=formats),),
        content_actions=(ContentAction.EXTRACT, ContentAction.COMPARE, ContentAction.RECONCILE, ContentAction.GENERATE),
        audiences=("executive", "analyst"), topologies=("chain",), verification=("readback",),
        prompt_template="Prepare the {period} {purpose} for {company}'s {audience} audience. Use {sources}. "
            "{action_instruction} {output_label} in {destination}. {verification_instruction}.{failure_instruction}")
    needed = {"sharepoint", *(connector for connector, _ in sources[:count])}
    return SpecRegistry((original.connectors[name] for name in sorted(needed)), (workflow,))


def _harness(world: World, count: int = 3) -> EnterpriseEvalHarness:
    return (EnterpriseEvalHarness.from_world(world).with_registry(_registry(count))
        .with_profile(CoverageProfile(name="query-first-parity", strengths=1,
            connector_counts=(count,), failures=("none",))).require_sources())


@pytest.mark.parametrize("strategy", ["covering", "exhaustive"])
def test_query_selection_is_bounded_deterministic_and_precedes_materialization(world: World, strategy: str) -> None:
    harness = _harness(world)
    if strategy == "exhaustive":
        harness = harness.exhaustive()
    complete, complete_report = harness.plan()
    bounded, report = harness.take(5).plan()
    assert bounded == complete[:5]
    assert (bounded, report) == harness.take(5).plan()
    assert len(bounded) == len({query.id for query in bounded}) == 5
    assert all(query.generation.source_requirements for query in bounded)
    if strategy == "covering":
        assert complete_report is not None and complete_report.complete
        assert report is not None and report.truncated and not report.complete
    else:
        assert report is complete_report is None


def test_canonical_dimensions_carry_company_requests_and_explicit_native_formats(world: World) -> None:
    queries, _ = _harness(world).exhaustive().plan()
    assert {query.dimensions["output_format"] for query in queries} == {"docx", "xlsx", "pptx"}
    assert {query.dimensions["operation"] for query in queries} == {"create", "update"}
    assert {query.dimensions["content_action"] for query in queries} == {"extract", "compare", "reconcile", "generate"}
    assert {query.dimensions["audience"] for query in queries} == {"executive", "analyst"}
    for query in queries:
        text = query.query.lower()
        assert world.company.name.lower() in text
        assert " as json" not in text and "mcp" not in text
        assert query.generation.mutation.output_format == query.dimensions["output_format"]
        assert query.generation.mutation.operation == query.dimensions["operation"]
        assert len(query.generation.source_requirements) == 3


@pytest.mark.parametrize("count", [1, 2, 3, 4, 6])
def test_supported_source_cardinalities_bind_real_evidence(world: World, count: int) -> None:
    corpus, _ = _harness(world, count).exhaustive().take(2).build()
    records = {record.id: record for record in corpus.connector_data.records}
    assert len(corpus.queries) == 2
    for query, fixture in zip(corpus.queries, corpus.fixtures, strict=True):
        assert len(query.generation.source_requirements) == len(fixture.input_record_ids) == count
        assert fixture.query_id == query.id
        for identifiers in fixture.input_record_ids.values():
            assert identifiers
            assert all(identifier in records and carries_evidence(records[identifier]) for identifier in identifiers)
    assert validate_corpus(corpus) == ()


def test_materialization_pins_fixture_identities_and_create_update_preconditions(world: World) -> None:
    harness = _harness(world).exhaustive()
    corpus, report = harness.build()
    assert (corpus, report) == harness.build()
    assert corpus.queries == harness.plan()[0]
    records = {record.id: record for record in corpus.connector_data.records}
    assert {query.generation.mutation.operation for query in corpus.queries} == {"create", "update"}
    for query, fixture in zip(corpus.queries, corpus.fixtures, strict=True):
        assert query.id == fixture.query_id
        assert set(identifier for ids in fixture.input_record_ids.values() for identifier in ids) <= records.keys()
        if query.generation.mutation.preexisting_record:
            assert fixture.destination_record_id in records
            assert records[fixture.destination_record_id].fields["manual_content"]
        else:
            assert fixture.destination_record_id is None
        assert fixture.expected_fact_ids
    assert validate_corpus(corpus) == ()


def test_missing_source_evidence_is_refused_without_placeholder_substitution(world: World) -> None:
    empty = replace(world, _facts=(), _events=(), _artifact_irs=(), _artifact_intents=())
    with pytest.raises(ValueError, match="ungroundable_world"):
        _harness(empty).take(5).build()


@pytest.mark.parametrize("shape", ["read_chain", "fan_in", "fan_out", "diamond", "map_read"])
def test_topologies_use_the_executable_grammar_and_grade_actual_traces(world: World, shape: str) -> None:
    # The former planner carried topology labels without executing them. The
    # catalogue compiles source-bound result references and checks actual reads,
    # writes and readback, including every item in a mapped source result.
    harness = (_harness(world, 2).with_registry(_registry(2, formats=("docx",)))
        .with_dag_grammar(shape).exhaustive().take(1))
    corpus, _ = harness.build()
    records = runtime_records(corpus.connector_data.records)
    compiled = compile_rows(corpus.queries, corpus.fixtures, records)
    assert not compiled.refusals and len(compiled.rows) == 1
    assert corpus.queries[0].dimensions["dag_shape"] == shape
    result = run_eval_row(compiled.rows[0], records)
    assert result.grade["fails"] == [], result.grade
    assert any(span.writes for span in result.spans)
    assert any(span.reads for span in result.spans)


@pytest.mark.parametrize(("label", "connector", "entity", "format", "operation"), [
    ("record", "servicenow", "incident", "record", Operation.CREATE),
    ("page", "confluence", "page", "html", Operation.CREATE),
    ("document", "sharepoint", "file", "docx", Operation.CREATE),
    ("workbook", "sharepoint", "file", "xlsx", Operation.CREATE),
    ("presentation", "sharepoint", "file", "pptx", Operation.CREATE),
    ("email", "email", "message", "html", Operation.DRAFT),
])
def test_output_labels_map_to_supported_connector_entities_and_formats(
    world: World, label: str, connector: str, entity: str, format: str, operation: Operation,
) -> None:
    original = builtin_registry()
    workflow = _registry().workflows["evidence_review"].model_copy(update={
        "destinations": (DestinationRole(connector=connector, entities=(entity,),
            operations=(operation,), formats=(format,)),),
        "content_actions": (ContentAction.EXTRACT,),
    })
    registry = SpecRegistry(original.connectors.values(), (workflow,))
    harness = _harness(world).with_registry(registry).with_dag_grammar("fan_in").exhaustive().take(1)
    corpus, _ = harness.build()
    assert len(corpus.queries) == 1, label
    mutation = corpus.queries[0].generation.mutation
    assert (mutation.connector, mutation.entity, mutation.output_format) == (connector, entity, format)
    records = runtime_records(corpus.connector_data.records)
    compiled = compile_rows(corpus.queries, corpus.fixtures, records)
    assert not compiled.refusals, compiled.refusals
    assert run_eval_row(compiled.rows[0], records).grade["fails"] == []


@pytest.mark.parametrize("name", ["risk_register", "steering_pack"])
def test_custom_workflow_names_remain_authorable_without_a_second_planner(world: World, name: str) -> None:
    registry = _registry()
    workflow = registry.workflows["evidence_review"].model_copy(update={"name": name, "purpose": name.replace("_", " ")})
    authored = SpecRegistry(registry.connectors.values(), (workflow,))
    queries, _ = _harness(world).with_registry(authored).take(1).plan()
    assert len(queries) == 1 and queries[0].workflow == name
    assert name.replace("_", " ") in queries[0].query
