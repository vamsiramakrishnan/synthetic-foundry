"""Exercise the actual StreamableHTTP boundary, including isolation and grading."""
from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

pytest.importorskip("mcp.server.mcpserver")
from starlette.testclient import TestClient

from worldloom.cli import app
from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorError
from worldloom.connectors import (
    ConnectorEvaluationService,
    ServingError,
    ServingLimits,
    create_connector_app,
)

HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
TOKENS = {"alice": "alice-private-evaluation-secret", "bob": "bob-private-evaluation-secret"}


def records() -> list[dict[str, Any]]:
    return [{"fid": f"f{i}", "server": "servicenow", "entity": "incident",
             "ident": f"INC000000{i}", "state": "new", "short_description": f"Case {i}"}
            for i in (1, 2)]


def row() -> dict[str, Any]:
    return {"id": "q1", "query": "Read INC0000001, move it to open, then verify.",
            "expected_dag": {"nodes": [
                {"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident"},
                {"id": "write", "server": "servicenow", "tool": "update_record", "fixture": "f1", "entity": "incident"},
                {"id": "verify", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident"},
            ], "edges": [["read", "write"], ["write", "verify"]]},
            "assertions": [{"type": "tool_called", "node": node} for node in ("read", "write", "verify")]
            + [{"type": "order", "before": "read", "after": "write"},
               {"type": "order", "before": "write", "after": "verify"},
               {"type": "state_equals", "node": "write", "fixture": "f1", "state": "open"}]}


def service(**options: Any) -> ConnectorEvaluationService:
    return ConnectorEvaluationService([row()], records(),
                                      definitions={"servicenow": load_connector_definition("servicenow")},
                                      **options)


def rpc(client: TestClient, method: str, params: dict[str, Any], *, actor: str = "alice") -> dict[str, Any]:
    response = client.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {TOKENS[actor]}"},
                           json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def call(client: TestClient, name: str, arguments: dict[str, Any], *, actor: str = "alice") -> dict[str, Any]:
    result = rpc(client, "tools/call", {"name": name, "arguments": arguments}, actor=actor)
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


def test_http_initialize_list_call_trace_grade_and_end() -> None:
    original_records = records()
    original_row = row()
    runtime = ConnectorEvaluationService([original_row], original_records,
                                        definitions={"servicenow": load_connector_definition("servicenow")})
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://localhost") as client:
        initialized = rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                 "clientInfo": {"name": "external-agent", "version": "1"}})
        assert initialized["serverInfo"]["name"] == "worldloom-connectors"
        tools = {tool["name"]: tool for tool in rpc(client, "tools/list", {})["tools"]}
        assert "servicenow.get_record" in tools
        assert tools["servicenow.get_record"]["annotations"]["readOnlyHint"]
        assert not tools["servicenow.update_record"]["annotations"]["readOnlyHint"]
        assert tools["servicenow.update_record"]["inputSchema"]["required"] == ["run_id", "fields", "id"]
        assert call(client, "eval_list", {})["queries"][0]["query_id"] == "q1"
        run = call(client, "eval_begin", {"query_id": "q1"})["run_id"]
        assert call(client, "eval_grade", {"run_id": run})["status"] == "fail"
        assert call(client, "servicenow.get_record", {"run_id": run, "id": "INC0000001"})["state"] == 1
        call(client, "servicenow.update_record", {"run_id": run, "id": "INC0000001", "fields": {"state": "open"}})
        assert call(client, "servicenow.get_record", {"run_id": run, "id": "INC0000001"})["state"] == 2
        observed = call(client, "eval_trace", {"run_id": run, "limit": 2})
        assert observed["next_offset"] == 2
        assert [span["node"] for span in observed["spans"]] == ["read", "write"]
        assert [span["id"] for span in observed["spans"]] == ["s1", "s2"]
        assert observed["spans"][1]["consumed_from"] == ["s1"]
        assert observed["spans"][0]["result"]["number"] == "INC0000001"
        assert call(client, "eval_trace", {"run_id": run, "offset": 2})["spans"][0]["node"] == "verify"
        assert call(client, "eval_grade", {"run_id": run})["status"] == "ok"
        assert call(client, "eval_end", {"run_id": run})["grade"]["status"] == "ok"
        assert rpc(client, "tools/call", {"name": "eval_trace", "arguments": {"run_id": run}})["isError"]
    assert original_records == records()
    assert original_row == row()


