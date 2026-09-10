"""Company-scoped native files, public tasks and privately graded target receipts.

This lane measures explicit native contracts. It does not infer a noise band or
calibration from a successful task, and its exec seam is a trusted subprocess,
not an operating-system confidentiality sandbox.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, ValidationError, model_validator

from ..evals.calibration import TrialOutcome, world_digest
from ..evals.dataset import _files, _read
from ..models import Model
from ..native_corpus import render_native_corpus
from ..native_reference import qualify_native_task
from ..native_tasks import (
    MAX_FILE_BYTES,
    NativeFile,
    NativeSubmission,
    NativeTask,
    grade_native_task,
    public_contract,
)
from ..providers import digest
from ..world import World
from .checkpoints import Exchanges, atomic_json, document
from .models import ProjectSpec
from .native_calibration import seal, summarize
from .native_noise import interventions

if TYPE_CHECKING:
    from .service import Studio


class NativeOutputFile(Model):
    artifact_id: str
    format: Literal["docx", "pptx", "xlsx", "pdf"]
    path: str = Field(min_length=1)
    source_sha256: str | None = None

    @model_validator(mode="after")
    def safe_path(self) -> NativeOutputFile:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.path:
            raise ValueError("native output path must remain inside the task output directory")
        return self


class NativeReply(Model):
    request_id: str
    submission: NativeSubmission = Field(default_factory=NativeSubmission)
    output_files: tuple[NativeOutputFile, ...] = ()


def _submission(reply: NativeReply, directory: Path) -> NativeSubmission:
    files = list(reply.submission.files)
    for item in reply.output_files:
        path = directory / item.path
        if directory.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != directory.parent):
            raise ValueError("native outputs cannot contain symlinks")
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("native output must be a file inside the task output directory")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("native output exceeds the file size limit")
        payload = path.read_bytes()
        if len(payload) > MAX_FILE_BYTES:
            raise ValueError("native output exceeds the file size limit")
        files.append(NativeFile(artifact_id=item.artifact_id, format=item.format,
                               content_base64=base64.b64encode(payload).decode("ascii"),
                               source_sha256=item.source_sha256))
    return NativeSubmission(answers=reply.submission.answers, files=tuple(files))


def _bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("native corpus cannot contain symlinks")
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("native file changed after generation")
        return
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_bytes(payload)
    pending.replace(path)


def _components(tasks: tuple[NativeTask, ...], evidence: dict[str, set[str]]) -> dict[str, str]:
    """Shared originals and shared authored evidence must never become holdouts."""
    parents = {task.id: task.id for task in tasks}

    def find(key: str) -> str:
        while parents[key] != key:
            key = parents[key]
        return key

    owners: dict[str, str] = {}
    for task in tasks:
        if not task.inputs:
            # Without source provenance, differently named creation prompts
            # cannot establish independent company evidence. Keep them together.
            key = "ungrounded-create:" + task.use_case_id
            if key in owners:
                left, right = sorted((find(task.id), find(owners[key])))
                parents[right] = left
            else:
                owners[key] = task.id
        for item in task.inputs:
            keys = {"artifact:" + item.artifact_id} | evidence[item.artifact_id]
            for key in sorted(keys):
                if key in owners:
                    left, right = sorted((find(task.id), find(owners[key])))
                    parents[right] = left
                else:
                    owners[key] = task.id
    groups: dict[str, list[str]] = {}
    for task in tasks:
        groups.setdefault(find(task.id), []).append(task.id)
    return {task_id: digest(sorted(members)) for members in groups.values() for task_id in members}


def source_world(studio: Studio, spec: ProjectSpec, project: str) -> tuple[World, Path]:
    world, snapshot = studio.snapshot(spec)
    if spec.narration_job:
        narration = studio.store.job(spec.narration_job)
        target = studio.path("narrated", spec.narration_job)
        if (narration["project"] != project or narration["status"] != "complete"
                or narration["options"]["operation"] != "narrate"
                or narration["result"].get("snapshot") != snapshot.name):
            raise ValueError("selected narration does not belong to this company snapshot")
        receipt = _read(target / "receipt.json")
        if receipt.get("snapshot") != snapshot.name or receipt.get("files") != _files(target):
            raise ValueError("selected narration changed after acceptance")
        world = World.load(target / "world")
    return world, snapshot


def execute(studio: Studio, job: dict[str, Any], *, harness_command: str | None,
            timeout: float) -> dict[str, Any]:
    spec = ProjectSpec.model_validate(studio.store.get(job["project"], job["revision"])["spec"])
    if not spec.native_corpus or not spec.native_tasks:
        raise ValueError("native run requires corpus plans and native tasks")
    if len({plan.artifact_id for plan in spec.native_corpus}) != len(spec.native_corpus):
        raise ValueError("native corpus artifact ids must be unique")
    if len({task.id for task in spec.native_tasks}) != len(spec.native_tasks):
        raise ValueError("native task ids must be unique")
    world, snapshot = source_world(studio, spec, job["project"])
    root = studio.path("native", job["id"])
    root.mkdir(parents=True, exist_ok=True)
    if (root / "manifest.json").exists():
        if _read(root / "manifest.json").get("files") != _files(root):
            raise ValueError("native run changed after checkpoint")
    identity = {"schema": "worldloom.native-run/v1", "project": job["project"],
                "revision": job["revision"], "world_digest": world_digest(world),
                "harness": digest(harness_command), "options": job["options"]}
    document(root / "run.json", identity)
    inputs: dict[str, bytes] = {}
    metadata: dict[str, dict[str, Any]] = {}
    evidence: dict[str, set[str]] = {}
    for plan in spec.native_corpus:
        rendered = render_native_corpus(world, plan)
        path = "inputs/" + digest(plan.artifact_id) + "." + plan.format
        _bytes(root / path, rendered.payload)
        inputs[plan.artifact_id] = rendered.payload
        metadata[plan.artifact_id] = {**rendered.manifest.model_dump(mode="json"), "path": path}
        evidence[plan.artifact_id] = {
            "section:" + digest([item.source_artifact_id, item.section_index])
            for item in rendered.manifest.evidence
        } | {"fact:" + fact_id for item in rendered.manifest.evidence for fact_id in item.fact_ids}
    tasks: list[NativeTask] = []
    for task in spec.native_tasks:
        bound = []
        for item in task.inputs:
            if item.artifact_id not in metadata:
                raise ValueError("native task names an unknown corpus artifact: " + item.artifact_id)
            actual = metadata[item.artifact_id]
            if item.format != actual["format"]:
                raise ValueError("native task input format does not match generated bytes")
            if item.sha256 and item.sha256 != actual["sha256"]:
                raise ValueError("native task input checksum does not match generated bytes")
            bound.append(item.model_copy(update={"sha256": actual["sha256"], "path": actual["path"]}))
        tasks.append(NativeTask.model_validate({**task.model_dump(mode="json"),
                     "inputs": [item.model_dump(mode="json") for item in bound]}))
    components = _components(tuple(tasks), evidence)
    sealed = seal(spec.native_calibration, tasks, components) if spec.native_calibration else None
    if sealed:
        document(root / "calibration-seal.json", sealed)
    noise = (interventions(tasks, components, spec.native_calibration.noise_variants, sealed)
             if sealed and spec.native_calibration and spec.native_calibration.noise_variants else None)
    if noise:
        document(root / "noise-seal.json", noise)
    splits = sealed["splits"] if sealed else {task.id: "unassigned" for task in tasks}
    public = [{**public_contract(task), "evidence_component": components[task.id], "split": splits[task.id]}
              for task in tasks]
    # Oracle export supports audit and replay but its path never enters a target
    # request. An untrusted coding harness still requires host-level isolation.
    document(root / "corpus.json", {"world_digest": identity["world_digest"], "artifacts": metadata})
    document(root / "queryset.json", public)
    document(root / "oracles.json", [task.model_dump(mode="json") for task in tasks])
    qualification: list[dict[str, Any]] = []
    for task in tasks:
        reference_grade = qualify_native_task(task, {item.artifact_id: inputs[item.artifact_id] for item in task.inputs})
        proof = {"task_id": task.id, "task_digest": digest(task.model_dump(mode="json")),
                 "grade": reference_grade.model_dump(mode="json")}
        qualification.append(proof)
    document(root / "qualification.json", qualification)
    if any(not proof["grade"]["passed"] for proof in qualification):
        raise ValueError("native reference qualification failed; inspect qualification.json before running a target")
    outcomes: list[dict[str, Any]] = []
    exchange = Exchanges(root / "exchanges", harness_command, timeout)
    calibration: dict[str, Any] = {"mode": "fixed_corpus", "configured": sealed is not None}
    feasible = (sealed is None or sealed["feasible"]) and (noise is None or noise["feasible"])
    if sealed:
        calibration["support"] = sealed["support"]
    if noise:
        calibration.update(mode="grounded_distractor_files", noise=noise, candidates=[], selected_variant=None)

    def observe(phase: str, variant: str | None) -> list[dict[str, Any]]:
        selected = [task for task in tasks if task.id in sealed["samples"][phase]] if sealed else tasks
        if sealed:
            selected.sort(key=lambda task: sealed["samples"][phase].index(task.id))
        rows: list[dict[str, Any]] = []
        for task in selected:
            distractors = noise["candidates"][variant][task.id] if noise and variant else []
            intervention = {"variant": variant, "distractor_artifacts": distractors} if noise else None
            request_id = digest([identity, task.model_dump(mode="json")] + ([intervention] if noise else []))
            trial_key = digest([task.id, variant]) if noise else digest(task.id)
            output_directory = root / "outputs" / trial_key
            output_directory.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {"schema": "worldloom.native-trial/v1", "request_id": request_id,
                       "task": public_contract(task), "output_directory": str(output_directory.resolve()), "input_files": {
                           item.artifact_id: str((root / item.path).resolve()) for item in task.inputs},
                       "response_schema": NativeReply.model_json_schema()}
            # These are authentic related company files, not fabricated claims.
            # The explicit task contract still identifies its required originals.
            for artifact in distractors:
                payload["input_files"][artifact] = str((root / metadata[artifact]["path"]).resolve())
            reply = exchange(payload)
            for artifact in metadata.values():
                input_path = root / artifact["path"]
                if input_path.is_symlink() or hashlib.sha256(input_path.read_bytes()).hexdigest() != artifact["sha256"]:
                    raise ValueError("target modified an immutable native input")
            try:
                proposed = NativeReply.model_validate(reply.document)
                if proposed.request_id != request_id:
                    raise ValueError("native reply request id mismatch")
                grade = grade_native_task(task, {item.artifact_id: inputs[item.artifact_id] for item in task.inputs},
                                          _submission(proposed, output_directory))
                outcome = TrialOutcome(passed=grade.passed, details=grade.model_dump(mode="json"))
            except (ValidationError, ValueError) as error:
                outcome = TrialOutcome(passed=False, details={"findings": ["invalid_native_submission"],
                                                               "detail": str(error)[:2000]})
            value = {"task_id": task.id, "trial_id": request_id, "evidence_component": components[task.id],
                     "split": splits[task.id], **outcome.model_dump(mode="json")}
            if noise:
                value["intervention"] = intervention
            document(root / "trials" / (trial_key + ".json"), value)
            rows.append(value)
        outcomes.extend(rows)
        return rows

    if harness_command and feasible:
        if sealed and spec.native_calibration:
            variants = [variant.name for variant in spec.native_calibration.noise_variants] if noise else [None]
            for variant in variants:
                training = observe("train", variant)
                summary = summarize(spec.native_calibration, tasks, training, sealed,
                                    corpus_digest=digest(metadata), evaluator_digest=digest([harness_command, timeout, variant]),
                                    split="train")
                if noise:
                    candidate = {"variant": variant, **summary}
                    calibration["candidates"].append(candidate)
                    document(root / "candidates" / (str(variant) + ".json"), candidate)
                calibration["training"] = summary
                if summary["accepted"]:
                    if noise:
                        calibration["selected_variant"] = variant
                    # Commit selection and its training evidence before any heldout call.
                    document(root / "calibration-training.json", summary)
                    document(root / "calibration-selection.json", {"variant": variant,
                             "training_digest": digest(summary), "noise_digest": digest(noise)})
                    holdout = observe("holdout", variant)
                    calibration["holdout"] = summarize(spec.native_calibration, tasks, training + holdout, sealed,
                        corpus_digest=digest(metadata), evaluator_digest=digest([harness_command, timeout, variant]),
                        split="holdout")
                    document(root / "calibration-holdout.json", calibration["holdout"])
                    break
            if "holdout" not in calibration:
                document(root / "calibration-training.json", calibration["training"])
        else:
            observe("unassigned", None)
    calibrated = bool(calibration.get("training", {}).get("accepted") and
                      calibration.get("holdout", {}).get("accepted"))
    calibration["accepted"] = calibrated
    calibration["findings"] = ([] if calibrated or not sealed else sealed["findings"] + (noise["findings"] if noise else []) if not feasible else
        ["target_required" if not harness_command else "native_difficulty_band_not_supported"])
    document(root / "calibration.json", calibration)
    # Bind all public and private exports after trials, catching deleted receipts
    # and changed oracles on completed replay without making another agent call.
    result = {"schema": "worldloom.native-run/v1", "status": ("blocked" if not feasible or (sealed and harness_command and not calibrated) else
                         "complete" if harness_command else "prepared"),
              "native": root.name, "directory": str(root), "snapshot": snapshot.name,
              "queryset": str(root / "queryset.json"), "corpus": str(root / "corpus.json"),
              "artifacts": len(metadata), "corpus_artifacts": metadata, "tasks": len(tasks), "observed_trials": len(outcomes),
              "passed_trials": sum(item["passed"] for item in outcomes), "outcomes": outcomes,
              "evidence_components": len(set(components.values())), "calibrated": calibrated,
              "calibration": calibration,
              "noise_calibrated": bool(calibrated and noise and spec.native_calibration and
                  any(v.name == calibration["selected_variant"] and v.distractor_files > 0
                      for v in spec.native_calibration.noise_variants)), "split": "sealed" if sealed else "unassigned"}
    document(root / "result.json", result)
    manifest = {"identity": identity, "files": _files(root)}
    if (root / "manifest.json").exists():
        if _read(root / "manifest.json") != manifest:
            raise ValueError("native run changed after checkpoint")
    else:
        atomic_json(root / "manifest.json", manifest)
    return result


__all__ = ["NativeOutputFile", "NativeReply", "execute"]
