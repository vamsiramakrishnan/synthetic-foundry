"""Real native replies drive training-only, replayable curriculum proposals."""
from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from worldloom import RetailWorld
from worldloom.benchmarks.core import NativeBenchmark
from worldloom.benchmarks.curriculum import (
    NativeCurriculum,
    build_curriculum_training,
    diagnose_benchmark,
    load_training_run,
    run_training_curriculum,
)
from worldloom.benchmarks.runner import (
    BenchmarkRun,
    CallableHarness,
    HarnessFailure,
    run_benchmark,
)
from worldloom.benchmarks.scenarios import NativeScenarioDemand, build_native_scenarios
from worldloom.corpus import write_json
from worldloom.evalrun.qualification import QualificationPolicy
from worldloom.native_query_planning import NativeWorkloadPlan
from worldloom.native_requirements import (
    BenchmarkRequirements,
    CoverageDimension,
    CoverageRequirement,
)
from worldloom.native_tasks import NativeGrade, NativeSubmission
from worldloom.providers import digest


@pytest.fixture(scope="module")
def training() -> NativeBenchmark:
    pytest.importorskip("docx")
    scenarios = build_native_scenarios(RetailWorld(seed=8128).build(), NativeScenarioDemand(
        episodes=3, processes=("supplier_reconciliation",), batch_id="curriculum-seed"))
    return NativeBenchmark.from_rendered(scenarios.world, scenarios.render(formats=("docx",)),
        NativeWorkloadPlan(use_case_id="training", objective="Read transaction evidence.",
            formats=("docx",), operations=("read",), max_tasks=6, discovery_scope="artifact"),
        split_role="training")


@pytest.fixture(scope="module")
def measured(training: NativeBenchmark, tmp_path_factory: pytest.TempPathFactory) -> tuple[BenchmarkRun, Path]:
    def fail(_: dict[str, Any], __: Any) -> NativeSubmission:
        raise HarnessFailure("custom-error:DO_NOT_COPY_FAILURE_CONTENT", "PRIVATE_TARGET_STDERR")

    directory = tmp_path_factory.mktemp("curriculum") / "run"
    report = run_benchmark(training, CallableHarness(fail, {"kind": "failing-reader-v1"}),
        directory=directory, repeats=2)
    return report, directory


def _diagnose(training: NativeBenchmark, directory: Path, **kwargs: Any) -> NativeCurriculum:
    return diagnose_benchmark(training, directory, namespace=training.world.company.id,
        qualification_policy=QualificationPolicy(trials=1, min_units=2), **kwargs)


@contextmanager
def _rewritten_report(directory: Path, report: BenchmarkRun) -> Iterator[None]:
    path = directory / "run.json"
    original = path.read_bytes()
    try:
        write_json(path, report.model_dump(mode="json"))
        yield
    finally:
        path.write_bytes(original)


def test_actual_failures_compile_source_query_eval_demands_and_sanitize_details(
    training: NativeBenchmark, measured: tuple[BenchmarkRun, Path],
) -> None:
    report, directory = measured
    assert load_training_run(training, directory) == report
    result = _diagnose(training, directory)
    assert result == _diagnose(training, directory)
    assert result.feedback_split == "training"
    assert result.training_run_id == report.run_id
    assert result.training_run_digest == digest(report.model_dump(mode="json"))
    assert {item.stage for item in result.demands} == {"SOURCE", "QUERY", "EVAL"}
    assert result.observations[0].failures == len(report.trials)
    assert result.observations[0].independent_units == 3
    assert result.observations[0].independent_units < result.observations[0].trials
    document = result.model_dump_json()
    assert "PRIVATE_TARGET_STDERR" not in document and "DO_NOT_COPY_FAILURE_CONTENT" not in document
    assert all(task.prompt not in document for task in training.workload.tasks)
    assert {item.code for item in result.observations[0].failure_codes} >= {"harness_failure", "answer_set_mismatch"}
    assert result.qualification == "new_study_with_fresh_heldout_required"


@pytest.mark.parametrize("role", ["heldout", "unspecified"])
def test_feedback_requires_sealed_training_role_even_after_directory_rename(
    role: Any, training: NativeBenchmark, measured: tuple[BenchmarkRun, Path], tmp_path: Path,
) -> None:
    protected = replace(training, split_role=role)
    saved = protected.export(tmp_path / "training")
    loaded = NativeBenchmark.load(saved.directory)
    assert loaded.digest != training.digest and loaded.split_role == role
    # Even an altered summary that claims this other package cannot bypass role.
    report = measured[0].model_copy(update={"benchmark_digest": loaded.digest})
    with _rewritten_report(measured[1], report), pytest.raises(ValueError, match="split_role='training'"):
        _diagnose(loaded, measured[1])


