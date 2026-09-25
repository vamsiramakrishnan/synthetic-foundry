"""Finite noise calibration over existing campaign worlds and observed cohorts.

Messiness owns interventions; CampaignRun owns validation/oracle rebinding;
DifficultyCalibrator owns empirical estimates; Archive owns niche selection.
This adapter only schedules their finite composition and records every attempt.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from .. import packkit
from ..archive import Archive, Axis
from ..corpus import write_json
from ..eval_candidates import GeneratedCandidate
from ..eval_instances import EvalInstance
from ..eval_metrics import (
    CalibrationObservation,
    DifficultyCalibrator,
    DifficultyEstimate,
    feature_slice,
)
from ..messiness import Messiness, apply
from ..models import GenerationLedgerEntry, Model
from ..providers import digest
from .campaign import CampaignRun

if TYPE_CHECKING:
    from ..fidelity import FidelityReport
    from ..narrative.reader_checks import ReaderAcceptance
    from ..world import World


class NoiseVariant(Model):
    name: str = Field(min_length=1)
    budget: dict[str, StrictInt]
    niche: str = Field(min_length=1)

    @model_validator(mode="after")
    def _budget(self) -> NoiseVariant:
        if any(type(value) is not int or value < 0 or value > 1000 for value in self.budget.values()):
            raise ValueError("noise budgets must be integer counts in [0, 1000]")
        try:
            Messiness(self.budget)
        except KeyError as error:
            raise ValueError(str(error)) from error
        return self


class MetricThreshold(Model):
    path: tuple[str, ...] = Field(min_length=1)
    maximum: float = Field(allow_inf_nan=False)


class NoiseCalibrationPlan(Model):
    variants: tuple[NoiseVariant, ...] = Field(min_length=1, max_length=32)
    niches: tuple[str, ...] = Field(min_length=2, max_length=32)
    cohort: str = Field(min_length=1)
    evaluator_config: dict[str, Any]
    evaluator_kind: Literal["agent", "reader"] = "agent"
    target_low: float = Field(default=0.3, ge=0, le=1)
    target_high: float = Field(default=0.7, ge=0, le=1)
    min_support: int = Field(default=20, ge=1, le=4096)
    max_training_attempts: int = Field(default=128, ge=1, le=4096)
    max_holdout_attempts: int = Field(default=64, ge=1, le=4096)
    holdout_ordinals: tuple[int, ...] = Field(min_length=1)
    reader_id: str | None = None
    reader_config: dict[str, Any] = Field(default_factory=dict)
    fidelity_config: dict[str, Any] = Field(default_factory=dict)
    fidelity_slices: tuple[str, ...] = ()
    fidelity_thresholds: tuple[MetricThreshold, ...] = ()
    formats: tuple[str, ...] = ()
    noise_author: Literal["worldloom-noise-template/v1"] = "worldloom-noise-template/v1"

    @model_validator(mode="after")
    def _contract(self) -> NoiseCalibrationPlan:
        if self.target_low >= self.target_high:
            raise ValueError("target_low must be less than target_high")
        if len(set(self.niches)) != len(self.niches):
            raise ValueError("niches must be distinct")
        if len({v.name for v in self.variants}) != len(self.variants):
            raise ValueError("variant names must be distinct")
        if any(v.niche not in self.niches for v in self.variants):
            raise ValueError("every variant must occupy a declared niche")
        if len(set(self.holdout_ordinals)) != len(self.holdout_ordinals):
            raise ValueError("holdout ordinals must be distinct")
        if bool(self.fidelity_slices) != bool(self.fidelity_thresholds):
            raise ValueError("fidelity requires both slices and metric thresholds")
        if self.fidelity_slices and not self.fidelity_config:
            raise ValueError("fidelity requires sealed reference and projection configuration")
        if not self.evaluator_config or self.reader_id == "":
            raise ValueError("evaluator configuration and declared reader identity must be nonempty")
        json.dumps(self.model_dump(mode="json"), allow_nan=False)
        return self


class TrialOutcome(Model):
    passed: StrictBool
    details: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class TrialRequest:
    """Trusted grading adapter input; the oracle must not be sent to an agent."""
    world: World
    instance: EvalInstance
    variant: NoiseVariant
    trial_id: str
    split: Literal["train", "holdout"]


class CalibrationAttempt(Model):
    variant: str
    ordinal: int
    split: Literal["train", "holdout"]
    corpus_digest: str
    findings: tuple[str, ...] = ()
    actual_noise: dict[str, int] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    ledger: tuple[GenerationLedgerEntry, ...] = ()
    observation: CalibrationObservation | None = None
    outcome: TrialOutcome | None = None
    receipt_digest: str

    @model_validator(mode="after")
    def _receipt(self) -> CalibrationAttempt:
        body = self.model_dump(mode="json", exclude={"receipt_digest"})
        if digest(body) != self.receipt_digest:
            raise ValueError("noise calibration receipt digest mismatch")
        if bool(self.observation) != bool(self.outcome):
            raise ValueError("observation and outcome must be recorded together")
        if self.observation and (self.findings or self.observation.passed != self.outcome.passed):  # type: ignore[union-attr]
            raise ValueError("refused or conflicting outcome cannot train")
        return self


class NoiseCalibrationRecord(Model):
    schema_version: Literal["worldloom.noise-calibration/v1"] = "worldloom.noise-calibration/v1"
    plan: NoiseCalibrationPlan
    plan_digest: str
    baseline_digest: str
    attempts: tuple[CalibrationAttempt, ...] = ()

    @model_validator(mode="after")
    def _sealed(self) -> NoiseCalibrationRecord:
        if digest(self.plan.model_dump(mode="json")) != self.plan_digest:
            raise ValueError("noise calibration plan digest mismatch")
        keys = [(a.variant, a.ordinal, a.split) for a in self.attempts]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate noise calibration attempt")
        return self

    def export(self, path: str | Path) -> Path:
        destination = Path(path)
        write_json(destination, self.model_dump(mode="json"))
        return destination

    @classmethod
    def load(cls, path: str | Path) -> NoiseCalibrationRecord:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


class VariantCalibration(Model):
    variant: str
    estimate: DifficultyEstimate
    target_supported: bool
    holdout_estimate: DifficultyEstimate | None = None
    holdout_status: str = "not_selected"


class NoiseCalibrationReport(Model):
    status: Literal["selected", "unfitted", "target_unmet"]
    training_attempts: int
    holdout_attempts: int
    training_exhausted: bool
    training_budget_exhausted: bool
    holdout_budget_exhausted: bool
    selected_variants: tuple[str, ...]
    holes: tuple[str, ...]
    variants: tuple[VariantCalibration, ...]
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class NoiseCalibrationRun:
    plan: NoiseCalibrationPlan
    record: NoiseCalibrationRecord
    report: NoiseCalibrationReport
    campaigns: tuple[tuple[str, CampaignRun], ...]

    def export(self, out: str | Path) -> Path:
        """Export exact admitted worlds. Rendering after calibration is a new trial."""
        root = Path(out)
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(f"noise calibration destination is not empty: {root}")
        # Nested pydantic mappings can be mutated despite frozen models.
        checked = NoiseCalibrationRecord.model_validate(self.record.model_dump(mode="json"))
        expected = {(a.variant, a.ordinal): a.corpus_digest for a in checked.attempts if not a.findings}
        for name, run in self.campaigns:
            for candidate in run.selected:
                if world_digest(candidate.world) != expected[(name, candidate.plan.ordinal)]:
                    raise ValueError("calibrated world changed before export")
        root.mkdir(parents=True, exist_ok=True)
        self.record.export(root / "calibration-record.json")
        write_json(root / "calibration-report.json", self.report.model_dump(mode="json"))
        for index, (name, run) in enumerate(self.campaigns):
            run.export(root / "variants" / f"{index:03d}-{digest(name)}")
        write_json(root / "manifest.json", {
            "schema": "worldloom.noise-calibration/v1", "plan_digest": checked.plan_digest,
            "record_digest": digest(checked.model_dump(mode="json")),
            "selected_variants": list(self.report.selected_variants),
        })
        return root


def world_digest(world: World) -> str:
    """Bind every persisted table and native byte, independent of source paths."""
    with TemporaryDirectory(prefix="worldloom-calibration-") as temporary:
        root = world.export(Path(temporary) / "corpus")
        files = [(path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
                 for path in sorted(root.rglob("*")) if path.is_file()]
    return digest(files)


def _render_formats(world: World, requested: tuple[str, ...]) -> tuple[str, ...]:
    if requested:
        return requested
    if not world._rendered:
        if any(artifact.path for artifact in world.artifacts):
            raise ValueError("calibration needs explicit formats for persisted native files")
        return ()
    found: list[str] = []
    suffixes = {".md": "markdown", ".html": "html", ".docx": "docx", ".pdf": "pdf",
                ".pptx": "pptx", ".xlsx": "xlsx"}
    for item in world._rendered:
        path = Path(item.path)
        if path.name.endswith(".citations.md"):
            continue
        name = path.parts[0] if path.parts[0] in {"jira", "servicenow", "confluence"} else suffixes.get(path.suffix)
        if name is None:
            raise ValueError("calibration cannot infer native renderer; supply explicit formats")
        if name not in found:
            found.append(name)
    # A union of suffixes is not proof of a uniform render policy. Check it
    # against the actual baseline before applying that policy to new artifacts.
    replayed = world.render(*found)
    if {r.path: r.payload for r in replayed._rendered} != {r.path: r.payload for r in world._rendered}:
        raise ValueError("heterogeneous native rendering requires explicit calibration formats")
    return tuple(found)


def _noise_world(world: World, variant: NoiseVariant, formats: tuple[str, ...], *,
                 replay_ledger: tuple[GenerationLedgerEntry, ...] | None = None) -> World:
    from .. import documents
    from ..ids import Minter
    from ..narrative import compiler, handshake
    from ..narrative.providers import DeterministicProvider, UnreachableProvider

    rendered_formats = _render_formats(world, formats)
    # A frozen World still carries a mutable sequential minter. Interventions
    # branch from the same state; consuming its IDs would poison the next arm.
    minter = deepcopy(world._minter) if world._minter is not None else Minter()
    changed = apply(replace(world, _minter=minter), Messiness(variant.budget))
    existing = {ir.id for ir in world.artifact_irs}
    added = tuple(documents.compile_intent(changed, intent, minter) for intent in changed.artifact_intents
                  if intent.id not in existing)
    if handshake.pending(world):
        raise ValueError("finish baseline narration before calibrating noise")
    manifested = {artifact.id for artifact in world.artifacts}
    manifest = tuple(entry for entry in changed._manifest_for(added) if entry.id not in manifested)
    changed = replace(changed, _artifacts=tuple(world.artifacts) + manifest)
    ledger = {entry.key: entry for entry in changed.ledger}
    if added:
        # Reuse the existing validated template provider only for the new IRs.
        # Its identity is deliberately different from every original author;
        # replay preserves that attribution instead of laundering generated text.
        author = DeterministicProvider()
        author.id = "worldloom-noise-template/v1"
        available = dict(ledger)
        if replay_ledger is not None:
            available.update({entry.key: entry for entry in replay_ledger if entry.model_id == author.id})
        tail = compiler.narrate(replace(changed, _artifact_irs=added),
            UnreachableProvider(id=author.id) if replay_ledger is not None else author, ledger=tuple(available.values()))
        added = tail.irs
        ledger.update({entry.key: entry for entry in tail.ledger})
    changed = replace(changed, _artifact_irs=tuple(world.artifact_irs) + added, _ledger=tuple(ledger.values()),
                      _artifacts=tuple(world.artifacts) + manifest, _rendered=world._rendered)
    return changed.render(*rendered_formats) if rendered_formats else changed


def _subset(run: CampaignRun, candidate: GeneratedCandidate) -> CampaignRun:
    return CampaignRun(spec=run.spec, attempts=(candidate,), instances=(), constructions=tuple(
        item for item in run.constructions if item.candidate.plan.ordinal == candidate.plan.ordinal
    ))


def _supported(estimate: DifficultyEstimate, plan: NoiseCalibrationPlan) -> bool:
    return bool(estimate.fitted and estimate.interval_low is not None and estimate.interval_high is not None
                and estimate.interval_low >= plan.target_low and estimate.interval_high <= plan.target_high)


def calibrate_noise(
    run: CampaignRun,
    plan: NoiseCalibrationPlan,
    evaluate: Callable[[TrialRequest], TrialOutcome],
    *,
    read: Callable[[World, EvalInstance], ReaderAcceptance] | None = None,
    fidelity: Callable[[World], FidelityReport] | None = None,
    recorded: NoiseCalibrationRecord | None = None,
    checkpoint: Callable[[NoiseCalibrationRecord], None] | None = None,
) -> NoiseCalibrationRun:
    """Schedule bounded, nonmonotonic interventions; freeze before holdout.

    A recorded prefix resumes; a complete record replays without external calls.
    Reader callbacks may append their review ledger, but authoring belongs before
    this operation. Untrusted agent results require a caller-owned grading adapter.
    """
    plan = NoiseCalibrationPlan.model_validate(plan.model_dump(mode="json"))
    plan_key = digest(plan.model_dump(mode="json"))
    ordinals = {c.plan.ordinal for c in run.attempts}
    if len(ordinals) != len(run.attempts) or len({c.plan.seed for c in run.attempts}) != len(run.attempts):
        raise ValueError("calibration candidates must have distinct ordinals and seeds")
    if not set(plan.holdout_ordinals) < ordinals:
        raise ValueError("holdout must be a nonempty strict subset of candidate ordinals")
    if len(run.attempts) > 128:
        raise ValueError("calibration supports at most 128 baseline candidates")
    baseline = digest({"spec": run.spec.model_dump(mode="json"), "worlds": [
        {"plan": c.plan.model_dump(mode="json"), "world": world_digest(c.world)} for c in run.attempts
    ]})
    if recorded is not None:
        recorded = NoiseCalibrationRecord.model_validate(recorded.model_dump(mode="json"))
        if (recorded.plan_digest, recorded.baseline_digest) != (plan_key, baseline):
            raise ValueError("recorded noise calibration plan or baseline changed")
    entries: list[CalibrationAttempt] = []
    previous = recorded.attempts if recorded else ()
    candidates = {c.plan.ordinal: c for c in run.attempts}
    training = tuple(sorted(ordinals - set(plan.holdout_ordinals)))
    holdout = tuple(sorted(plan.holdout_ordinals))
    variants = {v.name: v for v in plan.variants}
    features = {v.name: feature_slice(run.spec, conditions={
        "noise_variant": digest(v.model_dump(mode="json")), "calibration_plan": plan_key,
    }) for v in plan.variants}
    calibrator = DifficultyCalibrator()
    completed: dict[str, list[CampaignRun]] = {v.name: [] for v in plan.variants}
    cursors = {v.name: 0 for v in plan.variants}

    def estimate(name: str) -> DifficultyEstimate:
        return calibrator.estimate(plan.cohort, features[name], min_trials=plan.min_support)

    def attempt(name: str, ordinal: int, split: Literal["train", "holdout"]) -> None:
        variant = variants[name]
        old = previous[len(entries)] if len(entries) < len(previous) else None
        if old is not None and (old.variant, old.ordinal, old.split) != (name, ordinal, split):
            raise ValueError("recorded attempt conflicts with deterministic calibration schedule")
        source = candidates[ordinal]
        missing_generator = bool(sum(variant.budget.values()) and source.world._minter is None)
        transformed = _subset(run, source).map_worlds(lambda world: world if missing_generator else
            _noise_world(world, variant, plan.formats, replay_ledger=old.ledger if old else None))
        candidate = transformed.attempts[0]
        findings: list[str] = ["noise_generator_state_missing"] if missing_generator else []
        quality: dict[str, Any] = {}
        if not candidate.validation.accepted:
            findings.append("candidate_requirements_failed")
        if not candidate.world.validate().ok:
            findings.append("world_validation_failed")
        if not findings and plan.reader_id:
            from ..narrative.reader_checks import plan as reader_plan
            from ..narrative.reader_checks import replay, verified_review
            expected_plan = reader_plan(candidate.world, reader_id=plan.reader_id, instances=transformed.instances,
                                        share=float(plan.reader_config.get("share", packkit.policy("evals.calibration.reader_share"))),
                                        reader_config=plan.reader_config)
            if old:
                from ..narrative.reader_checks import ReaderReview
                present = {entry.key for entry in candidate.world.ledger}
                new_keys = tuple(entry.key for entry in old.ledger if entry.key not in present)
                world = replay(candidate.world, keys=new_keys, ledger=old.ledger) if new_keys else candidate.world
                review_payload = old.quality.get("reader")
                if review_payload is None:
                    findings.append("reader_input_missing")
                else:
                    review = verified_review(world, ReaderReview.model_validate(review_payload), instances=transformed.instances)
                    transformed = transformed.map_worlds(lambda _: world)
                    quality["reader"] = review.model_dump(mode="json")
                    if not review.passed:
                        findings.append("reader_rejected")
            elif read is None:
                findings.append("reader_input_missing")
            else:
                acceptance = read(candidate.world, transformed.instances[0])
                review = verified_review(acceptance.world, acceptance.review, instances=transformed.instances)
                present = {entry.key for entry in candidate.world.ledger}
                new_keys = tuple(entry.key for entry in acceptance.world.ledger if entry.key not in present)
                restored = replay(candidate.world, keys=new_keys, ledger=tuple(acceptance.world.ledger)) if new_keys else candidate.world
                if world_digest(restored) != world_digest(acceptance.world):
                    raise ValueError("reader callback changed the corpus beyond its review ledger")
                quality["reader"] = review.model_dump(mode="json")
                transformed = transformed.map_worlds(lambda _: acceptance.world)
                if not review.passed:
                    findings.append("reader_rejected")
            if "reader" in quality and quality["reader"].get("plan_id") != expected_plan.id:
                findings.append("reader_policy_mismatch")
            if not transformed.attempts[0].validation.accepted:
                findings.append("post_reader_requirements_failed")
        candidate = transformed.attempts[0]
        if not findings and plan.fidelity_slices:
            if old:
                report = old.quality.get("fidelity")
            elif fidelity is None:
                report = None
            else:
                measured = fidelity(candidate.world)
                report = measured.as_dict()
                report["support_complete"] = measured.support_complete
            if report is None:
                findings.append("fidelity_input_missing")
            else:
                quality["fidelity"] = report
                if not report.get("support_complete"):
                    findings.append("fidelity_support_incomplete")
                if not set(plan.fidelity_slices) <= set(report.get("slice_support", {})):
                    findings.append("fidelity_slice_missing")
                for threshold in plan.fidelity_thresholds:
                    value: Any = report
                    for key in threshold.path:
                        value = value.get(key) if isinstance(value, dict) else None
                    if type(value) not in (int, float) or not math.isfinite(value):
                        findings.append("fidelity_metric_missing:" + ".".join(threshold.path))
                    elif value > threshold.maximum:
                        findings.append("fidelity_metric_exceeded:" + ".".join(threshold.path))
        corpus_key = world_digest(candidate.world)
        trial_id = digest([plan_key, name, ordinal, split, corpus_key])
        observation = None
        outcome = None
        if not findings:
            outcome = old.outcome if old else TrialOutcome.model_validate(
                evaluate(TrialRequest(candidate.world, transformed.instances[0], variant, trial_id, split)).model_dump(mode="json")
            )
            if outcome is None:
                raise ValueError("recorded accepted attempt has no outcome")
            if world_digest(candidate.world) != corpus_key:
                raise ValueError("evaluator changed the candidate corpus")
            observation = CalibrationObservation(
                cohort=plan.cohort, trial_id=trial_id, eval_id=transformed.instances[0].id,
                corpus_digest=corpus_key, evaluator_config_digest=digest(plan.evaluator_config),
                evaluator_kind=plan.evaluator_kind, features=features[name], passed=outcome.passed, split=split,
            )
            calibrator.ingest(observation)
            completed[name].append(transformed)
        actual: dict[str, int] = {}
        for error in candidate.world.intentional_errors:
            kind = str(error.error_type)
            actual[kind] = actual.get(kind, 0) + 1
        body: dict[str, Any] = dict(variant=name, ordinal=ordinal, split=split, corpus_digest=corpus_key,
                    findings=tuple(findings), actual_noise=actual, quality=quality,
                    ledger=tuple(candidate.world.ledger), observation=observation, outcome=outcome)
        # Pydantic serializes nested receipts consistently before addressing them.
        raw = {k: [x.model_dump(mode="json") for x in v] if k == "ledger" else
               v.model_dump(mode="json") if isinstance(v, Model) else v for k, v in body.items()}
        entry = CalibrationAttempt(**body, receipt_digest=digest(raw))
        if old is not None and entry != old:
            raise ValueError("recorded noise observation or quality receipt conflicts with current world")
        if digest(plan.model_dump(mode="json")) != plan_key:
            raise ValueError("calibration callback changed the sealed plan")
        entries.append(entry)
        if checkpoint:
            checkpoint(NoiseCalibrationRecord(plan=plan, plan_digest=plan_key, baseline_digest=baseline, attempts=tuple(entries)))

    while sum(cursors.values()) < plan.max_training_attempts:
        available = [name for name, index in cursors.items() if index < len(training)]
        if not available:
            break
        # Explore every variant, then spend support near the target before distant
        # slices. This is finite scheduling, not an assumed severity response curve.
        def priority(name: str) -> tuple[int, int, float, str]:
            current = estimate(name)
            overlap = bool(current.interval_low is not None and current.interval_high is not None
                           and current.interval_low <= plan.target_high and current.interval_high >= plan.target_low)
            return (int(current.trials >= plan.min_support), int(not overlap), float(cursors[name]), name)
        name = min(available, key=priority)
        attempt(name, training[cursors[name]], "train")
        cursors[name] += 1
    archive = Archive((Axis("noise_niche", plan.niches),))
    for name in sorted(variants):
        current = estimate(name)
        if _supported(current, plan):
            archive.consider(name, (variants[name].niche,), -abs(current.predicted_pass_rate - (plan.target_low + plan.target_high) / 2))
    selected = tuple(elite.key for elite in archive.elites())
    # Selection is now immutable. Holdout outcomes cannot update training counts
    # or choose a different variant; even a failed holdout remains reported.
    holdout_count = 0
    for ordinal in holdout:
        for name in selected:
            if holdout_count >= plan.max_holdout_attempts:
                break
            attempt(name, ordinal, "holdout")
            holdout_count += 1
    if len(previous) > len(entries):
        raise ValueError("recorded attempts exceed current calibration schedule")
    summaries: list[VariantCalibration] = []
    for name in sorted(variants):
        test = calibrator.estimate(plan.cohort, features[name], min_trials=plan.min_support, split="holdout") if name in selected else None
        summaries.append(VariantCalibration(variant=name, estimate=estimate(name), target_supported=_supported(estimate(name), plan),
            holdout_estimate=test, holdout_status=("supported" if test and _supported(test, plan) else
                "target_unmet" if test and test.fitted else "insufficient_support" if test else "not_selected")))
    campaigns: list[tuple[str, CampaignRun]] = []
    for name in selected:
        pieces = completed[name]
        campaigns.append((name, CampaignRun(spec=run.spec,
            attempts=tuple(c for piece in pieces for c in piece.attempts),
            instances=tuple(i for piece in pieces for i in piece.instances),
            constructions=tuple(c for piece in pieces for c in piece.constructions))))
    training_count = sum(cursors.values())
    exhausted = all(index == len(training) for index in cursors.values())
    report = NoiseCalibrationReport(
        status="selected" if selected else "target_unmet" if any(estimate(name).fitted for name in variants) else "unfitted",
        training_attempts=training_count, holdout_attempts=holdout_count, training_exhausted=exhausted,
        training_budget_exhausted=not exhausted and training_count >= plan.max_training_attempts,
        holdout_budget_exhausted=holdout_count < len(selected) * len(holdout),
        selected_variants=selected, holes=tuple(coordinate[0] for coordinate in archive.holes()), variants=tuple(summaries),
    )
    record = NoiseCalibrationRecord(plan=plan, plan_digest=plan_key, baseline_digest=baseline, attempts=tuple(entries))
    return NoiseCalibrationRun(plan, record, report, tuple(campaigns))


__all__ = ["NoiseVariant", "MetricThreshold", "NoiseCalibrationPlan", "TrialRequest", "TrialOutcome",
           "CalibrationAttempt", "NoiseCalibrationRecord", "VariantCalibration", "NoiseCalibrationReport",
           "NoiseCalibrationRun", "calibrate_noise", "world_digest"]
