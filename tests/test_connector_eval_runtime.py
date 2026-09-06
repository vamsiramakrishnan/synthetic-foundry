from worldloom.connector_eval_runtime import run_eval_row


def _jira_records() -> tuple[dict[str, object], ...]:
    return (
        {
            "fid": "jr:bug:1",
            "server": "jira",
            "entity": "bug",
            "ident": "PHX-1",
            "name": "Checkout regression",
            "project": "PHX",
            "issuetype": "Bug",
            "summary": "Checkout regression",
            "status": "open",
            "priority": "High",
        },
        {
            "fid": "jr:bug:2",
            "server": "jira",
            "entity": "bug",
            "ident": "PHX-2",
            "name": "Retry regression",
            "project": "PHX",
            "issuetype": "Bug",
            "summary": "Retry regression",
            "status": "open",
            "priority": "Low",
        },
    )


def test_runtime_pages_search_and_executes_for_each_through_one_definition() -> None:
    row = {
        "id": "runtime-1",
        "expected_dag": {
            "nodes": [
                {
                    "id": "n1",
                    "server": "jira",
                    "tool": "search_issues",
                    "entity": "bug",
                    "payload": {"predicate": {"project": "PHX", "status": "open"}},
                },
                {
                    "id": "n2",
                    "server": "jira",
                    "tool": "add_comment",
                    "entity": "bug",
                    "for_each": True,
                    "payload": {"note": "triaged"},
                },
            ],
            "edges": [["n1", "n2"]],
        },
        "ground_truth": {"for_each": {"n2": {"count": 2}}},
        "assertions": [
            {"type": "tool_called", "node": "n1"},
            {"type": "tool_called", "node": "n2"},
            {"type": "per_item", "node": "n2"},
            {"type": "order", "before": "n1", "after": "n2"},
        ],
    }

    result = run_eval_row(row, _jira_records())

    assert result.grade["status"] == "ok"
    assert result.grade["fails"] == []
    assert len(result.spans) == 3
    assert len({span.id for span in result.spans}) == 3
    assert [span.tool for span in result.spans] == [
        "jira.search_issues",
        "jira.add_comment",
        "jira.add_comment",
    ]


def test_runtime_keeps_invalid_connector_workflow_visible() -> None:
    row = {
        "id": "runtime-invalid-transition",
        "expected_dag": {
            "nodes": [
                {
                    "id": "n1",
                    "server": "jira",
                    "tool": "transition_issue",
                    "entity": "bug",
                    "fixture": "jr:bug:1",
                    "payload": {"state": "todo"},
                }
            ],
            "edges": [],
        },
        "assertions": [{"type": "tool_called", "node": "n1"}],
    }

    result = run_eval_row(row, _jira_records())

    assert result.behaviors == ("validation_error",)
    assert result.spans[0].error is not None
    assert result.spans[0].error["kind"] == "bad_transition"
    assert result.grade["status"] == "behavior"
