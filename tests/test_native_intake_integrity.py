"""Native intake validates source privacy and canonical identity independently."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

import pytest

from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Cell,
    Column,
    Company,
    FormulaKind,
    Quantity,
    Row,
    Table,
)
from worldloom.native_corpus import (
    NativeContent,
    NativeCorpusPlan,
    NativeCorpusResult,
    render_native_corpus,
)
from worldloom.native_eval_bridge import native_task_cases
from worldloom.native_query_evidence import SourceEvidenceIndex
from worldloom.native_query_planning import NativeWorkloadPlan, plan_native_workload
from worldloom.native_reference import qualify_native_task
from worldloom.world import World

NativeFormat = Literal["docx", "pptx", "xlsx"]


def _corpus(format: NativeFormat, content_kind: str) -> tuple[World, NativeCorpusResult, NativeWorkloadPlan]:
    facts = tuple(CanonicalFact(id="FACT-" + kind.upper(), kind="financial.revenue." + kind,
        subject="store:north", period="2026-01", value=Quantity(amount=amount, unit="AUD"),
        valid_from=datetime(2026, 1, 1, tzinfo=UTC), authority=Authority.SYSTEM_OF_RECORD)
        for kind, amount in (("actual", 125), ("budget", 100)))
    section = ArtifactSection(heading="North store revenue",
        body="Actual revenue: {{fact:FACT-ACTUAL}}. Budget revenue: {{fact:FACT-BUDGET}}.",
        fact_ids=[fact.id for fact in facts])
    if content_kind == "table":
        section = ArtifactSection(heading="Revenue reconciliation", table=Table(key="revenue", title="Store revenue",
            columns=[Column(key=key, label=label) for key, label in
                     (("actual", "Actual revenue"), ("budget", "Budget revenue"), ("variance", "Variance"))],
            rows=[Row(key="north", label="North store", cells={
                "actual": Cell(value=125, fact_id="FACT-ACTUAL"),
                "budget": Cell(value=100, fact_id="FACT-BUDGET"),
                "variance": Cell(value=25, formula=FormulaKind.DIFFERENCE, operands=["actual", "budget"]),
            })]))
    world = World(seed=8128, company=Company(id="CO-1", name="Northstar Retail", industry="retail",
        headquarters="Sydney", fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-SOURCE", intent_id="INTENT-1", title="Revenue review", sections=[section]),))
    native_plan = NativeCorpusPlan(artifact_id="review", format=format, title="Revenue review", surface="business",
        contents=(NativeContent(source_artifact_id="ART-SOURCE", section_index=0,
            placement="notes" if format == "pptx" and content_kind == "prose" else "body"),))
    result = render_native_corpus(world, native_plan)
    workload_plan = NativeWorkloadPlan(use_case_id="review", objective="Review store revenue.",
        formats=(format,), operations=("read",), discovery_scope="artifact")
    return world, result, workload_plan


def _changed_section(world: World, **updates: object) -> World:
    source = world.artifact_irs[0]
    section = source.sections[0].model_copy(update=updates)
    return replace(world, _artifact_irs=(source.model_copy(update={"sections": [section]}),))


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
@pytest.mark.parametrize("content_kind", ["prose", "table"])
def test_intake_refuses_source_sections_made_private_after_rendering(format: NativeFormat, content_kind: str) -> None:
    world, result, plan = _corpus(format, content_kind)
    rendered = {"review": result}
    workload = plan_native_workload(world, rendered, plan)
    assert workload.tasks and workload.reference_qualified == len(workload.tasks)
    assert all(qualify_native_task(task, {"review": result.payload}).passed for task in workload.tasks)
    valid = native_task_cases(workload.tasks, rendered, namespace="northstar/revenue", world=world)
    assert len(valid) == len(workload.tasks)
    private = _changed_section(world, hidden=True)
    with pytest.raises(ValueError, match="private authored section: ART-SOURCE:0"):
        plan_native_workload(private, rendered, plan)
    with pytest.raises(ValueError, match="private authored section: ART-SOURCE:0"):
        native_task_cases(workload.tasks, rendered, namespace="northstar/revenue", world=private)
    assert result.payload == render_native_corpus(world, NativeCorpusPlan(artifact_id="review", format=format,
        title="Revenue review", surface="business", contents=(NativeContent(source_artifact_id="ART-SOURCE", section_index=0,
            placement="notes" if format == "pptx" and content_kind == "prose" else "body"),))).payload
    assert plan_native_workload(world, rendered, plan) == workload


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
@pytest.mark.parametrize("defect,updates,message", [
    ("bare_figure", {"body": "Unapproved forecast: 999. Actual: {{fact:FACT-ACTUAL}}."}, "reference canonical figures"),
    ("unknown_reference", {"body": "Forecast: {{fact:FACT-MISSING}}."}, "unknown canonical facts"),
    ("malformed_reference", {"body": "Forecast: {{fact:0001}}."}, "unknown canonical facts"),
    ("unknown_declared_fact", {"fact_ids": ["FACT-MISSING"]}, "unknown canonical facts"),
])
def test_table_intake_refuses_stale_ungrounded_source_ir(
    format: NativeFormat, defect: str, updates: dict[str, object], message: str,
) -> None:
    world, result, plan = _corpus(format, "table")
    workload = plan_native_workload(world, {"review": result}, plan)
    assert workload.tasks, defect
    stale = _changed_section(world, **updates)
    with pytest.raises(ValueError, match=message):
        plan_native_workload(stale, {"review": result}, plan)
    with pytest.raises(ValueError, match=message):
        native_task_cases(workload.tasks, {"review": result}, namespace="northstar/revenue", world=stale)


@pytest.mark.parametrize("identity", ["artifact", "fact"])
def test_native_intake_refuses_ambiguous_source_ids_instead_of_last_write_winning(identity: str) -> None:
    world, result, plan = _corpus("xlsx", "table")
    workload = plan_native_workload(world, {"review": result}, plan)
    if identity == "artifact":
        private = world.artifact_irs[0].model_copy(update={"sections": [
            world.artifact_irs[0].sections[0].model_copy(update={"hidden": True}),
        ]})
        ambiguous = replace(world, _artifact_irs=(private, *world.artifact_irs))
        message = "duplicate authored artifact identity"
    else:
        conflicting = world.facts[0].model_copy(update={"value": Quantity(amount=999, unit="AUD")})
        ambiguous = replace(world, _facts=(conflicting, *world.facts))
        message = "duplicate canonical fact identity"
    with pytest.raises(ValueError, match=message):
        plan_native_workload(ambiguous, {"review": result}, plan)
    with pytest.raises(ValueError, match=message):
        native_task_cases(workload.tasks, {"review": result}, namespace="northstar/revenue", world=ambiguous)


@pytest.mark.parametrize("updates,message", [
    ({"hidden": True}, "private authored section"),
    ({"body": "Actual: {{fact:FACT-ACTUAL}}. Budget: {{fact:FACT-BUDGET}}. Forecast: 999."}, "reference canonical figures"),
])
def test_scalar_register_intake_validates_authored_ir_even_when_only_values_are_claimed(
    updates: dict[str, object], message: str,
) -> None:
    world, result, plan = _corpus("xlsx", "prose")
    values = tuple(entry for entry in result.manifest.evidence if entry.value is not None)
    assert values and all(len(entry.fact_ids) == 1 for entry in values)
    register = replace(result, manifest=result.manifest.model_copy(update={"evidence": values}))
    workload = plan_native_workload(world, {"review": register}, plan)
    assert workload.tasks and workload.reference_qualified == len(workload.tasks)
    stale = _changed_section(world, **updates)
    with pytest.raises(ValueError, match=message):
        plan_native_workload(stale, {"review": register}, plan)
    with pytest.raises(ValueError, match=message):
        native_task_cases(workload.tasks, {"review": register}, namespace="northstar/revenue", world=stale)


@pytest.mark.parametrize("updates,message", [
    ({"hidden": True}, "private authored section"),
    ({"body": "Forecast: {{fact:FACT-MISSING}}."}, "unknown canonical facts"),
])
def test_reusable_source_guard_rechecks_a_replaced_authored_section(updates: dict[str, object], message: str) -> None:
    world, _, _ = _corpus("docx", "prose")
    guard = SourceEvidenceIndex(world)
    source = world.artifact_irs[0]
    original = source.sections[0]
    assert guard.section(source.id, 0) is original
    # Frozen IRs still contain a section list. Replacing a section must not
    # reuse the previous public section's validation under the same address.
    source.sections[0] = original.model_copy(update=updates)
    with pytest.raises(ValueError, match=message):
        guard.section(source.id, 0)


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
@pytest.mark.parametrize("private", [False, True])
def test_erasing_provenance_cannot_admit_ungrounded_or_private_bytes(format: NativeFormat, private: bool) -> None:
    world, result, plan = _corpus(format, "prose")
    workload = plan_native_workload(world, {"review": result}, plan)
    assert workload.tasks and workload.reference_qualified == len(workload.tasks)
    erased = replace(result, manifest=result.manifest.model_copy(update={
        "evidence": (), "content_units": 0, "distinct_fact_count": 0, "source_artifact_count": 0,
    }))
    source_world = _changed_section(world, hidden=True) if private else world
    with pytest.raises(ValueError, match="source has no canonical evidence"):
        plan_native_workload(source_world, {"review": erased}, plan)
    with pytest.raises(ValueError, match="source has no canonical evidence"):
        native_task_cases(workload.tasks, {"review": erased}, namespace="northstar/revenue", world=source_world)
