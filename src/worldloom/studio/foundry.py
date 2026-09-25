"""Durable construction, quality measurement, case trials, and one frozen world.

No stage publishes a dataset merely because the reference executor can solve
it. Selection depends on observed target-agent traces and a sealed holdout.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from .. import packkit
from ..enterprise_io import load_exported_corpus
from ..eval_candidates import validate_candidate
from ..eval_metrics import CalibrationObservation
from ..evals.calibration import _noise_world, world_digest
from ..evals.company_dataset import FrozenCompanyBuilder
from ..evals.dataset import _files, _read, compile_dataset, verify_dataset
from ..narrative import handshake, reader_checks
from ..providers import digest
from .calibration import estimates, features, independent_samples, select, supported
from .checkpoints import Exchanges, atomic_json, document, load_world, save_world
from .construction import (
    bind_query,
    compile_project,
    construct_company,
)
from .models import ProjectSpec, RunOptions

if TYPE_CHECKING:
    from ..world import World
    from .service import Studio


def progress(studio: Studio, job_id: str) -> dict[str, Any] | None:
    path = studio.path("foundry", job_id) / "progress.json"
    return _read(path) if path.exists() else None


def _rows(root: Path) -> list[dict[str, Any]]:
    with (root / "queryset.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def _review(world: World, location: Path, critical: set[str], *, command: str | None,
            timeout: float, share: float) -> dict[str, Any]:
    if not world.artifact_intents and not world.artifact_irs:
        # Structured evidence has no authored sections for this reader. Do
        # not manufacture an accepted review from an empty request set.
        return {"status": "missing_prose_evidence" if critical else "not_applicable",
                "requests": 0, "reason": "No authored document sections in this world"}
    intent = {"noise": world_digest(world), "critical": sorted(critical),
              "reader": digest(command), "share": share}
    reviewed = load_world(location / "reader", intent)
    if reviewed is not None:
        reader_checks.verified_review(reviewed[0], reader_checks.ReaderReview.model_validate(reviewed[1]["review"]),
                                      critical_fact_ids=sorted(critical))
        return reviewed[1]
    planned = reader_checks.plan(world, reader_id="foundry-reader/" + digest(command),
        critical_fact_ids=sorted(critical), share=share,
        reader_config={"harness": digest(command), "role": "blind-reader"})
    exchange = Exchanges(location / "reader-turns", command, timeout)

    def read(request: reader_checks.ReaderRequest) -> reader_checks.ReaderResponse:
        payload = {"schema": "worldloom.blind-reader/v1", "request": request.model_dump(mode="json"),
                   "instructions": packkit.text("studio.foundry.reader.instructions"),
                   "response_schema": reader_checks.ReaderResponse.model_json_schema()}
        return reader_checks.ReaderResponse.model_validate(exchange(payload).document)

    acceptance = reader_checks.run(world, planned, read)
    review = reader_checks.verified_review(acceptance.world, acceptance.review, critical_fact_ids=sorted(critical))
    result = {"status": "measured", "review": review.model_dump(mode="json"), "requests": len(planned.requests)}
    save_world(location / "reader", intent, acceptance.world, result)
    return result


def execute(studio: Studio, job: dict[str, Any], *, harness_command: str | None,
            timeout: float) -> dict[str, Any]:
    from ..execseam import narrate_loop
    from .trials import evaluate_trial, unmeasured_artifact_outcomes

    spec = ProjectSpec.model_validate(studio.store.get(job["project"], job["revision"])["spec"])
    options = RunOptions.model_validate(job["options"])
    root = studio.path("foundry", job["id"])
    root.mkdir(parents=True, exist_ok=True)
    identity = {"schema": "worldloom.foundry/v1", "project": job["project"],
                "revision": job["revision"], "options": options.model_dump(mode="json"),
                "harness": digest(harness_command)}
    document(root / "run.json", identity)
    state: dict[str, Any] = {"status": "running", "stages": {}, "findings": []}

    def stage(name: str, status: str = "running", **details: Any) -> None:
        state["stage"] = name
        state["stages"][name] = {"status": status, **details}
        atomic_json(root / "progress.json", state)

    def blocked(name: str, findings: Any, **details: Any) -> dict[str, Any]:
        state.update(status="blocked", findings=findings)
        stage(name, "blocked", findings=findings, **details)
        return state

    def incomplete(name: str, report: Any) -> dict[str, Any]:
        if options.batch_limit is not None and report.batches < spec.max_batches:
            state.update(status="paused", findings=list(report.findings))
            stage(name, "paused", report=report.model_dump(mode="json"))
            return state
        return blocked(name, list(report.findings), report=report.model_dump(mode="json"))

    stage("requirements")
    construction_plan = compile_project(spec)
    document(root / "requirements.json", construction_plan.model_dump(mode="json"))
    if not construction_plan.accepted:
        return blocked("requirements", [f.model_dump(mode="json") for f in construction_plan.findings])
    if spec.narration_job is not None:
        return blocked("requirements", ["Foundry narrates the constructed evidence; clear the base-only narration selection before running"])
    if spec.calibration is None:
        return blocked("requirements", ["Declare a target cohort, noise variants, support and trial budgets"])
    calibration = spec.calibration
    if spec.split_by != "case" or not {"train", "test"} <= spec.split_weights.keys():
        return blocked("requirements", ["Foundry calibration needs case-isolated train and test splits"])
    stage("requirements", "complete", contract=construction_plan.model_dump(mode="json"))

    stage("construction")
    constructed, base_path = construct_company(studio, spec, construction_plan)
    document(root / "construction.json", constructed.report.model_dump(mode="json"))
    if not constructed.report.accepted:
        return blocked("construction", [f.model_dump(mode="json") for f in constructed.report.findings],
                       report=constructed.report.model_dump(mode="json"))
    world = constructed.world
    if world.artifact_intents and not world.artifact_irs:
        world = world.compile()
    world.validate().raise_if_failed()
    stage("construction", "complete", report=constructed.report.model_dump(mode="json"),
          company=world.company.name, seed=world.seed, facts=len(world.facts))
    if spec.retail_process is not None:
        from ..retail_replenishment import process_report
        state["stages"]["construction"]["process_evidence"] = process_report(world)

    stage("narration")
    authored_path = root / "authored"
    authored_intent = {"construction": world_digest(world), "harness": digest(harness_command)}
    authored = load_world(authored_path, authored_intent)
    if authored is None:
        rounds = 0
        if handshake.pending(world):
            if not harness_command:
                return blocked("narration", ["A coding harness is required to author pending sections"])
            result = narrate_loop(world, harness_command, max_rounds=options.max_rounds, timeout=timeout,
                                 model_id="foundry-author/" + digest(harness_command),
                                 exchange=Exchanges(root / "author-turns", harness_command, timeout))
            if not result.complete or result.world is None:
                return blocked("narration", ["Narration exhausted its acceptance round budget"],
                               outstanding={key: str(value) for key, value in result.outstanding.items()})
            world = result.world
            rounds = len(result.rounds)
        if world.artifact_irs:
            world = world.render("markdown")
        save_world(authored_path, authored_intent, world, {"rounds": rounds})
    else:
        # The construction replay restores the sequential generator state;
        # accepted prose and bytes come only from the authenticated checkpoint.
        world = replace(authored[0], _minter=world._minter)
    stage("narration", "complete", snapshot=world_digest(world))

    transforms = {case.id: partial(bind_query, construction_plan, case.id) for case in spec.use_cases}
    contracts = {case.id: digest(case.construction.model_dump(mode="json"))
                 for case in spec.use_cases if case.construction is not None}

    def compile_at(candidate: World, path: Path, world_path: Path,
                   assignments: dict[str, str] | None = None) -> Any:
        plan = studio.dataset_plan(job["project"], job["revision"], spec, world_path)
        plan = plan.model_copy(update={"generation_contracts": contracts, "split_assignments": assignments or {}})
        previous_batches = _read(path / "progress.json")["batches"] if (path / "progress.json").exists() else 0
        limit = previous_batches + options.batch_limit if options.batch_limit is not None else None
        return compile_dataset(plan, path, batch_limit=limit,
            builder=FrozenCompanyBuilder(candidate, seed=spec.seed, query_transforms=transforms,
                                         bind_cases=spec.retail_process is not None))

    stage("qualification")
    baseline_path = root / "baseline"
    baseline = compile_at(world, baseline_path, authored_path / "world")
    state["report"] = baseline.report.model_dump(mode="json")
    if not baseline.report.complete:
        return incomplete("qualification", baseline.report)
    rows = _rows(baseline_path)
    samples = independent_samples(rows)
    assignments = {digest([r["stratum"], r["query_id"]]): r["split"] for r in rows}
    document(root / "sample-plan.json", {"samples": samples, "splits": assignments})
    stage("qualification", "complete", report=state["report"], independent_samples=len(samples))

    # Each variant starts from the complete, same authored world. No arm can
    # consume another arm's IDs or accumulate its noise interventions.
    designs = {case.id: case.construction for case in spec.use_cases}
    variants: dict[str, dict[str, Any]] = {}
    stage("quality")
    for variant in calibration.variants:
        location = root / "variants" / digest(variant.model_dump(mode="json"))
        intent = {"baseline": world_digest(world), "variant": variant.model_dump(mode="json")}
        changed = load_world(location / "noise", intent)
        if changed is None:
            noisy = _noise_world(world, variant, ("markdown",) if world.artifact_irs else ())
            save_world(location / "noise", intent, noisy, {})
        else:
            noisy = changed[0]
        findings = []
        if not noisy.validate().ok:
            findings.append("world_validation_failed")
        for candidate in constructed.candidates:
            contract = next(c.spec for c in construction_plan.use_cases
                            if c.spec.id == candidate.plan.eval_spec_id)
            if not validate_candidate(candidate.plan, contract, noisy).accepted:
                findings.append("construction_requirement_failed:" + contract.id)
        dataset_path = location / "dataset"
        variant_run = compile_at(noisy, dataset_path, location / "noise" / "world", assignments)
        if not variant_run.report.complete and options.batch_limit is not None and variant_run.report.batches < spec.max_batches:
            return incomplete("quality", variant_run.report)
        if not variant_run.report.complete:
            findings.extend(variant_run.report.findings)
        variant_rows = _rows(dataset_path) if variant_run.report.complete else []
        lookup = {(r["stratum"], r["query_id"]): r for r in variant_rows}
        for row in rows:
            matched = lookup.get((row["stratum"], row["query_id"]))
            if matched is None or matched["evidence"] != row["evidence"]:
                findings.append("sealed_case_evidence_changed:" + row["query_id"])
        # Read actual accepted text independently. Only the public requests
        # leave this boundary; expected facts and targets stay in the checker.
        critical: set[str] = set()
        for path in sorted((dataset_path / "batches").glob("*/qualified")):
            corpus = load_exported_corpus(path)
            for query in corpus.queries:
                findings.extend(unmeasured_artifact_outcomes(query))
            for fixture in corpus.fixtures:
                critical.update(fixture.expected_fact_ids)
        reader_result = _review(noisy, location, critical, command=harness_command,
                                timeout=timeout, share=calibration.reader_share)
        if reader_result.get("review", {}).get("passed") is False or reader_result["status"] == "missing_prose_evidence":
            findings.append("reader_rejected")
        actual: dict[str, int] = {}
        for error in noisy.intentional_errors:
            actual[str(error.error_type)] = actual.get(str(error.error_type), 0) + 1
        variants[variant.name] = {"path": dataset_path, "world": world_digest(noisy), "rows": lookup,
            "quality": {"findings": sorted(set(findings)), "reader": reader_result,
                        "coverage": variant_run.report.model_dump(mode="json"),
                        "requested_noise": variant.budget, "actual_noise": actual}}
        stage("quality", "running", variants={name: v["quality"] for name, v in variants.items()})
    stage("quality", "complete", variants={name: v["quality"] for name, v in variants.items()})

    observations: list[CalibrationObservation] = []
    attempts: list[dict[str, Any]] = []

    def trial(name: str, row: dict[str, Any], split: Literal["train", "holdout"]) -> None:
        candidate = variants[name]
        match = candidate["rows"][(row["stratum"], row["query_id"])]
        trial_id = digest([identity, name, row["id"], split, candidate["world"]])
        outcome = evaluate_trial(candidate["path"] / match["qualification"], match["query_id"],
            root=root / "trials" / trial_id, harness_command=harness_command or "", timeout=timeout,
            max_turns=calibration.max_turns, trial_id=trial_id, world_digest=candidate["world"])
        observation = CalibrationObservation(cohort=calibration.cohort, trial_id=trial_id,
            eval_id=row["id"], corpus_digest=candidate["world"],
            evaluator_config_digest=digest({"harness": digest(harness_command), "max_turns": calibration.max_turns}),
            evaluator_kind="agent", features=features(calibration, designs[row["stratum"]], row["stratum"], name),
            passed=outcome.passed, split=split)
        observations.append(observation)
        attempts.append({"variant": name, "case": row["stratum"], "split": split,
                         "observation": observation.model_dump(mode="json"), "outcome": outcome.model_dump(mode="json")})
        atomic_json(root / "observations.json", attempts)
        stage("trials", "running", training=sum(a["split"] == "train" for a in attempts),
              holdout=sum(a["split"] == "holdout" for a in attempts))

    stage("trials")
    training = [r for r in samples if r["split"] == "train"]
    # Deterministic rounds over evidence cases, then variants. Budget is total
    # external trials, not a per-company reminting or a hidden retry budget.
    count = 0
    for row in training:
        for name in sorted(variants):
            if count >= calibration.max_training_attempts:
                break
            if not variants[name]["quality"]["findings"]:
                trial(name, row, "train")
                count += 1
    summary = {name: estimates(calibration, designs, observations, variant=name) for name in variants}
    chosen = select(calibration, summary)
    selection: dict[str, Any] = {"variant": chosen, "training": {name: {case: e.model_dump(mode="json") for case, e in values.items()}
                                                 for name, values in summary.items()},
                 "observations_digest": digest(attempts)}
    document(root / "selection.json", selection)
    stage("selection", "complete", **selection)
    holdout_values = {}
    if chosen is not None:
        for row in [r for r in samples if r["split"] == "test"][:calibration.max_holdout_attempts]:
            trial(chosen, row, "holdout")
        holdout_values = estimates(calibration, designs, observations, variant=chosen, split="holdout")
    state["calibration"] = {"status": "supported" if chosen and supported(calibration, holdout_values) else "target_unmet",
        "selected_variant": chosen, "variants": [{"name": name, "quality": v["quality"],
            "training": selection["training"][name],
            "holdout": {case: e.model_dump(mode="json") for case, e in holdout_values.items()} if name == chosen else {}}
            for name, v in sorted(variants.items())]}
    stage("trials", "complete", training=count, holdout=sum(a["split"] == "holdout" for a in attempts))
    if chosen is None or not supported(calibration, holdout_values):
        return blocked("freeze", ["No variant has sufficient training and holdout support inside the target interval"])

    stage("freeze")
    selected = variants[chosen]
    if not verify_dataset(selected["path"]).complete:
        raise ValueError("selected dataset became incomplete")
    destination = studio.path("datasets", digest([job["project"], job["revision"], job["id"]]))
    frozen = {"variant": chosen, "world_digest": selected["world"],
              "dataset": destination.name, "files": _files(selected["path"]),
              "selection_digest": digest(selection), "observations_digest": digest(attempts),
              "base_snapshot": base_path.name}
    if destination.exists():
        verify_dataset(destination)
        if _files(destination) != frozen["files"]:
            raise ValueError("frozen dataset changed after selection")
    else:
        pending = destination.with_name(destination.name + ".pending")
        if pending.exists():
            shutil.rmtree(pending)
        shutil.copytree(selected["path"], pending)
        pending.rename(destination)
    document(root / "frozen.json", frozen)
    verify_dataset(destination)
    state.update(status="complete", frozen_dataset=destination.name, snapshot=selected["world"])
    stage("freeze", "complete", **frozen)
    return state
