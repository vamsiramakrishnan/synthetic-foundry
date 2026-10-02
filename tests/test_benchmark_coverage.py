"""Task solvability and independent experiment support are different claims."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from worldloom.benchmarks.coverage import (
    NativeAssessmentSource,
    assess_native_benchmark,
)
from worldloom.evalrun.qualification import QualificationPolicy
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
from worldloom.native_query_planning import NativeWorkloadPlan, plan_native_workload
from worldloom.world import World


@pytest.fixture(scope="module")
def sources() -> tuple:
    facts = tuple(CanonicalFact(id=f"FACT-{index:04}", kind="retail.units", subject=f"Store {chr(65 + index)}", period="2026-01",
        value=Quantity(amount=100 + index, unit="units"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD) for index in range(5))
    world = World(seed=8128, company=Company(id="CO-1", name="Northstar", industry="retail", headquarters="Sydney",
        fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-SOURCE", intent_id="INTENT-1", title="Store review", sections=[
            ArtifactSection(heading=f"Store {chr(65 + index)} units", body=f"Units for Store {chr(65 + index)}: {{{{fact:{fact.id}}}}}", fact_ids=[fact.id])
            for index, fact in enumerate(facts)]),))
    plans = tuple(NativeCorpusPlan(artifact_id=f"native-{index}", format="docx", title="Store review", surface="business",
        contents=(NativeContent(source_artifact_id="ART-SOURCE", section_index=index),)) for index in range(5))
    rendered = {plan.artifact_id: render_native_corpus(world, plan) for plan in plans}
    plan = NativeWorkloadPlan(use_case_id="review", objective="Read store evidence.", formats=("docx",),
        operations=("read",), max_tasks=64, discovery_scope="artifact")
    return world, rendered, plan_native_workload(world, rendered, plan)


def codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_qualified_tasks_do_not_imply_promotion_support(sources: tuple) -> None:
    world, rendered, workload = sources
    report = assess_native_benchmark(world, rendered, workload, namespace="northstar")
    assert report.execution_ready and report.coverage_complete
    assert report.tasks == report.reference_qualified == 10
    assert report.independent_units == report.used_sources == report.used_canonical_facts == 5
    assert not report.promotion_ready and "qualification_policy_missing" in codes(report)
    assert report.operations[0].tasks == 10 and report.operations[0].independent_units == 5
    assert report.model_dump_json() == assess_native_benchmark(world, dict(reversed(tuple(rendered.items()))),
        workload, namespace="northstar").model_dump_json()


def test_requested_operations_and_formats_do_not_disappear(sources: tuple) -> None:
    world, rendered, workload = sources
    requested = workload.model_copy(update={"plan": workload.plan.model_copy(update={
        "formats": ("docx", "xlsx"), "operations": ("read", "analyze", "update", "create")}),
        "operation_counts": {"read": 999, "analyze": 999}, "reference_qualified": 999})
    report = assess_native_benchmark(world, rendered, requested, namespace="northstar")
    assert report.execution_ready and not report.coverage_complete and not report.promotion_ready
    assert {"requested_operation_missing", "requested_format_missing", "operation_format_gaps",
            "operation_counts_uneven", "qualification_count_stale"} <= codes(report)
    assert {entry.name: entry.tasks for entry in report.operations} == {"analyze": 0, "create": 0, "read": 10, "update": 0}
    assert {entry.name: entry.tasks for entry in report.formats} == {"docx": 10, "xlsx": 0}
    assert report.reference_qualified == 10


def test_format_replicas_and_private_artifact_aliases_share_one_component(sources: tuple) -> None:
    world, _, workload = sources
    plans = tuple(NativeCorpusPlan(artifact_id=name, format=format, title="Store review", surface="business",
        contents=tuple(NativeContent(source_artifact_id="ART-SOURCE", section_index=index) for index in range(5)))
        for name, format in (("private-alias-one", "docx"), ("private-alias-two", "docx"), ("slide-replica", "pptx")))
    rendered = {plan.artifact_id: render_native_corpus(world, plan) for plan in plans}
    copied = plan_native_workload(world, rendered, workload.plan.model_copy(update={"formats": ("docx", "pptx")}))
    report = assess_native_benchmark(world, rendered, copied, namespace="northstar",
        qualification_policy=QualificationPolicy(trials=2, min_units=2), repeats=2)
    assert report.execution_ready and report.tasks > 5
    assert report.independent_units == 1
    assert all(entry.independent_units == 1 for entry in report.formats)
    assert {"shared_evidence", "evidence_budget_insufficient", "qualification_split_missing"} <= codes(report)


def test_policy_budget_and_transitive_split_audit_use_real_evidence(sources: tuple) -> None:
    world, rendered, workload = sources
    train_ids = [task.id for task in workload.tasks if task.inputs[0].artifact_id == "native-0"]
    held_ids = [task.id for task in workload.tasks if task.id not in train_ids]
    policy = QualificationPolicy(trials=2, min_units=2, min_repeats=2)
    report = assess_native_benchmark(world, rendered, workload, namespace="northstar", qualification_policy=policy,
        training_task_ids=train_ids, heldout_task_ids=held_ids, repeats=2)
    assert report.promotion_ready and report.required_heldout_units == 4
    assert report.split_audit.isolated and report.split_audit.training_units == 1 and report.split_audit.heldout_units == 4
    assert report.unassigned_tasks == 0
    leaked = assess_native_benchmark(world, rendered, workload, namespace="northstar", qualification_policy=policy,
        training_task_ids=train_ids[:1], heldout_task_ids=[*held_ids, *train_ids[1:]], repeats=1)
    assert not leaked.promotion_ready
    assert {"qualification_split_leakage", "repeat_budget_insufficient"} <= codes(leaked)
    assert leaked.split_audit.overlapping_units == 1


def test_separate_heldout_package_is_revalidated_and_audited(sources: tuple) -> None:
    world, rendered, workload = sources
    train = workload.model_copy(update={"tasks": tuple(task for task in workload.tasks if task.inputs[0].artifact_id == "native-0")})
    held = workload.model_copy(update={"tasks": tuple(task for task in workload.tasks if task not in train.tasks)})
    policy = QualificationPolicy(trials=2, min_units=2)
    report = assess_native_benchmark(world, rendered, train, namespace="northstar", qualification_policy=policy,
        repeats=2, heldout=NativeAssessmentSource(world, rendered, held, "northstar"))
    assert report.promotion_ready and report.heldout_reference_qualified == 8
    assert report.split_audit.heldout_units == 4
    overlap = assess_native_benchmark(world, rendered, train, namespace="northstar", qualification_policy=policy,
        repeats=2, heldout=NativeAssessmentSource(world, rendered, workload, "northstar"))
    assert not overlap.promotion_ready and "qualification_split_leakage" in codes(overlap)
    tampered = {**rendered, "native-1": replace(rendered["native-1"], payload=rendered["native-1"].payload + b"changed")}
    bad = assess_native_benchmark(world, rendered, train, namespace="northstar", qualification_policy=policy,
        repeats=2, heldout=NativeAssessmentSource(world, tampered, held, "northstar"))
    assert not bad.promotion_ready and "heldout_contract_invalid" in codes(bad)
    assert bad.heldout_reference_qualified is None


def test_invalid_bytes_never_claim_qualified_or_independent_units(sources: tuple) -> None:
    world, rendered, workload = sources
    tampered = {**rendered, "native-0": replace(rendered["native-0"], payload=rendered["native-0"].payload + b"changed")}
    report = assess_native_benchmark(world, tampered, workload, namespace="northstar")
    assert not report.execution_ready and not report.promotion_ready
    assert report.reference_qualified is None and report.independent_units is None
    assert "native_contract_invalid" in codes(report)


def test_heldout_requested_coverage_is_required_even_with_enough_isolated_units(sources: tuple) -> None:
    world, rendered, workload = sources
    training_sources = {key: value for key, value in rendered.items() if key == "native-0"}
    heldout_sources = {key: value for key, value in rendered.items() if key != "native-0"}
    training = plan_native_workload(world, training_sources, workload.plan)
    heldout = plan_native_workload(world, heldout_sources, workload.plan.model_copy(update={
        "operations": ("read", "update"), "formats": ("docx", "xlsx")}))
    report = assess_native_benchmark(world, training_sources, training, namespace="northstar",
        qualification_policy=QualificationPolicy(trials=2, min_units=2), repeats=2,
        heldout=NativeAssessmentSource(world, heldout_sources, heldout, "northstar"))
    assert report.execution_ready and report.coverage_complete
    assert report.split_audit.isolated and report.split_audit.heldout_units == 4
    assert report.heldout_reference_qualified == len(heldout.tasks)
    assert report.heldout_coverage_complete is False and not report.promotion_ready
    assert {"heldout_requested_operation_missing", "heldout_requested_format_missing"} <= codes(report)


def test_unknown_policy_dimension_and_empty_workload_are_named(sources: tuple) -> None:
    world, rendered, workload = sources
    report = assess_native_benchmark(world, rendered, workload, namespace="northstar",
        qualification_policy=QualificationPolicy(unit_dimension="invented"), repeats=2)
    assert report.execution_ready and not report.promotion_ready
    assert report.independent_units is None and "independence_unavailable" in codes(report)
    empty = assess_native_benchmark(world, rendered, workload.model_copy(update={"tasks": ()}), namespace="northstar")
    assert not empty.execution_ready and not empty.coverage_complete
    assert "empty_workload" in codes(empty)


def test_insufficient_heldout_pool_and_origin_renaming_cannot_pass(sources: tuple) -> None:
    world, rendered, workload = sources
    train = workload.model_copy(update={"tasks": tuple(task for task in workload.tasks if task.inputs[0].artifact_id == "native-0")})
    held = workload.model_copy(update={"tasks": tuple(task for task in workload.tasks if task.inputs[0].artifact_id in {"native-1", "native-2"})})
    policy = QualificationPolicy(trials=2, min_units=2)
    report = assess_native_benchmark(world, rendered, train, namespace="northstar", qualification_policy=policy,
        repeats=2, heldout=NativeAssessmentSource(world, rendered, held, "northstar"))
    assert not report.promotion_ready and report.split_audit.heldout_units == 2
    assert "heldout_units_insufficient" in codes(report)
    renamed = assess_native_benchmark(world, rendered, train, namespace="northstar", qualification_policy=policy,
        repeats=2, heldout=NativeAssessmentSource(world, rendered, workload, "renamed-same-world"))
    assert not renamed.promotion_ready and "heldout_origin_mismatch" in codes(renamed)
