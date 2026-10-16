"""Execute authored native DAGs over source-bound benchmark contracts.

The trace observes runner-scheduled harness calls and the bytes staged for each
call. It does not claim to observe the target's internal tool use or reasoning,
and is deliberately not an autonomous planning score. Conditional branches and
unbounded iteration are not part of this versioned, bounded DAG contract.
"""
from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from ..models import Model
from ..native_eval_bridge import native_grader_identity
from ..native_reference import reference_submission
from ..native_tasks import (
    NativeGrade,
    NativeSubmission,
    NativeTask,
    grade_native_task,
    public_contract,
)
from ..providers import digest
from .runner import (
    HarnessFailure,
    _atomic_json,
    _canonical,
    _file_digest,
    _public_agent,
    _read_json,
    _seal,
    _unseal,
)

if TYPE_CHECKING:
    from ..evalrun.agents import AgentUnderTest
    from .core import NativeBenchmark
    from .runner import NativeHarness


class NativeWorkflowInput(Model):
    """Stage an actual parent update as a new version of its existing input."""

    input_artifact_id: str = Field(min_length=1)
    parent_step_id: str = Field(min_length=1)


class NativeWorkflowStep(Model):
    id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    input_bindings: tuple[NativeWorkflowInput, ...] = ()

    @model_validator(mode="after")
    def distinct_bindings(self) -> NativeWorkflowStep:
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("workflow parent steps must be distinct")
        if len({item.input_artifact_id for item in self.input_bindings}) != len(self.input_bindings):
            raise ValueError("workflow input bindings must be distinct")
        if any(item.parent_step_id not in self.depends_on for item in self.input_bindings):
            raise ValueError("workflow input binding must name a declared parent")
        return self


class NativeWorkflowPlan(Model):
    """A source-bound authored plan; task assertions cannot be supplied here.

    Steps are a topological sequence. Explicit order is part of the identity,
    including the order chosen for independent branches. Reusing a benchmark
    task in multiple steps is permitted; step identities must remain distinct.
    File bindings pass updates into read/analyze steps over that same source;
    write steps retain canonical inputs until derived write contracts exist.
    """

    schema_version: Literal["worldloom.native-workflow-plan/v1"] = "worldloom.native-workflow-plan/v1"
    id: str = Field(min_length=1)
    benchmark_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    steps: tuple[NativeWorkflowStep, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def ordered_dag(self) -> NativeWorkflowPlan:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError("workflow step identities must be distinct")
            if any(parent not in seen for parent in step.depends_on):
                raise ValueError("workflow parent is missing or steps are not in dependency order")
            seen.add(step.id)
        return self

    @property
    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))


class NativeWorkflowLineage(Model):
    input_artifact_id: str
    parent_step_id: str
    parent_execution_id: str
    parent_submission_digest: str
    output_artifact_id: str
    source_input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class NativeWorkflowStepResult(Model):
    step_id: str
    task_id: str
    operation: str
    execution_id: str
    status: Literal["graded", "harness_failed", "blocked"]
    grade: NativeGrade
    submission_digest: str
    lineage: tuple[NativeWorkflowLineage, ...] = ()
    failure_code: str | None = None
    failure_detail: str | None = None


class NativeWorkflowQualification(Model):
    workflow_digest: str
    passed: bool
    steps: tuple[NativeWorkflowStepResult, ...]


class NativeWorkflowRun(Model):
    schema_version: Literal["worldloom.native-workflow-run/v1"] = "worldloom.native-workflow-run/v1"
    run_id: str
    workflow_digest: str
    benchmark_digest: str
    harness_identity: dict[str, Any]
    observation: Literal["runner_scheduled_calls_and_staged_bytes"] = "runner_scheduled_calls_and_staged_bytes"
    total: int
    passed_count: int
    blocked_count: int
    harness_failures: int
    passed: bool
    steps: tuple[NativeWorkflowStepResult, ...]


def workflow_capabilities() -> dict[str, Any]:
    """State the execution boundary without claiming legacy DAG equivalence."""
    return {"schema": "worldloom.native-workflow-capabilities/v1", "maximum_steps": 256,
        "supported": ["source_bound_authored_dag", "ordered_dependencies", "read", "analyze", "update", "create",
            "graded_update_bytes_as_inputs", "reference_graph_qualification", "independent_step_grading",
            "failure_blocking", "policy_pinning", "deterministic_resume", "receipt_lineage_verification"],
        "unavailable": ["conditional_branches", "iteration", "created_artifact_input_contracts", "modified_input_write_contracts",
            "target_internal_tool_trajectory", "autonomous_agent_plan_scoring"],
        "observation": "runner_scheduled_calls_and_staged_bytes"}


