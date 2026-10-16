"""Anvil composite flows on the plan axis (``worldloom.evalrun.compose``).

Anvil's composite SDK states a cross-connector task as a flow, a DAG of
operation calls (Anvil ADR-0031). These tests hold the two translations
through the shipped Anvil mappings: a gold DAG written as a flow, and a flow
(or the plan Anvil derives from one) read back and graded as a plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.enterprise_io import export_corpus
from worldloom.evalrun import grade_planned, parse_plan
from worldloom.evalrun.compose import FLOW_SCHEMA, flow_from_case, planned_from_compose
from worldloom.evalrun.contract import case_from_row

runner = CliRunner()


def _triage() -> Any:
    nodes = [
        {"id": "find", "server": "jira", "tool": "search_issues", "fixture": "rec-1", "entity": "task", "op": "search",
         "payload": {"query": "project = OPS AND status = open"}},
        {"id": "move", "server": "jira", "tool": "transition_issue", "fixture": "rec-1", "entity": "task", "op": "transition"},
    ]
    return case_from_row({"id": "jira-triage", "query": "Find the open Sev-1 task in OPS and move it to review.",
                          "expected_dag": {"nodes": nodes, "edges": [["find", "move"]]}})


def test_a_gold_dag_becomes_a_composite_flow() -> None:
    flow = flow_from_case(_triage())
    assert flow["schema"] == FLOW_SCHEMA and flow["name"] == "jira-triage" and "unmapped" not in flow
    find, move = flow["steps"]
    # The payload is written by wire name, as the operation's SDK accepts it.
    assert find == {"id": "find", "operation": "jira.jql.search", "connector": "jira",
                    "args": {"jql": "project = OPS AND status = open"}}
    assert move["operation"] == "jira.transitions.create" and move["after"] == ["find"]
    # The write is confirmed (the gold plan intends it), and what the gold
    # payload cannot supply is named rather than invented.
    assert move["confirm"] is True and move["needs"]


def test_a_composite_flow_is_graded_as_the_plan_it_states() -> None:
    case = _triage()
    flow = flow_from_case(case)
    planned = planned_from_compose(flow)
    assert [node.tool for node in planned.nodes] == ["jira.search_issues", "jira.transition_issue"]
    assert grade_planned(case, planned).passed
    # parse_plan reads the same document, bare or under "plan", for --exec planners.
    assert grade_planned(case, parse_plan({"plan": flow})).passed
    # Dependencies a flow states through references count as edges.
    by_ref = {"schema": FLOW_SCHEMA, "steps": [
        {"id": "s", "operation": "jira.jql.search", "args": {"jql": "x"}},
        {"id": "t", "operation": "jira:jira.transitions.create", "args": {"issueIdOrKey": {"$ref": "s", "path": "issues[0].key"}}},
    ]}
    assert grade_planned(case, parse_plan(by_ref)).passed
    # Without the dependency the edge is missing.
    unordered = {"schema": FLOW_SCHEMA, "steps": [dict(step, args={}) for step in by_ref["steps"]]}
    assert grade_planned(case, parse_plan(unordered)).edge_recall == 0.0


def test_an_anvil_plan_document_is_read_by_its_depends_on() -> None:
    plan = {"schema": "anvil.compose-plan/v1", "nodes": [
        {"id": "a", "operation": "jira.jql.search", "connector": "jira", "depends_on": []},
        {"id": "b", "operation": "jira.transitions.create", "connector": "jira", "depends_on": ["a"]},
        {"id": "c", "operation": "jira.issue.create", "connector": "jira", "depends_on": ["b"]},
        {"id": "d", "operation": "acme.widgets.list", "connector": "acme", "depends_on": []},
    ]}
    planned = parse_plan(plan)
    # An operation no mapping knows stays itself and is graded as unmatched.
    assert planned.nodes[-1].tool == "acme.acme.widgets.list"
    grade = grade_planned(_triage(), planned)
    # A write the gold plan does not hold costs the plan its pass.
    assert grade.edge_recall == 1.0 and grade.unattributed_calls == 2 and grade.extra_writes == 1
    assert not grade.passed


def test_a_node_no_mapping_serves_is_reported() -> None:
    case = case_from_row({"id": "x", "query": "Post it.", "expected_dag": {"nodes": [
        {"id": "post", "server": "nowhere", "tool": "post_thing", "entity": "thing", "op": "create"}], "edges": []}})
    flow = flow_from_case(case)
    assert flow["steps"] == []
    assert flow["unmapped"] == [{"node": "post", "tool": "nowhere.post_thing",
                                 "reason": "no Anvil mapping ships for this connector"}]


@pytest.fixture(scope="module")
def grammar_corpus() -> Any:
    from tests.test_evalrun import _build

    return _build(("map_read", "conditional"))


def test_every_gold_flow_grades_back_as_its_own_plan(grammar_corpus: Any) -> None:
    """Through the mappings and back, a gold DAG loses only the nodes it reports unmapped."""

    from worldloom.evalrun import EvalSession

    session = EvalSession.from_corpus(grammar_corpus)
    translated = 0
    for case in session.cases:
        flow = flow_from_case(case)
        unmapped = {entry["node"] for entry in flow.get("unmapped", ())}
        translated += len(flow["steps"])
        grade = grade_planned(case, planned_from_compose(flow))
        assert set(grade.missing_nodes) == unmapped, (case.id, flow, grade.model_dump())
        assert grade.unattributed_calls == 0 and grade.extra_writes == 0
        if not unmapped:
            assert grade.passed, (case.id, flow, grade.model_dump())
    assert translated > 0


def test_evalrun_flow_writes_every_case(grammar_corpus: Any, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    export_corpus(grammar_corpus, corpus)
    out = tmp_path / "flows.json"
    result = runner.invoke(app, ["evalrun", "flow", str(corpus), "-o", str(out)])
    assert result.exit_code == 0, result.output
    document = json.loads(out.read_text())
    assert document["schema"] == "worldloom.compose-flows/v1" and document["flows"]
    assert all(flow["schema"] == FLOW_SCHEMA for flow in document["flows"].values())
    assert "flow(s)" in result.output
