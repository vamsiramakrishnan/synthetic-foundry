"""One surface from the contract: the tools served in process are the tools Anvil's MCP server lists, and answer alike.

The contract surface (``worldloom.connectors.surface``) presents each
contracted connector's operations exactly as Anvil projects them for MCP and
dispatches a call through the connector's Anvil mapping, the dispatch the
stdio provider also runs. Without Anvil these tests hold the shipped
surfaces to their mappings and the service to the surface. With Anvil (and
node) they compile each committed trim, list the tools Anvil's own
generated MCP server serves for it and require the same tool list, names,
titles, descriptions and input schemas in process; then they run one call
sequence per connector twice, in process and through Anvil's MCP server
over ``anvil simulate serve`` and the Worldloom provider, and require the
same results.

What Anvil cannot yet do is not a silent pass: it is recorded against the
named capability and the test xfails naming it, after every other assertion
held.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import test_contract_parity as parity

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator
from worldloom.connectors.anvil import (
    EmulatorBackend,
    lint_mapping,
    load_mapping,
    operations_from_air,
)
from worldloom.connectors.contracts import build, load_lock
from worldloom.connectors.surface import (
    SURFACE_SCHEMA,
    ContractCallError,
    parse_surface,
    project,
    serving_surface,
    shipped_surface,
    shipped_surfaces,
    surface_in_force,
)
from worldloom.corpus import write_jsonl

FIXTURES = Path(__file__).parent / "fixtures" / "anvil" / "contracts"
SRC = Path(__file__).resolve().parent.parent / "src"
ANVIL = parity.ANVIL
needs_anvil = parity.needs_anvil
CONNECTORS = tuple(sorted(load_lock().contracts))

#: Anvil's MCP server converts a tool's input schema with the MCP SDK's zod
#: converter, which refuses a Discovery schema that names two different
#: schemas by one `id`: listing Drive's file lane fails for the whole list.
DRIVE_SCHEMA_IDS = "Anvil MCP tools/list: the zod converter refuses Drive's file schemas (duplicate schema id)"


# -- without Anvil -------------------------------------------------------------------------


def test_every_locked_contract_ships_a_surface() -> None:
    assert shipped_surfaces() == CONNECTORS


@pytest.mark.parametrize("connector", CONNECTORS)
def test_a_shipped_surface_is_served_through_its_mapping(connector: str) -> None:
    surface = shipped_surface(connector)
    definition = load_connector_definition(connector)
    mapping = load_mapping(connector)
    names = [tool.name for tool in surface.tools]
    assert len(names) == len(set(names)) == load_lock().contract(connector).profiled_operations
    assert all(name.startswith(f"{connector}_") for name in names), names
    for tool in surface.tools:
        assert tool.binding["operation"], tool.name
        assert tool.input_schema.get("type") == "object", tool.name
        assert surface.entry(tool) is not None, f"{tool.operation} is exposed and not in the mapping"
    # The surface and the mapping describe the same contract.
    operations = [parity_operation for parity_operation in _operations(surface)]
    errors, _ = lint_mapping(mapping, operations, definition)
    assert errors == ()


def _operations(surface: Any) -> list[Any]:
    from worldloom.connectors.anvil import ContractOperation

    return [ContractOperation(tool.operation, method=tool.binding.get("method"), path=tool.binding.get("path"))
            for tool in surface.tools]


def test_the_contract_surface_is_the_default_and_native_stays_selectable() -> None:
    # The default flipped once every generated case proved on the contract
    # surface (the planner writes evidence where each vendor keeps it); the
    # connector definitions' own tools are still one flag away.
    assert surface_in_force() == "contract"
    with serving_surface("native"):
        assert surface_in_force() == "native"
    assert surface_in_force() == "contract"


def _jira_service(surface: str) -> Any:
    from worldloom.connectors.serving import ConnectorEvaluationService

    records = parity._jira_records()
    row = {"id": "q1", "query": "Find the Sev-1 issues", "expected_dag": {
        "nodes": [{"id": "n1", "server": "jira", "tool": "search_issues", "op": "search", "entity": "task",
                   "payload": {"query": "project = OPS"}}], "edges": []}, "assertions": []}
    return ConnectorEvaluationService([row], records, surface=surface, query_engine="native")


def test_the_service_lists_the_contract_tools_in_place_of_the_connectors() -> None:
    from worldloom.connectors.serving import ServingError

    service = _jira_service("contract")
    run = service.begin("agent", "q1")["run_id"]
    catalog = service.tool_catalog("agent", run)
    surface = shipped_surface("jira")
    assert [entry["name"] for entry in catalog] == [tool.name for tool in surface.tools]
    assert [entry["inputSchema"] for entry in catalog] == [dict(tool.input_schema) for tool in surface.tools]
    assert all(entry["surface"] == "contract" and entry["connector"] == "jira" for entry in catalog)
    search = next(entry for entry in catalog if entry["name"] == "jira_search_and_reconsile_issues_using_jql_post")
    # The mapped call reads a JQL query: its grammar rides the tool, against the argument that carries it.
    assert search["query"]["language"] == "jql" and search["query"]["argument"] == "body.jql"
    with pytest.raises(ServingError, match="tool_not_served"):
        service.call("agent", run, "jira.get_issue", {"id": "OPS-1"})
    assert service.refusals("agent", run)[-1]["error"].startswith("tool_not_served")
    native = _jira_service("native")
    assert all("." in entry["name"] for entry in native.tool_catalog("agent", native.begin("agent", "q1")["run_id"]))


def test_a_contract_call_is_graded_as_the_connector_call_it_becomes() -> None:
    service = _jira_service("contract")
    run = service.begin("agent", "q1")["run_id"]
    body = service.call("agent", run, "jira_get_issue", {"issue_id_or_key": "OPS-2"})
    assert body["key"] == "OPS-2" and body["fields"]["status"] == {"name": "To Do"}
    page = service.call("agent", run, "jira_search_and_reconsile_issues_using_jql_post",
                        {"body": {"jql": "project = OPS ORDER BY created ASC", "maxResults": 2}})
    # The simulator's page envelope: Jira's `issues` and the continuation Anvil writes.
    assert [issue["key"] for issue in page["issues"]] == ["OPS-1", "OPS-2"] and page["nextPageToken"] == "2"
    spans = service.spans("agent", run)
    assert [span.tool for span in spans] == ["jira.get_issue", "jira.search_issues"]
    assert spans[1].args == {"query": "project = OPS ORDER BY created ASC", "max_results": 2}


def test_a_refusal_is_anvils_envelope_and_counts_against_the_mapped_tool() -> None:
    service = _jira_service("contract")
    run = service.begin("agent", "q1")["run_id"]
    with pytest.raises(ContractCallError) as missing:
        service.call("agent", run, "jira_get_issue", {})
    assert missing.value.envelope["error"]["code"] == "validation_error"
    assert "issue_id_or_key" in missing.value.envelope["error"]["message"]
    with pytest.raises(ContractCallError) as unconfirmed:
        service.call("agent", run, "jira_add_comment", {"issue_id_or_key": "OPS-1", "body": {"body": "x"}})
    # The published schema requires `confirm: true` of a write that needs confirmation, as the MCP server does.
    assert unconfirmed.value.kind == "validation_error" and "confirm" in unconfirmed.value.message
    with pytest.raises(ContractCallError) as unmodelled:
        service.call("agent", run, "jira_delete_issue", {"issue_id_or_key": "OPS-1", "confirm": True})
    # Anvil's runtime serves the contract's declared message for the status, never the provider's prose.
    assert unmodelled.value.code == 404 and unmodelled.value.kind == "not_found"
    with pytest.raises(ContractCallError) as absent:
        service.call("agent", run, "jira_get_issue", {"issue_id_or_key": "OPS-404"})
    assert absent.value.code == 404
    refusals = service.refusals("agent", run)
    # An unmodelled operation maps to no connector tool: it counts against the contract tool itself.
    assert [item["tool"] for item in refusals] == ["jira.get_issue", "jira.add_comment", "jira.jira_delete_issue"]
    assert refusals[2]["error"].startswith("anvil_unsupported_operation")
    # A call the connector answered is a span with its error, not a refusal.
    assert service.spans("agent", run)[-1].error["code"] == 404


def test_the_mcp_server_serves_the_contract_tools_with_anvils_schemas() -> None:
    pytest.importorskip("mcp")
    from starlette.testclient import TestClient

    from worldloom.connectors.serving import create_connector_app

    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25",
               "Authorization": "Bearer alice-private-evaluation-secret"}

    def rpc(client: TestClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                                              "params": params})
        assert response.status_code == 200, response.text
        return dict(response.json()["result"])

    service = _jira_service("contract")
    app = create_connector_app(service, bearer_tokens={"alice": "alice-private-evaluation-secret"})
    surface = shipped_surface("jira")
    with TestClient(app, base_url="http://localhost") as client:
        rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                   "clientInfo": {"name": "external-agent", "version": "1"}})
        listed = {tool["name"]: tool for tool in rpc(client, "tools/list", {})["tools"]}
        assert {name for name in listed if not name.startswith("eval_")} == set(surface.names)
        for tool in surface.tools:
            served = listed[tool.name]
            # The evaluation server adds the run id every one of its tools takes; the rest is Anvil's.
            schema = dict(served["inputSchema"])
            assert schema["properties"].pop("run_id")["type"] == "string"
            assert schema["required"][0] == "run_id"
            assert {**schema, "required": schema["required"][1:]} == {**tool.input_schema,
                                                                    "required": list(tool.input_schema.get("required") or ())}
            assert served["description"] == tool.definition["description"]
        run = json.loads(rpc(client, "tools/call", {"name": "eval_begin", "arguments": {"query_id": "q1"}})
                         ["content"][0]["text"])["run_id"]
        got = rpc(client, "tools/call", {"name": "jira_get_issue", "arguments": {"run_id": run, "issue_id_or_key": "OPS-2"}})
        assert not got.get("isError") and json.loads(got["content"][0]["text"])["key"] == "OPS-2"
        missing = rpc(client, "tools/call", {"name": "jira_get_issue", "arguments": {"run_id": run, "issue_id_or_key": "OPS-404"}})
        assert missing["isError"] and '"not_found"' in missing["content"][0]["text"]
    assert [span.tool for span in service.spans("alice", run)] == ["jira.get_issue", "jira.get_issue"]


def test_carry_is_the_mapping_run_backwards_and_checked_forwards() -> None:
    surface = shipped_surface("jira")
    definition = load_connector_definition("jira")
    carried = surface.carry("search_issues", {"query": "project = OPS", "max_results": 2, "start_at": 2,
                                              "entity": "task"}, definition)
    assert carried.tool == "jira_search_and_reconsile_issues_using_jql_post"
    assert carried.arguments == {"body": {"jql": "project = OPS", "maxResults": 2, "nextPageToken": "2"}}
    carried = surface.carry("transition_issue", {"id": "OPS-1", "state": "done"}, definition)
    assert carried.arguments == {"issue_id_or_key": "OPS-1", "body": {"transition": {"id": "41"}}}
    assert surface.carry("add_comment", {"id": "OPS-1", "body": "hi"}, definition).arguments["confirm"] is True
    # A read is carried by the operation that answers with the record, not by one answered from part of it.
    assert surface.carry("get_issue", {"id": "OPS-1"}, definition).tool == "jira_get_issue"


def test_the_program_client_names_contract_operations_as_anvils_sdk_does() -> None:
    from worldloom.evalrun.program import (
        client_methods,
        client_source,
        declared_from_program,
    )

    catalog = shipped_surface("jira").catalog(load_connector_definition("jira"))
    source = client_source(catalog)
    assert "    def get_issue(self, **arguments):" in source
    assert "return call('jira_get_issue', **arguments)" in source
    methods = client_methods(catalog)
    program = "issue = jira.get_issue(issue_id_or_key='OPS-1')\njira.edit_issue(issue_id_or_key=issue['key'], body={})\n"
    declared = declared_from_program(program, [entry["name"] for entry in catalog], methods=methods)
    assert declared is not None
    assert [node["tool"] for node in declared["nodes"]] == ["jira_get_issue", "jira_edit_issue"]


def test_a_surface_document_is_refused_without_its_schema() -> None:
    from worldloom.connectors.surface import SurfaceError

    with pytest.raises(SurfaceError, match="schema"):
        parse_surface({"connector": "jira", "tools": []})
    assert SURFACE_SCHEMA == "worldloom.contract-surface/v1"


# -- through Anvil -------------------------------------------------------------------------


class McpClient:
    """Anvil's generated MCP server on stdio: ``initialize``, then JSON-RPC requests."""

    def __init__(self, bundle: Path, *, env: dict[str, str] | None = None) -> None:
        assert ANVIL is not None
        self.process = subprocess.Popen([*ANVIL, "serve", "mcp", str(bundle)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                        env={**os.environ, **(env or {})})
        self.ordinal = 0
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "worldloom-tests", "version": "1"}})
        self.notify("notifications/initialized")

    def notify(self, method: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.ordinal += 1
        message = {"jsonrpc": "2.0", "id": self.ordinal, "method": method, **({"params": params} if params else {})}
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise AssertionError(f"Anvil's MCP server closed during {method}")
            reply = json.loads(line)
            if reply.get("id") == self.ordinal:
                return dict(reply)

    def lanes(self) -> list[str]:
        listed = self.request("tools/list")["result"]["tools"]
        return [tool["name"] for tool in listed if (tool.get("_meta") or {}).get("anvil/lane")]

    def open_all(self) -> None:
        for lane in self.lanes():
            self.request("tools/call", {"name": lane, "arguments": {}})

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        self.process.terminate()
        self.process.wait(timeout=30)
        if self.process.stdout is not None:
            self.process.stdout.close()


def _operation_tools(listed: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {tool["name"]: tool for tool in listed if not (tool.get("_meta") or {}).get("anvil/lane")}


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("contracts")


def _bundle(connector: str, cache: Path) -> Path:
    assert ANVIL is not None
    return build(connector, cache=cache, anvil=ANVIL, spec=FIXTURES / f"{connector}.spec.json.gz").bundle


def _listed(bundle: Path, landing: parity.Landing) -> dict[str, dict[str, Any]]:
    """Every operation tool Anvil's MCP server lists for *bundle*, every disclosure lane opened.

    A lane whose listing Anvil refuses is opened on its own server, so the
    rest are still compared; the refusal is recorded against its capability.
    """
    client = McpClient(bundle)
    try:
        listed = client.request("tools/list")
        lanes = client.lanes()
        client.open_all()
        flat = client.request("tools/list")
    finally:
        client.close()
    if "result" in flat:
        return _operation_tools(flat["result"]["tools"])
    out = _operation_tools(listed["result"]["tools"])
    for lane in lanes:
        one = McpClient(bundle)
        try:
            one.request("tools/call", {"name": lane, "arguments": {}})
            reply = one.request("tools/list")
        finally:
            one.close()
        if "result" in reply:
            out.update(_operation_tools(reply["result"]["tools"]))
        else:
            landing.expect(False, DRIVE_SCHEMA_IDS if "duplicate schema id" in str(reply).casefold()
                           else f"Anvil MCP tools/list refused lane {lane}: {reply.get('error')}")
    return out


@needs_anvil
@pytest.mark.parametrize("connector", CONNECTORS)
def test_the_in_process_tools_are_the_tools_anvils_mcp_server_lists(connector: str, cache: Path) -> None:
    assert ANVIL is not None
    bundle = _bundle(connector, cache)
    surface = shipped_surface(connector)
    # The shipped surface is what Anvil projects for the committed trim today: the drift gate.
    fresh = project(bundle, connector, anvil=ANVIL)
    assert fresh["tools"] == [dict(tool.definition) for tool in surface.tools]
    assert fresh["bindings"] == {tool.name: dict(tool.binding) for tool in surface.tools}
    landing = parity.Landing()
    served = _listed(bundle, landing)
    ours = {tool.name: tool for tool in surface.tools}
    if landing.pending:
        # Anvil lists none of a refused lane's tools; every one it does list is compared.
        assert set(served) < set(ours) and {tool.name for tool in surface.tools if tool.unprojected} - set(served)
    else:
        assert set(served) == set(ours)
    for name, tool in served.items():
        mine = ours[name].definition
        for key in ("title", "description", "inputSchema", "annotations"):
            assert mine.get(key) == tool.get(key), f"{name}.{key}"
    landing.settle()


# -- one call sequence, two transports -----------------------------------------------------


Step = tuple[str, dict[str, Any]] | Callable[[list[Any]], tuple[str, dict[str, Any]]]


def _jira_steps() -> list[Step]:
    jql = 'project = OPS AND cf[10231] = "Sev-1" ORDER BY created ASC'
    return [
        ("jira_search_and_reconsile_issues_using_jql_post", {"body": {"jql": jql, "maxResults": 2}}),
        lambda prior: ("jira_search_and_reconsile_issues_using_jql_post",
                       {"body": {"jql": jql, "maxResults": 2, "nextPageToken": prior[-1]["nextPageToken"]}}),
        ("jira_get_issue", {"issue_id_or_key": "OPS-2"}),
        ("jira_create_issue", {"confirm": True, "body": {"fields": {
            "summary": "Vendor follow-up", "project": {"key": "OPS"}, "issuetype": {"name": "Task"},
            "customfield_10231": {"value": "Sev-2"}}}}),
        ("jira_edit_issue", {"issue_id_or_key": "OPS-1", "body": {"fields": {"summary": "Renamed"}}}),
        ("jira_do_transition", {"issue_id_or_key": "OPS-3", "body": {"transition": {"id": "31"}}}),
        ("jira_add_comment", {"issue_id_or_key": "OPS-1", "confirm": True, "body": {"body": parity._adf("Checked")}}),
        ("jira_get_comments", {"issue_id_or_key": "OPS-1"}),
        ("jira_get_issue", {"issue_id_or_key": "OPS-404"}),
        ("jira_search_and_reconsile_issues_using_jql_post", {"body": {"jql": "project = OPS AND"}}),
        ("jira_delete_issue", {"issue_id_or_key": "OPS-1", "confirm": True}),
        ("jira_get_issue", {"issue_id_or_key": "OPS-1"}),
    ]


def _servicenow_steps() -> list[Step]:
    return [
        ("servicenow_get_table_records_by_table_name", {"table_name": "incident", "sysparm_query": "priority=1^ORDERBYnumber",
                                                        "sysparm_limit": 2}),
        lambda prior: ("servicenow_get_table_record_by_sys_id", {"table_name": "incident",
                                                                 "sys_id": prior[0]["result"][0]["sys_id"]}),
        ("servicenow_create_table_record", {"table_name": "incident", "confirm": True,
                                            "body": {"short_description": "Badge reader down", "caller_id": "bob"}}),
        lambda prior: ("servicenow_update_table_record", {"table_name": "incident", "confirm": True,
                                                          "sys_id": prior[0]["result"][0]["sys_id"], "body": {"state": "open"}}),
        ("servicenow_get_table_record_by_sys_id", {"table_name": "incident", "sys_id": "0000"}),
        ("servicenow_get_table_stats", {"table_name": "incident"}),
    ]


def _salesforce_steps() -> list[Step]:
    return [
        ("salesforce_query", {"q": "SELECT Id, Name FROM Account WHERE BillingCountry = 'MY' ORDER BY Name DESC LIMIT 3"}),
        ("salesforce_create_s_object", {"s_object": "Case", "confirm": True, "subject": "Login fails", "status": "New"}),
        lambda prior: ("salesforce_get_s_object", {"s_object": "Case", "id": prior[1]["id"]}),
        ("salesforce_get_s_object", {"s_object": "Account", "id": "001000000000000AAA"}),
        ("salesforce_query", {"q": "SELECT Id FROM Account WHERE"}),
    ]


def _slack_steps() -> list[Step]:
    return [
        ("slack_search_messages", {"token": "admin", "query": "deploy in:C01"}),
        ("slack_conversations_history", {"token": "admin", "channel": "C01", "limit": 2}),
        ("slack_conversations_list", {"token": "admin"}),
        ("slack_chat_post_message", {"token": "admin", "confirm": True, "channel": "C01", "text": "Deploy done"}),
        ("slack_conversations_info", {"token": "admin", "channel": "C404"}),
    ]


def _confluence_steps() -> list[Step]:
    return [
        ("confluence_get_pages", {"title": "Runbook 2"}),
        ("confluence_get_pages", {"limit": 3}),
        ("confluence_get_page_by_id", {"id": 1001}),
        ("confluence_create_page", {"confirm": True, "body": {"spaceId": "OPS", "status": "current", "title": "Escalation path",
                                                              "body": {"representation": "storage", "value": "Call the lead"}}}),
        ("confluence_update_page_title", {"id": 1002, "status": "current", "title": "Runbook two"}),
        # The manifest narrows the body union to its storage alternative: a
        # page PUT with a storage body is served, a wiki body is refused.
        ("confluence_update_page", {"id": 1003, "body": {"id": "1003", "status": "current", "title": "Runbook 3",
                                                         "body": {"representation": "storage", "value": "<p>Step three, revised</p>"},
                                                         "version": {"number": 2}}}),
        ("confluence_update_page", {"id": 1004, "body": {"id": "1004", "status": "current", "title": "Runbook 4",
                                                         "body": {"representation": "wiki", "value": "h1. Step four"},
                                                         "version": {"number": 2}}}),
        ("confluence_get_page_by_id", {"id": 1003}),
        ("confluence_get_page_by_id", {"id": 9999}),
    ]


def _drive_steps() -> list[Step]:
    return [
        ("drive_drive_files_list", {"q": "name contains 'Budget' and trashed = false", "page_size": 2}),
        ("drive_drive_files_get", {"file_id": "file1"}),
        ("drive_drive_files_get", {"file_id": "nope"}),
        ("drive_drive_files_delete", {"file_id": "file3", "confirm": True}),
    ]


def _outlook_steps() -> list[Step]:
    flt = "from/emailAddress/address eq 'ap@vendor.com'"
    return [
        ("outlook_me_list_messages_direct", {"filter": flt, "top": 1}),
        ("outlook_me_get_messages", {"message_id": "AAMkMsg2"}),
        ("outlook_me_list_mail_folders", {}),
        ("outlook_me_update_messages", {"message_id": "AAMkMsg1", "confirm": True,
                                        "body": {"@odata.type": "#microsoft.graph.message", "isRead": True}}),
        ("outlook_me_update_messages", {"message_id": "AAMkMsg1", "confirm": True, "body": {"isRead": True}}),
        ("outlook_me_get_messages", {"message_id": "AAMkNope"}),
    ]


def _onedrive_steps() -> list[Step]:
    return [
        ("onedrive_drives_drive_search", {"drive_id": "b!drive1", "q": "budget"}),
        ("onedrive_drives_items_list_children", {"drive_id": "b!drive1", "drive_item_id": "01FOLDER1"}),
        ("onedrive_drives_get_items", {"drive_id": "b!drive1", "drive_item_id": "01ITEM1"}),
        ("onedrive_drives_update_items", {"drive_id": "b!drive1", "drive_item_id": "01ITEM2", "confirm": True,
                                          "body": {"@odata.type": "#microsoft.graph.driveItem", "name": "Budget model v2.xlsx"}}),
        ("onedrive_drives_update_items", {"drive_id": "b!drive1", "drive_item_id": "01ITEM2", "confirm": True,
                                          "body": {"name": "Budget model v2.xlsx"}}),
        ("onedrive_drives_get_items", {"drive_id": "b!drive1", "drive_item_id": "01NOPE"}),
    ]


def _sharepoint_steps() -> list[Step]:
    site = "contoso.sharepoint.com,1,2"
    return [
        ("sharepoint_drives_drive_search", {"drive_id": "b!site1", "q": "budget"}),
        ("sharepoint_drives_get_items_drives", {"drive_id": "b!site1", "drive_item_id": "01ITEM1"}),
        ("sharepoint_sites_lists_list_items", {"site_id": site, "list_id": "L1", "filter": "fields/Status eq 'Open'"}),
        ("sharepoint_sites_get_pages", {"site_id": site, "base_site_page_id": "PAGE1"}),
        ("sharepoint_drives_get_items_drives", {"drive_id": "b!site1", "drive_item_id": "01NOPE"}),
    ]


def _teams_steps() -> list[Step]:
    return [
        ("teams_teams_team_list_team", {"filter": "displayName eq 'Finance'"}),
        ("teams_teams_team_get_team", {"team_id": "TEAM1"}),
        ("teams_teams_list_channels", {"team_id": "TEAM1"}),
        ("teams_teams_channels_list_messages_teams", {"team_id": "TEAM1", "channel_id": "19:chan2@thread.tacv2", "top": 1}),
        ("teams_teams_get_channels", {"team_id": "TEAM1", "channel_id": "19:nope@thread.tacv2"}),
    ]


SEQUENCES: dict[str, tuple[Callable[[], list[Any]], Callable[[], list[Step]]]] = {
    "confluence": (parity._confluence_records, _confluence_steps),
    "drive": (parity._drive_records, _drive_steps),
    "jira": (parity._jira_records, _jira_steps),
    "onedrive": (lambda: parity._drive_items("onedrive", "01"), _onedrive_steps),
    "outlook": (parity._outlook_records, _outlook_steps),
    "salesforce": (parity._salesforce_records, _salesforce_steps),
    "servicenow": (parity._servicenow_records, _servicenow_steps),
    "sharepoint": (parity._sharepoint_records, _sharepoint_steps),
    "slack": (parity._slack_records, _slack_steps),
    "teams": (parity._teams_records, _teams_steps),
}

_LINK = re.compile(r"^https?://")


_INVALID = "Input validation error"


def _outcome(result: tuple[str, Any]) -> Any:
    """A call's outcome for comparison: a refusal of the arguments by schema is one outcome, whatever wrote its text.

    Anvil's MCP server refuses arguments its zod schema does not admit before
    its runtime runs (a protocol error, zod's wording); in process the same
    published schema refuses them with Anvil's envelope (``jsonschema``'s).
    Which arguments are refused is compared; the wording is each validator's.
    """
    kind, body = result
    if kind == "protocol" and _INVALID in str(body):
        return "refused: input schema"
    if kind == "error" and str(((body or {}).get("error") or {}).get("message", "")).startswith(_INVALID):
        return "refused: input schema"
    return _normal(result)


def _normal(value: Any) -> Any:
    """A result with what legitimately differs between transports taken out.

    A trace id and the simulator's request id are per call; a continuation
    link is absolute on whichever server answered (the contract's own in
    process, the simulator's through Anvil), so a link keeps its query only.
    """
    if isinstance(value, dict):
        return {key: _normal(item) for key, item in value.items() if key not in {"trace_id", "request_id"}}
    if isinstance(value, list | tuple):
        return [_normal(item) for item in value]
    if isinstance(value, str) and _LINK.match(value) and "?" in value:
        return "link?" + urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(urllib.parse.urlsplit(value).query)))
    return value


