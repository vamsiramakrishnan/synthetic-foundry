"""Ambiguous joins and stale sources graded under a checked policy, opt-in.

The legacy gold for both defects was the single write, so an agent that
picked one of two matching records, or built on the stale one, graded clean.
Under ``source_policy=True`` the gold is to name both candidates and stop, or
to cite the authoritative replacement, and the outcome axis says which was
missed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldloom.enterprise_corpus import EnterpriseCorpus, materialize_corpus
from worldloom.enterprise_failures import (
    ambiguous_duplicate_id,
    authoritative_replacement_id,
)
from worldloom.enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from worldloom.enterprise_rows import runtime_records
from worldloom.evalrun.agents import (
    AgentResponse,
    AgentTask,
    CallableAgent,
    ReferenceAgent,
    ToolSurface,
)
from worldloom.evalrun.autopsy import finding_keys
from worldloom.evalrun.contract import EvalCase, cases_from_corpus
from worldloom.evalrun.runner import CaseResult, run_cases, service_for
from worldloom.evalrun.source_policy import source_policy_row
from worldloom.world import World


def _query(failure: str) -> PlannedEnterpriseQuery:
    return PlannedEnterpriseQuery(
        id=f"policy-{failure}", workflow="incident-followup",
        query="Read the incident evidence, save its report and verify the result.",
        dimensions={"failure": failure},
        generation=GenerationRequirement(
            process="service_management",
            source_requirements=(SourceRequirement(connector="servicenow", entity="incident"),),
            mutation=MutationRequirement(connector="sharepoint", entity="file", operation="create",
                                         output_format="docx", preexisting_record=False),
            state_overrides=(failure,),
        ),
        expected_dag=(
            {"id": "read", "connector": "servicenow", "entity": "incident", "kind": "read", "depends_on": []},
            {"id": "transform", "connector": "model", "entity": "docx", "kind": "generate", "depends_on": ["read"]},
            {"id": "write", "connector": "sharepoint", "entity": "file", "kind": "create", "depends_on": ["transform"]},
            {"id": "verify", "connector": "sharepoint", "entity": "file", "kind": "readback", "depends_on": ["write"]},
        ),
    )


@pytest.fixture(scope="module")
def corpus() -> EnterpriseCorpus:
    return materialize_corpus(World.load(Path("examples/retail-close")),
                              (_query("ambiguous_join"), _query("stale_source")))


@pytest.fixture(scope="module")
def records(corpus: EnterpriseCorpus) -> list[dict]:
    return runtime_records(corpus.connector_data.records)


def _run(corpus: EnterpriseCorpus, records: list[dict], cases: tuple[EvalCase, ...], agent: object) -> dict[str, CaseResult]:
    report = run_cases(service_for(cases, records), cases, agent)  # type: ignore[arg-type]
    return {result.case_id: result for result in report.results}


def _bound(corpus: EnterpriseCorpus, failure: str) -> str:
    fixture = next(item for item in corpus.fixtures if item.query_id == f"policy-{failure}")
    return str(fixture.overrides[0].record_id)


def test_opt_in_leaves_legacy_cases_byte_identical(corpus: EnterpriseCorpus) -> None:
    legacy = cases_from_corpus(corpus)
    again = cases_from_corpus(corpus, source_policy=False)
    assert [case.model_dump(mode="json") for case in legacy] == [case.model_dump(mode="json") for case in again]
    assert all("source_policy" not in json.dumps(case.model_dump(mode="json")) for case in legacy)
    policed = {case.id: case for case in cases_from_corpus(corpus, source_policy=True)}
    ambiguous, stale = policed["policy-ambiguous_join"], policed["policy-stale_source"]
    assert ambiguous.outcomes.source_policy is not None and ambiguous.outcomes.no_write
    assert ambiguous.plan.of_kind("write") == ()
    assert [point.id for point in ambiguous.trajectory.questions] == ["which-record"]
    assert stale.outcomes.source_policy is not None
    assert stale.outcomes.source_policy.authoritative == (
        authoritative_replacement_id("policy-stale_source", _bound(corpus, "stale_source")),)


def test_reference_meets_both_policies(corpus: EnterpriseCorpus, records: list[dict]) -> None:
    cases = cases_from_corpus(corpus, source_policy=True)
    results = _run(corpus, records, cases, ReferenceAgent(cases))
    for case_id, result in results.items():
        assert result.score is not None, result.error
        assert result.score.passed, (case_id, finding_keys(result), result.notes)
        policy = result.score.outcomes.source_policy
        assert policy is not None and policy.findings == ()
    ambiguous = results["policy-ambiguous_join"]
    duplicate = ambiguous_duplicate_id("policy-ambiguous_join", _bound(corpus, "ambiguous_join"))
    assert duplicate in ambiguous.questions[0]["question"]
    assert ambiguous.score is not None and ambiguous.score.outcomes.diff.created == ()


def test_picking_one_join_candidate_is_a_missing_clarification(corpus: EnterpriseCorpus, records: list[dict]) -> None:
    policed = tuple(case for case in cases_from_corpus(corpus, source_policy=True) if case.id == "policy-ambiguous_join")
    # The legacy gold reads the bound record and writes: an arbitrary pick.
    legacy = tuple(case for case in cases_from_corpus(corpus) if case.id == "policy-ambiguous_join")
    result = _run(corpus, records, policed, ReferenceAgent(legacy))["policy-ambiguous_join"]
    assert result.score is not None and not result.score.passed
    keys = finding_keys(result, policed[0])
    assert "outcomes.clarification_missing" in keys
    assert "outcomes.collateral" in keys


def test_building_on_the_stale_record_is_found(corpus: EnterpriseCorpus, records: list[dict]) -> None:
    policed = tuple(case for case in cases_from_corpus(corpus, source_policy=True) if case.id == "policy-stale_source")
    legacy = tuple(case for case in cases_from_corpus(corpus) if case.id == "policy-stale_source")
    stale = next(record for record in records if record["fid"] == _bound(corpus, "stale_source"))
    walker = ReferenceAgent(legacy)

    def cites_stale(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        walker.run(task, tools)
        return AgentResponse(answer=f"Report built from {stale['external_id']}.")

    def cites_nothing(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        walker.run(task, tools)
        return AgentResponse(answer="Report saved.")

    used = _run(corpus, records, policed, CallableAgent(cites_stale, name="stale"))["policy-stale_source"]
    assert "outcomes.stale_source_used" in finding_keys(used, policed[0])
    missing = _run(corpus, records, policed, CallableAgent(cites_nothing, name="silent"))["policy-stale_source"]
    assert "outcomes.authoritative_source_missing" in finding_keys(missing, policed[0])


def test_rows_without_a_source_defect_are_left_alone(corpus: EnterpriseCorpus, records: list[dict]) -> None:
    case = cases_from_corpus(corpus)[0]
    row = {**case.row, "state_overrides": []}
    assert source_policy_row(row, records) is None
    doubled = {**case.row, "state_overrides": [*case.row["state_overrides"], *case.row["state_overrides"]]}
    with pytest.raises(ValueError, match="exactly one source defect"):
        source_policy_row(doubled, records)
