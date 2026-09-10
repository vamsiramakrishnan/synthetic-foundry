from __future__ import annotations

import json
import shlex
import sys

import pytest

from worldloom.corpus import write_json
from worldloom.evals.calibration import NoiseVariant
from worldloom.evals.dataset import _files, verify_dataset
from worldloom.execseam import ExecReply
from worldloom.studio import RunOptions, Studio, preset
from worldloom.studio.calibration import CompanyCalibrationPlan, independent_samples
from worldloom.studio.checkpoints import Exchanges, save_world
from worldloom.studio.retail_pilot import pilot_project
from worldloom.studio.worker import run_job


def test_sample_support_uses_transitive_evidence_and_fair_case_order():
    def row(identifier, case, evidence, split="train"):
        return {"id": identifier, "stratum": case, "case_id": identifier,
                "evidence": evidence, "split": split}
    rows = [row("a", "inventory", ["x"]), row("b", "inventory", ["x", "y"]),
            row("c", "inventory", ["y"]), row("d", "invoice", ["y"]),
            row("e", "inventory", ["z"]), row("f", "invoice", ["w"])]
    sample = independent_samples(rows)
    assert [r["id"] for r in sample] == ["a", "d", "e", "f"]
    with pytest.raises(ValueError, match="crosses dataset splits"):
        independent_samples([*rows, row("leak", "invoice", ["x"], "test")])


def test_harness_exchange_replays_and_refuses_deleted_prefix_or_tail(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("worldloom.studio.checkpoints.run_exec", lambda command, payload, **kw:
                        (calls.append(payload) or ExecReply(document={"answer": payload["q"]}, stderr_tail="")))
    exchange = Exchanges(tmp_path, "scripted", 1)
    expected = [exchange({"q": i}).document for i in range(2)]
    replay = Exchanges(tmp_path, "scripted", 1)
    assert [replay({"q": i}).document for i in range(2)] == expected and len(calls) == 2
    original = (tmp_path / "000000.json").read_bytes()
    (tmp_path / "000000.json").unlink()
    with pytest.raises(ValueError, match="missing turn"):
        Exchanges(tmp_path, "scripted", 1)
    (tmp_path / "000000.json").write_bytes(original)
    (tmp_path / "000001.json").unlink()
    with pytest.raises(ValueError, match="journal changed"):
        Exchanges(tmp_path, "scripted", 1)
    assert len(calls) == 2


def test_unconfigured_foundry_refuses_before_building_company(tmp_path, monkeypatch):
    studio = Studio(tmp_path)
    project = studio.store.create(preset())
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="foundry"))
    monkeypatch.setattr(studio, "snapshot", lambda *_: pytest.fail("built before requirements"))
    result = studio.execute(job["id"])
    assert result["status"] == "blocked" and result["stage"] == "requirements"
    assert not studio.path("datasets").exists()


def test_world_stage_recovers_interruption_before_intent_write(tmp_path):
    from worldloom import RetailWorld
    pending = tmp_path / "stage.pending"
    pending.mkdir()
    world = RetailWorld(seed=4).build()
    save_world(tmp_path / "stage", {"input": "same"}, world, {"ok": True})
    assert (tmp_path / "stage" / "receipt.json").exists()


def test_paused_jobs_can_resume_but_complete_results_cannot(tmp_path):
    studio = Studio(tmp_path)
    project = studio.store.create(preset())
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="foundry", batch_limit=1))
    studio.store.finish(job["id"], result={"status": "paused"})
    assert studio.store.job(job["id"])["status"] == "paused"
    assert studio.store.retry(job["id"])["status"] == "queued"
    studio.store.finish(job["id"], result={"status": "complete"})
    with pytest.raises(ValueError, match="only failed"):
        studio.store.retry(job["id"])


def test_connected_foundry_qualifies_trials_freezes_and_replays(tmp_path, monkeypatch):
    # An actual subprocess deliberately does no work. This verifies observed
    # failure accounting and recovery, not a model's reasoning capability.
    adapter = tmp_path / "target.py"
    adapter.write_text('import json,sys\np=json.load(sys.stdin)\nprint(json.dumps({"request_id":p["request_id"],"final":"No action taken"}))\n')
    command = shlex.join([sys.executable, str(adapter)])
    import os
    import subprocess
    if os.name == "nt":
        command = subprocess.list2cmdline([sys.executable, str(adapter)])
    spec = pilot_project(count=12).model_copy(update={
        "split_weights": {"train": 1, "test": 1},
        "calibration": CompanyCalibrationPlan(variants=(NoiseVariant(name="clean", budget={}, niche="control"),),
            cohort="scripted-no-action-test/v1", target_low=0, target_high=1,
            min_support=1, max_training_attempts=3, max_holdout_attempts=3, max_turns=1),
    })
    studio = Studio(tmp_path / "workspace")
    project = studio.store.create(spec)
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="foundry"))
    assert run_job(studio, job["id"], harness_command=command)
    finished = studio.store.job(job["id"])
    assert finished["status"] == "complete", finished
    result = finished["result"]
    assert result["status"] == "complete", result
    selected = result["calibration"]["variants"][0]
    assert selected["quality"]["reader"]["status"] == "not_applicable"
    assert all(e["trials"] == 1 and e["successes"] == 0 for e in selected["training"].values())
    assert all(e["trials"] == 1 and e["successes"] == 0 for e in selected["holdout"].values())
    destination = studio.dataset_location(project["id"], project["revision"])
    assert verify_dataset(destination).companies == 1
    before = _files(destination)
    monkeypatch.setattr("worldloom.execseam.run_exec", lambda *_args, **_kwargs: pytest.fail("replay called harness"))
    replayed = Studio(studio.root).execute(job["id"], harness_command=command)
    assert replayed == result
    assert _files(destination) == before
    manifest = json.loads((destination / "manifest.json").read_text())
    write_json(destination / "manifest.json", {**manifest, "complete": False})
    with pytest.raises(ValueError, match="manifest or files changed"):
        studio.dataset_location(project["id"], project["revision"])
