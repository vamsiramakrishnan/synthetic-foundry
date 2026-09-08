"""Empirical observations must survive replay without manufacturing support."""

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from worldloom.eval_metrics import (
    CalibrationObservation,
    CalibrationSnapshot,
    DifficultyCalibrator,
    EvalFeatures,
    FeatureSlice,
    feature_slice,
)
from worldloom.evals.difficulty import RequestFeatures
from worldloom.ids import content_key


def _features(**changes: object) -> FeatureSlice:
    fields = dict(evidence_kinds=1, facts_required=2, artifacts_required=1,
                  distractor_density=0.0, unstated_slots=0)
    fields.update(changes)
    return feature_slice(RequestFeatures(**fields))


def _row(index: int, **changes: object) -> CalibrationObservation:
    fields = dict(
        cohort="agent-a", trial_id=f"trial-{index:04d}", eval_id=f"eval-{index:04d}",
        corpus_digest=content_key("corpus", index),
        evaluator_config_digest=content_key("agent", "model", "prompt", "tools"),
        evaluator_kind="agent", features=_features(), passed=index % 2 == 0,
        split="train",
    )
    fields.update(changes)
    return CalibrationObservation(**fields)


def _trained(count: int = 40) -> DifficultyCalibrator:
    result = DifficultyCalibrator()
    for index in range(count):
        result.ingest(_row(index))
    return result


def test_request_features_are_consumed_and_unfitted_is_explicit() -> None:
    calibrator = DifficultyCalibrator()
    empty = calibrator.estimate("agent-a", _features().values)
    assert empty.status == "unfitted" and not empty.fitted
    assert empty.trials == 0 and empty.predicted_pass_rate == 0.5
    assert (empty.interval_low, empty.interval_high) == (0.0, 1.0)
    calibrator.ingest(_row(0))
    estimate = calibrator.estimate("agent-a", _features())
    assert estimate.feature_schema == "request/v1"
    assert estimate.status == "insufficient_data" and not estimate.fitted
    assert estimate.provenance_complete and estimate.successes == 1
    assert estimate.interval_low == pytest.approx(0.20654931437723745)
    assert estimate.interval_high == 1.0


def test_interventions_condition_counts_without_changing_default_slice() -> None:
    values = _features().values
    pristine = feature_slice(values, conditions={"noise": "pristine", "period": "2026-03"})
    lived = feature_slice(values, conditions={"period": "2026-03", "noise": "lived_in"})
    reordered = feature_slice(values, conditions={"period": "2026-03", "noise": "pristine"})
    assert pristine == reordered
    assert pristine.slice_key != lived.slice_key
    assert feature_slice(values).slice_key == values.slice_key()
    calibrator = DifficultyCalibrator()
    for index in range(40):
        calibrator.ingest(_row(index, features=pristine, passed=True))
        calibrator.ingest(_row(index + 40, features=lived, passed=False))
    a = calibrator.estimate("agent-a", pristine)
    b = calibrator.estimate("agent-a", lived)
    assert a.fitted and b.fitted
    assert a.interval_low > b.interval_high
    assert calibrator.estimate("agent-a", values).status == "unfitted"


def test_feature_namespaces_and_full_measurements_are_bound() -> None:
    ev = EvalFeatures(step_count=1, dag_depth=1, connector_count=0, write_steps=0,
                      verify_steps=0, requirement_count=1, revision_depth=0,
                      temporal_requirements=0, permission_requirements=0,
                      distractor_requirements=0)
    plan = feature_slice(ev)
    request = _features()
    assert plan.feature_schema == "eval/v1"
    with pytest.raises(ValidationError, match="namespace"):
        FeatureSlice(feature_schema="eval/v1", values=request.values)
    more = _features(facts_required=7)
    many = _features(facts_required=9)
    assert more.slice_key == many.slice_key
    assert more.feature_digest != many.feature_digest
    calibrator = DifficultyCalibrator()
    calibrator.ingest(_row(0, features=plan))
    assert calibrator.estimate("agent-a", request).trials == 0


