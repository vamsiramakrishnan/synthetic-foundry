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


def test_an_installed_harness_is_one_flag_not_an_adapter_script(
    grammar_corpus: Any, tmp_path: Path
) -> None:
    """`--harness codex` is the bundled adapter; naming a child twice is refused."""
    from worldloom.studio.harness import adapter_command

    corpus = str(tmp_path / "corpus")
    out = str(tmp_path / "run")
    result = runner.invoke(app, ["evalrun", "run", corpus, "-o", out, "--harness", "gpt"])
    assert result.exit_code != 0 and "codex or claude" in result.output
    result = runner.invoke(
        app, ["evalrun", "run", corpus, "-o", out, "--harness", "codex", "--exec", "./adapter.sh"]
    )
    assert result.exit_code != 0 and "give one" in result.output
    result = runner.invoke(app, ["evalrun", "plan", corpus, "-o", out, "--harness", "gpt"])
    assert result.exit_code != 0 and "codex or claude" in result.output
    # The same child every seam is offered, and it is this package's own module.
    assert "worldloom.studio.harness" in adapter_command("codex")


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


# -- harness transports ----------------------------------------------------------


def _exec_cmd(*parts: object) -> str:
    import os
    import shlex
    import subprocess
    import sys

    argv = [sys.executable, *(str(part) for part in parts)]
    return subprocess.list2cmdline(argv) if os.name == "nt" else " ".join(shlex.quote(part) for part in argv)


_CHILD = """
import json, sys
doc = json.load(sys.stdin)
assert doc["schema"] == "worldloom.evalrun-turn/v2", doc.get("schema")
assert all(tool["name"] for tool in doc["tools"])
if not doc["transcript"]:
    read = next(t for t in doc["tools"] if t["name"] == "servicenow.get_record")
    print(json.dumps({"call": {"tool": read["name"], "arguments": {"id": "INC0000001"}}}))
elif len(doc["transcript"]) == 1:
    seen = doc["transcript"][0]["result"]
    assert "error" not in doc["transcript"][0], doc["transcript"][0]
    print(json.dumps({"call": {"tool": "servicenow.update_record", "arguments": {"id": "INC0000001", "fields": {"state": "open"}}}}))
elif len(doc["transcript"]) == 2:
    print(json.dumps({"call": {"tool": "servicenow.get_record", "arguments": {"id": "INC0000001"}}}))
else:
    state = doc["transcript"][-1]["result"].get("state")
    print(json.dumps({"answer": f"INC0000001 is now {state}.", "artifacts": [{"name": "note", "text": "moved", "cites": ["f1"]}]}))
"""


def test_an_executable_is_the_agent_one_subprocess_per_turn(tmp_path: Path) -> None:
    from worldloom.evalrun import ExecAgent

    child = tmp_path / "child.py"
    child.write_text(_CHILD, encoding="utf-8")
    update, _ = _hand_cases()
    result = run_case(_hand_service(), update, ExecAgent(_exec_cmd(child), timeout=60))
    assert result.status == "graded", result.error
    assert result.score is not None and result.score.passed, result.score.model_dump()
    assert result.notes == ("answered on turn 4",)
    assert result.score.outcomes.artifacts_produced == 1
    assert result.agent.startswith("exec:")


def test_a_child_that_breaks_the_turn_contract_is_an_error_row_with_its_stderr(tmp_path: Path) -> None:
    from worldloom.evalrun import ExecAgent

    crashes = tmp_path / "crash.py"
    crashes.write_text("import sys; sys.stderr.write('adapter exploded\\n'); sys.exit(3)", encoding="utf-8")
    update, _ = _hand_cases()
    result = run_case(_hand_service(), update, ExecAgent(_exec_cmd(crashes), timeout=60))
    assert result.status == "error"
    assert result.error is not None and "exec_failed" in result.error and "adapter exploded" in result.error

    silent = tmp_path / "silent.py"
    silent.write_text("print('{}')", encoding="utf-8")
    result = run_case(_hand_service(), update, ExecAgent(_exec_cmd(silent), timeout=60))
    assert result.status == "error" and "neither" in (result.error or "")

    looping = tmp_path / "loop.py"
    looping.write_text("import json; print(json.dumps({'call': {'tool': 'servicenow.get_record', 'arguments': {'id': 'INC0000001'}}}))", encoding="utf-8")
    result = run_case(_hand_service(), update, ExecAgent(_exec_cmd(looping), timeout=60, max_turns=3))
    assert result.status == "graded" and result.calls == 3
    assert "turn budget of 3 exhausted" in result.notes[0]


