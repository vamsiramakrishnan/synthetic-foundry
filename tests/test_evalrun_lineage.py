"""Plans as data flow: lineage from the call trace, and the executed DAG graded edge by edge.

Each test runs an agent through the real tool surface over a small built
corpus and reads what the plan stage attached. A call depends on an earlier
call when a value that call returned reappears in its arguments; ordering
alone is never a dependency. So an agent that chains through the ids its
reads returned carries every gold edge, one that hardcodes an id it never saw
is missing the edge however early the read ran, and two independent reads run
one after the other are an efficiency finding, not an error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import packkit
from worldloom.cli import app
from worldloom.connector_definition import load_connector_definition
from worldloom.evalrun import (
    AgentResponse,
    CallableAgent,
    ReferenceAgent,
    ScriptedAgent,
    case_from_row,
    cases_from_corpus,
    derive_lineage,
    grade_plan_nodes,
    read_run,
    run_case,
    run_cases,
    service_for,
    summarize,
    write_run,
)
from worldloom.evalrun.lineage import consumed_values, distinctive, produced_values
from worldloom.evalrun.program import ProgramAgent, client_source, declared_from_program

# These tests script agents in the connector definitions' own tool names
# (`jira.get_issue`), so they serve those tools; the contract surface is the default.
pytestmark = pytest.mark.usefixtures("native_surface")

runner = CliRunner()


def _records() -> list[dict[str, Any]]:
    out = []
    for index in range(1, 7):
        hot = index == 1
        out.append({"fid": f"i{index}", "server": "servicenow", "entity": "incident", "ident": f"INC100000{index}",
                    "state": "new" if hot else "closed", "priority": "1" if hot else "3",
                    "short_description": f"Pump failure at site {index}", "caller_id": "u1",
                    "sys_created_on": "2026-09-01T09:00:00+08:00"})
    return out


QUERY = "Find the new priority-one incident, move it to open, then read it back to confirm."


def _row() -> dict[str, Any]:
    """search -> update (the id the search returned) -> verify (the record the update wrote)."""

    return {
        "id": "triage", "query": QUERY,
        "expected_dag": {"nodes": [
            {"id": "find", "server": "servicenow", "tool": "search_records", "entity": "incident",
             "node_kind": "search", "op": "search", "payload": {"predicate": {"state": "new"}}, "fixture": "i1",
             "expected_reads": ["i1"]},
            {"id": "move", "server": "servicenow", "tool": "update_record", "entity": "incident", "op": "update",
             "fixture": "i1", "bindings": {"id": {"node": "find", "path": ["id"], "select": "first", "encoding": "value"}}},
            {"id": "check", "server": "servicenow", "tool": "get_record", "entity": "incident", "op": "readback",
             "fixture": "i1", "bindings": {"id": {"node": "move", "path": ["id"], "select": "first", "encoding": "value"}}},
        ], "edges": [["find", "move"], ["move", "check"]]},
        "assertions": [{"type": "tool_called", "node": node} for node in ("find", "move", "check")]
        + [{"type": "state_equals", "node": "move", "fixture": "i1", "state": "open"}],
    }


def _parallel_row() -> dict[str, Any]:
    """Two independent searches feeding one draft; only the first one's records are bound into it."""

    return {
        "id": "digest", "query": "Find the new and the closed incidents and draft a digest of the new ones.",
        "expected_dag": {"nodes": [
            {"id": "open", "server": "servicenow", "tool": "search_records", "entity": "incident",
             "node_kind": "search", "op": "search", "payload": {"predicate": {"state": "new"}}, "expected_reads": ["i1"]},
            {"id": "closed", "server": "servicenow", "tool": "search_records", "entity": "incident",
             "node_kind": "search", "op": "search", "payload": {"predicate": {"state": "closed"}},
             "expected_reads": ["i2", "i3", "i4", "i5", "i6"]},
            {"id": "write", "server": "email", "tool": "create_draft", "entity": "message", "node_kind": "write",
             "op": "create", "payload": {"name": "digest", "fields": {"subject": "digest"}},
             "bindings": {"fields.evidence": {"node": "open", "path": [], "select": "all", "encoding": "value"}}},
        ], "edges": [["open", "write"], ["closed", "write"]]},
        "assertions": [{"type": "tool_called", "node": node} for node in ("open", "closed", "write")],
    }