def test_exact_replay_is_idempotent_and_conflicts_leave_ledger_unchanged() -> None:
    calibrator = DifficultyCalibrator()
    row = _row(0)
    assert calibrator.ingest(row)
    snapshot = calibrator.snapshot()
    assert not calibrator.ingest(row)
    for altered in (row.model_copy(update={"passed": False}),
                    row.model_copy(update={"features": _features(facts_required=3)}),
                    row.model_copy(update={"split": "holdout"})):
        with pytest.raises(ValueError, match="conflicting trial replay"):
            calibrator.ingest(altered)
    assert calibrator.snapshot() == snapshot


@pytest.mark.parametrize("change", [
    {"evaluator_config_digest": content_key("another-model")},
    {"evaluator_kind": "reader"},
])
def test_cohort_configuration_cannot_drift(change: dict[str, object]) -> None:
    calibrator = _trained(1)
    with pytest.raises(ValueError, match="cohort evaluator"):
        calibrator.ingest(_row(1, **change))
    assert len(calibrator.snapshot().observations) == 1


@pytest.mark.parametrize("split", ["validation", "holdout"])
def test_eval_corpus_group_cannot_leak_across_splits(split: str) -> None:
    calibrator = _trained(1)
    with pytest.raises(ValueError, match="overlaps"):
        calibrator.ingest(_row(1, eval_id="eval-0000", corpus_digest=content_key("corpus", 0), split=split))


def test_holdout_and_validation_never_train_or_change_predictions() -> None:
    calibrator = _trained()
    before = calibrator.estimate("agent-a", _features())
    for index in range(40, 80):
        calibrator.ingest(_row(index, split="holdout", passed=True))
        calibrator.ingest(_row(index + 40, split="validation", passed=False))
    assert calibrator.estimate("agent-a", _features()) == before
    assert before.fitted and before.trials == 40 and before.successes == 20
    report = calibrator.report("agent-a")
    assert report.observations == report.scored == 40
    assert report.unsupported == 0
    assert report.brier_score == 0.25
    assert report.expected_calibration_error == 0.5
    assert sum(bucket.count for bucket in report.bins) == report.scored


def test_heldout_report_preserves_unsupported_denominators() -> None:
    calibrator = _trained()
    calibrator.ingest(_row(100, split="holdout"))
    calibrator.ingest(_row(101, split="holdout", features=_features(temporal=True)))
    report = calibrator.report("agent-a")
    assert (report.observations, report.scored, report.unsupported) == (2, 1, 1)
    assert report.unsupported_trial_ids == ("trial-0101",)
    unsupported = calibrator.report("agent-a", min_trials=100)
    assert unsupported.scored == 0
    assert unsupported.brier_score is None
    assert unsupported.expected_calibration_error is None


def test_reference_execution_cannot_calibrate_agent_or_reader_difficulty() -> None:
    calibrator = DifficultyCalibrator()
    for index in range(50):
        calibrator.ingest(_row(index, evaluator_kind="reference_executor", passed=True))
    calibrator.ingest(_row(100, evaluator_kind="reference_executor", passed=True, split="holdout"))
    estimate = calibrator.estimate("agent-a", _features())
    assert estimate.status == "reference_only"
    assert estimate.trials == 0 and not estimate.fitted and not estimate.provenance_complete
    assert calibrator.report("agent-a").unsupported == 1


def test_legacy_observations_remain_compatible_but_unverified() -> None:
    calibrator = DifficultyCalibrator()
    for index in range(40):
        calibrator.observe("agent-a", _features().values, passed=index % 2 == 0)
    estimate = calibrator.estimate("agent-a", _features())
    assert estimate.predicted_pass_rate == 0.5 and estimate.trials == 40
    assert estimate.status == "unverified" and not estimate.fitted
    with pytest.raises(ValueError, match="legacy cohort"):
        calibrator.ingest(_row(100))
    restored = DifficultyCalibrator.from_snapshot(calibrator.snapshot())
    assert restored.estimate("agent-a", _features()) == estimate
    with pytest.raises(ValueError, match="identified cohort"):
        _trained(1).observe("agent-a", _features().values, passed=True)


