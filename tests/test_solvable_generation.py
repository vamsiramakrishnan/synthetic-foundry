"""The shipped generators make no case their own reference agent cannot solve.

`evalrun prove` replays every gold plan. Over the documented enterprise builds
it once found 116 of 1,000 cases per seed unsolvable, every one the
generator's or the grader's doing: a reply sent to a message the gold plan
never read (`destructive_without_read`), a diamond that joined two views of
one record into an evidence count of two, a restated-figure corner whose
answer stated figures no readable record carries, and a programme answer
that stated a count of filtered records. One regression per cause, and the
documented build proved with nothing dropped.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_definition import builtin_connector_definitions
from worldloom.enterprise_corpus import materialize_corpus
from worldloom.enterprise_dag import resolve_shapes
from worldloom.enterprise_dag_planning import _reads_target_first, write_nodes
from worldloom.enterprise_queries import MutationRequirement, plan_queries
from worldloom.enterprise_specs import CoverageProfile, builtin_registry
from worldloom.evalrun import ReferenceAgent, ScriptedAgent, run_cases, service_for
from worldloom.evalrun.contract import EvalCase, cases_from_corpus
from worldloom.evalrun.proof import prove_cases, read_proof
from worldloom.evalrun.safety import classify_tool
from worldloom.world import World

runner = CliRunner()


@pytest.fixture(scope="module")
def world_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("world") / "w8128"
    result = runner.invoke(app, ["build", "--seed", "8128", "--incident", "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


@pytest.fixture(scope="module")
def generated(world_dir: Path) -> tuple[tuple[EvalCase, ...], tuple[Any, ...]]:
    """The documented build's cases for seed 8128, planned and compiled in process."""
    queries, _ = plan_queries(World.load(world_dir), registry=builtin_registry(), profile=CoverageProfile(strengths=2),
                              strategy="exhaustive", limit=200, dag_shapes=resolve_shapes(["*"]))
    corpus = materialize_corpus(World.load(world_dir), queries)
    return cases_from_corpus(corpus), tuple(corpus.connector_data.records)


def _pick(cases: Sequence[EvalCase], operation: str, shape: str | None = None) -> list[EvalCase]:
    return [case for case in cases if case.dimensions.get("operation") == operation
            and (shape is None or case.dimensions.get("dag_shape") == shape)]


def _prove(cases: Sequence[EvalCase], records: Sequence[Any]) -> None:
    report = prove_cases(cases, records)
    assert report.unsolvable == 0, [item.failure for item in report.unsolvable_cases()]


# -- 1. a write the safety law holds reads its target first ------------------------------------


def test_the_planner_asks_the_graders_own_classification_which_writes_read_first() -> None:
    # One rule: for every tool a builtin connector serves, the planner plans a
    # target read exactly where the grader's law holds the call to one.
    checked = 0
    for name, definition in builtin_connector_definitions().items():
        for entity, spec in definition.entities.items():
            for operation, tool in spec.ops.items():
                law = classify_tool(name, tool, definition.tool(tool)).reads_first
                assert _reads_target_first(name, entity, entity, operation) == law, (name, entity, operation)
                checked += 1
    assert checked > 50
    held = {(name, spec.op) for name, definition in builtin_connector_definitions().items()
            for tool, spec in definition.tools.items()
            if classify_tool(name, tool, spec).reads_first}
    assert ("email", "reply") in held and ("email", "delete") not in held and ("sharepoint", "delete") in held
    # A send names no record: it creates the one it acts on, so there is nothing to have read.
    assert not any(op == "send" for _, op in held)


def test_a_reply_reads_its_message_first_and_proves_solvable(
        generated: tuple[tuple[EvalCase, ...], tuple[Any, ...]]) -> None:
    cases, records = generated
    replies = _pick(cases, "reply")
    assert replies, "the documented build plans replies"
    for case in replies:
        nodes = [node["id"] for node in case.row["expected_dag"]["nodes"]]
        for node in case.row["expected_dag"]["nodes"]:
            if node["op"] == "reply":
                assert node["bindings"]["id"]["node"] == f"target-{node['id']}"
                assert nodes.index(f"target-{node['id']}") < nodes.index(node["id"])
    _prove(replies, records)


