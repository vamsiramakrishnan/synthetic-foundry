from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from worldloom.native_corpus import NativeContent, NativeCorpusPlan
from worldloom.native_tasks import (
    NativeAssertion,
    NativeCitation,
    NativeInput,
    NativeTask,
)
from worldloom.studio import RunOptions
from worldloom.studio.models import ProjectSpec
from worldloom.studio.native import execute
from worldloom.studio.native_calibration import (
    NativeCalibrationPlan,
    NativeNoiseVariant,
    seal,
)
from worldloom.studio.native_noise import interventions


def _variant(name, count):
    return NativeNoiseVariant(name=name, distractor_files=count)


def test_variant_contract_and_total_budget():
    from test_native_calibration import _tasks

    with pytest.raises(ValueError, match="distinct interventions"):
        NativeCalibrationPlan(cohort="test", noise_variants=(_variant("a", 0), _variant("b", 0)))
    with pytest.raises(ValueError, match="explicit zero-distractor baseline"):
        NativeCalibrationPlan(cohort="test", noise_variants=(_variant("context", 1),))
    tasks = _tasks(128)
    plan = NativeCalibrationPlan(cohort="test", noise_variants=(_variant("baseline", 0), _variant("context", 1)),
                                 max_training_attempts=63, min_support=32)
    sealed = seal(plan, tasks, {task.id: task.id for task in tasks})
    assert len(sealed["samples"]["train"]) == 31
    assert not sealed["feasible"]
    assert any("insufficient_native_budget:train" in finding for finding in sealed["findings"])
    noise = interventions(tasks, {task.id: task.id for task in tasks}, plan.noise_variants, sealed)
    assert not noise["feasible"]
    assert all(not artifacts for rows in noise["candidates"].values() for artifacts in rows.values())


@pytest.mark.parametrize("missing_distractors, fail_holdout", [(False, False), (True, False), (False, True)])
def test_native_noise_selection_is_training_only_bounded_disjoint_and_replayed(tmp_path, monkeypatch, missing_distractors, fail_holdout):
    from test_studio_native import _setup

    import worldloom.studio.checkpoints as checkpoints

    studio, original_job = _setup(tmp_path, monkeypatch)
    base = ProjectSpec.model_validate(studio.store.get(original_job["project"])["spec"])
    world, snapshot = studio.snapshot(base)
    source = world.artifact_irs[0]
    facts = tuple(world.facts[0].model_copy(update={"id": f"FACT-{i}"}) for i in range(8))
    sections = [source.sections[0].model_copy(update={"body": "{{fact:" + fact.id + "}}", "fact_ids": [fact.id]})
                for fact in facts]
    world = replace(world, _facts=facts, _artifact_irs=(source.model_copy(update={"sections": sections}),))
    monkeypatch.setattr(studio, "snapshot", lambda spec: (world, snapshot))
    copies = 1 if missing_distractors else 2
    plans = tuple(NativeCorpusPlan(artifact_id=f"ART-{i}-{j}", format="xlsx", title="Receipt",
                  contents=(NativeContent(source_artifact_id=source.id, section_index=i),))
                  for i in range(8) for j in range(copies))
    tasks = tuple(NativeTask(id=f"task-{i}-{j}", use_case_id=base.use_cases[0].id, operation="read", prompt="Read disposition",
                  inputs=(NativeInput(artifact_id=f"ART-{i}-{j}", format="xlsx", path=f"{i}-{j}.xlsx", sha256=""),),
                  assertions=(NativeAssertion(id="status", target=NativeCitation(
                      artifact_id=f"ART-{i}-{j}", locator="sheet:Evidence/cell:B2")),))
                  for i in range(8) for j in range(copies))
    plan = NativeCalibrationPlan(cohort="scripted-intervention-protocol", target_low=.1, target_high=.9,
                                 min_support=4, max_training_attempts=8, max_holdout_attempts=4,
                                 holdout_percent=50, noise_variants=(_variant("baseline", 0), _variant("context", 1)))
    project = studio.store.create(base.model_copy(update={"native_corpus": plans, "native_tasks": tasks,
                                                         "native_calibration": plan}))
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="native"))
    root = studio.path("native", job["id"])
    calls = []

    def respond(command, payload, **kwargs):
        assert not missing_distractors
        index = len(calls)
        calls.append(payload)
        assert (root / "noise-seal.json").exists()
        required = payload["task"]["inputs"][0]["artifact_id"]
        # Files from other periods are never visible through a distractor.
        assert {key.rsplit("-", 1)[0] for key in payload["input_files"]} == {required.rsplit("-", 1)[0]}
        assert len(payload["input_files"]) == (1 if index < 4 else 2)
        if index >= 8:
            import json
            assert json.loads((root / "calibration-selection.json").read_text())["variant"] == "context"
        # Scripted responses exercise selection, not measured model capability.
        answers = [] if index < 4 or index % 2 or (fail_holdout and index >= 8) else [{"assertion_id": "status", "value": "Receiving confirmed",
                  "citations": [{"artifact_id": required, "locator": "sheet:Evidence/cell:B2"}]}]
        return SimpleNamespace(document={"request_id": payload["request_id"], "submission": {"answers": answers}})

    monkeypatch.setattr(checkpoints, "run_exec", respond)
    result = execute(studio, job, harness_command="scripted-intervention-protocol", timeout=30)
    if missing_distractors:
        assert not calls and result["status"] == "blocked"
        assert result["calibration"]["findings"][0].startswith("insufficient_native_distractors")
    else:
        assert len(calls) == 12
        assert result["noise_calibrated"] == result["calibrated"] == (not fail_holdout)
        assert result["status"] == ("blocked" if fail_holdout else "complete")
        assert result["calibration"]["selected_variant"] == "context"
        assert [row["accepted"] for row in result["calibration"]["candidates"]] == [False, True]
        assert result["calibration"]["holdout"]["accepted"] == (not fail_holdout)
        train = {row["evidence_component"] for row in result["outcomes"] if row["split"] == "train"}
        holdout = {row["evidence_component"] for row in result["outcomes"] if row["split"] == "holdout"}
        assert not train & holdout
    monkeypatch.setattr(checkpoints, "run_exec", lambda *a, **k: pytest.fail("replay called target"))
    assert execute(studio, job, harness_command="scripted-intervention-protocol", timeout=30) == result
    (root / "noise-seal.json").write_text("{}")
    with pytest.raises(ValueError, match="changed after checkpoint"):
        execute(studio, job, harness_command="scripted-intervention-protocol", timeout=30)
