"""Run a generated retail/banking dataset through admission and offline replay.

The optional 100k index probe measures split machinery on replicated metadata;
it is explicitly not a 100k qualified dataset or agent-performance benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worldloom.evals.dataset import compile_dataset, verify_dataset
from worldloom.evals.dataset_contract import (
    DatasetEntry,
    DatasetPlan,
    DatasetSource,
    DatasetStratum,
)
from worldloom.evals.dataset_identity import assign_splits
from worldloom.synthesis import IncidentRule, banking, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile


def design(count: int) -> DatasetPlan:
    if count < 40 or count % 4:
        raise ValueError("count must be a multiple of four, at least 40")
    cells = []
    for domain in ("retail", "banking"):
        for failure in ("none", "partial_write"):
            scenario = operational_profile(domain)
            scenario = scenario.model_copy(update={"coverage": scenario.coverage.model_copy(update={"failures": (failure,)})})
            program = (with_parameters(retail(stores=4, products=8, ticks=24), {"initial_stock": 8, "target_stock": 15})
                       if domain == "retail" else banking(borrowers=24, ticks=16))
            rule = (IncidentRule(table="inventory", signal="lost", title="Stock availability") if domain == "retail"
                    else IncidentRule(table="loan", signal="arrears", title="Payment arrears"))
            source = DatasetSource(company={"engine": domain, "geo": "united_kingdom"}, scenario=scenario,
                                   simulation=program, incident_rule=rule, pool_size=32, planning_budget=512,
                                   acknowledged_unmet=(() if domain == "retail" else (
                                       "the 'flat' trading year: the banking engine's world builder has no `seasonality` field, so nothing carries one. Only the retail engine reads a trading year today (`generators/finance` is the one generator that consults it).",
                                   )))
            cells.append(DatasetStratum(id=f"{domain}-{failure}", count=count // 4, source=source))
    return DatasetPlan(strata=tuple(cells), max_batches=max(32, count // 4), split_by="company",
                       max_per_task=max(8, count // 16), max_per_request=max(4, count // 32),
                       max_per_case=3, minimum_tasks=16, minimum_companies=8)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--write-plan", type=Path)
    parser.add_argument("--index-probe", action="store_true")
    args = parser.parse_args()
    plan = design(args.count)
    if args.write_plan:
        args.write_plan.parent.mkdir(parents=True, exist_ok=True)
        args.write_plan.write_text(plan.model_dump_json(indent=2) + "\n")
    resumed = (args.out / "plan.json").exists()
    start = time.perf_counter()
    result = compile_dataset(plan, args.out)
    elapsed = time.perf_counter() - start
    verify_dataset(args.out)
    before = (args.out / "manifest.json").read_bytes()
    replay_start = time.perf_counter()
    replay = compile_dataset(plan, args.out, replay_only=True)
    assert result.report == replay.report
    assert before == (args.out / "manifest.json").read_bytes()
    report = {"dataset": result.report.model_dump(mode="json"), "compile_seconds": elapsed,
              "started_from_checkpoint": resumed,
              "offline_replay_seconds": time.perf_counter() - replay_start,
              "replay_manifest_identical": True, "plan": plan.model_dump(mode="json"),
              "limits": ["Two business workflows, four requested strata; not enterprise-wide semantic coverage.",
                         "Company-disjoint splits; executable task families may occur in multiple splits.",
                         "Reference connector assertions; no measured target-agent difficulty or prose-quality gate."]}
    if args.index_probe:
        sample = json.loads((args.out / "queryset.jsonl").read_text().splitlines()[0])
        base = DatasetEntry.model_validate({k: v for k, v in sample.items() if k in DatasetEntry.model_fields})
        started = time.perf_counter()
        entries = [base.model_copy(update={"id": str(i), "company_id": str(i // 10),
                   "case_id": str(i // 2), "evidence": (f"evidence:{i // 2}",)}) for i in range(100_000)]
        _, counts, groups, largest = assign_splits(entries, plan)
        report["metadata_only_100k_split_probe"] = {"rows": len(entries), "groups": groups,
                                                    "largest": largest, "splits": counts,
                                                    "seconds": time.perf_counter() - started}
    repo = Path(__file__).resolve().parents[1]
    paths = [Path(__file__).resolve(), *(repo / "src/worldloom/evals").glob("dataset*.py")]
    report["source_sha256"] = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in {"plan", "source_sha256"}}, indent=2))
    result.raise_if_incomplete()


if __name__ == "__main__":
    main()