def _credentials(bundle: Path) -> dict[str, str]:
    """Every credential variable the bundle's runtime reads, set to the simulator's principal."""
    text = (bundle / "deploy" / "credentials.required.yaml").read_text(encoding="utf-8")
    return {name: "admin" for name in sorted(set(re.findall(r"\bANVIL_PROD_[A-Z0-9_]+", text)))}


@contextmanager
def _anvil_mcp(connector: str, bundle: Path, records: list[Any], tmp_path: Path) -> Iterator[McpClient]:
    """Anvil's MCP server for *bundle*, its upstream the simulator over the Worldloom provider."""
    assert ANVIL is not None
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write_jsonl(corpus / "records.jsonl", records)
    provider = shlex.join([sys.executable, "-m", "worldloom.anvil_provider", "--corpus", str(corpus),
                           "--connector", connector])
    with parity._served(bundle, provider, tmp_path / "calls.jsonl") as url:
        env = {"PYTHONPATH": os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")]), "ANVIL_ENV": "dev",
               "ANVIL_BASE_URL": url, "ANVIL_CREDENTIALS": "env", "ANVIL_AUTH_PROFILE": "prod",
               **_credentials(bundle)}
        client = McpClient(bundle, env=env)
        try:
            client.open_all()
            yield client
        finally:
            client.close()