def test_requests_carry_only_what_the_agent_may_know_and_responses_replay(tmp_path: Path) -> None:
    from worldloom.evalrun import ResponsesAgent, load_responses, requests_document

    cases = _hand_cases()
    document = requests_document(_hand_service(), cases)
    assert document["schema"] == "worldloom.evalrun-requests/v1"
    assert [entry["case_id"] for entry in document["cases"]] == ["upd", "del"]
    text = json.dumps(document)
    assert "expected_dag" not in text and "assertions" not in text and '"f1"' not in text
    delete_tools = {tool["name"] for tool in document["cases"][1]["tools"]}
    assert "sharepoint.delete_list_item" in delete_tools and "servicenow.get_record" not in delete_tools

    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps({"schema": "worldloom.evalrun-responses/v1", "cases": {
        "upd": {"calls": [["servicenow.get_record", {"id": "INC0000001"}],
                          ["servicenow.update_record", {"id": "INC0000001", "fields": {"state": "open"}}],
                          ["servicenow.get_record", {"id": "INC0000001"}]],
                "answer": "Moved to open.", "artifacts": [{"name": "n", "text": "moved", "cites": ["f1"]}]},
    }}), encoding="utf-8")
    agent = ResponsesAgent(load_responses(responses))
    service = _hand_service()
    report = run_cases(service, cases, agent)
    assert report.results[0].graded and report.results[0].score is not None and report.results[0].score.passed
    assert report.results[1].status == "error" and "not_attempted" in (report.results[1].error or "")

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"upd": {"calls": [["only-a-tool"]]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="list of \\[tool, arguments\\]"):
        load_responses(bad)


def test_the_session_is_the_sdk_entry(grammar_corpus: Any, tmp_path: Path) -> None:
    from worldloom.evalrun import EvalSession

    export_corpus(grammar_corpus, tmp_path / "corpus")
    session = EvalSession.from_export(tmp_path / "corpus", limit=3)
    assert session.coverage().cases == 3
    ceiling = session.reference()
    floor = session.run(ScriptedAgent([], name="lazy"), label="lazy")
    assert ceiling.case_set == floor.case_set
    assert session.summary("reference").pass_rate == 1.0
    assert set(session.compare("reference", "lazy").regressions) == {case.id for case in session.cases}
    session.write("lazy", tmp_path / "lazy")
    assert read_run(tmp_path / "lazy").agent == "lazy"
    with pytest.raises(KeyError, match="no run labelled"):
        session.summary("nope")


def test_the_mcp_tools_and_the_seam_expose_the_same_surface(grammar_corpus: Any, tmp_path: Path) -> None:
    from worldloom import mcp
    from worldloom.evalrun import seam_contract
    from worldloom.seams import seam_manifest

    export_corpus(grammar_corpus, tmp_path / "corpus")
    coverage = mcp.call("evalrun_cases", {"cases": str(tmp_path / "corpus"), "limit": 2})
    assert coverage["cases"] == 2
    summary = mcp.call("evalrun_run", {"cases": str(tmp_path / "corpus"), "out": str(tmp_path / "ref"), "limit": 2})
    assert summary["pass_rate"] == 1.0
    lazy = mcp.call("evalrun_run", {"cases": str(tmp_path / "corpus"), "out": str(tmp_path / "lazy"), "limit": 2, "agent": "lazy"})
    assert lazy["pass_rate"] == 0.0
    delta = mcp.call("evalrun_compare", {"baseline": str(tmp_path / "ref"), "recent": str(tmp_path / "lazy")})
    assert len(delta["regressions"]) == 2
    assert mcp.call("evalrun_summarize", {"run": str(tmp_path / "ref")})["graded"] == 2
    assert "error" in mcp.call("evalrun_run", {"cases": str(tmp_path / "corpus"), "out": str(tmp_path / "x"), "agent": "magic"})
    for tool in mcp.TOOLS:
        assert any(subject in tool["schema"]["required"] for subject in mcp.SUBJECTS), tool["name"]

    seam = {item["name"]: item for item in seam_manifest()["seams"]}["evalrun"]
    assert seam["canonical_import"] == "worldloom.evalrun"
    contract = seam["contract"]
    assert contract == seam_contract()
    assert contract["axes"] == ["plan", "trajectory", "outcomes"]
    assert set(contract["mcp_tools"]) == {tool["name"] for tool in mcp.TOOLS if tool["name"].startswith("evalrun_")}


# -- served scoring and the exec rater ------------------------------------------


def test_a_served_run_is_scored_on_three_axes_from_what_the_service_observed() -> None:
    service = _hand_service()
    run = service.begin("alice", "upd")
    rid = run["run_id"]
    service.call("alice", rid, "servicenow.get_record", {"id": "INC0000001"})
    service.call("alice", rid, "servicenow.update_record", {"id": "INC0000001", "fields": {"state": "open"}})
    service.call("alice", rid, "servicenow.get_record", {"id": "INC0000001"})
    document = service.score("alice", rid, answer="Moved to open.",
                             artifacts=[{"name": "note", "text": "moved", "cites": ["f1"]}])
    assert document["status"] == "graded" and document["agent"] == "served:alice"
    assert document["score"]["passed"], document["score"]
    assert document["score"]["outcomes"]["diff"]["updated"] == ["f1"]
    assert document["score"]["assertion_status"] == "ok"
    # Scoring leaves the run open; ending still grades the assertions.
    assert service.end("alice", rid)["grade"]["status"] == "ok"

    blind = service.begin("bob", "del")
    service.call("bob", blind["run_id"], "sharepoint.delete_list_item", {"id": "item-1"})
    document = service.score("bob", blind["run_id"])
    assert [f["law"] for f in document["score"]["trajectory"]["safety"]] == ["destructive_without_read"]
    assert document["score"]["outcomes"]["diff"]["deleted"] == ["l1"]
    assert not document["score"]["passed"]
    service.end("bob", blind["run_id"])


