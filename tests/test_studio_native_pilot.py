from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from worldloom.narrative import DeterministicProvider
from worldloom.native_corpus import render_native_corpus
from worldloom.native_reference import qualify_native_task
from worldloom.studio import Studio
from worldloom.studio.native_pilot import pilot_base, pilot_project


@pytest.fixture(scope="module")
def retail_world(tmp_path_factory):
    base = pilot_base(periods=1)
    world, _ = Studio(tmp_path_factory.mktemp("native-pilot")).snapshot(base)
    return base, world.narrate(DeterministicProvider())


def test_native_pilot_qualifies_real_episode_facts_and_preserved_updates(retail_world):
    base, world = retail_world
    spec = pilot_project(world, base, units=8)
    assert world.recipe is not None and world.ledger
    assert {task.operation for task in spec.native_tasks} == {"read", "analyze", "update", "create"}
    rendered = {plan.artifact_id: render_native_corpus(world, plan) for plan in spec.native_corpus}
    for task in spec.native_tasks:
        grade = qualify_native_task(task, {item.artifact_id: rendered[item.artifact_id].payload for item in task.inputs})
        assert grade.passed, (task.id, grade.findings)
    book = rendered[spec.native_corpus[2].artifact_id]
    calculation = spec.native_tasks[2].assertions[0].calculation
    assert calculation is not None
    cells = {item.locator: item.fact_ids[0] for item in book.manifest.evidence if item.locator.startswith("sheet:Facts/")}
    facts = {fact.id: fact for fact in world.facts}
    actual, budget = [facts[cells[ref.locator]] for ref in calculation.operands]
    assert (actual.subject, actual.period, actual.value.unit) == (budget.subject, budget.period, budget.value.unit)
    assert actual.kind == "financial.revenue.actual" and budget.kind == "financial.revenue.budget"
    assert spec.native_tasks[1].assertions[0].target.locator == "slide:8/notes"


def test_native_pilot_shortage_cannot_be_padded(retail_world):
    base, world = retail_world
    with pytest.raises(ValueError, match="generate and narrate more monthly episodes"):
        pilot_project(world, base, units=200)
    with pytest.raises(ValueError, match="selected company and seed"):
        pilot_project(world, base.model_copy(update={"seed": 7}), units=8)
    with pytest.raises(ValueError, match="monthly episodes"):
        pilot_base(periods=25)


def test_native_pilot_tool_uses_studio_and_replays_without_target_claim(tmp_path):
    script = Path(__file__).resolve().parents[1] / "tools" / "measure_native_pilot.py"
    report = tmp_path / "report.json"
    argv = [sys.executable, str(script), "--out", str(tmp_path / "studio"), "--report", str(report), "--periods", "1", "--units", "8"]
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    value = json.loads(report.read_text())
    assert value["reference_qualified_tasks"] == 6
    assert value["result"]["observed_trials"] == 0
    assert value["reference_authoring_only"] and value["byte_identical_run_replay"]
    assert value["result"]["evidence_components"] == 1
    assert not value["editorial_realism_measured"]
    repeated = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert json.loads(report.read_text()) == value