def validate_workflow(benchmark: NativeBenchmark, plan: NativeWorkflowPlan) -> None:
    """Rebuild benchmark truth before interpreting any authored graph binding."""
    NativeWorkflowPlan.model_validate(plan.model_dump(mode="json"))
    benchmark.validate()
    if plan.benchmark_digest != benchmark.digest:
        raise ValueError("native workflow benchmark identity changed")
    tasks = {task.id: task for task in benchmark.workload.tasks}
    prior: dict[str, NativeTask] = {}
    for step in plan.steps:
        if step.task_id not in tasks:
            raise ValueError("native workflow references an unknown benchmark task: " + step.task_id)
        task = tasks[step.task_id]
        if step.input_bindings and task.output is not None:
            raise ValueError("native workflow modified-input writes need a derived output contract")
        inputs = {item.artifact_id: item for item in task.inputs}
        for binding in step.input_bindings:
            if binding.input_artifact_id not in inputs:
                raise ValueError("native workflow binds an undeclared input")
            output = prior[binding.parent_step_id].output
            if output is None:
                raise ValueError("native workflow file parent has no output")
            if output.format != inputs[binding.input_artifact_id].format:
                raise ValueError("native workflow input and parent output formats differ")
            if output.source_artifact_id != binding.input_artifact_id:
                raise ValueError("native workflow input requires a parent update of the same source artifact")
        prior[step.id] = task


def _task_inputs(task: NativeTask, step: NativeWorkflowStep, inputs: Mapping[str, bytes],
                 results: Mapping[str, NativeWorkflowStepResult], submissions: Mapping[str, NativeSubmission],
                 ) -> tuple[NativeTask, dict[str, bytes], tuple[NativeWorkflowLineage, ...]]:
    bound_inputs = {item.artifact_id: inputs[item.artifact_id] for item in task.inputs}
    declarations = {item.artifact_id: item for item in task.inputs}
    lineage: list[NativeWorkflowLineage] = []
    for binding in step.input_bindings:
        parent = results[binding.parent_step_id]
        if not parent.grade.passed:
            raise ValueError("cannot bind a failed workflow parent")
        # The grader has already required exactly one declared native output.
        produced = submissions[binding.parent_step_id].files[0]
        payload = base64.b64decode(produced.content_base64, validate=True)
        checksum = hashlib.sha256(payload).hexdigest()
        bound_inputs[binding.input_artifact_id] = payload
        declarations[binding.input_artifact_id] = declarations[binding.input_artifact_id].model_copy(update={"sha256": checksum})
        lineage.append(NativeWorkflowLineage(input_artifact_id=binding.input_artifact_id,
            parent_step_id=binding.parent_step_id, parent_execution_id=parent.execution_id,
            parent_submission_digest=parent.submission_digest, output_artifact_id=produced.artifact_id,
            source_input_sha256=next(item.sha256 for item in task.inputs if item.artifact_id == binding.input_artifact_id),
            sha256=checksum))
    # Only staged input checksums vary. Authored plans cannot rewrite locators,
    # expected output content, calculations or preservation requirements.
    bound_task = NativeTask.model_validate({**task.model_dump(mode="json"),
        "inputs": [declarations[item.artifact_id].model_dump(mode="json") for item in task.inputs]})
    return bound_task, bound_inputs, tuple(lineage)


def _result(task: NativeTask, step: NativeWorkflowStep, inputs: Mapping[str, bytes], submission: NativeSubmission, *,
            execution_id: str, lineage: tuple[NativeWorkflowLineage, ...] = (),
            failure_code: str | None = None, failure_detail: str | None = None,
            blocked: bool = False) -> NativeWorkflowStepResult:
    if blocked:
        grade = NativeGrade(passed=False, findings=("workflow_dependency_failed",), metrics={"assertions": 0})
    else:
        grade = grade_native_task(task, inputs, submission)
        if failure_code:
            grade = NativeGrade(passed=False, findings=(failure_code, *grade.findings), metrics=grade.metrics)
    return NativeWorkflowStepResult(step_id=step.id, task_id=step.task_id, operation=task.operation,
        execution_id=execution_id, status="blocked" if blocked else "harness_failed" if failure_code else "graded",
        grade=grade, submission_digest=digest(submission.model_dump(mode="json")), lineage=lineage,
        failure_code=failure_code, failure_detail=failure_detail)