@pytest.mark.parametrize("change, match", [
    ({"benchmark_digest": "a" * 64}, "sealed training benchmark"),
    ({"passed_count": 1}, "aggregate"),
    ({"trials": ()}, "cover the training benchmark"),
])
def test_feedback_rejects_stale_or_tampered_reports(
    change: dict[str, Any], match: str, training: NativeBenchmark, measured: tuple[BenchmarkRun, Path],
) -> None:
    with _rewritten_report(measured[1], measured[0].model_copy(update=change)), pytest.raises(ValueError, match=match):
        _diagnose(training, measured[1])


def test_trial_identity_cannot_be_replayed_from_another_execution(
    training: NativeBenchmark, measured: tuple[BenchmarkRun, Path],
) -> None:
    report = measured[0]
    wrong = report.trials[0].model_copy(update={"execution_id": "b" * 64})
    rewritten = report.model_copy(update={"trials": (wrong, *report.trials[1:])})
    with _rewritten_report(measured[1], rewritten), pytest.raises(ValueError, match="execution or operation identity"):
        _diagnose(training, measured[1])


def test_receipts_are_regraded_before_diagnosis(
    training: NativeBenchmark, measured: tuple[BenchmarkRun, Path],
) -> None:
    report, directory = measured
    trial = report.trials[0]
    path = directory / "receipts" / (digest([trial.task_id, trial.repeat]) + ".json")
    original = path.read_bytes()
    try:
        document = json.loads(original)
        document["trial"]["grade"]["metrics"]["assertions"] = 100000
        document["digest"] = digest({key: value for key, value in document.items() if key != "digest"})
        write_json(path, document)
        with pytest.raises(ValueError, match="independent byte grading"):
            load_training_run(training, directory)
    finally:
        path.write_bytes(original)


def test_consistently_forged_success_summary_cannot_enter_public_sdk(
    training: NativeBenchmark, measured: tuple[BenchmarkRun, Path],
) -> None:
    report, directory = measured
    forged_trials = tuple(trial.model_copy(update={"grade": NativeGrade(passed=True, findings=(),
        metrics={"assertions": 1})}) for trial in report.trials)
    forged = report.model_copy(update={"trials": forged_trials, "passed_count": report.total,
        "failed_count": 0, "passed": True})
    with pytest.raises(ValueError, match="never a bare report"):
        diagnose_benchmark(training, forged, namespace=training.world.company.id)  # type: ignore[arg-type]
    with _rewritten_report(directory, forged), pytest.raises(ValueError, match="independent byte grading"):
        _diagnose(training, directory)


@pytest.mark.parametrize("forge_demands", [False, True])
def test_rehashed_curriculum_strategy_and_demands_are_rederived_from_actual_training(
    forge_demands: bool, training: NativeBenchmark, measured: tuple[BenchmarkRun, Path],
) -> None:
    curriculum = _diagnose(training, measured[1])
    document = curriculum.model_dump(mode="json")
    document["scenario_demand"]["episodes"] = 1
    document["scenario_demand"]["processes"] = ["supplier_reconciliation"]
    document["next_plan"]["max_tasks"] = 3
    if forge_demands:
        document["demands"] = [item for item in document["demands"] if item["stage"] == "EVAL"]
        document["observations"] = [{**item, "failures": 0, "failure_codes": []} for item in document["observations"]]
    document["digest"] = digest({key: value for key, value in document.items() if key != "digest"})
    forged = NativeCurriculum.model_validate(document)
    with pytest.raises(ValueError, match="independently verified training feedback"):
        build_curriculum_training(training, measured[1], forged)


