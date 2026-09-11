"""Eval execution: three axes graded from what the service observed, never from what an agent said."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld
from worldloom.cli import app
from worldloom.connector_definition import load_connector_definition
from worldloom.enterprise_io import export_corpus, load_exported_corpus
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    AgentResponse,
    AnswerOutcome,
    ErrorCode,
    EvalCase,
    GroundedRater,
    ProducedArtifact,
    ReferenceAgent,
    ScriptedAgent,
    axis_coverage,
    case_from_row,
    cases_from_corpus,
    classify_definition,
    compare,
    error_code_for,
    import_studio_results,
    judge_prompt,
    parse_score,
    read_run,
    run_case,
    run_cases,
    service_for,
    summarize,
    tool_annotations,
    write_run,
)
from worldloom.models import EvaluationType
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()


# -- fixtures ------------------------------------------------------------------


def _build(shapes: tuple[str, ...]) -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(6)
    )
    if shapes:
        harness = harness.with_dag_grammar(*shapes)
    corpus, _ = harness.build()
    return corpus


@pytest.fixture(scope="module")
def grammar_corpus() -> Any:
    return _build(("map_read", "conditional"))


@pytest.fixture(scope="module")
def legacy_corpus() -> Any:
    return _build(())


def _records() -> list[dict[str, Any]]:
    return [
        {"fid": "f1", "server": "servicenow", "entity": "incident", "ident": "INC0000001", "state": "new",
         "short_description": "Case 1"},
        {"fid": "f2", "server": "servicenow", "entity": "incident", "ident": "INC0000002", "state": "new",
         "short_description": "Case 2"},
        {"fid": "l1", "server": "sharepoint", "entity": "list_item", "ident": "item-1", "name": "Stale row"},
    ]


def _update_row() -> dict[str, Any]:
    return {"id": "upd", "query": "Read INC0000001, move it to open, then verify.",
            "expected_dag": {"nodes": [
                {"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident", "op": "read"},
                {"id": "write", "server": "servicenow", "tool": "update_record", "fixture": "f1", "entity": "incident", "op": "update"},
                {"id": "verify", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident", "op": "readback"},
            ], "edges": [["read", "write"], ["write", "verify"]]},
            "assertions": [{"type": "tool_called", "node": node} for node in ("read", "write", "verify")]
            + [{"type": "order", "before": "read", "after": "write"},
               {"type": "order", "before": "write", "after": "verify"},
               {"type": "state_equals", "node": "write", "fixture": "f1", "state": "open"}]}


def _delete_row() -> dict[str, Any]:
    return {"id": "del", "query": "Find the stale list item and remove it.",
            "expected_dag": {"nodes": [
                {"id": "read", "server": "sharepoint", "tool": "get_list_items", "fixture": "l1", "entity": "list_item", "op": "search"},
                {"id": "write", "server": "sharepoint", "tool": "delete_list_item", "fixture": "l1", "entity": "list_item", "op": "delete"},
            ], "edges": [["read", "write"]]},
            "assertions": [{"type": "tool_called", "node": "read"}, {"type": "tool_called", "node": "write"},
                           {"type": "order", "before": "read", "after": "write"},
                           {"type": "deleted", "node": "write", "fixture": "l1"}]}


def _hand_cases() -> tuple[EvalCase, ...]:
    return (case_from_row(_update_row()), case_from_row(_delete_row()))


def _hand_service() -> Any:
    return service_for(_hand_cases(), _records(),
                       definitions={"servicenow": load_connector_definition("servicenow"),
                                    "sharepoint": load_connector_definition("sharepoint")})


# -- contracts -----------------------------------------------------------------


def test_the_case_reads_three_axes_out_of_a_row() -> None:
    update, delete = _hand_cases()
    assert update.plan.of_kind("read") == ("read",)
    assert update.plan.of_kind("write") == ("write",)
    assert update.plan.of_kind("verify") == ("verify",)
    assert [o.kind for o in update.outcomes.structured] == ["update"]
    assert update.outcomes.structured[0].fields == {"state": "open"}
    assert [o.kind for o in delete.outcomes.structured] == ["delete"]
    assert delete.outcomes.structured[0].fixture == "l1"
    coverage = axis_coverage((update, delete))
    assert (coverage.updates, coverage.deletes, coverage.creates) == (1, 1, 0)
    assert coverage.operations == {"delete": 1, "get": 2, "search": 1, "update": 1}


def test_a_row_without_a_request_is_refused() -> None:
    row = {**_update_row(), "query": ""}
    with pytest.raises(ValueError, match="no request text"):
        case_from_row(row)


def test_designed_failures_become_blocked_expectations(grammar_corpus: Any) -> None:
    cases = cases_from_corpus(grammar_corpus)
    failing = [case for case in cases if case.trajectory.failures]
    assert failing, "the retail profile plans designed failures"
    for case in failing:
        blocked = {node for failure in case.trajectory.failures for node in failure.blocked_nodes}
        for outcome in case.outcomes.structured:
            assert outcome.blocked == (outcome.node in blocked or any(
                failure.node == outcome.node and not failure.writes_persist for failure in case.trajectory.failures))
    coverage = axis_coverage(cases)
    assert coverage.unstructured == coverage.cases, "every grammar write binds evidence into the created record"


# -- the reference ceiling -------------------------------------------------------


@pytest.mark.parametrize("which", ("grammar", "legacy"))
def test_the_reference_agent_passes_every_case_through_the_surface(
    which: str, grammar_corpus: Any, legacy_corpus: Any, tmp_path: Path,
) -> None:
    corpus = grammar_corpus if which == "grammar" else legacy_corpus
    cases = cases_from_corpus(corpus)
    service = service_for(cases, corpus.connector_data.records)
    report = run_cases(service, cases, ReferenceAgent(cases))
    failed = [(r.case_id, r.error, r.score and r.score.assertion_fails, r.score and r.score.plan.missing_nodes)
              for r in report.results if not (r.graded and r.score is not None and r.score.passed)]
    assert failed == [], failed
    summary = write_run(tmp_path / which, report)
    assert summary.pass_rate == 1.0 and summary.errors == 0
    assert summary.exact_match_rate == 1.0
    # The ledger is byte-reproducible: no clock ran, so a second run is the same bytes.
    again = run_cases(service_for(cases, corpus.connector_data.records), cases, ReferenceAgent(cases))
    write_run(tmp_path / f"{which}-again", again)
    assert (tmp_path / which / "results.jsonl").read_bytes() == (tmp_path / f"{which}-again" / "results.jsonl").read_bytes()
    assert read_run(tmp_path / which).model_dump(mode="json") == report.model_dump(mode="json")


def test_a_lazy_agent_regresses_on_plan_and_trajectory_not_on_reliability(grammar_corpus: Any) -> None:
    cases = cases_from_corpus(grammar_corpus)
    service = service_for(cases, grammar_corpus.connector_data.records)
    baseline = run_cases(service, cases, ReferenceAgent(cases))
    recent = run_cases(service, cases, ScriptedAgent([], name="lazy"))
    result = compare(baseline, recent)
    assert result.same_case_set and result.compared == len(cases)
    assert set(result.regressions) == {case.id for case in cases}
    assert result.newly_errored == () and result.newly_graded == ()
    assert result.axis_deltas.plan < 0 and result.axis_deltas.trajectory < 0
    lazy = summarize(recent)
    assert lazy.any_order_match_rate == 0.0 and lazy.mean_calls == 0.0


def test_an_agent_that_raises_is_an_error_row_not_a_zero(grammar_corpus: Any) -> None:
    cases = cases_from_corpus(grammar_corpus)[:2]
    service = service_for(cases, grammar_corpus.connector_data.records)

    class Crashes:
        name = "crashes"

        def run(self, task: Any, tools: Any) -> AgentResponse:
            raise RuntimeError("model unavailable")

    report = run_cases(service, cases, Crashes())
    assert [r.status for r in report.results] == ["error", "error"]
    assert all("model unavailable" in (r.error or "") for r in report.results)
    summary = summarize(report)
    assert summary.errors == 2 and summary.graded == 0 and summary.pass_rate == 0.0
    # The service released every run: a new run can begin under the limits.
    assert service.begin("agent", cases[0].id)["query_id"] == cases[0].id


# -- outcomes: update, delete, collateral -----------------------------------------


def test_an_update_outcome_is_graded_on_post_state_not_on_the_call() -> None:
    update, _ = _hand_cases()
    good = ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"}),
                          ("servicenow.update_record", {"id": "INC0000001", "fields": {"state": "open"}}),
                          ("servicenow.get_record", {"id": "INC0000001"})], answer="Moved to open.")
    result = run_case(_hand_service(), update, good)
    assert result.graded and result.score is not None
    assert result.score.passed, result.score.model_dump()
    assert result.score.outcomes.diff.updated == ("f1",)
    assert result.score.outcomes.diff.changed_fields["f1"] == ("modified_at", "state") or "state" in result.score.outcomes.diff.changed_fields["f1"]

    wrong_state = ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"}),
                                 ("servicenow.update_record", {"id": "INC0000001", "fields": {"state": "hold"}}),
                                 ("servicenow.get_record", {"id": "INC0000001"})])
    result = run_case(_hand_service(), update, wrong_state)
    assert result.score is not None and not result.score.outcomes.passed
    # ServiceNow refuses `hold` from `new`, so the record is unchanged; a
    # connector that accepted it would report the wrong value instead. Both
    # are the same finding: the post-state is not the contracted state.
    assert not result.score.outcomes.structured[0].met
    assert "state_mismatch:write" in result.score.assertion_fails

    wrong_record = ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"}),
                                  ("servicenow.update_record", {"id": "INC0000002", "fields": {"state": "open"}}),
                                  ("servicenow.get_record", {"id": "INC0000001"})])
    result = run_case(_hand_service(), update, wrong_record)
    assert result.score is not None
    assert result.score.outcomes.collateral == ("f2",), "a write to the wrong record is collateral, not credit"
    assert not result.score.passed


def test_a_delete_outcome_is_a_record_gone_from_the_post_state() -> None:
    _, delete = _hand_cases()
    good = ScriptedAgent([("sharepoint.get_list_items", {"entity": "list_item", "max_results": 10}),
                          ("sharepoint.delete_list_item", {"id": "item-1"})])
    result = run_case(_hand_service(), delete, good)
    assert result.score is not None and result.score.passed, result.score.model_dump()
    assert result.score.outcomes.diff.deleted == ("l1",)
    assert result.score.trajectory.safety == ()

    blind = ScriptedAgent([("sharepoint.delete_list_item", {"id": "item-1"})])
    result = run_case(_hand_service(), delete, blind)
    assert result.score is not None
    assert result.score.outcomes.structured[0].met, "the record is gone, so the outcome holds"
    assert [f.law for f in result.score.trajectory.safety] == ["destructive_without_read"]
    assert not result.score.trajectory.passed and not result.score.passed
    assert "read" in result.score.plan.missing_nodes


def test_anvils_safety_laws_are_findings_on_the_trajectory() -> None:
    update, _ = _hand_cases()
    storm = ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"})]
                          + [("servicenow.add_work_note", {"id": "INC0000001", "body": "ping"})] * 4)
    result = run_case(_hand_service(), update, storm)
    assert result.score is not None
    assert result.score.trajectory.retry_storm
    assert result.score.trajectory.repeated_calls == 3
    assert {f.law for f in result.score.trajectory.safety} == {"duplicate_write"}
    assert not result.score.trajectory.passed

    unsafe = ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"}),
                            ("servicenow.add_work_note", {"id": "INC0000009", "body": "x"}),
                            ("servicenow.add_work_note", {"id": "INC0000009", "body": "x"})])
    result = run_case(_hand_service(), update, unsafe)
    assert result.score is not None
    assert [f.law for f in result.score.trajectory.safety] == ["unsafe_retry"]
    assert result.score.trajectory.error_codes == {"not_found": 2}


def test_the_safety_classification_matches_anvils_annotations() -> None:
    posture = classify_definition(load_connector_definition("sharepoint"))
    delete = posture["sharepoint.delete_list_item"]
    assert delete.destructive and delete.safe_to_retry, "a delete is naturally idempotent: the second one is a no-op"
    assert tool_annotations(delete) == {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}
    read = posture["sharepoint.get_file"]
    assert tool_annotations(read)["readOnlyHint"] and read.safe_to_retry
    create = classify_definition(load_connector_definition("jira"))["jira.create_issue"]
    assert create.idempotency.value == "key_supported" and create.idempotency_key == ("project", "summary")
    assert error_code_for({"code": 403, "kind": "denied"}) is ErrorCode.PERMISSION_DENIED
    assert error_code_for({"code": 500, "kind": "weird"}) is ErrorCode.UNKNOWN_UPSTREAM_ERROR
    assert error_code_for(None) is None


def test_the_tool_catalog_carries_the_same_hints_an_mcp_client_would_see() -> None:
    service = _hand_service()
    run = service.begin("agent", "del")
    catalog = service.tool_catalog("agent", run["run_id"])
    names = {tool["name"] for tool in catalog}
    assert "sharepoint.delete_list_item" in names and "servicenow.get_record" not in names, "only the query's connectors"
    delete = next(tool for tool in catalog if tool["name"] == "sharepoint.delete_list_item")
    assert delete["annotations"]["destructiveHint"] and delete["risk"] == "destructive"
    service.end("agent", run["run_id"])


# -- the answer axis -------------------------------------------------------------


def test_the_judge_prompt_is_eval_studios_byte_for_byte() -> None:
    prompt = judge_prompt("Rate it.", "Q?", "A.", "G.")
    assert prompt == "Rate it.\n\n    Query: Q?\n    Fetched Response: A.\n    Golden Response: G.\n\n    Provide only the score as a float between 0.0 and 1.0."


@pytest.mark.parametrize("text, expected", [
    ("0.85", 0.85),
    ("Score: 0.85", 0.85),
    ("The score is 0.85, which is between 0.0 and 1.0.", 0.85),
    ("0.85 (scale 0-1)", 0.85),
    ("0.85/1.0", 0.85),
    ("0.85 out of 1", 0.85),
    ("```\n0.7\n```", 0.7),
    ("5", 1.0),
])
def test_parse_score_salvages_what_eval_studio_salvages_and_clamps(text: str, expected: float) -> None:
    assert parse_score(text) == (expected, None)


def test_parse_score_reports_no_number_as_an_error_not_a_zero() -> None:
    score, error = parse_score("I cannot rate this.")
    assert score is None and error is not None


def test_the_grounded_rater_checks_figures_and_abstains_on_judge_only_shapes() -> None:
    row = _update_row()
    lookup = case_from_row(row, answer=AnswerOutcome(golden="Revenue was 4,200 in FY25 for INC0000001."))
    rater = GroundedRater()
    assert rater(lookup, "FY25 revenue: 4200 (INC0000001)") == (1.0, None)
    assert rater(lookup, "Revenue was 9,999.") == (0.0, None)
    assert rater(lookup, "In FY25 revenue was 9,999.") == (round(1 / 3, 4), None)
    causal = case_from_row(row, answer=AnswerOutcome(golden="Because x, y.", rubric=EvaluationType.CAUSAL_MULTI_HOP))
    assert rater(causal, "Because x, y.")[0] is None
    refusal = case_from_row(row, answer=AnswerOutcome(golden="The corpus holds no 2026 figure.", expects_abstention=True))
    assert rater(refusal, "I cannot find that in the records.") == (1.0, None)
    assert rater(refusal, "It was 3,000 in 2026.") == (0.0, None)


def test_artifacts_are_graded_on_the_records_they_rest_on(grammar_corpus: Any) -> None:
    cases = cases_from_corpus(grammar_corpus)
    healthy = next(case for case in cases if not case.trajectory.failures)
    assert healthy.outcomes.unstructured is not None and healthy.outcomes.unstructured.required_records
    service = service_for(cases, grammar_corpus.connector_data.records)
    reference = ReferenceAgent(cases)

    class Cites:
        name = "cites"

        def run(self, task: Any, tools: Any) -> AgentResponse:
            reference.run(task, tools)
            return AgentResponse(answer="done", artifacts=(ProducedArtifact(name="memo", text="see evidence",
                                                                             cites=healthy.outcomes.unstructured.required_records),))

    result = run_case(service, healthy, Cites())
    assert result.score is not None and result.score.outcomes.grounding == 1.0
    assert result.score.outcomes.artifacts_produced == 1


# -- Eval Studio round trip ------------------------------------------------------


def test_eval_studio_results_import_as_an_answer_axis_only_run(tmp_path: Path) -> None:
    cases = _hand_cases()
    csv_path = tmp_path / "eval_results.csv"
    csv_path.write_text(
        "query,golden,fetched,ttft,ttfa,ttlt,score,scoreError\n"
        f'"{cases[0].query}",moved,Moved to open.,0.4,0.6,1.9,0.9,\n'
        f'"{cases[1].query}",removed,Error: 429,0,0,0,0,\n'
        '"a query no case asks",x,y,0,0,0,1,\n',
        encoding="utf-8",
    )
    report = import_studio_results(csv_path, cases)
    assert [r.status for r in report.results] == ["graded", "error"]
    graded = report.results[0]
    assert graded.score is not None and graded.score.score == 0.9 and graded.score.assertion_status == "unobserved"
    assert graded.latency is not None and graded.latency.ttlt == 1.9 and graded.latency.ttft == 0.4
    summary = write_run(tmp_path / "studio", report)
    assert summary.errors == 1 and summary.timed == 1 and summary.mean_ttlt == 1.9
    duplicate = (cases[0], case_from_row({**_update_row(), "id": "upd2"}))
    with pytest.raises(ValueError, match="cannot be attributed"):
        import_studio_results(csv_path, duplicate)


# -- CLI -------------------------------------------------------------------------


def test_the_cli_runs_compares_and_names_the_gaps(grammar_corpus: Any, tmp_path: Path) -> None:
    export_corpus(grammar_corpus, tmp_path / "corpus")
    assert load_exported_corpus(tmp_path / "corpus") == grammar_corpus
    result = runner.invoke(app, ["evalrun", "cases", str(tmp_path / "corpus"), "--json"])
    assert result.exit_code == 0, result.output
    coverage = json.loads(result.output)
    assert coverage["cases"] == len(grammar_corpus.queries) and coverage["deletes"] == 0
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path / "corpus"), "-o", str(tmp_path / "ref"), "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "3/3 passed" in result.output
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path / "corpus"), "-o", str(tmp_path / "lazy"), "--limit", "3",
                                 "--agent", "lazy", "--timed"])
    assert result.exit_code == 0, result.output
    assert "latency: mean ttlt" in result.output
    result = runner.invoke(app, ["evalrun", "compare", str(tmp_path / "ref"), str(tmp_path / "lazy")])
    assert result.exit_code == 0, result.output
    assert "3 regressed" in result.output
    result = runner.invoke(app, ["evalrun", "summarize", str(tmp_path / "ref"), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["pass_rate"] == 1.0
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path / "corpus"), "-o", str(tmp_path / "x"), "--agent", "magic"])
    assert result.exit_code != 0
    assert "is not one of" in result.output
