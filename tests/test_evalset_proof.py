"""Solvable case sets: the vendor engine by default, gold-plan proofs, and the pins a run checks.

A pilot's call errors were mostly valid vendor queries the old predicate
parser refused, and nothing said, before an agent was graded, that each case
could be solved at all. These tests hold the three answers to that: the
vendor evaluator is the default engine and each search tool says what its
query language is; ``evalrun prove`` replays each case's gold DAG and names
the first node that makes it unsolvable; and a case set carries the pins its
proof rests on, which ``evalrun run`` checks, re-proving when one moved.
"""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_data import ConnectorRecord
from worldloom.connector_definition import (
    builtin_connector_definitions,
    load_connector_definition,
)
from worldloom.connector_emulator import ConnectorEmulator, ConnectorError
from worldloom.connectors.anvil import load_mapping
from worldloom.connectors.query.docs import describe, query_help
from worldloom.corpus import write_jsonl
from worldloom.enterprise_rows import runtime_records
from worldloom.evalrun import case_from_row, service_for
from worldloom.evalrun.anvil import AnvilServing, find_anvil
from worldloom.evalrun.corners import write_case_set
from worldloom.evalrun.proof import (
    PROOF_FILE,
    Unsolvable,
    anvil_request,
    environment_pins,
    gate,
    pin_changes,
    prove_cases,
    read_proof,
)
from worldloom.evalrun.results import compare, read_run

runner = CliRunner()


# -- the vendor engine is the default ------------------------------------------------------


def _emulator(connector: str, records: list[ConnectorRecord]) -> ConnectorEmulator:
    return ConnectorEmulator(load_connector_definition(connector), runtime_records(records))


def test_valid_vendor_queries_the_old_parser_refused_now_run_by_default() -> None:
    salesforce = _emulator("salesforce", [
        ConnectorRecord(id=f"sf-{n}", connector="salesforce", entity="account", external_id=f"001{n:015d}",
                        title=f"Account {n}", fields={"name": f"Account {n}", "modified_at": f"2026-0{n}-01T00:00:00Z"})
        for n in range(1, 5)])
    assert salesforce.query_engine == "native"
    page = salesforce.call("query", query="SELECT Id, Name FROM Account ORDER BY LastModifiedDate DESC LIMIT 50")
    assert page["total"] == 4
    assert [item["Name"] for item in page["items"]] == ["Account 4", "Account 3", "Account 2", "Account 1"]
    # The historical parser refused the same query outright.
    legacy = ConnectorEmulator(salesforce.definition, list(salesforce.records.values()), query_engine="predicate")
    with pytest.raises(ConnectorError):
        legacy.call("query", query="SELECT Id, Name FROM Account ORDER BY LastModifiedDate DESC LIMIT 50")
    snow = _emulator("servicenow", [
        ConnectorRecord(id=f"inc-{n}", connector="servicenow", entity="incident", external_id=f"INC000000{n}",
                        title=f"Case {n}", fields={"priority": str(n % 2 + 1), "short_description": f"Case {n}"})
        for n in range(1, 4)])
    assert snow.call("search_records", query="priority=1^ORDERBYnumber")["total"] == 1
    assert snow.call("search_records", query="priority=2^ORDERBYDESCnumber")["total"] == 2
    jira = _emulator("jira", [
        ConnectorRecord(id=f"j-{n}", connector="jira", entity="task", external_id=f"OPS-{n}", title=f"Issue {n}",
                        fields={"project": "OPS" if n % 2 else "PHX", "summary": f"Issue {n}", "status": "open"})
        for n in range(1, 5)])
    assert jira.call("search_issues", query="project = PHX OR project = OPS ORDER BY created DESC")["total"] == 4
    assert jira.call("search_issues", query="text ~ \"Issue 3\"")["total"] >= 1


