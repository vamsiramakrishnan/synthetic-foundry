"""Local gates and bounded managed entrypoint for Worldloom AlphaEvolve."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
from types import ModuleType
from typing import Any

from evals.alphaevolve.registry import (
    EXPERIMENT_MODULES,
    experiment_fingerprint,
    levers_for_experiment,
    registry_document,
)

EXPERIMENTS = EXPERIMENT_MODULES


def load_experiment(name: str) -> ModuleType:
    try:
        return importlib.import_module(EXPERIMENTS[name])
    except KeyError as exc:
        raise SystemExit(
            f"unknown experiment {name!r}; choose: {', '.join(EXPERIMENTS)}"
        ) from exc


def _comparison(result: dict[str, Any]) -> dict[str, Any] | None:
    totals = result.get("totals")
    baseline = result.get("baseline")
    if not isinstance(totals, dict) or not isinstance(baseline, dict):
        return None
    return {
        "totals": totals,
        "baseline": baseline,
        "reductions": {
            key: (
                1.0 - float(totals[key]) / float(baseline[key])
                if float(baseline[key]) > 0 else None
            )
            for key in sorted(set(totals) & set(baseline))
        },
        "lexicographically_beats_baseline": result.get(
            "lexicographically_beats_baseline"
        ),
    }


def local_scorecard(experiments: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Evaluate reviewed policies against search, holdout and adversarial gates."""
    rows: dict[str, Any] = {}
    for name in experiments or tuple(EXPERIMENTS):
        module = load_experiment(name)
        code = module.INTEGRATED_PROGRAM_CODE
        results = {
            "search": module.score_candidate(code),
            "holdout": module.score_holdout(code),
            "adversarial": module.score_adversarial(code),
        }
        gates = {
            label: {
                "score": result.get("score"),
                "passed": (
                    result.get("error") is None
                    and result.get("promotion_passed") is True
                ),
                "error": result.get("error"),
                "optimal": result.get("optimal"),
                "case_count": result.get("case_count"),
                "comparison": _comparison(result),
            }
            for label, result in results.items()
        }
        rows[name] = {
            "metric": module.METRIC_NAME,
            "dataset_fingerprint": experiment_fingerprint(name),
            "levers": [lever.id for lever in levers_for_experiment(name)],
            "candidate": "integrated",
            "gates": gates,
            "promotion_ready": all(gate["passed"] for gate in gates.values()),
        }
    return {
        "schema": "worldloom.alphaevolve-local-scorecard/v1",
        "experiments": rows,
        "all_gates_pass": all(row["promotion_ready"] for row in rows.values()),
    }


