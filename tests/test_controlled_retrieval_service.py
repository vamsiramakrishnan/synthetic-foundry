"""Controlled retrieval uses real service state and keeps its oracle off the wire."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import pytest

from worldloom.connector_emulator import ConnectorError
from worldloom.connectors.serving import ServingError, ServingLimits
from worldloom.evalrun.agents import (
    AgentResponse,
    AgentTask,
    CallableAgent,
    ToolSurface,
)
from worldloom.evalrun.contract import EvalCase, case_from_row
from worldloom.evalrun.retrieval import (
    QueryAlias,
    QueryIntent,
    RetrievalContract,
    RetrievalFault,
)
from worldloom.evalrun.runner import run_case, run_cases, service_for
from worldloom.predicates import FieldPredicate

pytestmark = pytest.mark.usefixtures("native_surface")


def _contract(*, faults: tuple[RetrievalFault, ...] = ()) -> RetrievalContract:
    return RetrievalContract(
        id="private-report-intent", connector="servicenow", tool="search_records",
        intent=QueryIntent(entity="incident", scope=(FieldPredicate(field="region", value="APAC"),),
                           period=(FieldPredicate(field="period", value="FY2026"),),
                           authority=(FieldPredicate(field="approval", value="approved"),)),
        aliases=(QueryAlias(field="region", canonical="APAC", alternatives=("Asia Pacific",)),), faults=faults,
    )


def _row(*, contract: RetrievalContract | None = None) -> dict[str, Any]:
    return {
        "id": "reports", "query": "Find approved FY2026 APAC incident reports and read the full report.",
        "controlled_retrieval": (contract or _contract()).model_dump(mode="json"),
        "expected_dag": {"nodes": [
            {"id": "find", "server": "servicenow", "tool": "search_records", "entity": "incident",
             "op": "search", "expected_reads": ["current"]},
            {"id": "read", "server": "servicenow", "tool": "get_record", "entity": "incident",
             "op": "read", "fixture": "current"},
        ], "edges": [["find", "read"]]},
        "assertions": [{"type": "tool_called", "node": node} for node in ("find", "read")]
        + [{"type": "reads_contain", "node": "find", "records": ["current"]}],
    }


def _records() -> list[dict[str, Any]]:
    return [
        {"fid": fid, "server": "servicenow", "entity": "incident", "ident": f"INC000000{index}",
         "region": region, "period": period, "approval": approval, "state": "new",
         "short_description": f"{period} {region} {approval} incident report", "description": "Verified source body"}
        for index, (fid, region, period, approval) in enumerate((
            ("current", "APAC", "FY2026", "approved"),
            ("stale", "APAC", "FY2025", "draft"),
            ("foreign", "EMEA", "FY2026", "approved"),
        ), start=1)
    ]


def _sufficient() -> dict[str, Any]:
    return {"entity": "incident", "predicate": {"approval": "approved", "period": "FY2026", "region": "Asia Pacific"}}


def test_public_only_agent_recovers_and_receipts_stay_private() -> None:
    case = case_from_row(_row())
    service = service_for((case,), _records())
    seen: list[dict[str, Any]] = []

    def target(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        # The target sees only the user request and ordinary connector tools.
        assert "FY2026" in task.query and "APAC" in task.query and "approved" in task.query
        public = json.dumps({"task": task.model_dump(), "tools": tools.tools()}, sort_keys=True)
        assert "contract_id" not in public and "private-report-intent" not in public
        assert "missing_dimensions" not in public and "on_insufficient" not in public
        search = next(tool for tool in tools.tools() if tool["name"] == "servicenow.search_records")
        assert search["query"]["argument"] == "predicate"
        assert {"region", "period", "approval"} <= set(search["query"]["fields"])
        assert "query" not in search["params"]
        first = tools.call("servicenow.search_records", entity="incident", predicate={"region": "APAC"})
        assert first["items"] == []
        assert "missing_dimensions" not in json.dumps(first)
        answer = tools.call("servicenow.search_records", **_sufficient())
        assert len(answer["items"]) == 1
        tools.call("servicenow.get_record", id=answer["items"][0]["number"])
        for span in tools.spans:
            wire = asdict(span)
            assert "retrieval" not in wire
            assert "missing_dimensions" not in json.dumps(wire)
        seen.extend(answer["items"])
        return AgentResponse(answer="Read the approved FY2026 APAC source.")

    result = run_case(service, case, CallableAgent(target, name="public-only"))
    assert result.status == "graded", result.error
    assert seen
    receipts = [span["retrieval"] for span in result.spans if "retrieval" in span]
    assert [receipt["intent_status"] for receipt in receipts] == ["insufficient", "sufficient"]
    assert receipts[1]["progress"] == "refinement"
    assert [span["node"] for span in result.spans] == [None, "find", "read"]
    assert receipts[1]["returned"][0]["record_id"] == "current"
    assert receipts[1]["returned"][0]["source_digest"]
    assert result.score is not None and result.score.passed, result.score
    assert result.execution_mode == "controlled_retrieval"
    assert result.score.trajectory.retrieval is not None
    assert result.score.trajectory.retrieval.recovered == 1


def test_trace_wire_and_score_wire_do_not_publish_private_receipts() -> None:
    case = case_from_row(_row())
    service = service_for((case,), _records())
    run = service.begin("agent", case.id)["run_id"]
    service.call("agent", run, "servicenow.search_records", _sufficient())
    trace = service.trace("agent", run)
    assert "retrieval" not in trace["spans"][0]
    assert "missing_dimensions" not in json.dumps(trace)
    score = service.score("agent", run)
    assert "retrieval" not in score["spans"][0]
    assert service.grading_spans("agent", run)[0]["retrieval"]["intent_status"] == "sufficient"
    service.end("agent", run)


def test_target_cannot_supply_delivery_receipts() -> None:
    case = case_from_row(_row())
    service = service_for((case,), _records())

    def target(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        with pytest.raises(ServingError, match="unknown_arguments"):
            tools.call("servicenow.search_records", **_sufficient(),
                       retrieval={"intent_status": "sufficient", "returned": [{"record_id": "current"}]})
        return AgentResponse(answer="Correct", program={"retrieval": {"intent_status": "sufficient"}})

    result = run_case(service, case, CallableAgent(target, name="forger"))
    assert result.status == "graded"
    assert result.spans == ()
    assert result.score is not None and not result.score.passed
    assert result.refused == 1


def test_response_limit_never_counts_as_delivery() -> None:
    case = case_from_row(_row())
    service = service_for((case,), _records(), limits=ServingLimits(max_response_bytes=100))
    run = service.begin("agent", case.id)["run_id"]
    with pytest.raises(ConnectorError, match="response_limit"):
        service.call("agent", run, "servicenow.search_records", _sufficient())
    span = service.grading_spans("agent", run)[0]
    assert span["retrieval"]["intent_status"] == "transport_fault"
    assert span["retrieval"]["returned"] == []
    assert span["reads"] == [] and span["node"] is None
    assert service.snapshot("agent", run)["current"]["period"] == "FY2026"
    service.end("agent", run)


def test_response_limit_retains_attempt_count_and_allows_smaller_page_recovery() -> None:
    case = case_from_row(_row(contract=_contract(faults=(RetrievalFault(attempt=2, kind="rate_limit"),))))
    records = _records()
    records.append({**records[0], "fid": "current2", "ident": "INC0000004"})
    service = service_for((case,), records, limits=ServingLimits(max_response_bytes=650))
    run = service.begin("agent", case.id)["run_id"]
    with pytest.raises(ConnectorError, match="response_limit"):
        service.call("agent", run, "servicenow.search_records", {**_sufficient(), "max_results": 2})
    with pytest.raises(ConnectorError, match="Too many requests"):
        service.call("agent", run, "servicenow.search_records", {**_sufficient(), "max_results": 1})
    first = service.call("agent", run, "servicenow.search_records", {**_sufficient(), "max_results": 1})
    assert len(first["items"]) == 1 and not first["is_last"]
    service.call("agent", run, "servicenow.search_records", {**_sufficient(), "max_results": 1, "start_at": 1})
    receipts = [span["retrieval"] for span in service.grading_spans("agent", run)]
    assert [receipt["intent_status"] for receipt in receipts] == ["transport_fault", "transport_fault", "sufficient", "sufficient"]
    assert receipts[0]["returned"] == []
    assert receipts[2]["progress"] == "retry"
    assert receipts[3]["progress"] == "pagination"
    assert "missing_dimensions" not in json.dumps(service.trace("agent", run))
    service.end("agent", run)


def test_transient_retry_receipts_and_runs_are_isolated() -> None:
    case = case_from_row(_row(contract=_contract(faults=(RetrievalFault(attempt=1),))))
    service = service_for((case,), _records())
    for principal in ("alice", "bob"):
        run = service.begin(principal, case.id)["run_id"]
        with pytest.raises(ConnectorError, match="Gateway timeout"):
            service.call(principal, run, "servicenow.search_records", _sufficient())
        service.call(principal, run, "servicenow.search_records", _sufficient())
        spans = service.grading_spans(principal, run)
        assert [span["retrieval"]["intent_status"] for span in spans] == ["transport_fault", "sufficient"]
        assert spans[1]["retrieval"]["progress"] == "retry"
        assert spans[1]["node"] == "find"
        service.end(principal, run)


def test_contract_schema_and_source_satisfiability_fail_before_target() -> None:
    row = _row()
    row["controlled_retrieval"]["intent"]["unknown"] = "not allowed"
    with pytest.raises(ValueError, match="unknown"):
        case_from_row(row)
    valid = case_from_row(_row())
    serialized = valid.model_dump(mode="json")
    serialized["row"]["controlled_retrieval"] = None
    with pytest.raises(ValueError):
        EvalCase.model_validate(serialized)
    with pytest.raises(ServingError, match="no visible source"):
        service_for((valid,), [record for record in _records() if record["fid"] != "current"])


def test_contract_cannot_ambiguously_control_two_search_nodes() -> None:
    row = _row()
    row["expected_dag"]["nodes"].append({**row["expected_dag"]["nodes"][0], "id": "other-search"})
    with pytest.raises(ServingError, match="exactly one planned search node"):
        service_for((case_from_row(row),), _records())


def test_uncontrolled_service_retains_ordinary_trace_shape() -> None:
    row = _row()
    del row["controlled_retrieval"]
    case = case_from_row(row)
    service = service_for((case,), _records())
    run = service.begin("agent", case.id)["run_id"]
    service.call("agent", run, "servicenow.search_records", {"entity": "incident", "predicate": {"region": "APAC"}})
    assert service.grading_spans("agent", run) == service.spans("agent", run)
    assert "retrieval" not in json.dumps(service.trace("agent", run))
    service.end("agent", run)


def test_mixed_bundle_serves_the_controlled_case_on_its_actual_typed_surface() -> None:
    controlled = case_from_row(_row())
    row = _row()
    del row["controlled_retrieval"]
    row["id"] = "ordinary"
    ordinary = case_from_row(row)
    service = service_for((controlled, ordinary), _records(), surface="contract")
    controlled_run = service.begin("agent", controlled.id)
    ordinary_run = service.begin("agent", ordinary.id)
    assert controlled_run["execution_mode"] == "controlled_retrieval"
    assert "execution_mode" not in ordinary_run
    assert service.surface_for("agent", controlled_run["run_id"]) == "native"
    assert service.surface_for("agent", ordinary_run["run_id"]) == "contract"
    typed = service.tool_catalog("agent", controlled_run["run_id"])
    vendor = service.tool_catalog("agent", ordinary_run["run_id"])
    assert any(tool["name"] == "servicenow.search_records" for tool in typed)
    assert all(tool["name"] != "servicenow.search_records" for tool in vendor)
    answer = service.call("agent", controlled_run["run_id"], "servicenow.search_records", _sufficient())
    assert len(answer["items"]) == 1
    with pytest.raises(ServingError, match="tool_not_served"):
        service.call("agent", ordinary_run["run_id"], "servicenow.search_records", _sufficient())
    service.end("agent", controlled_run["run_id"])
    service.end("agent", ordinary_run["run_id"])


def test_external_anvil_cannot_silently_remove_controlled_observations() -> None:
    case = case_from_row(_row())
    service = service_for((case,), _records())

    def target(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        pytest.fail("incompatible service must fail preflight")

    agent = CallableAgent(target, name="never")
    with pytest.raises(ServingError, match="external Anvil serving"):
        run_cases(service, (case,), agent, anvil=object())  # type: ignore[arg-type]
    assert service._ordinal == 0


def test_controlled_typed_surface_over_actual_mcp_http() -> None:
    pytest.importorskip("mcp.server.mcpserver")
    from starlette.testclient import TestClient

    from worldloom.connectors.serving import create_connector_app

    case = case_from_row(_row())
    service = service_for((case,), _records(), surface="contract")
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    with TestClient(create_connector_app(service), base_url="http://localhost") as client:
        def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
            response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1,
                                                                 "method": method, "params": params})
            assert response.status_code == 200, response.text
            return response.json()["result"]

        def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            result = rpc("tools/call", {"name": name, "arguments": arguments})
            assert not result.get("isError"), result
            return json.loads(result["content"][0]["text"])

        tools = rpc("tools/list", {})["tools"]
        search = next(tool for tool in tools if tool["name"] == "servicenow.search_records")
        predicate = search["inputSchema"]["properties"]["predicate"]
        assert {"region", "period", "approval"} <= set(predicate["properties"]["where"]["items"]["properties"]["field"]["enum"])
        assert "private-report-intent" not in json.dumps(tools)
        begun = call("eval_begin", {"query_id": case.id})
        assert begun["execution_mode"] == "controlled_retrieval"
        run = begun["run_id"]
        empty = call("servicenow.search_records", {"run_id": run, "entity": "incident", "predicate": {"region": "APAC"}})
        assert empty["items"] == []
        found = call("servicenow.search_records", {"run_id": run, **_sufficient()})
        call("servicenow.get_record", {"run_id": run, "id": found["items"][0]["number"]})
        trace = call("eval_trace", {"run_id": run})
        assert "missing_dimensions" not in json.dumps(trace)
        score = call("eval_score", {"run_id": run, "answer": "Read the approved source."})
        assert score["score"]["passed"], score
        assert score["score"]["trajectory"]["retrieval"]["recovered"] == 1
        call("eval_end", {"run_id": run})
