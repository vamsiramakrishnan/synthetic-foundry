"""Public-only reference and adversarial controls over existing evalrun seams."""

from __future__ import annotations

from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest

from worldloom.connector_data import ConnectorRecord
from worldloom.connector_definition import load_connector_definition
from worldloom.enterprise_dag import EnterpriseDagNode, transform_results
from worldloom.enterprise_rows import runtime_records
from worldloom.evalrun.agents import (
    AgentResponse,
    AgentTask,
    CallableAgent,
    ToolSurface,
)
from worldloom.evalrun.contract import read_case_set
from worldloom.evalrun.harness_dags import (
    HarnessDagConfig,
    HarnessDagReference,
    build_harness_dags,
)
from worldloom.evalrun.runner import run_cases, service_for
from worldloom.predicates import Predicate


def records(*, count: int = 3, stale: bool = True) -> tuple[ConnectorRecord, ...]:
    """Mechanical fixtures only; production builder must consume supplied facts."""
    values = [ConnectorRecord(id=f"source-{index}", external_id=f"EXT-{index}", connector="sharepoint", entity="xlsx",
                              title=f"Ledger {index}", fields={"business_unit": "Treasury", "period": "FY2026",
                              "status": "approved", "amount_minor": 100 * index}, fact_ids=[f"fixture-fact-{index}"])
              for index in range(1, count + 1)]
    if stale:
        values.append(ConnectorRecord(id="source-stale", external_id="EXT-STALE", connector="sharepoint", entity="xlsx",
                                      title="Working ledger", fields={"business_unit": "Treasury", "period": "FY2026",
                                      "status": "draft", "amount_minor": 90000}, fact_ids=["fixture-stale-fact"]))
    return tuple(values)


def run(suite: Any, agent: Any) -> Any:
    service = service_for(suite.cases, runtime_records(suite.records), surface="native")
    return run_cases(service, suite.cases, agent)


@pytest.mark.parametrize("refine", [False, True])
def test_public_only_reference_passes_all_operations_and_response_policies(refine: bool) -> None:
    suite = build_harness_dags(records(), HarnessDagConfig(cases=6))
    report = run(suite, HarnessDagReference(suite.tasks, refine=refine))
    assert len(report.results) == 6
    for result in report.results:
        assert result.graded and result.score and result.score.passed, (result.error, result.score)
        assert result.score.trajectory.retrieval
        assert result.score.trajectory.retrieval.recovered == int(refine)
        assert result.score.outcomes.structured_met == 1
    assert {case.dimensions["retrieval_response"] for case in suite.cases} == {"empty", "partial", "stale"}
    assert {case.dimensions["operation"] for case in suite.cases} == {"create", "update"}


