#!/usr/bin/env python3
"""Measure planning, compilation, execution and grading as separate gates.

The default reproduces the 400-row remaining-design measurement: the bounded
exhaustive prefix, fairly interleaved across workflows and connector lanes.
Covering scans the complete candidate space before applying the row limit.

    python tools/measure_enterprise_execution.py --output measurement.json
    python tools/measure_enterprise_execution.py --strategy exhaustive --failure none

This script never modifies the source world or suppresses failed rows. Runtime
exceptions are observations here, so one broken row cannot hide the denominator.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from worldloom.connector_eval_runtime import run_eval_row
from worldloom.enterprise_corpus import materialize_corpus, validate_corpus
from worldloom.enterprise_queries import plan_queries
from worldloom.enterprise_rows import compile_rows, runtime_records
from worldloom.enterprise_specs import CoverageProfile
from worldloom.world import World


def measure(world_path: Path, *, limit: int, strategy: str, failure: str, dag_shapes: tuple[str, ...] = ()) -> dict[str, Any]:
    world = World.load(world_path)
    profile = CoverageProfile()
    if failure != "all":
        if failure not in profile.failures:
            raise ValueError(f"unknown failure {failure!r}; choose from {profile.failures}")
        profile = profile.model_copy(update={"failures": (failure,)})
    planned, coverage = plan_queries(world, profile=profile, strategy=strategy, limit=limit, dag_shapes=dag_shapes)
    corpus = materialize_corpus(world, tuple(planned))
    records = runtime_records(corpus.connector_data.records)
    report = compile_rows(corpus.queries, corpus.fixtures, records)
    counts: Counter[str] = Counter()
    grade_failures: Counter[str] = Counter()
    runtime_errors: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    slices: dict[str, Counter[str]] = {}
    by_id = {query.id: query for query in corpus.queries}
    for row in report.rows:
        failure_kind = by_id[row["id"]].dimensions.get("failure", "none")
        bucket = slices.setdefault(failure_kind, Counter())
        bucket["compiled"] += 1
        try:
            result = run_eval_row(row, records)
        except Exception as error:
            counts["raised"] += 1
            bucket["raised"] += 1
            reason = f"{type(error).__name__}: {error}"
            runtime_errors[reason] += 1
            errors.append({"query_id": row["id"], "reason": reason})
            continue
        counts["executed"] += 1
        bucket["executed"] += 1
        status = str(result.grade["status"])
        counts[f"grade_{status}"] += 1
        bucket[f"grade_{status}"] += 1
        grade_failures.update(result.grade.get("fails", ()))
        if any(span.error for span in result.spans):
            counts["execution_with_tool_error"] += 1
            bucket["execution_with_tool_error"] += 1
    validation = validate_corpus(corpus)
    total = len(corpus.queries)
    return {
        "parameters": {
            "world": str(world_path), "strategy": strategy, "limit": limit,
            "failures": list(profile.failures),
            "dag_shapes": list(dag_shapes),
        },
        "population": total,
        "compiled": report.compiled,
        "refused": len(report.refusals),
        "compile_percent": round(100 * report.compiled / total, 2) if total else 0.0,
        "compile_refusals": report.reasons(),
        "execution": dict(sorted(counts.items())),
        "grade_failures": dict(sorted(grade_failures.items())),
        "runtime_errors": dict(sorted(runtime_errors.items())),
        "runtime_error_rows": errors,
        "by_failure": {key: dict(sorted(value.items())) for key, value in sorted(slices.items())},
        "by_shape": dict(sorted(Counter(query.dimensions.get("dag_shape", "legacy") for query in corpus.queries).items())),
        "validation_finding_count": len(validation),
        "validation_examples": list(validation[:20]),
        "coverage": coverage.model_dump(mode="json") if coverage else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, default=Path("examples/retail-close"))
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--strategy", choices=("covering", "exhaustive"), default="exhaustive")
    parser.add_argument("--failure", default="all")
    parser.add_argument("--dag-shape", action="append", default=[], help="Opt into a DAG shape; repeat, or use '*' for all authored shapes.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    result = measure(args.world, limit=args.limit, strategy=args.strategy, failure=args.failure, dag_shapes=tuple(args.dag_shape))
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    result["revision"] = revision.stdout.strip() if revision.returncode == 0 else None
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    result["working_tree_dirty"] = bool(dirty.stdout) if dirty.returncode == 0 else None
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8", newline="\n")
    print(serialized, end="")


if __name__ == "__main__":
    main()
