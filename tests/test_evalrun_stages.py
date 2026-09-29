"""The stages inside the axes: the queries an agent issued, the plan nodes it formed, the output it left.

Each test runs a scripted agent through the real tool surface over a small
built corpus (eight ServiceNow incidents, three of them the evidence) and
reads the stage grade the runner attached. The queries are graded by what
the emulator returned, so two differently written searches that return the
same records must score the same; a search that returns everything, or
filters on a window that excludes the evidence, must say so by name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from worldloom import packkit
from worldloom.connector_definition import load_connector_definition
from worldloom.evalrun import (
    AgentResponse,
    CallableAgent,
    PlannedDag,
    PlannedNode,
    ProducedArtifact,
    ReferencePlanner,
    ScriptedAgent,
    ToolCall,
    case_from_row,
    compare,
    grade_plan_nodes,
    grader_identity,
    plan_cases,
    read_run,
    run_case,
    run_cases,
    service_for,
    summarize,
    write_run,
)
from worldloom.evalrun.autopsy import autopsy, finding_keys, render_brief
from worldloom.evalrun.evidence import collect, render_evidence
from worldloom.evalrun.grader import axis_digest
from worldloom.evalrun.runner import RunReport

# These tests script agents in the connector definitions' own tool names
# (`jira.get_issue`), so they serve those tools; the contract surface is the default.
pytestmark = pytest.mark.usefixtures("native_surface")

GOLD = ("i1", "i2", "i3")
SUBJECT = "Weekly incident digest"


def _records() -> list[dict[str, Any]]:
    records = []
    for index in range(1, 9):
        gold = index <= 3
        records.append({
            "fid": f"i{index}", "server": "servicenow", "entity": "incident", "ident": f"INC000000{index}",
            "state": "new" if gold else "closed", "priority": "1" if gold else "3",
            "short_description": f"Incident {index}", "caller_id": "u1",
            "sys_created_on": f"2026-09-0{index}T09:00:00+08:00" if gold else "2026-08-01T09:00:00+08:00",
            "cost": 1250 * index,
        })
    return records


def _row() -> dict[str, Any]:
    return {
        "id": "digest", "query": f"Find the new incidents and draft an email titled '{SUBJECT}' summarising them.",
        "expected_dag": {"nodes": [
            {"id": "search", "server": "servicenow", "tool": "search_records", "entity": "incident",
             "node_kind": "search", "op": "search", "payload": {"predicate": {"state": "new"}, "max_results": 50},
             "expected_reads": list(GOLD)},
            {"id": "write", "server": "email", "tool": "create_draft", "entity": "message", "node_kind": "write",
             "op": "create", "payload": {"name": "digest", "fields": {"subject": SUBJECT}},
             "bindings": {"fields.evidence": {"node": "search", "path": [], "select": "all", "encoding": "value"},
                          "fields.evidence_count": {"node": "search", "path": [], "select": "count", "encoding": "value"}}},
        ], "edges": [["search", "write"]]},
        "assertions": [{"type": "tool_called", "node": "search"}, {"type": "tool_called", "node": "write"}],
    }


def _parallel_row() -> dict[str, Any]:
    """Two independent searches feeding one write: the searches may run in either order."""

    row = _row()
    row["id"] = "parallel"
    nodes = row["expected_dag"]["nodes"]
    nodes.insert(1, {"id": "search-closed", "server": "servicenow", "tool": "search_records", "entity": "incident",
                     "node_kind": "search", "op": "search", "payload": {"predicate": {"state": "closed"}},
                     "expected_reads": ["i4", "i5", "i6", "i7", "i8"]})
    row["expected_dag"]["edges"] = [["search", "write"], ["search-closed", "write"]]
    return row


def _case(row: dict[str, Any] | None = None) -> Any:
    return case_from_row(row or _row(), output_format="markdown", sections=("Summary", "Actions"))


def _definitions() -> dict[str, Any]:
    return {"servicenow": load_connector_definition("servicenow"), "email": load_connector_definition("email")}


def _service(case: Any) -> Any:
    return service_for((case,), _records(), definitions=_definitions())


def _draft(evidence: list[str] | None = None, count: int = 3, subject: str = SUBJECT) -> ToolCall:
    listed = list(GOLD) if evidence is None else evidence
    return ToolCall(tool="email.create_draft", arguments={
        "entity": "message", "name": "digest",
        "fields": {"subject": subject, "evidence": [{"id": fid} for fid in listed], "evidence_count": count}})


def _search(**arguments: Any) -> ToolCall:
    return ToolCall(tool="servicenow.search_records", arguments={"entity": "incident", **arguments})


def _run(calls: list[ToolCall], *, answer: str = "Done.", artifacts: tuple[ProducedArtifact, ...] = (),
         case: Any = None) -> Any:
    case = case or _case()
    result = run_case(_service(case), case, ScriptedAgent(calls, answer=answer, artifacts=artifacts))
    assert result.graded and result.score is not None, result.error
    return result


# -- queries --------------------------------------------------------------------


def test_equivalent_queries_written_differently_score_the_same() -> None:
    written = [
        _search(predicate={"state": "new"}),
        _search(predicate={"state": ["in", ["new"]]}),
        _search(query="state=new"),
        _search(predicate={"priority": "1"}),
    ]
    grades = [_run([call, _draft()]).score.trajectory.queries for call in written]
    for grade in grades:
        assert grade is not None
        assert grade.recall == 1.0 and grade.findings == {}
        node = grade.nodes[0]
        assert (node.found, node.needed, node.returned, node.pages) == (3, 3, 3, 1)
    assert len({grade.score for grade in grades}) == 1 and grades[0].score == 1.0
    # What each one filtered on is recorded, and differs; the score does not.
    assert grades[0].calls[0].constrained == ("state",)
    assert grades[3].calls[0].constrained == ("priority",)


def test_an_unfiltered_search_is_overfetch_with_the_missing_filter_named() -> None:
    result = _run([_search(), _draft()])
    grade = result.score.trajectory.queries
    node = grade.nodes[0]
    assert node.recall == 1.0 and node.returned == 8 and node.precision == 0.375
    assert node.overfetch == pytest.approx(8 / 3, abs=1e-3)
    assert {"query.overfetch", "query.missing_filter"} <= set(grade.findings)
    assert grade.calls[0].missing_filters == ("state",)
    assert grade.score < 1.0
    # The axes did not move: the stage refines, it never re-scores.
    assert result.score.trajectory.score == _run([_search(predicate={"state": "new"}), _draft()]).score.trajectory.score


def test_a_window_that_starts_after_the_clock_or_cuts_evidence_is_the_wrong_window() -> None:
    future = _run([_search(predicate={"state": "new", "sys_created_on": [">=", "2026-10-01T00:00:00+08:00"]}), _draft()])
    grade = future.score.trajectory.queries
    assert grade.calls[0].wrong_window == ("sys_created_on",)
    assert {"query.wrong_window", "query.missed_evidence", "query.zero_result"} <= set(grade.findings)
    cut = _run([_search(predicate={"state": "new", "sys_created_on": [">=", "2026-09-02T00:00:00+08:00"]}), _draft()])
    grade = cut.score.trajectory.queries
    assert grade.calls[0].wrong_window == ("sys_created_on",)
    assert grade.nodes[0].found == 2 and "query.missed_evidence" in grade.findings
    # A window that holds every record the step needs is no fault.
    fits = _run([_search(predicate={"state": "new", "sys_created_on": [">=", "2026-08-15T00:00:00+08:00"]}), _draft()])
    assert fits.score.trajectory.queries.findings == {}


def test_malformed_and_wrong_scope_searches_are_named() -> None:
    # ServiceNow drops a condition it cannot read (`state!!new`) and answers
    # the rest, as the vendor evaluator does by default; what it refuses is
    # an argument it cannot honour.
    malformed = _run([_search(query="state=new", start_at=-1), _search(predicate={"state": "new"}), _draft()])
    grade = malformed.score.trajectory.queries
    assert grade.calls[0].malformed and grade.findings.get("query.malformed") == 1
    assert grade.nodes[0].recall == 1.0 and grade.nodes[0].score < 1.0
    scoped = _run([ToolCall(tool="servicenow.search_records", arguments={"entity": "problem"}),
                   _search(predicate={"state": "new"}), _draft()])
    grade = scoped.score.trajectory.queries
    assert grade.calls[0].wrong_scope and grade.findings.get("query.wrong_scope") == 1


def test_paging_in_small_pages_costs_efficiency_not_evidence() -> None:
    paged = _run([_search(predicate={"state": "new"}, max_results=1, start_at=0),
                  _search(predicate={"state": "new"}, max_results=1, start_at=1),
                  _search(predicate={"state": "new"}, max_results=1, start_at=2), _draft()])
    node = paged.score.trajectory.queries.nodes[0]
    assert node.recall == 1.0 and node.pages == 3 and node.min_pages == 1
    assert node.score < 1.0


# -- plan nodes -------------------------------------------------------------------


def test_the_implied_plan_is_matched_node_by_node() -> None:
    good = _run([_search(predicate={"state": "new"}), _draft()]).score.plan.nodes
    assert good is not None and good.source == "implied" and good.score == 1.0
    skipped = _run([_draft()]).score.plan.nodes
    assert skipped.node_recall == 0.5 and "plan.node_missing:search" in skipped.findings
    backwards = _run([_draft(), _search(predicate={"state": "new"})]).score.plan.nodes
    assert backwards.misordered == (("search", "write"),) and "plan.node_misordered" in backwards.findings
    extra = _run([_search(predicate={"state": "new"}), ToolCall(tool="servicenow.get_record", arguments={"id": "i1"}),
                  _draft()]).score.plan.nodes
    assert extra.node_precision < 1.0 and "plan.node_extra:read" in extra.findings


def test_a_declared_plan_is_graded_by_dependency_and_parallel_nodes_may_run_in_any_order() -> None:
    case = _case(_parallel_row())

    def plan(*nodes: tuple[str, str, tuple[str, ...]]) -> PlannedDag:
        return PlannedDag(nodes=tuple(PlannedNode(id=node, tool=tool, depends_on=parents, entity="")
                                      for node, tool, parents in nodes))

    search, draft = "servicenow.search_records", "email.create_draft"
    one = grade_plan_nodes(case, declared=plan(("a", search, ()), ("b", search, ()), ("w", draft, ("a", "b"))),
                           definitions=_definitions())
    other = grade_plan_nodes(case, declared=plan(("b", search, ()), ("a", search, ()), ("w", draft, ("b", "a"))),
                             definitions=_definitions())
    assert one.source == "declared" and one.score == other.score == 1.0
    loose = grade_plan_nodes(case, declared=plan(("a", search, ()), ("w", draft, ("a",)), ("b", search, ("w",))),
                             definitions=_definitions())
    assert loose.matched == 3 and loose.misordered == (("search-closed", "write"),)
    assert loose.dependency_accuracy == 0.5
    extra = grade_plan_nodes(case, declared=plan(("a", search, ()), ("b", search, ()), ("w", draft, ("a", "b")),
                                                 ("x", "servicenow.update_record", ("w",))), definitions=_definitions())
    assert extra.node_precision == 0.75 and extra.extra and "plan.node_extra:update" in extra.findings
    # Declared through the response, beside the observed run: the stated DAG wins as the source.
    agent = CallableAgent(lambda task, tools: AgentResponse(planned_dag={"nodes": [
        {"id": "a", "tool": search}, {"id": "w", "tool": draft, "depends_on": ["a"]}]}), name="planner")
    stated = run_case(_service(case), case, agent).score.plan.nodes
    assert stated.source == "declared" and "plan.node_missing:search" in stated.findings


def test_a_plan_only_run_carries_the_node_breakdown_of_the_stated_dag() -> None:
    case = _case(_parallel_row())
    report = plan_cases(_service(case), (case,), ReferencePlanner((case,)))
    nodes = report.results[0].score.plan.nodes
    assert nodes is not None and nodes.source == "declared" and nodes.score == 1.0


# -- output --------------------------------------------------------------------------


def test_structured_fields_are_graded_from_the_gold_bindings_and_the_stated_subject() -> None:
    good = _run([_search(predicate={"state": "new"}), _draft()]).score.outcomes.output
    assert good is not None and good.fields_expected == 3 and good.fields_met == 3
    assert {check.source for check in good.fields} == {"records", "count", "stated"}
    wrong = _run([_search(predicate={"state": "new"}), _draft(evidence=["i1", "i2"], count=2,
                                                              subject="Digest")]).score.outcomes.output
    assert wrong.fields_met == 0 and "output.field_mismatch" in wrong.findings
    assert any("1 of 3 evidence record(s) absent" in check.detail for check in wrong.fields)


def test_sections_format_and_grounding_of_a_produced_document() -> None:
    calls = [_search(predicate={"state": "new"}), _draft()]
    full = ProducedArtifact(name="digest.md", media_type="text/markdown",
                            text="# Summary\nThree new incidents, INC0000001 first; cost 1,250.\n# Actions\nTriage.")
    good = _run(calls, artifacts=(full,), answer="Drafted: 3 incidents, cost 3,750 on INC0000003.").score.outcomes.output
    assert good.format_met is True and good.sections_missing == () and good.sections_score == 1.0
    assert good.grounding == 1.0 and good.facts == 2 and good.score == 1.0
    thin = ProducedArtifact(name="digest.html", media_type="text/html", text="<h1>Summary</h1><p>cost 9,999</p>")
    bad = _run(calls, artifacts=(thin,), answer="Done.").score.outcomes.output
    assert bad.format_met is False and bad.sections_missing == ("Actions",)
    assert bad.ungrounded == ("9,999",)
    assert {"output.wrong_format", "output.missing_section", "output.ungrounded_fact"} <= set(bad.findings)
    # No document text at all: sections and format are unobserved, not failed.
    silent = _run(calls).score.outcomes.output
    assert silent.format_met is None and silent.sections_score is None


# -- surfacing ------------------------------------------------------------------------


def _report(results: list[Any], name: str) -> RunReport:
    return RunReport(agent=name, principal="agent", case_set="set", results=tuple(results), grader=grader_identity())


def test_summary_compare_autopsy_and_brief_carry_the_stages(tmp_path: Path) -> None:
    case = _case()
    good = run_cases(_service(case), (case,), ScriptedAgent([_search(predicate={"state": "new"}), _draft()], name="good"))
    broad = run_cases(_service(case), (case,), ScriptedAgent(
        [_search(), _draft(evidence=["i1"], count=1)], name="broad"))
    assert good.grader is not None and good.grader["stages"]["enabled"] == ["output", "plan_nodes", "queries"]
    summary = summarize(broad)
    assert summary.stages is not None and summary.stages.overfetch_nodes == 1
    assert summary.stages.findings["query.overfetch"] == 1
    write_run(tmp_path / "broad", broad)
    dumped = json.loads((tmp_path / "broad" / "summary.json").read_text())
    assert "stages" in dumped
    assert read_run(tmp_path / "broad").results[0].score == broad.results[0].score
    delta = compare(good, broad)
    assert delta.stage_deltas is not None and delta.stage_deltas["query"] < 0
    found = autopsy(broad, cases=(case,))
    keys = {cluster.key for cluster in found.clusters}
    assert {"query.overfetch", "output.field_mismatch"} <= keys
    assert "query.overfetch" in finding_keys(broad.results[0], case)
    assert "a search returned far more records" in render_brief(found)
    text = render_evidence(collect(broad, cases=(case,), found=found), 20000)
    assert "Searches that fell short" in text and "found 3 of 3" in text and "8 returned" in text


def _off(tmp_path: Path) -> Any:
    packs = tmp_path / "packs" / "policy"
    packs.mkdir(parents=True, exist_ok=True)
    (packs / "nostages.json").write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "policy", "name": "nostages",
                                                     "body": {"values": {"evalrun.grade.queries": False,
                                                                         "evalrun.grade.plan_nodes": False,
                                                                         "evalrun.grade.output": False}}}))
    return packkit.use("policy:nostages", roots=[tmp_path / "packs"])


def test_with_every_stage_off_the_run_is_what_it_was_before_stages(tmp_path: Path) -> None:
    case = _case()
    calls = [_search(), _draft()]
    with _off(tmp_path):
        off = run_cases(_service(case), (case,), ScriptedAgent(calls, name="a"))
        identity = grader_identity()
    on = run_cases(_service(case), (case,), ScriptedAgent(calls, name="a"))
    assert "stages" not in identity
    dumped = off.results[0].model_dump(mode="json")["score"]
    assert "nodes" not in dumped["plan"] and "queries" not in dumped["trajectory"] and "output" not in dumped["outcomes"]
    assert "stages" not in summarize(off).model_dump(mode="json", by_alias=True)
    # The axis scores are the same numbers either way; only the breakdowns differ.
    left, right = off.results[0].score, on.results[0].score
    assert (left.plan.score, left.trajectory.score, left.outcomes.score, left.score, left.passed) == \
           (right.plan.score, right.trajectory.score, right.outcomes.score, right.score, right.passed)
    # The grader digest moves with the stages, but what graded the axes does not:
    # an older run and a new one still compare on plan, trajectory and outcomes.
    assert off.grader["digest"] != on.grader["digest"]
    assert axis_digest(off.grader) == axis_digest(on.grader) == off.grader["digest"]
    comparison = compare(off, on)
    assert not comparison.grader_mismatch and comparison.stage_deltas is None
    assert "stage_deltas" not in comparison.model_dump(mode="json", by_alias=True)


# -- native queries: the stage reads what the evaluator executed ----------------


def _native_query_grade(connector: str, tool: str, entity: str, records: list[dict[str, Any]], gold: list[str],
                        predicate: dict[str, Any], query: str) -> Any:
    row = {"id": f"native-{connector}", "query": "Find the records the request names.",
           "expected_dag": {"nodes": [{"id": "search", "server": connector, "tool": tool, "entity": entity,
                                       "node_kind": "search", "op": "search", "payload": {"predicate": predicate},
                                       "expected_reads": gold}], "edges": []},
           "assertions": [{"type": "tool_called", "node": "search"}]}
    case = case_from_row(row)
    service = service_for((case,), records, query_engine="native")
    result = run_case(service, case, ScriptedAgent([(f"{connector}.{tool}", {"query": query})]))
    assert result.graded and result.score is not None, result.error
    assert not result.spans[0]["error"], result.spans[0]
    grade = result.score.trajectory.queries
    assert grade is not None
    return grade


def test_a_native_jql_disjunction_with_a_relative_window_is_read_as_the_evaluator_ran_it() -> None:
    records = [{"fid": f"j{n}", "server": "jira", "entity": "task", "ident": f"OPS-{n}", "project": "OPS",
                "status": status, "severity": severity, "summary": f"Issue {n}",
                "created_at": f"2026-09-0{n}T10:00:00+08:00"}
               for n, (status, severity) in enumerate(
                   [("open", "Sev-1"), ("todo", "Sev-2"), ("review", "Sev-1"), ("done", "Sev-3"), ("open", "Sev-1")],
                   start=1)]
    grade = _native_query_grade(
        "jira", "search_issues", "task", records, ["j1", "j3", "j5"], {"severity": "Sev-1"},
        '(status = open OR status = review) AND created >= -2d AND cf[10231] = "Sev-1"')
    call = grade.calls[0]
    # The historical conjunctive parser could not read this query at all.
    assert call.constrained == ("created_at", "severity", "status")
    assert call.missing_filters == ()
    # `-2d` from the clock (2026-09-05 09:00) cuts j1, created on the 1st.
    assert call.wrong_window == ("created_at",)
    assert {"query.wrong_window", "query.missed_evidence"} <= set(grade.findings)
    assert grade.nodes[0].found == 2


def test_a_native_odata_filter_is_read_as_the_evaluator_ran_it() -> None:
    records = [{"fid": f"m{n}", "server": "outlook", "entity": "message", "ident": f"msg-{n}",
                "subject": f"Invoice {n}", "sender": "ap@vendor.example" if n < 4 else "someone@else.example",
                "received_at": f"2026-09-0{n}T08:00:00+08:00", "is_read": n % 2 == 0}
               for n in range(1, 7)]
    grade = _native_query_grade(
        "outlook", "list_messages", "message", records, ["m1", "m2", "m3"], {"sender": "ap@vendor.example"},
        "from/emailAddress/address eq 'ap@vendor.example' and (isRead eq true or contains(subject,'Invoice')) "
        "and receivedDateTime ge 2026-09-02T00:00:00+08:00")
    call = grade.calls[0]
    assert call.constrained == ("is_read", "received_at", "sender", "subject")
    assert call.missing_filters == ()
    assert call.wrong_window == ("received_at",)
    assert grade.nodes[0].found == 2
    # Without the sender clause, the gold node's filter is named as missing.
    loose = _native_query_grade(
        "outlook", "list_messages", "message", records, ["m1", "m2", "m3"], {"sender": "ap@vendor.example"},
        "receivedDateTime ge 2026-08-01T00:00:00+08:00")
    assert loose.calls[0].missing_filters == ("sender",) and loose.calls[0].wrong_window == ()
