#!/usr/bin/env python3
"""Measure reader admission, slice support and replayed noise calibration.

    python tools/measure_quality_calibration.py --out docs/measurements/quality-calibration.json

This is a deterministic protocol probe over real generated Worlds. Its explicit
Subject/aspect/value prose and regex extractor measure integration, not natural
language comprehension, production difficulty, or enterprise realism. The small
support and broad acceptance interval are reported, never extrapolated. No model
service, credentials, downloaded data, or additional dependencies are used.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.corpus import write_json
from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.eval_instances import EvalInstance, EvalOracle
from worldloom.eval_metrics import DifficultyCalibrator
from worldloom.evals.calibration import (
    MetricThreshold,
    NoiseCalibrationPlan,
    NoiseCalibrationRecord,
    NoiseVariant,
    TrialOutcome,
    TrialRequest,
    calibrate_noise,
    world_digest,
)
from worldloom.evals.campaign import EvalCampaign
from worldloom.evaluate.index import passages
from worldloom.fidelity import compute
from worldloom.narrative import handshake, programs
from worldloom.narrative import reader_checks as readers
from worldloom.narrative.providers import ResponseProvider, UnreachableProvider
from worldloom.narrative.requests import GeneratedClaim, GeneratedNarrative
from worldloom.providers import digest
from worldloom.recipe import rebuild

AUTHOR = "scripted-protocol-author/v1"
READER = "scripted-protocol-reader/v1"
COHORT = "scripted-protocol-probe/v1"
READER_CONFIG = {"share": 0, "implementation": "subject-aspect-value-regex/v1"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _files(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)): _sha(path.read_bytes())
            for path in sorted(directory.rglob("*")) if path.is_file()}


def _no_call(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("offline replay invoked an external callback")


def _authored(world: World) -> World:
    world = world.compile()
    facts = {fact.id: fact for fact in world.facts}
    responses = {}
    for request in handshake.pending(world):
        sentences = [(fid, "Subject " + request.subjects.get(fid, facts[fid].subject)
                      + "; aspect " + facts[fid].kind + "; value {{fact:" + fid + "}}.")
                     for fid in request.allowed_fact_ids]
        responses[f"{request.artifact_id}/{request.section}"] = GeneratedNarrative(
            text="\n".join(sentence for _, sentence in sentences),
            claims=[GeneratedClaim(text=sentence, supporting_fact_ids=[fid]) for fid, sentence in sentences],
        )
    return world.narrate(ResponseProvider(responses, model_id=AUTHOR))


def _reader(request: readers.ReaderRequest) -> readers.ReaderResponse:
    """Public payload only. The parser receives no World, target, or oracle."""
    kinds = {kind.replace("_", " ").replace(".", " "): kind for kind in request.aspects}
    kinds.update({kind: kind for kind in request.aspects})
    claims = []
    for line in request.text.replace(". Subject ", ".\nSubject ").splitlines():
        found = re.fullmatch(r"Subject (.+); aspect ([^;]+); value (.+)\.", line)
        if found:
            subject, kind, value = found.groups()
            claims.append(readers.RecoveredClaim(kind=kinds.get(kind, kind), subject=subject,
                                                value=value, quote=line))
    return readers.ReaderResponse(id=request.id, request_id=request.request_id,
        reader_id=request.reader_id, text_digest=request.text_digest,
        contract_version=request.contract_version, claims=tuple(claims))


def _critical(world: World) -> tuple[str, ...]:
    section = next(section for ir in world.artifact_irs for section in ir.sections
                   if section.body and len(section.fact_ids) >= 5)
    return tuple(section.fact_ids[:5])


def _instance(world: World, critical: tuple[str, ...]) -> EvalInstance:
    return EvalInstance(id="protocol-eval-reader", spec_id="protocol-reader", candidate_seed=world.seed or 0,
        design_digest=digest({"critical": critical}), capability="read", persona="analyst",
        request="Recover the stated evidence.", difficulty="medium", steps=(), assertions=(),
        oracle=EvalOracle(fact_ids=critical, evidence_by_requirement={}))


def _review_summary(review: readers.ReaderReview) -> dict[str, Any]:
    return {"passed": review.passed, "critical": len(review.critical_fact_ids),
            "recovered_critical": len(review.recovered_critical_fact_ids),
            "missing_critical": len(review.missing_critical_fact_ids),
            "finding_count": len(review.findings),
            "issues": [issue.model_dump(mode="json") for issue in review.issues]}


def _world_replay(world: World, planned: readers.ReaderPlan, directory: Path,
                  *, program_expansion: bool = False) -> dict[str, Any]:
    world.export(directory / "original")
    loaded = World.load(directory / "original")
    rebuilt = rebuild(loaded.recipe, ledger=tuple(loaded.ledger))
    # Recipe restores metadata; the ordinary narrator replays authored prose.
    author = next(entry.model_id for entry in loaded.ledger if entry.call_site == "narration.program") if program_expansion else AUTHOR
    rebuilt = rebuilt.narrate(UnreachableProvider(id=author), ledger=tuple(loaded.ledger))
    cached = readers.run(rebuilt, planned, _no_call)
    _require(cached.review.passed and cached.replayed and cached.reader_calls == 0,
             "reader acceptance was not restored offline")
    cached.world.export(directory / "replayed")
    first, second = _files(directory / "original"), _files(directory / "replayed")
    _require(first == second, "world recipe and ledger replay changed export bytes")
    return {"reader_calls": cached.reader_calls, "replayed": cached.replayed,
            "export_byte_equal": True, "export_files": len(first), "export_digest": digest(first)}


def _reader_probe(directory: Path) -> dict[str, Any]:
    baseline = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
    world = _authored(baseline)
    critical = _critical(world)
    instance = _instance(world, critical)
    planned = readers.plan(world, reader_id=READER, instances=(instance,), share=0,
                           reader_config=READER_CONFIG)
    wire = json.dumps(planned.requests_document(), sort_keys=True)
    _require(not any(fid in wire for fid in critical), "reader payload leaked fact identifiers")
    _require(all(token not in wire for token in ("targets_digest", "expected_value", "critical_fact_ids", "{{fact:")),
             "reader payload leaked trusted-side targets")
    counts = Counter(target.request_id for target in planned.targets)
    _require(max(counts.values()) > 3, "probe did not exceed prior three-target ceiling")
    accepted = readers.run(world, planned, _reader).raise_if_failed()
    readers.verified_review(accepted.world, accepted.review, instances=(instance,))
    failed = readers.accept(world, planned)
    _require(not failed.review.passed and len(failed.world.ledger) > len(world.ledger),
             "missing responses did not persist a rejected review")
    replies = tuple(_reader(request) for request in planned.requests)
    wrong_reader = tuple(reply.model_copy(update={"reader_id": "different-reader"}) for reply in replies)
    refused_identity = readers.accept(world, planned, wrong_reader)
    _require(not refused_identity.review.passed, "wrong reader identity passed")
    changed = replace(accepted.world, _artifact_irs=tuple(ir.model_copy(update={"sections": [
        section.model_copy(update={"body": section.body + " Changed wording."}) if section.body else section
        for section in ir.sections]}) for ir in accepted.world.artifact_irs))
    stale = readers.run(changed, planned, _no_call)
    _require(not stale.review.passed, "changed prose reused stale reader acceptance")
    empty = readers.accept(world, readers.plan(world, reader_id=READER, share=0))
    _require(not empty.review.passed, "empty reader sample passed")
    failed.world.export(directory / "rejected")
    rejected = World.load(directory / "rejected")
    _require(tuple(rejected.ledger) == tuple(failed.world.ledger), "rejected review lost during export")

    program_plan = programs.plan(baseline, budget=programs.Budget(
        model_calls=1000, variants_per_family=1, near_dup_rate=1))
    authored_programs = tuple(programs.NarrativeProgram(family=family.id, clauses=(programs.ProgramClause(
        id="record", kind="*", maximum=256,
        alternatives=("Subject $subject; aspect $kind; value $value.",),
    ),)) for family in program_plan.families)
    expansion = programs.expand(baseline, program_plan, authored_programs)
    expanded_plan = readers.plan(baseline, reader_id=READER, instances=(instance,), share=0,
                                 expansion=expansion, reader_config=READER_CONFIG)
    expanded_replies = tuple(_reader(request) for request in expanded_plan.requests)
    expanded_review = readers.check_plan(baseline, expanded_plan, expanded_replies, expansion=expansion)
    _require(expanded_review.passed, "program expansion failed shared reader boundary")
    committed = programs.commit(baseline, expansion, reader_plan=expanded_plan, reader_responses=expanded_replies)
    refused_program = False
    try:
        programs.commit(baseline, expansion, reader_plan=expanded_plan)
    except readers.ReaderRejected:
        refused_program = True
    _require(refused_program, "program commit accepted missing critical reader responses")
    return {"seed": 8128, "period": "2026-03", "facts": len(world.facts),
            "artifacts": len(world.artifact_irs), "author": AUTHOR, "reader": READER,
            "reader_protocol": READER_CONFIG, "public_requests": len(planned.requests),
            "public_payload_digest": digest(planned.requests_document()), "target_count": len(planned.targets),
            "maximum_targets_per_request": max(counts.values()), "all_oracle_facts_targeted": True,
            "public_payload_contains_private_targets": False,
            "accepted": _review_summary(accepted.review), "missing_response": _review_summary(failed.review),
            "wrong_reader": _review_summary(refused_identity.review), "stale_text": _review_summary(stale.review),
            "empty_sample": _review_summary(empty.review), "rejected_ledger_export_equal": True,
            "ordinary_replay": _world_replay(accepted.world, planned, directory / "ordinary"),
            "program_expansion": {"families": len(program_plan.families), "sections": len(expansion.sections),
                "review": _review_summary(expanded_review), "missing_response_commit_refused": refused_program,
                "replay": _world_replay(committed, expanded_plan, directory / "program", program_expansion=True)}}


def _fidelity_probe() -> dict[str, Any]:
    reference = [{"region": "north", "amount": 10}, {"region": "north", "amount": 20},
                 {"region": "south", "amount": 10}, {"region": "south", "amount": 20}]
    synthetic = reference[:2]
    report = compute(reference, synthetic, slices=("region",))
    capped = compute(reference, reference, slices=("region",), max_slices=1)
    matched = compute(reference, reference, slices=("region",))
    _require(report.columns["amount"]["ks"] == 0, "missing-region control did not match global amount distribution")
    _require(not report.support_complete and not capped.support_complete and matched.support_complete,
             "slice support incorrectly admitted missing or omitted populations")
    _require(report.slice_support["region"].reference_supported_rows == 2,
             "missing-group denominator was dropped")
    return {"reference_rows": len(reference), "synthetic_rows": len(synthetic),
            "reference_digest": digest(reference), "synthetic_digest": digest(synthetic),
            "missing_region": report.as_dict(), "missing_region_admitted": report.support_complete,
            "findings": [asdict(finding) for finding in report.support_findings()],
            "capped_support": capped.slice_support["region"].as_dict(),
            "capped_admitted": capped.support_complete, "matched_admitted": matched.support_complete}


def _projection(world: World) -> list[dict[str, Any]]:
    # Every persisted fact contributes; this is a world-relative drift check,
    # not a comparison with private enterprise data or a realism measurement.
    return [{"authority": str(fact.authority), "kind": fact.kind,
             "display_length": len(str(fact.value if fact.value is not None else fact.text_value))}
            for fact in world.facts]


def _public_date_solver(question: str, passages: tuple[str, ...]) -> tuple[str, ...]:
    """An explicit-format extractor, without access to an EvalInstance or World."""
    if "committed date" not in question:
        return ()
    return tuple(sorted({value for passage in passages for value in re.findall(
        r"; aspect close\.due_date; value (\d{4}-\d{2}-\d{2})\.", passage)}))


def _generic_campaign_replay(result: Any, directory: Path) -> dict[str, Any]:
    """Exercise the ordinary recipe/ledger path, without calibration records."""
    worlds = []
    for name, campaign in result.campaigns:
        for candidate in campaign.selected:
            target = directory / name / str(candidate.plan.ordinal)
            candidate.world.export(target / "original")
            loaded = World.load(target / "original")
            authors = tuple(sorted({ir.metadata["narrated_by"] for ir in loaded.artifact_irs
                                    if ir.metadata.get("narrated_by")}))
            _require(bool(authors), "selected world has no recorded prose authors")
            rebuilt = rebuild(loaded.recipe, ledger=tuple(loaded.ledger))
            rebuilt = rebuilt.narrate(UnreachableProvider(allowed_model_ids=authors),
                                       ledger=tuple(loaded.ledger)).render(*result.plan.formats)
            rebuilt.export(target / "replayed")
            first, second = _files(target / "original"), _files(target / "replayed")
            _require(first == second, f"generic recipe replay changed {name}/{candidate.plan.ordinal}")
            worlds.append({"variant": name, "ordinal": candidate.plan.ordinal,
                "author_ids": authors, "unreachable_provider_calls": 0,
                "export_byte_equal": True, "export_files": len(first), "export_digest": digest(first),
                "native_formats": result.plan.formats})
    _require(bool(worlds), "generic replay checked no selected worlds")
    return {"worlds_checked": len(worlds), "unreachable_provider_calls": 0,
            "calibration_record_used": False, "all_export_bytes_equal": True, "worlds": worlds}


def _controller_probe(directory: Path) -> dict[str, Any]:
    spec = EvalSpec(id="protocol-close-date", capability="search", persona="controller",
        request_template="What is the committed date for period close?",
        steps=(EvalStepSpec(id="read", capability="search"),),
        requirements=(WorldRequirement(id="due-date", kind=RequirementKind.FACT,
                                        selector={"kind": "close.due_date"}),), candidate_count=6)
    run = EvalCampaign(spec).run(lambda candidate: _authored(
        RetailWorld(seed=candidate.seed).build().run(MonthEndClose(period="2026-03"))))
    _require(len(run.instances) == spec.candidate_count, "baseline candidate requirements refused")
    references = {candidate.world.seed: _projection(candidate.world) for candidate in run.attempts}
    plan = NoiseCalibrationPlan(variants=(NoiseVariant(name="clean", budget={}, niche="current"),
        NoiseVariant(name="lived-in", budget={"staleness": 1, "mechanical": 1}, niche="decayed")),
        niches=("current", "decayed", "unproposed"), cohort=COHORT,
        evaluator_config={"implementation": "close-date-public-regex/v1", "grader": "canonical-date-exact/v1",
                          "measurement_kind": "scripted protocol, not language-model quality"},
        target_low=.2, target_high=1, min_support=2, max_training_attempts=8,
        max_holdout_attempts=4, holdout_ordinals=(4, 5), formats=("markdown",),
        reader_id=READER, reader_config=READER_CONFIG,
        fidelity_config={"reference_digest": digest(references), "projection": "all-fact-display-length/v1"},
        fidelity_slices=("authority",),
        fidelity_thresholds=(MetricThreshold(path=("univariate", "display_length", "ks"), maximum=.1),))
    calls: Counter[str] = Counter()
    def read(world: World, instance: EvalInstance) -> readers.ReaderAcceptance:
        calls["reader_boundary"] += 1
        return readers.run(world, readers.plan(world, reader_id=READER, instances=(instance,), share=0,
                           reader_config=READER_CONFIG), _reader)
    def fidelity(world: World) -> Any:
        calls["fidelity"] += 1
        return compute(references[world.seed], _projection(world), slices=("authority",), max_slices=64)
    def evaluate(request: TrialRequest) -> TrialOutcome:
        calls[request.split + "_evaluator"] += 1
        public_passages = tuple(passage.text for passage in passages(request.world))
        recovered = _public_date_solver(request.instance.request, public_passages)
        oracle = set(request.instance.oracle.fact_ids)
        expected = tuple(sorted({str(fact.text_value) for fact in request.world.facts if fact.id in oracle}))
        return TrialOutcome(passed=bool(expected) and recovered == expected,
            details={"solver": "public regex over authored passages", "recovered": recovered,
                     "expected_count": len(expected), "passages": len(public_passages)})
    checkpoints = []
    result = calibrate_noise(run, plan, evaluate, read=read, fidelity=fidelity, checkpoint=checkpoints.append)
    _require(result.report.selected_variants, "protocol probe selected no supported variant")
    _require(all(attempt.observation is not None for attempt in result.record.attempts),
             "accepted-path measurement unexpectedly refused a quality input")
    splits = [attempt.split for attempt in result.record.attempts]
    _require(splits == sorted(splits, key=lambda split: split != "train"), "holdout ran before selection froze")
    result.record.export(directory / "record.json")
    loaded = NoiseCalibrationRecord.load(directory / "record.json")
    replay = calibrate_noise(run, plan, _no_call, read=_no_call, fidelity=_no_call, recorded=loaded)
    _require(replay.record == result.record and replay.report == result.report, "cold record replay changed calibration")
    result.export(directory / "original")
    replay.export(directory / "replayed")
    exports = _files(directory / "original")
    _require(exports == _files(directory / "replayed"), "noise calibration replay changed exported worlds")
    generic_replay = _generic_campaign_replay(result, directory / "generic-replay")
    resume_calls = Counter()
    def resume_evaluate(request: TrialRequest) -> TrialOutcome:
        resume_calls["evaluator"] += 1
        return evaluate(request)
    resumed = calibrate_noise(run, plan, resume_evaluate, read=read, fidelity=fidelity, recorded=checkpoints[4])
    _require(resumed.record == result.record, "checkpoint resume changed final receipts")
    _require(resume_calls["evaluator"] == len(result.record.attempts) - 5, "resume repeated recorded evaluator calls")
    narrow = plan.model_copy(update={"target_low": .4, "target_high": .6, "max_training_attempts": 2})
    refused = calibrate_noise(run, narrow, evaluate, read=read, fidelity=fidelity)
    _require(not refused.report.selected_variants and refused.report.holdout_attempts == 0,
             "under-supported narrow interval was accepted")
    quality_refused = calibrate_noise(run, plan, _no_call)
    _require(not any(attempt.observation for attempt in quality_refused.record.attempts),
             "missing quality callbacks produced training observations")
    quality_replay = calibrate_noise(run, plan, _no_call, recorded=quality_refused.record)
    _require(quality_replay.record == quality_refused.record, "failed quality record did not replay")

    calibrator = DifficultyCalibrator()
    observations = tuple(attempt.observation for attempt in result.record.attempts if attempt.observation is not None)
    for observation in observations:
        if observation.split == "train":
            calibrator.ingest(observation)
    train_before = {row.features.slice_key: calibrator.estimate(COHORT, row.features, min_trials=2)
                    for row in observations if row.split == "train"}
    for observation in observations:
        if observation.split == "holdout":
            calibrator.ingest(observation)
    for row in observations:
        if row.split == "train":
            _require(calibrator.estimate(COHORT, row.features, min_trials=2) == train_before[row.features.slice_key],
                     "holdout observations changed training estimates")
    added_on_replay = sum(calibrator.ingest(row) for row in observations)
    _require(added_on_replay == 0, "observation replay manufactured trial support")
    snapshot_path = calibrator.export(directory / "cohort.json")
    restored = DifficultyCalibrator.load(snapshot_path)
    _require(restored.snapshot() == calibrator.snapshot(), "calibration snapshot changed on reload")
    restored.export(directory / "cohort-reloaded.json")
    _require(snapshot_path.read_bytes() == (directory / "cohort-reloaded.json").read_bytes(),
             "calibration snapshot bytes changed on reload")
    for row in observations:
        if row.split == "train":
            _require(restored.estimate(COHORT, row.features, min_trials=2) == train_before[row.features.slice_key],
                     "snapshot replay changed training estimates")
    overlap_refusal = ""
    train_row = next(row for row in observations if row.split == "train")
    try:
        restored.ingest(train_row.model_copy(update={"trial_id": "disallowed-overlap", "split": "holdout"}))
    except ValueError as exc:
        overlap_refusal = str(exc)
    _require(bool(overlap_refusal), "same eval/corpus group leaked into holdout")
    reference = DifficultyCalibrator()
    for row in observations:
        reference.ingest(row.model_copy(update={"cohort": "reference-protocol-probe/v1", "evaluator_kind": "reference_executor"}))
    reference_estimate = reference.estimate("reference-protocol-probe/v1", train_row.features, min_trials=2)
    _require(not reference_estimate.fitted and reference_estimate.trials == 0,
             "reference execution was relabeled empirical agent difficulty")
    return {"cohort": COHORT, "cohort_kind": "deterministic regex protocol probe; not an LLM",
            "baseline_worlds": len(run.attempts), "seeds": [candidate.world.seed for candidate in run.attempts],
            "baseline_world_digests": [world_digest(candidate.world) for candidate in run.attempts],
            "plan": plan.model_dump(mode="json"), "report": result.report.model_dump(mode="json"),
            "attempts": [{"variant": a.variant, "ordinal": a.ordinal, "split": a.split,
                "corpus_digest": a.corpus_digest, "receipt_digest": a.receipt_digest,
                "findings": a.findings, "actual_noise": a.actual_noise,
                "outcome": a.outcome.model_dump(mode="json") if a.outcome else None,
                "reader": _review_summary(readers.ReaderReview.model_validate(a.quality["reader"]))
                    if "reader" in a.quality else None} for a in result.record.attempts],
            "record_digest": digest(result.record.model_dump(mode="json")),
            "export_digest": digest(exports), "export_files": len(exports), "export_byte_equal": True,
            "cold_replay_external_calls": 0, "checkpoint_prefix_attempts": 5,
            "generic_recipe_ledger_replay": generic_replay,
            "resume_evaluator_calls": resume_calls["evaluator"], "all_probe_callback_counts": dict(sorted(calls.items())),
            "narrow_band_refusal": refused.report.model_dump(mode="json"),
            "missing_quality_refusals": dict(sorted(Counter(finding for a in quality_refused.record.attempts
                                                             for finding in a.findings).items())),
            "failed_quality_replay_equal": True,
            "calibration": {"snapshot_digest": restored.snapshot().digest, "snapshot_byte_equal": True,
                "observations": len(observations), "splits": dict(sorted(Counter(row.split for row in observations).items())),
                "replay_added_trials": added_on_replay, "split_overlap_refusal": overlap_refusal,
                "holdout_changed_training_estimates": False,
                "heldout_report": restored.report(COHORT, min_trials=2).model_dump(mode="json"),
                "reference_only_estimate": reference_estimate.model_dump(mode="json"),
                "default_support_estimate": restored.estimate(COHORT, train_row.features).model_dump(mode="json")}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sources = ("src/worldloom/narrative/reader_checks.py", "src/worldloom/narrative/programs.py",
               "src/worldloom/narrative/compiler.py", "src/worldloom/narrative/providers.py",
               "src/worldloom/recipe.py", "src/worldloom/fidelity.py", "src/worldloom/eval_metrics.py",
               "src/worldloom/evals/difficulty.py", "src/worldloom/evals/calibration.py",
               "src/worldloom/evals/campaign.py", "src/worldloom/messiness.py", "tools/measure_quality_calibration.py")
    with tempfile.TemporaryDirectory(prefix="worldloom-quality-probe-") as temporary:
        root = Path(temporary)
        for name in ("readers", "controller"):
            (root / name).mkdir()
        result = {"schema": "worldloom.quality-calibration-measurement/v1",
            "scope": "Bounded integration and determinism measurement; no claim of production or language-model quality.",
            "runtime": {"python": sys.version.split()[0], **{name: importlib.metadata.version(name)
                         for name in ("worldloom", "pydantic", "numpy")}},
            "source_sha256": {name: _sha((ROOT / name).read_bytes()) for name in sources},
            "reader_admission": _reader_probe(root / "readers"), "fidelity": _fidelity_probe(),
            "noise_calibration": _controller_probe(root / "controller")}
    write_json(args.out, result)
    print(json.dumps({"out": str(args.out), "reader_critical_targets": result["reader_admission"]["accepted"]["critical"],
                      "noise_status": result["noise_calibration"]["report"]["status"],
                      "observations": result["noise_calibration"]["calibration"]["observations"]}, sort_keys=True))


if __name__ == "__main__":
    main()
