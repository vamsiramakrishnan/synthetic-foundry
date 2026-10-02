"""Exercise the public/native exchange without leaking or trusting the oracle."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.benchmarks import NativeBenchmark, NativeWorkloadPlan
from worldloom.cli import app
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
from worldloom.native_corpus import NativeContent, NativeCorpusPlan
from worldloom.native_reference import reference_submission
from worldloom.synthesis import Simulator, retail
from worldloom.world import World

runner = CliRunner()


@pytest.fixture
def exchange(tmp_path: Path) -> Path:
    facts = tuple(CanonicalFact(id=f"FACT-{index:04}", kind="financial.revenue.actual", subject=f"store:{name}",
        period="2026-01", value=Quantity(amount=amount, unit="AUD"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD) for index, (name, amount) in enumerate((("east", 125), ("west", 70))))
    world = World(seed=8128, company=Company(id="CO-1", name="Northstar Retail", industry="retail",
        headquarters="Sydney", fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-SOURCE", intent_id="INTENT-1", title="January close", sections=[
            ArtifactSection(heading=f"{fact.subject} revenue", body=f"Revenue for {fact.subject}: {{{{fact:{fact.id}}}}}.",
                fact_ids=[fact.id]) for fact in facts]),))
    source = world.export(tmp_path / "source")
    native = NativeCorpusPlan(artifact_id="ART-DOC", format="docx", title="Revenue review", minimum_units=2,
        contents=tuple(NativeContent(source_artifact_id="ART-SOURCE", section_index=index) for index in range(2)))
    scale = tmp_path / "scale"
    export_corpus_scale(world, plan_corpus_scale(world, Simulator(retail(stores=1, products=1, ticks=1), seed=8128),
        profile=CorpusScaleProfile(name="cli", minimum_relational_rows=3), native_plans=(native,)), scale)
    plan = tmp_path / "workload.json"
    write_json(plan, NativeWorkloadPlan(use_case_id="close", objective="Review revenue evidence and update the report.",
        formats=("docx",), operations=("read", "update", "create"), max_tasks=6).model_dump(mode="json"))
    destination = tmp_path / "exchange"
    built = runner.invoke(app, ["native-evals", "build", str(source), str(scale), "--plan", str(plan), "--out", str(destination)])
    assert built.exit_code == 0, built.output
    summary = json.loads(built.output)
    assert set(summary["operation_counts"]) == {"read", "update", "create"}
    assert summary["reference_qualified"] == summary["tasks"]
    return destination


def test_exchange_public_contract_qualification_and_actual_reply_grading(exchange: Path) -> None:
    public = json.loads((exchange / "public/public-tasks.json").read_text())
    assert "FACT-0000" not in json.dumps(public)
    assert "expected" not in json.dumps(public)
    assert all((exchange / "public" / item["path"]).is_file() for task in public["tasks"] for item in task["inputs"])
    qualified = runner.invoke(app, ["native-evals", "qualify", str(exchange)])
    assert qualified.exit_code == 0, qualified.output
    assert json.loads(qualified.output)["passed"]
    benchmark = NativeBenchmark.load(exchange)
    workload, inputs = benchmark.workload, benchmark.inputs
    replies = [{"task_id": task.id, "submission": reference_submission(task, inputs).model_dump(mode="json")}
               for task in workload.tasks]
    path = exchange.parent / "replies.json"
    write_json(path, {"replies": replies})
    graded = runner.invoke(app, ["native-evals", "grade", str(exchange), "--replies", str(path)])
    assert graded.exit_code == 0, graded.output
    assert json.loads(graded.output)["passed"]
    answer_reply = next(reply for reply in replies if reply["submission"]["answers"])
    answer_reply["submission"]["answers"][0]["value"] = "Fabricated revenue evidence"
    write_json(path, {"replies": replies})
    wrong = runner.invoke(app, ["native-evals", "grade", str(exchange), "--replies", str(path)])
    assert wrong.exit_code == 1, wrong.output
    assert not json.loads(wrong.output)["passed"]
    write_json(path, {"replies": replies[:-1]})
    missing = runner.invoke(app, ["native-evals", "grade", str(exchange), "--replies", str(path)])
    assert missing.exit_code != 0 and "exactly once" in missing.output


def test_qualification_refuses_changed_native_input(exchange: Path) -> None:
    source = next((exchange / "public/inputs").iterdir())
    source.write_bytes(source.read_bytes() + b"tampered")
    result = runner.invoke(app, ["native-evals", "qualify", str(exchange)])
    assert result.exit_code != 0, result.output
    assert "checksum changed" in result.output


@pytest.mark.parametrize("command", ["qualify", "grade"])
def test_exchange_refuses_public_prompt_drift_before_qualification_or_grading(exchange: Path, command: str) -> None:
    benchmark = NativeBenchmark.load(exchange)
    workload, inputs = benchmark.workload, benchmark.inputs
    replies = exchange.parent / "reference-replies.json"
    write_json(replies, {"replies": [
        {"task_id": task.id, "submission": reference_submission(task, inputs).model_dump(mode="json")}
        for task in workload.tasks]})
    # These replies satisfy the unchanged evaluator oracle, but the target is
    # now being asked to do different work. Neither command may certify that
    # mismatched exchange by inspecting only the oracle and input checksums.
    public_path = exchange / "public/public-tasks.json"
    public = json.loads(public_path.read_text())
    public["tasks"][0]["prompt"] = "Ignore the revenue review and answer an unrelated request."
    write_json(public_path, public)
    manifest_path = exchange / "benchmark.json"
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["files"]:
        if item["path"] == "public/public-tasks.json":
            payload = public_path.read_bytes()
            item.update(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
    write_json(manifest_path, manifest)
    argv = ["native-evals", command, str(exchange)]
    if command == "grade":
        argv.extend(["--replies", str(replies)])
    result = runner.invoke(app, argv)
    assert result.exit_code != 0, result.output
    assert "public native tasks differ" in result.output


def test_build_has_one_source_bound_layout_and_no_cli_model_shim(exchange: Path) -> None:
    import worldloom.native_evals_cli as native_cli

    assert (exchange / "benchmark.json").is_file()
    assert (exchange / "private/source/world.json").is_file()
    assert not (exchange / "oracle.json").exists()
    result = runner.invoke(app, ["native-evals", "build", "--help"])
    assert result.exit_code == 0, result.output
    assert "--layout" not in result.output
    assert not hasattr(native_cli, "NativeTaskReply")