def test_bearer_and_run_isolation_cover_mutations_and_trace_reads() -> None:
    with TestClient(create_connector_app(service(), bearer_tokens=TOKENS), base_url="http://localhost") as client:
        response = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 401
        alice = call(client, "eval_begin", {"query_id": "q1"})["run_id"]
        bob = call(client, "eval_begin", {"query_id": "q1"}, actor="bob")["run_id"]
        call(client, "servicenow.update_record", {"run_id": alice, "id": "INC0000001", "fields": {"state": "open"}})
        assert call(client, "servicenow.get_record", {"run_id": bob, "id": "INC0000001"}, actor="bob")["state"] == 1
        for name, args in [("eval_trace", {}), ("eval_grade", {}), ("eval_end", {}),
                           ("servicenow.update_record", {"id": "INC0000001", "fields": {"state": "open"}})]:
            result = rpc(client, "tools/call", {"name": name, "arguments": {"run_id": alice, **args}}, actor="bob")
            assert result["isError"]
            assert "unknown_run" in result["content"][0]["text"]
        second = call(client, "eval_begin", {"query_id": "q1"})["run_id"]
        assert call(client, "servicenow.get_record", {"run_id": second, "id": "INC0000001"})["state"] == 1


def test_error_is_real_mcp_error_and_trace_records_failed_call() -> None:
    with TestClient(create_connector_app(service(), bearer_tokens=TOKENS), base_url="http://localhost") as client:
        run = call(client, "eval_begin", {"query_id": "q1"})["run_id"]
        failed = rpc(client, "tools/call", {"name": "servicenow.get_record", "arguments": {"run_id": run, "id": "missing"}})
        assert failed["isError"]
        assert "No Record found" in failed["content"][0]["text"]
        trace = call(client, "eval_trace", {"run_id": run})
        assert trace["spans"][0]["error"]["code"] == 404
        assert trace["spans"][0]["node"] is None
        assert call(client, "eval_grade", {"run_id": run})["status"] == "fail"
        forged = rpc(client, "tools/call", {"name": "servicenow.get_record", "arguments": {"run_id": run, "id": "INC0000002", "_node": "read"}})
        assert forged["isError"]
        assert "Extra inputs" in forged["content"][0]["text"]


def test_actual_state_and_order_determine_grade() -> None:
    runtime = service()
    run = runtime.begin("agent", "q1")["run_id"]
    runtime.call("agent", run, "servicenow.get_record", {"id": "INC0000001"})
    runtime.call("agent", run, "servicenow.update_record", {"id": "INC0000002", "fields": {"state": "open"}})
    runtime.call("agent", run, "servicenow.get_record", {"id": "INC0000001"})
    assert "state_mismatch:write" in runtime.grade("agent", run)["fails"]
    assert "tool_not_called:write" in runtime.grade("agent", run)["fails"]


def test_limits_refuse_without_corrupting_state() -> None:
    runtime = service(limits=ServingLimits(max_runs=1, max_calls_per_run=2, max_response_bytes=20))
    run = runtime.begin("agent", "q1")["run_id"]
    with pytest.raises(ServingError, match="run_limit"):
        runtime.begin("other", "q1")
    with pytest.raises(ConnectorError, match="response_limit"):
        runtime.call("agent", run, "servicenow.update_record", {"id": "INC0000001", "fields": {"state": "open"}})
    assert "state_mismatch:write" in runtime.grade("agent", run)["fails"]
    with pytest.raises(ServingError, match="unknown_arguments"):
        runtime.call("agent", run, "servicenow.get_record", {"id": "INC0000001", "_node": "read"})
    with pytest.raises(ServingError, match="call_limit"):
        runtime.call("agent", run, "servicenow.get_record", {"id": "INC0000001"})
    assert runtime.trace("agent", run)["spans"][0]["writes"] == ()
    runtime.end("agent", run)
    assert runtime.begin("other", "q1")["run_id"] != run


def test_public_bind_allowlisting_and_dns_rebinding() -> None:
    with pytest.raises(ServingError, match="authentication_required"):
        create_connector_app(service(), host="0.0.0.0")
    with pytest.raises(ServingError, match="unique"):
        create_connector_app(service(), bearer_tokens={"alice": TOKENS["alice"], "bob": TOKENS["alice"]})
    with pytest.raises(ServingError, match="required_tool_disabled"):
        service(allowed_tools=["servicenow.get_record"])
    runtime = service(allowed_tools=["servicenow.get_record", "servicenow.update_record"])
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://attacker.invalid") as client:
        response = client.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {TOKENS['alice']}"},
                               json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 421