def qualify_workflow(benchmark: NativeBenchmark, plan: NativeWorkflowPlan) -> NativeWorkflowQualification:
    """Reference-execute every required step against actual predecessor bytes."""
    validate_workflow(benchmark, plan)
    tasks = {task.id: task for task in benchmark.workload.tasks}
    results: dict[str, NativeWorkflowStepResult] = {}
    submissions: dict[str, NativeSubmission] = {}
    for step in plan.steps:
        task = tasks[step.task_id]
        execution_id = digest(["native-workflow-reference/v1", plan.digest, step.id])
        blocked = any(not results[parent].grade.passed for parent in step.depends_on)
        submission = NativeSubmission()
        inputs: dict[str, bytes] = {}
        lineage: tuple[NativeWorkflowLineage, ...] = ()
        failure_code = None
        failure_detail = None
        if not blocked:
            task, inputs, lineage = _task_inputs(task, step, benchmark.inputs, results, submissions)
            try:
                submission = reference_submission(task, inputs)
            except (ValueError, KeyError, OSError, ArithmeticError, ImportError, TypeError) as error:
                failure_code, failure_detail = "workflow_reference_invalid", type(error).__name__
        results[step.id] = _result(task, step, inputs, submission, execution_id=execution_id, lineage=lineage,
            failure_code=failure_code, failure_detail=failure_detail, blocked=blocked)
        submissions[step.id] = submission
    return NativeWorkflowQualification(workflow_digest=plan.digest,
        passed=all(item.grade.passed for item in results.values()), steps=tuple(results[step.id] for step in plan.steps))


def _request(task: NativeTask, step: NativeWorkflowStep, execution_id: str,
             results: Mapping[str, NativeWorkflowStepResult], submissions: Mapping[str, NativeSubmission],
             lineage: tuple[NativeWorkflowLineage, ...]) -> dict[str, Any]:
    return {**public_contract(task), "execution_id": execution_id,
        "workflow": {"step_id": step.id, "parents": [
            {"step_id": parent, "execution_id": results[parent].execution_id,
             "submission_digest": results[parent].submission_digest,
             "answers": [answer.model_dump(mode="json") for answer in submissions[parent].answers]}
            for parent in step.depends_on], "input_lineage": [item.model_dump(mode="json") for item in lineage]}}


