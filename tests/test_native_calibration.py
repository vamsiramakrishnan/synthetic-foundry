from __future__ import annotations

import pytest

from worldloom.native_tasks import (
    NativeAssertion,
    NativeCitation,
    NativeInput,
    NativeTask,
)
from worldloom.providers import digest
from worldloom.studio.native import _components
from worldloom.studio.native_calibration import NativeCalibrationPlan, seal, summarize


def _tasks(count=128):
    return [NativeTask(id=f"task-{i:04}", use_case_id="receiving", operation="read", prompt="Read disposition",
            inputs=(NativeInput(artifact_id=f"ART-{i}", format="xlsx", path=f"{i}.xlsx", sha256=""),),
            assertions=(NativeAssertion(id="status", target=NativeCitation(
                artifact_id=f"ART-{i}", locator="sheet:Evidence/cell:B2")),)) for i in range(count)]


def _outcomes(sealed):
    return [{"task_id": task, "trial_id": digest(task), "split": split, "passed": i % 2 == 0}
            for split, tasks in sealed["samples"].items() for i, task in enumerate(tasks)]


def test_native_seal_shared_facts_transitive_and_duplicate_support():
    tasks = _tasks(4)
    evidence = {"ART-0": {"fact:a"}, "ART-1": {"fact:a", "fact:b"},
                "ART-2": {"fact:b"}, "ART-3": {"fact:c"}}
    components = _components(tuple(tasks), evidence)
    assert components[tasks[0].id] == components[tasks[2].id]
    plan = NativeCalibrationPlan(cohort="scripted-protocol-test", holdout_percent=50)
    sealed = seal(plan, tasks, components)
    assert len(set(sealed["splits"][task.id] for task in tasks[:3])) == 1
    assert sum(map(len, sealed["samples"].values())) == 2
    assert seal(plan, list(reversed(tasks)), components)["samples"] == sealed["samples"]


def test_native_fixed_corpus_observed_wilson_and_holdout():
    tasks = _tasks()
    # Assertions differ, but the declared cohort measures the whole use-case,
    # operation and format population. Per-observation counts remain in receipts.
    tasks = [task.model_copy(update={"assertions": task.assertions +
             (task.assertions[0].model_copy(update={"id": "second-status"}),)}) if i % 3 == 0 else task
             for i, task in enumerate(tasks)]
    components = {task.id: digest(task.id) for task in tasks}
    plan = NativeCalibrationPlan(cohort="scripted-protocol-test", holdout_percent=50)
    sealed = seal(plan, tasks, components)
    outcomes = _outcomes(sealed)
    for split in ("train", "holdout"):
        summary = summarize(plan, tasks, outcomes, sealed, corpus_digest=digest("corpus"),
                            evaluator_digest=digest("script"), split=split)
        assert summary["accepted"]
        assert {row["features"]["values"]["assertion_count"] for row in summary["observations"]["observations"]} == {1, 2}
        estimate, = summary["estimates"].values()
        assert estimate["trials"] == 64 and estimate["successes"] == 32
        assert estimate["feature_schema"] == "native/v1"
        assert estimate["interval_low"] > .3 and estimate["interval_high"] < .7
    with pytest.raises(ValueError, match="duplicate support"):
        summarize(plan, tasks, outcomes + outcomes[:1], sealed, corpus_digest=digest("corpus"),
                  evaluator_digest=digest("script"), split="train")
    forged = [{**outcomes[0], "split": "holdout"}]
    with pytest.raises(ValueError, match="outside the sealed sample"):
        summarize(plan, tasks, forged, sealed, corpus_digest=digest("corpus"),
                  evaluator_digest=digest("script"), split="holdout")


def test_native_budget_and_insufficient_support_block():
    tasks = _tasks()
    plan = NativeCalibrationPlan(cohort="scripted-protocol-test", max_training_attempts=2,
                                 max_holdout_attempts=1)
    sealed = seal(plan, tasks, {task.id: digest(task.id) for task in tasks})
    assert len(sealed["samples"]["train"]) == 2 and len(sealed["samples"]["holdout"]) == 1
    summary = summarize(plan, tasks, _outcomes(sealed), sealed, corpus_digest=digest("corpus"),
                        evaluator_digest=digest("script"), split="train")
    assert not summary["accepted"]
    assert next(iter(summary["estimates"].values()))["status"] == "insufficient_data"