def test_cli_configuration_error_uses_refusal(tmp_path: Any) -> None:
    result = CliRunner().invoke(app, ["enterprise-evals", "serve", str(tmp_path / "missing"), "--check"], env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code != 0
    assert "connector_serve_failed" in result.output


def test_existing_stdio_tool_surface_still_works_with_current_sdk() -> None:
    from worldloom.mcp import TOOLS, create_server

    server = create_server()
    with TestClient(server.streamable_http_app(stateless_http=True, json_response=True), base_url="http://localhost:8000") as client:
        advertised = rpc(client, "tools/list", {})["tools"]
        assert {tool["name"] for tool in advertised} == {tool["name"] for tool in TOOLS}
        assert {tool["name"]: tool["inputSchema"] for tool in advertised} == {tool["name"]: tool["schema"] for tool in TOOLS}
        result = call(client, "validate_corpus", {"corpus": "examples/retail-close"})
        assert result["ok"]


def test_unbound_verify_reads_the_record_actually_created() -> None:
    target = {"id": "create", "expected_dag": {"nodes": [
        {"id": "write", "server": "servicenow", "tool": "create_record", "op": "create", "entity": "incident"},
        {"id": "verify", "server": "servicenow", "tool": "get_record", "op": "read", "entity": "incident"},
    ], "edges": [["write", "verify"]]}, "assertions": [
        {"type": "tool_called", "node": "write"}, {"type": "tool_called", "node": "verify"},
        {"type": "artifact_created", "node": "write"},
    ]}
    runtime = ConnectorEvaluationService([target], records())
    run = runtime.begin("agent", "create")["run_id"]
    result = runtime.call("agent", run, "servicenow.create_record", {
        "entity": "incident", "name": "New incident", "fields": {"short_description": "New", "caller_id": "agent"},
    })
    runtime.call("agent", run, "servicenow.get_record", {"id": "INC0000001"})
    assert "tool_not_called:verify" in runtime.grade("agent", run)["fails"]
    runtime.call("agent", run, "servicenow.get_record", {"id": result["number"]})
    assert runtime.grade("agent", run)["status"] == "ok"


def test_rejected_response_does_not_count_as_delivered_evidence() -> None:
    target = {"id": "read", "expected_dag": {"nodes": [
        {"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1"},
    ], "edges": []}, "assertions": [{"type": "reads_contain", "node": "read", "records": ["f1"]}]}
    runtime = ConnectorEvaluationService([target], records(), limits=ServingLimits(max_response_bytes=20))
    run = runtime.begin("agent", "read")["run_id"]
    with pytest.raises(ConnectorError, match="response_limit"):
        runtime.call("agent", run, "servicenow.get_record", {"id": "INC0000001"})
    assert runtime.grade("agent", run)["status"] == "fail"
    assert runtime.trace("agent", run)["spans"][0]["reads"] == ()
    assert "result" not in runtime.trace("agent", run)["spans"][0]


def test_search_pages_retain_attribution_and_loops_require_distinct_members() -> None:
    target = {"id": "loop", "expected_dag": {"nodes": [
        {"id": "read", "server": "servicenow", "tool": "search_records", "entity": "incident"},
        {"id": "write", "server": "servicenow", "tool": "update_record", "entity": "incident", "for_each": True},
    ], "edges": [["read", "write"]]}, "ground_truth": {"for_each": {"write": {"count": 2}}}, "assertions": [
        {"type": "tool_called", "node": "read"}, {"type": "tool_called", "node": "write"},
        {"type": "reads_contain", "node": "read", "records": ["f1", "f2"]},
        {"type": "per_item", "node": "write"},
    ]}
    runtime = ConnectorEvaluationService([target], records())
    run = runtime.begin("agent", "loop")["run_id"]
    for start_at in (0, 1):
        runtime.call("agent", run, "servicenow.search_records", {"entity": "incident", "max_results": 1, "start_at": start_at})
    assert [span["node"] for span in runtime.trace("agent", run)["spans"]] == ["read", "read"]
    for _ in range(2):
        runtime.call("agent", run, "servicenow.update_record", {"id": "INC0000001", "fields": {"state": "open"}})
    assert runtime.grade("agent", run)["status"] == "fail"
    runtime.call("agent", run, "servicenow.update_record", {"id": "INC0000002", "fields": {"state": "open"}})
    assert runtime.grade("agent", run)["status"] == "ok"


def test_selected_corpus_serves_through_cli_and_fixture_failures(tmp_path: Any) -> None:
    from worldloom.enterprise_corpus import materialize_corpus
    from worldloom.enterprise_io import export_corpus
    from worldloom.enterprise_queries import plan_queries
    from worldloom.enterprise_specs import (
        CoverageProfile,
        builtin_registry,
    )
    from worldloom.world import World

    registry = builtin_registry()
    # An exhaustive prefix exercises the compiler without a global covering search.
    queries, _ = plan_queries(World.load("retail-close"), registry=registry,
                              profile=CoverageProfile(failures=("none",)), strategy="exhaustive", limit=1)
    corpus = materialize_corpus(World.load("retail-close"), queries)
    export_corpus(corpus, tmp_path)
    result = CliRunner().invoke(app, ["enterprise-evals", "serve", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["queries"] == 1
    runtime = ConnectorEvaluationService.from_corpus(corpus)
    for query in corpus.queries:
        assert runtime.begin("agent", query.id)["query_id"] == query.id


def test_authenticated_actor_is_retained_in_created_record_state() -> None:
    target = {"id": "create", "expected_dag": {"nodes": [
        {"id": "write", "server": "jira", "tool": "create_issue", "entity": "task", "op": "create"},
    ], "edges": []}, "assertions": [{"type": "tool_called", "node": "write"}]}
    runtime = ConnectorEvaluationService([target], [])
    run = runtime.begin("alice", "create")["run_id"]
    runtime.call("alice", run, "jira.create_issue", {"entity": "task", "name": "Task", "fields": {"project": "TEST"}})
    emulator = runtime._runs[run].emulators["jira"]
    assert emulator.actor == "alice"
    assert all(record.get("created_by", "alice") == "alice" for record in emulator.records.values())
    assert runtime.trace("alice", run)["spans"][0]["actor"] == "alice"


def test_declared_permission_fault_surfaces_on_external_write() -> None:
    target = row()
    target["expected_dag"]["nodes"][0]["op"] = "read"
    target["expected_dag"]["nodes"][1]["op"] = "update"
    target["expected_dag"]["nodes"][2]["op"] = "read"
    target["state_overrides"] = [{"kind": "permission_denied", "connector": "servicenow", "record_id": "f1", "details": {}}]
    runtime = ConnectorEvaluationService([target], records())
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://localhost") as client:
        run = call(client, "eval_begin", {"query_id": "q1"})["run_id"]
        call(client, "servicenow.get_record", {"run_id": run, "id": "INC0000001"})
        result = rpc(client, "tools/call", {"name": "servicenow.update_record", "arguments": {
            "run_id": run, "id": "INC0000001", "fields": {"state": "open"},
        }})
        assert result["isError"]
        trace = call(client, "eval_trace", {"run_id": run})
        assert trace["spans"][1]["node"] == "write"
        assert trace["spans"][1]["error"]["code"] == 403
        assert call(client, "servicenow.get_record", {"run_id": run, "id": "INC0000001"})["state"] == 1


def test_embedded_custom_definitions_are_served_and_conflicts_refused() -> None:
    from worldloom.connector_definition import ConnectorFieldDefinition

    original = load_connector_definition("servicenow")
    definition = original.with_fields("incident", (ConnectorFieldDefinition(
        id="u_risk_band", canonical="risk_band", name="Risk band", field_type="option", options=("low", "high"),
    ),))
    target = row()
    target["connector_definitions"] = {"servicenow": definition.wire_dict()}
    runtime = ConnectorEvaluationService([target], records())
    assert runtime.definitions["servicenow"] == definition
    conflicting = {**row(), "id": "other", "connector_definitions": {"servicenow": original.wire_dict()}}
    with pytest.raises(ServingError, match="conflicting_row_definitions"):
        ConnectorEvaluationService([target, conflicting], records())
    explicit = ConnectorEvaluationService([target, conflicting], records(), definitions={"servicenow": definition})
    assert explicit.definitions["servicenow"] == definition
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://localhost") as client:
        run = call(client, "eval_begin", {"query_id": "q1"})["run_id"]
        result = call(client, "servicenow.get_record", {"run_id": run, "id": "INC0000001", "fields": ["u_risk_band"]})
        assert result["u_risk_band"] in {"low", "high"}


def test_from_corpus_refuses_ungrounded_evidence() -> None:
    from worldloom.enterprise_corpus import materialize_corpus
    from worldloom.enterprise_queries import plan_queries
    from worldloom.enterprise_specs import CoverageProfile
    from worldloom.world import World

    world = World.load("retail-close")
    queries, _ = plan_queries(world, profile=CoverageProfile(failures=("none",)), strategy="exhaustive", limit=1)
    corpus = materialize_corpus(world, queries)
    ungrounded = tuple(record.model_copy(update={"fact_ids": ()}) for record in corpus.connector_data.records)
    corpus = corpus.model_copy(update={"connector_data": corpus.connector_data.model_copy(update={"records": ungrounded})})
    with pytest.raises(ServingError, match=r"invalid_corpus.*carries no fact"):
        ConnectorEvaluationService.from_corpus(corpus)


def test_from_corpus_preserves_custom_fields_and_injected_failure_over_http() -> None:
    from test_enterprise_fields_state import FIELD, _registry

    from worldloom.enterprise_corpus import materialize_corpus
    from worldloom.enterprise_queries import plan_queries
    from worldloom.enterprise_specs import CoverageProfile
    from worldloom.world import World

    world = World.load("retail-close")
    queries, _ = plan_queries(world, registry=_registry(), profile=CoverageProfile(
        strengths=1, connector_counts=(1,), failures=("permission_denied",),
    ))
    corpus = materialize_corpus(world, queries)
    runtime = ConnectorEvaluationService.from_corpus(corpus)
    query = corpus.queries[0]
    fixture = corpus.fixtures[0]
    read = next(node for node in runtime.rows[query.id]["expected_dag"]["nodes"] if node["id"] == "read-0")
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://localhost") as client:
        run = call(client, "eval_begin", {"query_id": query.id})["run_id"]
        payload = call(client, "servicenow.search_records", {"run_id": run, "entity": "incident", **read["payload"]})
        assert payload["items"]
        assert all(item[FIELD.id] in FIELD.options for item in payload["items"])
        failed = rpc(client, "tools/call", {"name": "servicenow.update_record", "arguments": {
            "run_id": run, "id": fixture.destination_record_id, "fields": {"state": "assess"},
        }})
        assert failed["isError"]
        trace = call(client, "eval_trace", {"run_id": run})
        assert trace["spans"][0]["node"] == "read-0"
        assert trace["spans"][1]["error"]["code"] == 403


def test_authored_partial_write_retains_state_and_grades_the_actual_failure() -> None:
    from worldloom.enterprise_failures import compile_failure_contract

    target = row()
    for node, op in zip(target["expected_dag"]["nodes"], ("read", "update", "read"), strict=True):
        node["op"] = op
    target["state_overrides"] = [{"kind": "partial_write", "connector": "servicenow", "record_id": "f1", "details": {}}]
    target = compile_failure_contract(target)
    runtime = ConnectorEvaluationService([target], records())
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://localhost") as client:
        run = call(client, "eval_begin", {"query_id": "q1"})["run_id"]
        call(client, "servicenow.get_record", {"run_id": run, "id": "INC0000001"})
        result = rpc(client, "tools/call", {"name": "servicenow.update_record", "arguments": {
            "run_id": run, "id": "INC0000001", "fields": {"state": "open"},
        }})
        assert result["isError"]
        trace = call(client, "eval_trace", {"run_id": run})
        assert trace["spans"][1]["writes"] == ["f1"]
        assert trace["spans"][1]["error"]["code"] == 207
        assert call(client, "eval_grade", {"run_id": run})["status"] == "behavior"
        assert runtime._runs[run].emulators["servicenow"].records["f1"]["state"] == "open"


@pytest.mark.parametrize("shape,count", [("conditional", 1), *[(shape, 3) for shape in ("conditional", "deep_chain", "delete_chain", "diamond", "fan_in", "fan_out", "map_read", "read_chain", "write_chain")]])
def test_external_calls_execute_every_shipped_dag_shape(shape: str, count: int) -> None:
    from test_enterprise_dag import compiled

    from worldloom.connector_eval_runtime import run_eval_row

    target, data = compiled(shape, count)
    reference = run_eval_row(target, data)
    assert reference.grade["fails"] == []
    runtime = ConnectorEvaluationService([target], data)
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://localhost") as client:
        advertised = rpc(client, "tools/list", {})["tools"]
        assert not any(tool["name"].startswith("model.") for tool in advertised)
        run = call(client, "eval_begin", {"query_id": target["id"]})["run_id"]
        for span in reference.spans:
            if span.error:
                # The readback after a delete is expected to fail, served or not.
                failed = rpc(client, "tools/call", {"name": span.tool, "arguments": {"run_id": run, **span.args}})
                assert failed.get("isError"), failed
                continue
            call(client, span.tool, {"run_id": run, **span.args})
        grade = call(client, "eval_grade", {"run_id": run})
        assert grade["fails"] == [], (shape, grade)
        observed = call(client, "eval_trace", {"run_id": run})
        assert [span["node"] for span in observed["spans"]] == [span.node for span in reference.spans]
        assert [(span["node"], span["error"]["kind"]) for span in observed["spans"] if span.get("error")] == \
            [(span.node, span.error["kind"]) for span in reference.spans if span.error]


def test_external_mapped_creates_bind_each_actual_source_and_verify_each_created_record() -> None:
    from test_enterprise_dag import compiled

    from worldloom.connector_eval_runtime import run_eval_row

    target, data = compiled("map_read")
    nodes = target["expected_dag"]["nodes"]
    writer = next(node for node in nodes if node["id"] == "write")
    writer["for_each"] = {"node": "read-0", "limit": 100}
    writer["payload"].pop("name", None)
    writer["bindings"]["name"] = {"node": "read-0", "select": "item", "path": ["title"]}
    verifier = next(node for node in nodes if node["node_kind"] == "verify")
    verifier["for_each"] = {"node": "write", "limit": 100}
    verifier["bindings"]["id"] = {"node": "write", "select": "item", "path": ["id"]}
    reference = run_eval_row(target, data)
    assert reference.grade["fails"] == []
    runtime = ConnectorEvaluationService([target], data)
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://localhost") as client:
        run = call(client, "eval_begin", {"query_id": target["id"]})["run_id"]
        for span in reference.spans:
            call(client, span.tool, {"run_id": run, **span.args})
        grade = call(client, "eval_grade", {"run_id": run})
        assert grade["fails"] == [], grade
        trace = call(client, "eval_trace", {"run_id": run})
        writes = [span for span in trace["spans"] if span["node"] == "write"]
        assert len(writes) == 3
        assert len({span["writes"][0] for span in writes}) == 3


@pytest.mark.parametrize("operation", ["create", "send"])
def test_legacy_email_payloads_conform_to_the_real_http_schema(operation: str) -> None:
    from test_enterprise_dag import query_and_fixture

    from worldloom.connector_eval_runtime import run_eval_row
    from worldloom.enterprise_queries import MutationRequirement
    from worldloom.enterprise_rows import compile_row

    query, fixture, data = query_and_fixture("fan_in", 1)
    mutation = MutationRequirement(connector="email", entity="message", operation=operation,
                                   output_format="record", preexisting_record=False)
    query = query.model_copy(update={"dimensions": {}, "generation": query.generation.model_copy(update={"mutation": mutation}),
                                    "expected_dag": (
                                        {"id": "read-0", "connector": "jira", "entity": "issue", "kind": "read", "depends_on": []},
                                        {"id": "write", "connector": "email", "entity": "message", "kind": operation, "depends_on": ["read-0"]},
                                        {"id": "verify", "connector": "email", "entity": "message", "kind": "readback", "depends_on": ["write"]},
                                    )})
    target = compile_row(query, fixture, data)
    reference = run_eval_row(target, data)
    assert reference.grade["fails"] == []
    runtime = ConnectorEvaluationService([target], data)
    with TestClient(create_connector_app(runtime, bearer_tokens=TOKENS), base_url="http://localhost") as client:
        run = call(client, "eval_begin", {"query_id": target["id"]})["run_id"]
        for span in reference.spans:
            call(client, span.tool, {"run_id": run, **span.args})
        assert call(client, "eval_grade", {"run_id": run})["fails"] == []
