"""The second lever: failures owned by the interface, and an Anvil manifest overlay that fixes them.

The first half needs no Node: it attributes crafted runs to their owners by
the rules in ``evalrun.ownership`` and checks the overlay lint's line-level
surface check. The second half serves a small Jira case set through Anvil
(``anvil simulate serve`` over the trimmed Jira fixture) and is skipped
without ``node`` and a built Anvil CLI: an agent that writes the query
grammar its tool description shows is served a search tool whose
description shows none, so it sends the request's words as JQL and the
vendor refuses them. A proposer adds a grammar description and example to
that one tool; the overlay is recompiled, served, and promoted through the
training gate, ablation, the holdout and the transfer gate, and written out
as a reviewable diff and a simulation-only approvals record.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from worldloom import packkit
from worldloom.connector_data import ConnectorRecord
from worldloom.evalrun import (
    CallableAgent,
    ScriptedAgent,
    case_from_row,
    run_cases,
    service_for,
)
from worldloom.evalrun.agents import AgentResponse
from worldloom.evalrun.anvil import find_anvil
from worldloom.evalrun.autopsy import autopsy, render_brief
from worldloom.evalrun.improve import improve
from worldloom.evalrun.interface import (
    InterfaceLever,
    InterfaceVariant,
    air_findings,
    bundle_hash,
    parse_levers,
    surface_findings,
)
from worldloom.evalrun.ownership import SurfaceFacts, attribute_case, ownership
from worldloom.packkit import diffs

# These tests script agents in the connector definitions' own tool names
# (`jira.get_issue`), so they serve those tools; the contract surface is the default.
pytestmark = pytest.mark.usefixtures("native_surface")

FIXTURES = Path(__file__).parent / "fixtures" / "anvil"
TRANSITIONS = {"todo": "11", "open": "21", "review": "31", "done": "41", "blocked": "51"}
SEARCH_OP = "  searchAndReconsileIssuesUsingJqlPost: { state: approved }\n"
PROJECT_OP = "  getFieldsPaginated: { state: approved }\n"


# -- a small Jira world ------------------------------------------------------------------


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


#: (record, entity, status, severity, target): each a case "find the one issue, move it".
_TRIAGE = [
    (1, "task", "open", "Sev-1", "review"), (2, "bug", "todo", "Sev-2", "open"), (3, "story", "review", "Sev-1", "done"),
    (5, "bug", "open", "Sev-1", "done"), (2, "bug", "todo", "Sev-2", "blocked"), (1, "task", "open", "Sev-1", "done"),
    (3, "story", "review", "Sev-1", "open"), (5, "bug", "open", "Sev-1", "review"),
    (1, "task", "open", "Sev-1", "blocked"), (5, "bug", "open", "Sev-1", "blocked"),
]


def _row(index: int, record: int, entity: str, status: str, severity: str, target: str) -> dict[str, Any]:
    fixture = f"rec-{record}"
    nodes = [
        {"id": "find", "server": "jira", "tool": "search_issues", "fixture": fixture, "entity": entity, "op": "search"},
        {"id": "move", "server": "jira", "tool": "transition_issue", "fixture": fixture, "entity": entity,
         "op": "transition"},
    ]
    return {"id": f"triage-{index:02d}",
            "query": f"Find the {status} {severity} {entity} in OPS and move it to {target}.",
            "expected_dag": {"nodes": nodes, "edges": [["find", "move"]]},
            "assertions": [{"type": "tool_called", "node": node["id"]} for node in nodes]
            + [{"type": "order", "before": "find", "after": "move"},
               {"type": "state_equals", "node": "move", "fixture": fixture, "field": "status", "state": target}]}


def _cases() -> list[Any]:
    return [case_from_row(_row(index, *spec)) for index, spec in enumerate(_TRIAGE, start=1)]


_REQUEST = re.compile(r"Find the (\w+) (Sev-\d) (\w+) in (\w+) and move it to (\w+)\.")


# -- ownership on crafted runs ---------------------------------------------------------


def _in_process(calls: list[tuple[str, dict[str, Any]]], *, answer: str = "done", name: str = "crafted") -> Any:
    cases = _cases()[:1]
    return run_cases(service_for(cases, _records(), query_engine="native"), cases,
                     ScriptedAgent(calls, answer=answer, name=name)), cases[0]


GOOD_JQL = 'project = OPS AND issuetype = task AND status = open AND cf[10231] = "Sev-1"'


def _by_key(items: Any) -> dict[str, tuple[str, str]]:
    return {item.key: (item.owner, item.rule) for item in items}


def test_a_refused_query_grammar_is_the_interfaces_and_what_it_stopped_follows_it() -> None:
    run, case = _in_process([("jira.search_issues", {"query": "open Sev-1 task in OPS"})])
    result = run.results[0]
    owned = _by_key(attribute_case(result, case))
    assert owned["error:validation_error"] == ("interface", "interface.error_code")
    # The search never returned evidence, so the write it would have fed
    # never ran: that follows from the refusal, and names it.
    assert owned["plan.missing:write"] == ("interface", "interface.consequence")
    items = {item.key: item for item in attribute_case(result, case)}
    evidence = " ".join(items["error:validation_error"].evidence)
    assert "open Sev-1 task in OPS" in evidence, evidence


def test_behaviour_is_the_agents_and_serving_errors_and_hidden_tools_are_the_interfaces() -> None:
    run, case = _in_process([("jira.search_issues", {"query": GOOD_JQL})])
    result = run.results[0]
    owned = _by_key(attribute_case(result, case))
    assert owned["plan.missing:write"] == ("agent", "agent.default")
    # The same finding, when the served surface does not expose the tool the node needs.
    hidden = {"jira.search_issues": SurfaceFacts(), "jira.transition_issue": SurfaceFacts(exposed=False)}
    owned = _by_key(attribute_case(result, case, surface=hidden))
    assert owned["plan.missing:write"] == ("interface", "interface.not_exposed")
    errored = result.model_copy(update={"status": "error", "score": None, "error": "anvil: case uses x, which no --contract serves"})
    assert _by_key(attribute_case(errored, case)) == {"run.errored": ("interface", "interface.serving")}
    crashed = result.model_copy(update={"status": "error", "score": None, "error": "RuntimeError: boom"})
    assert _by_key(attribute_case(crashed, case)) == {"run.errored": ("agent", "agent.default")}


def test_a_refused_call_is_the_interfaces() -> None:
    run, case = _in_process([("jira.find_issue", {"q": "x"}), ("jira.search_issues", {"query": GOOD_JQL})])
    owned = _by_key(attribute_case(run.results[0], case))
    assert owned["trajectory.refused_call"] == ("interface", "interface.refused_call")


def test_a_proof_or_the_reference_agent_makes_it_the_worlds() -> None:
    run, case = _in_process([("jira.search_issues", {"query": GOOD_JQL})])
    result = run.results[0]
    proofs = {case.id: {"case_id": case.id, "solvable": False, "reason": "the issue's transition is not in its workflow"}}
    owned = attribute_case(result, case, proofs=proofs)
    assert {item.owner for item in owned} == {"world"} and {item.rule for item in owned} == {"world.proof"}
    assert "not in its workflow" in owned[0].evidence[0]
    partial = {case.id: {"case_id": case.id, "solvable": True, "unreachable": ["move"]}}
    assert _by_key(attribute_case(result, case, proofs=partial))["plan.missing:write"] == ("world", "world.proof")
    reference, _ = _in_process([("jira.search_issues", {"query": GOOD_JQL})], name="reference")
    owned = ownership(run, cases=[case], reference=reference)
    assert {item.rule for item in owned.attributions} == {"world.reference"}


def test_identical_trajectories_scored_differently_are_the_graders() -> None:
    run, case = _in_process([("jira.search_issues", {"query": GOOD_JQL})])
    failed = run.results[0]
    assert failed.score is not None and not failed.score.passed
    flipped = failed.model_copy(update={"score": failed.score.model_copy(update={"passed": True}), "agent": "peer"})
    peer = run.model_copy(update={"results": (flipped,)})
    owned = ownership(run, cases=[case], peers=[peer])
    assert {item.rule for item in owned.attributions} == {"grader.disagreement"}
    # A failed case nothing explains is a grader gap.
    unexplained = failed.model_copy(update={"score": failed.score.model_copy(update={"passed": False})})
    assert _by_key(attribute_case(unexplained, case, keys=["unclassified"])) == {
        "unclassified": ("grader", "grader.unexplained")}


def test_the_autopsy_carries_owner_shares_and_the_brief_prints_them() -> None:
    run, case = _in_process([("jira.search_issues", {"query": "open Sev-1 task in OPS"})])
    plain = autopsy(run, cases=[case])
    assert plain.ownership is None and "ownership" not in plain.model_dump(by_alias=True)
    assert all("owner" not in cluster.model_dump() for cluster in plain.clusters)
    owned = autopsy(run, cases=[case], attribute=True)
    assert owned.ownership is not None
    shares = {share.owner: share.findings for share in owned.ownership.owners}
    assert shares["interface"] >= 1 and sum(shares.values()) == owned.ownership.findings
    brief = render_brief(owned)
    assert "owners: " in brief and "owner: interface" in brief
    assert render_brief(plain) == render_brief(autopsy(run, cases=[case]))


# -- the overlay's surface check ---------------------------------------------------------


def test_the_surface_check_names_every_key_an_overlay_may_not_touch() -> None:
    base = (FIXTURES / "jira.anvil.yaml").read_text(encoding="utf-8")
    allowed = base.replace(SEARCH_OP, SEARCH_OP.replace("{ state: approved }", "") .rstrip() + "\n"
                           "    state: approved\n    description: Search with JQL.\n"
                           "    intent_examples:\n      - 'jql: project = OPS'\n")
    assert surface_findings("jira", base, allowed) == []
    risky = base.replace("    risk: medium\n    idempotency:\n      strategy: none\n    confirmation:\n      required: true\n"
                         "      risk: medium\n      reason: Creates a new Jira issue",
                         "    risk: low\n    idempotency:\n      strategy: none\n    confirmation:\n      required: true\n"
                         "      risk: medium\n      reason: Creates a new Jira issue")
    assert risky != base
    findings = surface_findings("jira", base, risky)
    assert findings and "operations.createIssue.risk" in findings[0]
    auth = base.replace("  type: basic\n", "  type: oauth2\n")
    assert any("`auth.type`" in item for item in surface_findings("jira", base, auth))
    assert parse_levers("interface,agent") == ("agent", "interface")
    with pytest.raises(ValueError):
        parse_levers("agent,grader")


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
needs_anvil = pytest.mark.skipif(ANVIL is None, reason="needs the Anvil CLI (set WORLDLOOM_ANVIL) and node")


@pytest.fixture(scope="module")
def contract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    assert ANVIL is not None
    root = tmp_path_factory.mktemp("anvil-interface")
    spec = root / "jira.spec.json"
    spec.write_bytes(gzip.decompress((FIXTURES / "jira.spec.json.gz").read_bytes()))
    done = subprocess.run([*ANVIL, "compile", str(spec), "--root", str(root), "--manifest",
                           str(FIXTURES / "jira.anvil.yaml"), "--service", "jira", "--out", str(root / "jira")],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    return root / "jira"


def _http(url: str, method: str, path: str, body: Any = None) -> tuple[int, Any]:
    request = urllib.request.Request(url + path, method=method,
                                     data=None if body is None else json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer admin"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "null")


def _grammar(text: str) -> bool:
    """Whether *text* shows a JQL clause for each field this agent needs to filter on."""
    return all(field in text for field in ("project = ", "issuetype = ", "status = ", "cf[10231] = "))


def _follower(read: str, name: str) -> CallableAgent:
    """An agent that writes a query in whatever grammar the served search tool shows, and guesses without one.

    *read* is what it reads of the tool: ``examples`` (the intent examples)
    or ``description``. It never sees a case's gold, only the request and
    the served surface.
    """

    def run(task: Any, tools: Any) -> AgentResponse:
        url = tools.base_urls["jira"]
        search = next(tool for tool in tools.surfaces["jira"]["tools"] if tool["operation"] == "jira.jql.search")
        shown = " ".join(search["intent_examples"]) if read == "examples" else search["description"]
        matched = _REQUEST.match(task.query)
        assert matched is not None, task.query
        status, severity, entity, project, target = matched.groups()
        if _grammar(shown):
            jql = f'project = {project} AND issuetype = {entity} AND status = {status} AND cf[10231] = "{severity}"'
        else:
            jql = f"{status} {severity} {entity} in {project}"
        code, found = _http(url, "POST", "/rest/api/2/search/jql", {"jql": jql})
        if code != 200 or not found.get("issues"):
            return AgentResponse(answer="I could not search for the issue.")
        key = found["issues"][0]["key"]
        _http(url, "POST", f"/rest/api/2/issue/{key}/transitions", {"transition": {"id": TRANSITIONS[target]}})
        return AgentResponse(answer=f"{key} moved to {target}.")

    return CallableAgent(run, name=name)


_DESCRIPTION = ("Search issues with a JQL expression in `jql`: `field operator value` clauses joined by AND. "
                "Filter on project, issuetype, status and severity (cf[10231]), for example "
                'project = OPS AND issuetype = task AND status = open AND cf[10231] = "Sev-1".')
_EXAMPLE = 'open Sev-1 tasks in OPS: project = OPS AND issuetype = task AND status = open AND cf[10231] = "Sev-1"'


def _overlay(tree: dict[str, str], *, inert: bool = True) -> dict[str, str]:
    text = tree["jira/manifest.yaml"]
    block = (f"  searchAndReconsileIssuesUsingJqlPost:\n    state: approved\n    description: {json.dumps(_DESCRIPTION)}\n"
             f"    intent_examples:\n      - {json.dumps(_EXAMPLE)}\n")
    assert SEARCH_OP in text
    text = text.replace(SEARCH_OP, block)
    if inert:
        # A second hunk the failures never called for: ablation should drop it.
        text = text.replace(PROJECT_OP, "  getFieldsPaginated:\n    state: approved\n    display_name: List fields, a page at a time\n")
    return {**tree, "jira/manifest.yaml": text}


def _proposer(*replies: Any) -> Any:
    seen: list[dict[str, Any]] = []

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        make = replies[min(len(seen), len(replies)) - 1]
        tree = payload["draft_tree"]
        return {"request_id": payload["request_id"], "message": "document the query grammar",
                "proposal": {"name": payload["name"], "diff": diffs.render(tree, make(tree))}}

    exchange.seen = seen  # type: ignore[attr-defined]
    return exchange


def _forbidden(tree: dict[str, str]) -> dict[str, str]:
    text = tree["jira/manifest.yaml"].replace("  deleteIssue: { state: approved }\n",
                                              "  deleteIssue:\n    state: approved\n    side_effect: read\n")
    return {**tree, "jira/manifest.yaml": text}


def _lever(contract: Path, out: Path) -> InterfaceLever:
    records = _records()

    def serve(cases: Any, agent: Any, serving: Any) -> Any:
        return run_cases(service_for(cases, records, query_engine="native"), cases, agent, anvil=serving)

    return InterfaceLever.from_contracts({"jira": contract}, serve=serve, out=out, command=ANVIL)


def _never(cases: Any, agent: Any) -> Any:
    raise AssertionError("under the interface lever every run is served through Anvil")


@needs_anvil
def test_an_overlay_touching_vendor_behaviour_is_refused_by_the_compiled_contract(contract: Path, tmp_path: Path) -> None:
    lever = _lever(contract, tmp_path / "loop")
    base = lever.base
    variant, findings = lever.lint(base, diffs.render(base.tree, _forbidden(base.tree)))
    assert variant is None and "operations.deleteIssue.side_effect" in findings[0], findings
    flow = base.tree["jira/manifest.yaml"].replace("  deleteIssue: { state: approved }\n",
                                                   "  deleteIssue: { state: approved, side_effect: read }\n")
    variant, findings = lever.lint(base, diffs.render(base.tree, {"jira/manifest.yaml": flow}))
    assert variant is None and "operations.deleteIssue.side_effect" in findings[0], findings
    # Behind the line check, the compiled contract is the authority: an
    # operation whose behaviour moved in the AIR is refused whatever the
    # manifest line looked like.
    air = json.loads((contract / "air.json").read_text(encoding="utf-8"))
    moved = json.loads(json.dumps(air))
    target = next(item for item in moved["operations"] if item["id"] == "jira.issue.delete")
    target["effect"]["kind"] = "read"
    target["description"] = "reworded"
    found = air_findings("jira", air, moved)
    assert len(found) == 1 and "jira.issue.delete changed effect" in found[0], found
    reworded = json.loads(json.dumps(air))
    next(item for item in reworded["operations"] if item["id"] == "jira.issue.delete")["description"] = "reworded"
    assert air_findings("jira", air, reworded) == []
    variant, findings = lever.lint(base, diffs.render(base.tree, {**base.tree, "jira/provider.py": "x\n"}))
    assert variant is None and "only the served connectors' manifests" in findings[0]
    variant, findings = lever.lint(base, diffs.render(base.tree, _overlay(base.tree)))
    assert findings == [] and variant is not None
    compiled = lever.compile(variant)
    assert compiled.digests["jira"] != lever.sources["jira"].contract_digest
    # Compiled once per digest, inside the loop's directory only.
    assert lever.compile(InterfaceVariant.from_tree(variant.tree)) is compiled
    assert compiled.contracts["jira"].resolve().is_relative_to((tmp_path / "loop").resolve())


@needs_anvil
def test_an_interface_candidate_is_promoted_through_every_gate(contract: Path, tmp_path: Path) -> None:
    cases = _cases()
    train, held = cases[:4], cases[6:9]
    out = tmp_path / "loop"
    lever = _lever(contract, out)
    manifest_before = (contract / ".anvil" / "manifest.yaml").read_bytes()
    hash_before = bundle_hash(contract)
    agent = _follower("examples", "follower")
    # The first reply touches vendor behaviour and is refused with findings;
    # the second documents the grammar (and renames a display name nobody needed).
    exchange = _proposer(_forbidden, _overlay)
    report = improve(packkit.resolve("agent:baseline"), train, run=_never, agent_for=lambda pack: agent,
                     exchange=exchange, out=out, holdout=held, rounds=1, levers=("interface",), interface=lever,
                     transfer=_follower("description", "reader"))
    receipt = report.rounds[0]
    assert receipt.decision == "promoted", receipt.reasons
    assert receipt.lever == "interface"
    # The proposer saw the interface's findings, the vendor's own error, the
    # arguments that caused it, and the tool as the agent saw it.
    first = exchange.seen[0]
    assert first["schema"] == "worldloom.pack-interview/v1" and first["kind"] == "anvil-overlay"
    assert "error:validation_error" in first["message"] and "Error in the JQL Query" in first["message"]
    assert "open Sev-1 task in OPS" in first["message"]
    assert any(tool["operation"] == "jira.jql.search" for tool in first["surface"]["jira"]["tools"])
    assert not any(case.id in first["message"] for case in held)
    # The forbidden first reply came back refused, with the key it may not touch.
    assert receipt.authoring[0]["status"] == "refused"
    assert any("operations.deleteIssue.side_effect" in finding for finding in receipt.authoring[0]["findings"])
    assert receipt.authoring[1]["status"] == "accepted"
    # Gated exactly like an agent candidate.
    assert receipt.train is not None and receipt.train.passed and receipt.train.mean_delta >= 0.1
    assert receipt.holdout is not None and receipt.holdout.passed
    assert receipt.transfer is not None and receipt.transfer.passed
    ablation = receipt.ablation
    assert ablation is not None and ablation.reduced
    assert [hunk.decision for hunk in ablation.hunks] == ["dropped", "kept"]
    assert receipt.diff is not None and "getFieldsPaginated" not in receipt.diff and "cf[10231]" in receipt.diff
    # The receipt names the overlay and the recompiled contract by digest.
    record = receipt.interface
    assert record is not None and set(record["overlays"]) == {"jira"}
    assert record["contracts"]["jira"] != record["base_contracts"]["jira"]
    assert record["transfer"] == {"passed": True}
    stored = json.loads((out / "rounds" / "001.json").read_text(encoding="utf-8"))
    assert stored["lever"] == "interface" and stored["candidate"]["ref"] == "interface:jira"
    # Graded from Anvil's trace of provider calls.
    held_run = json.loads(next((out / "runs").glob("baseline@*+if-*/holdout/results.jsonl")).read_text(
        encoding="utf-8").splitlines()[0])
    assert [span["tool"] for span in held_run["spans"]] == ["jira.search_issues", "jira.transition_issue"]
    assert held_run["score"]["passed"] is True
    # Promotion: a reviewable diff and a simulation-only approvals record, inside the loop's directory.
    promoted = out / "interface" / "promoted" / "001"
    diff_text = (promoted / "jira.manifest.diff").read_text(encoding="utf-8")
    assert diff_text == receipt.diff.replace("jira/manifest.yaml", "jira/manifest.yaml")
    approvals = [json.loads(line) for line in (promoted / "jira.approvals.jsonl").read_text().splitlines()]
    assert len(approvals) == 1
    entry = approvals[0]
    assert entry["schemaVersion"] == 1 and entry["reviewer"] == "unrecorded" and entry["action"] == "reproject"
    assert entry["note"].startswith("simulation-only") and "human" not in entry["reviewer"]
    assert re.fullmatch(r"[0-9a-f]{64}", entry["bundleHash"]["before"]) and entry["bundleHash"]["before"] == hash_before
    assert entry["bundleHash"]["after"] != hash_before
    assert {"kind": "operation", "id": "jira.jql.search", "from": "approved", "to": "approved"} in entry["subjects"]
    # Nothing outside the loop's directory moved.
    assert (contract / ".anvil" / "manifest.yaml").read_bytes() == manifest_before
    assert bundle_hash(contract) == hash_before
    assert not (contract / ".anvil" / "approvals.jsonl").exists()
    assert report.interface is not None and report.interface["champion"] == receipt.candidate["digest"]


@needs_anvil
def test_without_a_transfer_agent_the_gate_is_skipped_and_says_why(contract: Path, tmp_path: Path) -> None:
    cases = _cases()
    out = tmp_path / "loop"
    agent = _follower("examples", "follower")
    report = improve(packkit.resolve("agent:baseline"), cases[:4], run=_never, agent_for=lambda pack: agent,
                     exchange=_proposer(lambda tree: _overlay(tree, inert=False)), out=out, holdout=cases[6:9],
                     rounds=1, levers=("interface",), interface=_lever(contract, out), ablate=False)
    receipt = report.rounds[0]
    assert receipt.decision == "promoted", receipt.reasons
    assert receipt.transfer is None
    assert receipt.interface is not None and "no transfer agent" in receipt.interface["transfer"]["skipped"]


@needs_anvil
def test_wide_search_mixes_agent_and_interface_candidates(contract: Path, tmp_path: Path) -> None:
    cases = _cases()
    out = tmp_path / "loop"
    agent = _follower("examples", "follower")
    overlay = _proposer(lambda tree: _overlay(tree, inert=False))
    kinds: list[str] = []

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        kinds.append(payload["kind"])
        if payload["kind"] == "anvil-overlay":
            return overlay(payload)
        body = {**payload["draft"]["body"], "skills": {"patience": "Read the whole request before searching."}}
        return {"request_id": payload["request_id"], "message": "an agent-side guess",
                "proposal": {"name": payload["draft"]["name"], "body": body}}

    report = improve(packkit.resolve("agent:baseline"), cases[:3], run=_never, agent_for=lambda pack: agent,
                     exchange=exchange, out=out, holdout=cases[6:8], rounds=1, levers=("agent", "interface"),
                     interface=_lever(contract, out), candidates=2, screen_cases=2, ablate=False)
    receipt = report.rounds[0]
    # The interface owns more of the failing findings, so it takes the first candidate.
    assert kinds == ["anvil-overlay", "agent"]
    assert receipt.screening is not None
    assert [record.ref.split(":")[0] for record in receipt.screening.candidates if record.ref] == ["interface", "agent"]
    assert receipt.decision == "promoted" and receipt.lever == "interface", receipt.reasons


# -- the agent lever alone keeps its bytes ------------------------------------------------


class _PolicyAgent:
    """Walks the gold plan when its policy teaches `verify`; otherwise does nothing."""

    def __init__(self, pack: Any, cases: Any) -> None:
        from worldloom.evalrun import ReferenceAgent
        from worldloom.evalrun.policy import agent_name, pack_record

        self.name = agent_name("policy", pack)
        self.pack_record = pack_record(pack)
        skilled = "verify" in pack.body.skills
        self.inner: Any = ReferenceAgent(cases) if skilled else ScriptedAgent([], name="idle")

    def run(self, task: Any, tools: Any) -> Any:
        return self.inner.run(task, tools)


def _agent_loop(out: Path, **options: Any) -> Any:
    cases = _cases()
    records = _records()

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        body = {**payload["draft"]["body"], "skills": {"verify": "Walk every step and read each write back."}}
        return {"request_id": payload["request_id"], "message": "revised",
                "proposal": {"name": payload["draft"]["name"], "body": body}}

    def run(subset: Any, agent: Any) -> Any:
        return run_cases(service_for(subset, records), subset, agent)

    return improve(packkit.resolve("agent:baseline"), cases[:6], run=run,
                   agent_for=lambda pack: _PolicyAgent(pack, cases), exchange=exchange, out=out, holdout=cases[6:],
                   rounds=1, **options)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*"))
            if path.is_file() and path.suffix in {".json", ".diff"} and "runs" not in path.parts}


def test_receipts_are_byte_identical_when_only_the_agent_lever_is_used(tmp_path: Path) -> None:
    default = _agent_loop(tmp_path / "default")
    explicit = _agent_loop(tmp_path / "explicit", levers=("agent",), interface=None, transfer=None)
    assert default.rounds[0].decision == "promoted", default.rounds[0].reasons
    assert explicit.model_dump() == default.model_dump()
    left, right = _tree_bytes(tmp_path / "default"), _tree_bytes(tmp_path / "explicit")
    assert sorted(left) == sorted(right) and left == right
    receipt = json.loads(left["rounds/001.json"])
    assert not {"lever", "interface", "transfer"} & set(receipt)
    assert not {"levers", "interface"} & set(json.loads(left["improve.json"]))
    assert not (tmp_path / "default" / "interface").exists()
    # The interface lever without its bundles is refused before anything runs.
    with pytest.raises(ValueError, match="interface lever needs"):
        _agent_loop(tmp_path / "refused", levers=("agent", "interface"))


# -- the CLI ---------------------------------------------------------------------------


def test_the_cli_prints_owners_and_refuses_lever_flags_that_do_not_combine(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from worldloom.cli import app
    from worldloom.evalrun.results import write_run

    runner = CliRunner()
    run, _ = _in_process([("jira.search_issues", {"query": "open Sev-1 task in OPS"})])
    write_run(tmp_path / "run", run)
    result = runner.invoke(app, ["evalrun", "autopsy", str(tmp_path / "run")])
    assert result.exit_code == 0, result.output
    assert "owners: " in result.output and "owner: interface" in result.output
    result = runner.invoke(app, ["evalrun", "autopsy", str(tmp_path / "run"), "--no-owners"])
    assert result.exit_code == 0 and "owners: " not in result.output
    result = runner.invoke(app, ["evalrun", "summarize", str(tmp_path / "run")])
    assert result.exit_code == 0 and "owners: " in result.output, result.output
    result = runner.invoke(app, ["evalrun", "compare", str(tmp_path / "run"), str(tmp_path / "run")])
    assert result.exit_code == 0 and "interface 6 -> 6 finding(s)" in result.output, result.output
    base = ["evalrun", "improve", str(tmp_path), "--agent-pack", "agent:baseline", "-o", str(tmp_path / "out")]
    result = runner.invoke(app, [*base, "--levers", "agent,grader"])
    assert result.exit_code == 2 and "levers are agent, interface" in " ".join(result.output.split()), result.output
    result = runner.invoke(app, [*base, "--contract", "jira=./bundle"])
    assert result.exit_code == 2 and "belong to the interface lever" in " ".join(result.output.split()), result.output
    result = runner.invoke(app, [*base, "--levers", "interface"])
    assert result.exit_code == 2 and "needs at least one --contract" in " ".join(result.output.split()), result.output


# -- the lever on the contract surface, in process ----------------------------------------


def _contract_follower(name: str) -> CallableAgent:
    """The description reader, on the contract surface: it reads the tool list the run presents and calls it in process."""

    def run(task: Any, tools: Any) -> AgentResponse:
        catalog = {entry.get("operation"): entry for entry in tools.tools()}
        search, move = catalog["jira.jql.search"], catalog["jira.transitions.create"]
        matched = _REQUEST.match(task.query)
        assert matched is not None, task.query
        status, severity, entity, project, target = matched.groups()
        if _grammar(str(search.get("description") or "")):
            jql = f'project = {project} AND issuetype = {entity} AND status = {status} AND cf[10231] = "{severity}"'
        else:
            jql = f"{status} {severity} {entity} in {project}"
        try:
            found = tools.call(search["name"], body={"jql": jql})
        except Exception:  # the vendor's refusal, as the agent sees it
            return AgentResponse(answer="I could not search for the issue.")
        if not found.get("issues"):
            return AgentResponse(answer="I could not search for the issue.")
        key = found["issues"][0]["key"]
        tools.call(move["name"], issue_id_or_key=key, body={"transition": {"id": TRANSITIONS[target]}})
        return AgentResponse(answer=f"{key} moved to {target}.")

    return CallableAgent(run, name=name)


@needs_anvil
def test_the_interface_lever_serves_its_candidates_in_process_on_the_contract_surface(
        contract: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from worldloom.connectors import surface as surfaces
    from worldloom.evalrun.anvil import AnvilCase
    from worldloom.evalrun.interface import ContractServing

    def no_server(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("on the contract surface no Anvil server is started for a case")

    monkeypatch.setattr(AnvilCase, "start", no_server)
    projected: list[str] = []
    real_project = surfaces.project

    def counting(bundle: Any, connector: str, **options: Any) -> Any:
        projected.append(str(bundle))
        return real_project(bundle, connector, **options)

    monkeypatch.setattr(surfaces, "project", counting)
    records = _records()

    def serve(cases: Any, agent: Any, serving: Any) -> Any:
        assert isinstance(serving, ContractServing)
        service = service_for(cases, records, query_engine="native", surface=serving.surfaces)
        return run_cases(service, cases, agent)

    out = tmp_path / "loop"
    lever = InterfaceLever.from_contracts({"jira": contract}, serve=serve, out=out, command=ANVIL, surface="contract")
    # The overlay changes the surface the in-process run presents, exactly as it changes Anvil's.
    base = lever.serving(lever.base)
    before = next(tool for tool in base.projected["jira"].tools if tool.operation == "jira.jql.search")
    assert not _grammar(str(before.definition.get("description")))
    candidate, findings = lever.lint(lever.base, diffs.render(lever.base.tree, _overlay(lever.base.tree, inert=False)))
    assert candidate is not None, findings
    after = next(tool for tool in lever.serving(candidate).projected["jira"].tools if tool.operation == "jira.jql.search")
    assert _grammar(str(after.definition.get("description")))
    assert lever.identity(candidate)["serving"] == "contract-surface"
    # Each bundle is projected once and read back from the cache after.
    lever.serving(candidate)
    assert len(projected) == len(set(projected)) == 2
    cases = _cases()
    train, held = cases[:4], cases[6:9]
    report = improve(packkit.resolve("agent:baseline"), train, run=_never,
                     agent_for=lambda pack: _contract_follower("reader"), exchange=_proposer(_overlay), out=out,
                     holdout=held, rounds=1, levers=("interface",), interface=lever)
    receipt = report.rounds[0]
    assert receipt.decision == "promoted", receipt.reasons
    assert receipt.lever == "interface"
    assert receipt.train is not None and receipt.train.mean_delta >= 0.1
    held_run = json.loads(next((out / "runs").glob("baseline@*+if-*/holdout/results.jsonl")).read_text(
        encoding="utf-8").splitlines()[0])
    # Graded as the connector calls the mapping made of the contract calls.
    assert [span["tool"] for span in held_run["spans"]] == ["jira.search_issues", "jira.transition_issue"]
    assert held_run["score"]["passed"] is True
