"""Exercise reviewed creation against a copy of an accepted company workspace.

The original workspace is unchanged. Reference qualification is not a target
trial; this measurement never invokes a model or claims calibrated difficulty.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worldloom.corpus import write_json
from worldloom.providers import digest
from worldloom.studio import (
    DataCreationRequest,
    NativeSuiteRequest,
    ProjectSpec,
    RunOptions,
    Studio,
    preset,
)
from worldloom.studio.data_creation import propose
from worldloom.studio.worker import run_job
from worldloom.synthesis import Simulator


def measure(workspace: Path, project_id: str, use_case: str, *, max_cases: int = 12) -> dict:
    original = Studio(workspace)
    current = original.store.get(project_id)
    # This separate recipe check verifies planned volume against actual emitted
    # operational rows. It does not splice those rows into the native company.
    recipe = preset("retail", "Sizing recipe check")
    sized = propose(recipe, DataCreationRequest(simulation_target="operations-review",
        stores=4, products=8, ticks=30, query_counts={"operations-review": 1000}))
    program = sized.spec.use_cases[0].simulation
    assert program is not None and sized.summary.simulation is not None
    actual_rows = dict(sorted(Counter(row.table for row in Simulator(program, seed=recipe.seed).rows()).items()))
    assert actual_rows == sized.summary.simulation.table_rows
    with TemporaryDirectory(prefix="worldloom-creation-measurement-") as temporary:
        copied = Path(temporary) / "workspace"
        shutil.copytree(workspace, copied, ignore=shutil.ignore_patterns("studio.sqlite*", "worker.lock"))
        with original.store.connection() as source, sqlite3.connect(copied / "studio.sqlite") as destination:
            source.backup(destination)
        studio = Studio(copied)
        sources = studio.native_sources(project_id, current["revision"], group_by="artifact", limit=1000)
        assert sources["status"] == "accepted"
        proposal = studio.prepare_native(project_id, current["revision"], NativeSuiteRequest(
            use_case_id=use_case, max_cases=max_cases, minimum_units=2))
        assert studio.store.get(project_id)["revision"] == current["revision"]
        revision = studio.store.revise(project_id, current["revision"], ProjectSpec.model_validate(proposal["spec"]),
                                      reason="Measurement: reviewed corpus and eval proposal")
        job = studio.store.enqueue(project_id, revision["revision"], RunOptions(operation="native"))
        assert run_job(studio, job["id"])
        completed = studio.store.job(job["id"])
        if completed["status"] != "complete":
            raise ValueError(completed["error"])
        result = completed["result"]
        queries = []
        offset = 0
        while True:
            page = studio.native_queryset(project_id, job["id"], offset=offset, limit=100)
            queries.extend(page["rows"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        files = {}
        for artifact_id, metadata in sorted(result["corpus_artifacts"].items()):
            payload, format = studio.native_artifact(project_id, job["id"], artifact_id)
            files[artifact_id] = {"format": format, "bytes": len(payload), "sha256": metadata["sha256"],
                                  "content_units": metadata["content_units"], "distinct_facts": metadata["distinct_fact_count"]}
        replay = studio.execute(job["id"])
        assert replay == result
        report = {"schema": "worldloom.creation-workbench-measurement/v1",
            "company": current["spec"]["company"]["identity"]["company_name"],
            "revision": revision["revision"], "accepted_source_artifacts": sources["total"],
            "proposal_summary": proposal["summary"], "files": files, "file_count": len(files),
            "public_queryset_digest": digest(queries), "task_count": len(queries),
            "operations": dict(sorted(Counter(row["operation"] for row in queries).items())),
            "evidence_components": result["evidence_components"], "observed_target_trials": result["observed_trials"],
            "calibrated": result["calibrated"], "replay_identical": True,
            "sample_public_tasks": [{key: value for key, value in row.items() if key != "submission_schema"} for row in queries[:4]],
            "separate_operational_recipe_check": {"dimensions": sized.summary.simulation.dimensions,
                "planned_rows": sized.summary.simulation.table_rows, "emitted_rows": actual_rows,
                "requested_queries": 1000, "queries_generated_in_recipe_check": 0},
            "screenshots": {"captured": False, "reason": "This offline mechanism check does not perform browser capture"}}
    assert original.store.get(project_id)["revision"] == current["revision"]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--use-case", required=True)
    parser.add_argument("--max-cases", type=int, default=12)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = measure(args.workspace, args.project, args.use_case, max_cases=args.max_cases)
    write_json(args.report, report)
    print(json.dumps({key: report[key] for key in ("file_count", "task_count", "operations", "evidence_components", "observed_target_trials", "replay_identical")}))


if __name__ == "__main__":
    main()
