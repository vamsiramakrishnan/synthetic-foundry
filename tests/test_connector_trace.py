from __future__ import annotations

from worldloom.connector_trace import executed_dag, grade_trace, shape_assertions
from worldloom.eval_design import (
    EvalShape,
    RecordShapeRequirement,
    ThreadShapeRequirement,
)


def _row() -> dict[str, object]:
    return {
        "expected_dag": {
            "nodes": [
                {
                    "id": "n1",
                    "server": "jira",
                    "tool": "search_issues",
                    "op": "search",
                }
            ],
            "edges": [],
        },
        "assertions": [{"type": "tool_called", "node": "n1"}],
        "ground_truth": {},
    }


def test_executed_dag_uses_explicit_consumption_edges() -> None:
    spans = [
        {
            "id": "s1",
            "tool": "jira.search_issues",
            "reads": ["jr:1"],
            "writes": [],
            "args": {},
            "error": None,
        },
        {
            "id": "s2",
            "tool": "salesforce.create_task",
            "reads": [],
            "writes": ["sf:new:1"],
            "args": {},
            "consumed_from": ["s1"],
            "error": None,
        },
    ]

    graph = executed_dag(spans)

    assert graph["edges"] == [["s1", "s2"]]


def test_projection_assertion_is_compiled_from_eval_shape() -> None:
    shape = EvalShape(
        records=(
            RecordShapeRequirement(
                connector="jira",
                entity="bug",
                total_fields=320,
                custom_fields=300,
                projection_required=True,
                maximum_read_bytes=8_000,
            ),
        )
    )
    assertion = shape_assertions(shape)[0]

    assert assertion == {
        "type": "projection_used",
        "connector": "jira",
        "entity": "bug",
        "max_bytes": 8_000,
    }


def test_wide_unprojected_read_fails_but_projected_read_passes() -> None:
    shape = EvalShape(
        records=(
            RecordShapeRequirement(
                connector="jira",
                entity="bug",
                custom_fields=300,
                projection_required=True,
                maximum_read_bytes=8_000,
            ),
        )
    )
    unprojected = [
        {
            "id": "s1",
            "node": "n1",
            "tool": "jira.search_issues",
            "args": {"entity": "bug"},
            "reads": ["jr:1"],
            "writes": [],
            "bytes": 55_000,
            "error": None,
        }
    ]
    projected = [
        {
            **unprojected[0],
            "args": {"entity": "bug", "fields": ["summary", "status"]},
            "bytes": 2_000,
        }
    ]

    assert grade_trace(unprojected, _row(), shape=shape)["fails"] == ["no_projection"]
    assert grade_trace(projected, _row(), shape=shape)["status"] == "ok"


def test_long_thread_requires_actual_paging() -> None:
    shape = EvalShape(
        threads=(
            ThreadShapeRequirement(
                connector="outlook",
                entity="message",
                messages_per_thread=400,
                pagination_required=True,
            ),
        )
    )
    one_page = [
        {
            "id": "s1",
            "tool": "outlook.list_messages",
            "args": {"start_at": 0},
            "reads": ["ol:1"],
            "writes": [],
            "bytes": 2_000,
            "error": None,
        }
    ]
    two_pages = [
        one_page[0],
        {
            **one_page[0],
            "id": "s2",
            "args": {"start_at": 10},
            "reads": ["ol:2"],
        },
    ]

    empty_row = {"expected_dag": {"nodes": [], "edges": []}, "assertions": []}
    assert grade_trace(one_page, empty_row, shape=shape)["fails"] == [
        "no_pagination:outlook"
    ]
    assert grade_trace(two_pages, empty_row, shape=shape)["status"] == "ok"