def test_eval_score_is_served_over_mcp_and_imports_as_a_run(tmp_path: Path) -> None:
    pytest.importorskip("mcp.server.mcpserver")
    from starlette.testclient import TestClient

    from worldloom.connectors import create_connector_app

    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    tokens = {"alice": "alice-private-evaluation-secret"}
    with TestClient(create_connector_app(_hand_service(), bearer_tokens=tokens), base_url="http://localhost") as client:
        _served_round_trip(client, headers, tokens, tmp_path)


def _served_round_trip(client: Any, headers: dict[str, str], tokens: dict[str, str], tmp_path: Path) -> None:
    def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = client.post("/mcp", headers={**headers, "Authorization": f"Bearer {tokens['alice']}"},
                               json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": name, "arguments": arguments}})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result.get("isError"), result
        return result.get("structuredContent") or json.loads(result["content"][0]["text"])

    listed = client.post("/mcp", headers={**headers, "Authorization": f"Bearer {tokens['alice']}"},
                         json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()["result"]
    assert "eval_score" in {tool["name"] for tool in listed["tools"]}
    rid = call("eval_begin", {"query_id": "upd"})["run_id"]
    call("servicenow.get_record", {"run_id": rid, "id": "INC0000001"})
    call("servicenow.update_record", {"run_id": rid, "id": "INC0000001", "fields": {"state": "open"}})
    call("servicenow.get_record", {"run_id": rid, "id": "INC0000001"})
    scored = call("eval_score", {"run_id": rid, "answer": "Moved to open.",
                                 "artifacts": [{"name": "note", "text": "moved", "cites": ["f1"]}]})
    assert scored["score"]["passed"], scored["score"]
    call("eval_end", {"run_id": rid})

    ledger = tmp_path / "served.jsonl"
    ledger.write_text(json.dumps(scored) + "\n", encoding="utf-8")
    from worldloom.evalrun import import_served

    report = import_served(ledger, _hand_cases())
    assert [r.status for r in report.results] == ["graded", "error"]
    assert report.results[0].agent == "served" and report.results[0].score is not None and report.results[0].score.passed
    assert "not_attempted" in (report.results[1].error or "")
    ledger.write_text(json.dumps({**scored, "case_id": "nope"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not in this case set"):
        import_served(ledger, _hand_cases())


def test_the_exec_rater_judges_over_the_seam_and_reports_outages_as_errors(tmp_path: Path) -> None:
    from worldloom.evalrun import exec_rater

    lookup = case_from_row(_update_row(), answer=AnswerOutcome(golden="Revenue was 4,200 in FY25."))
    judge = tmp_path / "judge.py"
    judge.write_text(
        "import json, sys\n"
        "doc = json.load(sys.stdin)\n"
        "assert doc['schema'] == 'worldloom.evalrun-rating/v1' and 'Golden Response:' in doc['prompt']\n"
        "print(json.dumps({'text': 'Score: 0.85 (between 0.0 and 1.0)'}))\n",
        encoding="utf-8",
    )
    assert exec_rater(_exec_cmd(judge), timeout=60)(lookup, "4,200 in FY25") == (0.85, None)
    numeric = tmp_path / "numeric.py"
    numeric.write_text("import json; print(json.dumps({'score': 7}))", encoding="utf-8")
    assert exec_rater(_exec_cmd(numeric), timeout=60)(lookup, "x") == (1.0, None)
    broken = tmp_path / "broken.py"
    broken.write_text("import sys; sys.stderr.write('quota\\n'); sys.exit(2)", encoding="utf-8")
    score, error = exec_rater(_exec_cmd(broken), timeout=60)(lookup, "x")
    assert score is None and error is not None and "exec_failed" in error and "quota" in error
    silent = tmp_path / "silent.py"
    silent.write_text("print('{}')", encoding="utf-8")
    assert exec_rater(_exec_cmd(silent), timeout=60)(lookup, "x")[1] is not None


def test_the_cli_takes_an_exec_rater_and_imports_served_results(grammar_corpus: Any, tmp_path: Path) -> None:
    export_corpus(grammar_corpus, tmp_path / "corpus")
    judge = tmp_path / "judge.py"
    judge.write_text("import json; print(json.dumps({'score': 1.0}))", encoding="utf-8")
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path / "corpus"), "-o", str(tmp_path / "ref"), "--limit", "2",
                                 "--rater", f"exec:{_exec_cmd(judge)}"])
    assert result.exit_code == 0, result.output
    assert "2/2 passed" in result.output
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path / "corpus"), "-o", str(tmp_path / "x"), "--rater", "magic"])
    assert result.exit_code != 0 and "exec:<command>" in result.output
    served = tmp_path / "served.jsonl"
    served.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["evalrun", "import-served", str(tmp_path / "corpus"), str(served), "-o", str(tmp_path / "served")])
    assert result.exit_code == 0, result.output
    assert "0/0 passed" in result.output and f"{len(grammar_corpus.queries)} error(s) excluded" in result.output