def _definitions() -> dict[str, Any]:
    return {"servicenow": load_connector_definition("servicenow"), "email": load_connector_definition("email")}


def _service(*cases: Any) -> Any:
    return service_for(cases, _records(), definitions=_definitions())


def _search(**predicate: Any) -> tuple[str, dict[str, Any]]:
    return ("servicenow.search_records", {"entity": "incident", "predicate": predicate})


def _chaining(task: Any, tools: Any) -> AgentResponse:
    found = tools.call("servicenow.search_records", entity="incident", predicate={"state": "new"})
    sys_id = found["items"][0]["sys_id"]
    moved = tools.call("servicenow.update_record", id=sys_id, fields={"state": "open"})
    tools.call("servicenow.get_record", id=moved["sys_id"])
    return AgentResponse(answer=f"{found['items'][0]['number']} is open.")


def _run(agent: Any, row: dict[str, Any] | None = None) -> Any:
    case = case_from_row(row or _row())
    result = run_case(_service(case), case, agent)
    assert result.graded and result.score is not None, result.error
    return result


# -- the lineage rules --------------------------------------------------------------------


def test_the_distinctiveness_rule() -> None:
    assert distinctive("OPS-1") and distinctive("INC1000001") and distinctive("ana@example.com")
    assert distinctive("9ce88802f07591e5ce0457ef51ece021") and distinctive("12345")
    assert distinctive("Quarterly vendor onboarding review")
    for common in ("1", "31", "2026", "new", "In Progress", "true", "2026-09-01T09:00:00+08:00", "2026-09-01"):
        assert not distinctive(common), common
    # A value most items of a listing share is an attribute, not an identity.
    listing = {"items": [{"id": f"REC-{n}", "assignee": "owner-7"} for n in range(4)]}
    produced = produced_values(listing)
    assert "REC-2" in produced and "owner-7" not in produced
    # Inside a native query and a URL path, the literal values are what a call consumed.
    jql = consumed_values({"query": 'project = OPS AND key = "OPS-12"'}, tool="jira.search_issues",
                          definitions={"jira": load_connector_definition("jira")})
    assert "OPS-12" in jql
    assert "OPS-7" in consumed_values({"path": "/rest/api/2/issue/OPS-7/transitions"})


def test_a_value_the_request_states_is_not_a_dependency() -> None:
    spans = [
        {"id": "s1", "tool": "jira.search_issues", "args": {}, "result": {"items": [{"key": "OPS-42"}]}, "reads": [],
         "writes": [], "error": None},
        {"id": "s2", "tool": "jira.get_issue", "args": {"id": "OPS-42"}, "reads": [], "writes": [], "error": None},
    ]
    linked = derive_lineage(spans, query="Look at the incident queue.")
    assert linked.consumed_from()["s2"] == ("s1",)
    stated = derive_lineage(spans, query="Read OPS-42 and summarise it.")
    assert stated.consumed_from()["s2"] == () and stated.spans[1].stated == 1


def test_the_most_recent_producer_wins_and_the_others_are_alternatives() -> None:
    spans = [
        {"id": "s1", "tool": "jira.search_issues", "args": {}, "result": {"items": [{"key": "OPS-42"}]}, "error": None},
        {"id": "s2", "tool": "jira.get_issue", "args": {"id": "OPS-42"}, "result": {"key": "OPS-42"}, "error": None},
        {"id": "s3", "tool": "jira.update_issue", "args": {"id": "OPS-42"}, "result": {}, "error": None},
    ]
    link = derive_lineage(spans).spans[2].links[0]
    assert (link.producer, link.alternatives) == ("s2", ("s1",))