def test_correct_outcome_does_not_excuse_unchanged_insufficient_retries() -> None:
    suite = build_harness_dags(records(), HarnessDagConfig(cases=1))
    public = suite.tasks[0]
    good = HarnessDagReference(suite.tasks)

    def retry(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        broad = Predicate(entity=public.source_entity, where=(public.scope,)).model_dump(mode="json")
        for _ in range(2):
            tools.call(f"{public.connector}.{public.search_tool}", entity=public.source_entity,
                       predicate=broad, max_results=10)
        return good.run(task, tools)

    result = run(suite, CallableAgent(retry, name="pointless-retries")).results[0]
    assert result.graded and result.score and result.score.outcomes.passed
    assert not result.score.trajectory.passed
    assert result.score.trajectory.retrieval and result.score.trajectory.retrieval.repeated_without_progress == 1
    assert not result.score.passed


def test_wrong_aggregate_in_a_created_report_fails_actual_state() -> None:
    suite = build_harness_dags(records(), HarnessDagConfig(cases=1))
    good = HarnessDagReference(suite.tasks)

    class WrongTotal:
        def __init__(self, tools: ToolSurface) -> None:
            self.tools = tools

        def call(self, tool: str, **arguments: Any) -> Any:
            if tool.endswith(".create_file"):
                arguments["fields"] = {**arguments["fields"], "total": -1}
            return self.tools.call(tool, **arguments)

    def bad(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        try:
            return good.run(task, WrongTotal(tools))  # type: ignore[arg-type]
        except ValueError:
            return AgentResponse(answer="The correct report was created.")

    result = run(suite, CallableAgent(bad, name="false-success")).results[0]
    assert result.graded and result.score and not result.score.outcomes.passed
    assert not result.score.passed


def test_equivalent_predicate_order_is_not_a_different_plan() -> None:
    suite = build_harness_dags(records(), HarnessDagConfig(cases=1))
    good = HarnessDagReference(suite.tasks)

    class Reordered:
        def __init__(self, tools: ToolSurface) -> None:
            self.tools = tools

        def call(self, tool: str, **arguments: Any) -> Any:
            if "predicate" in arguments:
                arguments["predicate"] = {**arguments["predicate"], "where": list(reversed(arguments["predicate"]["where"]))}
            return self.tools.call(tool, **arguments)

    result = run(suite, CallableAgent(lambda task, tools: good.run(task, Reordered(tools)), name="equivalent-plan")).results[0]  # type: ignore[arg-type]
    assert result.graded and result.score and result.score.passed, result


def test_independent_evidence_reads_can_run_in_reverse_order() -> None:
    suite = build_harness_dags(records(), HarnessDagConfig(cases=1))
    good = HarnessDagReference(suite.tasks)

    class ReversedReads:
        def __init__(self, tools: ToolSurface) -> None:
            self.tools = tools

        def call(self, tool: str, **arguments: Any) -> Any:
            result = self.tools.call(tool, **arguments)
            if tool.endswith(".search_files"):
                return {**result, "items": list(reversed(result["items"]))}
            return result

    result = run(suite, CallableAgent(lambda task, tools: good.run(task, ReversedReads(tools)), name="reverse-reads")).results[0]  # type: ignore[arg-type]
    assert result.graded and result.score and result.score.passed, result


def test_public_tasks_expose_constraints_but_no_answer_source_ids_or_private_dag() -> None:
    suite = build_harness_dags(records(), HarnessDagConfig(cases=1))
    public = suite.tasks[0].model_dump_json()
    for forbidden in ("expected_dag", "controlled_retrieval", "fixture-fact-", "EXT-1", "source-1", '"total":600'):
        assert forbidden not in public
    assert "Treasury" in public and "FY2026" in public and "approved" in public


def test_case_set_replays_and_loads_through_existing_evalrun_format(tmp_path: Path) -> None:
    config = HarnessDagConfig(cases=6)
    first = build_harness_dags(records(), config)
    second = build_harness_dags(reversed(records()), config)
    assert first == second
    first.write(tmp_path / "first")
    second.write(tmp_path / "second")
    for path in (tmp_path / "first").iterdir():
        assert path.read_bytes() == (tmp_path / "second" / path.name).read_bytes()
    cases, held = read_case_set(tmp_path / "first")
    assert cases == first.cases
    assert len(held) == len(first.records)
    assert len({case.dimensions["family_id"] for case in cases}) == 1
    with pytest.raises(ValueError, match="not empty"):
        first.write(tmp_path / "first")


def test_no_stale_condition_is_claimed_without_an_actual_stale_source() -> None:
    suite = build_harness_dags(records(stale=False), HarnessDagConfig(cases=6))
    assert len(suite.cases) == 4
    assert {case.dimensions["retrieval_response"] for case in suite.cases} == {"empty", "partial"}
    assert any(finding.reason == "stale_response_without_stale_source" for finding in suite.skipped)


@pytest.mark.parametrize("field,value,reason", [
    ("amount_minor", "100", "invalid_numeric_source"),
    ("amount_minor", True, "invalid_numeric_source"),
    ("business_unit", None, "source_count"),
])
def test_missing_or_invalid_source_facts_are_not_repaired_with_filler(field: str, value: Any, reason: str) -> None:
    original = records(count=2, stale=False)
    corrupted = original[0].model_copy(update={"fields": {**original[0].fields, field: value}})
    with pytest.raises(ValueError, match=reason):
        build_harness_dags((corrupted, original[1]))


def test_call_budget_counts_every_search_page() -> None:
    definition = load_connector_definition("sharepoint")
    tool = definition.tools["search_files"].model_copy(update={"page_size": 1})
    definition = definition.model_copy(update={"tools": {**definition.tools, "search_files": tool}})
    # Three fetches + three search pages + write + readback = eight calls.
    with pytest.raises(ValueError, match="call_budget:8>7"):
        build_harness_dags(records(), HarnessDagConfig(cases=1, max_calls=7), definitions={"sharepoint": definition})
    suite = build_harness_dags(records(), HarnessDagConfig(cases=1, max_calls=8), definitions={"sharepoint": definition})
    result = run(suite, HarnessDagReference(suite.tasks)).results[0]
    assert result.graded and result.score and result.score.passed, result
    assert result.calls == 8


def aggregate(values: list[Any]) -> Any:
    node = EnterpriseDagNode(id="sum", connector="model", entity="value", kind="transform", operation="aggregate",
                             transform="aggregate", depends_on=("read",), arguments={"path": ["amount"]})
    return transform_results(node, {"read": [{"amount": value} for value in values]})[0]["value"]


def test_decimal_aggregation_is_exact_and_independent_of_caller_precision() -> None:
    with localcontext() as context:
        context.prec = 3
        context.Emax = 5
        context.Emin = -5
        assert aggregate([10**30, 1]) == 10**30 + 1
        assert aggregate([Decimal("0.10"), Decimal("0.20")]) == "0.3"
        assert aggregate([0.1, 0.2]) == "0.3"
    with pytest.raises(ValueError, match="precision budget"):
        aggregate([Decimal("1E+1000000")])


@pytest.mark.parametrize("value", [True, "100", float("inf"), float("nan"), Decimal("NaN")])
def test_nonfinite_and_nonnumeric_aggregate_inputs_are_refused(value: Any) -> None:
    with pytest.raises(ValueError, match="aggregate requires"):
        aggregate([value])
