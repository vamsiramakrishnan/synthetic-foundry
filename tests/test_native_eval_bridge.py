"""Actual native outcomes feed sealed promotion without invented trace scores."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from worldloom import packkit
from worldloom.evalrun.agents import AgentResponse, ScriptedAgent
from worldloom.evalrun.autopsy import autopsy
from worldloom.evalrun.improve import improve
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.evalrun.qualification import (
    QualificationPolicy,
    audit_splits,
    evidence_components,
)
from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Company,
    Quantity,
)
from worldloom.native_artifacts import inspect_artifact
from worldloom.native_corpus import (
    NativeContent,
    NativeCorpusPlan,
    render_native_corpus,
)
from worldloom.native_eval_bridge import (
    NativeGrader,
    native_grader_identity,
    native_run_report,
    native_runner,
    native_task_cases,
)
from worldloom.native_query_planning import NativeWorkloadPlan, plan_native_workload
from worldloom.native_reference import reference_submission
from worldloom.native_tasks import NativeAnswer, NativeCitation, NativeSubmission
from worldloom.world import World


@pytest.fixture
def corpus() -> tuple:
    facts = tuple(CanonicalFact(id=f"FACT-{index:04}", kind="retail.units", subject="store:" + chr(65 + index), period="2026-01",
        value=Quantity(amount=100 + index, unit="units"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD) for index in range(12))
    world = World(seed=8128, company=Company(id="CO-1", name="Northstar Retail", industry="retail", headquarters="Sydney",
        fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-SOURCE", intent_id="INTENT-1", title="Store review", sections=[
            ArtifactSection(heading=f"Store {chr(65 + index)} units", body=f"Units for {fact.subject}: {{{{fact:{fact.id}}}}}", fact_ids=[fact.id])
            for index, fact in enumerate(facts)]),))
    plans = tuple(NativeCorpusPlan(artifact_id=f"native-{index}", format="docx", title="Store review", surface="business",
        contents=(NativeContent(source_artifact_id="ART-SOURCE", section_index=index),)) for index in range(12))
    rendered = {plan.artifact_id: render_native_corpus(world, plan) for plan in plans}
    workload = plan_native_workload(world, rendered, NativeWorkloadPlan(use_case_id="review", objective="Review store unit evidence.",
        formats=("docx",), operations=("read",), max_tasks=64, discovery_scope="artifact"))
    cases = native_task_cases(workload.tasks, rendered, namespace="northstar/seed-8128", world=world)
    return world, rendered, workload, cases


def test_byte_outcomes_and_private_lineage_survive_the_bridge(corpus: tuple) -> None:
    _, rendered, workload, cases = corpus
    assert len(cases) == 24 and len(set(evidence_components(cases).values())) == 12
    inputs = {key: result.payload for key, result in rendered.items()}
    replies = {task.id: reference_submission(task, inputs) for task in workload.tasks}
    report = native_run_report(cases, inputs, replies, agent="reference", agent_identity={"kind": "byte-reference", "version": "v1"})
    assert all(row.score.passed and row.score.observed == ("outcomes",) for row in report.results)
    assert all(row.score.plan.score == 0 and row.score.trajectory.score == 0 for row in report.results)
    first = cases[0]
    replies[first.id] = NativeSubmission()
    failed = native_run_report(cases, inputs, replies, agent="reference", agent_identity={"kind": "byte-reference", "version": "v1"})
    found = autopsy(failed, cases=cases)
    assert found.failing == 1 and found.clusters[0].key == "outcomes.answer_below_threshold"
    assert "answer_set_mismatch" in failed.results[0].answer
    assert first.row["native_task"] == next(task for task in workload.tasks if task.id == first.id).model_dump(mode="json")
    assert not audit_splits(cases[:1], cases[1:]).isolated


def test_bridge_refuses_missing_replies_changed_bytes_and_forged_lineage(corpus: tuple) -> None:
    world, rendered, workload, cases = corpus
    inputs = {key: result.payload for key, result in rendered.items()}
    replies = {task.id: reference_submission(task, inputs) for task in workload.tasks}
    with pytest.raises(ValueError, match="complete replies"):
        native_run_report(cases, inputs, {}, agent="test", agent_identity={"version": "v1"})
    key = workload.tasks[0].inputs[0].artifact_id
    with pytest.raises(ValueError, match="source bytes changed"):
        native_run_report(cases, {**inputs, key: inputs[key] + b"changed"}, replies,
            agent="test", agent_identity={"version": "v1"})
    original = rendered[key]
    entry = original.manifest.evidence[0].model_copy(update={"fact_ids": ("FACT-9999",)})
    forged = replace(original, manifest=original.manifest.model_copy(update={"evidence": (entry, *original.manifest.evidence[1:])}))
    with pytest.raises(ValueError, match="unknown canonical facts"):
        native_task_cases(workload.tasks, {**rendered, key: forged}, namespace="northstar/seed-8128", world=world)


def test_bridge_requires_grounded_supported_source_lineage(corpus: tuple) -> None:
    world, rendered, workload, _ = corpus
    task = workload.tasks[0]
    for changed in (task.model_copy(update={"inputs": ()}), task.model_copy(update={"inputs": (
            task.inputs[0].model_copy(update={"format": "pdf"}),)})):
        with pytest.raises(ValueError, match="grounded DOCX, PPTX or XLSX inputs"):
            native_task_cases((changed,), rendered, namespace="northstar/seed-8128", world=world)


def test_native_grader_pins_absence_of_unused_optional_parsers(monkeypatch: pytest.MonkeyPatch) -> None:
    from importlib.metadata import PackageNotFoundError

    from worldloom import native_eval_bridge
    def installed(name: str) -> str:
        if name in {"python-pptx", "openpyxl"}:
            raise PackageNotFoundError(name)
        return "installed"
    monkeypatch.setattr(native_eval_bridge, "version", installed)
    identity = native_grader_identity()
    assert identity["dependencies"]["python-pptx"] == identity["dependencies"]["openpyxl"] == "absent"
    assert identity["dependencies"]["python-docx"] == "installed"


def test_target_schema_failures_are_observed_outcomes(corpus: tuple) -> None:
    _, rendered, workload, cases = corpus
    inputs = {key: result.payload for key, result in rendered.items()}
    replies: dict[str, Any] = {task.id: reference_submission(task, inputs) for task in workload.tasks}
    replies[cases[0].id] = {"answers": "invented agent success", "passed": True}
    report = native_run_report(cases, inputs, replies, agent="test", agent_identity={"command": "target-v1"})
    assert not report.results[0].score.passed
    assert report.results[0].score.observed == ("outcomes",)
    assert report.results[0].notes == ("submission_schema_invalid",)
    assert all(result.score.passed for result in report.results[1:])


def test_runner_preflight_refuses_relabeling_source_independence(corpus: tuple) -> None:
    _, rendered, _, cases = corpus
    def submit(*_: Any) -> NativeSubmission:
        raise AssertionError("provenance must be checked before invoking the target")
    runner = native_runner(rendered, submit, namespace="northstar/seed-8128", submit_identity={"command": "target-v1"})
    first = cases[0]
    forged_facts = first.model_copy(update={"row": {**first.row, "expected_fact_ids": ["FACT-9999"]}})
    with pytest.raises(ValueError, match="evidence lineage"):
        runner.validate_cases((forged_facts,))
    forged_dimension = first.model_copy(update={"dimensions": {**first.dimensions, "independent_unit": "invented"}})
    with pytest.raises(ValueError, match="dimensions"):
        runner.validate_cases((forged_dimension,))
    rewritten = first.row["native_lineage"][0]
    rewritten = {**rewritten, "fact_ids": ["FACT-9999"], "evidence_ids": ["invented"], "manifest_digest": "invented"}
    forged_receipt = first.model_copy(update={"row": {**first.row, "native_lineage": [rewritten],
        "expected_fact_ids": ["FACT-9999"], "expected_evidence_ids": ["invented"]},
        "outcomes": first.outcomes.model_copy(update={"unstructured": first.outcomes.unstructured.model_copy(
            update={"required_fact_ids": ("FACT-9999",)})})})
    with pytest.raises(ValueError, match="actual source manifests"):
        runner.validate_cases((forged_receipt,))


def test_runner_refuses_stale_sources_before_cache_lookup_and_changes_repeat_request_ids(corpus: tuple, tmp_path: Path) -> None:
    _, rendered, _, cases = corpus
    ids = []
    def submit(agent: Any, public: dict, inputs: dict) -> NativeSubmission:
        assert "native_task" not in public and "expected" not in public and "experiment" not in public
        ids.append(public["execution_id"])
        return NativeSubmission()
    runner = native_runner(rendered, submit, namespace="northstar/seed-8128", submit_identity={"command": "native-test-v1"})
    agent = ScriptedAgent([], name="native-test")
    identity = runner.grading_identity(NativeGrader())
    for repeat in (1, 2):
        runner.run_experiment(cases[:1], agent, directory=tmp_path / str(repeat), label="train", repeat=repeat, grader=identity)
    assert ids[0] != ids[1]
    source_id = next(iter(runner.rendered))
    runner.rendered[source_id] = replace(runner.rendered[source_id], payload=runner.rendered[source_id].payload + b"changed")
    with pytest.raises(ValueError, match="source bytes differ"):
        runner.grading_identity(NativeGrader())


class _PolicyAgent:
    def __init__(self, pack: Any) -> None:
        self.name = agent_name("native-test", pack)
        self.pack_record = pack_record(pack)
        self.skilled = "verify" in pack.body.skills

    def fingerprint(self) -> dict:
        return {"kind": "native-test", "policy": self.pack_record["digest"]}

    def run(self, *_: Any) -> AgentResponse:
        raise AssertionError("the native runner uses its public byte submission seam")


def _proposal(payload: dict) -> dict:
    return {"request_id": payload["request_id"], "message": "revised",
        "proposal": {"name": payload["draft"]["name"], "body": {**payload["draft"]["body"],
            "skills": {"verify": "Find the requested business evidence in the supplied native bytes and cite its actual native location."}}}}


def test_real_native_failure_drives_qualified_improvement_with_fresh_repeats(
    corpus: tuple, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, rendered, _, cases = corpus
    train = tuple(case for case in cases if int(case.row["expected_fact_ids"][0].split("-")[1]) < 4)
    held = tuple(case for case in cases if case not in train)
    executions: list[tuple[str, str]] = []
    def submit(agent: Any, public: dict, inputs: dict) -> NativeSubmission:
        assert "expected" not in public and "native_task" not in public
        assert "experiment" not in public
        assert str(tmp_path) not in json.dumps(public)
        executions.append((public["id"], public["execution_id"]))
        if not agent.skilled:
            return NativeSubmission()
        source = public["inputs"][0]
        units = inspect_artifact(inputs[source["artifact_id"]], source["format"]).units
        answer_id = public["answers"][0]["assertion_id"]
        if answer_id == "evidence":
            unit = next(unit for unit in units if unit.text.startswith("Units for store:"))
        else:
            unit = next(unit for unit in units if "/row:2/cell:4" in unit.locator)
        return NativeSubmission(answers=(NativeAnswer(assertion_id=answer_id, value=unit.text,
            citations=(NativeCitation(artifact_id=source["artifact_id"], locator=unit.locator),)),))
    runner = native_runner(rendered, submit, namespace="northstar/seed-8128", submit_identity={"command": "native-business-parser-v1"})
    report = improve(packkit.resolve("agent:baseline"), train, holdout=held, run=runner,
        agent_for=_PolicyAgent, exchange=_proposal, out=tmp_path, rater=NativeGrader(), rounds=1,
        repeats=2, ablate=False, qualification=QualificationPolicy(trials=2, min_units=2))
    receipt = report.rounds[0]
    assert receipt.decision == "promoted", receipt.reasons
    assert receipt.holdout.independent_units == 4
    assert report.grader["native"]["digest"] in NativeGrader().name
    assert len(executions) == len({execution for _, execution in executions})
    reservation = json.loads((tmp_path / "qualification" / "trials" / "001.json").read_text())
    assert reservation["grader"]["native_submit"] == {"command": "native-business-parser-v1"}
    executed = len(executions)
    # Reconstruct an interrupted round from existing executions and its sealed
    # reservation. This exercises tuple/list JSON identity replay, not a skipped round.
    (tmp_path / "rounds" / "001.json").unlink()
    (tmp_path / "improve.json").unlink()
    resumed = improve(packkit.resolve("agent:baseline"), train, holdout=held, run=runner,
        agent_for=_PolicyAgent, exchange=_proposal, out=tmp_path, rater=NativeGrader(), rounds=1,
        repeats=2, ablate=False, qualification=QualificationPolicy(trials=2, min_units=2))
    assert resumed.promotions == report.promotions == 1
    assert len(executions) == executed
    assert resumed.rounds[0] == receipt
    runner.submit_identity = {"command": "native-business-parser-v2"}
    with pytest.raises(ValueError, match="sealed qualification"):
        improve(packkit.resolve("agent:baseline"), train, holdout=held, run=runner,
            agent_for=_PolicyAgent, exchange=_proposal, out=tmp_path, rater=NativeGrader(), rounds=1,
            repeats=2, ablate=False, qualification=QualificationPolicy(trials=2, min_units=2))
    assert len(executions) == executed
    runner.submit_identity = {"command": "native-business-parser-v1"}
    from worldloom import native_eval_bridge
    original_identity = native_grader_identity()
    monkeypatch.setattr(native_eval_bridge, "native_grader_identity", lambda: {**original_identity, "digest": "changed"})
    with pytest.raises(ValueError, match="native grader identity changed"):
        improve(packkit.resolve("agent:baseline"), train, holdout=held, run=runner,
            agent_for=_PolicyAgent, exchange=_proposal, out=tmp_path, rater=NativeGrader(), rounds=1,
            repeats=2, ablate=False, qualification=QualificationPolicy(trials=2, min_units=2))
    assert len(executions) == executed
