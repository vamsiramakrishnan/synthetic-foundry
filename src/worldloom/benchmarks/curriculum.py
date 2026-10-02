"""Measured training failures drive fresh source, query and evaluation demands.

This is a deterministic curriculum compiler, not a second policy optimizer.
Policy revisions continue through ``improve_benchmark`` and its sealed fresh
qualification tranches. No held-out result or free-text target diagnostic is
accepted by this seam; benchmark roles are part of their persisted identity.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from ..evalrun.qualification import QualificationPolicy, evidence_components
from ..models import Model
from ..native_eval_bridge import native_grader_identity, native_task_cases
from ..native_query_planning import NativeWorkloadPlan
from ..native_requirements import BenchmarkRequirements
from ..native_tasks import NativeSubmission, NativeTask
from ..providers import digest
from .core import NativeBenchmark
from .requirements import resolve_requirements
from .runner import (
    BenchmarkRun,
    BenchmarkTrial,
    NativeHarness,
    _atomic_json,
    _pins,
    _read_json,
    _trial,
    _unseal,
    run_benchmark,
)
from .scenarios import NativeScenarioDemand, build_native_scenarios

if TYPE_CHECKING:
    from ..world import World
    from .coverage import BenchmarkAssessment

CurriculumAblation = Literal["none", "without_failures", "without_coverage"]
_HEX = r"^[a-f0-9]{64}$"
_ADDRESS = r"^[a-f0-9]{32}$"
_GRADE_CODES = frozenset({"input_missing_or_oversized", "input_invalid", "answer_set_mismatch",
    "answer_failed", "unexpected_output_files", "output_set_mismatch", "output_type_failed",
    "output_type_requires_cell", "output_assertion_failed", "update_source_version_mismatch",
    "update_target_missing_in_source", "update_did_not_change_content", "update_unaffected_content_changed",
    "output_invalid"})


class _CurriculumSettings(Model):
    """Static diagnosis inputs validated before any target execution."""

    namespace: str = Field(min_length=1)
    version: int = Field(ge=1, strict=True)
    parent_digest: str | None = Field(default=None, pattern=_ADDRESS)
    ablation: CurriculumAblation = "none"
    requirements: BenchmarkRequirements
    qualification_policy: QualificationPolicy

    @model_validator(mode="after")
    def _declared(self) -> _CurriculumSettings:
        if not self.namespace.strip():
            raise ValueError("curriculum needs a stable source namespace")
        if (self.version == 1) != (self.parent_digest is None):
            raise ValueError("curriculum versions after one require a parent receipt")
        return self


def _settings(
    training: NativeBenchmark, *, namespace: str, requirements: BenchmarkRequirements | None,
    qualification_policy: QualificationPolicy | None, version: int, parent_digest: str | None,
    ablation: CurriculumAblation,
) -> _CurriculumSettings:
    settings = _CurriculumSettings.model_validate({"namespace": namespace, "version": version,
        "parent_digest": parent_digest, "ablation": ablation,
        "requirements": resolve_requirements(training.workload.plan, additional=requirements).model_dump(mode="json"),
        "qualification_policy": (qualification_policy or QualificationPolicy()).model_dump(mode="json")})
    if settings.qualification_policy.unit_dimension is not None:
        cases = native_task_cases(training.workload.tasks, training.rendered, namespace=namespace, world=training.world)
        evidence_components(cases, unit_dimension=settings.qualification_policy.unit_dimension)
    return settings


class CurriculumFailure(Model):
    code: str
    trials: int = Field(ge=1)


class CurriculumObservation(Model):
    """Descriptive counts; repeated failures never become independent units."""

    capability: str
    tasks: int = Field(ge=1)
    independent_units: int = Field(ge=1)
    trials: int = Field(ge=1)
    failures: int = Field(ge=0)
    failure_codes: tuple[CurriculumFailure, ...]


class CurriculumDemand(Model):
    stage: Literal["SOURCE", "QUERY", "EVAL"]
    capability: str
    reason: Literal["measured_failure", "independent_unit_shortfall", "fresh_qualification", "paired_repeats"]
    independent_units: int = Field(default=0, ge=0)
    additional_units: int = Field(default=0, ge=0)
    repeats: int = Field(default=0, ge=0)
    observed_failures: int = Field(default=0, ge=0)


class NativeCurriculum(Model):
    """Content-addressed proposal for a new training corpus, never a gain claim."""

    schema_version: Literal["worldloom.native-curriculum/v1"] = "worldloom.native-curriculum/v1"
    digest: str = Field(pattern=_ADDRESS)
    version: int = Field(ge=1, strict=True)
    parent_digest: str | None = Field(default=None, pattern=_ADDRESS)
    namespace: str = Field(min_length=1)
    training_benchmark_digest: str = Field(pattern=_HEX)
    source_digest: str = Field(pattern=_HEX)
    training_run_id: str = Field(pattern=_ADDRESS)
    training_run_digest: str = Field(pattern=_ADDRESS)
    feedback_split: Literal["training"] = "training"
    ablation: CurriculumAblation = "none"
    requirements: BenchmarkRequirements
    qualification_policy: QualificationPolicy
    observations: tuple[CurriculumObservation, ...]
    demands: tuple[CurriculumDemand, ...]
    scenario_demand: NativeScenarioDemand
    next_plan: NativeWorkloadPlan
    qualification: Literal["new_study_with_fresh_heldout_required"] = "new_study_with_fresh_heldout_required"

    @model_validator(mode="after")
    def _receipt(self) -> NativeCurriculum:
        _CurriculumSettings.model_validate(self.model_dump(mode="json", include=set(_CurriculumSettings.model_fields)))
        if self.digest != digest(self.model_dump(mode="json", exclude={"digest"})):
            raise ValueError("curriculum receipt checksum changed")
        return self


@dataclass(frozen=True)
class NativeCurriculumBuild:
    world: World
    benchmark: NativeBenchmark
    curriculum: NativeCurriculum
    assessment: BenchmarkAssessment


def _training(benchmark: NativeBenchmark) -> None:
    if benchmark.split_role != "training":
        raise ValueError("curriculum feedback requires a benchmark sealed with split_role='training'; heldout and unspecified packages are refused")
    benchmark.validate()


def _check_run(training: NativeBenchmark, report: BenchmarkRun) -> None:
    """Reject stale packages, unknown/missing trials and forged aggregate counts."""
    _training(training)
    if report.benchmark_digest != training.digest:
        raise ValueError("curriculum run does not belong to the sealed training benchmark")
    if report.repeats < 1 or not report.harness_identity:
        raise ValueError("curriculum run requires repeats and a pinned harness identity")
    tasks = {task.id: task for task in training.workload.tasks}
    expected = {(task_id, repeat) for task_id in tasks for repeat in range(1, report.repeats + 1)}
    actual = {(trial.task_id, trial.repeat) for trial in report.trials}
    if actual != expected or len(actual) != len(report.trials):
        raise ValueError("curriculum run trials must cover the training benchmark exactly once per repeat")
    for trial in report.trials:
        if (trial.execution_id != digest([report.run_id, trial.task_id, trial.repeat])
                or trial.operation != tasks[trial.task_id].operation):
            raise ValueError("curriculum trial execution or operation identity changed")
        if ((trial.status == "harness_failed") != (trial.failure_code is not None)
                or trial.grade.passed == bool(trial.grade.findings)):
            raise ValueError("curriculum trial status disagrees with its grade")
    passed = sum(trial.grade.passed for trial in report.trials)
    failures = sum(trial.status == "harness_failed" for trial in report.trials)
    if (report.total != len(report.trials) or report.passed_count != passed
            or report.failed_count != len(report.trials) - passed or report.harness_failures != failures
            or report.passed != (passed == len(report.trials))):
        raise ValueError("curriculum run aggregate disagrees with its trials")


def load_training_run(training: NativeBenchmark, directory: Path) -> BenchmarkRun:
    """Regrade persisted training submissions without executing the target again.

    A summary alone cannot prove its grade. The CLI uses this loader before
    diagnosis so editing ``run.json`` cannot invent a measured improvement.
    Receipt checksums detect modification, not hostile replacement of an entire
    evaluator and all of its source evidence.
    """
    directory = Path(directory).absolute()
    if directory.is_symlink():
        raise ValueError("curriculum run directory may not be a symlink")
    report = BenchmarkRun.model_validate(_read_json(directory / "run.json"))
    _check_run(training, report)
    manifest = _unseal(_read_json(directory / "manifest.json"))
    configuration = {key: value for key, value in manifest.items() if key != "run_id"}
    if (manifest.get("run_id") != report.run_id
            or digest([configuration, str(directory.resolve())]) != report.run_id
            or manifest.get("benchmark_digest") != training.digest
            or manifest.get("workload_digest") != digest(training.workload.model_dump(mode="json"))
            or manifest.get("harness") != report.harness_identity or manifest.get("repeats") != report.repeats
            or manifest.get("grader") != native_grader_identity()):
        raise ValueError("curriculum run manifest differs from its sealed configuration")
    receipt_root = directory / "receipts"
    if receipt_root.is_symlink():
        raise ValueError("curriculum receipt directory may not be a symlink")
    tasks = {task.id: task for task in training.workload.tasks}
    for trial in report.trials:
        task = tasks[trial.task_id]
        saved = _unseal(_read_json(receipt_root / (digest([trial.task_id, trial.repeat]) + ".json")))
        if set(saved) != {"pins", "submission", "trial"} or saved["pins"] != _pins(task, report.run_id, trial.repeat):
            raise ValueError("curriculum trial receipt differs from its sealed task")
        submission = NativeSubmission.model_validate(saved["submission"])
        measured = _trial(task, {item.artifact_id: training.inputs[item.artifact_id] for item in task.inputs},
            submission, repeat=trial.repeat, execution_id=trial.execution_id,
            failure_code=trial.failure_code, failure_detail=trial.failure_detail)
        if measured != trial or saved["trial"] != measured.model_dump(mode="json"):
            raise ValueError("curriculum saved grade differs from independent byte grading")
    return report


def _capabilities(task: NativeTask) -> tuple[str, ...]:
    formats = {task.output.format} if task.output is not None else {item.format for item in task.inputs}
    return tuple(f"{task.operation}:{format}" for format in sorted(formats))


def _failure_codes(trial: BenchmarkTrial) -> tuple[str, ...]:
    # Assertion IDs, artifact IDs, exception strings and stderr can contain
    # arbitrary data. Only a closed diagnostic vocabulary reaches proposers.
    codes = {finding.split(":", 1)[0] for finding in trial.grade.findings}
    clean = {code if code in _GRADE_CODES else "native_grade_failure" for code in codes}
    if trial.status == "harness_failed":
        clean.add("harness_failure")
    return tuple(sorted(clean))


def diagnose_benchmark(
    training: NativeBenchmark, run_directory: Path, *, namespace: str,
    requirements: BenchmarkRequirements | None = None,
    qualification_policy: QualificationPolicy | None = None,
    version: int = 1, parent_digest: str | None = None, ablation: CurriculumAblation = "none",
) -> NativeCurriculum:
    """Compile SOURCE/QUERY/EVAL proposals using only designated training runs.

    Supply the committed run directory, never a bare summary. Every call
    independently regrades its actual submissions. Counts describe observed target
    outcomes; the next corpus is a proposal requiring another measured run.
    Held-out evidence is absent from this API, including held-out failure text.
    """
    if not isinstance(run_directory, (str, Path)):
        raise ValueError("curriculum diagnosis requires a committed run directory, never a bare report")
    settings = _settings(training, namespace=namespace, requirements=requirements,
        qualification_policy=qualification_policy, version=version, parent_digest=parent_digest, ablation=ablation)
    report = load_training_run(training, Path(run_directory))
    policy = settings.qualification_policy
    required = settings.requirements
    assessment = training.assess(namespace=namespace, requirements=required, qualification_policy=policy,
        repeats=report.repeats)
    cases = native_task_cases(training.workload.tasks, training.rendered, namespace=namespace, world=training.world)
    components = evidence_components(cases, unit_dimension=policy.unit_dimension)
    tasks = {task.id: task for task in training.workload.tasks}
    by_capability: dict[str, list[BenchmarkTrial]] = {}
    for trial in report.trials:
        for capability in _capabilities(tasks[trial.task_id]):
            by_capability.setdefault(capability, []).append(trial)
    observations: list[CurriculumObservation] = []
    demands: list[CurriculumDemand] = []
    for capability, trials in sorted(by_capability.items()):
        task_ids = {trial.task_id for trial in trials}
        codes = Counter(code for trial in trials if not trial.grade.passed for code in _failure_codes(trial))
        failures = sum(not trial.grade.passed for trial in trials)
        units = len({components[task_id] for task_id in task_ids})
        observations.append(CurriculumObservation(capability=capability, tasks=len(task_ids), independent_units=units,
            trials=len(trials), failures=failures,
            failure_codes=tuple(CurriculumFailure(code=code, trials=count) for code, count in sorted(codes.items()))))
        if failures and ablation != "without_failures":
            demands.extend(CurriculumDemand(stage=stage, capability=capability, reason="measured_failure",
                independent_units=max(policy.min_units, units), additional_units=max(1, policy.min_units - units),
                observed_failures=failures) for stage in ("SOURCE", "QUERY"))
    if ablation != "without_coverage":
        for cell in assessment.required_coverage:
            if not cell.satisfied:
                shortfall = max(0, cell.required_units - (cell.independent_units or 0))
                demands.extend(CurriculumDemand(stage=stage, capability=cell.name,
                    reason="independent_unit_shortfall", independent_units=cell.required_units,
                    additional_units=shortfall) for stage in ("SOURCE", "QUERY"))
    demands.extend((CurriculumDemand(stage="EVAL", capability="qualification", reason="fresh_qualification",
        independent_units=policy.trials * policy.min_units, additional_units=policy.trials * policy.min_units),
        CurriculumDemand(stage="EVAL", capability="paired_target_runs", reason="paired_repeats",
            repeats=policy.min_repeats)))
    # Fresh tranches must support each declared cell as well as the aggregate.
    # This budget is computed from policy, never inferred from held-out scores.
    demands.extend(CurriculumDemand(stage="EVAL", capability=cell.name, reason="fresh_qualification",
        independent_units=policy.trials * max(policy.min_units, cell.min_independent_units),
        additional_units=policy.trials * max(policy.min_units, cell.min_independent_units)) for cell in required.cells)
    ordered = tuple(sorted(demands, key=lambda item: (item.stage, item.capability, item.reason)))
    identity = {"version": version, "parent_digest": parent_digest, "namespace": namespace,
        "training_benchmark_digest": training.digest, "source_digest": training.source_digest,
        "training_run_id": report.run_id, "training_run_digest": digest(report.model_dump(mode="json")),
        "ablation": ablation, "requirements": required.model_dump(mode="json"),
        "qualification_policy": policy.model_dump(mode="json"), "demands": [item.model_dump(mode="json") for item in ordered]}
    batch = "curriculum-" + digest(identity)[:24]
    # Native scenario episodes are disjoint source families. The maximum is a
    # bounded build budget; assessment reports any still-unmet larger demand.
    requested_processes = {dimension.value for cell in required.cells for dimension in cell.dimensions
        if dimension.name == "scenario_process"}
    supported_processes = NativeScenarioDemand().processes
    processes = tuple(process for process in supported_processes if process in requested_processes) or supported_processes
    source_units = [item.independent_units for item in demands if item.stage == "SOURCE"]
    episodes = min(256, len(processes) * max(source_units, default=1))
    scenario = NativeScenarioDemand(episodes=episodes, processes=processes, batch_id=batch)
    requested_operations = {cell.operation for cell in required.cells if cell.operation is not None}
    if any(cell.calculation is not None for cell in required.cells):
        requested_operations.add("analyze")
    operations = tuple(sorted(set(training.workload.plan.operations) | requested_operations))
    formats = tuple(sorted(set(training.workload.plan.formats) | {
        cell.format for cell in required.cells if cell.format is not None}))
    scope = "mixed" if any(cell.scope is not None for cell in required.cells) else training.workload.plan.discovery_scope
    next_plan = NativeWorkloadPlan(use_case_id=batch, objective="Practice measured native capabilities on fresh business evidence.",
        operations=operations, formats=formats, discovery_scope=scope,
        max_tasks=min(10000, max(training.workload.plan.max_tasks, episodes * len(operations) * len(formats) * 4)),
        requirements=required)
    body = {**identity, "schema_version": "worldloom.native-curriculum/v1", "feedback_split": "training",
        "observations": [item.model_dump(mode="json") for item in observations],
        "scenario_demand": scenario.model_dump(mode="json"), "next_plan": next_plan.model_dump(mode="json"),
        "qualification": "new_study_with_fresh_heldout_required"}
    return NativeCurriculum.model_validate({**body, "digest": digest(body)})


def build_curriculum_training(
    training: NativeBenchmark, run_directory: Path, curriculum: NativeCurriculum,
) -> NativeCurriculumBuild:
    """Materialize proposed source changes, then report actual delivered coverage.

    A fresh batch creates new canonical evidence, native bytes and task IDs.
    Pass its benchmark to the existing policy improvement loop with a newly
    partitioned held-out pool and a new study directory, never an old seal.
    """
    curriculum = NativeCurriculum.model_validate(curriculum.model_dump(mode="json"))
    expected = diagnose_benchmark(training, run_directory, namespace=curriculum.namespace,
        requirements=curriculum.requirements, qualification_policy=curriculum.qualification_policy,
        version=curriculum.version, parent_digest=curriculum.parent_digest, ablation=curriculum.ablation)
    if expected != curriculum:
        raise ValueError("curriculum differs from independently verified training feedback; diagnose again")
    scenario = build_native_scenarios(training.world, curriculum.scenario_demand)
    benchmark = NativeBenchmark.from_rendered(scenario.world, scenario.render(formats=curriculum.next_plan.formats),
        curriculum.next_plan, split_role="training")
    if benchmark.digest == curriculum.training_benchmark_digest:
        raise ValueError("curriculum must produce a fresh benchmark identity")
    assessment = benchmark.assess(namespace=curriculum.namespace, requirements=curriculum.requirements,
        qualification_policy=curriculum.qualification_policy)
    return NativeCurriculumBuild(world=scenario.world, benchmark=benchmark, curriculum=curriculum, assessment=assessment)


def run_training_curriculum(
    training: NativeBenchmark, harness: NativeHarness, *, directory: Path, namespace: str,
    repeats: int = 1, resume: bool = False, requirements: BenchmarkRequirements | None = None,
    qualification_policy: QualificationPolicy | None = None, version: int = 1,
    parent_digest: str | None = None, ablation: CurriculumAblation = "none",
) -> NativeCurriculum:
    """Run, independently grade, diagnose and persist a replayable next proposal."""
    _training(training)
    settings = _settings(training, namespace=namespace, requirements=requirements,
        qualification_policy=qualification_policy, version=version, parent_digest=parent_digest, ablation=ablation)
    path = Path(directory) / "curriculum.json"
    if path.exists() or path.is_symlink():
        prior = NativeCurriculum.model_validate(_read_json(path))
        prior_settings = _CurriculumSettings.model_validate(prior.model_dump(mode="json",
            include=set(_CurriculumSettings.model_fields)))
        if prior.training_benchmark_digest != training.digest or prior_settings != settings:
            raise ValueError("curriculum configuration changed; create a new training run")
    run_benchmark(training, harness, directory=directory, repeats=repeats, resume=resume)
    curriculum = diagnose_benchmark(training, directory, namespace=namespace, requirements=requirements,
        qualification_policy=qualification_policy, version=version, parent_digest=parent_digest, ablation=ablation)
    document = curriculum.model_dump(mode="json")
    if path.exists() and _read_json(path) != document:
        raise ValueError("curriculum configuration changed; create a new training run")
    _atomic_json(path, document)
    return curriculum


__all__ = ["CurriculumAblation", "CurriculumFailure", "CurriculumObservation", "CurriculumDemand",
    "NativeCurriculum", "NativeCurriculumBuild", "load_training_run", "diagnose_benchmark",
    "build_curriculum_training", "run_training_curriculum"]
