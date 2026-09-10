"""Scripted protocol tests, not measurements of a live target model."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys

import pytest

from worldloom.connector_data import generate_connector_data
from worldloom.enterprise_io import load_exported_corpus
from worldloom.enterprise_qualification import qualify_queries
from worldloom.enterprise_queries import (
    ArtifactRequirement,
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from worldloom.execseam import ExecReply
from worldloom.predicates import FieldPredicate, Predicate
from worldloom.studio.trials import TrialReceipt, evaluate_trial
from worldloom.world import World


@pytest.fixture(scope="module")
def qualified(tmp_path_factory):
    world = World.load("examples/retail-close")
    source = generate_connector_data(world, connectors=("servicenow",)).records[0]
    query = PlannedEnterpriseQuery(
        id="trial-case", workflow="incident-reconcile",
        query=f"Read {source.external_id}. Find Existing incident for {world.company.name}, set its state to open and verify it.",
        dimensions={"workflow": "incident-reconcile", "failure": "none"},
        generation=GenerationRequirement(
            process="service_management",
            source_requirements=(SourceRequirement(
                connector="servicenow", entity="incident",
                predicate=Predicate(entity="incident", where=(FieldPredicate(field="external_id", value=source.external_id),)),
            ),),
            mutation=MutationRequirement(connector="servicenow", entity="incident", operation="patch",
                                         output_format="record", preexisting_record=True, target_state="open"),
        ),
        expected_dag=(
            {"id": "read", "connector": "servicenow", "entity": "incident", "kind": "read", "depends_on": []},
            {"id": "write", "connector": "servicenow", "entity": "incident", "kind": "patch", "depends_on": ["read"]},
            {"id": "verify", "connector": "servicenow", "entity": "incident", "kind": "readback", "depends_on": ["write"]},
        ),
    )
    result = qualify_queries(world, (query,), pool_size=1, pool_exhausted=True)
    assert result.report.selected_count == 1
    return result.export(tmp_path_factory.mktemp("target-corpus") / "qualified")


def scripted_agent(command, request, **kwargs):
    """Choose actual calls solely from the public task and delivered results."""
    assert command == "scripted-target"
    assert kwargs["timeout"] == 600
    assert set(request) == {"schema", "request_id", "query", "tools", "history", "remaining_turns", "instructions", "response_schema"}
    assert not {"eval_trace", "eval_grade", "eval_begin", "eval_end"} & {tool["name"] for tool in request["tools"]}
    serialized = json.dumps(request)
    assert all(f'"{key}":' not in serialized for key in (
        "expected_dag", "expected_fact_ids", "expected_evidence_ids", "fixture", "fixtures",
        "grade", "split", "world_digest", "corpus_digest", "proofs",
    ))
    history = request["history"]
    if len(history) == 0:
        call = {"tool": "servicenow.get_record", "arguments": {"id": request["query"].split("Read ")[1].split(".")[0]}}
    elif len(history) == 1:
        title = request["query"].split("Find ")[1].split(", set its")[0]
        call = {"tool": "servicenow.search_records", "arguments": {"entity": "incident", "predicate": {"title": title}}}
    elif len(history) == 2:
        target = history[1]["observation"]["result"]["items"][0]["sys_id"]
        call = {"tool": "servicenow.update_record", "arguments": {"id": target, "fields": {"state": "open"}}}
    elif len(history) == 3:
        target = history[2]["observation"]["result"]["sys_id"]
        call = {"tool": "servicenow.get_record", "arguments": {"id": target}}
    else:
        assert history[3]["observation"]["result"]["state"] == 2
        return ExecReply({"request_id": request["request_id"], "final": "The incident is now open; I verified the saved record."}, "")
    return ExecReply({"request_id": request["request_id"], "call": call}, "")


@pytest.mark.parametrize("format", ("docx", "pptx", "xlsx"))
def test_reference_file_write_cannot_certify_native_output(qualified, tmp_path, monkeypatch, format):
    original = load_exported_corpus(qualified).queries[0]
    query = original.model_copy(update={
        "query": f"Read the incident and create a {format} report in Drive; verify it.",
        "generation": original.generation.model_copy(update={
            "mutation": MutationRequirement(connector="drive", entity="file", operation="create",
                                            output_format=format, preexisting_record=False),
            "artifact": ArtifactRequirement(format=format),
        }),
        "expected_dag": (
            {"id": "read", "connector": "servicenow", "entity": "incident", "kind": "read", "depends_on": []},
            {"id": "write", "connector": "drive", "entity": "file", "kind": "create", "depends_on": ["read"]},
            {"id": "verify", "connector": "drive", "entity": "file", "kind": "readback", "depends_on": ["write"]},
        ),
    })
    result = qualify_queries(World.load("examples/retail-close"), (query,), pool_size=1, pool_exhausted=True)
    assert result.report.selected_count == 1
    exported = result.export(tmp_path / "native")
    monkeypatch.setattr("worldloom.execseam.run_exec", lambda *_args, **_kw: pytest.fail("unsupported task reached target"))
    with pytest.raises(ValueError, match="native_output_content_and_preservation_unmeasured"):
        evaluate_trial(exported, query.id, root=tmp_path / "trial", harness_command="scripted-target")


def test_actual_calls_are_graded_and_replayed_with_zero_exec(qualified, tmp_path, monkeypatch):
    monkeypatch.setattr("worldloom.execseam.run_exec", scripted_agent)
    before = {path.name: path.read_bytes() for path in qualified.iterdir()}
    outcome = evaluate_trial(qualified, "trial-case", root=tmp_path, harness_command="scripted-target")
    assert outcome.passed, outcome
    assert outcome.details["calls"] == 4
    assert outcome.details["turns"] == 5
    assert outcome.details["evaluation"] == "observed_connector_contract"
    assert {path.name: path.read_bytes() for path in qualified.iterdir()} == before
    observation = TrialReceipt.model_validate_json((tmp_path / "observation-0003.json").read_text())
    assert observation.body["spans"][0]["node"] == "write"
    assert observation.body["spans"][0]["writes"]
    def forbidden(*args, **kwargs):
        pytest.fail("completed trial made an external call")
    monkeypatch.setattr("worldloom.execseam.run_exec", forbidden)
    assert evaluate_trial(qualified, "trial-case", root=tmp_path, harness_command="scripted-target") == outcome


@pytest.mark.parametrize("interruption", ("between_turns", "after_proposal"))
def test_resume_reconstructs_mutations_without_repeating_accepted_proposals(qualified, tmp_path, monkeypatch, interruption):
    monkeypatch.setattr("worldloom.execseam.run_exec", scripted_agent)
    expected = evaluate_trial(qualified, "trial-case", root=tmp_path / "complete", harness_command="scripted-target")
    resumed = tmp_path / "resume"
    resumed.mkdir()
    for filename in ("input.json", "proposal-0001.json", "observation-0001.json", "proposal-0002.json", "observation-0002.json", "proposal-0003.json"):
        shutil.copy(tmp_path / "complete" / filename, resumed / filename)
    if interruption == "between_turns":
        shutil.copy(tmp_path / "complete" / "observation-0003.json", resumed / "observation-0003.json")
    seen = []
    def continue_agent(command, payload, **kwargs):
        seen.append(len(payload["history"]))
        return scripted_agent(command, payload, **kwargs)
    monkeypatch.setattr("worldloom.execseam.run_exec", continue_agent)
    assert evaluate_trial(qualified, "trial-case", root=resumed, harness_command="scripted-target") == expected
    assert seen == [3, 4]


def test_self_reported_success_does_not_pass_without_observed_execution(qualified, tmp_path, monkeypatch):
    def claim(command, request, **kwargs):
        return ExecReply({"request_id": request["request_id"], "final": "Everything passed and the incident is open."}, "")
    monkeypatch.setattr("worldloom.execseam.run_exec", claim)
    outcome = evaluate_trial(qualified, "trial-case", root=tmp_path, harness_command="scripted-target")
    assert not outcome.passed
    assert "tool_not_called:write" in outcome.details["grade"]["fails"]
    assert "state_not_written:write" in outcome.details["grade"]["fails"] or "state_mismatch:write" in outcome.details["grade"]["fails"]


def test_additional_unassigned_mutation_fails_after_correct_task(qualified, tmp_path, monkeypatch):
    def corrupt(command, request, **kwargs):
        if len(request["history"]) == 4:
            return ExecReply({"request_id": request["request_id"], "call": {
                "tool": "servicenow.update_record", "arguments": {"id": request["query"].split("Read ")[1].split(".")[0], "fields": {"state": "open"}},
            }}, "")
        if len(request["history"]) == 5:
            return ExecReply({"request_id": request["request_id"], "final": "Done."}, "")
        return scripted_agent(command, request, **kwargs)
    monkeypatch.setattr("worldloom.execseam.run_exec", corrupt)
    outcome = evaluate_trial(qualified, "trial-case", root=tmp_path, harness_command="scripted-target")
    assert not outcome.passed
    assert outcome.details["grade"]["fails"] == []
    assert outcome.details["unmatched_writes"] == ["s5"]


def test_declared_failure_is_observed_in_the_runtime_not_claimed_by_the_agent(qualified, tmp_path, monkeypatch):
    query = load_exported_corpus(qualified).queries[0]
    query = query.model_copy(update={
        "dimensions": {**query.dimensions, "failure": "version_conflict"},
        "generation": query.generation.model_copy(update={"state_overrides": ("version_conflict",)}),
    })
    result = qualify_queries(World.load("examples/retail-close"), (query,), pool_size=1, pool_exhausted=True)
    assert result.report.selected_count == 1
    exported = result.export(tmp_path / "conflicted")
    def conflict_agent(command, request, **kwargs):
        if len(request["history"]) == 3:
            assert request["history"][2]["observation"]["error"]["code"] == 409
            return ExecReply({"request_id": request["request_id"], "final": "The system refused the write due to a version conflict."}, "")
        return scripted_agent(command, request, **kwargs)
    monkeypatch.setattr("worldloom.execseam.run_exec", conflict_agent)
    outcome = evaluate_trial(exported, "trial-case", root=tmp_path / "trial", harness_command="scripted-target")
    assert outcome.passed, outcome
    assert outcome.details["grade"]["errors"] == 1


@pytest.mark.parametrize("kind", ("proposal", "observation", "result", "missing_prefix", "input", "qualified"))
def test_tampered_inputs_and_receipts_refuse_before_new_external_work(qualified, tmp_path, monkeypatch, kind):
    source = tmp_path / "source"
    shutil.copytree(qualified, source)
    ledger = tmp_path / "trial"
    monkeypatch.setattr("worldloom.execseam.run_exec", scripted_agent)
    evaluate_trial(source, "trial-case", root=ledger, harness_command="scripted-target")
    if kind == "missing_prefix":
        (ledger / "proposal-0002.json").unlink()
    elif kind == "qualified":
        path = source / "qualified-rows.jsonl"
        row = json.loads(path.read_text())
        row["assertions"] = []
        path.write_text(json.dumps(row) + "\n")
    else:
        path = ledger / ({"proposal": "proposal-0002.json", "observation": "observation-0002.json",
                          "result": "result.json", "input": "input.json"}[kind])
        value = json.loads(path.read_text())
        value["body"]["tampered"] = True
        path.write_text(json.dumps(value))
    def forbidden(*args, **kwargs):
        pytest.fail("tampered trial made an external call")
    monkeypatch.setattr("worldloom.execseam.run_exec", forbidden)
    with pytest.raises(ValueError, match=r"digest|prefix"):
        evaluate_trial(source, "trial-case", root=ledger, harness_command="scripted-target")


def test_harness_changes_refuse_and_invalid_response_is_not_accepted(qualified, tmp_path, monkeypatch):
    def invalid(command, request, **kwargs):
        return ExecReply({"request_id": request["request_id"], "passed": True, "final": "Done."}, "")
    monkeypatch.setattr("worldloom.execseam.run_exec", invalid)
    with pytest.raises(ValueError, match="Extra inputs"):
        evaluate_trial(qualified, "trial-case", root=tmp_path, harness_command="scripted-target")
    assert not list(tmp_path.glob("proposal-*.json"))
    with pytest.raises(ValueError, match=r"changed input\.json"):
        evaluate_trial(qualified, "trial-case", root=tmp_path, harness_command="different-target")


def test_turn_budget_stops_without_calling_an_unbounded_agent(qualified, tmp_path, monkeypatch):
    monkeypatch.setattr("worldloom.execseam.run_exec", scripted_agent)
    outcome = evaluate_trial(qualified, "trial-case", root=tmp_path, harness_command="scripted-target", max_turns=2)
    assert not outcome.passed
    assert outcome.details["stopped"] == "turn_budget"
    assert outcome.details["calls"] == 2


def test_exec_adapter_uses_an_ordinary_process_without_trusting_its_claims(qualified, tmp_path):
    """The seam is JSON over subprocess pipes, not filesystem containment."""
    marker = tmp_path / "host-marker.txt"
    marker.write_text("ordinary-host-file", encoding="utf-8")
    adapter = tmp_path / "scripted adapter.py"
    adapter.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "request = json.load(sys.stdin)\n"
        "assert request['schema'] == 'worldloom.target-trial/v1'\n"
        "assert 'expected_dag' not in request and 'fixtures' not in request\n"
        "marker = Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "json.dump({'request_id': request['request_id'], 'final': 'Claimed success: ' + marker}, sys.stdout)\n",
        encoding="utf-8",
    )
    argv = [sys.executable, str(adapter), str(marker)]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    outcome = evaluate_trial(qualified, "trial-case", root=tmp_path / "trial", harness_command=command,
                             timeout=5, max_turns=1)
    assert not outcome.passed
    assert outcome.details["calls"] == 0
    proposal = TrialReceipt.model_validate_json((tmp_path / "trial" / "proposal-0001.json").read_text())
    assert proposal.body["reply"]["final"] == "Claimed success: ordinary-host-file"
