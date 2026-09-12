"""Grade an agent on the company's connector cases, inside Studio, per axis.

Studio compiles a company's use cases into a dataset of qualified connector
queries and, in a Foundry run, observes a target agent's trials to measure
difficulty. What it did not have was the three-axis run: `worldloom evalrun`
existed only as a CLI over an exported corpus, and a console operator had no
job that graded an agent's plan, trajectory and outcomes on the dataset the
console had just built, and no page that showed which axis moved.

This job is that wire. It takes the revision's dataset (the compiled or the
frozen one, verified before use), selects its rows, loads each batch's
qualified corpus, compiles the three-axis cases with their dataset lineage
attached, and runs one agent through the same tool surface an external agent
gets: the reference agent (the executable ceiling, no harness needed) or the
configured coding harness over the ``--exec`` seam, one subprocess per turn.
``plan`` mode asks the same agent for a DAG only and grades the plan axis.

The ledger is durable: every graded case is appended to ``results.jsonl`` as
it completes, ``progress.json`` reports the count, and a retried job reuses
what it already graded rather than asking the harness again. The finished
run directory is the one ``worldloom evalrun summarize`` and ``compare``
read, sealed by a receipt the results API authenticates before showing a row.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..corpus import write_json
from ..enterprise_io import load_exported_corpus
from ..evalrun import (
    CaseResult,
    EvalCase,
    ExecAgent,
    ExecPlanner,
    ReferenceAgent,
    ReferencePlanner,
    RunReport,
    cases_from_corpus,
    plan_cases,
    read_run,
    run_cases,
    service_for,
    write_run,
)
from ..evalrun.runner import case_set_digest
from ..evals.dataset import _files, _read, verify_dataset
from ..providers import digest
from .checkpoints import atomic_json, document
from .models import RunOptions

if TYPE_CHECKING:
    from .service import Studio

SCHEMA = "worldloom.studio-evalrun/v1"
_PRINCIPAL = "studio-agent"
_FILTERS = ("status", "shape", "use_case", "split", "verdict")


def progress(studio: Studio, job_id: str) -> dict[str, Any] | None:
    path = studio.path("evalruns", job_id) / "progress.json"
    return _read(path) if path.exists() else None


def _rows(directory: Path) -> tuple[list[dict[str, Any]], bool]:
    """The dataset's admitted rows, or its candidates when coverage is incomplete."""
    complete = (directory / "queryset.jsonl").exists()
    source = directory / ("queryset.jsonl" if complete else "candidates.jsonl")
    if not source.exists():
        return [], complete
    with source.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()], complete


def _selected(rows: Iterable[dict[str, Any]], options: RunOptions) -> list[dict[str, Any]]:
    chosen = [row for row in rows if row.get("qualification")
              and (not options.evalrun_split or row.get("split") == options.evalrun_split)]
    return chosen[:options.evalrun_limit] if options.evalrun_limit else chosen


def _groups(directory: Path, rows: list[dict[str, Any]]) -> list[tuple[list[EvalCase], Any]]:
    """Cases per qualified batch, in row order, each carrying its dataset lineage."""
    by_batch: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_batch.setdefault(str(row["qualification"]), []).append(row)
    groups: list[tuple[list[EvalCase], Any]] = []
    for qualification, members in by_batch.items():
        corpus = load_exported_corpus(directory / qualification)
        compiled = {case.id: case for case in cases_from_corpus(corpus, principal=_PRINCIPAL)}
        cases: list[EvalCase] = []
        for row in members:
            case = compiled.get(str(row["query_id"]))
            if case is None:
                raise ValueError(f"dataset row {row['id']} names a query its batch does not compile")
            lineage = row.get("lineage") or {}
            cases.append(case.model_copy(update={"dimensions": {
                **case.dimensions, "use_case": str(lineage.get("use_case") or row.get("stratum") or ""),
                "split": str(row.get("split") or ""), "dataset_row": str(row["id"]), "batch": str(row.get("batch", "")),
            }}))
        groups.append((cases, corpus.connector_data.records))
    return groups


def _agent_name(options: RunOptions) -> str:
    return f"{options.evalrun_mode}:{options.evalrun_agent}"


