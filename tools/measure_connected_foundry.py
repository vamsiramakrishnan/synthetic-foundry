"""Measure real connected-case coverage without inventing model observations."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    from worldloom.corpus import write_json
    from worldloom.evals.company_dataset import load_dataset_plan
    from worldloom.evals.dataset import _files, compile_dataset, verify_dataset
    from worldloom.providers import digest
    from worldloom.retail_replenishment import process_report
    from worldloom.studio import RunOptions, Studio
    from worldloom.studio.retail_pilot import pilot_project
    from worldloom.studio.worker import run_job
    from worldloom.world import World

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--count", type=int, default=12)
    args = parser.parse_args()
    studio = Studio(args.out)
    spec = pilot_project(count=args.count)
    project = studio.store.create(spec)
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="compile"))
    run_job(studio, job["id"])
    job = studio.store.job(job["id"])
    if job["status"] != "complete":
        raise RuntimeError(job["error"] or job["status"])
    directory = studio.dataset_location(project["id"], project["revision"])
    report = verify_dataset(directory)
    if not report.complete:
        raise RuntimeError("connected pilot coverage incomplete: " + "; ".join(report.findings))
    original = _files(directory)
    plan = load_dataset_plan(json.loads((directory / "plan.json").read_text()))
    replay = compile_dataset(plan, directory, replay_only=True)
    if replay.report != report or _files(directory) != original:
        raise RuntimeError("connected dataset replay changed its export")
    world = World.load(directory / "company" / "world")
    rows = [json.loads(line) for line in (directory / "queryset.jsonl").read_text().splitlines()]
    source_files = sorted((ROOT / "src" / "worldloom").rglob("*.py"))
    sources = [(p.relative_to(ROOT).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()) for p in source_files]
    write_json(args.report, {
        "schema": "worldloom.connected-foundry-measurement/v1", "seed": spec.seed,
        "company": world.company.name, "report": report.model_dump(mode="json"),
        "process_evidence": process_report(world), "byte_identical_dataset_replay": True,
        "real_agent_difficulty_measured": False, "reference_qualification_only": True,
        "native_artifact_analysis_measured": False,
        "examples": [next(row for row in rows if row["stratum"] == case.id) for case in spec.use_cases],
        "source_digest": digest(sources),
        "reproduce": "python tools/measure_connected_foundry.py --out ./connected-pilot --report ./connected-pilot.json",
    })
    print(json.dumps({"report": str(args.report), "queryset": str(directory / "queryset.jsonl"),
                      "qualified": report.accepted, "cases": report.cases, "tasks": report.tasks}, sort_keys=True))


if __name__ == "__main__":
    main()