def test_a_later_page_depends_on_the_page_before_it() -> None:
    spans = [
        {"id": f"s{n + 1}", "tool": "servicenow.search_records", "error": None, "result": {"items": []},
         "args": {"entity": "incident", "predicate": {"state": "new"}, "start_at": n, "max_results": 1}}
        for n in range(3)
    ]
    parents = derive_lineage(spans).consumed_from()
    assert parents == {"s1": (), "s2": ("s1",), "s3": ("s2",)}
    assert derive_lineage(spans).spans[2].links[0].via == "page"


def test_lineage_reads_what_the_agent_saw_when_the_call_was_served_over_http() -> None:
    # The replay's span carries connector arguments; the agent sent a vendor
    # path. Lineage reads the observation, so the link is the agent's own.
    spans = [
        {"id": "s1", "tool": "jira.search_issues", "args": {"query": "x"}, "result": {"items": []}, "error": None},
        {"id": "s2", "tool": "jira.transition_issue", "args": {"state": "review"}, "result": {}, "error": None},
    ]
    observed = {"s1": {"request": {"path": "/rest/api/2/search/jql"}, "response": {"issues": [{"key": "OPS-5"}]}},
                "s2": {"request": {"path": "/rest/api/2/issue/OPS-5/transitions", "body": {"transition": {"id": "31"}}}}}
    assert derive_lineage(spans).consumed_from()["s2"] == ()
    assert derive_lineage(spans, observations=observed).consumed_from()["s2"] == ("s1",)


# -- (a) chaining through returned ids ----------------------------------------------------------


def test_an_agent_that_chains_through_returned_ids_carries_every_gold_edge() -> None:
    result = _run(CallableAgent(_chaining, name="chain"))
    dag = result.score.plan.nodes.dag
    assert dag is not None
    assert (dag.edge_precision, dag.edge_recall, dag.findings) == (1.0, 1.0, ())
    assert dag.honoured == dag.gold_data_edges == 2 and dag.unsourced == 0
    # The ledger's consumed_from is the data-flow lineage.
    assert [span["consumed_from"] for span in result.spans] == [[], ["s1"], ["s2"]]
    assert [edge.via for edge in dag.executed.edges] == [("record",), ("record",)]
    assert dag.executed.depth == 3 and dag.executed.steps == 3


# -- (b) a hardcoded id is a missing dependency ---------------------------------------------------


def test_an_id_the_agent_could_not_have_known_is_a_missing_dependency() -> None:
    # The search it ran returned the closed incidents; the id it wrote to came from nowhere.
    blind = ScriptedAgent([_search(state="closed"),
                           ("servicenow.update_record", {"id": "INC1000001", "fields": {"state": "open"}}),
                           ("servicenow.get_record", {"id": "INC1000001"})])
    result = _run(blind)
    dag = result.score.plan.nodes.dag
    assert ("find", "move") in dag.missing and "plan.edge_missing" in dag.findings
    assert dag.unsourced >= 1
    assert result.spans[1]["consumed_from"] == []
    # The readback still consumed the record the update wrote.
    assert ("move", "check") not in dag.missing
    assert "plan.edge_missing" in result.score.model_dump()["plan"]["nodes"]["dag"]["findings"]


# -- (c) two independent reads run serially ---------------------------------------------------------


def test_independent_reads_run_serially_are_an_efficiency_finding_not_an_error() -> None:
    def digest(task: Any, tools: Any) -> AgentResponse:
        found = tools.call("servicenow.search_records", entity="incident", predicate={"state": "new"})
        tools.call("servicenow.search_records", entity="incident", predicate={"state": "closed"})
        tools.call("email.create_draft", entity="message", name="digest", fields={
            "subject": "digest", "evidence": [{"number": item["number"]} for item in found["items"]]})
        return AgentResponse(answer="Drafted.")

    result = _run(CallableAgent(digest, name="serial"), _parallel_row())
    dag = result.score.plan.nodes.dag
    assert dag.serialised == (("open", "closed"),) and dag.parallelisable == 1
    assert dag.findings == ("plan.serialised",)
    assert dag.edge_recall == 1.0 and dag.missing == () and dag.spurious == ()
    assert result.score.plan.passed and result.score.trajectory.passed
    # Calls the agent issued together (an sdk-program's threads) are one step and not serialised.
    case = case_from_row(_parallel_row())
    together = grade_plan_nodes(case, result.spans, definitions=_definitions(), concurrent=[["s1", "s2"]])
    assert together.dag.serialised == () and together.dag.parallelisable == 1
    assert together.dag.executed.steps == 2