def _via_anvil(client: McpClient, tool: str, args: dict[str, Any]) -> tuple[str, Any]:
    reply = client.request("tools/call", {"name": tool, "arguments": args})
    if "error" in reply:
        return "protocol", reply["error"].get("message")
    result = reply["result"]
    text = "".join(part.get("text", "") for part in result.get("content") or () if part.get("type") == "text")
    try:
        # The text content is the response itself; `structuredContent` wraps a
        # response that is not an object as `{"result": ...}`.
        parsed = json.loads(text) if text else None
    except ValueError:
        return "protocol", text
    return ("error" if result.get("isError") else "ok"), parsed


@needs_anvil
@pytest.mark.parametrize("connector", CONNECTORS)
def test_a_call_sequence_answers_alike_in_process_and_through_anvil(connector: str, cache: Path, tmp_path: Path) -> None:
    make_records, make_steps = SEQUENCES[connector]
    records = make_records()
    bundle = _bundle(connector, cache)
    surface = shipped_surface(connector)
    backend = EmulatorBackend(ConnectorEmulator(load_connector_definition(connector), records, query_engine="native"))
    landing = parity.Landing()
    prior: list[Any] = []
    with _anvil_mcp(connector, bundle, records, tmp_path) as client:
        for index, step in enumerate(make_steps()):
            tool, args = step(prior) if callable(step) else step
            try:
                mine: tuple[str, Any] = ("ok", surface.invoke(tool, args, backend, request_id=f"r{index + 1}"))
            except ContractCallError as error:
                mine = ("error", error.envelope)
            theirs = _via_anvil(client, tool, args)
            if theirs[0] == "protocol" and "duplicate schema id" in str(theirs[1]).casefold():
                landing.expect(False, DRIVE_SCHEMA_IDS)
                prior.append(mine[1])
                continue
            assert _outcome(theirs) == _outcome(mine), f"{connector} step {index + 1}: {tool}({args})"
            prior.append(mine[1])
    landing.settle()


def test_the_sequences_cover_every_locked_connector() -> None:
    assert tuple(sorted(SEQUENCES)) == CONNECTORS
    for connector, (_, make_steps) in SEQUENCES.items():
        names = {tool.name for tool in shipped_surface(connector).tools}
        for step in make_steps():
            if not callable(step):
                assert step[0] in names, f"{connector}: {step[0]} is not on the surface"


def test_operations_listed_by_the_air_match_the_surface() -> None:
    # Guards the helper the lint test uses, so it cannot pass vacuously.
    assert operations_from_air({"operations": []}) == ()


def test_a_changed_mapping_changes_the_surface_pin() -> None:
    """Calls dispatch through the mapping, so the pin a proof records must move with it."""
    import dataclasses

    surface = shipped_surface("jira")
    operation, entry = next((key, value) for key, value in surface.mapping.operations.items() if value.tool)
    moved = dataclasses.replace(surface.mapping, operations={
        **surface.mapping.operations, operation: dataclasses.replace(entry, tool=f"{entry.tool}_elsewhere")})
    assert dataclasses.replace(surface, mapping=moved).digest != surface.digest
    assert dataclasses.replace(surface, mapping=surface.mapping).digest == surface.digest