# -- planned deletes ---------------------------------------------------------------


def _delete_corpus() -> Any:
    from worldloom.enterprise_specs import DestinationRole, Operation

    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    scenario = operational_profile("retail")
    scenario = scenario.model_copy(update={"coverage": scenario.coverage.model_copy(update={"failures": ("none",)})})
    # A delete chain needs a destination whose connector can remove what it
    # created; the retail profile drafts email, which nothing deletes.
    workflow = scenario.additional_workflows[0].model_copy(update={
        "destinations": (DestinationRole(connector="sharepoint", entities=("file",),
                                         operations=(Operation.CREATE,), formats=("docx",)),),
    })
    scenario = scenario.model_copy(update={"additional_workflows": (workflow,),
                                           "connectors": (*scenario.connectors, "sharepoint")})
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(scenario)
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(3).with_dag_grammar("delete_chain")
    )
    corpus, _ = harness.build()
    return corpus


@pytest.fixture(scope="module")
def delete_corpus() -> Any:
    return _delete_corpus()


def test_a_planned_delete_chain_is_graded_on_every_axis(delete_corpus: Any) -> None:
    cases = cases_from_corpus(delete_corpus)
    coverage = axis_coverage(cases)
    assert coverage.deletes == len(cases) == 3 and coverage.shapes == {"delete_chain": 3}
    case = cases[0]
    assert [node.id for node in case.plan.tool_nodes][-4:] == ["write", "verify-write", "delete", "verify-deleted"]
    assert case.plan.tool_nodes[-2].op == "delete"
    # The record to delete is the one the run creates: no fixture can name it.
    assert case.outcomes.of_kind("delete")[0].fixture is None
    assert [(failure.node, failure.kind) for failure in case.trajectory.failures] == [("verify-deleted", "not_found")]

    report = run_cases(service_for(cases, delete_corpus.connector_data.records), cases, ReferenceAgent(cases))
    for result in report.results:
        assert result.graded and result.score is not None and result.score.passed, (result.error, result.score)
        matches = {match.expected.kind: match for match in result.score.outcomes.structured}
        assert matches["create"].met and matches["delete"].met
        assert matches["create"].record == matches["delete"].record
        # Created and deleted within the run: invisible to the diff, visible to the spans.
        assert result.score.outcomes.diff.created == () and result.score.outcomes.diff.deleted == ()
        assert result.score.outcomes.collateral == () and result.score.outcomes.grounding == 1.0
        assert (result.score.trajectory.failures_honoured, result.score.trajectory.failures_expected) == (1, 1)
        assert result.score.trajectory.error_codes == {"not_found": 1} and result.score.trajectory.safety == ()
        assert result.score.assertion_status == "behavior" and result.score.assertion_fails == ()


def test_an_agent_that_creates_and_keeps_fails_the_delete_not_the_create(delete_corpus: Any) -> None:
    from worldloom.evalrun import ToolCall

    cases = cases_from_corpus(delete_corpus)[:1]
    case = cases[0]
    records = delete_corpus.connector_data.records
    ceiling = run_case(service_for(cases, records), case, ReferenceAgent(cases))
    assert ceiling.graded
    kept_calls = [ToolCall(tool=span["tool"], arguments=span["args"]) for span in ceiling.spans
                  if span["node"] not in {"delete", "verify-deleted"}]
    kept = run_case(service_for(cases, records), case, ScriptedAgent(kept_calls, name="keeper", answer="Filed it."))
    assert kept.graded and kept.score is not None and not kept.score.passed
    matches = {match.expected.kind: match for match in kept.score.outcomes.structured}
    assert matches["create"].met and not matches["delete"].met
    assert matches["delete"].detail == "no record of the entity was deleted"
    assert kept.score.outcomes.diff.created == (matches["create"].record,)
    assert kept.score.plan.missing_nodes == ("delete", "verify-deleted")
    assert kept.score.trajectory.failures_honoured == 0
    assert "not_deleted:delete" in kept.score.assertion_fails
    assert "failure_not_observed:verify-deleted:not_found" in kept.score.assertion_fails


def test_a_delete_by_the_id_the_readback_returned_attributes_after_the_record_is_gone(delete_corpus: Any) -> None:
    from worldloom.connector_emulator import ConnectorError
    from worldloom.evalrun import CallableAgent, ToolSurface

    cases = cases_from_corpus(delete_corpus)[:1]
    case = cases[0]
    records = delete_corpus.connector_data.records
    ceiling = run_case(service_for(cases, records), case, ReferenceAgent(cases))
    prefix = [(span["tool"], span["args"]) for span in ceiling.spans if span["node"] not in {"verify-write", "delete", "verify-deleted"}]
    readback = next(span for span in ceiling.spans if span["node"] == "verify-write")

    def native_id_agent(task: Any, tools: ToolSurface) -> AgentResponse:
        for tool, arguments in prefix:
            tools.call(tool, **arguments)
        # An external agent addresses the record by the id the connector
        # returned, not by the fid the emulator keeps; after the delete the
        # emulator has forgotten that id and the readback must still attribute.
        seen = tools.call(readback["tool"], **readback["args"])
        native = str(seen["id"])
        tools.call("sharepoint.delete_file", id=native)
        with pytest.raises(ConnectorError):
            tools.call("sharepoint.get_file", id=native)
        return AgentResponse(answer="Removed it again.")

    result = run_case(service_for(cases, records), case, CallableAgent(native_id_agent, name="native-id"))
    assert result.graded and result.score is not None, result.error
    assert result.score.plan.observed_nodes == result.score.plan.expected_nodes
    assert result.score.passed, result.score.model_dump()