def test_every_search_tool_states_its_query_language_and_its_examples_run() -> None:
    free_text = {"jql": "text ~", "cql": "text ~", "encoded_query": "123TEXTQUERY321=",
                 "drive_q": "fullText contains", "kql": "bare terms", "soql": "LIKE"}
    seen: set[str] = set()
    for name, definition in sorted(builtin_connector_definitions().items()):
        emulator = ConnectorEmulator(definition, [])
        for tool, declared in sorted(definition.tools.items()):
            help = query_help(definition, tool)
            if "query" not in declared.params and "predicate" not in declared.params:
                assert help is None
                continue
            assert help is not None and help["grammar"] and help["free_text"] and 2 <= len(help["examples"]) <= 3, tool
            seen.add(help["language"])
            if help["language"] in free_text:
                assert free_text[help["language"]] in help["free_text"], (name, tool)
            for example in help["examples"]:
                # Every example the agent is shown runs through the evaluator.
                if help["argument"] == "query":
                    emulator.call(tool, query=example)
                else:
                    emulator.call(tool, predicate=json.loads(example))
            assert help["name"] in describe(help)
    assert {"jql", "soql", "encoded_query", "odata", "cql", "kql", "drive_q", "slack_search", "predicate"} <= seen


def test_the_tool_catalog_carries_the_query_help() -> None:
    case = case_from_row(_row())
    service = service_for((case,), _records())
    begun = service.begin("agent", case.id)
    catalog = {tool["name"]: tool for tool in service.tool_catalog("agent", begun["run_id"])}
    assert catalog["jira.search_issues"]["query"]["language"] == "jql"
    assert "cf[10231]" in catalog["jira.search_issues"]["query"]["fields"]
    assert "query" not in catalog["jira.transition_issue"]


# -- proving a case set ------------------------------------------------------------------


def _records() -> list[ConnectorRecord]:
    issues = [("task", "open"), ("bug", "todo"), ("story", "review")]
    jira = [ConnectorRecord(id=f"rec-{n}", connector="jira", entity=entity, external_id=f"OPS-{n}",
                            title=f"Issue {n} vendor onboarding",
                            fields={"status": status, "project": "OPS", "summary": f"Issue {n} vendor onboarding"})
            for n, (entity, status) in enumerate(issues, start=1)]
    snow = [ConnectorRecord(id="snow-1", connector="servicenow", entity="incident", external_id="INC0000001",
                            title="Payment run failed", fields={"priority": "1", "state": "new"})]
    return [*jira, *snow]


def _row(*, find: dict[str, Any] | None = None, move: dict[str, Any] | None = None, case_id: str = "triage") -> dict[str, Any]:
    nodes = [
        {"id": "find", "server": "jira", "tool": "search_issues", "fixture": "rec-1", "entity": "task", "op": "search",
         "payload": {"predicate": {"id": ["in", ["rec-1"]]}, "max_results": 5}, "expected_reads": ["rec-1"],
         **(find or {})},
        {"id": "move", "server": "jira", "tool": "transition_issue", "fixture": "rec-1", "entity": "task",
         "op": "transition", "payload": {"state": "review"}, **(move or {})},
    ]
    fixture = nodes[1]["fixture"]
    return {"id": case_id, "query": "Find the open vendor onboarding task in OPS and move it to review.",
            "expected_dag": {"nodes": nodes, "edges": [["find", "move"]]},
            "assertions": [{"type": "tool_called", "node": node["id"]} for node in nodes]
            + [{"type": "order", "before": "find", "after": "move"},
               {"type": "state_equals", "node": "move", "fixture": fixture, "field": "status", "state": "review"}]}


def test_a_sound_case_proves_solvable_with_every_score_at_one() -> None:
    report = prove_cases((case_from_row(_row()),), _records())
    proof = report.cases[0]
    assert report.unsolvable == 0 and proof.solvable and proof.failure is None, proof.failures
    assert proof.scores["plan"] == proof.scores["trajectory"] == proof.scores["outcomes"] == 1.0
    assert report.query_engine == "native"
    assert set(report.pins) >= {"corpus", "connectors", "query_engine", "query_data", "grader", "serving"}
    assert report.pins["connectors"].keys() == {"jira"}


