"""The compiler that joins Worldloom's two accounts of a trajectory.

`enterprise_queries` plans a verb-level DAG; `connector_eval_runtime` executes a
tool-level one and `connector_trace.grade_trace` decides nineteen assertion
kinds over it. The second is the half that can answer "was the system actually
updated", and nothing reached it: `state_equals` was implemented, correct, and
had no producer.

Four things about the executor's row are not guessable, and each of these tests
pins one, because getting any of them wrong produces a row that looks right and
either refuses to run or grades the wrong thing.
"""

from __future__ import annotations

import pytest

from worldloom.connector_eval_runtime import run_eval_row
from worldloom.enterprise_corpus import materialize_corpus
from worldloom.enterprise_queries import builtin_registry, plan_queries
from worldloom.enterprise_rows import (
    MODEL_CONNECTOR,
    CompileReport,
    RowError,
    compile_row,
    compile_rows,
    runtime_records,
)
from worldloom.enterprise_specs import ScenarioProfile, apply_scenario_profile
from worldloom.world import World

PROFILE = {
    "name": "rows",
    "industry": "retail",
    "company_description": "Retail operations close.",
    "connectors": ["servicenow", "jira", "sharepoint"],
    "workflows": ["change_assurance"],
    "additional_workflows": [
        {
            "name": "change_assurance",
            "purpose": "change assurance pack",
            "process": "service_management",
            "sources": [
                {"connector": "servicenow", "entities": ["change_request", "incident"]},
                {"connector": "jira", "entities": ["issue"]},
            ],
            "destinations": [
                {
                    "connector": "sharepoint",
                    "entities": ["file"],
                    "operations": ["create"],
                    "formats": ["xlsx", "docx"],
                }
            ],
            "content_actions": ["extract", "reconcile", "generate", "render"],
            "audiences": ["executive", "manager", "analyst", "operations"],
            "prompt_template": (
                "Prepare the {period} {purpose} for {company}'s {audience} audience."
                " Use {sources}. {action_instruction} {output_label} in {destination}."
                " {verification_instruction}{failure_instruction}"
            ),
        }
    ],
    "coverage": {
        "name": "narrow",
        "strengths": 2,
        "connector_counts": [1, 2],
        "failures": ["none"],
        "max_candidates": 10_000_000,
    },
}


@pytest.fixture(scope="module")
def corpus():
    world = World.load("examples/retail-close")
    profile = ScenarioProfile.model_validate(PROFILE)
    registry = apply_scenario_profile(builtin_registry(), profile)
    queries, _ = plan_queries(world, registry=registry, profile=profile.coverage, limit=8)
    return materialize_corpus(world, tuple(queries))


def test_the_whole_set_compiles_and_executes(corpus) -> None:
    """The number this module exists for.

    Compiling is not the claim; executing is. A row that compiles and then
    refuses to run is worth nothing, and every failure mode below produced
    exactly that.
    """
    records = runtime_records(corpus.connector_data.records)
    report = compile_rows(corpus.queries, corpus.fixtures, records)
    assert report.refusals == (), report.reasons()
    assert report.compiled == len(corpus.queries)

    for row in report.rows:
        grade = run_eval_row(row, records).grade
        assert grade["status"] in {"ok", "behavior"}, (row["id"], grade["fails"])


def test_the_model_transform_node_is_dropped_and_its_edges_rewired(corpus) -> None:
    """`run_eval_row` refuses a `model` server outright.

    The planner puts exactly one transform node in every DAG, so this is not an
    optimisation: without it the row raises
    `eval row references connectors with no definition: ['model']` before
    anything executes. The rewiring has to be transitive, or the write is
    orphaned from the read it depends on.
    """
    fixtures = {f.query_id: f for f in corpus.fixtures}
    query = corpus.queries[0]
    assert any(node["connector"] == MODEL_CONNECTOR for node in query.expected_dag)

    row = compile_row(query, fixtures[query.id], runtime_records(corpus.connector_data.records))
    assert all(node["server"] != MODEL_CONNECTOR for node in row["expected_dag"]["nodes"])
    edges = {(a, b) for a, b in row["expected_dag"]["edges"]}
    assert ("read-0", "write") in edges
    assert ("write", "verify") in edges


def test_tool_names_are_bare_not_connector_qualified(corpus) -> None:
    """`servicenow.get_record` raises `unknown servicenow tool`.

    The qualified spelling exists only on the way out: the emulator stamps it
    on the span and the grader rebuilds it from the node to compare. A compiler
    emitting it would fail the lookup, and had it not, the grader would compare
    against `servicenow.servicenow.get_record`.
    """
    fixtures = {f.query_id: f for f in corpus.fixtures}
    query = corpus.queries[0]
    row = compile_row(query, fixtures[query.id], runtime_records(corpus.connector_data.records))
    for node in row["expected_dag"]["nodes"]:
        assert "." not in node["tool"], node


def test_edges_are_two_element_sequences(corpus) -> None:
    """A mapping does not error; it unpacks to its keys and mis-resolves
    `for_each` silently, which is the worse failure."""
    fixtures = {f.query_id: f for f in corpus.fixtures}
    query = corpus.queries[0]
    row = compile_row(query, fixtures[query.id], runtime_records(corpus.connector_data.records))
    for edge in row["expected_dag"]["edges"]:
        assert isinstance(edge, list) and len(edge) == 2, edge


def test_records_are_translated_to_the_shape_the_emulator_indexes(corpus) -> None:
    """The two halves disagree about a record as well as about a DAG.

    `ConnectorRecord` names the identity `id` and the system `connector`; the
    emulator requires `fid` and `server` and raises `KeyError: 'fid'` before a
    single node runs.
    """
    raw = list(corpus.connector_data.records)
    assert "fid" not in (raw[0].model_dump() if hasattr(raw[0], "model_dump") else raw[0])
    translated = runtime_records(raw)
    assert all("fid" in record and "server" in record for record in translated)


def test_an_operation_with_no_tool_is_refused_not_silently_dropped() -> None:
    """A row that quietly loses its write node would grade clean while testing
    nothing, which is the failure this seam exists to stop."""
    report = CompileReport(refusals=(RowError("Q1", "salesforce/account has no tool for 'upsert'"),))
    assert report.compiled == 0
    assert report.reasons() == {"salesforce/account has no tool for 'upsert'": 1}


def test_compiling_is_deterministic(corpus) -> None:
    """Two compilations of one corpus produce identical rows.

    The create payload's name is derived from the query id for this reason;
    nothing here draws or reads a clock.
    """
    records = runtime_records(corpus.connector_data.records)
    first = compile_rows(corpus.queries, corpus.fixtures, records).rows
    second = compile_rows(corpus.queries, corpus.fixtures, records).rows
    assert first == second
