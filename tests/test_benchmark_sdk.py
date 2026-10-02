"""The stable SDK binds target files, task contracts and canonical provenance."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from worldloom.benchmarks import (
    NativeBenchmark,
    NativeTaskReply,
    NativeWorkloadPlan,
    NativeWorkloadReplies,
)
from worldloom.corpus import write_json
from worldloom.corpus_scale import (
    CorpusScaleProfile,
    export_corpus_scale,
    plan_corpus_scale,
)
from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Company,
    Quantity,
)
from worldloom.native_corpus import (
    NativeContent,
    NativeCorpusPlan,
    render_native_corpus,
)
from worldloom.native_reference import reference_submission
from worldloom.seams import seam_manifest
from worldloom.synthesis import Simulator, retail
from worldloom.world import World


@pytest.fixture(scope="module")
def benchmark(tmp_path_factory: pytest.TempPathFactory) -> NativeBenchmark:
    root = tmp_path_factory.mktemp("benchmark-sdk-source")
    facts = tuple(CanonicalFact(id=f"FACT-{index:04}", kind="financial.revenue.actual", subject=f"store:{name}",
        period="2026-01", value=Quantity(amount=amount, unit="AUD"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD) for index, (name, amount) in enumerate((("east", 125), ("west", 70))))
    world = World(seed=8128, company=Company(id="CO-1", name="Northstar Retail", industry="retail",
        headquarters="Sydney", fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-SOURCE", intent_id="INTENT-1", title="January close", sections=[
            ArtifactSection(heading=f"{fact.subject} revenue", body=f"Revenue for {fact.subject}: {{{{fact:{fact.id}}}}}.",
                fact_ids=[fact.id]) for fact in facts]),))
    native = NativeCorpusPlan(artifact_id="ART-DOC", format="docx", title="Revenue review", minimum_units=2,
        contents=tuple(NativeContent(source_artifact_id="ART-SOURCE", section_index=index) for index in range(2)))
    scale = root / "scale"
    export_corpus_scale(world, plan_corpus_scale(world, Simulator(retail(stores=1, products=1, ticks=1), seed=8128),
        profile=CorpusScaleProfile(name="sdk", minimum_relational_rows=3), native_plans=(native,)), scale)
    return NativeBenchmark.build(world, scale, NativeWorkloadPlan(use_case_id="close",
        objective="Review revenue evidence and update the report.", formats=("docx",),
        operations=("read", "update", "create"), max_tasks=6))


def _tree(directory: Path) -> dict[str, bytes]:
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob("*")) if path.is_file()}


def _refresh_manifest(directory: Path, *, identity: str | None = None) -> None:
    path = directory / "benchmark.json"
    manifest = json.loads(path.read_text())
    manifest["files"] = [{"path": key, "sha256": hashlib.sha256(value).hexdigest(), "size_bytes": len(value)}
        for key, value in _tree(directory).items() if key != "benchmark.json"]
    if identity is not None:
        manifest["digest"] = identity
    write_json(path, manifest)


def test_sdk_exports_replayable_target_only_corpus_and_retains_private_lineage(benchmark: NativeBenchmark, tmp_path: Path) -> None:
    first = benchmark.export(tmp_path / "first")
    second = benchmark.export(tmp_path / "second")
    assert first.digest == second.digest == benchmark.digest
    assert _tree(first.directory) == _tree(second.directory)
    assert set(_tree(first.target_directory)) == {"public-tasks.json", *(item.path for task in first.workload.tasks for item in task.inputs)}
    assert not any("oracle" in name or "source" in name for name in _tree(first.target_directory))
    assert (first.directory / "private" / "source" / "world.json").is_file()
    assert first.world is not None and first.rendered is not None
    assert first.qualify().passed
    replies = NativeWorkloadReplies(replies=tuple(NativeTaskReply(task_id=task.id,
        submission=reference_submission(task, first.inputs)) for task in first.workload.tasks))
    assert first.grade(replies).passed
    with pytest.raises(ValueError, match="exactly once"):
        first.grade(NativeWorkloadReplies(replies=replies.replies[:-1]))
    with pytest.raises(ValueError, match="exactly once"):
        first.grade(NativeWorkloadReplies(replies=(*replies.replies, replies.replies[0])))
    assert next(seam for seam in seam_manifest()["seams"] if seam["name"] == "benchmarks")["canonical_import"] == "worldloom.benchmarks"


def test_sdk_resumes_exact_identity_and_refuses_changed_contract(benchmark: NativeBenchmark, tmp_path: Path) -> None:
    output = tmp_path / "package"
    first = benchmark.export(output)
    before = _tree(output)
    assert benchmark.export(output, resume=True).digest == first.digest
    assert _tree(output) == before
    with pytest.raises(ValueError, match="already exists"):
        benchmark.export(output)
    assert benchmark.world is not None and benchmark.rendered is not None
    changed = NativeBenchmark.from_rendered(benchmark.world, benchmark.rendered,
        benchmark.workload.plan.model_copy(update={"objective": "Review a different reporting objective."}))
    with pytest.raises(ValueError, match="resume mismatch"):
        changed.export(output, resume=True)
    assert _tree(output) == before


def test_source_free_exchange_and_missing_provenance_are_rejected(benchmark: NativeBenchmark, tmp_path: Path) -> None:
    root = tmp_path / "exchange"
    root.mkdir()
    write_json(root / "oracle.json", benchmark.workload.model_dump(mode="json"))
    write_json(root / "public-tasks.json", benchmark.public_tasks)
    with pytest.raises(ValueError, match="manifest missing; rebuild a source-bound package"):
        NativeBenchmark.load(root)
    assert not hasattr(benchmark, "export_legacy")
    with pytest.raises(ValueError, match="require a canonical world"):
        replace(benchmark, world=None)
    with pytest.raises(ValueError, match="require a canonical world"):
        replace(benchmark, rendered=None)
    package = benchmark.export(tmp_path / "package")
    manifest_path = package.directory / "benchmark.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["source_digest"]
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="source_digest"):
        NativeBenchmark.load(package.directory)


def test_split_role_is_bound_to_identity_and_resume(benchmark: NativeBenchmark, tmp_path: Path) -> None:
    training = replace(benchmark, split_role="training")
    heldout = replace(benchmark, split_role="heldout")
    assert len({benchmark.digest, training.digest, heldout.digest}) == 3
    package = training.export(tmp_path / "training")
    assert package.split_role == "training"
    assert package.qualify().passed
    with pytest.raises(ValueError, match="resume mismatch"):
        heldout.export(package.directory, resume=True)
    manifest_path = package.directory / "benchmark.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["split_role"] = "heldout"
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="identity differs"):
        NativeBenchmark.load(package.directory)


@pytest.mark.parametrize("refresh_checksums", [False, True])
def test_public_prompt_drift_is_refused_even_with_updated_manifest(benchmark: NativeBenchmark, tmp_path: Path, refresh_checksums: bool) -> None:
    package = benchmark.export(tmp_path / "package")
    path = package.target_directory / "public-tasks.json"
    public = json.loads(path.read_text())
    public["tasks"][0]["prompt"] = "Perform an unrelated task."
    write_json(path, public)
    if refresh_checksums:
        _refresh_manifest(package.directory)
    with pytest.raises(ValueError, match=r"checksum changed|public native tasks differ"):
        NativeBenchmark.load(package.directory)


def test_rewriting_oracle_public_projection_and_all_checksums_cannot_forge_generated_tasks(benchmark: NativeBenchmark, tmp_path: Path) -> None:
    package = benchmark.export(tmp_path / "package")
    first, *rest = package.workload.tasks
    workload = package.workload.model_copy(update={"tasks": (first.model_copy(update={"prompt": "Perform an unrelated task."}), *rest)})
    forged = replace(package, workload=workload)
    write_json(package.directory / "private" / "oracle.json", workload.model_dump(mode="json"))
    write_json(package.target_directory / "public-tasks.json", forged.public_tasks)
    _refresh_manifest(package.directory, identity=forged.digest)
    with pytest.raises(ValueError, match="oracle differs from its canonical source"):
        NativeBenchmark.load(package.directory)


def test_public_folder_rejects_extra_oracle_even_when_its_checksum_is_declared(benchmark: NativeBenchmark, tmp_path: Path) -> None:
    package = benchmark.export(tmp_path / "package")
    (package.target_directory / "oracle-copy.json").write_bytes((package.directory / "private" / "oracle.json").read_bytes())
    _refresh_manifest(package.directory)
    with pytest.raises(ValueError, match="public directory contains files outside"):
        NativeBenchmark.load(package.directory)


def test_malformed_source_manifest_envelope_is_a_validation_refusal(benchmark: NativeBenchmark, tmp_path: Path) -> None:
    package = benchmark.export(tmp_path / "package")
    write_json(package.directory / "private" / "native-manifests.json", {"other": []})
    _refresh_manifest(package.directory)
    with pytest.raises(ValueError, match="manifests"):
        NativeBenchmark.load(package.directory)


def test_changed_native_bytes_and_symlink_inputs_are_refused(benchmark: NativeBenchmark, tmp_path: Path) -> None:
    package = benchmark.export(tmp_path / "package")
    item = package.workload.tasks[0].inputs[0]
    path = package.target_directory / item.path
    original = path.read_bytes()
    path.write_bytes(original + b"tampered")
    with pytest.raises(ValueError, match="checksum changed"):
        NativeBenchmark.load(package.directory)
    outside = tmp_path / "outside.docx"
    outside.write_bytes(original)
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links unavailable")
    with pytest.raises(ValueError, match="symbolic-link"):
        NativeBenchmark.load(package.directory)


def test_export_refuses_concurrent_writer_and_cleans_interrupted_stage(benchmark: NativeBenchmark, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "package"
    lock = tmp_path / ".package.native-benchmark.lock"
    lock.touch()
    with pytest.raises(ValueError, match="locked"):
        benchmark.export(output)
    assert lock.exists() and not output.exists()
    lock.unlink()

    def interrupted(*args: object, **kwargs: object) -> None:
        raise OSError("interrupted write")

    monkeypatch.setattr("worldloom.benchmarks.core.corpus.write_json", interrupted)
    with pytest.raises(OSError, match="interrupted write"):
        benchmark.export(output)
    assert not output.exists() and not lock.exists()
    assert list(tmp_path.iterdir()) == []


def test_input_mapping_is_copied_before_harness_can_mutate_it(benchmark: NativeBenchmark) -> None:
    supplied = dict(benchmark.inputs)
    detached = NativeBenchmark(benchmark.workload, supplied, benchmark.world, benchmark.rendered)
    supplied.clear()
    assert detached.qualify().passed
    with pytest.raises(TypeError):
        detached.inputs["new"] = b"changed"


def test_unexported_benchmark_names_missing_target_directory(benchmark: NativeBenchmark) -> None:
    with pytest.raises(ValueError, match="export the native benchmark"):
        _ = benchmark.target_directory


def test_unrequested_format_cannot_bring_unverified_source_claims_into_public_corpus(benchmark: NativeBenchmark) -> None:
    assert benchmark.world is not None and benchmark.rendered is not None
    workbook = render_native_corpus(benchmark.world, NativeCorpusPlan(artifact_id="ART-XLSX", format="xlsx",
        title="Other source format", contents=(NativeContent(source_artifact_id="ART-SOURCE", section_index=0),)))
    entries = workbook.manifest.evidence
    forged = replace(workbook, manifest=workbook.manifest.model_copy(update={"evidence": (
        entries[0].model_copy(update={"fact_ids": ("FACT-UNKNOWN",)}), *entries[1:])}))
    with pytest.raises(ValueError, match="unknown canonical facts"):
        NativeBenchmark.from_rendered(benchmark.world, {**benchmark.rendered, "ART-XLSX": forged}, benchmark.workload.plan)