def test_export_is_identical_across_ingestion_order_and_load(tmp_path: Path) -> None:
    rows = [_row(index, split="holdout" if index >= 40 else "train") for index in range(50)]
    a = DifficultyCalibrator()
    b = DifficultyCalibrator()
    for row in rows:
        a.ingest(row)
    for row in reversed(rows):
        b.ingest(row)
    first = a.export(tmp_path / "a.json")
    second = b.export(tmp_path / "b.json")
    assert first.read_bytes() == second.read_bytes()
    loaded = DifficultyCalibrator.load(first)
    assert loaded.snapshot() == a.snapshot()
    assert loaded.report("agent-a") == a.report("agent-a")
    assert not loaded.ingest(rows[0])
    altered = json.loads(first.read_text())
    altered["observations"][0]["passed"] = False
    first.write_text(json.dumps(altered))
    with pytest.raises(ValidationError, match="digest mismatch"):
        DifficultyCalibrator.load(first)


def test_resigned_snapshot_still_checks_duplicate_and_split_invariants() -> None:
    snapshot = _trained(1).snapshot().model_dump(mode="json", exclude={"digest"})
    snapshot["observations"].append(snapshot["observations"][0])
    digest = content_key("calibration-snapshot/v1", json.dumps(snapshot, sort_keys=True, separators=(",", ":")))
    signed = CalibrationSnapshot.model_validate({**snapshot, "digest": digest})
    with pytest.raises(ValueError, match="duplicate trial"):
        DifficultyCalibrator.from_snapshot(signed)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_features_are_rejected_including_unchecked_models(value: float) -> None:
    with pytest.raises(ValidationError):
        _features(distractor_density=value)
    unsafe = _features().values.model_copy(update={"distractor_density": value})
    with pytest.raises(ValidationError):
        feature_slice(unsafe)


@pytest.mark.parametrize("changes", [
    {"passed": 1}, {"passed": "true"}, {"cohort": " "},
    {"trial_id": " trial"}, {"corpus_digest": "missing"},
    {"split": "test"}, {"evaluator_config_digest": ""},
])
def test_invalid_observations_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _row(0, **changes)


def test_revalidates_unchecked_observation_and_query_arguments() -> None:
    calibrator = DifficultyCalibrator()
    with pytest.warns(UserWarning, match="serializer warnings"), pytest.raises(ValidationError):
        calibrator.ingest(_row(0).model_copy(update={"passed": "false"}))
    for support in (0, True, -1):
        with pytest.raises(ValueError, match="min_trials"):
            calibrator.estimate("agent-a", _features(), min_trials=support)
    for split in ("train", "test"):
        with pytest.raises(ValueError, match="split"):
            calibrator.report("agent-a", split=split)
    for bins in (0, 101, True):
        with pytest.raises(ValueError, match="bins"):
            calibrator.report("agent-a", bins=bins)
    assert calibrator.snapshot().observations == ()


def test_wilson_intervals_are_finite_and_contract_with_support() -> None:
    small = _trained(20).estimate("agent-a", _features())
    large = _trained(200).estimate("agent-a", _features())
    assert small.interval_low < large.interval_low < 0.5
    assert 0.5 < large.interval_high < small.interval_high
    assert all(math.isfinite(value) for value in (small.interval_low, small.interval_high, large.interval_low, large.interval_high))


def test_holdout_interval_is_descriptive_and_cannot_update_training() -> None:
    calibrator = _trained()
    before = calibrator.estimate("agent-a", _features())
    for index in range(40, 80):
        calibrator.ingest(_row(index, split="holdout", passed=True))
    heldout = calibrator.estimate("agent-a", _features(), split="holdout")
    assert heldout.split == "holdout" and heldout.trials == heldout.successes == 40
    assert heldout.interval_low > 0.9
    assert calibrator.estimate("agent-a", _features()) == before
    assert calibrator.report("agent-a").brier_score == 0.25
    with pytest.raises(ValueError, match="split"):
        calibrator.estimate("agent-a", _features(), split="test")