# -- (d) the wrong conditional branch -------------------------------------------------------------------


@pytest.fixture(scope="module")
def conditional_corpus() -> Any:
    from worldloom import RetailWorld
    from worldloom.enterprise_sdk import EnterpriseEvalHarness
    from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
    from worldloom.synthesis.connectors import operational_profile

    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    harness = (EnterpriseEvalHarness.from_world(world).with_scenario(operational_profile("retail"))
               .with_operational_data(Simulator(program, seed=8128),
                                      IncidentRule(table="inventory", signal="lost", title="Stock availability"),
                                      include_world_records=False)
               .exhaustive().take(12).with_dag_grammar("conditional"))
    corpus, _ = harness.build()
    return corpus


class _SwapBranch:
    """The reference's surface, with the conditional write's branch swapped."""

    def __init__(self, tools: Any) -> None:
        self._tools = tools

    def __getattr__(self, name: str) -> Any:
        return getattr(self._tools, name)

    def call(self, tool: str, /, **arguments: Any) -> Any:
        text = json.dumps(arguments)
        if "-write-primary" in text:
            text = text.replace("-write-primary", "-write-fallback")
        elif "-write-fallback" in text:
            text = text.replace("-write-fallback", "-write-primary")
        return self._tools.call(tool, **json.loads(text))


def test_the_branch_the_data_did_not_select_is_the_wrong_branch(conditional_corpus: Any) -> None:
    cases = [case for case in cases_from_corpus(conditional_corpus)
             if case.plan.shape == "conditional" and not case.trajectory.failures]
    assert cases, "the conditional shape plans cases without designed failures"
    service = service_for(cases, conditional_corpus.connector_data.records)
    reference = ReferenceAgent(cases)
    right = run_cases(service, cases, reference)
    for result in right.results:
        dag = result.score.plan.nodes.dag
        assert dag.wrong_branch == () and dag.edge_recall == 1.0, (result.case_id, dag)
    swapped = CallableAgent(lambda task, tools: reference.run(task, _SwapBranch(tools)), name="swapped")
    wrong = run_cases(service, cases, swapped)
    for case, result in zip(cases, wrong.results, strict=True):
        dag = result.score.plan.nodes.dag
        assert "plan.wrong_branch" in dag.findings, (case.id, dag)
        untaken = {node.id for node in case.plan.tool_nodes if node.kind == "write"} - {
            span["node"] for span in right.results[cases.index(case)].spans if span.get("node")}
        assert set(dag.wrong_branch) & untaken


# -- (e) a declared plan that differs from execution -----------------------------------------------------


def _declaring(plan: dict[str, Any]) -> Any:
    def run(task: Any, tools: Any) -> AgentResponse:
        response = _chaining(task, tools)
        return response.model_copy(update={"planned_dag": plan})

    return CallableAgent(run, name="declaring")


def test_the_declared_and_the_executed_dag_are_graded_separately_and_their_divergence_reported() -> None:
    faithful = _run(_declaring({"nodes": [
        {"id": "a", "tool": "servicenow.search_records", "entity": "incident"},
        {"id": "b", "tool": "servicenow.update_record", "depends_on": ["a"]},
        {"id": "c", "tool": "servicenow.get_record", "depends_on": ["b"]}]}))
    nodes = faithful.score.plan.nodes
    assert nodes.source == "declared" and nodes.dag.declared is not None
    assert nodes.dag.declared.agreement == 1.0 and nodes.dag.declared.declared_edge_recall == 1.0
    # Declared a comment it never made, left out the readback it did make, and
    # declared the update independent of the search it in fact consumed.
    drifted = _run(_declaring({"nodes": [
        {"id": "a", "tool": "servicenow.search_records", "entity": "incident"},
        {"id": "b", "tool": "servicenow.update_record"},
        {"id": "n", "tool": "email.create_draft", "depends_on": ["b"]}]}))
    declared = drifted.score.plan.nodes.dag.declared
    assert declared is not None and declared.agreement < 1.0
    assert declared.declared_not_executed == ("n=email:create:*",)
    assert [label.split("=")[0] for label in declared.executed_not_declared] == ["check"]
    assert declared.edges_added == (("find", "move"),)
    assert declared.declared_edge_recall is not None and declared.declared_edge_recall < 1.0
    # The executed DAG is graded on its own: the calls did chain.
    assert drifted.score.plan.nodes.dag.edge_recall == 1.0
    summary = summarize(run_cases(_service(case_from_row(_row())), (case_from_row(_row()),),
                                  _declaring({"nodes": [{"id": "a", "tool": "servicenow.search_records"}]})))
    assert summary.stages is not None and summary.stages.declared_cases == 1
    assert summary.stages.declared_agreement is not None and summary.stages.declared_agreement < 1.0