def run_workflow(benchmark: NativeBenchmark, plan: NativeWorkflowPlan, harness: NativeHarness, *,
                 directory: Path, resume: bool = False, agent: AgentUnderTest | None = None) -> NativeWorkflowRun:
    """Run a qualified DAG and resume only a fully regraded receipt prefix.

    A failed required parent blocks its descendants; independent branches still
    run. Every completed step has a receipt, including blocked steps. An
    interrupted, uncommitted call may be reissued under the same execution id.
    The existing harness trust boundary applies; this is not an OS sandbox.
    """
    qualification = qualify_workflow(benchmark, plan)
    if not qualification.passed:
        failed = next(item for item in qualification.steps if not item.grade.passed)
        raise ValueError("native workflow reference qualification failed at " + failed.step_id + ": " + ",".join(failed.grade.findings))
    harness_identity = _canonical(harness.identity)
    if not harness_identity:
        raise ValueError("native workflow harness needs an explicit identity")
    agent_identity = _canonical(_public_agent(agent)) if agent is not None else None
    configuration = {"schema": "worldloom.native-workflow-configuration/v1", "plan": plan.model_dump(mode="json"),
        "benchmark_digest": benchmark.digest, "source_digest": benchmark.source_digest,
        "harness": harness_identity, "agent": agent_identity, "grader": native_grader_identity(),
        "runner_sha256": _file_digest(Path(__file__)),
        "harness_adapter_sha256": _file_digest(Path(__file__).with_name("runner.py")),
        "qualification": qualification.model_dump(mode="json")}
    directory = Path(directory).absolute()
    if directory.is_symlink():
        raise ValueError("native workflow directory may not be a symlink")
    run_id = digest([configuration, str(directory.resolve())])
    manifest = _seal({**configuration, "run_id": run_id})
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock = directory.parent / ("." + directory.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ValueError("native workflow is locked; verify no process is active before removing the lock") from error
    os.close(descriptor)
    try:
        if directory.exists():
            if not resume:
                raise ValueError("native workflow run exists; use resume for the exact configuration")
            if _read_json(directory / "manifest.json") != manifest:
                raise ValueError("native workflow configuration changed; create a new run")
        else:
            if resume:
                raise ValueError("cannot resume a missing native workflow run")
            directory.mkdir()
            _atomic_json(directory / "manifest.json", manifest)
        receipts = directory / "receipts"
        if receipts.is_symlink():
            raise ValueError("native workflow receipt directory may not be a symlink")
        receipts.mkdir(exist_ok=True)
        paths = {step.id: receipts / (digest([step.id]) + ".json") for step in plan.steps}
        expected = {path.name for path in paths.values()}
        if any(path.name not in expected and path.name.removesuffix(".pending") not in expected for path in receipts.iterdir()):
            raise ValueError("native workflow contains unknown step receipts")
        raw: dict[str, dict[str, Any]] = {}
        missing = False
        for step in plan.steps:
            path = paths[step.id]
            if not (path.exists() or path.is_symlink()):
                missing = True
            elif missing:
                raise ValueError("native workflow receipt order has a missing predecessor")
            else:
                raw[step.id] = _unseal(_read_json(path))
        if (directory / "run.json").exists() and missing:
            raise ValueError("completed native workflow is missing step receipts")
        tasks = {task.id: task for task in benchmark.workload.tasks}
        results: dict[str, NativeWorkflowStepResult] = {}
        submissions: dict[str, NativeSubmission] = {}
        previous_digest: str | None = None

        def execute(step: NativeWorkflowStep, index: int, saved: dict[str, Any] | None) -> None:
            nonlocal previous_digest
            task = tasks[step.task_id]
            parents = {parent: results[parent].model_dump(mode="json") for parent in step.depends_on}
            execution_id = digest([run_id, step.id, parents])
            blocked = any(not results[parent].grade.passed for parent in step.depends_on)
            inputs: dict[str, bytes] = {}
            lineage: tuple[NativeWorkflowLineage, ...] = ()
            if not blocked:
                task, inputs, lineage = _task_inputs(task, step, benchmark.inputs, results, submissions)
            request = _request(task, step, execution_id, results, submissions, lineage)
            pins = {"schema": "worldloom.native-workflow-receipt/v1", "run_id": run_id, "step_id": step.id,
                "index": index, "execution_id": execution_id, "previous_receipt_digest": previous_digest,
                "parents": {parent: digest(value) for parent, value in sorted(parents.items())},
                "task_digest": digest(task.model_dump(mode="json")), "request_digest": digest(request)}
            failure_code = None
            failure_detail = None
            submission = NativeSubmission()
            if saved is not None:
                if set(saved) != {"pins", "submission", "result"} or saved.get("pins") != pins:
                    raise ValueError("native workflow receipt has wrong order, parents, task or lineage")
                submission = NativeSubmission.model_validate(saved["submission"])
                prior = NativeWorkflowStepResult.model_validate(saved["result"])
                failure_code, failure_detail = prior.failure_code, prior.failure_detail
                if blocked and (submission != NativeSubmission() or failure_code is not None or failure_detail is not None):
                    raise ValueError("native workflow blocked step has a fabricated submission")
            elif not blocked:
                try:
                    submission = NativeSubmission.model_validate(harness.submit(_canonical(request), dict(inputs), agent=agent))
                except HarnessFailure as error:
                    failure_code, failure_detail = error.code, error.detail
                except Exception as error:
                    failure_code, failure_detail = "harness_exception", type(error).__name__
            result = _result(task, step, inputs, submission, execution_id=execution_id, lineage=lineage,
                failure_code=failure_code, failure_detail=failure_detail, blocked=blocked)
            document = {"pins": pins, "submission": submission.model_dump(mode="json"), "result": result.model_dump(mode="json")}
            if saved is not None:
                if saved != document:
                    raise ValueError("native workflow receipt disagrees with independent byte grading or lineage")
            else:
                check_identity()
                _atomic_json(paths[step.id], _seal(document))
            results[step.id], submissions[step.id] = result, submission
            previous_digest = digest(document)

        def check_identity() -> None:
            current_agent = _canonical(_public_agent(agent)) if agent is not None else None
            if _canonical(harness.identity) != harness_identity or current_agent != agent_identity:
                raise ValueError("native workflow harness or policy identity changed during the run")

        # Inspect the entire saved prefix before any new target call. Neither a
        # rehashed success nor a forged predecessor link earns resumed credit.
        for index, step in enumerate(plan.steps):
            if step.id in raw:
                execute(step, index, raw[step.id])
        for index, step in enumerate(plan.steps):
            check_identity()
            if step.id not in raw:
                execute(step, index, None)
        ordered = tuple(results[step.id] for step in plan.steps)
        passed_count = sum(result.grade.passed for result in ordered)
        report = NativeWorkflowRun(run_id=run_id, workflow_digest=plan.digest, benchmark_digest=benchmark.digest,
            harness_identity=harness_identity, total=len(ordered), passed_count=passed_count,
            blocked_count=sum(result.status == "blocked" for result in ordered),
            harness_failures=sum(result.status == "harness_failed" for result in ordered),
            passed=passed_count == len(ordered), steps=ordered)
        summary = report.model_dump(mode="json")
        if (directory / "run.json").exists() and _read_json(directory / "run.json") != summary:
            raise ValueError("native workflow saved aggregate differs from its step receipts")
        _atomic_json(directory / "run.json", summary)
        return report
    finally:
        lock.unlink()


__all__ = ["NativeWorkflowInput", "NativeWorkflowStep", "NativeWorkflowPlan", "NativeWorkflowLineage",
    "NativeWorkflowStepResult", "NativeWorkflowQualification", "NativeWorkflowRun",
    "validate_workflow", "qualify_workflow", "run_workflow", "workflow_capabilities"]