def test_a_gold_query_on_a_field_the_vendor_does_not_have_is_refused_with_the_vendors_error() -> None:
    case = case_from_row(_row(find={"payload": {"predicate": {"bogus_field": "x"}, "max_results": 5}}))
    proof = prove_cases((case,), _records()).cases[0]
    assert not proof.solvable and proof.failure is not None
    assert (proof.failure.node, proof.failure.check) == ("find", "query.field")
    assert "Field 'bogus_field' does not exist" in proof.failure.reason
    assert "jql `" in proof.failure.reason


def test_evidence_no_query_can_reach_is_refused_at_its_node() -> None:
    # The evidence is a ServiceNow incident; the node searches Jira.
    case = case_from_row(_row(find={"expected_reads": ["snow-1"]}))
    proof = prove_cases((case,), _records()).cases[0]
    assert not proof.solvable and proof.failure is not None
    assert proof.failure.node == "find" and proof.failure.check == "query.evidence"
    assert "snow-1" in proof.failure.reason
    assert any(item.check == "read.evidence" and "snow-1" in item.reason for item in proof.failures)


def test_a_write_whose_target_does_not_exist_is_refused_at_the_write() -> None:
    case = case_from_row(_row(move={"fixture": "rec-404"}))
    proof = prove_cases((case,), _records()).cases[0]
    assert not proof.solvable and proof.failure is not None
    assert (proof.failure.node, proof.failure.check) == ("move", "write.error")
    assert "jira.transition_issue" in proof.failure.reason and "rec-404" in proof.failure.reason


def test_the_proof_is_deterministic() -> None:
    cases = (case_from_row(_row()), case_from_row(_row(move={"fixture": "rec-404"}, case_id="broken")))
    first, again = prove_cases(cases, _records()), prove_cases(cases, _records())
    assert first.model_dump() == again.model_dump() and first.digest == again.digest


# -- the command -------------------------------------------------------------------------