# -- the axes do not move --------------------------------------------------------------------------------


def _off(tmp_path: Path) -> Any:
    packs = tmp_path / "packs" / "policy"
    packs.mkdir(parents=True, exist_ok=True)
    (packs / "noplan.json").write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "policy", "name": "noplan",
                                                   "body": {"values": {"evalrun.grade.plan_nodes": False}}}))
    return packkit.use("policy:noplan", roots=[tmp_path / "packs"])


def test_lineage_leaves_every_existing_score_byte_identical(conditional_corpus: Any, tmp_path: Path) -> None:
    cases = cases_from_corpus(conditional_corpus)
    agents = [ReferenceAgent(cases), ScriptedAgent([], name="lazy")]
    for agent in agents:
        with _off(tmp_path):
            off = run_cases(service_for(cases, conditional_corpus.connector_data.records), cases, agent)
        on = run_cases(service_for(cases, conditional_corpus.connector_data.records), cases, agent)
        for left, right in zip(off.results, on.results, strict=True):
            assert left.score is not None and right.score is not None
            a, b = left.score.model_dump(mode="json"), right.score.model_dump(mode="json")
            b["plan"].pop("nodes", None)
            assert a == b
            # The spans differ in nothing but the parents lineage wrote into them.
            assert [{**span, "consumed_from": None} for span in left.spans] == \
                [{**span, "consumed_from": None} for span in right.spans]


# -- the sdk-program harness mode ------------------------------------------------------------------------


PROGRAM = '''
import json
import worldloom_client as client

found = client.servicenow.search_records(entity="incident", predicate={"state": "new"})
first = found["items"][0]
moved = client.call("servicenow.update_record", id=first["sys_id"], fields={"state": "open"})
client.servicenow.get_record(id=moved["sys_id"])
print(json.dumps({"answer": first["number"] + " is open."}))
'''


def _writer(tmp_path: Path, program: str) -> str:
    script = tmp_path / "writer.py"
    script.write_text(
        "import json, sys\n"
        "document = json.load(sys.stdin)\n"
        "assert document['schema'] == 'worldloom.evalrun-program/v1'\n"
        "assert 'def search_records' in document['client']['source']\n"
        f"print(json.dumps({{'program': {program!r}}}))\n", encoding="utf-8")
    return f"{sys.executable} {script}"


def test_an_sdk_program_runs_end_to_end_and_its_calls_are_graded_with_lineage(tmp_path: Path) -> None:
    case = case_from_row(_row())
    agent = ProgramAgent(_writer(tmp_path, PROGRAM), program_timeout=60)
    report = run_cases(_service(case), (case,), agent)
    result = report.results[0]
    assert result.graded and result.score is not None, result.error
    assert result.answer == "INC1000001 is open." and result.score.passed
    program = result.program
    assert program is not None and program["exit_code"] == 0 and program["source"] == PROGRAM
    assert program["declared_from"] == "source" and program["concurrent"] == []
    assert [(node["tool"], node["depends_on"]) for node in program["declared"]["nodes"]] == [
        ("servicenow.search_records", []), ("servicenow.update_record", ["p1"]), ("servicenow.get_record", ["p2"])]
    nodes = result.score.plan.nodes
    assert nodes.source == "declared" and nodes.score == 1.0
    assert nodes.dag.edge_recall == 1.0 and nodes.dag.declared.agreement == 1.0
    assert [span["consumed_from"] for span in result.spans] == [[], ["s1"], ["s2"]]
    # The program is on the ledger, for trace review and training export.
    write_run(tmp_path / "run", report)
    assert read_run(tmp_path / "run").results[0].program == program
    assert report.agent_identity["kind"] == "sdk-program"