# -- plan-only grading -------------------------------------------------------------


def test_the_plan_axis_is_graded_without_executing(grammar_corpus: Any) -> None:
    from worldloom.evalrun import (
        EvalSession,
        PlannedDag,
        PlannedNode,
        ReferencePlanner,
        grade_planned,
        parse_plan,
        plan_requests_document,
    )

    session = EvalSession.from_corpus(grammar_corpus)
    ceiling = session.plan(ReferencePlanner(session.cases))
    assert all(row.graded and row.score is not None and row.score.passed and row.calls == 0 for row in ceiling.results)
    assert all(row.score is not None and row.score.observed == ("plan",) for row in ceiling.results)
    session.reference()
    delta = session.compare("reference", "plan:reference")
    assert delta.axis_deltas.plan == 0.0 and delta.regressions == () and delta.stable == len(session.cases)
    # An axis one side never observed has no delta and no mean.
    assert delta.axis_deltas.trajectory is None and delta.axis_deltas.outcomes is None
    summary = session.summary("plan:reference")
    assert summary.means.plan == 1.0 and summary.means.trajectory is None and summary.means.outcomes is None
    assert summary.assertion_status == {"unobserved": len(session.cases)}

    document = plan_requests_document(session.service(), session.cases[:1])
    text = json.dumps(document)
    assert document["for"] == "plan" and "expected_dag" not in text and "assertions" not in text
    assert document["response_schema"]["schema"] == "worldloom.evalrun-plans/v1"

    case = next(case for case in session.cases if case.plan.shape == "map_read")
    tools = [f"{node.connector}.{node.tool}" for node in case.plan.tool_nodes]
    assert [node.id for node in case.plan.tool_nodes] == ["read-0", "fetch-0", "write", "verify-write"]
    # Graded by tool name and reachability: a planner's own ids and an extra
    # hop of its own do not cost it the edge.
    renamed = PlannedDag(nodes=tuple(PlannedNode(id=f"step{index}", tool=tool, depends_on=(f"step{index - 1}",) if index else ())
                                     for index, tool in enumerate(tools)))
    assert grade_planned(case, renamed).passed
    partial = parse_plan({"plan": {"nodes": [{"tool": tools[0]}, {"tool": tools[-2], "depends_on": ["n0"]},
                                             {"tool": "servicenow.create_record", "depends_on": ["n0"]}]}})
    grade = grade_planned(case, partial)
    assert grade.missing_verify == (case.plan.of_kind("verify")[-1],) and grade.extra_writes == 1
    assert grade.unattributed_calls == 1 and not grade.passed
    # The readback planned before the write it reads back: the edge is missing.
    backwards = PlannedDag(nodes=(PlannedNode(id="r", tool=tools[0]), PlannedNode(id="v", tool=tools[-1], depends_on=("r",)),
                                  PlannedNode(id="w", tool=tools[-2], depends_on=("v",))))
    assert grade_planned(case, backwards).edge_recall == 0.0
    with pytest.raises(ValueError, match="cycle"):
        PlannedDag(nodes=(PlannedNode(id="a", tool=tools[0], depends_on=("b",)), PlannedNode(id="b", tool=tools[1], depends_on=("a",))))
    with pytest.raises(ValueError, match="unknown node"):
        parse_plan({"nodes": [{"tool": tools[0], "depends_on": ["ghost"]}]})


_PLANNER = """
import json, sys
doc = json.load(sys.stdin)
assert doc["schema"] == "worldloom.evalrun-plan/v1", doc.get("schema")
assert "transcript" not in doc and doc["tools"]
reads = [t["name"] for t in doc["tools"] if t["annotations"]["readOnlyHint"]]
print(json.dumps({"plan": {"nodes": [{"id": "r", "tool": reads[0]}]}}))
"""


