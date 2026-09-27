"""The contract pack: the lock, fetching by digest, trims, mappings against the locked surface, coverage.

Nothing here needs Node or Anvil: the parity through Anvil is
``tests/test_contract_parity.py``. These tests hold the pack to what it
claims without compiling it: every connector is locked or says why not, an
authored contract hashes to its lock, a fetch refuses bytes that hash to
anything else, and every shipped mapping covers exactly the operations the
committed trim of its contract declares, with tools and arguments the
connector definition takes.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_definition import (
    REFERENCE_CONNECTORS,
    load_connector_definition,
)
from worldloom.connectors.anvil import (
    ContractOperation,
    lint_mapping,
    load_mapping,
    shipped_mappings,
)
from worldloom.connectors.contracts import (
    ContractError,
    count_operations,
    coverage,
    data_file,
    fetch_contract,
    load_lock,
    parse_lock,
    read_document,
    source_format,
    source_path,
    trim,
    write_trim,
)

FIXTURES = Path(__file__).parent / "fixtures" / "anvil" / "contracts"
runner = CliRunner()


def _trim_operations(connector: str) -> list[ContractOperation]:
    """The operations the committed trim declares, as a lint over the vendor's own ids reads them."""

    document = read_document(FIXTURES / f"{connector}.spec.json.gz")
    out = []
    if source_format(document) == "discovery":
        def walk(node: dict[str, Any]) -> None:
            for method in (node.get("methods") or {}).values():
                out.append(ContractOperation(method["id"], method=method["httpMethod"], path="/" + method["path"],
                                             vendor=method["id"]))
            for child in (node.get("resources") or {}).values():
                walk(child)
        walk(document)
        return out
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                out.append(ContractOperation(operation["operationId"], method=method.upper(), path=path,
                                             vendor=operation["operationId"]))
    return out


# -- the lock ------------------------------------------------------------------------------


def test_every_connector_is_locked_to_a_contract_or_says_why_not() -> None:
    lock = load_lock()
    assert set(lock.contracts) | set(lock.uncontracted) == set(REFERENCE_CONNECTORS)
    assert set(lock.contracts) == set(shipped_mappings())
    for name, contract in lock.contracts.items():
        assert data_file(contract.profile).is_file(), name
        assert contract.manifest is None or data_file(contract.manifest).is_file(), name
        assert contract.profiled_operations <= contract.vendor_operations
        if contract.provenance == "vendor":
            assert contract.source.url and contract.source.url.startswith("https://"), name
        else:
            assert contract.documentation and all(url.startswith("https://") for url in contract.documentation), name
    assert {name for name, contract in lock.contracts.items() if contract.provenance == "authored"} == {"servicenow", "salesforce"}


