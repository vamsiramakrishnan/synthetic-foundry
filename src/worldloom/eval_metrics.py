"""Measured eval slices and empirical difficulty calibration.

Difficulty is not authored by a formula. Worldloom exposes stable structural
features, then estimates pass rate for a named agent cohort from observed runs.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from .eval_design import EvalSpec, RequirementKind
from .evals.difficulty import RequestFeatures
from .ids import content_key
from .models import Model


class EvalFeatures(Model):
    step_count: int = Field(ge=1)
    dag_depth: int = Field(ge=1)
    connector_count: int = Field(ge=0)
    write_steps: int = Field(ge=0)
    verify_steps: int = Field(ge=0)
    requirement_count: int = Field(ge=1)
    revision_depth: int = Field(ge=0)
    temporal_requirements: int = Field(ge=0)
    permission_requirements: int = Field(ge=0)
    distractor_requirements: int = Field(ge=0)

    def slice_key(self) -> str:
        """Stable coarse slice for calibration and adaptive mutation."""
        return (
            f"d{self.dag_depth}:c{self.connector_count}:w{self.write_steps}:"
            f"r{self.revision_depth}:t{self.temporal_requirements}:"
            f"p{self.permission_requirements}:x{self.distractor_requirements}"
        )


def features_for(spec: EvalSpec) -> EvalFeatures:
    depth: dict[str, int] = {}
    for step in spec.steps:
        depth[step.id] = 1 + max((depth[parent] for parent in step.depends_on), default=0)
    connectors = {step.connector for step in spec.steps if step.connector}
    connectors.update(
        str(requirement.selector["connector"])
        for requirement in spec.requirements
        if "connector" in requirement.selector
    )
    revisions = [
        requirement.minimum
        for requirement in spec.requirements
        if requirement.kind == RequirementKind.REVISION_CHAIN
    ]
    return EvalFeatures(
        step_count=len(spec.steps),
        dag_depth=max(depth.values()),
        connector_count=len(connectors),
        write_steps=sum(step.effect == "write" for step in spec.steps),
        verify_steps=sum(step.effect == "verify" for step in spec.steps),
        requirement_count=len(spec.requirements),
        revision_depth=max(revisions, default=0),
        temporal_requirements=sum(
            requirement.kind == RequirementKind.TEMPORAL_RELATION
            for requirement in spec.requirements
        ),
        permission_requirements=sum(
            requirement.kind == RequirementKind.PERMISSION
            for requirement in spec.requirements
        ),
        distractor_requirements=sum(
            requirement.kind == RequirementKind.DISTRACTOR
            for requirement in spec.requirements
        ),
    )


FeatureSchema = Literal["eval/v1", "request/v1"]
ObservationSplit = Literal["train", "validation", "holdout"]
EvaluatorKind = Literal["agent", "reader", "reference_executor"]
EstimateStatus = Literal["unfitted", "insufficient_data", "fitted", "unverified", "reference_only"]
_ESTIMATOR: Literal["laplace-wilson95/v1"] = "laplace-wilson95/v1"
_DIGEST = r"^(?:[0-9a-f]{32}|[0-9a-f]{64})$"


def _identity(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("identity must be nonempty with no surrounding whitespace")
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class FeatureSlice(Model):
    """Versioned structural measurements and explicit intervention conditions.

    Full values remain in the receipt. Only the declared coarse slice determines
    aggregation; a content address binds it to the original measurements.
    """

    feature_schema: FeatureSchema
    values: EvalFeatures | RequestFeatures
    conditions: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def _contract(self) -> FeatureSlice:
        expected = EvalFeatures if self.feature_schema == "eval/v1" else RequestFeatures
        if not isinstance(self.values, expected):
            raise ValueError("feature namespace does not match its structural values")
        if self.conditions != tuple(sorted(set(self.conditions))):
            raise ValueError("conditions must be unique and sorted")
        if len({key for key, _ in self.conditions}) != len(self.conditions):
            raise ValueError("condition names must be unique")
        for key, value in self.conditions:
            _identity(key)
            _identity(value)
        return self

    @property
    def slice_key(self) -> str:
        key = self.values.slice_key()
        return key if not self.conditions else f"{key}:conditions={content_key(_canonical(self.conditions))}"

    @property
    def feature_digest(self) -> str:
        return content_key("calibration-features/v1", _canonical(self.model_dump(mode="json")))


def feature_slice(
    value: EvalSpec | EvalFeatures | RequestFeatures,
    *, conditions: Mapping[str, str] | None = None,
) -> FeatureSlice:
    if isinstance(value, EvalSpec):
        value = features_for(EvalSpec.model_validate(value.model_dump(mode="json")))
    if not isinstance(value, (EvalFeatures, RequestFeatures)):
        raise TypeError("calibration requires EvalSpec, EvalFeatures, or RequestFeatures")
    # Revalidate even model_copy/model_construct inputs: an infinite density
    # must never reach a slice label and thereby look like a measured cohort.
    checked = type(value).model_validate(value.model_dump(mode="json"))
    return FeatureSlice(
        feature_schema="eval/v1" if isinstance(checked, EvalFeatures) else "request/v1",
        values=checked, conditions=tuple(sorted((conditions or {}).items())),
    )


class CalibrationObservation(Model):
    """One externally observed trial. Worldloom does not invent these outcomes."""

    cohort: str
    trial_id: str
    eval_id: str
    corpus_digest: str = Field(pattern=_DIGEST)
    evaluator_config_digest: str = Field(pattern=_DIGEST)
    evaluator_kind: EvaluatorKind
    features: FeatureSlice
    passed: StrictBool
    split: ObservationSplit

    _identities = field_validator("cohort", "trial_id", "eval_id")(_identity)


class DifficultyEstimate(Model):
    cohort: str
    split: ObservationSplit = "train"
    feature_schema: FeatureSchema
    slice_key: str
    trials: int = Field(ge=0)
    successes: int = Field(ge=0)
    predicted_pass_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    interval_low: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    interval_high: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    confidence_level: float = Field(default=0.95, ge=0.95, le=0.95, allow_inf_nan=False)
    estimator_version: Literal["laplace-wilson95/v1"] = _ESTIMATOR
    min_trials: int = Field(ge=1)
    status: EstimateStatus
    provenance_complete: bool
    evaluator_kind: EvaluatorKind | None = None
    evaluator_config_digest: str | None = None

    @property
    def difficulty(self) -> float:
        return 1.0 - self.predicted_pass_rate

    @property
    def fitted(self) -> bool:
        return self.status == "fitted" and self.provenance_complete


class CalibrationBin(Model):
    lower: float
    upper: float
    count: int = Field(ge=1)
    predicted_mean: float
    observed_pass_rate: float


class CalibrationReport(Model):
    cohort: str
    split: Literal["validation", "holdout"]
    snapshot_digest: str
    estimator_version: Literal["laplace-wilson95/v1"] = _ESTIMATOR
    min_trials: int = Field(ge=1)
    observations: int = Field(ge=0)
    scored: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    brier_score: float | None = None
    expected_calibration_error: float | None = None
    bins: tuple[CalibrationBin, ...] = ()
    unsupported_trial_ids: tuple[str, ...] = ()


class LegacyCounts(Model):
    cohort: str
    features: FeatureSlice
    trials: int = Field(ge=1)
    successes: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts(self) -> LegacyCounts:
        _identity(self.cohort)
        if self.successes > self.trials:
            raise ValueError("successes cannot exceed trials")
        return self


class CalibrationSnapshot(Model):
    schema_version: Literal["worldloom.difficulty-calibration/v1"] = "worldloom.difficulty-calibration/v1"
    estimator_version: Literal["laplace-wilson95/v1"] = _ESTIMATOR
    observations: tuple[CalibrationObservation, ...] = ()
    legacy_counts: tuple[LegacyCounts, ...] = ()
    digest: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _digest(self) -> CalibrationSnapshot:
        payload = self.model_dump(mode="json", exclude={"digest"})
        if self.digest != content_key("calibration-snapshot/v1", _canonical(payload)):
            raise ValueError("calibration snapshot digest mismatch")
        return self


def _wilson(successes: int, trials: int) -> tuple[float, float]:
    if not trials:
        return 0.0, 1.0
    # Pinned normal quantile avoids dependency/version changes in replay. This
    # is a binomial interval, not a claim of independent corpus distributions.
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    radius = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


class CalibrationLedger:
    """Deterministic observation accounting behind the public calibrator."""

    def __init__(self) -> None:
        self.observations: dict[tuple[str, str], CalibrationObservation] = {}
        self.legacy: dict[tuple[str, str, str], LegacyCounts] = {}
        self.cohorts: dict[str, tuple[EvaluatorKind, str]] = {}
        self.counts: dict[tuple[str, str, str, str], tuple[int, int]] = {}
        self.legacy_cohorts: set[str] = set()
        self.groups: dict[tuple[str, str, str], str] = {}

    @staticmethod
    def _key(cohort: str, features: FeatureSlice) -> tuple[str, str, str]:
        return cohort, features.feature_schema, features.slice_key

    def observe_legacy(self, cohort: str, features: FeatureSlice, *, passed: bool) -> None:
        _identity(cohort)
        if type(passed) is not bool:
            raise ValueError("passed must be a boolean")
        if cohort in self.cohorts:
            raise ValueError("identified cohort cannot accept unverified legacy observations")
        key = self._key(cohort, features)
        previous = self.legacy.get(key)
        self.legacy[key] = LegacyCounts(
            cohort=cohort, features=min((features, previous.features), key=lambda item: item.feature_digest) if previous else features,
            trials=1 + (previous.trials if previous else 0),
            successes=int(passed) + (previous.successes if previous else 0),
        )
        self.legacy_cohorts.add(cohort)

    def ingest(self, observation: CalibrationObservation) -> bool:
        observation = CalibrationObservation.model_validate(observation.model_dump(mode="json"))
        key = (observation.cohort, observation.trial_id)
        if key in self.observations:
            if self.observations[key] != observation:
                raise ValueError(f"conflicting trial replay: {observation.cohort}/{observation.trial_id}")
            return False
        if observation.cohort in self.legacy_cohorts:
            raise ValueError("legacy cohort cannot mix with provenance-bearing observations")
        identity = (observation.evaluator_kind, observation.evaluator_config_digest)
        if self.cohorts.get(observation.cohort, identity) != identity:
            raise ValueError("cohort evaluator kind/configuration changed; use a distinct cohort")
        group = (observation.cohort, observation.eval_id, observation.corpus_digest)
        if self.groups.get(group, observation.split) != observation.split:
            raise ValueError("eval/corpus group overlaps train, validation, or holdout splits")
        self.observations[key] = observation
        self.cohorts[observation.cohort] = identity
        self.groups[group] = observation.split
        if observation.evaluator_kind != "reference_executor":
            slice_key = (*self._key(observation.cohort, observation.features), observation.split)
            trials, successes = self.counts.get(slice_key, (0, 0))
            self.counts[slice_key] = (trials + 1, successes + int(observation.passed))
        return True

    def estimate(
        self, cohort: str, features: FeatureSlice, *, min_trials: int,
        split: ObservationSplit = "train",
    ) -> DifficultyEstimate:
        _identity(cohort)
        if type(min_trials) is not int or min_trials < 1:
            raise ValueError("min_trials must be a positive integer")
        if split not in {"train", "validation", "holdout"}:
            raise ValueError("unknown calibration split")
        features = FeatureSlice.model_validate(features.model_dump(mode="json"))
        key = self._key(cohort, features)
        identity = self.cohorts.get(cohort)
        legacy = self.legacy.get(key) if split == "train" else None
        trials, successes = (legacy.trials, legacy.successes) if legacy else self.counts.get((*key, split), (0, 0))
        complete = identity is not None and identity[0] != "reference_executor" and legacy is None
        status: EstimateStatus = "fitted" if trials >= min_trials else ("insufficient_data" if trials else "unfitted")
        if legacy:
            status = "unverified"
        if identity and identity[0] == "reference_executor":
            status = "reference_only"
        low, high = _wilson(successes, trials)
        return DifficultyEstimate(
            cohort=cohort, split=split, feature_schema=features.feature_schema, slice_key=features.slice_key,
            trials=trials, successes=successes, predicted_pass_rate=(successes + 1) / (trials + 2),
            interval_low=low, interval_high=high, min_trials=min_trials,
            status=status, provenance_complete=complete,
            evaluator_kind=identity[0] if identity else None,
            evaluator_config_digest=identity[1] if identity else None,
        )

    def report(self, cohort: str, *, split: str, bins: int, min_trials: int) -> CalibrationReport:
        _identity(cohort)
        if split not in {"validation", "holdout"}:
            raise ValueError("calibration reporting requires validation or holdout split")
        if type(bins) is not int or not 1 <= bins <= 100:
            raise ValueError("bins must be an integer between 1 and 100")
        if type(min_trials) is not int or min_trials < 1:
            raise ValueError("min_trials must be a positive integer")
        rows = tuple(row for _, row in sorted(self.observations.items()) if row.cohort == cohort and row.split == split)
        scored: list[tuple[float, int]] = []
        unsupported: list[str] = []
        for row in rows:
            estimate = self.estimate(cohort, row.features, min_trials=min_trials)
            if not estimate.fitted:
                unsupported.append(row.trial_id)
            else:
                scored.append((estimate.predicted_pass_rate, int(row.passed)))
        bucketed: dict[int, list[tuple[float, int]]] = {}
        for probability, passed in scored:
            bucketed.setdefault(min(bins - 1, int(probability * bins)), []).append((probability, passed))
        summaries = tuple(
            CalibrationBin(
                lower=index / bins, upper=(index + 1) / bins, count=len(values),
                predicted_mean=sum(p for p, _ in values) / len(values),
                observed_pass_rate=sum(y for _, y in values) / len(values),
            ) for index, values in sorted(bucketed.items())
        )
        return CalibrationReport(
            cohort=cohort, split="holdout" if split == "holdout" else "validation", snapshot_digest=self.snapshot().digest, min_trials=min_trials,
            observations=len(rows), scored=len(scored), unsupported=len(unsupported),
            brier_score=sum((p - y) ** 2 for p, y in scored) / len(scored) if scored else None,
            expected_calibration_error=(sum(bucket.count * abs(bucket.predicted_mean - bucket.observed_pass_rate) for bucket in summaries) / len(scored) if scored else None),
            bins=summaries, unsupported_trial_ids=tuple(unsupported),
        )

    def snapshot(self) -> CalibrationSnapshot:
        payload = {
            "schema_version": "worldloom.difficulty-calibration/v1",
            "estimator_version": _ESTIMATOR,
            "observations": [row.model_dump(mode="json") for _, row in sorted(self.observations.items())],
            "legacy_counts": [row.model_dump(mode="json") for _, row in sorted(self.legacy.items())],
        }
        return CalibrationSnapshot.model_validate({**payload, "digest": content_key("calibration-snapshot/v1", _canonical(payload))})

    @classmethod
    def from_snapshot(cls, snapshot: CalibrationSnapshot) -> CalibrationLedger:
        snapshot = CalibrationSnapshot.model_validate(snapshot.model_dump(mode="json"))
        ledger = cls()
        for row in snapshot.observations:
            if not ledger.ingest(row):
                raise ValueError("duplicate trial in calibration snapshot")
        for legacy_row in snapshot.legacy_counts:
            key = ledger._key(legacy_row.cohort, legacy_row.features)
            if key in ledger.legacy or legacy_row.cohort in ledger.cohorts:
                raise ValueError("duplicate or mixed legacy cohort in calibration snapshot")
            ledger.legacy[key] = legacy_row
            ledger.legacy_cohorts.add(legacy_row.cohort)
        if ledger.snapshot() != snapshot:
            raise ValueError("calibration snapshot is not in canonical observation order")
        return ledger


class DifficultyCalibrator:
    """Empirical cohort calibration with replay-safe observations.

    ``ingest`` is the supported provenance-bearing seam. Historical ``observe``
    remains a count-only compatibility API; those counts are explicitly
    unverified and cannot establish fitted calibration for a controller.
    """

    def __init__(self) -> None:
        self._ledger = CalibrationLedger()

    def observe(
        self, cohort: str, spec: EvalSpec | EvalFeatures | RequestFeatures,
        *, passed: bool,
    ) -> None:
        """Legacy count-only input. Use ``ingest`` for identifiable real trials."""
        self._ledger.observe_legacy(cohort, feature_slice(spec), passed=passed)

    def ingest(self, observation: CalibrationObservation) -> bool:
        """Add one observed trial; exact replay is a no-op, conflicting replay refuses."""
        return self._ledger.ingest(observation)

    def estimate(
        self, cohort: str, spec: EvalSpec | EvalFeatures | RequestFeatures | FeatureSlice,
        *, min_trials: int = 20, split: ObservationSplit = "train",
    ) -> DifficultyEstimate:
        """Estimate a declared split; only train estimates are fitting evidence.

        Held-out estimates describe outcomes after policy freeze. They never
        update the train model or the predictions used by ``report``.
        """
        features = spec if isinstance(spec, FeatureSlice) else feature_slice(spec)
        return self._ledger.estimate(cohort, features, min_trials=min_trials, split=split)

    def report(
        self, cohort: str, *, split: str = "holdout", bins: int = 10,
        min_trials: int = 20,
    ) -> CalibrationReport:
        """Score held-out observations against training-only estimates."""
        return self._ledger.report(cohort, split=split, bins=bins, min_trials=min_trials)

    def snapshot(self) -> CalibrationSnapshot:
        return self._ledger.snapshot()

    def export(self, path: str | Path) -> Path:
        from .corpus import write_json

        destination = Path(path)
        write_json(destination, self.snapshot().model_dump(mode="json"))
        return destination

    @classmethod
    def from_snapshot(cls, snapshot: CalibrationSnapshot) -> DifficultyCalibrator:
        result = cls()
        result._ledger = CalibrationLedger.from_snapshot(snapshot)
        return result

    @classmethod
    def load(cls, path: str | Path) -> DifficultyCalibrator:
        return cls.from_snapshot(CalibrationSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8")))


__all__ = [
    "DifficultyCalibrator", "DifficultyEstimate", "EvalFeatures", "features_for",
    "FeatureSlice", "feature_slice", "CalibrationObservation", "CalibrationSnapshot",
    "CalibrationReport", "CalibrationBin",
]