def test_a_failing_program_is_an_error_row_that_keeps_the_program(tmp_path: Path) -> None:
    case = case_from_row(_row())
    broken = PROGRAM.replace("client.servicenow.get_record", "raise SystemExit(3)  #")
    result = run_case(_service(case), case, ProgramAgent(_writer(tmp_path, broken), program_timeout=60))
    assert result.status == "error" and "program_failed: exit 3" in (result.error or "")
    assert result.program is not None and result.program["exit_code"] == 3 and result.calls == 2


def test_the_declared_dag_is_read_off_the_source_by_variable_flow() -> None:
    tools = ["jira.search_issues", "jira.get_issue", "email.create_draft"]
    source = (
        "import worldloom_client as wl\n"
        "page = wl.jira.search_issues(query='project = OPS')\n"
        "details = []\n"
        "for item in page['issues']:\n"
        "    details.append(wl.jira.get_issue(id=item['key']))\n"
        "other = wl.call('jira.search_issues', query='project = FIN')\n"
        "wl.email.create_draft(entity='message', name='x', fields={'evidence': details})\n"
    )
    declared = declared_from_program(source, tools)
    assert declared is not None
    assert [(node["id"], node["tool"], node["depends_on"], node["entity"]) for node in declared["nodes"]] == [
        ("p1", "jira.search_issues", [], ""), ("p2", "jira.get_issue", ["p1"], ""),
        ("p3", "jira.search_issues", [], ""), ("p4", "email.create_draft", ["p2"], "message")]
    assert declared_from_program("not python (", tools) is None
    assert "def get_issue(self, **arguments)" in client_source([{"name": "jira.get_issue", "op": "get", "params": {"id": {}}}])


def test_the_cli_refuses_an_sdk_program_mode_without_an_exec_child(tmp_path: Path) -> None:
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path), "-o", str(tmp_path / "out"),
                                 "--harness-mode", "sdk-program"])
    assert result.exit_code != 0 and "--exec" in result.output, result.output
    result = runner.invoke(app, ["evalrun", "run", str(tmp_path), "-o", str(tmp_path / "out"), "--exec", "x",
                                 "--harness-mode", "batch"])
    assert result.exit_code != 0 and "turns or sdk-program" in result.output, result.output


def test_the_cli_runs_an_sdk_program_and_keeps_it_on_the_ledger(tmp_path: Path) -> None:
    from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE

    corpus = tmp_path / "cases"
    corpus.mkdir()
    (corpus / CASE_SET_FILE).write_text(case_from_row(_row()).model_dump_json(by_alias=True) + "\n", encoding="utf-8")
    records = [{"id": record["fid"], "connector": "servicenow", "entity": "incident", "external_id": record["ident"],
                "title": record["short_description"],
                "fields": {key: value for key, value in record.items()
                           if key not in {"fid", "server", "entity", "ident", "short_description"}}}
               for record in _records()]
    (corpus / RECORDS_FILE).write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    result = runner.invoke(app, ["evalrun", "run", str(corpus), "-o", str(tmp_path / "run"), "--timeout", "60",
                                 "--exec", _writer(tmp_path, PROGRAM), "--harness-mode", "sdk-program",
                                 "--program-timeout", "60"])
    assert result.exit_code == 0, result.output
    line = json.loads((tmp_path / "run" / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["status"] == "graded", line.get("error")
    assert line["program"]["source"] == PROGRAM and line["program"]["exit_code"] == 0
    assert line["score"]["plan"]["nodes"]["dag"]["edge_recall"] == 1.0
    summary = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["stages"]["edge_recall"] == 1.0 and summary["stages"]["declared_agreement"] == 1.0
