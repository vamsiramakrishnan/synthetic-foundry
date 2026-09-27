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
             form: bool = False) -> tuple[int, Any]:
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
                                         headers={"Content-Type": content, "Authorization": "Bearer admin"})
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
