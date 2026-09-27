"""Parity through the real vendor contracts: the same calls in process and through Anvil agree.

For each connector the contract pack locks (``worldloom contracts``), the test
compiles the committed trim of its contract (``tests/fixtures/anvil/contracts``,
made from the locked source with the same profile) through
``worldloom.connectors.contracts.build``, serves it with ``anvil simulate
serve`` and the Worldloom provider over a small corpus, and runs one call
sequence twice: over HTTP against the vendor's own paths, and directly
against an in-process emulator over the same records. Records, errors and
the state diff must be identical.

A paging behaviour still landing in Anvil (an envelope field it does not
write yet) is not a silent pass: the assertion is recorded against the named
capability and the test xfails naming it, after every other assertion held.
Skipped only when node and the Anvil CLI are unavailable.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from worldloom.connector_data import ConnectorRecord
from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator, ConnectorError
from worldloom.connectors.anvil import load_mapping
from worldloom.connectors.contracts import build, load_lock
from worldloom.corpus import write_jsonl
from worldloom.evalrun.anvil import find_anvil

FIXTURES = Path(__file__).parent / "fixtures" / "anvil" / "contracts"
SRC = Path(__file__).resolve().parent.parent / "src"


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


# -- serving -------------------------------------------------------------------------------


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


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "created": {fid: after[fid] for fid in sorted(set(after) - set(before))},
        "deleted": sorted(set(before) - set(after)),
        "updated": {fid: {key: after[fid].get(key) for key in sorted(set(after[fid]) | set(before[fid]))
                          if after[fid].get(key) != before[fid].get(key)}
                    for fid in sorted(set(before) & set(after)) if after[fid] != before[fid]},
    }


class Session:
    """One connector served two ways: ``http`` through Anvil, ``local`` against an emulator over the same records."""

    def __init__(self, connector: str, url: str, records: list[ConnectorRecord]) -> None:
        self.connector = connector
        self.url = url
        self.mapping = load_mapping(connector)
        self.emulator = ConnectorEmulator(load_connector_definition(connector), records, query_engine="native")
        self.before = _json({fid: dict(record) for fid, record in self.emulator.records.items()})
        self.landing = Landing()

    def http(self, method: str, path: str, body: Any = None, *, query: dict[str, Any] | None = None,
             form: bool = False, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        target = self.url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        if body is None:
            data = None
            content = "application/json"
        elif form:
            data = urllib.parse.urlencode(body).encode("utf-8")
            content = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode("utf-8")
            content = "application/json"
        request = urllib.request.Request(target, method=method, data=data,
                                         headers={"Content-Type": content, "Authorization": "Bearer admin", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8") or "null")

    def local(self, tool: str, **args: Any) -> tuple[int, Any]:
        """The in-process call, its error as the vendor's body the mapping writes."""

        from worldloom.connectors.anvil import _fill
        from worldloom.connectors.query import QueryError

        try:
            return 200, _json(self.emulator.call(tool, **args))
        except ConnectorError as error:
            cause = error.__cause__
            if isinstance(cause, QueryError) and cause.body is not None:
                return error.code, _json(cause.body)
            body = _fill(self.mapping.error_body, error.message) if self.mapping.error_body is not None else None
            return error.code, _json(body)

    def state(self) -> dict[str, Any]:
        return _json({fid: dict(record) for fid, record in self.emulator.records.items()})


