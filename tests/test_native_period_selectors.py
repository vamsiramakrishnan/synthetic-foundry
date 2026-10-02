"""Repeated headings need public descriptors from the same native body."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pytest

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
from worldloom.native_eval_bridge import native_task_cases
from worldloom.native_query_planning import NativeWorkloadPlan, plan_native_workload
from worldloom.native_reference import qualify_native_task
from worldloom.world import World

NativeFormat = Literal["docx", "pptx", "xlsx"]


def _source(format: NativeFormat, defect: str | None = None) -> tuple:
    facts = []
    sections = []
    for index, name in enumerate(("EARLY", "LATER")):
        period = "2026-01" if index == 0 or defect == "duplicate_period" else "2026-02"
        measure = CanonicalFact(id="FACT-REVENUE-" + name, kind="financial.revenue.actual", subject="store:north",
            period=period, value=Quantity(amount=100 + index * 25, unit="AUD"),
            valid_from=datetime(2026, 1, 1, tzinfo=UTC), authority=Authority.SYSTEM_OF_RECORD)
        date = CanonicalFact(id="FACT-PERIOD-" + name, kind="reporting.period", subject="store:north",
            period=period, text_value=period, valid_from=measure.valid_from, authority=measure.authority)
        facts.extend((measure, date))
        subject = "the business" if defect == "missing_subject" else "store:north"
        temporal = "" if defect == "missing_period" else " in reporting period {{fact:" + date.id + "}}"
        sections.append(ArtifactSection(heading="Revenue", body=f"Revenue for {subject}{temporal}: {{{{fact:{measure.id}}}}}."))
    world = World(seed=8128, company=Company(id="CO-1", name="Northstar Retail", industry="retail",
        headquarters="Sydney", fiscal_year_start_month=7, employees_total=100), _facts=tuple(facts),
        _artifact_irs=(ArtifactIR(id="ART-SOURCE", intent_id="INTENT-1", title="Revenue close", sections=sections),))
    plan = NativeCorpusPlan(artifact_id="period-review", format=format, title="Revenue close", surface="business",
        minimum_units=2, contents=tuple(NativeContent(source_artifact_id="ART-SOURCE", section_index=index,
            placement="notes" if format == "pptx" else "body") for index in range(2)))
    return world, render_native_corpus(world, plan)


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
def test_unique_subject_and_period_in_the_same_body_disambiguate_repeated_headings(format: NativeFormat) -> None:
    world, result = _source(format)
    workload = plan_native_workload(world, {"period-review": result}, NativeWorkloadPlan(use_case_id="revenue",
        objective="Review revenue evidence.", formats=(format,), operations=("read", "update"), discovery_scope="artifact"))
    assert workload.operation_counts["update"] > 0
    assert not any(finding.code == "ambiguous_evidence_selector" for finding in workload.findings)
    prose = [task for task in workload.tasks if any(assertion.id == "evidence" for assertion in task.assertions)]
    assert len(prose) == 2
    assert all("concerning 'store:north' in reporting period" in task.prompt for task in prose)
    assert any("'2026-01'" in task.prompt for task in prose)
    assert any("'2026-02'" in task.prompt for task in prose)
    for task in workload.tasks:
        assert qualify_native_task(task, {"period-review": result.payload}).passed
        for assertion in task.assertions:
            if assertion.target is not None:
                assert assertion.target.locator not in task.prompt
    cases = native_task_cases(workload.tasks, {"period-review": result}, namespace="northstar", world=world)
    assert len(cases) == len(workload.tasks)


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
@pytest.mark.parametrize("defect", ["duplicate_period", "missing_period", "missing_subject"])
def test_period_selector_cannot_guess_a_duplicate_or_use_descriptors_outside_the_body(format: NativeFormat, defect: str) -> None:
    world, result = _source(format, defect)
    # Business registers still expose reporting periods even when the prose
    # omits them; those separate units cannot identify a repeated evidence body.
    if defect == "missing_period":
        assert "2026-01" in {unit.text for unit in inspect_artifact(result.payload, format).units}
    workload = plan_native_workload(world, {"period-review": result}, NativeWorkloadPlan(use_case_id="revenue",
        objective="Review revenue evidence.", formats=(format,), operations=("read", "update"), discovery_scope="artifact"))
    assert sum(finding.code == "ambiguous_evidence_selector" for finding in workload.findings) == 2
    assert not any(task.operation == "update" for task in workload.tasks)
    assert not any(any(assertion.id == "evidence" for assertion in task.assertions) for task in workload.tasks)
    assert any(finding.code == "operation_unavailable" and finding.operation == "update" for finding in workload.findings)