def test_independent_shortfalls_drive_actual_process_source_demands_and_ablation_receipts(
    training: NativeBenchmark, measured: tuple[BenchmarkRun, Path],
) -> None:
    requirements = BenchmarkRequirements(cells=(CoverageRequirement(name="supplier-evidence", operation="read",
        format="docx", dimensions=(CoverageDimension(name="scenario_process", value="supplier_reconciliation"),),
        min_independent_units=4),))
    result = _diagnose(training, measured[1], requirements=requirements)
    coverage = [item for item in result.demands if item.reason == "independent_unit_shortfall"]
    assert coverage and all(item.additional_units == 1 for item in coverage)
    assert result.scenario_demand.processes == ("supplier_reconciliation",)
    assert result.scenario_demand.episodes == 4
    budget = next(item for item in result.demands if item.stage == "EVAL" and item.capability == "supplier-evidence")
    assert budget.independent_units == 4
    no_failures = _diagnose(training, measured[1], requirements=requirements, ablation="without_failures")
    assert all(item.reason != "measured_failure" for item in no_failures.demands)
    no_coverage = _diagnose(training, measured[1], requirements=requirements, ablation="without_coverage")
    assert all(item.reason != "independent_unit_shortfall" for item in no_coverage.demands)
    assert len({result.digest, no_failures.digest, no_coverage.digest}) == 3
    assert len({result.scenario_demand.batch_id, no_failures.scenario_demand.batch_id,
        no_coverage.scenario_demand.batch_id}) == 3
    second = _diagnose(training, measured[1], version=2, parent_digest=result.digest)
    assert second.digest != result.digest and second.parent_digest == result.digest
    with pytest.raises(ValueError, match="parent receipt"):
        _diagnose(training, measured[1], version=2)
    altered = result.model_dump(mode="json")
    altered["scenario_demand"]["episodes"] += 1
    with pytest.raises(ValueError, match="checksum changed"):
        NativeCurriculum.model_validate(altered)
    missing_analysis = _diagnose(training, measured[1], requirements=BenchmarkRequirements(cells=(
        CoverageRequirement(name="ratio-between-sources", calculation="ratio", scope="cross_artifact"),)))
    assert "analyze" in missing_analysis.next_plan.operations
    assert missing_analysis.next_plan.discovery_scope == "mixed"


def test_next_training_benchmark_changes_real_source_and_task_identity(
    training: NativeBenchmark, measured: tuple[BenchmarkRun, Path], tmp_path: Path,
) -> None:
    curriculum = _diagnose(training, measured[1], ablation="without_failures")
    evolved = build_curriculum_training(training, measured[1], curriculum)
    assert evolved.benchmark.split_role == "training"
    assert evolved.benchmark.digest != training.digest
    assert evolved.benchmark.source_digest != training.source_digest
    assert {task.id for task in evolved.benchmark.workload.tasks}.isdisjoint(task.id for task in training.workload.tasks)
    assert evolved.assessment.execution_ready and evolved.assessment.coverage_complete
    assert len(evolved.world.facts) > len(training.world.facts)
    with pytest.raises(ValueError, match="sealed training benchmark"):
        build_curriculum_training(evolved.benchmark, measured[1], curriculum)
    harness = CallableHarness(lambda *_: NativeSubmission(), {"kind": "empty-reader-v1"})
    out = tmp_path / "loop"
    proposal = run_training_curriculum(training, harness, directory=out, namespace=curriculum.namespace)
    before = (out / "curriculum.json").read_bytes()
    assert run_training_curriculum(training, harness, directory=out, namespace=curriculum.namespace, resume=True) == proposal
    assert (out / "curriculum.json").read_bytes() == before
    with pytest.raises(ValueError, match="configuration changed"):
        run_training_curriculum(evolved.benchmark, harness, directory=out, namespace=curriculum.namespace, resume=True)


@pytest.mark.parametrize("change", [
    {"namespace": " "},
    {"version": 0},
    {"version": True},
    {"version": 2},
    {"parent_digest": "invalid"},
    {"ablation": "skip-everything"},
    {"qualification_policy": QualificationPolicy(unit_dimension="unavailable-dimension")},
    {"requirements": BenchmarkRequirements(cells=(CoverageRequirement(name="operation:read", operation="analyze"),))},
])
def test_invalid_static_curriculum_settings_fail_before_any_target_call(
    change: dict[str, Any], training: NativeBenchmark, tmp_path: Path,
) -> None:
    calls: list[str] = []

    def target(request: dict[str, Any], _: Any) -> NativeSubmission:
        calls.append(request["id"])
        return NativeSubmission()

    options = {"namespace": training.world.company.id, **change}
    directory = tmp_path / "invalid-settings"
    with pytest.raises(ValueError):
        run_training_curriculum(training, CallableHarness(target, {"kind": "must-not-run"}),
            directory=directory, **options)
    assert not calls and not directory.exists()


def test_changed_saved_settings_refuse_before_missing_trial_can_execute(
    training: NativeBenchmark, measured: tuple[BenchmarkRun, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import worldloom.benchmarks.curriculum as module

    report, directory = measured
    prior = _diagnose(training, directory)
    path = directory / "curriculum.json"
    write_json(path, prior.model_dump(mode="json"))
    calls: list[str] = []

    def run_must_not_execute(*_: Any, **__: Any) -> None:
        calls.append("runner")
        raise AssertionError("configuration drift must refuse before entering the target runner")

    monkeypatch.setattr(module, "run_benchmark", run_must_not_execute)
    try:
        with pytest.raises(ValueError, match="configuration changed"):
            run_training_curriculum(training, CallableHarness(lambda *_: NativeSubmission(), report.harness_identity),
                directory=directory, namespace=prior.namespace, resume=True, ablation="without_failures",
                qualification_policy=prior.qualification_policy)
        assert not calls
    finally:
        path.unlink()