def test_a_reply_that_opens_the_thread_first_is_not_penalised_and_one_that_never_reads_it_is(
        generated: tuple[tuple[EvalCase, ...], tuple[Any, ...]]) -> None:
    cases, records = generated
    case = _pick(cases, "reply", "fan_in")[0]
    service = service_for([case], records)
    reference = run_cases(service, [case], ReferenceAgent([case])).results[0]
    calls = [(str(span["tool"]), dict(span["args"])) for span in reference.spans]
    target = next(index for index, (tool, _) in enumerate(calls) if tool == "email.get_message")
    # The thread opened before the evidence is gathered: the same work, in
    # an order the plan allows, because the target read waits on no read.
    early = [calls[target], *calls[:target], *calls[target + 1:]]
    score = run_cases(service_for([case], records), [case], ScriptedAgent(early, name="thread-first")).results[0].score
    assert score is not None and score.plan.passed and score.trajectory.safety == (), score.plan
    blind = [call for index, call in enumerate(calls) if index != target]
    score = run_cases(service_for([case], records), [case], ScriptedAgent(blind, name="blind")).results[0].score
    assert score is not None and [finding.law for finding in score.trajectory.safety] == ["destructive_without_read"]


def test_a_send_proves_solvable_without_a_target_read(
        generated: tuple[tuple[EvalCase, ...], tuple[Any, ...]]) -> None:
    cases, records = generated
    sends = _pick(cases, "send")
    assert sends
    assert not any(node["id"].startswith("target-") for case in sends for node in case.row["expected_dag"]["nodes"])
    _prove(sends, records)


def test_a_delete_and_a_move_still_read_their_target() -> None:
    for operation, connector, entity in (("delete", "sharepoint", "file"), ("move", "drive", "file")):
        mutation = MutationRequirement(connector=connector, entity=entity, operation=operation,
                                       output_format="record", preexisting_record=True)
        planned = write_nodes(mutation, "collect", _result_body(), "write")
        assert [node.id for node in planned] == ["target-write", "write", "verify-write"]
        assert planned[1].bindings["id"].node == "target-write"


def _result_body() -> Any:
    from worldloom.enterprise_dag import ResultReference

    return ResultReference(node="collect", select="all", encoding="json")


# -- 2. a diamond counts each record once --------------------------------------------------------


def test_a_diamond_writes_one_evidence_entry_per_record_and_proves_solvable(
        generated: tuple[tuple[EvalCase, ...], tuple[Any, ...]]) -> None:
    cases, records = generated
    diamonds = [case for case in cases if case.dimensions.get("dag_shape") == "diamond"
                and case.dimensions.get("operation") not in {"reply", "forward", "comment", "delete", "move"}]
    assert diamonds
    report = run_cases(service_for(diamonds, records), diamonds, ReferenceAgent(diamonds))
    checked = 0
    for case, result in zip(diamonds, report.results, strict=True):
        wanted = {rid for node in case.row["expected_dag"]["nodes"] for rid in node.get("expected_reads", ())}
        writes = [span for span in result.spans if span.get("node") == "write" and not span.get("error")]
        if not writes:
            continue  # a designed failure refused the write
        fields = writes[0]["args"]["fields"]
        checked += 1
        assert fields["evidence_count"] == len(fields["evidence"]) == len(wanted), (case.id, fields)
    assert checked
    _prove(diamonds, records)


# -- 3. answers state only figures a readable record carries -------------------------------------


def test_a_reply_body_carries_the_sections_its_document_requires(
        generated: tuple[tuple[EvalCase, ...], tuple[Any, ...]]) -> None:
    cases, records = generated
    case = _pick(cases, "reply", "deep_chain")[0]
    assert case.outcomes.unstructured is not None and case.outcomes.unstructured.sections
    result = run_cases(service_for([case], records), [case], ReferenceAgent([case])).results[0]
    body = next(span for span in result.spans if span.get("node") == "write")["args"]["body"]
    assert all(f"<h2>{section}</h2>" in body for section in case.outcomes.unstructured.sections), body
    assert result.score is not None and result.score.passed


def test_a_programme_answer_names_the_filtered_records_rather_than_counting_them() -> None:
    from worldloom import industry

    derived = industry.programme("retail")
    cases = [case for case in derived.evalrun_cases()[:40] if case.dimensions.get("intent") == "triage_queue"]
    assert cases
    counted = [case for case in cases if len(case.row["expected_record_ids"]) >= 10]
    assert counted, "a queue with ten or more open records (a two-digit count) is among them"
    for case in counted:
        assert f"{len(case.row['expected_record_ids'])} open" not in case.row["expected_answer"]
    _prove(cases, derived.records)


# -- 4. the documented build proves with nothing dropped ----------------------------------------


def test_the_documented_build_proves_with_nothing_dropped(world_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "cases"
    result = runner.invoke(app, ["enterprise-evals", "build", str(world_dir), str(out),
                                 "--exhaustive", "--limit", "100", "--dag-shape", "*"])
    assert result.exit_code == 0, result.output
    proof = read_proof(out)
    assert proof is not None and proof.unsolvable == 0 and proof.dropped == () and proof.solvable == 100
    written = (out / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    operations = {json.loads(line)["dimensions"]["operation"] for line in written}
    shapes = {json.loads(line)["dimensions"]["dag_shape"] for line in written}
    assert "reply" in operations and "diamond" in shapes
