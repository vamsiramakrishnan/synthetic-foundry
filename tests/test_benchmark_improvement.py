"""The public benchmark seam uses the sealed native loop without custom glue."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from worldloom import packkit
from worldloom.benchmarks.core import NativeBenchmark
from worldloom.benchmarks.improvement import improve_benchmark
from worldloom.benchmarks.runner import CallableHarness
from worldloom.evalrun.qualification import QualificationPolicy
from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Company,
    Quantity,
)
from worldloom.native_artifacts import inspect_artifact
from worldloom.native_corpus import (
    NativeContent,
    NativeCorpusPlan,
    render_native_corpus,
)
from worldloom.native_query_planning import NativeWorkloadPlan
from worldloom.native_tasks import NativeAnswer, NativeCitation, NativeSubmission
from worldloom.world import World


def _benchmark(world: World, rendered: dict) -> NativeBenchmark:
    return NativeBenchmark.from_rendered(world, rendered, NativeWorkloadPlan(
        use_case_id="store-review", objective="Review each store's unit evidence.",
        formats=("docx",), operations=("read",), max_tasks=64, discovery_scope="artifact"))


@pytest.fixture(scope="module")
def benchmarks() -> tuple[NativeBenchmark, NativeBenchmark]:
    facts = tuple(CanonicalFact(id=f"FACT-{index:04}", kind="retail.units", subject="store:" + chr(65 + index),
        period="2026-01", value=Quantity(amount=100 + index, unit="units"),
        valid_from=datetime(2026, 1, 1, tzinfo=UTC), authority=Authority.SYSTEM_OF_RECORD) for index in range(6))
    world = World(seed=8128, company=Company(id="CO-1", name="Northstar Retail", industry="retail", headquarters="Sydney",
        fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-SOURCE", intent_id="INTENT-1", title="Store review", sections=[
            ArtifactSection(heading=f"Store {chr(65 + index)} units", body=f"Units for {fact.subject}: {{{{fact:{fact.id}}}}}",
                fact_ids=[fact.id]) for index, fact in enumerate(facts)]),))
    rendered = {}
    for index in range(6):
        plan = NativeCorpusPlan(artifact_id=f"native-{index}", format="docx", title="Store review", surface="business",
            contents=(NativeContent(source_artifact_id="ART-SOURCE", section_index=index),))
        rendered[plan.artifact_id] = render_native_corpus(world, plan)
    return (_benchmark(world, {key: value for key, value in rendered.items() if key in {"native-0", "native-1"}}),
            _benchmark(world, {key: value for key, value in rendered.items() if key not in {"native-0", "native-1"}}))


class _ByteHarness:
    def __init__(self) -> None:
        self.executions: list[tuple[str, str]] = []

    def __call__(self, request: dict, inputs: dict) -> NativeSubmission:
        assert "expected" not in request and "native_task" not in request and "experiment" not in request
        self.executions.append((request["id"], request["execution_id"]))
        if "verify" not in request["agent"]["policy"]["skills"]:
            return NativeSubmission()
        source = request["inputs"][0]
        units = inspect_artifact(inputs[source["artifact_id"]], source["format"]).units
        answer_id = request["answers"][0]["assertion_id"]
        unit = (next(unit for unit in units if unit.text.startswith("Units for store:")) if answer_id == "evidence"
                else next(unit for unit in units if "/row:2/cell:4" in unit.locator))
        return NativeSubmission(answers=(NativeAnswer(assertion_id=answer_id, value=unit.text,
            citations=(NativeCitation(artifact_id=source["artifact_id"], locator=unit.locator),)),))


def _propose(payload: dict) -> dict:
    return {"request_id": payload["request_id"], "message": "revised", "proposal": {
        "name": payload["draft"]["name"], "body": {**payload["draft"]["body"], "skills": {
            "verify": "Find the requested business evidence in the supplied native bytes and cite its actual native location."}}}}


def test_benchmark_improvement_delivers_policy_and_reuses_sealed_resume(
    benchmarks: tuple[NativeBenchmark, NativeBenchmark], tmp_path: Path,
) -> None:
    training, heldout = benchmarks
    assert heldout.world is not None and heldout.rendered is not None
    # Snapshots may differ outside a task's evidence graph. The runner must use
    # the source world that owns each artifact, not overwrite all source worlds
    # with either side of the train/held-out pair.
    changed = tuple(fact.model_copy(update={"value": Quantity(amount=999, unit="units")})
        if fact.id == "FACT-0000" else fact for fact in heldout.world.facts)
    heldout = _benchmark(replace(heldout.world, _facts=changed), dict(heldout.rendered))
    target = _ByteHarness()
    harness = CallableHarness(target, identity={"kind": "native-business-parser", "version": "v1"})
    proposals = []

    def proposer(payload: dict) -> dict:
        proposals.append(payload)
        assert all(task.prompt not in json.dumps(payload) for task in heldout.workload.tasks)
        return _propose(payload)

    args = {"namespace": "northstar/company", "harness": harness, "proposer": proposer, "out": tmp_path,
        "qualification_policy": QualificationPolicy(trials=2, min_units=2), "repeats": 2, "ablate": False}
    report = improve_benchmark(packkit.resolve("agent:baseline"), training, heldout, **args)
    assert report.promotions == 1
    assert report.rounds[0].decision == "promoted", report.rounds[0].reasons
    assert report.rounds[0].holdout.independent_units == 2
    assert len(proposals) == 1
    assert len(target.executions) == len(set(target.executions))
    before = len(target.executions)
    (tmp_path / "rounds" / "001.json").unlink()
    (tmp_path / "improve.json").unlink()
    resumed = improve_benchmark(packkit.resolve("agent:baseline"), training, heldout, **args)
    assert resumed.rounds == report.rounds
    assert len(target.executions) == before
    # A completed round evicts its proposal journal. Reconstructing its receipt
    # may propose the same revision again, but cannot spend held-out calls again.
    assert len(proposals) == 2
    args["harness"] = CallableHarness(target, identity={"kind": "native-business-parser", "version": "changed"})
    with pytest.raises(ValueError, match="sealed qualification"):
        improve_benchmark(packkit.resolve("agent:baseline"), training, heldout, **args)
    assert len(target.executions) == before and len(proposals) == 2


def _never(*_: Any) -> Any:
    raise AssertionError("invalid benchmark data must fail before target or proposer execution")


class _NeverHarness:
    identity: ClassVar[dict] = {"kind": "must-not-execute"}
    __call__ = _never


@pytest.mark.parametrize("defect", ["legacy", "lineage", "shared", "replica", "units", "repeats", "namespace", "origin"])
def test_improvement_refuses_impossible_studies_before_any_external_call(
    defect: str, benchmarks: tuple[NativeBenchmark, NativeBenchmark], tmp_path: Path,
) -> None:
    training, heldout = benchmarks
    namespace = "northstar/company"
    repeats = 2
    pattern = ""
    if defect == "legacy":
        training = replace(training, world=None, rendered=None)
        pattern = "canonical source provenance"
    elif defect == "lineage":
        assert training.rendered is not None
        key = next(iter(training.rendered))
        source = training.rendered[key]
        evidence = source.manifest.evidence[0].model_copy(update={"fact_ids": ("FACT-9999",)})
        forged = replace(source, manifest=source.manifest.model_copy(update={"evidence": (evidence,)}))
        training = replace(training, rendered={**training.rendered, key: forged})
        pattern = "unknown canonical facts"
    elif defect == "shared":
        heldout = training
        pattern = "both training and held out"
    elif defect == "replica":
        assert training.world is not None and training.rendered is not None
        heldout = NativeBenchmark.from_rendered(training.world, training.rendered,
            training.workload.plan.model_copy(update={"use_case_id": "another-business-request"}))
        assert set(task.id for task in training.workload.tasks).isdisjoint(task.id for task in heldout.workload.tasks)
        pattern = "share protected evidence"
    elif defect == "units":
        assert heldout.rendered is not None and heldout.world is not None
        heldout = _benchmark(heldout.world, dict(list(heldout.rendered.items())[:2]))
        pattern = "4 independent held-out units"
    elif defect == "repeats":
        repeats = 1
        pattern = "at least 2 repeats"
    elif defect == "namespace":
        namespace = " "
        pattern = "stable company source namespace"
    elif defect == "origin":
        assert heldout.world is not None and heldout.rendered is not None
        world = replace(heldout.world, company=heldout.world.company.model_copy(update={"id": "CO-OTHER"}))
        heldout = _benchmark(world, dict(heldout.rendered))
        pattern = "one company origin"
    with pytest.raises(ValueError, match=pattern):
        improve_benchmark(packkit.resolve("agent:baseline"), training, heldout, namespace=namespace,
            harness=_NeverHarness(), proposer=_never, out=tmp_path, repeats=repeats,
            qualification_policy=QualificationPolicy(trials=2, min_units=2), agent_for=_never)


def test_improvement_refuses_same_artifact_id_with_different_verified_content(
    benchmarks: tuple[NativeBenchmark, NativeBenchmark], tmp_path: Path,
) -> None:
    training, heldout = benchmarks
    assert heldout.world is not None
    plan = NativeCorpusPlan(artifact_id="native-0", format="docx", title="Another store review", surface="business",
        contents=(NativeContent(source_artifact_id="ART-SOURCE", section_index=3),))
    conflicting = _benchmark(heldout.world, {plan.artifact_id: render_native_corpus(heldout.world, plan)})
    with pytest.raises(ValueError, match="conflicting artifact identities"):
        improve_benchmark(packkit.resolve("agent:baseline"), training, conflicting, namespace="northstar/company",
            harness=_NeverHarness(), proposer=_never, out=tmp_path,
            qualification_policy=QualificationPolicy(trials=1, min_units=2), agent_for=_never)


@pytest.mark.parametrize("relation", ["derived_from", "supersedes"])
def test_improvement_refuses_shared_artifact_with_changed_canonical_source_graph(
    relation: str, benchmarks: tuple[NativeBenchmark, NativeBenchmark], tmp_path: Path,
) -> None:
    training, _ = benchmarks
    assert training.world is not None and training.rendered is not None
    update = {relation: ("FACT-0004",) if relation == "derived_from" else "FACT-0004"}
    facts = tuple(fact.model_copy(update=update) if fact.id == "FACT-0000" else fact for fact in training.world.facts)
    changed = NativeBenchmark.from_rendered(replace(training.world, _facts=facts), training.rendered,
        training.workload.plan.model_copy(update={"use_case_id": "changed-source-graph"}))
    assert changed.rendered == training.rendered
    assert changed.inputs == training.inputs
    with pytest.raises(ValueError, match="conflicting canonical source graphs"):
        improve_benchmark(packkit.resolve("agent:baseline"), training, changed, namespace="northstar/company",
            harness=_NeverHarness(), proposer=_never, out=tmp_path,
            qualification_policy=QualificationPolicy(trials=1, min_units=2), agent_for=_never)


@pytest.mark.parametrize("relation", ["derived_from", "supersedes"])
def test_improvement_refuses_distinct_artifacts_with_shared_canonical_ancestors(
    relation: str, benchmarks: tuple[NativeBenchmark, NativeBenchmark], tmp_path: Path,
) -> None:
    training, heldout = benchmarks
    assert heldout.world is not None and heldout.rendered is not None
    update = {relation: ("FACT-0000",) if relation == "derived_from" else "FACT-0000"}
    facts = tuple(fact.model_copy(update=update) if fact.id == "FACT-0002" else fact for fact in heldout.world.facts)
    heldout = _benchmark(replace(heldout.world, _facts=facts), dict(heldout.rendered))
    with pytest.raises(ValueError, match="share protected evidence"):
        improve_benchmark(packkit.resolve("agent:baseline"), training, heldout, namespace="northstar/company",
            harness=_NeverHarness(), proposer=_never, out=tmp_path,
            qualification_policy=QualificationPolicy(trials=1, min_units=2), agent_for=_never)


@pytest.mark.parametrize("split", ["training", "held-out"])
@pytest.mark.parametrize("gap", ["operations", "formats"])
def test_improvement_requires_each_split_to_deliver_its_declared_work_before_external_calls(
    split: str, gap: str, benchmarks: tuple[NativeBenchmark, NativeBenchmark], tmp_path: Path,
) -> None:
    training, heldout = benchmarks
    source = training if split == "training" else heldout
    assert source.world is not None and source.rendered is not None
    if gap == "operations":
        plan = source.workload.plan.model_copy(update={"operations": ("read", "analyze", "update", "create"), "max_tasks": 1})
        missing = "analyze, create, update"
    else:
        plan = source.workload.plan.model_copy(update={"formats": ("docx", "pptx")})
        missing = "pptx"
    incomplete = NativeBenchmark.from_rendered(source.world, source.rendered, plan)
    assert {task.operation for task in incomplete.workload.tasks} == {"read"}
    if split == "training":
        training = incomplete
    else:
        heldout = incomplete
    with pytest.raises(ValueError, match=f"{split} benchmark does not cover requested {gap}: {missing}"):
        improve_benchmark(packkit.resolve("agent:baseline"), training, heldout, namespace="northstar/company",
            harness=_NeverHarness(), proposer=_never, out=tmp_path,
            qualification_policy=QualificationPolicy(trials=1, min_units=2), agent_for=_never)
