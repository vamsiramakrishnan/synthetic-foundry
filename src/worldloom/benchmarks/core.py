"""One native benchmark contract for SDKs, file exchanges and harness runners.

The public directory is the complete target corpus. The private directory holds
the oracle and canonical source needed to independently validate its lineage.
Neither directory separation nor a checksum is an operating-system sandbox.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from .. import corpus
from ..ids import content_key
from ..models import Model
from ..native_corpus import NativeCorpusManifest, NativeCorpusResult
from ..native_query_planning import NativeWorkload, NativeWorkloadPlan
from ..native_tasks import (
    MAX_FILE_BYTES,
    NativeGrade,
    NativeSubmission,
    public_contract,
)
from ..synthesis.compiler import digest

if TYPE_CHECKING:
    from ..evalrun.qualification import QualificationPolicy
    from ..world import World
    from .coverage import BenchmarkAssessment

PUBLIC_WORKLOAD_SCHEMA = "worldloom.native-workload.public/v1"
BENCHMARK_SCHEMA = "worldloom.native-benchmark/v1"
_METADATA_LIMIT = 128 * 1024 * 1024


class NativeTaskReply(Model):
    task_id: str = Field(min_length=1)
    submission: NativeSubmission


class NativeWorkloadReplies(Model):
    replies: tuple[NativeTaskReply, ...]


class NativeWorkloadGrade(Model):
    passed: bool
    grades: dict[str, NativeGrade]


class BenchmarkFile(Model):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)


class NativeBenchmarkManifest(Model):
    schema_version: Literal["worldloom.native-benchmark/v1"] = "worldloom.native-benchmark/v1"
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    files: tuple[BenchmarkFile, ...]


class _NativeSourceManifests(Model):
    manifests: tuple[NativeCorpusManifest, ...]


def _file(root: Path, relative: str, *, limit: int = _METADATA_LIMIT) -> Path:
    path = PurePosixPath(relative)
    if (path.is_absolute() or not path.parts or ".." in path.parts or "\\" in relative
            or path.as_posix() != relative):
        raise ValueError("native benchmark path must remain inside the package")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("native benchmark symbolic links are not permitted")
    if not current.resolve().is_relative_to(root.resolve()) or not current.is_file() or current.stat().st_size > limit:
        raise ValueError(f"native input is missing, outside the package, or oversized: {relative}")
    return current


def _document(root: Path, relative: str) -> Any:
    return corpus.read_json(_file(root, relative))


def _public(workload: NativeWorkload) -> dict[str, Any]:
    return {"schema": PUBLIC_WORKLOAD_SCHEMA, "tasks": [public_contract(task) for task in workload.tasks]}


def _input_paths(workload: NativeWorkload, rendered: Mapping[str, NativeCorpusResult] | None) -> dict[str, str]:
    formats = {item.artifact_id: item.format for task in workload.tasks for item in task.inputs}
    if rendered is not None:
        formats.update({key: value.manifest.format for key, value in rendered.items()})
    return {key: "inputs/" + content_key("native-evals/input/v1", key) + "." + format
            for key, format in sorted(formats.items())}


def _relocate(workload: NativeWorkload, paths: Mapping[str, str]) -> NativeWorkload:
    return workload.model_copy(update={"tasks": tuple(task.model_copy(update={
        "inputs": tuple(item.model_copy(update={"path": paths[item.artifact_id]}) for item in task.inputs)
    }) for task in workload.tasks)})


def _load_inputs(workload: NativeWorkload, target: Path) -> dict[str, bytes]:
    inputs: dict[str, bytes] = {}
    identities: dict[str, tuple[str, str, str]] = {}
    for task in workload.tasks:
        for item in task.inputs:
            identity = (item.format, item.path, item.sha256)
            if item.artifact_id in identities:
                if identities[item.artifact_id] != identity:
                    raise ValueError("input identity differs between tasks")
                continue
            payload = _file(target, item.path, limit=MAX_FILE_BYTES).read_bytes()
            if hashlib.sha256(payload).hexdigest() != item.sha256:
                raise ValueError(f"native input checksum changed: {item.artifact_id}")
            identities[item.artifact_id] = identity
            inputs[item.artifact_id] = payload
    return inputs


@dataclass(frozen=True)
class NativeBenchmark:
    """Validated native tasks and byte-bound inputs, with optional source lineage.

    Build from a verified scale corpus, then export once. Hand only
    ``target_directory`` to a target. For independent train/holdout execution,
    runners stage only each task's declared inputs, not the whole public corpus.
    Legacy exchanges remain readable but cannot supply missing source lineage.
    """

    workload: NativeWorkload
    inputs: Mapping[str, bytes]
    world: World | None = None
    rendered: Mapping[str, NativeCorpusResult] | None = None
    directory: Path | None = None
    layout: Literal["separated", "legacy"] = "separated"

    def __post_init__(self) -> None:
        # Copy caller-owned containers. A harness must not change served bytes
        # by mutating the dictionary it originally passed into the SDK.
        object.__setattr__(self, "inputs", MappingProxyType(dict(sorted(self.inputs.items()))))
        if self.rendered is not None:
            object.__setattr__(self, "rendered", MappingProxyType(dict(sorted(self.rendered.items()))))
        self._validate_inputs()

    def _validate_inputs(self) -> None:
        from ..native_artifacts import inspect_artifact

        NativeWorkload.model_validate(self.workload.model_dump(mode="json"))
        tasks = self.workload.tasks
        if not tasks or len({task.id for task in tasks}) != len(tasks):
            raise ValueError("native workload requires distinct, nonempty tasks")
        identities: dict[str, tuple[str, str, str]] = {}
        paths: dict[str, str] = {}
        for task in tasks:
            for item in task.inputs:
                identity = (item.format, item.path, item.sha256)
                if item.artifact_id in identities and identities[item.artifact_id] != identity:
                    raise ValueError("input identity differs between tasks")
                if item.path in paths and paths[item.path] != item.artifact_id:
                    raise ValueError("native input path is shared by different artifact identities")
                if item.artifact_id in identities:
                    continue
                payload = self.inputs.get(item.artifact_id)
                if payload is None or len(payload) > MAX_FILE_BYTES:
                    raise ValueError(f"native input is missing or oversized: {item.artifact_id}")
                if inspect_artifact(payload, item.format).sha256 != item.sha256:
                    raise ValueError(f"native input checksum changed: {item.artifact_id}")
                identities[item.artifact_id] = identity
                paths[item.path] = item.artifact_id
        if (self.world is None) != (self.rendered is None):
            raise ValueError("native benchmark lineage requires both world and rendered manifests")
        if self.rendered is not None:
            if set(self.rendered) != set(self.inputs):
                raise ValueError("native benchmark manifests differ from the supplied corpus")
            for key, result in self.rendered.items():
                if (result.manifest.artifact_id != key or result.payload != self.inputs[key]
                        or len(result.payload) > MAX_FILE_BYTES
                        or len(result.payload) != result.manifest.file_size_bytes
                        or hashlib.sha256(result.payload).hexdigest() != result.manifest.sha256):
                    raise ValueError(f"native benchmark source bytes differ from their manifest: {key}")
        elif set(self.inputs) != set(identities):
            raise ValueError("native benchmark has inputs without task or source manifests")

    @classmethod
    def build(cls, world: World, scale_directory: Path, plan: NativeWorkloadPlan) -> NativeBenchmark:
        """Verify physical source projections, plan business tasks, qualify bytes."""
        from ..corpus_scale import verify_corpus_scale
        scale_directory = Path(scale_directory)
        manifest = verify_corpus_scale(world, scale_directory)
        paths = {item.sha256: item.path for item in manifest.files if item.kind == "native"}
        rendered = {item.artifact_id: NativeCorpusResult(
            payload=(scale_directory / paths[item.sha256]).read_bytes(), manifest=item) for item in manifest.native}
        return cls.from_rendered(world, rendered, plan)

    @classmethod
    def from_rendered(cls, world: World, rendered: Mapping[str, NativeCorpusResult],
                      plan: NativeWorkloadPlan) -> NativeBenchmark:
        """Compile already-rendered native sources through the same provenance gate."""
        from ..native_query_planning import _inventory, plan_native_workload

        # All exported files are part of the corpus, including formats the
        # current task plan does not select. Their lineage still needs proof.
        _inventory(world, rendered, NativeWorkloadPlan(use_case_id="benchmark-provenance",
            objective="Validate all exported native source provenance."))
        workload = plan_native_workload(world, rendered, plan)
        if not workload.tasks:
            raise ValueError("native workload has no executable tasks; inspect source scope and discovery coverage")
        workload = _relocate(workload, _input_paths(workload, rendered))
        return cls(workload, {key: result.payload for key, result in rendered.items()}, world, rendered)

    @property
    def source_digest(self) -> str | None:
        from ..corpus_scale import _world_digest

        return _world_digest(self.world) if self.world is not None else None

    @property
    def digest(self) -> str:
        """Identity of contracts, actual inputs and canonical source lineage."""
        return digest({"schema": BENCHMARK_SCHEMA, "workload": self.workload.model_dump(mode="json"),
            "inputs": {key: hashlib.sha256(value).hexdigest() for key, value in sorted(self.inputs.items())},
            "source": self.source_digest,
            "manifests": None if self.rendered is None else {
                key: value.manifest.model_dump(mode="json") for key, value in sorted(self.rendered.items())}})

    @property
    def target_directory(self) -> Path:
        if self.directory is None:
            raise ValueError("export the native benchmark before requesting its target directory")
        if self.layout == "legacy":
            raise ValueError("legacy exchange mixes evaluator files with target inputs; export a separated benchmark first")
        return self.directory / "public"

    @property
    def public_tasks(self) -> dict[str, Any]:
        return _public(self.workload)

    def validate(self) -> None:
        """Recheck inputs and reconstruct the planner's canonical task contracts."""
        from ..native_query_planning import _inventory, plan_native_workload

        self._validate_inputs()
        if self.world is not None and self.rendered is not None:
            _inventory(self.world, self.rendered, NativeWorkloadPlan(use_case_id="benchmark-provenance",
                objective="Validate all exported native source provenance."))
            expected = plan_native_workload(self.world, self.rendered, self.workload.plan)
            expected = _relocate(expected, _input_paths(expected, self.rendered))
            if self.workload != expected:
                raise ValueError("native benchmark oracle differs from its canonical source and workload plan")

    def qualify(self) -> NativeWorkloadGrade:
        """Independently recheck task satisfiability against actual input bytes."""
        from ..native_reference import qualify_native_task

        self.validate()
        grades = {task.id: qualify_native_task(task, self.inputs) for task in self.workload.tasks}
        return NativeWorkloadGrade(passed=all(grade.passed for grade in grades.values()), grades=grades)

    def grade(self, replies: NativeWorkloadReplies | Mapping[str, NativeSubmission]) -> NativeWorkloadGrade:
        """Require one actual submission per task; independently grade content."""
        from ..native_tasks import grade_native_task

        self.validate()
        if isinstance(replies, NativeWorkloadReplies):
            by_id = {reply.task_id: reply.submission for reply in replies.replies}
            duplicate = len(by_id) != len(replies.replies)
        else:
            by_id = dict(replies)
            duplicate = False
        if duplicate or set(by_id) != {task.id for task in self.workload.tasks}:
            raise ValueError("reply task ids must cover the workload exactly once")
        grades = {task.id: grade_native_task(task, self.inputs, by_id[task.id]) for task in self.workload.tasks}
        return NativeWorkloadGrade(passed=all(grade.passed for grade in grades.values()), grades=grades)

    def assess(self, *, namespace: str | None = None, qualification_policy: QualificationPolicy | None = None,
               training_task_ids: Sequence[str] | None = None, heldout_task_ids: Sequence[str] | None = None,
               repeats: int | None = None, heldout: NativeBenchmark | None = None) -> BenchmarkAssessment:
        """Explain delivered coverage and independent promotion prerequisites."""
        from .coverage import NativeAssessmentSource, assess_native_benchmark

        self.validate()
        if self.world is None or self.rendered is None:
            raise ValueError("native benchmark source lineage unavailable; rebuild from the original world and scale corpus")
        origin = namespace if namespace is not None else self.world.company.id
        holdout_source = None
        if heldout is not None:
            heldout.validate()
            if heldout.world is None or heldout.rendered is None:
                raise ValueError("heldout native benchmark source lineage unavailable; rebuild from the original source")
            if heldout.world.company.id != self.world.company.id:
                raise ValueError("native benchmark holdout must describe the same company origin")
            holdout_source = NativeAssessmentSource(heldout.world, heldout.rendered, heldout.workload, origin)
        return assess_native_benchmark(self.world, self.rendered, self.workload,
            namespace=origin,
            qualification_policy=qualification_policy, training_task_ids=training_task_ids,
            heldout_task_ids=heldout_task_ids, repeats=repeats, heldout=holdout_source)

    def export(self, destination: Path, *, resume: bool = False) -> NativeBenchmark:
        """Atomically export a content-bound package with a target-only folder."""
        return self._export(Path(destination), resume=resume, legacy=False)

    def export_legacy(self, destination: Path, *, resume: bool = False) -> NativeBenchmark:
        """Preserve the historical native-evals exchange layout for existing clients."""
        return self._export(Path(destination), resume=resume, legacy=True)

    def _export(self, destination: Path, *, resume: bool, legacy: bool) -> NativeBenchmark:
        self.validate()
        paths = _input_paths(self.workload, self.rendered)
        workload = _relocate(self.workload, paths)
        expected = replace(self, workload=workload, directory=None)
        if destination.is_symlink():
            raise ValueError("native benchmark root must not be a symbolic link")
        if destination.exists():
            if not resume:
                raise ValueError("native exchange destination already exists")
            loaded = self.load(destination)
            if legacy:
                matches = loaded.layout == "legacy" and loaded.workload == workload and all(
                    loaded.inputs[key] == expected.inputs[key] for key in loaded.inputs)
            else:
                matches = loaded.layout == "separated" and loaded.digest == expected.digest
            if not matches:
                raise ValueError("native benchmark resume mismatch: contracts, inputs or source lineage changed")
            return loaded
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock = destination.parent / f".{destination.name}.native-benchmark.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise ValueError("native benchmark destination is locked") from error
        try:
            os.close(descriptor)
            with TemporaryDirectory(prefix=".native-benchmark-", dir=destination.parent) as temporary:
                stage = Path(temporary) / "package"
                target = stage if legacy else stage / "public"
                private = stage if legacy else stage / "private"
                (target / "inputs").mkdir(parents=True)
                private.mkdir(parents=True, exist_ok=True)
                used = {item.artifact_id for task in workload.tasks for item in task.inputs}
                for key in sorted(used if legacy else self.inputs):
                    (target / paths[key]).write_bytes(self.inputs[key])
                corpus.write_json(private / "oracle.json", workload.model_dump(mode="json"))
                corpus.write_json(target / "public-tasks.json", _public(workload))
                if not legacy:
                    if self.world is not None and self.rendered is not None:
                        # Source lineage needs canonical metadata, not copies of
                        # every unrelated rendered artifact from the source tree.
                        replace(self.world, root=None, _rendered=()).export(private / "source")
                        corpus.write_json(private / "native-manifests.json", {"manifests": [
                            value.manifest.model_dump(mode="json") for _, value in sorted(self.rendered.items())]})
                    files = tuple(BenchmarkFile(path=path.relative_to(stage).as_posix(),
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size)
                        for path in sorted(stage.rglob("*")) if path.is_file())
                    manifest = NativeBenchmarkManifest(digest=expected.digest, source_digest=expected.source_digest, files=files)
                    corpus.write_json(stage / "benchmark.json", manifest.model_dump(mode="json"))
                # Refuse a race with an external writer, including a dangling
                # symlink. The sidecar serializes cooperating SDK exporters.
                if destination.exists() or destination.is_symlink():
                    raise ValueError("native exchange destination already exists")
                self.load(stage)
                stage.rename(destination)
        finally:
            lock.unlink()
        return self.load(destination)

    @classmethod
    def load(cls, directory: Path) -> NativeBenchmark:
        """Load separated v1 packages or historical native-evals exchanges."""
        from ..world import World

        directory = Path(directory)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("native benchmark root must be a real directory")
        if not (directory / "benchmark.json").exists():
            workload = NativeWorkload.model_validate(_document(directory, "oracle.json"))
            if _document(directory, "public-tasks.json") != _public(workload):
                raise ValueError("public native tasks differ from the evaluator's task contract")
            return cls(workload, _load_inputs(workload, directory), directory=directory, layout="legacy")
        manifest = NativeBenchmarkManifest.model_validate(_document(directory, "benchmark.json"))
        expected = {"benchmark.json", *(item.path for item in manifest.files)}
        paths = tuple(directory.rglob("*"))
        actual = {path.relative_to(directory).as_posix() for path in paths if path.is_file()}
        if (actual != expected or len(expected) != len(manifest.files) + 1
                or any(path.is_symlink() for path in paths)):
            raise ValueError("native benchmark file set contains missing, additional, duplicate or symbolic-link files")
        for item in manifest.files:
            path = _file(directory, item.path)
            if path.stat().st_size != item.size_bytes or hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256:
                raise ValueError(f"native benchmark checksum changed: {item.path}")
        workload = NativeWorkload.model_validate(_document(directory, "private/oracle.json"))
        if _document(directory, "public/public-tasks.json") != _public(workload):
            raise ValueError("public native tasks differ from the evaluator's task contract")
        inputs = _load_inputs(workload, directory / "public")
        world = None
        rendered = None
        if manifest.source_digest is not None:
            world = World.load(directory / "private" / "source")
            manifests = _NativeSourceManifests.model_validate(
                _document(directory, "private/native-manifests.json")).manifests
            if len({item.artifact_id for item in manifests}) != len(manifests):
                raise ValueError("native benchmark source manifests must be distinct")
            rendered = {}
            for native in manifests:
                relative = "inputs/" + content_key("native-evals/input/v1", native.artifact_id) + "." + native.format
                payload = _file(directory / "public", relative, limit=MAX_FILE_BYTES).read_bytes()
                inputs[native.artifact_id] = payload
                rendered[native.artifact_id] = NativeCorpusResult(payload=payload, manifest=native)
        result = cls(workload, inputs, world, rendered, directory=directory)
        allowed_public = {"public/public-tasks.json", *(
            "public/" + path for path in _input_paths(workload, rendered).values())}
        if {item.path for item in manifest.files if item.path.startswith("public/")} != allowed_public:
            raise ValueError("native benchmark public directory contains files outside the target contract")
        allowed_private = {"private/oracle.json"}
        if manifest.source_digest is not None:
            allowed_private.add("private/native-manifests.json")
            allowed_private.update(item.path for item in manifest.files if item.path.startswith("private/source/"))
        if {item.path for item in manifest.files} != allowed_public | allowed_private:
            raise ValueError("native benchmark package contains files outside its versioned layout")
        if result.source_digest != manifest.source_digest or result.digest != manifest.digest:
            raise ValueError("native benchmark identity differs from its contracts, inputs or canonical source")
        result.validate()
        return result


__all__ = ["BENCHMARK_SCHEMA", "PUBLIC_WORKLOAD_SCHEMA", "BenchmarkFile", "NativeBenchmarkManifest",
    "NativeBenchmark", "NativeTaskReply", "NativeWorkloadReplies", "NativeWorkloadGrade"]