@contextmanager
def _served(bundle: Path, provider: str, trace: Path) -> Iterator[str]:
    assert ANVIL is not None
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")])}
    process = subprocess.Popen([*ANVIL, "simulate", "serve", "--contract", str(bundle), "--provider-cmd", provider,
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


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("contracts")


def _bundle(connector: str, cache: Path) -> Path:
    assert ANVIL is not None
    built = build(connector, cache=cache, anvil=ANVIL, spec=FIXTURES / f"{connector}.spec.json.gz")
    assert built.receipt["mapping"]["advisories"] == [], built.receipt["mapping"]["advisories"]
    assert len(built.receipt["exposed"]) == load_lock().contract(connector).profiled_operations
    return built.bundle


def _run(connector: str, records: list[ConnectorRecord], cache: Path, tmp_path: Path,
         scenario: Callable[[Session], None]) -> Session:
    bundle = _bundle(connector, cache)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write_jsonl(corpus / "records.jsonl", records)
    snapshot = tmp_path / "after.json"
    provider = shlex.join([sys.executable, "-m", "worldloom.anvil_provider", "--corpus", str(corpus),
                           "--connector", connector, "--snapshot-out", str(snapshot)])
    with _served(bundle, provider, tmp_path / "calls.jsonl") as url:
        session = Session(connector, url, records)
        scenario(session)
    after = json.loads(snapshot.read_text(encoding="utf-8"))
    assert after == session.state()
    assert _diff(session.before, after) == _diff(session.before, session.state())
    return session


# -- ServiceNow (authored contract) --------------------------------------------------------


def _servicenow_records() -> list[ConnectorRecord]:
    rows = [("new", "1", "Service Desk"), ("open", "2", "Network"), ("new", "1", "Network"), ("hold", "3", "Service Desk"),
            ("new", "1", "Service Desk")]
    return [ConnectorRecord(id=f"sn-{n}", connector="servicenow", entity="incident", external_id=f"INC000100{n}",
                            title=f"Printer {n} offline", fields={"state": state, "priority": priority,
                                                                  "assignment_group": group, "caller_id": "alice"})
            for n, (state, priority, group) in enumerate(rows, start=1)]


def _servicenow(s: Session) -> None:
    table = "/api/now/table/incident"
    query = "priority=1^ORDERBYnumber"
    # A list, two records at a time, then the next offset.
    status, page = s.http("GET", table, query={"sysparm_query": query, "sysparm_limit": 2})
    mine = s.local("search_records", entity="incident", query=query, max_results=2)[1]
    assert (status, page) == (200, {"result": mine["items"]})
    status, page = s.http("GET", table, query={"sysparm_query": query, "sysparm_limit": 2, "sysparm_offset": 2})
    mine = s.local("search_records", entity="incident", query=query, max_results=2, start_at=2)[1]
    assert (status, page) == (200, {"result": mine["items"]}) and len(mine["items"]) == 1
    # One record by sys_id, whole and projected.
    sys_id = page["result"][0]["sys_id"]
    assert s.http("GET", f"{table}/{sys_id}") == (200, {"result": s.local("get_record", id=sys_id)[1]})
    status, body = s.http("GET", f"{table}/{sys_id}", query={"sysparm_fields": "number,state"})
    assert (status, body) == (200, {"result": s.local("get_record", id=sys_id, fields=["number", "state"])[1]})
    # Create, then update by PATCH and by PUT.
    fields = {"short_description": "Badge reader down", "caller_id": "bob", "priority": "2"}
    status, created = s.http("POST", table, fields)
    mine = s.local("create_record", entity="incident", name="Badge reader down", fields=fields)[1]
    assert (status, created) == (201, {"result": mine})
    status, body = s.http("PATCH", f"{table}/{sys_id}", {"state": "open"})
    assert (status, body) == (200, {"result": s.local("update_record", id=sys_id, fields={"state": "open"})[1]})
    new_id = created["result"]["sys_id"]
    status, body = s.http("PUT", f"{table}/{new_id}", {"priority": "1"})
    assert (status, body) == (200, {"result": s.local("update_record", id=new_id, fields={"priority": "1"})[1]})
    # ServiceNow drops a condition it cannot read and runs the rest; so do both sides.
    lenient = "priority=1^no_such_field=x"
    status, body = s.http("GET", table, query={"sysparm_query": lenient})
    mine = s.local("search_records", entity="incident", query=lenient)[1]
    assert (status, body) == (200, {"result": mine["items"]}) and len(mine["items"]) == 4  # three, and the one created
    # Domain errors: a missing record, a mandatory field, a transition the workflow refuses.
    assert s.http("GET", f"{table}/0000") == s.local("get_record", id="0000")
    assert s.http("POST", table, {"short_description": "No caller"}) == s.local(
        "create_record", entity="incident", name="No caller", fields={"short_description": "No caller"})
    assert s.http("PATCH", f"{table}/{sys_id}", {"state": "closed"}) == s.local(
        "update_record", id=sys_id, fields={"state": "closed"})
    # A neighbour the connector does not model is refused, not answered from nowhere.
    status, _ = s.http("DELETE", f"{table}/{sys_id}")
    assert status >= 400


@needs_anvil
def test_servicenow_parity_through_the_authored_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("servicenow", _servicenow_records(), cache, tmp_path, _servicenow)
    session.landing.settle()


# -- Salesforce (authored contract) --------------------------------------------------------


def _salesforce_records() -> list[ConnectorRecord]:
    # More accounts than one query batch holds, so the answer carries nextRecordsUrl.
    accounts = [ConnectorRecord(id=f"sf-a{n}", connector="salesforce", entity="account", external_id=f"001{n:012d}AAA",
                                title=f"Account {n:03d}",
                                fields={"Name": f"Account {n:03d}", "region": "SG" if n % 2 else "MY"})
                for n in range(1, 204)]
    cases = [ConnectorRecord(id=f"sf-c{n}", connector="salesforce", entity="case", external_id=f"500{n:012d}AAA",
                             title=f"Case {n}",
                             fields={"Subject": f"Case {n}", "status": "open"}) for n in range(1, 3)]
    return [*accounts, *cases]


def _salesforce(s: Session) -> None:
    base = "/services/data/v61.0"
    soql = "SELECT Id, Name FROM Account"
    status, first = s.http("GET", f"{base}/query", query={"q": soql})
    mine = s.local("query", query=soql)[1]
    assert status == 200 and first["records"] == mine["items"] and len(first["records"]) == 200
    assert first["done"] is False and first["totalSize"] == 203 and first["nextRecordsUrl"].startswith(f"{base}/query/")
    status, rest = s.http("GET", first["nextRecordsUrl"])
    mine = s.local("query", query=soql, start_at=200)[1]
    assert status == 200 and rest["records"] == mine["items"] and len(rest["records"]) == 3
    assert rest["done"] is True and "nextRecordsUrl" not in rest
    filtered = "SELECT Id, Name FROM Account WHERE BillingCountry = 'MY' ORDER BY Name DESC LIMIT 3"
    status, body = s.http("GET", f"{base}/query", query={"q": filtered})
    assert status == 200 and body["records"] == s.local("query", query=filtered)[1]["items"]
    # Create, read back whole and projected, update.
    status, created = s.http("POST", f"{base}/sobjects/Case", {"Subject": "Login fails", "Status": "New"})
    mine = s.local("create_record", entity="case", fields={"Subject": "Login fails", "Status": "New"})[1]
    assert (status, created) == (201, {"id": mine["Id"], "success": True, "errors": []})
    assert s.http("GET", f"{base}/sobjects/Case/{created['id']}") == s.local("get_record", id=created["id"])
    assert s.http("GET", f"{base}/sobjects/Case/{created['id']}", query={"fields": "Subject,Status"}) == s.local(
        "get_record", id=created["id"], fields=["Subject", "Status"])
    account = first["records"][0]["Id"]
    status, body = s.http("PATCH", f"{base}/sobjects/Account/{account}", {"Name": "Account renamed"})
    assert status in (200, 204) and body is None
    s.local("update_record", id=account, fields={"Name": "Account renamed"})
    # Domain errors carry Salesforce's body on both sides.
    assert s.http("GET", f"{base}/sobjects/Account/001000000000000AAA") == s.local("get_record", id="001000000000000AAA")
    assert s.http("GET", f"{base}/query", query={"q": "SELECT Id FROM Account WHERE"}) == s.local(
        "query", query="SELECT Id FROM Account WHERE")
    assert s.http("POST", f"{base}/sobjects/Case", {"Status": "New"}) == s.local(
        "create_record", entity="case", fields={"Status": "New"})
    status, _ = s.http("DELETE", f"{base}/sobjects/Account/{account}")
    assert status >= 400


@needs_anvil
def test_salesforce_parity_through_the_authored_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("salesforce", _salesforce_records(), cache, tmp_path, _salesforce)
    session.landing.settle()


# -- Jira (the vendor's v3 contract) -------------------------------------------------------


#: Anvil pages POST /search/jql by its body token and writes the envelope: the issues and nextPageToken, not isLast.
JIRA_IS_LAST = "Anvil body-token paging: the page envelope does not carry Jira's isLast yet"


def _jira_records() -> list[ConnectorRecord]:
    issues = [("task", "open", "Sev-1"), ("bug", "todo", "Sev-2"), ("story", "review", "Sev-1"),
              ("task", "done", "Sev-3"), ("bug", "open", "Sev-1")]
    return [ConnectorRecord(id=f"rec-{n}", connector="jira", entity=entity, external_id=f"OPS-{n}",
                            title=f"Issue {n} vendor onboarding",
                            fields={"status": status, "project": "OPS", "summary": f"Issue {n} vendor onboarding",
                                    "severity": severity, "assignee": "alice" if n % 2 else "bob",
                                    "created_at": f"2026-09-0{n}T10:00:00+08:00"})
            for n, (entity, status, severity) in enumerate(issues, start=1)]


def _adf(text: str) -> dict[str, Any]:
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _jira(s: Session) -> None:
    api = "/rest/api/3"
    jql = 'project = OPS AND cf[10231] = "Sev-1" ORDER BY created ASC'
    status, page = s.http("POST", f"{api}/search/jql", {"jql": jql, "maxResults": 2})
    mine = s.local("search_issues", query=jql, max_results=2)[1]
    assert status == 200 and page["issues"] == mine["items"] and page["nextPageToken"]
    s.landing.expect(page.get("isLast") is False, JIRA_IS_LAST)
    status, page = s.http("POST", f"{api}/search/jql", {"jql": jql, "maxResults": 2, "nextPageToken": page["nextPageToken"]})
    mine = s.local("search_issues", query=jql, max_results=2, start_at=2)[1]
    assert status == 200 and page["issues"] == mine["items"] and "nextPageToken" not in page
    s.landing.expect(page.get("isLast") is True, JIRA_IS_LAST)
    assert s.http("GET", f"{api}/issue/OPS-2") == s.local("get_issue", id="OPS-2")
    status, created = s.http("POST", f"{api}/issue", {"fields": {
        "summary": "Vendor follow-up", "project": {"key": "OPS"}, "issuetype": {"name": "Task"},
        "customfield_10231": {"value": "Sev-2"}, "description": _adf("Chase the signed form")}})
    mine = s.local("create_issue", entity="task", name="Vendor follow-up",
                   fields={"project": "OPS", "severity": "Sev-2", "summary": "Vendor follow-up",
                           "description": "Chase the signed form"})[1]
    assert (status, created) == (201, {key: mine[key] for key in ("id", "key", "self")})
    assert s.http("PUT", f"{api}/issue/OPS-1", {"fields": {"summary": "Renamed"}})[0] in (200, 204)
    s.local("update_issue", id="OPS-1", fields={"summary": "Renamed"})
    assert s.http("POST", f"{api}/issue/{created['key']}/transitions", {"transition": {"id": "21"}})[0] in (201, 204)
    s.local("transition_issue", id=created["key"], state="open")
    status, comment = s.http("POST", f"{api}/issue/OPS-1/comment", {"body": _adf("Checked with the vendor")})
    s.local("add_comment", id="OPS-1", body="Checked with the vendor")
    assert status == 201 and comment["body"] == "Checked with the vendor"
    assert s.http("GET", f"{api}/issue/OPS-404") == s.local("get_issue", id="OPS-404")
    assert s.http("POST", f"{api}/issue/OPS-4/transitions", {"transition": {"id": "21"}}) == s.local(
        "transition_issue", id="OPS-4", state="open")
    assert s.http("POST", f"{api}/search/jql", {"jql": "project = OPS AND"}) == s.local(
        "search_issues", query="project = OPS AND")
    assert s.http("GET", f"{api}/issue/OPS-1") == s.local("get_issue", id="OPS-1")


@needs_anvil
def test_jira_parity_through_the_vendor_v3_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("jira", _jira_records(), cache, tmp_path, _jira)
    session.landing.settle()


# -- Confluence (the vendor's v2 contract) --------------------------------------------------


#: Anvil pages Confluence's cursor lists and writes the envelope: `results`, and its own continuation field.
CONFLUENCE_NEXT = "Anvil cursor paging: the page envelope does not carry Confluence's _links.next yet"


def _confluence_records() -> list[ConnectorRecord]:
    pages = [ConnectorRecord(id=f"cf-{n}", connector="confluence", entity="page", external_id=str(1000 + n),
                             title=f"Runbook {n}", fields={"space": "OPS", "body": f"Step {n}"}) for n in range(1, 5)]
    posts = [ConnectorRecord(id="cf-b1", connector="confluence", entity="blogpost", external_id="2001",
                             title="Quarter close notes", fields={"space": "OPS", "body": "Closed on time"})]
    return [*pages, *posts]


def _confluence(s: Session) -> None:
    # A title filter is the CQL it means; a listing pages through the rest.
    status, body = s.http("GET", "/pages", query={"title": "Runbook 2"})
    mine = s.local("search", entity="page", query='type = "page" AND title = "Runbook 2"')[1]
    assert status == 200 and body["results"] == mine["items"] and len(mine["items"]) == 1
    status, first = s.http("GET", "/pages", query={"limit": 3})
    mine = s.local("search", entity="page", query='type = "page"', max_results=3)[1]
    assert status == 200 and first["results"] == mine["items"] and len(mine["items"]) == 3
    s.landing.expect(str(first.get("_links", {}).get("next", "")).startswith("/wiki/api/v2/pages?cursor="), CONFLUENCE_NEXT)
    status, posts = s.http("GET", "/blogposts")
    assert status == 200 and posts["results"] == s.local("search", entity="blogpost", query='type = "blogpost"')[1]["items"]
    assert s.http("GET", "/pages/1001") == s.local("get_page", id="1001")
    assert s.http("GET", "/blogposts/2001") == s.local("get_blogpost", id="2001")
    # Create, retitle, replace, comment.
    status, created = s.http("POST", "/pages", {"spaceId": "OPS", "status": "current", "title": "Escalation path",
                                                "body": {"representation": "storage", "value": "Call the lead"}})
    mine = s.local("create_page", entity="page", name="Escalation path",
                   fields={"space": "OPS", "title": "Escalation path", "body": "Call the lead"})[1]
    assert (status, created) == (200, mine)  # Confluence v2 declares 200 for a create, and Anvil serves the declared status
    assert s.http("PUT", "/pages/1002/title", {"status": "current", "title": "Runbook two"}) == s.local(
        "update_page", id="1002", fields={"title": "Runbook two"})
    assert s.http("PUT", "/pages/1003", {"id": "1003", "status": "current", "title": "Runbook three",
                                         "body": {"representation": "storage", "value": "New steps"},
                                         "version": {"number": 2}}) == s.local(
        "update_page", id="1003", fields={"title": "Runbook three", "body": "New steps"})
    status, comment = s.http("POST", "/footer-comments", {"pageId": "1001", "body": {"representation": "storage",
                                                                                    "value": "Reviewed"}})
    s.local("add_comment", id="1001", body="Reviewed")
    assert status == 201 and comment["body"] == "Reviewed"
    # Errors: a page that does not exist, a create missing its space.
    assert s.http("GET", "/pages/9999") == s.local("get_page", id="9999")
    assert s.http("POST", "/pages", {"title": "Orphan", "body": {"representation": "storage", "value": "x"}}) == s.local(
        "create_page", entity="page", name="Orphan", fields={"title": "Orphan", "body": "x"})
    status, _ = s.http("DELETE", "/pages/1001")
    assert status >= 400


@needs_anvil
def test_confluence_parity_through_the_vendor_v2_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("confluence", _confluence_records(), cache, tmp_path, _confluence)
    session.landing.settle()


# -- Slack (the vendor's Web API contract) --------------------------------------------------


#: Anvil pages Slack's lists and writes the envelope itself: the items and a top-level `next_cursor`,
#: without Slack's `ok`, `has_more` and `response_metadata.next_cursor`.
SLACK_ENVELOPE = "Anvil cursor paging: the page envelope does not carry Slack's ok and response_metadata.next_cursor yet"
#: search.messages nests its matches (`messages.matches`) and pages by page number; Anvil writes a flat `items`.
SLACK_SEARCH = "Anvil page-number paging: a nested items field (search.messages' messages.matches) is written as a flat items"
#: conversations.info and users.info are not paged in the AIR, but the simulator pages them.
SLACK_READ = "Anvil paging classification: single-record reads without a path id (conversations.info, users.info) are served as pages"


def _found(body: Any, *paths: str) -> Any:
    """The items at the first of *paths* the body has (``a.b`` nests)."""

    for path in paths:
        node = body
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            return node
    return None


def _slack_records() -> list[ConnectorRecord]:
    channels = [ConnectorRecord(id=f"sl-c{n}", connector="slack", entity="channel", external_id=f"C0{n}",
                                title=name, fields={"name": name}) for n, name in enumerate(("ops", "finance"), start=1)]
    messages = [ConnectorRecord(id=f"sl-m{n}", connector="slack", entity="message", external_id=f"17000000{n}.000100",
                                title=text, fields={"channel": channel, "text": text, "sender": "U01",
                                                    "created_at": f"2026-09-0{n}T09:00:00+08:00"})
                for n, (channel, text) in enumerate((("C01", "Deploy window moved to Friday"),
                                                     ("C01", "Vendor invoice approved"),
                                                     ("C02", "Close checklist is out"),
                                                     ("C01", "Deploy done")), start=1)]
    users = [ConnectorRecord(id="sl-u1", connector="slack", entity="user", external_id="U01", title="alice",
                             fields={"name": "alice"})]
    return [*channels, *messages, *users]


def _slack(s: Session) -> None:
    # The spec declares the token: in the query of a read, in a `token` header of a write.
    def get(path: str, **query: Any) -> tuple[int, Any]:
        return s.http("GET", path, query={"token": "admin", **query})

    def post(path: str, form: dict[str, Any]) -> tuple[int, Any]:
        return s.http("POST", path, form, form=True, headers={"token": "admin"})

    status, body = get("/search.messages", query="deploy in:C01")
    mine = s.local("search_messages", query="deploy in:C01")[1]
    assert status == 200 and _found(body, "messages.matches", "items") == mine["items"] and len(mine["items"]) == 2
    s.landing.expect(_found(body, "messages.matches") is not None, SLACK_SEARCH)
    status, body = get("/conversations.history", channel="C01", limit=2)
    mine = s.local("search_messages", query="in:C01", max_results=2)[1]
    assert status == 200 and body["messages"] == mine["items"]
    s.landing.expect(body.get("ok") is True and _found(body, "response_metadata.next_cursor") == "2", SLACK_ENVELOPE)
    status, rest = get("/conversations.history", channel="C01", limit=2,
                       cursor=_found(body, "response_metadata.next_cursor", "next_cursor"))
    assert status == 200 and rest["messages"] == s.local("search_messages", query="in:C01", max_results=2, start_at=2)[1]["items"]
    status, body = get("/conversations.list", limit=10)
    assert status == 200 and body["channels"] == s.local("list_conversations", max_results=10)[1]["items"]
    for path, query, key, tool, ident in (("/conversations.info", {"channel": "C02"}, "channel", "get_conversation", "C02"),
                                          ("/users.info", {"user": "U01"}, "user", "get_user", "U01")):
        status, body = get(path, **query)
        record = s.local(tool, id=ident)[1]
        # Anvil pages these single-record reads and writes the record as a one-item array under the key.
        assert status == 200 and body[key] in (record, [record])
        s.landing.expect(body == {"ok": True, key: record}, SLACK_READ)
    # Post, edit, delete, as the form body Slack takes.
    status, posted = post("/chat.postMessage", {"channel": "C02", "text": "Books closed"})
    mine = s.local("post_message", entity="message", fields={"channel": "C02", "text": "Books closed"})[1]
    assert status in (200, 201) and posted == {"ok": True, "channel": mine["channel"], "ts": mine["ts"], "message": mine}
    status, edited = post("/chat.update", {"channel": "C01", "ts": "170000002.000100", "text": "Invoice paid"})
    mine = s.local("update_message", id="170000002.000100", fields={"text": "Invoice paid"})[1]
    assert status in (200, 201) and edited == {"ok": True, "channel": "C01", "ts": mine["ts"], "text": mine["text"]}
    status, deleted = post("/chat.delete", {"channel": "C01", "ts": "170000004.000100"})
    s.local("delete_message", id="170000004.000100")
    assert status in (200, 201) and deleted == {"ok": True, "ts": "170000004.000100"}
    # Slack answers its errors with 200 and ok false, on both sides.
    assert get("/conversations.info", channel="C99") == s.local("get_conversation", id="C99")
    assert post("/chat.update", {"channel": "C01", "ts": "1.000000", "text": "x"}) == s.local(
        "update_message", id="1.000000", fields={"text": "x"})
    status, _ = post("/reactions.add", {"channel": "C01", "timestamp": "170000001.000100", "name": "eyes"})
    assert status >= 400


@needs_anvil
def test_slack_parity_through_the_vendor_web_api_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("slack", _slack_records(), cache, tmp_path, _slack)
    session.landing.settle()


# -- Google Drive (the vendor's Discovery document) ----------------------------------------


#: Anvil pages files.list by pageToken and writes the envelope: `files` and `nextPageToken`, without `kind`.
DRIVE_ENVELOPE = "Anvil cursor paging: the page envelope does not carry Drive's kind and incompleteSearch yet"

GDOC = "application/vnd.google-apps.document"


def _drive_records() -> list[ConnectorRecord]:
    folder = ConnectorRecord(id="dr-f", connector="drive", entity="folder", external_id="fold1", title="Finance",
                             fields={"name": "Finance"})
    files = [ConnectorRecord(id=f"dr-{n}", connector="drive", entity=entity, external_id=f"file{n}", title=name,
                             fields={"name": name, "folder": "fold1", "modified_at": f"2026-09-0{n}T09:00:00+08:00"})
             for n, (entity, name) in enumerate((("gdoc", "Budget memo"), ("xlsx", "Budget workbook"),
                                                 ("pdf", "Audit letter"), ("gdoc", "Budget notes")), start=1)]
    return [folder, *files]


def _drive(s: Session) -> None:
    q = "name contains 'Budget' and trashed = false"
    status, body = s.http("GET", "/files", query={"q": q, "pageSize": 2})
    mine = s.local("search", query=q, max_results=2)[1]
    assert status == 200 and body["files"] == mine["items"] and body["nextPageToken"] == "2"
    s.landing.expect(body.get("kind") == "drive#fileList", DRIVE_ENVELOPE)
    status, body = s.http("GET", "/files", query={"q": q, "pageSize": 2, "pageToken": body["nextPageToken"]})
    mine = s.local("search", query=q, max_results=2, start_at=2)[1]
    assert status == 200 and body["files"] == mine["items"] and "nextPageToken" not in body
    assert s.http("GET", "/files/file1") == s.local("get_file", id="file1")
    assert s.http("GET", "/files/fold1") == s.local("list_folder", id="fold1")
    # Create a Google Doc and an upload; the mime type chooses the tool.
    status, doc = s.http("POST", "/files", {"name": "Close plan", "mimeType": GDOC, "parents": ["fold1"]})
    mine = s.local("create_doc", entity="gdoc", name="Close plan", parent="fold1", fields={"name": "Close plan"})[1]
    assert (status, doc) == (200, mine)
    status, upload = s.http("POST", "/files", {"name": "Q3.csv", "mimeType": "text/csv"})
    assert (status, upload) == (200, s.local("upload_file", entity="csv", name="Q3.csv", fields={"name": "Q3.csv"})[1])
    # An update routes by what the file is: a Google Doc and an upload take different tools.
    assert s.http("PATCH", "/files/file1", {"name": "Budget memo v2"}) == s.local(
        "update_doc", id="file1", fields={"name": "Budget memo v2"})
    assert s.http("PATCH", "/files/file2", {"description": "Locked"}) == s.local(
        "update_file", id="file2", fields={"description": "Locked"})
    status, _ = s.http("DELETE", "/files/file3")
    assert status in (200, 204)
    s.local("delete_file", id="file3")
    # Errors: a file that does not exist, a query Drive refuses.
    assert s.http("GET", "/files/nope") == s.local("get_file", id="nope")
    assert s.http("GET", "/files", query={"q": "name > 'x'"}) == s.local("search", query="name > 'x'")
    status, _ = s.http("GET", "/files/file1/export", query={"mimeType": "application/pdf"})
    assert status >= 400


@needs_anvil
def test_drive_parity_through_the_vendor_discovery_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("drive", _drive_records(), cache, tmp_path, _drive)
    session.landing.settle()


# -- Microsoft Graph: Outlook mail ----------------------------------------------------------


#: Anvil pages Graph lists by $skiptoken and writes `value`; the `@odata.nextLink` continuation is the part pending.
GRAPH_NEXT = "Anvil OData paging: the page envelope does not carry Graph's @odata.nextLink yet"
#: GET .../content reads one item's bytes; Anvil classifies it as a list and serves a page.
GRAPH_CONTENT = "Anvil paging classification: a driveItem's GET .../content is served as a page"


def _outlook_records() -> list[ConnectorRecord]:
    folders = [ConnectorRecord(id=f"ol-f{n}", connector="outlook", entity="mail_folder", external_id=f"AAMkFolder{n}",
                               title=name, fields={"name": name}) for n, name in enumerate(("Inbox", "Archive"), start=1)]
    messages = [ConnectorRecord(id=f"ol-m{n}", connector="outlook", entity="message", external_id=f"AAMkMsg{n}",
                                title=subject, fields={"subject": subject, "sender": sender, "recipients": ["ops@contoso.com"],
                                                       "is_read": n % 2 == 0, "body": f"Body {n}", "state": "sent",
                                                       "received_at": f"2026-09-0{n}T09:00:00Z"})
                for n, (subject, sender) in enumerate((("Invoice 104 overdue", "ap@vendor.com"),
                                                       ("Close timetable", "controller@contoso.com"),
                                                       ("Invoice 105 received", "ap@vendor.com")), start=1)]
    return [*folders, *messages]


def _outlook(s: Session) -> None:
    flt = "from/emailAddress/address eq 'ap@vendor.com'"
    status, body = s.http("GET", "/me/messages", query={"$filter": flt, "$top": 1})
    mine = s.local("list_messages", query=f"$filter={flt}", max_results=1)[1]
    assert status == 200 and body["value"] == mine["items"] and len(mine["items"]) == 1
    link = urllib.parse.urlsplit(str(body.get("@odata.nextLink", "")))
    s.landing.expect(urllib.parse.parse_qs(link.query).get("$skiptoken") == ["1"], GRAPH_NEXT)
    status, body = s.http("GET", "/me/messages", query={"$filter": flt, "$top": 1, "$skiptoken": "1"})
    assert status == 200 and body["value"] == s.local("list_messages", query=f"$filter={flt}", max_results=1, start_at=1)[1]["items"]
    status, body = s.http("GET", "/me/messages", query={"$search": '"timetable"'})
    assert status == 200 and body["value"] == s.local("list_messages", query='$search="timetable"')[1]["items"]
    assert s.http("GET", "/me/messages/AAMkMsg2") == s.local("get_message", id="AAMkMsg2")
    status, body = s.http("GET", "/me/mailFolders")
    assert status == 200 and body["value"] == s.local("list_folders")[1]["items"]
    # Draft, mark read, reply, forward, move, send, delete.
    draft = {"subject": "Payment run", "body": {"contentType": "text", "content": "Run on Friday"},
             "toRecipients": [{"emailAddress": {"address": "treasury@contoso.com"}}]}
    status, created = s.http("POST", "/me/messages", draft)
    mine = s.local("create_draft", entity="message", name="Payment run",
                   fields={"subject": "Payment run", "body": "Run on Friday", "recipients": ["treasury@contoso.com"]})[1]
    assert (status, created) == (201, mine)
    assert s.http("PATCH", "/me/messages/AAMkMsg1", {"isRead": True}) == s.local(
        "update_message", id="AAMkMsg1", fields={"is_read": True})
    assert s.http("POST", "/me/messages/AAMkMsg1/reply", {"comment": "Paid today"})[0] in (200, 201, 202, 204)
    s.local("reply_message", id="AAMkMsg1", body="Paid today")
    assert s.http("POST", "/me/messages/AAMkMsg3/forward", {
        "comment": "For filing", "toRecipients": [{"emailAddress": {"address": "records@contoso.com"}}]})[0] in (200, 201, 202, 204)
    s.local("forward_message", id="AAMkMsg3", to=["records@contoso.com"], body="For filing")
    # The contract spells the move body PascalCase (DestinationId) and keeps only declared fields.
    status, moved = s.http("POST", "/me/messages/AAMkMsg2/move", {"DestinationId": "AAMkFolder2"})
    assert status in (200, 201) and moved == s.local("move_message", id="AAMkMsg2", parent="AAMkFolder2")[1]
    assert s.http("POST", "/me/sendMail", {"message": {"subject": "Close done", "body": {"contentType": "text", "content": "All done"},
                                                        "toRecipients": [{"emailAddress": {"address": "cfo@contoso.com"}}]},
                                           "saveToSentItems": True})[0] in (200, 201, 202, 204)
    s.local("send_message", entity="message", name="Close done",
            fields={"subject": "Close done", "body": "All done", "recipients": ["cfo@contoso.com"]})
    assert s.http("DELETE", "/me/messages/AAMkMsg3")[0] in (200, 204)
    s.local("delete_message", id="AAMkMsg3")
    # Errors: a message that does not exist, a filter Graph refuses, a draft with no subject.
    assert s.http("GET", "/me/messages/AAMkNope") == s.local("get_message", id="AAMkNope")
    assert s.http("GET", "/me/messages", query={"$filter": "subject eq"}) == s.local("list_messages", query="$filter=subject eq")
    assert s.http("POST", "/me/messages", {"body": {"contentType": "text", "content": "x"}}) == s.local(
        "create_draft", entity="message", fields={"body": "x"})
    status, _ = s.http("POST", "/me/messages/AAMkMsg1/replyAll", {"comment": "x"})
    assert status >= 400


@needs_anvil
def test_outlook_parity_through_the_vendor_graph_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("outlook", _outlook_records(), cache, tmp_path, _outlook)
    session.landing.settle()


# -- Microsoft Graph: OneDrive ---------------------------------------------------------------


def _drive_items(connector: str, prefix: str) -> list[ConnectorRecord]:
    folders = [ConnectorRecord(id=f"{prefix}-f{n}", connector=connector, entity="folder", external_id=f"01FOLDER{n}",
                               title=name, fields={"name": name, "parent": "root"})
               for n, name in enumerate(("Finance", "Archive"), start=1)]
    files = [ConnectorRecord(id=f"{prefix}-{n}", connector=connector, entity=entity, external_id=f"01ITEM{n}", title=name,
                             fields={"name": name, "parent": "01FOLDER1", "body": text,
                                     "modified_at": f"2026-09-0{n}T09:00:00Z"})
             for n, (entity, name, text) in enumerate((("docx", "Budget memo.docx", "Budget for the quarter"),
                                                        ("xlsx", "Budget model.xlsx", "Budget model"),
                                                        ("pdf", "Audit letter.pdf", "Letter from the auditor")), start=1)]
    return [*folders, *files]


def _onedrive(s: Session) -> None:
    drive = "/drives/b!drive1"
    status, body = s.http("GET", f"{drive}/search(q='budget')")
    mine = s.local("search_items", query="budget", drive_id="b!drive1")[1]  # search(q=) is KQL, as Microsoft Search reads it
    assert status == 200 and body["value"] == mine["items"] and len(mine["items"]) == 2
    status, body = s.http("GET", f"{drive}/items/01FOLDER1/children")
    assert status == 200 and body["value"] == s.local("list_children", id="01FOLDER1")[1]["items"]
    assert s.http("GET", f"{drive}/items/01ITEM1") == s.local("get_item", id="01ITEM1")
    assert s.http("GET", f"{drive}/items/01ITEM1", query={"$select": "name,size"}) == s.local(
        "get_item", id="01ITEM1", fields=["name", "size"])
    status, body = s.http("GET", f"{drive}/items/01ITEM3/content")
    record = s.local("download_content", id="01ITEM3")[1]
    assert status == 200 and record in (body, *(body.get("items") or ()))
    s.landing.expect(body == record, GRAPH_CONTENT)
    # A folder facet creates a folder; a file name creates a file of its type.
    status, folder = s.http("POST", f"{drive}/items/01FOLDER1/children", {"name": "Q3", "folder": {}})
    mine = s.local("create_folder", entity="folder", name="Q3", parent="01FOLDER1", fields={"name": "Q3"})[1]
    assert (status, folder) == (201, mine)
    status, upload = s.http("POST", f"{drive}/items/01FOLDER1/children", {"name": "Plan.docx", "file": {}})
    mine = s.local("upload_file", entity="docx", name="Plan.docx", parent="01FOLDER1", fields={"name": "Plan.docx"})[1]
    assert (status, upload) == (201, mine)
    # A rename is an update; a new parentReference is a move.
    assert s.http("PATCH", f"{drive}/items/01ITEM2", {"name": "Budget model v2.xlsx"}) == s.local(
        "update_item", id="01ITEM2", fields={"name": "Budget model v2.xlsx"})
    assert s.http("PATCH", f"{drive}/items/01ITEM3", {"parentReference": {"id": "01FOLDER2"}}) == s.local(
        "move_item", id="01ITEM3", parent="01FOLDER2")
    assert s.http("DELETE", f"{drive}/items/01ITEM1")[0] in (200, 204)
    s.local("delete_item", id="01ITEM1")
    # Errors: an item that does not exist, a move into a file.
    assert s.http("GET", f"{drive}/items/01NOPE") == s.local("get_item", id="01NOPE")
    assert s.http("PATCH", f"{drive}/items/01ITEM2", {"parentReference": {"id": "01ITEM3"}}) == s.local(
        "move_item", id="01ITEM2", parent="01ITEM3")
    status, _ = s.http("POST", f"{drive}/items/01ITEM2/checkout")
    assert status >= 400


@needs_anvil
def test_onedrive_parity_through_the_vendor_graph_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("onedrive", _drive_items("onedrive", "od"), cache, tmp_path, _onedrive)
    session.landing.settle()


# -- Microsoft Graph: SharePoint ------------------------------------------------------------


def _sharepoint_records() -> list[ConnectorRecord]:
    items = [ConnectorRecord(id=f"sp-l{n}", connector="sharepoint", entity="list_item", external_id=f"LI{n}", title=title,
                             fields={"fields": {"Title": title, "Status": status}, "status": status})
             for n, (title, status) in enumerate((("Renew lease", "Open"), ("Replace badge readers", "Done"),
                                                  ("Audit fire exits", "Open")), start=1)]
    pages = [ConnectorRecord(id="sp-p1", connector="sharepoint", entity="site_page", external_id="PAGE1", title="Onboarding",
                             fields={"title": "Onboarding", "name": "Onboarding.aspx", "body": "Start here"})]
    return [*_drive_items("sharepoint", "sp"), *items, *pages]


def _sharepoint(s: Session) -> None:
    drive, site = "/drives/b!site1", "/sites/contoso.sharepoint.com,1,2"
    status, body = s.http("GET", f"{drive}/search(q='budget')")
    mine = s.local("search_files", query="budget")[1]
    assert status == 200 and body["value"] == mine["items"] and len(mine["items"]) == 2
    assert s.http("GET", f"{drive}/items/01ITEM1") == s.local("get_file", id="01ITEM1")
    assert s.http("GET", f"{drive}/items/01FOLDER2") == s.local("list_folder", id="01FOLDER2")
    status, created = s.http("POST", f"{drive}/items/01FOLDER1/children", {"name": "Q3 plan.docx", "file": {}})
    mine = s.local("create_file", entity="docx", name="Q3 plan.docx", parent="01FOLDER1", fields={"name": "Q3 plan.docx"})[1]
    assert (status, created) == (201, mine)
    assert s.http("PATCH", f"{drive}/items/01ITEM2", {"name": "Budget model v2.xlsx"}) == s.local(
        "update_file", id="01ITEM2", fields={"name": "Budget model v2.xlsx"})
    assert s.http("PATCH", f"{drive}/items/01ITEM3", {"parentReference": {"id": "01FOLDER2"}}) == s.local(
        "move_file", id="01ITEM3", parent="01FOLDER2")
    # List items: an OData filter over the item's fields, a create, a delete.
    flt = "fields/Status eq 'Open'"
    status, body = s.http("GET", f"{site}/lists/L1/items", query={"$filter": flt})
    mine = s.local("get_list_items", entity="list_item", query=f"$filter={flt}")[1]
    assert status == 200 and body["value"] == mine["items"] and len(mine["items"]) == 2
    status, item = s.http("POST", f"{site}/lists/L1/items", {"fields": {"Title": "Order chairs", "Status": "Open"}})
    mine = s.local("create_list_item", entity="list_item", name="Order chairs", parent="L1",
                   fields={"fields": {"Title": "Order chairs", "Status": "Open"}})[1]
    assert (status, item) == (201, mine)
    assert s.http("DELETE", f"{site}/lists/L1/items/LI2")[0] in (200, 204)
    s.local("delete_list_item", id="LI2")
    # Site pages.
    status, body = s.http("GET", f"{site}/pages")
    assert status == 200 and body["value"] == s.local("search_pages")[1]["items"]
    assert s.http("GET", f"{site}/pages/PAGE1") == s.local("get_page", id="PAGE1")
    status, page = s.http("POST", f"{site}/pages", {"name": "Travel.aspx", "title": "Travel policy"})
    mine = s.local("create_page", entity="site_page", name="Travel.aspx", parent="contoso.sharepoint.com,1,2",
                   fields={"title": "Travel policy", "name": "Travel.aspx"})[1]
    assert (status, page) == (201, mine)
    assert s.http("PATCH", f"{site}/pages/PAGE1", {"title": "Onboarding guide"}) == s.local(
        "update_page", id="PAGE1", fields={"title": "Onboarding guide"})
    # Errors: a file that does not exist, a filter Graph refuses.
    assert s.http("GET", f"{drive}/items/01NOPE") == s.local("get_file", id="01NOPE")
    assert s.http("GET", f"{site}/lists/L1/items", query={"$filter": "fields/Status eq"}) == s.local(
        "get_list_items", entity="list_item", query="$filter=fields/Status eq")
    status, _ = s.http("PATCH", f"{site}/lists/L1/items/LI1/fields", {"Status": "Done"})
    assert status >= 400


@needs_anvil
def test_sharepoint_parity_through_the_vendor_graph_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("sharepoint", _sharepoint_records(), cache, tmp_path, _sharepoint)
    session.landing.settle()


# -- Microsoft Graph: Teams -----------------------------------------------------------------


def _teams_records() -> list[ConnectorRecord]:
    team = ConnectorRecord(id="tm-t1", connector="teams", entity="team", external_id="TEAM1", title="Finance",
                           fields={"displayName": "Finance", "description": "Finance team"})
    channels = [ConnectorRecord(id=f"tm-c{n}", connector="teams", entity="channel", external_id=f"19:chan{n}@thread.tacv2",
                                title=name, fields={"displayName": name, "team": "TEAM1"})
                for n, name in enumerate(("General", "Close"), start=1)]
    messages = [ConnectorRecord(id=f"tm-m{n}", connector="teams", entity="channel_message", external_id=f"MSG{n}", title=text,
                                fields={"body": text, "channel": "19:chan2@thread.tacv2", "team": "TEAM1", "sender": "alice",
                                        "created_at": f"2026-09-0{n}T09:00:00Z"})
                for n, text in enumerate(("Close starts Monday", "Accruals posted"), start=1)]
    chat = ConnectorRecord(id="tm-ch1", connector="teams", entity="chat", external_id="19:chat1@unq.gbl.spaces",
                           title="Audit prep", fields={"topic": "Audit prep", "members": ["alice", "bob"]})
    return [team, *channels, *messages, chat]


def _teams(s: Session) -> None:
    team, channel = "/teams/TEAM1", "/teams/TEAM1/channels/19:chan2@thread.tacv2"
    status, body = s.http("GET", "/teams", query={"$filter": "displayName eq 'Finance'"})
    mine = s.local("list_teams", query="$filter=displayName eq 'Finance'")[1]
    assert status == 200 and body["value"] == mine["items"] and len(mine["items"]) == 1
    assert s.http("GET", team) == s.local("get_team", id="TEAM1")
    status, body = s.http("GET", f"{team}/channels")
    assert status == 200 and body["value"] == s.local("list_channels", id="TEAM1")[1]["items"]
    assert s.http("GET", channel) == s.local("get_channel", id="19:chan2@thread.tacv2")
    status, body = s.http("GET", f"{channel}/messages", query={"$top": 1})
    assert status == 200 and body["value"] == s.local("list_channel_messages", id="19:chan2@thread.tacv2", max_results=1)[1]["items"]
    assert s.http("GET", f"{channel}/messages/MSG1") == s.local("get_channel_message", id="MSG1")
    # Post, reply, edit, delete in a channel; create a channel; post in a chat. Anvil serves
    # some of Graph's creates 201 and some 200, so the status is either.
    status, posted = s.http("POST", f"{channel}/messages", {"body": {"contentType": "text", "content": "Reconciliations due"}})
    mine = s.local("post_channel_message", entity="channel_message", parent="19:chan2@thread.tacv2",
                   fields={"body": "Reconciliations due", "channel": "19:chan2@thread.tacv2", "team": "TEAM1"})[1]
    assert status in (200, 201) and posted == mine
    status, reply = s.http("POST", f"{channel}/messages/MSG1/replies", {"body": {"content": "Confirmed"}})
    assert status in (200, 201) and reply == s.local("reply_channel_message", id="MSG1", body="Confirmed")[1]
    assert s.http("PATCH", f"{channel}/messages/MSG2", {"body": {"content": "Accruals posted and reviewed"}})[0] in (200, 204)
    s.local("update_channel_message", id="MSG2", fields={"body": "Accruals posted and reviewed"})
    assert s.http("DELETE", f"{channel}/messages/MSG1")[0] in (200, 204)
    s.local("delete_channel_message", id="MSG1")
    status, created = s.http("POST", f"{team}/channels", {"displayName": "Audit", "membershipType": "standard"})
    mine = s.local("create_channel", entity="channel", name="Audit", parent="TEAM1",
                   fields={"displayName": "Audit", "membership_type": "standard", "team": "TEAM1"})[1]
    assert status in (200, 201) and created == mine
    status, chat = s.http("POST", "/chats/19:chat1@unq.gbl.spaces/messages", {"body": {"content": "Files are in"}})
    mine = s.local("post_chat_message", entity="chat_message", parent="19:chat1@unq.gbl.spaces",
                   fields={"body": "Files are in", "chat": "19:chat1@unq.gbl.spaces"})[1]
    assert status in (200, 201) and chat == mine
    # Errors: a channel that does not exist, a message with no body.
    assert s.http("GET", f"{team}/channels/19:nope@thread.tacv2") == s.local("get_channel", id="19:nope@thread.tacv2")
    assert s.http("POST", f"{channel}/messages", {"subject": "no body"}) == s.local(
        "post_channel_message", entity="channel_message", parent="19:chan2@thread.tacv2",
        fields={"channel": "19:chan2@thread.tacv2", "team": "TEAM1"})
    status, _ = s.http("POST", f"{team}/archive")
    assert status >= 400


@needs_anvil
def test_teams_parity_through_the_vendor_graph_contract(cache: Path, tmp_path: Path) -> None:
    session = _run("teams", _teams_records(), cache, tmp_path, _teams)
    session.landing.settle()
