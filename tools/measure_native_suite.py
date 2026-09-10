"""Measure a native proposal against accepted company prose without target calls."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worldloom.corpus import write_json
from worldloom.native_corpus import render_native_corpus
from worldloom.native_tasks import public_contract
from worldloom.providers import digest
from worldloom.studio import NativeSuiteRequest, ProjectSpec, Studio
from worldloom.studio.native import _components, source_world
from worldloom.studio.native_calibration import NativeCalibrationPlan, seal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--use-case", required=True)
    parser.add_argument("--units", type=int, default=2)
    parser.add_argument("--max-cases", type=int, default=12)
    parser.add_argument("--source-artifact-id", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    studio = Studio(args.workspace)
    project = studio.store.get(args.project)
    request = NativeSuiteRequest(use_case_id=args.use_case, minimum_units=args.units,
        max_cases=args.max_cases, source_artifact_ids=tuple(args.source_artifact_id))
    proposal = studio.prepare_native(args.project, project["revision"], request)
    spec = ProjectSpec.model_validate(proposal["spec"])
    world, _ = source_world(studio, spec, args.project)
    evidence = {}
    for plan in spec.native_corpus:
        rendered = render_native_corpus(world, plan)
        evidence[plan.artifact_id] = {"fact:" + f for e in rendered.manifest.evidence for f in e.fact_ids} | {
            "section:" + digest([e.source_artifact_id, e.section_index]) for e in rendered.manifest.evidence}
    components = _components(spec.native_tasks, evidence)
    support = seal(NativeCalibrationPlan(cohort="unmeasured-pilot-target"), list(spec.native_tasks), components)
    queries = [public_contract(task) for task in spec.native_tasks]
    report = {"schema": "worldloom.native-suite-measurement/v1", "company": world.company.name,
        "seed": spec.seed, "episodes": list(spec.episodes), "request": request.model_dump(mode="json"),
        "proposal_digest": digest(proposal["spec"]), "summary": proposal["summary"],
        "evidence_components": len(set(components.values())), "default_calibration_feasible": support["feasible"],
        "support": support["support"], "observed_target_trials": 0, "calibrated": False,
        "queryset_digest": digest(queries), "sample_questions": [t.prompt for t in spec.native_tasks[:10]]}
    write_json(args.report, report)
    print(json.dumps({"report": str(args.report), "tasks": len(queries), "evidence_components": report["evidence_components"]}))


if __name__ == "__main__":
    main()
