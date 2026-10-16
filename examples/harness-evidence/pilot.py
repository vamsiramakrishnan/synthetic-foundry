"""Reproduce native evidence -> controlled queries -> graded operations.

Run from an installed checkout:
    python examples/harness-evidence/pilot.py --out /tmp/worldloom-harness-pilot
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from worldloom import RetailWorld
from worldloom.benchmarks import (
    NativeConnectorProjection,
    NativeRealismProfile,
    NativeScenarioDemand,
    build_native_scenarios,
    project_native_sources,
)
from worldloom.corpus import write_json, write_jsonl
from worldloom.enterprise_rows import runtime_records
from worldloom.evalrun import (
    HarnessDagConfig,
    HarnessDagReference,
    build_harness_dags,
    run_cases,
    service_for,
)
from worldloom.evalrun.agents import (
    AgentResponse,
    AgentTask,
    CallableAgent,
    ToolSurface,
)
from worldloom.evalrun.runner import CaseResult, RunReport
from worldloom.predicates import Predicate


def summarize(report: RunReport) -> dict[str, Any]:
    return {
        "cases": len(report.results),
        "passed": sum(bool(result.score and result.score.passed) for result in report.results),
        "results": [
            {
                "case_id": result.case_id,
                "status": result.status,
                "passed": bool(result.score and result.score.passed),
                "calls": result.calls,
                "retrieval": result.score.trajectory.retrieval.model_dump(mode="json")
                if result.score and result.score.trajectory.retrieval else None,
            }
            for result in report.results
        ],
    }


def require_score(result: CaseResult) -> None:
    if not result.graded or result.score is None:
        raise ValueError(f"pilot case did not grade: {result.case_id}: {result.error}")


def run_pilot(out: Path) -> dict[str, Any]:
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f"pilot destination is not empty: {out}")
    profile = NativeRealismProfile(
        line_count=12, budget_spread="zipf", exception_rate=0.25,
        decision_placement="back", row_order="varied",
        comparison_detail="amounts", line_commentary="largest_variance",
        revision_views=("reviewed",),
    )
    world = RetailWorld(seed=8128).build()
    batches = []
    for batch_id in ("alpha", "bravo"):
        batch = build_native_scenarios(world, NativeScenarioDemand(
            episodes=1, processes=("supplier_reconciliation",),
            batch_id=batch_id, realism=profile,
        ))
        batch.verify_source_replay()
        batches.append(batch)
        world = batch.world
    rendered = tuple(native for batch in batches for native in batch.render(formats=("docx", "xlsx")).values())
    projection = project_native_sources(world, rendered, NativeConnectorProjection(
        measure_kind="native.supplier_reconciliation.total.actual", unit=world.company.currency,
    ))
    config = HarnessDagConfig(
        cases=6, value_field="amount", scope_field="scope",
        authority_field="authority", authority_value="approved_report",
    )
    suite = build_harness_dags(projection.records, config)
    if len(suite.cases) != 6 or suite.skipped:
        raise ValueError("pilot requires all six operation/response variants")

    def execute(agent: Any, cases: Any = suite.cases) -> RunReport:
        return run_cases(service_for(cases, runtime_records(suite.records)), cases, agent)

    positive = {}
    for refine in (False, True):
        report = execute(HarnessDagReference(suite.tasks, refine=refine))
        if any(not result.graded or not result.score or not result.score.passed for result in report.results):
            raise ValueError(f"public reference failed: {report.model_dump_json()}")
        positive["refining" if refine else "direct"] = summarize(report)

    # A correct final value must not hide pointless repeated queries.
    public = suite.tasks[0]
    good = HarnessDagReference(suite.tasks)

    def pointless_retry(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        broad = Predicate(entity=public.source_entity, where=(public.scope,)).model_dump(mode="json")
        for _ in range(2):
            tools.call(f"{public.connector}.{public.search_tool}", entity=public.source_entity,
                       predicate=broad, max_results=10)
        return good.run(task, tools)

    repeat = execute(CallableAgent(pointless_retry, name="pointless-retry"), suite.cases[:1]).results[0]
    require_score(repeat)
    if not repeat.score or not repeat.score.outcomes.passed or repeat.score.trajectory.passed or repeat.score.passed:
        raise ValueError("pointless-retry control failed to distinguish outcome from trajectory")

    # A fluent success message must not excuse a wrong persisted report.
    class WrongTotal:
        def __init__(self, tools: ToolSurface) -> None:
            self.tools = tools

        def call(self, tool: str, **arguments: Any) -> Any:
            if tool.endswith(".create_file"):
                arguments["fields"] = {**arguments["fields"], "total": -1}
            return self.tools.call(tool, **arguments)

    def wrong_total(task: AgentTask, tools: ToolSurface) -> AgentResponse:
        try:
            return good.run(task, WrongTotal(tools))  # type: ignore[arg-type]
        except ValueError:
            return AgentResponse(answer="The report was created successfully.")

    wrong = execute(CallableAgent(wrong_total, name="wrong-total"), suite.cases[:1]).results[0]
    require_score(wrong)
    if not wrong.score or wrong.score.outcomes.passed or wrong.score.passed:
        raise ValueError("wrong-total control was incorrectly accepted")

    result = {
        "schema": "worldloom.harness-evidence-pilot/v1",
        "seed": 8128,
        "representation": projection.representation,
        "native_files": len(rendered),
        "native_formats": sorted({native.manifest.format for native in rendered}),
        "projected_records": len(projection.records),
        "excluded_format_replicas": len(projection.excluded_formats),
        "source_families": len({record.fields["source_family"] for record in projection.records}),
        "dag_families": len({case.dimensions["family_id"] for case in suite.cases}),
        "approved_values": sorted(record.fields["amount"] for record in projection.records
                                  if record.fields["authority"] == "approved_report"),
        "unit": world.company.currency,
        "realism": [episode.realism.model_dump(mode="json") for batch in batches
                    for episode in batch.episodes if episode.realism],
        "reference_runs": positive,
        "negative_controls": {
            "pointless_retry": {"outcome_passed": repeat.score.outcomes.passed,
                                "trajectory_passed": repeat.score.trajectory.passed,
                                "passed": repeat.score.passed},
            "wrong_total": {"outcome_passed": wrong.score.outcomes.passed,
                            "passed": wrong.score.passed},
        },
        "claims": {"live_model_improvement": False, "binary_ingestion_tested": False,
                   "visual_truth_qualified": False, "source_recipe_replay_verified": True},
    }
    out.mkdir(parents=True, exist_ok=True)
    world.export(out / "corpus")
    (out / "native").mkdir()
    for native in rendered:
        manifest = native.manifest
        (out / "native" / f"{manifest.artifact_id}.{manifest.format}").write_bytes(native.payload)
        write_json(out / "native" / f"{manifest.artifact_id}.manifest.json", manifest.model_dump(mode="json"))
    write_json(out / "projection.private.json", projection.model_dump(mode="json"))
    write_jsonl(out / "records.jsonl", list(projection.records))
    write_json(out / "harness-dags.json", config.model_dump(mode="json"))
    suite.write(out / "cases")
    write_json(out / "measurement.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New or empty output directory")
    arguments = parser.parse_args()
    print(json.dumps(run_pilot(arguments.out), sort_keys=True, indent=2))