@pytest.mark.parametrize("broad_test_band, infeasible", [
    (True, ""), (False, ""), (True, "population"), (True, "training_budget"), (True, "holdout_budget")])
def test_native_studio_sealed_training_before_holdout_and_replay(tmp_path, monkeypatch, broad_test_band, infeasible):
    from test_studio_native import _setup

    from worldloom.native_corpus import NativeContent, NativeCorpusPlan
    from worldloom.studio import RunOptions
    from worldloom.studio.models import ProjectSpec
    from worldloom.studio.native import execute

    studio, original_job = _setup(tmp_path, monkeypatch)
    base = ProjectSpec.model_validate(studio.store.get(original_job["project"])["spec"])
    world, snapshot = studio.snapshot(base)
    source = world.artifact_irs[0]
    facts = tuple(world.facts[0].model_copy(update={"id": f"FACT-{i}"}) for i in range(4))
    sections = [source.sections[0].model_copy(update={"body": "{{fact:" + fact.id + "}}", "fact_ids": [fact.id]})
                for fact in facts]
    from dataclasses import replace
    world = replace(world, _facts=facts, _artifact_irs=(source.model_copy(update={"sections": sections}),))
    monkeypatch.setattr(studio, "snapshot", lambda spec: (world, snapshot))
    plans = tuple(NativeCorpusPlan(artifact_id=f"ART-{i}", format="xlsx", title="Receipt",
                  contents=(NativeContent(source_artifact_id=source.id, section_index=i),)) for i in range(4))
    tasks = tuple(task.model_copy(update={"use_case_id": base.use_cases[0].id}) for task in _tasks(4))
    plan = NativeCalibrationPlan(cohort="scripted-protocol-test", target_low=0 if broad_test_band else .3,
                                 target_high=1 if broad_test_band else .7,
                                 min_support=3 if infeasible == "population" else 2 if infeasible else 1,
                                 max_training_attempts=1 if infeasible == "training_budget" else 384,
                                 max_holdout_attempts=1 if infeasible == "holdout_budget" else 128,
                                 holdout_percent=50)
    project = studio.store.create(base.model_copy(update={"native_corpus": plans, "native_tasks": tasks,
                                                         "native_calibration": plan}))
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="native"))
    root = studio.path("native", job["id"])
    calls = []
    from types import SimpleNamespace

    import worldloom.studio.checkpoints as checkpoints

    def respond(command, payload, **kwargs):
        assert not infeasible, "known insufficient support must not spend target budget"
        # Deliberately no correct answers: this test validates observation and
        # replay plumbing under an explicit [0, 1] test band, not model quality.
        if len(calls) >= 2:
            assert (root / "calibration-training.json").exists()
        assert (root / "calibration-seal.json").exists()
        calls.append(payload)
        return SimpleNamespace(document={"request_id": payload["request_id"], "submission": {}})

    monkeypatch.setattr(checkpoints, "run_exec", respond)
    result = execute(studio, job, harness_command="scripted-protocol-test", timeout=30)
    accepted = broad_test_band and not infeasible
    assert result["calibrated"] == accepted and not result["noise_calibrated"]
    assert result["observed_trials"] == (0 if infeasible else 4 if broad_test_band else 2)
    assert result["passed_trials"] == 0
    assert result["status"] == ("complete" if accepted else "blocked")
    assert (root / "calibration-holdout.json").exists() == accepted
    assert (root / "qualification.json").exists()
    if infeasible:
        assert not calls
        assert all(row["planned"] > 0 for values in result["calibration"]["support"].values() for row in values.values())
        assert result["calibration"]["findings"][0].startswith("insufficient_native_")
    monkeypatch.setattr(checkpoints, "run_exec", lambda *a, **k: pytest.fail("replay called target"))
    assert execute(studio, job, harness_command="scripted-protocol-test", timeout=30) == result
    (root / "calibration-seal.json").write_text("{}")
    with pytest.raises(ValueError, match="changed after checkpoint"):
        execute(studio, job, harness_command="scripted-protocol-test", timeout=30)