def readiness_report(experiments: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Report managed-search readiness, never production promotion."""
    scorecard = local_scorecard(experiments)
    return {
        "schema": "worldloom.alphaevolve-readiness/v1",
        "experiments": {
            name: {
                "ready": row["promotion_ready"],
                "fingerprint": row["dataset_fingerprint"],
                "reason": (
                    "all local search, holdout, and adversarial gates pass"
                    if row["promotion_ready"] else "one or more local gates failed"
                ),
            }
            for name, row in scorecard["experiments"].items()
        },
    }


def promotion_report(experiments: tuple[str, ...] | None = None) -> dict[str, Any]:
    """State the strongest claim the current evidence permits."""
    scorecard = local_scorecard(experiments)
    return {
        "schema": "worldloom.alphaevolve-promotion-report/v1",
        "experiments": {
            name: {
                "status": (
                    "reviewed_local_integration"
                    if row["promotion_ready"] else "blocked"
                ),
                "managed_winner": False,
                "production_promotion": row["promotion_ready"],
                "claim": (
                    "deterministic axis-coverage improvement only; no realism, "
                    "retrieval-quality, cloud-search, or cost claim"
                ),
                "gates": row["gates"],
            }
            for name, row in scorecard["experiments"].items()
        },
    }


def shadow_report(name: str) -> dict[str, Any]:
    row = local_scorecard((name,))["experiments"][name]
    return {
        "schema": "worldloom.alphaevolve-shadow/v1",
        "experiment": name,
        "mutated_production": False,
        "dataset_fingerprint": row["dataset_fingerprint"],
        "gates": row["gates"],
    }


def _env(name: str, fallback: str | None = None) -> str:
    return os.environ.get(name) or (os.environ.get(fallback) if fallback else "") or ""


def _managed_objects(module: ModuleType, max_programs: int, concurrency: int):
    project = _env("PROJECT_ID", "GOOGLE_CLOUD_PROJECT")
    engine = _env("GE_APP_ID")
    if not project or not engine:
        raise SystemExit("PROJECT_ID/GOOGLE_CLOUD_PROJECT and GE_APP_ID are required")
    try:
        from alpha_evolve.client import AlphaEvolveClient
        from alpha_evolve.controller import run_controller_loop
        from alpha_evolve.experiment import AlphaEvolveExperiment
    except ImportError as exc:
        raise SystemExit(
            "alpha_evolve is not installed; install Google's official client repository"
        ) from exc

    client = AlphaEvolveClient(
        project_id=project,
        location=_env("LOCATION") or "global",
        collection=_env("COLLECTION") or "default_collection",
        engine=engine,
        assistant=_env("ASSISTANT") or "default_assistant",
        base_url=_env("BASE_URL") or "discoveryengine.googleapis.com",
    )
    experiment = AlphaEvolveExperiment(
        ae_client=client,
        evaluator_function=module.evaluation_function,
        max_programs_evaluated=max_programs - 1,
        parallel_evaluation=concurrency > 1,
    )
    return experiment, run_controller_loop


def _ranking(experiment: Any, module: ModuleType) -> list[dict[str, Any]]:
    response = experiment.list_programs(params={"pageSize": 100}) or {}
    rows: list[dict[str, Any]] = []
    for program in response.get("alphaEvolvePrograms", []):
        scores = program.get("evaluation", {}).get("scores", {}).get("scores", [])
        score = next((
            item.get("score") for item in scores
            if item.get("metric") == module.METRIC_NAME
        ), None)
        rows.append({
            "program": str(program.get("name", "")).rsplit("/", 1)[-1],
            "score": score,
            "evolved": bool(program.get("parentPrograms")),
            "state": program.get("state"),
        })
    return sorted(
        rows,
        key=lambda row: float("-inf") if row["score"] is None else float(row["score"]),
        reverse=True,
    )


def start_managed(module: ModuleType, max_programs: int, concurrency: int) -> None:
    experiment, controller = _managed_objects(module, max_programs, concurrency)
    experiment.create_experiment({
        "title": module.TITLE,
        "problem_description": module.PROBLEM_PATH.read_text(encoding="utf-8"),
        "program_language": "python",
        "run_settings": {"max_programs": max_programs, "concurrency": concurrency},
        "generation_settings": {"models": [{"name": _env("MODEL") or "gemini-3.5-flash"}]},
    })
    print(f"experiment: {experiment.experiment_name}", flush=True)
    seed = module.score_candidate(module.INITIAL_PROGRAM_CODE)
    if seed.get("error"):
        raise RuntimeError(f"seed failed local evaluator: {seed['error']}")
    experiment.create_initial_program({
        "content": {"files": [{"path": "program.py", "content": module.INITIAL_PROGRAM_CODE}]},
        "evaluation": {"scores": {"scores": [{"metric": module.METRIC_NAME, "score": seed["score"]}]}},
    })
    experiment.start_experiment()
    asyncio.run(controller(
        experiment,
        num_samplers=concurrency,
        num_evaluators=concurrency,
    ))
    print(json.dumps(_ranking(experiment, module)[:5], indent=2))


def _bind_resource(experiment: Any, experiment_name: str) -> None:
    """Attach a client object to one exact managed experiment resource."""
    marker = "/alphaEvolveExperiments/"
    if marker not in experiment_name:
        raise SystemExit(
            "managed experiment must be a full resource name containing "
            "'/alphaEvolveExperiments/'"
        )
    experiment.session_name = experiment_name.split(marker, 1)[0]
    experiment.experiment_name = experiment_name


def resume_managed(
    module: ModuleType,
    experiment_name: str,
    max_programs: int,
    concurrency: int,
) -> None:
    """Resume one bounded managed experiment without minting a replacement."""
    experiment, controller = _managed_objects(module, max_programs, concurrency)
    _bind_resource(experiment, experiment_name)
    ranking = _ranking(experiment, module)
    completed = sum(
        1 for row in ranking if row["evolved"] and row["state"] == "COMPLETED"
    )
    experiment.stats["num_programs_evaluated"] = completed
    asyncio.run(controller(
        experiment,
        num_samplers=concurrency,
        num_evaluators=concurrency,
    ))
    print(json.dumps(_ranking(experiment, module)[:5], indent=2))


def inspect_managed(
    module: ModuleType,
    experiment_name: str,
    program_id: str,
) -> None:
    """Fetch one candidate and run every local gate before human review."""
    experiment, _controller = _managed_objects(module, max_programs=2, concurrency=1)
    _bind_resource(experiment, experiment_name)
    response = experiment.list_programs(params={"pageSize": 100}) or {}
    suffix = "/" + program_id.rsplit("/", 1)[-1]
    program = next((
        item for item in response.get("alphaEvolvePrograms", [])
        if str(item.get("name", "")).endswith(suffix)
    ), None)
    if program is None:
        raise SystemExit(f"program {program_id!r} not found in experiment")
    files = program.get("content", {}).get("files", [])
    if not files or not isinstance(files[0].get("content"), str):
        raise SystemExit("program has no inspectable source content")
    code = files[0]["content"]
    print(json.dumps({
        "experiment": experiment_name,
        "program": program.get("name"),
        "search": module.score_candidate(code),
        "holdout": module.score_holdout(code),
        "adversarial": module.score_adversarial(code),
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", nargs="?", default="variation-policy")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--ready-for-managed", action="store_true")
    parser.add_argument("--promotion-report", action="store_true")
    parser.add_argument("--shadow", action="store_true")
    parser.add_argument("--registry", action="store_true")
    parser.add_argument("--managed", action="store_true")
    parser.add_argument("--resume-experiment", default="")
    parser.add_argument("--inspect-experiment", default="")
    parser.add_argument("--program-id", default="")
    parser.add_argument("--confirm-spend", action="store_true")
    parser.add_argument("--max-programs", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()

    selected = (args.experiment,)
    if args.list:
        print("\n".join(EXPERIMENTS))
    elif args.registry:
        print(json.dumps(registry_document(), indent=2))
    elif args.ready_for_managed:
        print(json.dumps(readiness_report(selected), indent=2))
    elif args.promotion_report:
        print(json.dumps(promotion_report(selected), indent=2))
    elif args.shadow:
        print(json.dumps(shadow_report(args.experiment), indent=2))
    elif args.inspect_experiment:
        if not args.program_id:
            raise SystemExit("--inspect-experiment requires --program-id")
        inspect_managed(
            load_experiment(args.experiment),
            args.inspect_experiment,
            args.program_id,
        )
    elif args.managed or args.resume_experiment:
        if not args.confirm_spend:
            raise SystemExit("managed AlphaEvolve can incur spend; pass --confirm-spend")
        if not (2 <= args.max_programs <= 50):
            raise SystemExit("--max-programs must be between 2 and 50")
        if not (1 <= args.concurrency <= 4):
            raise SystemExit("--concurrency must be between 1 and 4")
        module = load_experiment(args.experiment)
        if args.resume_experiment:
            resume_managed(
                module,
                args.resume_experiment,
                args.max_programs,
                args.concurrency,
            )
        else:
            start_managed(module, args.max_programs, args.concurrency)
    else:
        print(json.dumps(local_scorecard(selected), indent=2))


if __name__ == "__main__":
    main()
