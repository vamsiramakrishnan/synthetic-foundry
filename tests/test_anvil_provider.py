"""Serving Worldloom records through Anvil: the mapping, the provider protocol, parity, and the runner mode.

The tests that need Anvil itself (``anvil simulate serve``) compile the
fixture contract, the Jira Cloud v3 spec trimmed to the 26 operations of
Anvil's own Jira backtest, and are skipped when neither ``$WORLDLOOM_ANVIL``,
an ``anvil`` on PATH, nor a sibling ``anvil`` checkout with a built CLI and
``node`` is available. Everything else runs without Node.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_data import ConnectorRecord
from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator, ConnectorError
from worldloom.connectors.anvil import (
    EmulatorBackend,
    MappingError,
    lint_mapping,
    load_mapping,
    operations_from_table,
    parse_mapping,
)
from worldloom.connectors.anvil_provider import Provider, load_corpus_records, serve
from worldloom.corpus import write_jsonl
from worldloom.evalrun import (
    CallableAgent,
    ScriptedAgent,
    case_from_row,
    run_case,
    service_for,
)
from worldloom.evalrun.agents import AgentResponse
from worldloom.evalrun.anvil import AnvilServing, find_anvil, merge_traces
from worldloom.evalrun.stages import _call_clauses

# These tests script agents in the connector definitions' own tool names
# (`jira.get_issue`), so they serve those tools; the contract surface is the default.
pytestmark = pytest.mark.usefixtures("native_surface")

FIXTURES = Path(__file__).parent / "fixtures" / "anvil"
SRC = Path(__file__).resolve().parent.parent / "src"
runner = CliRunner()

SEV1 = 'project = OPS AND cf[10231] = "Sev-1"'


# -- a small Jira corpus -------------------------------------------------------------------


def _records() -> list[ConnectorRecord]:
    issues = [("task", "open", "Sev-1"), ("bug", "todo", "Sev-2"), ("story", "review", "Sev-1"),
              ("task", "done", "Sev-3"), ("bug", "open", "Sev-1")]
    return [
        ConnectorRecord(id=f"rec-{n}", connector="jira", entity=entity, external_id=f"OPS-{n}",
                        title=f"Issue {n} vendor onboarding",
                        fields={"status": status, "project": "OPS", "summary": f"Issue {n} vendor onboarding",
                                "severity": severity, "assignee": "alice" if n % 2 else "bob", "labels": ["ops"],
                                "created_at": f"2026-09-0{n}T10:00:00+08:00"})
        for n, (entity, status, severity) in enumerate(issues, start=1)
    ]


def _corpus(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    write_jsonl(directory / "records.jsonl", _records())
    return directory


def _operations() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "jira.operations.json").read_text(encoding="utf-8"))


# -- the mapping ---------------------------------------------------------------------------


def test_the_shipped_jira_mapping_covers_every_operation_of_the_contract() -> None:
    mapping = load_mapping("jira")
    errors, advisories = lint_mapping(mapping, operations_from_table(_operations()), load_connector_definition("jira"))
    assert errors == () and advisories == ()
    modelled = sorted(entry.operation_id for entry in mapping.operations.values() if entry.unmodelled is None)
    assert "jira.jql.search" in modelled and "jira.transitions.create" in modelled
    assert len(mapping.operations) == 26


def test_an_operation_neither_mapped_nor_marked_unmodelled_is_a_lint_error() -> None:
    mapping = load_mapping("jira")
    table = [*_operations(), {"operationId": "jira.dashboard.list", "method": "GET", "pathTemplate": "/rest/api/2/dashboard",
                              "kind": "list"}]
    errors, _ = lint_mapping(mapping, operations_from_table(table))
    assert errors and errors[0].startswith("unmapped: jira.dashboard.list")


def test_a_route_matches_an_operation_compiled_under_another_service_id() -> None:
    mapping = load_mapping("jira")
    renamed = [{**item, "operationId": "atlassian." + item["operationId"]} for item in _operations()]
    errors, advisories = lint_mapping(mapping, operations_from_table(renamed))
    assert errors == () and advisories == ()


def test_a_mapping_is_refused_when_an_entry_says_neither_what_it_runs_nor_why_not() -> None:
    document = {"schema": "worldloom.anvil-mapping/v1", "connector": "jira",
                "operations": {"jira.issue.delete": {"route": "DELETE /rest/api/2/issue/{issueIdOrKey}"}}}
    with pytest.raises(MappingError, match="unmodelled"):
        parse_mapping(document)
    bad_tool = {"schema": "worldloom.anvil-mapping/v1", "connector": "jira",
                "operations": {"jira.issue.get": {"tool": "fetch_issue", "args": {"id": "path.issueIdOrKey"}}}}
    errors, _ = lint_mapping(parse_mapping(bad_tool), operations_from_table(()), load_connector_definition("jira"))
    assert errors == ("unknown_tool: jira.issue.get maps to jira.fetch_issue, which the definition does not declare",)


# -- the protocol, in process --------------------------------------------------------------


def _provider(tmp_path: Path, **options: Any) -> Provider:
    emulator = ConnectorEmulator(load_connector_definition("jira"), _records(), query_engine="native")
    return Provider(load_mapping("jira"), EmulatorBackend(emulator), **options)


def _rpc(provider: Provider, *messages: dict[str, Any]) -> list[dict[str, Any]]:
    out = io.StringIO()
    serve(provider, [json.dumps(message) + "\n" for message in messages], out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def _initialize(version: int = 1, operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": version, "serviceId": "jira", "operations": operations or _operations()}}


def _invoke(ident: int, operation: str, *, path: dict[str, Any] | None = None, body: Any = None,
            page: dict[str, Any] | None = None) -> dict[str, Any]:
    table = {item["operationId"]: item for item in _operations()}[operation]
    return {"jsonrpc": "2.0", "id": ident, "method": "invoke", "params": {
        "requestId": f"r{ident}", "operationId": operation, "toolName": table["toolName"], "kind": table["kind"],
        "method": table["method"], "pathTemplate": table["pathTemplate"],
        "params": {"path": path or {}, "query": {}, "header": {}}, "body": body, "page": page}}


def test_the_handshake_refuses_another_protocol_version_and_an_uncovered_contract(tmp_path: Path) -> None:
    replies = _rpc(_provider(tmp_path), _initialize(version=2))
    assert replies[0]["error"]["code"] == -32602 and "protocolVersion 2" in replies[0]["error"]["message"]
    extra = [*_operations(), {"operationId": "jira.dashboard.list", "method": "GET", "pathTemplate": "/x", "kind": "list"}]
    replies = _rpc(_provider(tmp_path), _initialize(operations=extra))
    assert "unmapped: jira.dashboard.list" in replies[0]["error"]["message"]


def test_the_provider_answers_reads_searches_pages_writes_and_domain_errors(tmp_path: Path) -> None:
    snapshot = tmp_path / "after.json"
    replies = _rpc(
        _provider(tmp_path, snapshot_out=snapshot),
        _initialize(),
        _invoke(2, "jira.jql.search", body={"jql": SEV1, "maxResults": 2}),
        _invoke(3, "jira.jql.search", body={"jql": SEV1, "maxResults": 2, "nextPageToken": "2"}),
        _invoke(4, "jira.issue.get", path={"issueIdOrKey": "OPS-404"}),
        _invoke(5, "jira.jql.search", body={"jql": "project = OPS AND"}),
        _invoke(6, "jira.transitions.list", path={"issueIdOrKey": "OPS-1"}, page={"cursor": None, "size": 1}),
        _invoke(7, "jira.transitions.create", path={"issueIdOrKey": "OPS-1"}, body={"transition": {"id": "31"}}),
        _invoke(8, "jira.issue.delete", path={"issueIdOrKey": "OPS-1"}),
        {"jsonrpc": "2.0", "id": 9, "method": "shutdown", "params": {}},
    )
    assert [reply["id"] for reply in replies] == list(range(1, 10))
    assert replies[0]["result"] == {"protocolVersion": 1}
    first, second = replies[1]["result"]["result"], replies[2]["result"]["result"]
    assert first["isLast"] is False and first["nextPageToken"] == "2" and len(first["issues"]) == 2
    assert second["isLast"] is True and "nextPageToken" not in second
    keys = sorted(issue["key"] for issue in (*first["issues"], *second["issues"]))
    assert keys == ["OPS-1", "OPS-3", "OPS-5"]
    missing = replies[3]["result"]
    assert missing["ok"] is False and missing["error"]["code"] == "not_found" and missing["error"]["status"] == 404
    assert missing["error"]["body"] == {"errorMessages": ["Issue does not exist or you do not have permission to see it."],
                                        "errors": {}}
    malformed = replies[4]["result"]["error"]
    assert malformed["code"] == "validation_error" and malformed["body"]["errorMessages"][0].startswith("Error in the JQL Query")
    paged = replies[5]["result"]
    assert paged["ok"] and len(paged["items"]) == 1 and paged["nextCursor"] == "1"
    assert replies[6]["result"] == {"ok": True, "result": None}
    assert replies[7]["result"]["error"]["code"] == "unsupported_operation"
    assert replies[8]["result"] is None
    after = json.loads(snapshot.read_text(encoding="utf-8"))
    assert after["rec-1"]["status"] == "review"


def test_the_module_speaks_only_protocol_on_stdout(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    lines = "".join(json.dumps(message) + "\n" for message in (
        _initialize(), _invoke(2, "jira.issue.get", path={"issueIdOrKey": "OPS-2"}),
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}))
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")])}
    done = subprocess.run([sys.executable, "-m", "worldloom.anvil_provider", "--corpus", str(corpus), "--connector", "jira"],
                          input=lines, capture_output=True, text=True, env=env, timeout=120, check=True)
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert replies[1]["result"]["result"]["key"] == "OPS-2"


# -- the stages read queries through the shared evaluator ----------------------------------


def test_stage_clauses_come_from_the_shared_evaluator_and_agree_with_the_old_parser() -> None:
    definitions = {"jira": load_connector_definition("jira")}
    clauses, entity = _call_clauses(definitions, "jira", {"query": 'issuetype = bug AND status = open AND cf[10231] = "Sev-1"'},
                                    tool="search_issues")
    assert entity == "bug"
    assert clauses == [("status", "eq", "open"), ("severity", "eq", "Sev-1")]
    windowed, _ = _call_clauses(definitions, "jira", {"query": "project = OPS AND created >= -7d"}, tool="search_issues")
    # The historical parser left `-7d` a string; the evaluator's bound is the
    # instant seven days before the connector's clock, as a RelativeTime.
    assert windowed is not None and windowed[0] == ("project", "eq", "OPS")
    field, op, bound = windowed[1]
    assert (field, op, bound.days, bound.seconds) == ("age_days", "gte", -7, 0)
    # A disjunction the conjunctive parser could not read still names its fields.
    either, _ = _call_clauses(definitions, "jira", {"query": "status = open OR assignee is EMPTY"}, tool="search_issues")
    assert either is not None and {field for field, _, _ in either} == {"status", "assignee"}
    # A query neither parser reads is unknown, not unfiltered.
    unknown, _ = _call_clauses(definitions, "jira", {"query": "status ~~ open"}, tool="search_issues")
    assert unknown is None
    # A language the evaluator does not parse keeps the historical path.
    cypher = {"jira": definitions["jira"].model_copy(update={"query_language": "cypher"})}
    kept, _ = _call_clauses(cypher, "jira", {"query": "status = 'open'"}, tool="search_issues")
    assert kept == [("status", "eq", "open")]


def test_traces_merge_in_the_order_the_providers_answered() -> None:
    jira = [{"seq": 1, "requestId": "r1", "normalized": {}}, {"seq": 2, "requestId": "r2", "normalized": None},
            {"seq": 3, "requestId": "r3", "normalized": {}}]
    wiki = [{"seq": 1, "requestId": "r1", "normalized": {}}]
    merged = merge_traces({"jira": jira, "confluence": wiki}, [("jira", "r1"), ("confluence", "r1"), ("jira", "r3")])
    assert [(name, entry["seq"]) for name, entry in merged] == [("jira", 1), ("confluence", 1), ("jira", 2), ("jira", 3)]


def test_the_cli_refuses_anvil_flags_without_anvil_and_an_unknown_serving(tmp_path: Path) -> None:
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path), "-o", str(tmp_path / "out"), "--contract", "x"])
    assert result.exit_code == 2 and "add --connectors" in result.output, result.output
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path), "-o", str(tmp_path / "out"), "--connectors", "http"])
    assert result.exit_code == 2 and "use emulator or anvil" in result.output, result.output


# -- through Anvil -------------------------------------------------------------------------


def _anvil() -> tuple[str, ...] | None:
    found = find_anvil()
    if found:
        return found
    node = shutil.which("node")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "anvil" / "packages" / "cli" / "dist" / "bin-anvil.js"
        if node and candidate.is_file():
            return (node, str(candidate))
    return None


ANVIL = _anvil()
needs_anvil = pytest.mark.skipif(ANVIL is None, reason="needs the Anvil CLI (set WORLDLOOM_ANVIL) and node")


@pytest.fixture(scope="module")
def contract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    assert ANVIL is not None
    root = tmp_path_factory.mktemp("anvil-contract")
    spec = root / "jira.spec.json"
    spec.write_bytes(gzip.decompress((FIXTURES / "jira.spec.json.gz").read_bytes()))
    done = subprocess.run([*ANVIL, "compile", str(spec), "--root", str(root), "--manifest", str(FIXTURES / "jira.anvil.yaml"),
                           "--service", "jira", "--out", str(root / "jira")], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    air = json.loads((root / "jira" / "air.json").read_text(encoding="utf-8"))
    assert sum(1 for item in air["operations"] if item["state"] == "approved") == 26
    return root / "jira"


@contextmanager
def _served(contract: Path, provider: str, trace: Path) -> Iterator[str]:
    assert ANVIL is not None
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")])}
    process = subprocess.Popen([*ANVIL, "simulate", "serve", "--contract", str(contract), "--provider-cmd", provider,
                                "--port", "0", "--trace", str(trace)], stdout=subprocess.PIPE, text=True, env=env)
    try:
        assert process.stdout is not None
        url = process.stdout.readline().strip()
        assert url.startswith("http"), url
        yield url
    finally:
        process.terminate()
        process.wait(timeout=30)
        if process.stdout is not None:
            process.stdout.close()


def _http(url: str, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(url + path, method=method,
                                     data=None if body is None else json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer admin",
                                              **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "null")


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "created": {fid: after[fid] for fid in sorted(set(after) - set(before))},
        "deleted": sorted(set(before) - set(after)),
        "updated": {fid: {key: after[fid].get(key) for key in sorted(set(after[fid]) | set(before[fid]))
                          if after[fid].get(key) != before[fid].get(key)}
                    for fid in sorted(set(before) & set(after)) if after[fid] != before[fid]},
    }


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


#: Anvil pages Jira's `POST /search/jql` by its body token now, and writes the
#: page envelope itself: the issues and `nextPageToken`, not yet `isLast`.
JIRA_IS_LAST = "Anvil body-token paging: the page envelope does not carry Jira's isLast yet"


class Landing:
    """Assertions on a capability still landing in Anvil: the test xfails naming it, after every other assertion held."""

    def __init__(self) -> None:
        self.pending: list[str] = []

    def expect(self, holds: bool, capability: str) -> None:
        if not holds and capability not in self.pending:
            self.pending.append(capability)

    def settle(self) -> None:
        if self.pending:
            pytest.xfail("; ".join(self.pending))


@needs_anvil
def test_parity_the_emulator_and_anvil_return_the_same_records_and_leave_the_same_state(contract: Path,
                                                                                       tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    emulator = ConnectorEmulator(load_connector_definition("jira"), load_corpus_records(corpus), query_engine="native")
    before = _json({fid: dict(record) for fid, record in emulator.records.items()})
    landing = Landing()

    def local(tool: str, **args: Any) -> tuple[int, Any]:
        try:
            return 200, emulator.call(tool, **args)
        except ConnectorError as error:
            return error.code, {"errorMessages": [error.message], "errors": {}}

    snapshot = tmp_path / "after.json"
    provider = shlex.join([sys.executable, "-m", "worldloom.anvil_provider", "--corpus", str(corpus), "--connector", "jira",
                           "--snapshot-out", str(snapshot)])
    with _served(contract, provider, tmp_path / "calls.jsonl") as url:
        # Search with JQL, two pages.
        status, page = _http(url, "POST", "/rest/api/2/search/jql", {"jql": SEV1, "maxResults": 2})
        _, mine = local("search_issues", query=SEV1, max_results=2)
        assert status == 200 and page["issues"] == _json(mine["items"]) and "nextPageToken" in page
        landing.expect(page.get("isLast") == mine["is_last"], JIRA_IS_LAST)
        status, page = _http(url, "POST", "/rest/api/2/search/jql",
                             {"jql": SEV1, "maxResults": 2, "nextPageToken": page["nextPageToken"]})
        _, mine = local("search_issues", query=SEV1, max_results=2, start_at=2)
        assert status == 200 and page["issues"] == _json(mine["items"]) and "nextPageToken" not in page
        landing.expect(page.get("isLast") is True, JIRA_IS_LAST)
        # Get, whole and projected.
        assert _http(url, "GET", "/rest/api/2/issue/OPS-1") == (200, _json(local("get_issue", id="OPS-1")[1]))
        assert _http(url, "GET", "/rest/api/2/issue/OPS-3?fields=summary,status") == \
            (200, _json(local("get_issue", id="OPS-3", fields=["summary", "status"])[1]))
        # Create: Jira answers with the new issue's id, key and self.
        status, created = _http(url, "POST", "/rest/api/2/issue", {"fields": {
            "summary": "Vendor follow-up", "project": {"key": "OPS"}, "issuetype": {"name": "Task"},
            "customfield_10231": {"value": "Sev-2"}}})
        _, mine = local("create_issue", entity="task", name="Vendor follow-up",
                        fields={"project": "OPS", "severity": "Sev-2", "summary": "Vendor follow-up"})
        assert status == 201 and created == {key: mine[key] for key in ("id", "key", "self")}
        # Update, then transition (by the vendor's transition id), then comment.
        # Jira answers an edit and a transition with 204; Anvil serves an empty result as 204 since it learned that.
        assert _http(url, "PUT", "/rest/api/2/issue/OPS-1", {"fields": {"summary": "Vendor onboarding, renamed"}})[0] in (200, 204)
        local("update_issue", id="OPS-1", fields={"summary": "Vendor onboarding, renamed"})
        assert _http(url, "POST", f"/rest/api/2/issue/{created['key']}/transitions", {"transition": {"id": "21"}})[0] in (201, 204)
        local("transition_issue", id=created["key"], state="open")
        status, comment = _http(url, "POST", "/rest/api/2/issue/OPS-1/comment", {"body": "Checked with the vendor"})
        local("add_comment", id="OPS-1", body="Checked with the vendor")
        assert status == 201 and comment["body"] == "Checked with the vendor"
        # Domain errors carry the vendor's status and text on both sides.
        for method, path, body, tool, args in (
            ("GET", "/rest/api/2/issue/OPS-404", None, "get_issue", {"id": "OPS-404"}),
            ("POST", "/rest/api/2/issue/OPS-4/transitions", {"transition": {"id": "21"}}, "transition_issue",
             {"id": "OPS-4", "state": "open"}),
            ("POST", "/rest/api/2/search/jql", {"jql": "project = OPS AND"}, "search_issues", {"query": "project = OPS AND"}),
        ):
            assert _http(url, method, path, body) == local(tool, **args)
        # The final read agrees too.
        assert _http(url, "GET", "/rest/api/2/issue/OPS-1") == (200, _json(local("get_issue", id="OPS-1")[1]))
    after_anvil = json.loads(snapshot.read_text(encoding="utf-8"))
    after_local = _json({fid: dict(record) for fid, record in emulator.records.items()})
    assert after_anvil == after_local
    diff = _diff(before, after_anvil)
    assert diff == _diff(before, after_local)
    assert sorted(diff["created"]) == ["new:ji:task:1"] and sorted(diff["updated"]) == ["rec-1"] and diff["deleted"] == []
    trace = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(trace) == 12 and all(entry["normalized"] is not None for entry in trace)
    landing.settle()


def _triage_row() -> dict[str, Any]:
    nodes = [
        {"id": "find", "server": "jira", "tool": "search_issues", "fixture": "rec-1", "entity": "task", "op": "search"},
        {"id": "move", "server": "jira", "tool": "transition_issue", "fixture": "rec-1", "entity": "task", "op": "transition"},
    ]
    return {"id": "jira-triage", "query": "Find the open Sev-1 task in OPS and move it to review.",
            "expected_dag": {"nodes": nodes, "edges": [["find", "move"]]},
            "assertions": [{"type": "tool_called", "node": node["id"]} for node in nodes]
            + [{"type": "order", "before": "find", "after": "move"},
               {"type": "state_equals", "node": "move", "fixture": "rec-1", "field": "status", "state": "review"}]}


TRIAGE_JQL = 'project = OPS AND status = open AND cf[10231] = "Sev-1" ORDER BY created ASC'


def _over_http(task: Any, tools: Any) -> AgentResponse:
    url = tools.base_urls["jira"]
    _, found = _http(url, "POST", "/rest/api/2/search/jql", {"jql": TRIAGE_JQL})
    key = found["issues"][0]["key"]
    _http(url, "POST", f"/rest/api/2/issue/{key}/transitions", {"transition": {"id": "31"}})
    return AgentResponse(answer=f"{key} is in review.")


@needs_anvil
def test_a_case_served_through_anvil_grades_exactly_as_the_same_calls_in_process(contract: Path, tmp_path: Path) -> None:
    case = case_from_row(_triage_row())
    in_process = ScriptedAgent([("jira.search_issues", {"query": TRIAGE_JQL}),
                                ("jira.transition_issue", {"id": "OPS-1", "state": "review"})],
                               answer="OPS-1 is in review.")
    local = run_case(service_for((case,), _records(), query_engine="native"), case, in_process)
    serving = AnvilServing({"jira": contract}, command=ANVIL, workdir=tmp_path / "anvil")
    served = run_case(service_for((case,), _records(), query_engine="native"), case,
                      CallableAgent(_over_http, name="http"), anvil=serving)
    assert served.graded and local.graded, served.error
    assert served.score is not None and local.score is not None
    assert served.score.passed and local.score.passed
    assert served.spans == local.spans
    assert served.score.model_dump() == local.score.model_dump()
    assert served.refusals == () and served.notes == ()
    assert (tmp_path / "anvil" / "jira-triage" / "jira.calls.jsonl").is_file()


@needs_anvil
def test_lineage_through_an_anvil_served_run_links_what_the_agent_sent_to_what_it_saw(contract: Path,
                                                                                      tmp_path: Path) -> None:
    # The agent read the key off the vendor's search response and put it in
    # the transition's URL path; lineage reads those, not the replay's arguments.
    case = case_from_row(_triage_row())
    serving = AnvilServing({"jira": contract}, command=ANVIL, workdir=tmp_path / "anvil")
    served = run_case(service_for((case,), _records(), query_engine="native"), case,
                      CallableAgent(_over_http, name="http"), anvil=serving)
    assert served.graded and served.score is not None, served.error
    assert [span["consumed_from"] for span in served.spans] == [[], ["s1"]]
    dag = served.score.plan.nodes.dag
    assert dag is not None and dag.edge_recall == 1.0 and dag.missing == () and dag.findings == ()
    assert "OPS-1" in dag.executed.edges[0].values


@needs_anvil
def test_an_sdk_program_runs_against_anvil_and_is_graded_with_lineage(contract: Path, tmp_path: Path) -> None:
    from worldloom.evalrun.program import ProgramAgent

    program = (
        "import json, os, urllib.request\n"
        "base, token = os.environ['ANVIL_BASE_URL'], os.environ['ANVIL_TOKEN']\n"
        "def http(method, path, body):\n"
        "    request = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode(),\n"
        "                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})\n"
        "    with urllib.request.urlopen(request, timeout=60) as response:\n"
        "        return json.loads(response.read().decode() or 'null')\n"
        f"found = http('POST', '/rest/api/2/search/jql', {{'jql': {TRIAGE_JQL!r}}})\n"
        "key = found['issues'][0]['key']\n"
        "http('POST', '/rest/api/2/issue/' + key + '/transitions', {'transition': {'id': '31'}})\n"
        "print(json.dumps({'answer': key + ' is in review.'}))\n"
    )
    writer = tmp_path / "writer.py"
    writer.write_text("import json, sys\n"
                      "document = json.load(sys.stdin)\n"
                      "assert document['anvil']['base_url_env'] == 'ANVIL_BASE_URL'\n"
                      f"print(json.dumps({{'program': {program!r}}}))\n", encoding="utf-8")
    case = case_from_row(_triage_row())
    serving = AnvilServing({"jira": contract}, command=ANVIL, workdir=tmp_path / "anvil")
    result = run_case(service_for((case,), _records(), query_engine="native"), case,
                      ProgramAgent(f"{sys.executable} {writer}", program_timeout=120), anvil=serving)
    assert result.graded and result.score is not None, result.error
    assert result.score.passed and result.answer == "OPS-1 is in review."
    assert result.program is not None and result.program["exit_code"] == 0
    assert [span["consumed_from"] for span in result.spans] == [[], ["s1"]]
    assert result.score.plan.nodes.dag.edge_recall == 1.0


@needs_anvil
def test_calls_anvil_answers_itself_and_in_process_calls_are_refusals_on_the_ledger(contract: Path,
                                                                                     tmp_path: Path) -> None:
    from worldloom.connectors.serving import ServingError

    def agent(task: Any, tools: Any) -> AgentResponse:
        with pytest.raises(ServingError, match="anvil_mode"):
            tools.call("jira.get_issue", id="OPS-1")
        throttled, _ = _http(tools.base_urls["jira"], "GET", "/rest/api/2/issue/OPS-1", headers={"X-Anvil-Fault": "throttle"})
        assert throttled == 429
        unmodelled, _ = _http(tools.base_urls["jira"], "DELETE", "/rest/api/2/issue/OPS-1")
        assert unmodelled >= 400
        return _over_http(task, tools)

    case = case_from_row(_triage_row())
    serving = AnvilServing({"jira": contract}, command=ANVIL, workdir=tmp_path / "anvil")
    served = run_case(service_for((case,), _records(), query_engine="native"), case, CallableAgent(agent, name="probe"),
                      anvil=serving)
    assert served.graded, served.error
    assert [span["tool"] for span in served.spans] == ["jira.search_issues", "jira.transition_issue"]
    assert [(item["tool"], item["error"].split(":")[0]) for item in served.refusals] == [
        ("jira.get_issue", "anvil_mode"), ("jira.get_issue", "anvil_rate_limited"),
        ("jira.jira_delete_issue", "anvil_unsupported_operation")]


@needs_anvil
def test_the_cli_serves_an_exec_agent_through_anvil_with_the_url_in_its_environment(contract: Path, tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    write_jsonl(cases / "evalrun-cases.jsonl", [case_from_row(_triage_row())])
    write_jsonl(cases / "records.jsonl", _records())
    child = tmp_path / "child.py"
    child.write_text(
        "import json, os, sys, urllib.request\n"
        "turn = json.load(sys.stdin)\n"
        "base, token = os.environ['ANVIL_BASE_URL'], os.environ['ANVIL_TOKEN']\n"
        "assert turn['anvil']['base_urls']['jira'] == base == os.environ['ANVIL_JIRA_BASE_URL']\n"
        "def call(method, path, body):\n"
        "    request = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode(),\n"
        "        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})\n"
        "    with urllib.request.urlopen(request) as response:\n"
        "        return json.loads(response.read() or b'null')\n"
        f"found = call('POST', '/rest/api/2/search/jql', {{'jql': {TRIAGE_JQL!r}}})\n"
        "key = found['issues'][0]['key']\n"
        "call('POST', '/rest/api/2/issue/' + key + '/transitions', {'transition': {'id': '31'}})\n"
        "print(json.dumps({'answer': key + ' is in review.'}))\n",
        encoding="utf-8",
    )
    out = tmp_path / "run"
    anvil_cmd = shlex.join(ANVIL or ())
    result = runner.invoke(app, ["evalrun", "run", str(cases), "-o", str(out), "--exec", f"{sys.executable} {child}",
                                 "--connectors", "anvil", "--contract", str(contract), "--anvil-cmd", anvil_cmd, "--json"])
    assert result.exit_code == 0, result.output
    line = json.loads((out / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["status"] == "graded", line.get("error")
    assert line["score"]["passed"] is True
    assert [span["tool"] for span in line["spans"]] == ["jira.search_issues", "jira.transition_issue"]
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["agent_identity"]["serving"]["connectors"] == "anvil"
