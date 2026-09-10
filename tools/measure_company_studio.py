"""Exercise one company across review and state-changing operational use cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worldloom.enterprise_specs import (
    ContentAction,
    DestinationRole,
    Operation,
    SourceRole,
)
from worldloom.evals import FrozenCompanyBuilder, compile_dataset
from worldloom.evals.dataset import _files, verify_dataset
from worldloom.providers import digest
from worldloom.studio import ProjectSpec, Studio, UseCase, preset
from worldloom.synthesis import retail, with_parameters


def pilot() -> ProjectSpec:
    spec = preset()
    original = spec.use_cases[0]
    program = with_parameters(retail(stores=6, products=8, ticks=36), {"initial_stock": 8, "target_stock": 15})
    assert original.scenario is not None
    workflow = original.scenario.additional_workflows[0].model_copy(update={
        "name": "inventory_escalation", "purpose": "escalate a replenishment exception for corrective action",
        "sources": (SourceRole(connector="servicenow", entities=("incident",)),
                    SourceRole(connector="email", entities=("thread",))),
        "destinations": (DestinationRole(connector="jira", entities=("issue",),
                                         operations=(Operation.PATCH,), target_state="In Progress", target_state_field="status"),),
        "content_actions": (ContentAction.CLASSIFY,),
    })
    profile = original.scenario.model_copy(update={"name": "inventory-escalation", "workflows": (workflow.name,),
                                                   "additional_workflows": (workflow,)})
    cases = (original.model_copy(update={"count": 48, "simulation": program}),
             UseCase(id="replenishment-escalation", title="Escalate replenishment exceptions",
                     objective=workflow.purpose, owner=spec.structure.bus[-2].name if spec.structure else "",
                     count=48, scenario=profile, simulation=program, incident_rule=original.incident_rule))
    return ProjectSpec.model_validate(spec.model_copy(update={"use_cases": cases, "pool_size": 16,
                                                            "planning_budget": 512, "minimum_tasks": 8,
                                                            "max_per_task": 12, "max_per_request": 8}).model_dump(mode="json"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    studio = Studio(args.out)
    spec = pilot()
    project = studio.store.create(spec)
    world, snapshot = studio.snapshot(spec)
    plan = studio.dataset_plan(project["id"], project["revision"], spec, snapshot / "world")
    target = args.out / "pilot-dataset"
    run = compile_dataset(plan, target, builder=FrozenCompanyBuilder(world, seed=spec.seed))
    before = _files(target)
    assert verify_dataset(target) == run.report
    replay = compile_dataset(plan, target, replay_only=True)
    assert replay.report == run.report and _files(target) == before
    worlds = [_files(path / "world") for path in (target / "batches").iterdir() if (path / "world").exists()]
    canonical = _files(target / "company/world")
    assert all(value == canonical for value in worlds)
    revised = spec.model_copy(update={"max_batches": spec.max_batches + 1})
    _, same = studio.snapshot(revised)
    result = {"scope": "one company; inventory review and state-changing replenishment escalation",
              "reference_qualification_only": True, "real_agent_difficulty_measured": False,
              "plan_digest": digest(plan.model_dump(mode="json")), "report": run.report.model_dump(mode="json"),
              "reproduce": "python tools/measure_company_studio.py --out ./studio-pilot --report ./studio-pilot.json",
              "one_world_across_batches": all(value == canonical for value in worlds),
              "identical_offline_replay": before == _files(target),
              "eval_plan_change_reuses_company": same == snapshot,
              "generated_divisions": [unit.name for unit in world.business_units]}
    repo = Path(__file__).resolve().parents[1]
    paths = ["src/worldloom/evals/company_dataset.py", "src/worldloom/evals/dataset.py",
             "src/worldloom/studio/service.py", "src/worldloom/studio/models.py", "tools/measure_company_studio.py"]
    result["source_sha256"] = {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in paths}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "plan"}, sort_keys=True))
    run.raise_if_incomplete()


if __name__ == "__main__":
    main()
