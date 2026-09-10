from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Company,
    Quantity,
)
from worldloom.native_corpus import render_native_corpus
from worldloom.providers import digest
from worldloom.studio import (
    NativeSuiteRequest,
    ProjectSpec,
    RunOptions,
    Studio,
    StudioConflict,
    UseCase,
    preset,
)
from worldloom.studio.native import _components
from worldloom.studio.native_suite import propose
from worldloom.world import World


def _world():
    facts = tuple(CanonicalFact(id=f"FACT-{i:04}", kind="retail.units", subject=f"store:{i}",
        period="2026-01", value=Quantity(amount=100 + i, unit="units"),
        valid_from=datetime(2026, 1, 1, tzinfo=UTC), authority=Authority.SYSTEM_OF_RECORD) for i in range(8))
    sections = [ArtifactSection(heading="Store evidence", body=f"Units: {{{{fact:{f.id}}}}}", fact_ids=[f.id]) for f in facts]
    return World(seed=8128, company=Company(id="CO-1", name="Northstar Retail", industry="retail", headquarters="Sydney",
        fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-SOURCE", intent_id="INTENT-1", title="Store review", sections=sections),))


def _spec():
    return preset().model_copy(update={"use_cases": (UseCase(id="review", title="Review store evidence", objective="Read and reconcile evidence"),)})


def test_native_suite_compiles_all_formats_operations_and_independent_cases():
    world, spec = _world(), _spec()
    request = NativeSuiteRequest(use_case_id="review", minimum_units=2, max_cases=5)
    result = propose(world, spec, request)
    assert result == propose(world, spec, request)
    summary = result["summary"]
    assert (summary["prepared_cases"], summary["case_shortfall"], summary["tasks"]) == (4, 1, 40)
    assert summary["reference_qualified"] == 40
    proposal = ProjectSpec.model_validate(result["spec"])
    assert {t.operation for t in proposal.native_tasks} == {"read", "analyze", "update", "create"}
    evidence = {}
    for plan in proposal.native_corpus:
        rendered = render_native_corpus(world, plan)
        evidence[plan.artifact_id] = {"fact:" + f for e in rendered.manifest.evidence for f in e.fact_ids}
    components = _components(proposal.native_tasks, evidence)
    assert len(set(components.values())) == 4


def test_native_suite_shared_facts_never_recycled_as_independent_cases():
    world = _world()
    sections = [s.model_copy(update={"body": s.body + " Shared: {{fact:FACT-0000}}"}) for s in world.artifact_irs[0].sections]
    world = replace(world, _artifact_irs=(world.artifact_irs[0].model_copy(update={"sections": sections}),))
    result = propose(world, _spec(), NativeSuiteRequest(use_case_id="review", formats=("docx",), operations=("read",), minimum_units=2, max_cases=4))
    assert result["summary"]["prepared_cases"] == result["summary"]["source_components"] == 1
    assert result["summary"]["case_shortfall"] == 3
    with pytest.raises(ValueError, match="selected company and seed"):
        propose(replace(world, seed=99), _spec(), NativeSuiteRequest(use_case_id="review"))


def test_native_suite_reports_missing_arithmetic_and_requires_owned_source_scope():
    spec = _spec()
    result = propose(_world(), spec, NativeSuiteRequest(use_case_id="review", formats=("xlsx",), operations=("analyze",), minimum_units=1, max_cases=2))
    assert result["summary"]["tasks"] == 0
    assert len(result["summary"]["unsupported"]) == 2
    assert result["spec"] == spec.model_dump(mode="json")
    owned = spec.model_copy(update={"use_cases": (spec.use_cases[0].model_copy(update={"owner": spec.structure.bus[0].name}),)})
    with pytest.raises(ValueError, match="explicit source_artifact_ids"):
        propose(_world(), owned, NativeSuiteRequest(use_case_id="review"))


def test_native_proposal_is_reviewable_revision_bound_and_requires_narration(tmp_path, monkeypatch):
    import worldloom.studio.native as native
    studio = Studio(tmp_path)
    project = studio.store.create(_spec())
    request = NativeSuiteRequest(use_case_id="review", formats=("docx",), operations=("read",), max_cases=2)
    with pytest.raises(ValueError, match="select accepted"):
        studio.prepare_native(project["id"], project["revision"], request)
    spec = ProjectSpec.model_validate({**project["spec"], "narration_job": digest("accepted")})
    project = studio.store.revise(project["id"], project["revision"], spec, reason="Select test narration")
    monkeypatch.setattr(native, "source_world", lambda *args: (_world(), tmp_path / "snapshot"))
    result = studio.prepare_native(project["id"], project["revision"], request)
    assert studio.store.get(project["id"])["spec"] == project["spec"]
    revised = studio.store.revise(project["id"], result["revision"], ProjectSpec.model_validate(result["spec"]), reason="Reviewed native suite")
    with pytest.raises(StudioConflict):
        studio.prepare_native(project["id"], project["revision"], request)
    description = studio.describe(project["id"])
    assert not any(f["code"] == "workflow_missing" for f in description["findings"])
    assert description["workflow"]["capabilities"]["native_ready"]
    assert description["revision"] == revised["revision"]


def test_workflow_readonly_and_advance_executes_one_stage(tmp_path, monkeypatch):
    studio = Studio(tmp_path)
    project = studio.store.create(_spec())
    monkeypatch.setattr(studio, "snapshot", lambda *args: pytest.fail("readiness generated a world"))
    report = studio.workflow(project["id"])
    assert report.next_action.operation == "build"
    assert studio.store.jobs() == []
    assert not (tmp_path / "snapshots").exists()
    runner = CliRunner()
    result = runner.invoke(app, ["studio", "next", project["id"], "-w", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["next_action"]["operation"] == "build"
    calls = []
    monkeypatch.setattr(studio, "execute", lambda job_id, **kwargs: calls.append(job_id) or {"snapshot": "test", "company": "Northstar"})
    result = studio.advance(project["id"], project["revision"])
    assert len(calls) == 1 and result["job"]["status"] == "complete"
    # Even if an external worker did not create the expected snapshot, repeat
    # advance cannot turn a recorded success into another target call.
    studio.advance(project["id"], project["revision"])
    assert len(calls) == 1


def test_select_narration_authenticates_before_revision(tmp_path, monkeypatch):
    import worldloom.studio.native as native
    studio = Studio(tmp_path)
    project = studio.store.create(_spec())
    calls = []
    monkeypatch.setattr(native, "source_world", lambda s, spec, p: calls.append(spec.narration_job) or (_world(), tmp_path))
    selected = studio.select_narration(project["id"], project["revision"], digest("narration"))
    assert calls == [digest("narration")]
    assert selected["spec"]["narration_job"] == calls[0]
    with pytest.raises(StudioConflict):
        studio.select_narration(project["id"], project["revision"], digest("other"))
    def refuse(*args):
        raise ValueError("selected narration changed after acceptance")
    monkeypatch.setattr(native, "source_world", refuse)
    with pytest.raises(ValueError, match="changed after acceptance"):
        studio.select_narration(project["id"], selected["revision"], digest("other"))
    assert studio.store.get(project["id"])["revision"] == selected["revision"]


def test_workflow_does_not_replay_blocked_native_measurement(tmp_path):
    studio = Studio(tmp_path)
    proposal = propose(_world(), _spec(), NativeSuiteRequest(use_case_id="review", formats=("docx",), operations=("read",), max_cases=1))
    project = studio.store.create(ProjectSpec.model_validate(proposal["spec"]))
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="native"))
    studio.store.finish(job["id"], result={"status": "blocked", "calibration": {"findings": ["insufficient_native_population"]}})
    report = studio.workflow(project["id"], harness_configured=True)
    stage = next(s for s in report.stages if s.id == "native")
    assert stage.status == "blocked" and stage.action.kind == "navigate"
    assert any(f["message"] == "insufficient_native_population" for f in report.findings)


def test_stale_narration_does_not_block_recovery_interview(tmp_path):
    from worldloom.studio.service import snapshot_intent
    studio = Studio(tmp_path)
    project = studio.store.create(_spec())
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="narrate"))
    studio.store.finish(job["id"], result={"snapshot": digest(snapshot_intent(_spec()))})
    changed = _spec().model_copy(update={"episodes": ("2026-01",), "narration_job": job["id"]})
    current = studio.store.revise(project["id"], project["revision"], changed, reason="Extend company history")
    request = studio.interview_request(project["id"], current["revision"], "Refresh the evidence for the new period")
    assert request["native_sources"]["status"] == "stale_narration"
    assert request["native_sources"]["sources"] == []


def test_partial_native_coverage_stays_actionable(tmp_path):
    studio = Studio(tmp_path)
    proposal = propose(_world(), _spec(), NativeSuiteRequest(use_case_id="review", formats=("docx",), operations=("read",), max_cases=1))
    spec = ProjectSpec.model_validate(proposal["spec"])
    spec = spec.model_copy(update={"use_cases": (*spec.use_cases, UseCase(id="other", title="Other review", objective="Review another process"))})
    project = studio.store.create(spec)
    stage = next(s for s in studio.workflow(project["id"]).stages if s.id == "native_contracts")
    assert stage.status != "complete" and "other" in stage.detail
