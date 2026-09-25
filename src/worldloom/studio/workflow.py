"""Read-only readiness shared by operators, the console and coding harnesses."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from ..company import from_document, resolve
from ..models import Model
from ..providers import digest
from .models import ProjectSpec

if TYPE_CHECKING:
    from .service import Studio


class WorkflowAction(Model):
    kind: Literal["run", "navigate", "select_narration", "prepare_native"]
    label: str
    operation: Literal["build", "compile", "narrate", "foundry", "native", "evalrun"] | None = None
    #: Run options the action carries beyond its operation (which agent an
    #: `evalrun` grades). Merged into `RunOptions` by whoever runs it.
    options: dict[str, Any] = Field(default_factory=dict)
    page: str | None = None
    job_id: str | None = None


class WorkflowStage(Model):
    id: str
    title: str
    status: Literal["ready", "blocked", "complete", "running"]
    detail: str
    action: WorkflowAction | None = None


class WorkflowReport(Model):
    schema_version: Literal["worldloom.workflow/v1"] = "worldloom.workflow/v1"
    revision: str
    stages: tuple[WorkflowStage, ...]
    next_action: WorkflowAction | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)
    findings: tuple[dict[str, str], ...] = ()
    metrics: dict[str, int] = Field(default_factory=dict)


def report(studio: Studio, project: str, revision: str | None = None, *, harness_configured: bool = False) -> WorkflowReport:
    from .construction import compile_project
    from .service import snapshot_intent

    current = studio.store.get(project, revision)
    spec = ProjectSpec.model_validate(current["spec"])
    jobs = studio.store.jobs(project)
    local_jobs = [j for j in jobs if j["revision"] == current["revision"]]
    snapshot = digest(snapshot_intent(spec))
    built = (studio.path("snapshots", snapshot) / "receipt.json").is_file()
    unresolved = sorted(set(resolve(from_document(spec.company)).unmet) - set(spec.acknowledged_unmet))
    native_ids = {t.use_case_id for t in spec.native_tasks}
    missing = [c.id for c in spec.use_cases if c.scenario is None and c.id not in native_ids]
    connector_ready = bool(spec.use_cases) and all(c.scenario is not None for c in spec.use_cases)
    native_ready = bool(spec.native_corpus and spec.native_tasks)
    findings = [{"code": "company_unmet", "message": value} for value in unresolved]
    if missing:
        findings.append({"code": "contracts_missing", "message": "Define native tasks or connector workflows for: " + ", ".join(missing)})
    connector_cases = [c for c in spec.use_cases if c.scenario is not None]
    # A batch serves one use case with at most `pool_size` queries, so a
    # budget below this cannot meet the declared counts however it runs.
    floor = sum(-(-max(1, c.count) // spec.pool_size) for c in connector_cases)
    if connector_cases and floor > spec.max_batches:
        findings.append({"code": "batch_budget_short", "message":
            f"{len(connector_cases)} use cases asking {sum(c.count for c in connector_cases)} queries need at least "
            f"{floor} batches of {spec.pool_size}; max_batches is {spec.max_batches}, so the compile cannot meet every count."})
    stages: list[WorkflowStage] = []
    failed: list[WorkflowAction] = []

    def navigate(page: str, label: str) -> WorkflowAction:
        return WorkflowAction(kind="navigate", page=page, label=label)

    def run(operation: Any, label: str, **options: Any) -> WorkflowAction:
        return WorkflowAction(kind="run", operation=operation, label=label, options=options)

    def stage(key: str, title: str, status: Any, detail: str, action: WorkflowAction | None = None) -> None:
        operation: str | None = action.operation if action and action.kind == "run" else None
        if action and action.kind == "prepare_native":
            operation = "prepare_native"
        wanted = action.options if action and action.kind == "run" else {}
        job = next((j for j in local_jobs if j["options"]["operation"] == operation
                    and all(j["options"].get(key) == value for key, value in wanted.items())), None) if operation else None
        if job and job["status"] in {"queued", "running"}:
            status, detail, action = "running", "A worker owns this stage; inspect its run before starting more work.", navigate("changes", "Inspect active run")
        elif job and job["status"] == "paused" and operation != "prepare_native":
            # A batch limit paused committed work; resuming it is the next step.
            status, detail = "ready", "Paused at its batch limit; resume from the committed checkpoints."
            action = WorkflowAction(kind="run", operation=action.operation if action else None, options=wanted, job_id=job["id"], label="Resume run")
        elif job and job["status"] in {"failed", "interrupted"}:
            # The run that failed is the blocker, so it is named here and
            # ranked ahead of every other blocked stage: retrying it resumes
            # from its checkpoints once the cause is fixed.
            error = job["error"] or "Worker stopped; resume from the committed checkpoints."
            status, detail = "blocked", error
            action = (navigate("changes", "Inspect failed proposal") if operation == "prepare_native" else
                      WorkflowAction(kind="run", operation=action.operation if action else None, options=wanted, job_id=job["id"], label="Retry failed run"))
            failed.append(action)
            findings.append({"code": "run_failed", "message": f"{operation} run {job['id']} {job['status']}: {error}"})
        elif operation == "prepare_native" and job and job["status"] == "complete":
            status, detail, action = "ready", "A native suite proposal is ready for explicit review; its contracts have not been applied.", navigate("changes", "Review native proposal")
        stages.append(WorkflowStage(id=key, title=title, status=status, detail=detail, action=action))

    stage("company", "Company contract", "blocked" if unresolved else "complete",
          "Resolve unsupported company claims." if unresolved else "One company identity and seed own this dataset.",
          navigate("interview", "Refine company interview") if unresolved else None)
    stage("build", "Build company evidence", "complete" if built else "blocked" if unresolved else "ready",
          "Stored snapshot available; execution authenticates it before reuse." if built else "Generate the company facts and chronological episodes.",
          None if built or unresolved else run("build", "Build company"))
    narrations = [j for j in jobs if j["status"] == "complete" and j["options"]["operation"] == "narrate"
                  and j["result"] and j["result"].get("snapshot") == snapshot]
    selected = next((j for j in narrations if j["id"] == spec.narration_job), None)
    if spec.narration_job and selected is None:
        findings.append({"code": "stale_narration", "message": "Selected narration does not match the current company snapshot."})
    if selected:
        stage("narration", "Accepted company prose", "complete", "Selected narration belongs to this company snapshot.")
    elif narrations:
        stage("narration", "Accepted company prose", "ready", "Select accepted narration before preparing native contracts.",
              WorkflowAction(kind="select_narration", label="Use accepted narration", job_id=narrations[0]["id"]))
    else:
        stage("narration", "Accepted company prose", "ready" if built and harness_configured else "blocked",
              "A coding harness authors grounded prose; every claim passes the existing acceptance rules.",
              run("narrate", "Narrate company evidence") if built and harness_configured else navigate("interview", "Connect a writing harness"))
    native_covered = native_ready and not missing
    stage("native_contracts", "Prepare document evaluations", "complete" if native_covered else "ready" if selected and spec.use_cases else "blocked",
          "Existing native contracts bind source evidence to read, analysis, update and creation outcomes." if native_covered else
          "Compile reviewable tasks from distinct accepted sections. Scoped use cases require explicit source IDs." +
          (" Missing contracts: " + ", ".join(missing) if missing else ""),
          None if native_covered else WorkflowAction(kind="prepare_native", label="Prepare from accepted sources") if selected and spec.use_cases else navigate("usecases", "Define document use cases"))
    native = next((j for j in local_jobs if j["options"]["operation"] == "native"), None)
    nr = (native or {}).get("result") or {}
    observed = nr.get("observed_trials", 0)
    need_observation = nr.get("status") == "prepared" and harness_configured
    native_status = "blocked" if nr.get("status") == "blocked" else "complete" if nr and not need_observation else "ready" if native_ready else "blocked"
    stage("native", "Generate and evaluate files", native_status,
          f"{observed} observed trials; {nr.get('evidence_components', 0)} independent evidence components. " +
          ("Difficulty accepted." if nr.get("calibrated") else "Difficulty is not yet supported by held-out measurements.") if nr else
          "Render actual files, reference-qualify every task, then execute target trials when a harness is connected.",
          run("native", "Evaluate native files" if harness_configured else "Generate file queryset") if native_ready and (not nr or need_observation) else
          navigate("native", "Inspect document results") if nr else None)
    for value in nr.get("calibration", {}).get("findings", []):
        findings.append({"code": "native_calibration", "message": value})
    compilation = next((j for j in local_jobs if j["options"]["operation"] == "compile"), None)
    cr = (compilation or {}).get("result") or {}
    complete = cr.get("report", {}).get("complete", False)
    stage("compile", "Connector queryset", "complete" if complete else "ready" if connector_ready and not unresolved else "blocked",
          "Connector coverage quotas met." if complete else "Every use case in this path needs an executable connector scenario; native tasks are generated separately.",
          None if complete else run("compile", "Generate connector queryset") if connector_ready and not unresolved else navigate("usecases", "Review connector contracts"))
    graded = [j for j in local_jobs if j["options"]["operation"] == "evalrun" and j["status"] == "complete" and j["result"]]
    reference = next((j for j in graded if j["options"].get("evalrun_agent") == "reference" and j["options"].get("evalrun_mode", "run") == "run"), None)
    harness_run = next((j for j in graded if j["options"].get("evalrun_agent") == "harness"), None)
    frozen_ready = any(j["options"]["operation"] == "foundry" and (j.get("result") or {}).get("frozen_dataset") for j in local_jobs)
    dataset_ready = complete or bool(cr) or frozen_ready
    if reference is None:
        stage("evalrun", "Grade agents on connector cases", "ready" if dataset_ready else "blocked",
              "Run the reference agent through the served tool surface: the executable ceiling of this dataset, per axis."
              if dataset_ready else "A generated connector queryset is the case set an agent is graded on.",
              run("evalrun", "Grade the reference agent") if dataset_ready else navigate("evals", "Generate the queryset first"))
    elif harness_configured and harness_run is None:
        stage("evalrun", "Grade agents on connector cases", "ready",
              "The reference ceiling is recorded; grade the connected coding harness on the same cases and compare per axis.",
              run("evalrun", "Evaluate the connected harness", evalrun_agent="harness"))
    else:
        means = reference["result"].get("summary", {}).get("means", {})
        stage("evalrun", "Grade agents on connector cases", "complete",
              f"Reference agent graded on {reference['result'].get('cases', 0)} cases (plan {means.get('plan')}, trajectory {means.get('trajectory')}, outcomes {means.get('outcomes')})."
              + ("" if harness_run else " Connect a coding harness to grade it on the same cases."),
              navigate("evals", "Inspect agent grades"))
    foundry = next((j for j in local_jobs if j["options"]["operation"] == "foundry"), None)
    fr = (foundry or {}).get("result") or {}
    frozen = bool(fr.get("frozen_dataset"))
    foundry_ready = connector_ready and compile_project(spec).accepted and bool(spec.calibration) and harness_configured and not unresolved
    stage("foundry", "Calibrate and freeze connector dataset", "complete" if frozen else "ready" if foundry_ready and not fr else "blocked",
          "Dataset frozen with observed calibration receipts." if frozen else "Requires construction contracts, a target cohort, noise candidates and a connected harness.",
          run("foundry", "Run calibrated Foundry") if foundry_ready and not fr else navigate("foundry", "Inspect Foundry requirements"))
    # Prefer executable progress. Reviewing a proposal or changing a company is
    # always an explicit operator step, never an automatic retry loop.
    next_action = next((s.action for s in stages if s.status == "ready" and s.action), None)
    if next_action is None:
        next_action = next((s.action for s in stages if s.status == "running" and s.action), None)
    if next_action is None and failed:
        next_action = failed[0]
    if next_action is None:
        next_action = next((s.action for s in stages if s.status == "blocked" and s.action), None)
    return WorkflowReport(revision=current["revision"], stages=tuple(stages), next_action=next_action,
        capabilities={"connector_ready": connector_ready, "native_ready": native_ready,
                      "harness_configured": harness_configured, "accepted_narration": selected is not None},
        findings=tuple(findings), metrics={"use_cases": len(spec.use_cases), "native_tasks": len(spec.native_tasks),
            "native_artifacts": len(spec.native_corpus), "observed_native_trials": observed,
            "native_evidence_components": nr.get("evidence_components", 0), "qualified_connector_queries": cr.get("report", {}).get("accepted", 0),
            "graded_connector_cases": reference["result"].get("cases", 0) if reference else 0})


__all__ = ["WorkflowAction", "WorkflowStage", "WorkflowReport", "report"]