def execute(studio: Studio, job: dict[str, Any], *, harness_command: str | None, timeout: float) -> dict[str, Any]:
    options = RunOptions.model_validate(job["options"])
    if options.evalrun_agent == "harness" and not harness_command:
        raise ValueError("connect a coding harness to evaluate it; the reference agent needs none")
    directory = studio.dataset_location(job["project"], job["revision"])
    if not (directory / "manifest.json").exists():
        raise ValueError("generate the connector queryset before grading an agent on it")
    verify_dataset(directory)
    rows, complete = _rows(directory)
    selected = _selected(rows, options)
    if not selected:
        raise ValueError("no dataset row matches the requested split; generate the queryset or widen the selection")
    root = studio.path("evalruns", job["id"])
    root.mkdir(parents=True, exist_ok=True)
    identity = {"schema": SCHEMA, "project": job["project"], "revision": job["revision"],
                "options": options.model_dump(mode="json"), "dataset": directory.name,
                "dataset_files": digest(_files(directory)),
                "harness": digest(harness_command) if options.evalrun_agent == "harness" else None}
    document(root / "identity.json", identity)
    receipt = root / "receipt.json"
    if receipt.exists():
        # A completed run is replayed from its ledger: the harness is not
        # asked again, and a changed directory refuses rather than regrading.
        if _read(receipt).get("files") != _files(root):
            raise ValueError("agent run changed after its receipt was written")
        recorded: dict[str, Any] = _read(root / "result.json")
        return recorded
    groups = _groups(directory, selected)
    ledger = root / "results.jsonl"
    results: dict[str, CaseResult] = {}
    if ledger.exists():
        with ledger.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    prior = CaseResult.model_validate_json(line)
                    results[prior.case_id] = prior
    wanted = {case.id for cases, _ in groups for case in cases}
    results = {case_id: result for case_id, result in results.items() if case_id in wanted}
    state: dict[str, Any] = {"status": "running", "total": len(wanted), "graded": 0, "errors": 0, "passed": 0,
                             "agent": _agent_name(options), "mode": options.evalrun_mode}

    def account() -> None:
        state["graded"] = sum(1 for result in results.values() if result.graded)
        state["errors"] = sum(1 for result in results.values() if not result.graded)
        state["passed"] = sum(1 for result in results.values() if result.graded and result.score is not None and result.score.passed)
        atomic_json(root / "progress.json", state)

    def record(result: CaseResult) -> None:
        results[result.case_id] = result
        with ledger.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result.model_dump(mode="json"), sort_keys=True, default=str) + "\n")
        account()

    account()
    for cases, records in groups:
        pending = [case for case in cases if case.id not in results]
        if not pending:
            continue
        service = service_for(pending, records)
        if options.evalrun_mode == "plan":
            planner: Any = (ReferencePlanner(pending) if options.evalrun_agent == "reference"
                            else ExecPlanner(str(harness_command), timeout=timeout, name="plan:harness"))
            for result in plan_cases(service, pending, planner, principal=_PRINCIPAL).results:
                record(result)
        else:
            agent: Any = (ReferenceAgent(pending) if options.evalrun_agent == "reference"
                          else ExecAgent(str(harness_command), timeout=timeout, max_turns=options.evalrun_max_turns, name="run:harness"))
            run_cases(service, pending, agent, principal=_PRINCIPAL, on_result=record)
    ordered = tuple(results[case.id] for cases, _ in groups for case in cases)
    report = RunReport(agent=_agent_name(options), principal=_PRINCIPAL,
                       case_set=case_set_digest(case for cases, _ in groups for case in cases), results=ordered)
    summary = write_run(root, report)
    state["status"] = "complete"
    account()
    outcome: dict[str, Any] = {"schema": SCHEMA, "run": job["id"], "dataset": directory.name, "dataset_complete": complete,
                               "agent": report.agent, "mode": options.evalrun_mode, "split": options.evalrun_split,
                               "cases": len(ordered), "summary": summary.model_dump(mode="json", by_alias=True)}
    write_json(root / "result.json", outcome)
    write_json(receipt, {"files": _files(root)})
    return outcome


def _row(result: CaseResult) -> dict[str, Any]:
    score = result.score
    return {
        "case_id": result.case_id, "query": result.query, "shape": result.shape or "legacy",
        "use_case": result.dimensions.get("use_case", ""), "split": result.dimensions.get("split", ""),
        "dataset_row": result.dimensions.get("dataset_row", ""), "workflow": result.dimensions.get("workflow", ""),
        "failure": result.dimensions.get("failure", "none"),
        "status": result.status, "error": result.error, "calls": result.calls, "notes": list(result.notes),
        "passed": bool(score.passed) if score else None, "score": score.score if score else None,
        "observed": list(score.observed) if score else [],
        "plan": {"score": score.plan.score, "passed": score.plan.passed, "missing_nodes": list(score.plan.missing_nodes),
                 "extra_writes": score.plan.extra_writes} if score else None,
        "trajectory": {"score": score.trajectory.score, "passed": score.trajectory.passed,
                       "exact_match": score.trajectory.exact_match, "retry_storm": score.trajectory.retry_storm,
                       "failures": f"{score.trajectory.failures_honoured}/{score.trajectory.failures_expected}",
                       "safety": [finding.law for finding in score.trajectory.safety]} if score else None,
        "outcomes": {"score": score.outcomes.score, "passed": score.outcomes.passed,
                     "structured": f"{score.outcomes.structured_met}/{score.outcomes.structured_expected}",
                     "collateral": len(score.outcomes.collateral), "grounding": score.outcomes.grounding} if score else None,
        "assertion_status": score.assertion_status if score else None,
        "assertion_fails": list(score.assertion_fails) if score else [],
    }


def results(studio: Studio, project: str, job_id: str, *, offset: int = 0, limit: int = 25,
            **filters: str) -> dict[str, Any]:
    """Page the graded cases of one completed run, authenticated before a row is shown."""
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("invalid agent run page")
    unknown = set(filters) - set(_FILTERS)
    if unknown or any(len(value) > 200 for value in filters.values()):
        raise ValueError("invalid agent run filter")
    job = studio.store.job(job_id)
    if job["project"] != project or job["options"]["operation"] != "evalrun" or job["status"] != "complete":
        raise ValueError("agent results need a completed evalrun belonging to this project")
    root = studio.path("evalruns", job_id)
    if _read(root / "receipt.json").get("files") != _files(root):
        raise ValueError("agent run changed after checkpoint")
    report = read_run(root)
    rows = [_row(result) for result in report.results]
    wanted = {key: value for key, value in filters.items() if value}
    verdict = wanted.pop("verdict", "")
    selected = [row for row in rows if all(str(row.get(key)) == value for key, value in wanted.items())
                and (not verdict or (verdict == "passed" and row["passed"] is True)
                     or (verdict == "failed" and row["passed"] is False) or (verdict == "error" and row["status"] == "error"))]
    end = offset + limit
    return {"project": project, "revision": job["revision"], "job": job_id, "agent": report.agent,
            "mode": job["options"].get("evalrun_mode", "run"), "rows": selected[offset:end], "offset": offset,
            "total": len(selected), "unfiltered_total": len(rows), "next_offset": end if end < len(selected) else None,
            "summary": _read(root / "summary.json")}


__all__ = ["SCHEMA", "execute", "progress", "results"]