def test_an_authored_contract_hashes_to_its_lock_and_counts_what_it_declares() -> None:
    for name in ("servicenow", "salesforce"):
        contract = load_lock().contract(name)
        assert contract.source.path is not None
        data = data_file(contract.source.path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == contract.source.sha256 and len(data) == contract.source.bytes
        assert count_operations(json.loads(data)) == contract.vendor_operations


@pytest.mark.parametrize("change, match", [
    ({"provenance": "scraped"}, "provenance must be one of"),
    ({"source": {"format": "openapi3", "sha256": "0" * 64, "bytes": 1, "filename": "x.json", "version": "1", "locked": "x"}},
     "names the `url`"),
    ({"source": {"url": "https://x", "format": "raml", "sha256": "0" * 64, "bytes": 1, "filename": "x", "version": "1",
                 "locked": "x"}}, "format must be one of"),
    ({"source": {"url": "https://x", "format": "openapi3", "sha256": "ABC", "bytes": 1, "filename": "x", "version": "1",
                 "locked": "x"}}, "64 lowercase hex"),
])
def test_a_lock_entry_that_cannot_be_verified_is_refused(change: dict[str, Any], match: str) -> None:
    document = json.loads(data_file("_contracts.json").read_text(encoding="utf-8"))
    document["contracts"]["jira"].update(change)
    with pytest.raises(ContractError, match=match):
        parse_lock(document)
    authored = json.loads(data_file("_contracts.json").read_text(encoding="utf-8"))
    del authored["contracts"]["servicenow"]["documentation"]
    with pytest.raises(ContractError, match="documentation"):
        parse_lock(authored)


def _anvil_checkout() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "anvil" / "examples" / "profiles"
        if candidate.is_dir():
            return parent / "anvil"
    return None


@pytest.mark.skipif(_anvil_checkout() is None, reason="needs an Anvil checkout beside this one")
def test_the_lock_agrees_with_the_source_pins_of_anvils_reviewed_profiles() -> None:
    import re

    checkout = _anvil_checkout()
    assert checkout is not None
    referenced = {name: contract for name, contract in load_lock().contracts.items() if contract.anvil_profile}
    assert set(referenced) == {"jira", "confluence", "slack", "drive", "outlook", "onedrive", "sharepoint", "teams"}
    for name, contract in referenced.items():
        text = (checkout / str(contract.anvil_profile)).read_text(encoding="utf-8")
        pins = dict(re.findall(r"^\s+(url|sha256|content_sha256):\s*(\S+)", text, flags=re.MULTILINE))
        assert pins["url"] == contract.source.url, name
        # Drive's pin, like its lock, is of the canonical JSON Google's reordering cannot move.
        key = "content_sha256" if contract.source.canonical == "json" else "sha256"
        assert pins[key] == f"sha256:{contract.source.sha256}", name


def test_an_uncontracted_connector_says_why_when_asked_for_its_contract() -> None:
    with pytest.raises(ContractError, match="no contract: a provider-neutral mailbox"):
        load_lock().contract("email")


# -- fetch ---------------------------------------------------------------------------------


def test_a_fetch_refuses_bytes_that_hash_to_anything_but_the_lock(tmp_path: Path) -> None:
    contract = load_lock().contract("jira")
    with pytest.raises(ContractError, match=f"not the locked sha256:{contract.source.sha256}") as refused:
        fetch_contract(contract, tmp_path, opener=lambda url: b'{"openapi": "3.0.0", "paths": {}}')
    assert "re-lock" in str(refused.value)
    assert not source_path(contract, tmp_path).exists()


def test_a_fetch_writes_verified_bytes_once_and_then_reads_the_cache(tmp_path: Path) -> None:
    lock = load_lock()
    contract = lock.contract("jira")
    fake = b"the locked bytes"
    pinned = type(contract)(**{**contract.__dict__, "source": type(contract.source)(
        **{**contract.source.__dict__, "sha256": hashlib.sha256(fake).hexdigest(), "bytes": len(fake)})})
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        return fake

    first = fetch_contract(pinned, tmp_path, opener=opener)
    second = fetch_contract(pinned, tmp_path, opener=opener)
    assert (first.status, second.status) == ("fetched", "cached") and calls == [contract.source.url]
    assert first.path.read_bytes() == fake
    authored = fetch_contract(lock.contract("servicenow"), tmp_path)
    assert authored.status == "copied" and authored.path.name == "servicenow.openapi.json"


def test_a_canonical_json_lock_accepts_the_same_document_in_any_key_order(tmp_path: Path) -> None:
    # Google's Discovery service serves the Drive document with its keys in a
    # different order on every request; its lock pins the canonical JSON.
    from worldloom.connectors.contracts import canonical_json

    contract = load_lock().contract("drive")
    assert contract.source.canonical == "json"
    document = {"b": [1, {"y": 2, "x": 1}], "a": "one"}
    canonical = canonical_json(json.dumps(document).encode())
    pinned = type(contract)(**{**contract.__dict__, "source": type(contract.source)(
        **{**contract.source.__dict__, "sha256": hashlib.sha256(canonical).hexdigest(), "bytes": len(canonical)})})
    served = json.dumps({"a": "one", "b": [1, {"x": 1, "y": 2}]}, indent=2).encode()
    fetched = fetch_contract(pinned, tmp_path, opener=lambda url: served)
    assert fetched.status == "fetched" and fetched.path.read_bytes() == canonical
    with pytest.raises(ContractError, match="not the locked"):
        fetch_contract(pinned, tmp_path / "other", opener=lambda url: json.dumps({"a": "two"}).encode())


def test_the_cli_fetches_an_authored_contract_and_reports_coverage(tmp_path: Path) -> None:
    result = runner.invoke(app, ["contracts", "fetch", "servicenow", "salesforce", "--cache", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [(row["connector"], row["status"]) for row in rows] == [("servicenow", "copied"), ("salesforce", "copied")]
    result = runner.invoke(app, ["contracts", "coverage", "--json"])
    assert result.exit_code == 0, result.output
    by_name = {row["connector"]: row for row in json.loads(result.output)}
    assert by_name["jira"] == {"connector": "jira", "provenance": "vendor", "vendor_operations": 619, "profiled": 26,
                               "modelled": 9, "unmodelled": 17, "mapping_matches_profile": True, "reason": None}
    assert by_name["email"]["provenance"] == "none" and by_name["email"]["reason"]
    assert all(row["mapping_matches_profile"] for row in by_name.values() if row["provenance"] != "none")


def test_the_cli_refuses_a_build_without_anvil(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORLDLOOM_ANVIL", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    result = runner.invoke(app, ["contracts", "build", "jira", "--cache", str(tmp_path)])
    assert result.exit_code == 2 and "no Anvil CLI" in result.output, result.output


# -- trims ---------------------------------------------------------------------------------


def test_a_trim_keeps_the_exposed_operations_and_only_the_schemas_they_reach(tmp_path: Path) -> None:
    spec = {
        "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
        "paths": {
            "/a": {"get": {"operationId": "getA", "responses": {"200": {"content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/A"}}}}}},
                   "delete": {"operationId": "deleteA", "responses": {"204": {"description": "gone"}}}},
            "/b": {"get": {"operationId": "getB", "responses": {"200": {"$ref": "#/components/responses/B"}}}},
        },
        "components": {
            "schemas": {"A": {"properties": {"child": {"$ref": "#/components/schemas/Child"}}}, "Child": {"type": "string"},
                        "B": {"type": "object"}, "Orphan": {"type": "object"}},
            "responses": {"B": {"description": "b", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/B"}}}}},
            "securitySchemes": {"basic": {"type": "http", "scheme": "basic"}},
        },
    }
    cut = trim(spec, [("GET", "/a", "getA")])
    assert list(cut["paths"]) == ["/a"] and list(cut["paths"]["/a"]) == ["get"]
    assert sorted(cut["components"]["schemas"]) == ["A", "Child"] and "responses" not in cut["components"]
    assert cut["components"]["securitySchemes"] == spec["components"]["securitySchemes"]
    path = write_trim(cut, tmp_path / "t.spec.json.gz")
    again = write_trim(cut, tmp_path / "u.spec.json.gz")
    assert path.read_bytes() == again.read_bytes() and read_document(path) == cut
    swagger = {"swagger": "2.0", "info": {"title": "s", "version": "1"},
               "paths": {"/x": {"get": {"operationId": "x", "responses": {"200": {"schema": {"$ref": "#/definitions/X"}}}}},
                         "/y": {"get": {"operationId": "y", "responses": {"200": {"schema": {"$ref": "#/definitions/Y"}}}}}},
               "definitions": {"X": {"type": "object"}, "Y": {"type": "object"}}}
    assert list(trim(swagger, [("GET", "/y", "y")])["definitions"]) == ["Y"]
    discovery = {"discoveryVersion": "v1", "kind": "discovery#restDescription", "schemas": {
        "File": {"properties": {"owner": {"$ref": "User"}}}, "User": {"type": "object"}, "Drive": {"type": "object"}},
        "resources": {"files": {"methods": {"get": {"id": "d.files.get", "httpMethod": "GET", "path": "files/{id}",
                                                    "response": {"$ref": "File"}},
                                            "delete": {"id": "d.files.delete", "httpMethod": "DELETE", "path": "files/{id}"}}},
                      "drives": {"methods": {"list": {"id": "d.drives.list", "httpMethod": "GET", "path": "drives",
                                                      "response": {"$ref": "Drive"}}}}}}
    cut = trim(discovery, [(None, None, "d.files.get")])
    assert list(cut["resources"]) == ["files"] and list(cut["resources"]["files"]["methods"]) == ["get"]
    assert sorted(cut["schemas"]) == ["File", "User"]


@pytest.mark.parametrize("connector", sorted(load_lock().contracts))
def test_the_committed_trim_declares_exactly_what_the_mapping_covers(connector: str) -> None:
    contract = load_lock().contract(connector)
    document = read_document(FIXTURES / f"{connector}.spec.json.gz")
    assert source_format(document) == contract.source.format
    assert count_operations(document) == contract.profiled_operations
    mapping = load_mapping(connector)
    assert len(mapping.operations) == contract.profiled_operations
    operations = _trim_operations(connector)
    errors, advisories = lint_mapping(mapping, operations, load_connector_definition(connector))
    assert errors == () and advisories == (), (errors, advisories)
    routes = {operation.vendor: operation.route for operation in operations}
    for entry in mapping.operations.values():
        assert entry.vendor in routes, f"{entry.operation_id} names vendor operation {entry.vendor}, not in the contract"
        if connector != "jira":  # the Jira mapping's routes are the v2 paths of Anvil's backtest trim
            assert entry.route == routes[entry.vendor], entry.operation_id


def test_the_trims_are_small_and_gzipped() -> None:
    for path in sorted(FIXTURES.glob("*.spec.json.gz")):
        assert path.stat().st_size < 200_000, path.name
        assert gzip.decompress(path.read_bytes())[:1] == b"{"


@pytest.mark.parametrize("connector", sorted(load_lock().contracts))
def test_every_vendor_search_passes_its_native_query_to_the_shared_evaluator(connector: str) -> None:
    """Each connector serves at least one vendor query (JQL, CQL, SOQL, an encoded query, OData, KQL, Drive's q,
    Slack's modifiers) into a search tool whose language the shared evaluator parses."""

    from worldloom.connectors.query import tool_language

    definition = load_connector_definition(connector)
    native = []
    for entry in load_mapping(connector).operations.values():
        if "query" not in entry.args:
            continue
        for tool in entry.tools:
            if definition.tool(definition.canonical_tool(tool)).op == "search":
                assert tool_language(definition, tool) is not None, f"{entry.operation_id}: {tool} has no parsed language"
                native.append(entry.operation_id)
    assert native, f"{connector} serves no vendor query through the evaluator"


def test_coverage_counts_come_from_the_mapping_and_the_lock() -> None:
    rows = {row.connector: row for row in coverage()}
    assert [row.connector for row in coverage()][:len(REFERENCE_CONNECTORS)] == list(REFERENCE_CONNECTORS)
    for name, contract in load_lock().contracts.items():
        mapping = load_mapping(name)
        row = rows[name]
        assert row.modelled is not None and row.unmodelled is not None
        assert row.modelled + row.unmodelled == contract.profiled_operations == len(mapping.operations)
        assert row.modelled == sum(1 for entry in mapping.operations.values() if entry.unmodelled is None)