def test_the_cli_grades_planners_over_the_exec_seam_and_from_a_plans_file(grammar_corpus: Any, tmp_path: Path) -> None:
    from worldloom import mcp
    from worldloom.evalrun import (
        EvalSession,
        ExecPlanner,
        reference_plan,
        seam_contract,
    )

    export_corpus(grammar_corpus, tmp_path / "corpus")
    child = tmp_path / "planner.py"
    child.write_text(_PLANNER, encoding="utf-8")
    result = runner.invoke(app, ["evalrun", "plan", str(tmp_path / "corpus"), "-o", str(tmp_path / "exec"), "--limit", "2",
                                 "--exec", _exec_cmd(child), "--timeout", "60"])
    assert result.exit_code == 0, result.output
    assert "plan axis only" in result.output and "0/2 passed" in result.output
    ledger = read_run(tmp_path / "exec")
    assert all(row.graded and row.calls == 0 and row.score is not None and 0 < row.score.plan.score < 1 for row in ledger.results)

    crash = tmp_path / "crash.py"
    crash.write_text("import sys; sys.stderr.write('planner exploded\\n'); sys.exit(2)", encoding="utf-8")
    session = EvalSession.from_corpus(grammar_corpus, limit=1)
    report = session.plan(ExecPlanner(_exec_cmd(crash), timeout=60))
    assert report.results[0].status == "error" and "planner exploded" in (report.results[0].error or "")

    result = runner.invoke(app, ["evalrun", "requests", str(tmp_path / "corpus"), "--for", "plan", "-o", str(tmp_path / "requests.json")])
    assert result.exit_code == 0, result.output
    requests = json.loads((tmp_path / "requests.json").read_text(encoding="utf-8"))
    plans = {"schema": "worldloom.evalrun-plans/v1",
             "cases": {entry["case_id"]: reference_plan(next(case for case in session.cases if case.id == entry["case_id"])).model_dump(mode="json")
                       for entry in requests["cases"][:1]}}
    (tmp_path / "plans.json").write_text(json.dumps(plans), encoding="utf-8")
    result = runner.invoke(app, ["evalrun", "plan", str(tmp_path / "corpus"), "-o", str(tmp_path / "scripted"), "--limit", "2",
                                 "--agent", f"scripted:{tmp_path / 'plans.json'}", "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["graded"] == 1 and summary["errors"] == 1 and summary["means"]["trajectory"] is None
    result = runner.invoke(app, ["evalrun", "plan", str(tmp_path / "corpus"), "-o", str(tmp_path / "x"), "--agent", "magic"])
    assert result.exit_code != 0 and "scripted:<plans.json>" in result.output

    planned = mcp.call("evalrun_plan", {"cases": str(tmp_path / "corpus"), "out": str(tmp_path / "mcp"), "limit": 2})
    assert planned["pass_rate"] == 1.0 and planned["means"]["outcomes"] is None
    contract = seam_contract()
    assert "evalrun plan" in contract["commands"] and "evalrun_plan" in contract["mcp_tools"]
    assert contract["schemas"]["plan"] == "worldloom.evalrun-plan/v1"


def test_a_mapped_write_claims_every_record_it_produced() -> None:
    """A `for_each` write is one node and one record per item; none of them is collateral."""
    from copy import deepcopy

    from test_enterprise_dag import compiled

    from worldloom.connector_eval_runtime import run_eval_row
    from worldloom.evalrun import grade_outcomes

    row, data = compiled("map_read")
    forged = deepcopy(row)
    writer = next(node for node in forged["expected_dag"]["nodes"] if node["id"] == "write")
    writer["for_each"] = {"node": "read-0", "limit": 100}
    writer["payload"].pop("name", None)
    writer["bindings"]["name"] = {"node": "read-0", "select": "item", "path": ["title"]}
    # One write per search hit; the readback is dropped so the row stays a
    # plain fan-out of creates rather than a second mapped node.
    forged["expected_dag"]["nodes"] = [node for node in forged["expected_dag"]["nodes"] if node["node_kind"] != "verify"]
    forged["expected_dag"]["edges"] = [edge for edge in forged["expected_dag"]["edges"] if edge[1] != "verify-write"]
    result = run_eval_row(forged, data)
    assert result.grade["fails"] == []
    created = [fid for span in result.spans if span.node == "write" for fid in span.writes]
    assert len(created) == 3
    case = case_from_row(forged, query="Write one record per matching issue.")
    before = {str(record["fid"]): dict(record) for record in data}
    grade = grade_outcomes(case, before, result.post_state, spans=result.spans)
    match = next(item for item in grade.structured if item.expected.node == "write")
    assert match.met and set(match.records) == set(created) and match.record == created[0]
    assert grade.collateral == () and grade.passed, grade.model_dump()


def test_comparison_and_summary_speak_only_of_observed_axes(grammar_corpus: Any) -> None:
    from worldloom.evalrun import EvalSession, ReferencePlanner, ScriptedAgent

    session = EvalSession.from_corpus(grammar_corpus, limit=2)
    session.reference()
    session.run(ScriptedAgent([], name="lazy"), label="lazy")
    session.plan(ReferencePlanner(session.cases))
    # Executed against plan-only: the overall delta is the plan delta, not
    # the executed mean minus a plan-only score.
    plan_vs_lazy = session.compare("lazy", "plan:reference")
    assert plan_vs_lazy.axis_deltas.plan is not None and plan_vs_lazy.axis_deltas.plan > 0
    assert all(item.delta == item.axes.get("plan", item.delta) for item in plan_vs_lazy.deltas if item.delta is not None)
    assert plan_vs_lazy.axis_deltas.trajectory is None and plan_vs_lazy.axis_deltas.outcomes is None
    assert len(plan_vs_lazy.improvements) == 2, plan_vs_lazy.model_dump()
    same = session.compare("reference", "plan:reference")
    assert same.stable == 2 and same.mean_delta == 0.0
    # Two runs with no axis in common have no delta and no verdict.
    from worldloom.evalrun import RunReport
    from worldloom.evalrun.grading import (
        CaseScore,
        unobserved_outcomes,
        unobserved_plan,
        unobserved_trajectory,
    )
    from worldloom.evalrun.runner import CaseResult

    answer_only = RunReport(agent="studio", principal="eval-studio", case_set=session.runs["reference"].case_set, results=tuple(
        CaseResult(case_id=case.id, query=case.query, agent="studio", status="graded",
                   score=CaseScore(plan=unobserved_plan(), trajectory=unobserved_trajectory(), outcomes=unobserved_outcomes(0.9),
                                   assertion_status="unobserved", observed=("outcomes",), score=0.9, passed=True))
        for case in session.cases))
    session.runs["answers"] = answer_only
    disjoint = session.compare("plan:reference", "answers")
    assert all(item.verdict == "unobserved" and item.delta is None for item in disjoint.deltas)
    assert disjoint.stable == 0 and disjoint.improvements == () and disjoint.regressions == ()
    # Rates over the trajectory vocabulary exist only where a trajectory was observed.
    planned = session.summary("plan:reference")
    assert planned.exact_match_rate is None and planned.mean_calls is None
    executed = session.summary("reference")
    assert executed.exact_match_rate == 1.0 and executed.mean_calls is not None and executed.mean_calls > 0



# -- grader defects found by the reference on a project-built world ----------


def _list_item_row(nodes: list[dict[str, Any]], edges: list[list[str]], assertions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": "li", "query": "Read the stale row, then act on it.",
            "expected_dag": {"nodes": nodes, "edges": edges}, "assertions": assertions}


def _list_item_service(case: EvalCase) -> Any:
    return service_for((case,), _records(), definitions={"sharepoint": load_connector_definition("sharepoint")})


def test_an_update_the_plan_then_deletes_is_met_from_the_spans() -> None:
    """A delete chain updates a record and then removes it; the post-state cannot show the update.

    Found by the reference on a project-built world: the update read
    "<fid> is gone" and the case failed on its own ceiling. The service's
    span recorded the update, and the delete that followed is the other half
    of the same plan, so the update is met when the expectation names no
    target state to check.
    """
    row = _list_item_row(
        [{"id": "read", "server": "sharepoint", "tool": "get_list_items", "fixture": "l1", "entity": "list_item", "op": "search"},
         {"id": "write", "server": "sharepoint", "tool": "update_list_item", "fixture": "l1", "entity": "list_item", "op": "update"},
         {"id": "delete", "server": "sharepoint", "tool": "delete_list_item", "fixture": "l1", "entity": "list_item", "op": "delete"}],
        [["read", "write"], ["write", "delete"]],
        [{"type": "tool_called", "node": node} for node in ("read", "write", "delete")]
        + [{"type": "deleted", "node": "delete", "fixture": "l1"}],
    )
    case = case_from_row(row)
    agent = ScriptedAgent([("sharepoint.get_list_items", {"entity": "list_item", "max_results": 10}),
                           ("sharepoint.update_list_item", {"id": "item-1", "fields": {"name": "Reviewed row"}}),
                           ("sharepoint.delete_list_item", {"id": "item-1"})])
    result = run_case(_list_item_service(case), case, agent)
    assert result.score is not None, result.error
    by_node = {match.expected.node: match for match in result.score.outcomes.structured}
    assert by_node["write"].met and by_node["write"].detail == "updated, then deleted by the plan"
    assert by_node["delete"].met
    assert result.score.passed, result.score.model_dump()


def test_a_second_update_on_one_record_is_attributed_to_the_node_that_made_it() -> None:
    """Two nodes update the same record in turn; the diff shows one update.

    Found by the reference on `write_chain` rows: the marker update read
    "no record of the entity changed" because the first update had claimed
    the only changed record. A node's own successful spans say what it wrote.
    """
    row = _list_item_row(
        [{"id": "read", "server": "sharepoint", "tool": "get_list_items", "fixture": "l1", "entity": "list_item", "op": "search"},
         {"id": "write", "server": "sharepoint", "tool": "update_list_item", "fixture": "l1", "entity": "list_item", "op": "update"},
         {"id": "write-marker", "server": "sharepoint", "tool": "update_list_item", "entity": "list_item", "op": "update"}],
        [["read", "write"], ["write", "write-marker"]],
        [{"type": "tool_called", "node": node} for node in ("read", "write", "write-marker")],
    )
    case = case_from_row(row)
    agent = ScriptedAgent([("sharepoint.get_list_items", {"entity": "list_item", "max_results": 10}),
                           ("sharepoint.update_list_item", {"id": "item-1", "fields": {"name": "Reviewed row"}}),
                           ("sharepoint.update_list_item", {"id": "item-1", "fields": {"verified": True}})])
    result = run_case(_list_item_service(case), case, agent)
    assert result.score is not None, result.error
    matches = {match.expected.node: match for match in result.score.outcomes.structured}
    assert matches["write"].met and matches["write-marker"].met, result.score.outcomes.model_dump()
    assert matches["write-marker"].record == "l1"
    assert result.score.outcomes.collateral == ()


def test_a_failure_point_an_honoured_failure_blocked_is_not_expected() -> None:
    """A delete chain expects `not_found` from the readback after the delete.

    When the write the chain starts from is denied, the readback never runs.
    The grader counted it as a failure the agent did not honour and scored
    the reference 0.9 on its own trajectory. A point on a node an honoured
    failure blocked is unreachable, so it is not expected; a point the agent
    did reach and meet still counts.
    """
    from worldloom.evalrun import grade_trajectory

    row = _list_item_row(
        [{"id": "read", "server": "sharepoint", "tool": "get_list_items", "fixture": "l1", "entity": "list_item", "op": "search"},
         {"id": "write", "server": "sharepoint", "tool": "create_list_item", "entity": "list_item", "op": "create"},
         {"id": "verify-write", "server": "sharepoint", "tool": "get_list_item", "entity": "list_item", "op": "readback"},
         {"id": "delete", "server": "sharepoint", "tool": "delete_list_item", "entity": "list_item", "op": "delete"},
         {"id": "verify-deleted", "server": "sharepoint", "tool": "get_list_item", "entity": "list_item", "op": "readback"}],
        [["read", "write"], ["write", "verify-write"], ["verify-write", "delete"], ["delete", "verify-deleted"]],
        [{"type": "failure_at", "node": "verify-deleted", "kind": "not_found", "writes_persist": False, "blocked_nodes": []},
         {"type": "failure_at", "node": "write", "kind": "denied", "writes_persist": False,
          "blocked_nodes": ["verify-write", "delete", "verify-deleted"]}],
    )
    case = case_from_row(row)
    denied = [{"id": "s1", "node": "read", "tool": "sharepoint.get_list_items", "args": {}, "reads": ["l1"], "writes": []},
              {"id": "s2", "node": "write", "tool": "sharepoint.create_list_item", "args": {"name": "x"}, "reads": [], "writes": [],
               "error": {"kind": "denied", "code": 403}}]
    grade = grade_trajectory(case, denied)
    assert (grade.failures_expected, grade.failures_honoured) == (1, 1), grade.model_dump()
    assert grade.passed

    # The write went through: the chain reaches the readback, which must fail.
    reached = [denied[0],
               {"id": "s2", "node": "write", "tool": "sharepoint.create_list_item", "args": {"name": "x"}, "reads": [], "writes": ["n1"]},
               {"id": "s3", "node": "verify-write", "tool": "sharepoint.get_list_item", "args": {"id": "n1"}, "reads": ["n1"], "writes": []},
               {"id": "s4", "node": "delete", "tool": "sharepoint.delete_list_item", "args": {"id": "n1"}, "reads": [], "writes": ["n1"]},
               {"id": "s5", "node": "verify-deleted", "tool": "sharepoint.get_list_item", "args": {"id": "n1"}, "reads": [], "writes": [],
                "error": {"kind": "not_found", "code": 404}}]
    grade = grade_trajectory(case, reached)
    assert (grade.failures_expected, grade.failures_honoured) == (2, 1), "the denial was designed and did not happen"


def test_a_partial_write_on_a_delete_names_no_created_record() -> None:
    """A designed `partial_write` on a write that makes nothing has no record to check.

    Found once a delete could be planned as the primary write: its id is
    bound from the read before it, so the node carries no fixture, and the
    contract asked the grader to find a *created* record with the delete's
    name. The delete's persisted effect is the `deleted` assertion's to grade.
    """
    from worldloom.enterprise_failures import compile_failure_contract

    row = {"expected_dag": {"nodes": [
        {"id": "target", "server": "sharepoint", "tool": "get_file", "entity": "file", "op": "read", "fixture": "f1"},
        {"id": "write", "server": "sharepoint", "tool": "delete_file", "entity": "file", "op": "delete", "payload": {}},
        {"id": "verify-write", "server": "sharepoint", "tool": "get_file", "entity": "file", "op": "read"},
    ], "edges": [["target", "write"], ["write", "verify-write"]]},
        "assertions": [],
        "state_overrides": [{"kind": "partial_write", "connector": "sharepoint", "record_id": None,
                             "details": {"fail_after": 1, "rollback": False}}]}
    compiled = compile_failure_contract(row)
    failure = next(a for a in compiled["assertions"] if a["type"] == "failure_at" and a["node"] == "write")
    assert failure["writes_persist"] and "created_record" not in failure and "fixture" not in failure

    created = {**row, "expected_dag": {**row["expected_dag"], "nodes": [
        {**row["expected_dag"]["nodes"][1], "tool": "create_file", "op": "create", "payload": {"name": "pack.pdf"}}]}}
    compiled = compile_failure_contract(created)
    failure = next(a for a in compiled["assertions"] if a["type"] == "failure_at" and a["node"] == "write")
    assert failure["created_record"] == {"server": "sharepoint", "entity": "file", "name": "pack.pdf"}
