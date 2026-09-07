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


# ---------------------------------------------------------------------------
# What the grader used to let through.
#
# `grade_trace` decides eighteen assertion kinds in one if/elif chain, and the
# chain had no else and one bare node lookup. Three ways to get a clean grade
# out of a run that earned nothing are pinned below, because each of them
# reports success rather than staying silent, which is the failure mode a
# grader can least afford.


def _state_row(node: str = "write") -> dict[str, object]:
    return {
        "expected_dag": {
            "nodes": [
                {
                    "id": node,
                    "server": "sharepoint",
                    "tool": "sharepoint.update",
                    "entity": "file",
                    "op": "update",
                }
            ],
            "edges": [],
        },
        "assertions": [{"type": "state_equals", "node": node, "state": "fixed"}],
        "ground_truth": {},
    }


def _span(node: str, *, reads: tuple[str, ...] = (), writes: tuple[str, ...] = ()) -> dict[str, object]:
    return {
        "id": f"s-{node}",
        "node": node,
        "tool": "sharepoint.update",
        "reads": list(reads),
        "writes": list(writes),
    }


def test_state_equals_fails_when_nothing_was_written() -> None:
    """"The system was updated" must not pass on a system nobody updated.

    The target was resolved only from spans' `writes`, so with none the
    comparison loop never ran and no failure was ever appended. A trace with no
    write at all graded `ok`.
    """
    grade = grade_trace([], _state_row(), post_state={"REC-1": {"state": "open"}})
    assert grade["status"] == "fail"
    assert grade["fails"] == ["state_not_written:write"]


def test_state_equals_fails_when_the_write_ran_but_wrote_nothing() -> None:
    """The same hole reached the other way: the node executed and wrote none."""
    grade = grade_trace(
        [_span("write")], _state_row(), post_state={"REC-1": {"state": "open"}}
    )
    assert grade["status"] == "fail"
    assert grade["fails"] == ["state_not_written:write"]


def test_state_equals_still_compares_a_real_write() -> None:
    """The control: the guard must not swallow the comparison it guards."""
    post = {"REC-1": {"state": "open"}}
    wrong = grade_trace([_span("write", writes=("REC-1",))], _state_row(), post_state=post)
    assert wrong["fails"] == ["state_mismatch:write"]

    right = grade_trace(
        [_span("write", writes=("REC-1",))],
        _state_row(),
        post_state={"REC-1": {"state": "fixed"}},
    )
    assert right["status"] == "ok"


def test_a_write_that_vanished_from_the_post_state_is_reported() -> None:
    """Written, then absent. Distinct from a mismatch, and previously silent."""
    grade = grade_trace([_span("write", writes=("REC-9",))], _state_row(), post_state={})
    assert grade["fails"] == ["state_missing:write"]


def test_an_unrecognised_assertion_kind_fails_rather_than_passing() -> None:
    """A typo in an assertion type used to be indistinguishable from a pass.

    The chain has no else, so `totally_made_up` fell through it and the row
    graded clean: a rule that was never applied, reported as satisfied.
    """
    row = {**_state_row(), "assertions": [{"type": "totally_made_up", "node": "write"}]}
    grade = grade_trace([_span("write")], row, post_state={})
    assert grade["fails"] == ["unknown_assertion:totally_made_up"]


def test_an_assertion_naming_an_unknown_node_fails_rather_than_raising() -> None:
    """A malformed row should fail its own grade, not abort the grading run."""
    row = {**_state_row(), "assertions": [{"type": "tool_called", "node": "nope"}]}
    grade = grade_trace([_span("write")], row, post_state={})
    assert grade["fails"] == ["unknown_node:nope"]


def test_reads_contain_grades_which_records_came_back() -> None:
    """The resultset outcome.

    Every other kind grades the trajectory or a side effect. Nothing graded
    what a read returned, so a case asking for particular records could pass by
    reading any record at all.
    """
    row = {
        "expected_dag": {
            "nodes": [
                {
                    "id": "read-0",
                    "server": "servicenow",
                    "tool": "servicenow.get",
                    "entity": "incident",
                    "op": "read",
                }
            ],
            "edges": [],
        },
        "assertions": [
            {"type": "reads_contain", "node": "read-0", "records": ["REC-A", "REC-B"]}
        ],
        "ground_truth": {},
    }
    assert grade_trace([_span("read-0", reads=("REC-A", "REC-B"))], row)["status"] == "ok"
    partial = grade_trace([_span("read-0", reads=("REC-A",))], row)
    assert partial["fails"] == ["reads_missing:read-0:REC-B"]


def test_every_branch_of_the_chain_is_declared_known() -> None:
    """`_KNOWN_ASSERTIONS` gates the chain, so a branch missing from it is dead.

    Adding a branch without adding its name makes that assertion unreachable
    and, worse, makes it fail as unknown. This reads the source rather than the
    set so the two cannot drift apart quietly.
    """
    import re
    from pathlib import Path

    from worldloom.connector_trace import _KNOWN_ASSERTIONS

    source = Path("src/worldloom/connector_trace.py").read_text(encoding="utf-8")
    branched = set(re.findall(r'kind == "([a-z_]+)"', source))
    assert branched <= _KNOWN_ASSERTIONS, sorted(branched - _KNOWN_ASSERTIONS)