def _case_set(directory: Path, rows: list[dict[str, Any]], records: list[ConnectorRecord] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    write_jsonl(directory / "evalrun-cases.jsonl", [case_from_row(row) for row in rows])
    write_jsonl(directory / "records.jsonl", records if records is not None else _records())
    return directory


def test_prove_prints_each_verdict_and_exits_one_when_a_case_is_unsolvable(tmp_path: Path) -> None:
    cases = _case_set(tmp_path / "cases", [_row(), _row(move={"fixture": "rec-404"}, case_id="broken")])
    text = runner.invoke(app, ["evalrun", "prove", str(cases)])
    assert text.exit_code == 1, text.output
    assert "1 of 2 case(s) solvable" in text.output
    assert "ok   triage" in text.output
    assert "FAIL broken node move [write.error]" in text.output
    as_json = runner.invoke(app, ["evalrun", "prove", str(cases), "--json", "--record"])
    assert as_json.exit_code == 1
    document = json.loads(as_json.output)
    assert document["unsolvable"] == 1 and document["reasons"] == {"write.error": 1}
    broken = next(item for item in document["cases"] if item["case_id"] == "broken")
    assert broken["failure"]["node"] == "move"
    recorded = read_proof(cases)
    assert recorded is not None and recorded.digest == document["digest"]


def test_prove_through_anvil_skips_the_anvil_half_without_an_anvil_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORLDLOOM_ANVIL", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    cases = _case_set(tmp_path / "cases", [_row()])
    contract = tmp_path / "contract"
    contract.mkdir()
    result = runner.invoke(app, ["evalrun", "prove", str(cases), "--connectors", "anvil", "--contract", f"jira={contract}"])
    assert result.exit_code == 0, result.output
    assert "skipped: anvil: no Anvil CLI" in result.output and "1 of 1 case(s) solvable" in result.output


def test_a_gold_call_becomes_the_vendor_request_its_contract_operation_takes() -> None:
    mapping = load_mapping("jira")
    search = anvil_request(mapping, "search_issues", {"entity": "task", "predicate": {"id": ["in", ["rec-1"]]},
                                                      "max_results": 5}, None, "jira")
    assert (search["method"], search["path"]) == ("POST", "/rest/api/2/search/jql")
    assert "rec-1" in search["body"]["jql"] and search["body"]["maxResults"] == 5
    move = anvil_request(mapping, "transition_issue", {"id": "OPS-1", "state": "review"}, None, "jira")
    assert (move["method"], move["path"], move["body"]) == ("POST", "/rest/api/2/issue/OPS-1/transitions",
                                                            {"transition": {"id": "31"}})
    got = anvil_request(mapping, "get_issue", {"id": "OPS-3", "fields": ["summary", "status"]}, None, "jira")
    assert (got["path"], got["query"]) == ("/rest/api/2/issue/OPS-3", {"fields": "summary,status"})
    with pytest.raises(ValueError, match="no modelled contract operation"):
        anvil_request(mapping, "create_sprint", {"entity": "sprint", "name": "S1"}, None, "jira")


# -- writers refuse unsolvable sets ------------------------------------------------------


def test_a_case_set_writer_refuses_unsolvable_cases_or_drops_them_with_the_reason(tmp_path: Path) -> None:
    good, broken = case_from_row(_row()), case_from_row(_row(move={"fixture": "rec-404"}, case_id="broken"))
    with pytest.raises(Unsolvable, match="1 of 2 case"):
        write_case_set(tmp_path / "refused", [good, broken], _records())
    assert not (tmp_path / "refused").exists()
    written = write_case_set(tmp_path / "dropped", [good, broken], _records(), drop_unsolvable=True)
    proof = read_proof(written)
    assert proof is not None and [item.case_id for item in proof.cases] == ["triage"]
    assert [(item.case_id, item.failure.node if item.failure else None) for item in proof.dropped] == [("broken", "move")]
    lines = (written / "evalrun-cases.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["triage"]


def test_the_enterprise_build_refuses_unsolvable_cases_and_drops_them_on_request(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = ["enterprise-evals", "build", "examples/retail-close", "--exhaustive", "--limit", "40", "--dag-shape", "*"]
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    refused = runner.invoke(app, [*args[:3], str(tmp_path / "refused"), *args[3:]])
    assert refused.exit_code == 2, refused.output
    envelope = json.loads(refused.stderr.strip().splitlines()[-1])
    assert envelope["refusal"] == "cases_unsolvable" and envelope["data"]["unsolvable"] >= 1
    assert "node " in envelope["message"] and not (tmp_path / "refused").exists()
    monkeypatch.delenv("WORLDLOOM_OUTPUT")

    built = runner.invoke(app, [*args[:3], str(tmp_path / "cases"), *args[3:], "--drop-unsolvable"])
    assert built.exit_code == 0, built.output
    proof = read_proof(tmp_path / "cases")
    assert proof is not None and proof.dropped and proof.unsolvable == 0
    assert all(item.failure is not None and item.failure.node and item.failure.reason for item in proof.dropped)
    written = (tmp_path / "cases" / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(written) == len(proof.cases) == 40 - len(proof.dropped)
    summary = json.loads(built.stdout.strip().splitlines()[-1])
    assert summary["proof"] == {"solvable": len(proof.cases), "dropped": len(proof.dropped), "digest": proof.digest}

    # The written corpus proves, and a run over it trusts the record: no warning, the proof pinned.
    assert runner.invoke(app, ["evalrun", "prove", str(tmp_path / "cases")]).exit_code == 0
    run = runner.invoke(app, ["evalrun", "run", str(tmp_path / "cases"), "-o", str(tmp_path / "run"), "--limit", "3"])
    assert run.exit_code == 0 and "warning" not in run.output, run.output
    assert json.loads((tmp_path / "run" / "run.json").read_text(encoding="utf-8"))["pins"]["proof"] == proof.digest


# -- pins --------------------------------------------------------------------------------


def _run(cases: Path, out: Path) -> Any:
    return runner.invoke(app, ["evalrun", "run", str(cases), "-o", str(out)])


def test_a_set_without_a_proof_record_still_runs_with_a_warning(tmp_path: Path) -> None:
    cases = _case_set(tmp_path / "old", [_row()])
    result = _run(cases, tmp_path / "run")
    assert result.exit_code == 0, result.output
    assert "carries no proof record" in result.output
    header = json.loads((tmp_path / "run" / "run.json").read_text(encoding="utf-8"))
    assert header["pins"]["query_engine"] == "native" and header["pins"]["proof"]


def test_equal_pins_trust_the_record_and_a_moved_pin_reproves_or_refuses(tmp_path: Path) -> None:
    cases = write_case_set(tmp_path / "cases", [case_from_row(_row())], _records())
    recorded = read_proof(cases)
    assert recorded is not None and (cases / PROOF_FILE).is_file()

    first = _run(cases, tmp_path / "first")
    assert first.exit_code == 0, first.output
    assert "warning" not in first.output
    pins = json.loads((tmp_path / "first" / "run.json").read_text(encoding="utf-8"))["pins"]
    assert pins["proof"] == recorded.digest

    # A record nothing reads moves the corpus pin: re-proved, still solvable, runs.
    write_jsonl(cases / "records.jsonl", [*_records(), ConnectorRecord(
        id="rec-9", connector="jira", entity="task", external_id="OPS-9", title="Unrelated", fields={"status": "open"})])
    second = _run(cases, tmp_path / "second")
    assert second.exit_code == 0, second.output
    assert "proof was stale (corpus changed)" in second.output
    moved = json.loads((tmp_path / "second" / "run.json").read_text(encoding="utf-8"))["pins"]
    assert moved["proof"] != recorded.digest and moved["corpus"] != pins["corpus"]

    # Runs under different pins are never judged against each other.
    comparison = compare(read_run(tmp_path / "first"), read_run(tmp_path / "second"))
    assert comparison.pins_mismatch == ("corpus", "proof")
    assert not comparison.improvements and not comparison.regressions
    assert all(item.verdict == "incomparable" for item in comparison.deltas)

    # The task the gold reads is now a story: the set no longer proves, and the run is refused.
    broken = [record.model_copy(update={"entity": "story"}) if record.id == "rec-1" else record for record in _records()]
    write_jsonl(cases / "records.jsonl", broken)
    third = _run(cases, tmp_path / "third")
    assert third.exit_code == 2, third.output
    assert "proof is stale (corpus changed)" in third.output
    assert "triage at node find" in third.output


def test_pins_name_what_moved() -> None:
    case = case_from_row(_row())
    definitions = {"jira": load_connector_definition("jira")}
    live = environment_pins((case,), _records(), definitions=definitions)
    assert pin_changes(live, live) == ()
    edited = definitions["jira"].model_copy(update={"clock": "2030-01-01T00:00:00+00:00"})
    assert pin_changes(live, environment_pins((case,), _records(), definitions={"jira": edited})) == ("connectors.jira",)
    assert pin_changes(live, {**live, "query_engine": "predicate"}) == ("query_engine",)
    verdict = gate(None, (case,), _records(), definitions=definitions)
    assert verdict.status == "unrecorded" and verdict.refusal is None and verdict.pins["proof"]


# -- through Anvil -----------------------------------------------------------------------


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


@pytest.mark.skipif(ANVIL is None, reason="needs the Anvil CLI (set WORLDLOOM_ANVIL) and node")
def test_the_gold_trajectory_proves_through_anvil_as_it_does_in_process(tmp_path: Path) -> None:
    assert ANVIL is not None
    fixtures = Path(__file__).parent / "fixtures" / "anvil"
    spec = tmp_path / "jira.spec.json"
    spec.write_bytes(gzip.decompress((fixtures / "jira.spec.json.gz").read_bytes()))
    done = subprocess.run([*ANVIL, "compile", str(spec), "--root", str(tmp_path), "--manifest",
                           str(fixtures / "jira.anvil.yaml"), "--service", "jira", "--out", str(tmp_path / "jira")],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    serving = AnvilServing({"jira": tmp_path / "jira"}, command=ANVIL, workdir=tmp_path / "served")
    report = prove_cases((case_from_row(_row()),), _records(), anvil=serving)
    assert report.serving == "anvil" and report.unsolvable == 0, report.cases[0].failures
    assert report.pins["serving"]["connectors"] == "anvil" and report.pins["serving"]["mappings"]["jira"]
    assert report.pins["serving"]["contracts"] == serving.identity()["contracts"]
    # A gold call the contract does not model is refused at its node, through Anvil.
    unmapped = case_from_row(_row(move={"tool": "update_sprint", "entity": "sprint", "op": "update",
                                        "payload": {"fields": {"goal": "x"}}}, case_id="sprint"))
    broken = prove_cases((unmapped,), _records(), anvil=serving).cases[0]
    assert not broken.solvable, broken
    assert any(item.check == "anvil.unmapped" and item.node == "move" for item in broken.failures), broken.failures



# -- one identity for a rendered file --------------------------------------------------------


def test_a_rendered_file_is_served_under_the_name_its_snapshot_carries() -> None:
    """A Drive or SharePoint file's `name` is its file name, served and snapshotted alike.

    The served emulator used to name a `ConnectorRecord` by its title while a
    compiled row's snapshot named it by `fields.name`; on a rendered file the
    two differ, so every search over one graded `result_mismatch` for the
    reference agent itself.
    """
    record = ConnectorRecord(id="CONN-DRIVE-1", connector="drive", entity="docx", external_id="d1",
                             title="Close calendar", fields={"name": "art-0001-close-calendar.docx", "format": "docx"})
    served = ConnectorEmulator(load_connector_definition("drive"), [record]).call("get_file", id="CONN-DRIVE-1")
    assert served["name"] == runtime_records([record])[0]["name"] == "art-0001-close-calendar.docx"
    untitled = record.model_copy(update={"fields": {"format": "docx"}})
    assert ConnectorEmulator(load_connector_definition("drive"), [untitled]).call("get_file", id="CONN-DRIVE-1")["name"] \
        == "Close calendar"


def test_cases_over_a_rendered_world_prove_without_a_result_mismatch() -> None:
    from worldloom import RetailWorld
    from worldloom.enterprise_sdk import EnterpriseEvalHarness
    from worldloom.evalrun import cases_from_corpus
    from worldloom.scenarios import MonthEndClose

    world = (RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03", include_operational_incident=True))
             .render("docx", "xlsx"))
    built, _ = EnterpriseEvalHarness.from_world(world).take(200).with_dag_grammar().build()
    renamed = {record.id for record in built.connector_data.records
               if record.connector in {"drive", "sharepoint"} and record.fields.get("name") not in (None, record.title)}
    cases = cases_from_corpus(built)
    reading = [case for case in cases for snapshot in case.row.get("input_snapshots", {}).values()
               if renamed & set(snapshot)]
    assert renamed and reading, "the build must read a rendered file for this to test anything"
    report = prove_cases(cases, built.connector_data.records)
    mismatched = [(item.case_id, failure.reason) for item in report.cases for failure in item.failures
                  if "result_mismatch" in failure.reason]
    assert mismatched == []



# -- failure ownership reads the proof ----------------------------------------------------


def test_an_unsolvable_cases_findings_are_the_worlds_by_the_recorded_proof(tmp_path: Path) -> None:
    from worldloom.evalrun.ownership import read_proofs

    cases = _case_set(tmp_path / "cases", [_row(), _row(move={"fixture": "rec-404"}, case_id="broken")])
    assert runner.invoke(app, ["evalrun", "prove", str(cases), "--record"]).exit_code == 1
    proofs = read_proofs(cases)
    assert proofs["broken"]["solvable"] is False and proofs["triage"]["solvable"] is True
    assert read_proofs(cases / PROOF_FILE) == proofs and read_proofs(tmp_path) == {}

    run = runner.invoke(app, ["evalrun", "run", str(cases), "-o", str(tmp_path / "run")])
    assert run.exit_code == 0, run.output
    result = runner.invoke(app, ["evalrun", "autopsy", str(tmp_path / "run"), "--proofs", str(cases), "--json"])
    assert result.exit_code == 0, result.output
    owned = [item for item in json.loads(result.stdout)["ownership"]["attributions"] if item["case_id"] == "broken"]
    assert owned and {(item["owner"], item["rule"]) for item in owned} == {("world", "world.proof")}
    assert all("node move, write.error" in item["evidence"][0] for item in owned)
