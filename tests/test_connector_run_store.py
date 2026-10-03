"""Durable evaluation runs: a service restarted on its run store answers as the one that stopped."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorError
from worldloom.connectors import ConnectorEvaluationService, ServingError
from worldloom.connectors.run_store import RunStore, RunStoreWarning

pytestmark = pytest.mark.usefixtures("native_surface")


def records() -> list[dict[str, Any]]:
    return [{"fid": f"f{i}", "server": "servicenow", "entity": "incident",
             "ident": f"INC000000{i}", "state": "new", "short_description": f"Case {i}"}
            for i in (1, 2)]


def row(query: str = "Read INC0000001, move it to open, then verify.") -> dict[str, Any]:
    return {"id": "q1", "query": query,
            "expected_dag": {"nodes": [
                {"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident"},
                {"id": "write", "server": "servicenow", "tool": "update_record", "fixture": "f1", "entity": "incident"},
                {"id": "verify", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident"},
            ], "edges": [["read", "write"], ["write", "verify"]]},
            "assertions": [{"type": "tool_called", "node": node} for node in ("read", "write", "verify")]
            + [{"type": "order", "before": "read", "after": "write"},
               {"type": "state_equals", "node": "write", "fixture": "f1", "state": "open"}]}


def service(**options: Any) -> ConnectorEvaluationService:
    query = options.pop("query", None)
    return ConnectorEvaluationService([row(query) if query else row()], records(),
                                      definitions={"servicenow": load_connector_definition("servicenow")},
                                      **options)


def drive(runtime: ConnectorEvaluationService) -> tuple[str, str]:
    """One run ended, one left open mid-way, each with a refusal and a question."""
    done = runtime.begin("alice", "q1")["run_id"]
    runtime.call("alice", done, "servicenow.get_record", {"id": "INC0000001"})
    runtime.call("alice", done, "servicenow.update_record", {"id": "INC0000001", "fields": {"state": "open"}})
    runtime.call("alice", done, "servicenow.get_record", {"id": "INC0000001"})
    runtime.end("alice", done)
    live = runtime.begin("alice", "q1")["run_id"]
    runtime.call("alice", live, "servicenow.get_record", {"id": "INC0000001"})
    with pytest.raises(ServingError):
        runtime.call("alice", live, "servicenow.no_such_tool", {})
    with pytest.raises(ConnectorError):
        runtime.call("alice", live, "servicenow.get_record", {"id": "INC9999999"})
    runtime.ask("alice", live, "Which state should it move to?", ("state",))
    runtime.call("alice", live, "servicenow.update_record", {"id": "INC0000002", "fields": {"state": "open"}})
    return done, live


def observed(runtime: ConnectorEvaluationService, run: str) -> dict[str, Any]:
    return {"trace": runtime.trace("alice", run), "grade": runtime.grade("alice", run),
            "score": runtime.score("alice", run, answer="moved"), "refusals": runtime.refusals("alice", run),
            "questions": runtime.questions("alice", run), "snapshot": runtime.snapshot("alice", run),
            "spans": runtime.spans("alice", run)}


def test_restart_restores_open_runs_and_ended_grades(tmp_path: Path) -> None:
    store = tmp_path / "runs" / "journal.jsonl"
    first = service(run_store=store)
    done, live = drive(first)
    before, listed = observed(first, live), first.list_runs("alice")
    assert [entry["status"] for entry in listed] == ["ended", "open"]
    assert listed[0]["grade"]["status"] == "ok"

    second = service(run_store=store)
    assert observed(second, live) == before
    assert second.list_runs("alice") == listed
    assert second.list_runs("bob") == []
    # The restored run carries on, and new ids continue past the journal's.
    second.call("alice", live, "servicenow.get_record", {"id": "INC0000001"})
    assert second.begin("alice", "q1")["run_id"] == "run-3"
    third = service(run_store=store)
    assert observed(third, live) == observed(second, live)
    assert [entry["run_id"] for entry in third.list_runs("alice")] == [done, live, "run-3"]


def test_only_the_outermost_entry_point_is_journalled(tmp_path: Path) -> None:
    store = tmp_path / "journal.jsonl"
    runtime = service(run_store=store)
    drive(runtime)
    lines = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
    # `call` reaches `call_connector`; one journalled event per call made.
    assert [(line["kind"], line.get("op")) for line in lines] == [
        ("begin", None), ("event", "call"), ("event", "call"), ("event", "call"), ("end", None),
        ("begin", None), ("event", "call"), ("event", "call"), ("event", "call"), ("event", "ask"), ("event", "call"),
    ]
    assert all(line["schema"] == "worldloom.run-store/v1" for line in lines)
    # Same calls, same journal: nothing in a record depends on the clock.
    again = tmp_path / "again.jsonl"
    drive(service(run_store=again))
    assert again.read_bytes() == store.read_bytes()


def test_a_torn_final_line_is_dropped_with_a_warning(tmp_path: Path) -> None:
    store = tmp_path / "journal.jsonl"
    first = service(run_store=store)
    _, live = drive(first)
    intact = store.read_bytes()
    before = observed(first, live)
    first.call("alice", live, "servicenow.get_record", {"id": "INC0000002"})
    torn = store.read_bytes()
    # The crash came mid-write of the last call's record.
    store.write_bytes(torn[: len(intact) + (len(torn) - len(intact)) // 2])
    with pytest.warns(RunStoreWarning, match="torn final record"):
        second = service(run_store=store)
    assert observed(second, live) == before
    assert store.read_bytes() == intact
    # The next record starts on its own line.
    second.call("alice", live, "servicenow.get_record", {"id": "INC0000002"})
    assert len(RunStore(store).load()) == intact.count(b"\n") + 1


def test_an_unparseable_final_line_is_dropped_but_earlier_corruption_is_refused(tmp_path: Path) -> None:
    store = tmp_path / "journal.jsonl"
    drive(service(run_store=store))
    intact = store.read_bytes()
    store.write_bytes(intact + b'{"kind": "ev\n')
    with pytest.warns(RunStoreWarning):
        service(run_store=store)
    assert store.read_bytes() == intact
    store.write_bytes(b"not json\n" + intact)
    with pytest.raises(ServingError, match="line 1 is corrupt"):
        service(run_store=store)


def test_a_run_begun_on_a_different_case_is_not_replayed(tmp_path: Path) -> None:
    store = tmp_path / "journal.jsonl"
    _, live = drive(service(run_store=store))
    with pytest.warns(RunStoreWarning, match="not replayed"):
        changed = service(run_store=store, query="A different request.")
    assert [entry["status"] for entry in changed.list_runs("alice")] == ["ended"]
    with pytest.raises(ServingError, match="unknown_run"):
        changed.trace("alice", live)


def test_in_memory_default_is_unchanged(tmp_path: Path) -> None:
    runtime = service()
    assert runtime.run_store is None
    done, live = drive(runtime)
    # Without a store `end` forgets a run, as it always has, and nothing is written.
    assert [entry["run_id"] for entry in runtime.list_runs("alice")] == [live]
    with pytest.raises(ServingError, match="unknown_run"):
        runtime.grade("alice", done)
    assert list(tmp_path.iterdir()) == []
    # A stored service observes exactly what an in-memory one does.
    stored = service(run_store=tmp_path / "journal.jsonl")
    drive(stored)
    assert observed(stored, live) == observed(runtime, live)


def test_store_refuses_arguments_it_cannot_journal(tmp_path: Path) -> None:
    runtime = service(run_store=tmp_path / "journal.jsonl")
    run = runtime.begin("alice", "q1")["run_id"]
    with pytest.raises(ServingError, match="plain JSON"):
        runtime.call("alice", run, "servicenow.get_record", {"id": object()})
    assert runtime.spans("alice", run) == ()
