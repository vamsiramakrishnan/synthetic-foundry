"""Reporting-period context must be present in the served native labels."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

import pytest
from pydantic import ValidationError

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
from worldloom.native_artifacts import inspect_artifact
from worldloom.native_business import prepare_business_content
from worldloom.native_corpus import (
    NativeContent,
    NativeCorpusPlan,
    plan_native_corpus,
    render_native_corpus,
)
from worldloom.world import World

NativeFormat = Literal["docx", "pptx", "xlsx"]


def _world() -> World:
    facts = tuple(CanonicalFact(id=f"FACT-{index}", kind="close.revenue", subject="BU-NORTH", period=period,
        value=Quantity(amount=value, unit="AUD"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD) for index, (period, value) in enumerate((("2026-01", 100), ("2026-02", 125))))
    sections = [ArtifactSection(heading="Commitment", body=f"Revenue was committed at {{{{fact:{fact.id}}}}}.",
        # This unused metadata citation must not suppress the genuine period
        # of the values this section actually serves.
        fact_ids=[facts[1].id], table=Table(key=f"revenue-{index}", title="Revenue", columns=[
            Column(key="actual", label="Actual")], rows=[Row(key="north", label="North division",
                cells={"actual": Cell(value=fact.value.amount, fact_id=fact.id)})])) for index, fact in enumerate(facts)]
    return World(company=Company(id="CO-1", name="Northstar Retail", industry="retail", headquarters="Sydney",
        fiscal_year_start_month=7, employees_total=100), _facts=facts, _artifact_irs=(ArtifactIR(id="ART-1",
            intent_id="INTENT-1", title="Close calendar", sections=sections),))


def _plan(format: NativeFormat, *, contextual: bool = True) -> NativeCorpusPlan:
    return NativeCorpusPlan(artifact_id="native", format=format, title="Close calendar", surface="business",
        contents=tuple(NativeContent(source_artifact_id="ART-1", section_index=index) for index in range(2)),
        contextual_headings=contextual)


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
def test_context_occurs_in_actual_headings_and_table_titles_without_changing_evidence(format: NativeFormat) -> None:
    world = _world()
    original = world.artifact_irs[0].model_dump_json()
    plan = _plan(format)
    result = render_native_corpus(world, plan)
    assert result.payload == render_native_corpus(world, plan).payload
    assert world.artifact_irs[0].model_dump_json() == original
    units = {unit.text for unit in inspect_artifact(result.payload, format).units}
    for period in ("2026-01", "2026-02"):
        assert f"Commitment — reporting period {period}" in units
        assert f"Revenue — reporting period {period}" in units
    assert not any("FACT-" in unit for unit in units)
    assert result.manifest.distinct_fact_count == 2
    base = render_native_corpus(world, _plan(format, contextual=False))
    assert sorted(entry.text_sha256 for entry in result.manifest.evidence) == sorted(
        entry.text_sha256 for entry in base.manifest.evidence)
    assert [entry.fact_ids for entry in result.manifest.evidence] == [entry.fact_ids for entry in base.manifest.evidence]


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
def test_context_is_opt_in_and_false_preserves_wire_and_bytes(format: NativeFormat) -> None:
    world = _world()
    plan = _plan(format, contextual=False)
    wire = plan.model_dump()
    assert "contextual_headings" not in wire
    assert "contextual_headings" not in NativeCorpusPlan(artifact_id="legacy", format=format,
        title="Legacy", contents=plan.contents).model_dump()
    loaded = NativeCorpusPlan.model_validate(wire)
    assert render_native_corpus(world, plan).payload == render_native_corpus(world, loaded).payload
    with pytest.raises(ValidationError, match="require the business surface"):
        NativeCorpusPlan(artifact_id="legacy", format=format, title="Legacy", contents=plan.contents,
                         contextual_headings=True)
    selected = plan_native_corpus(world, artifact_id="native", format=format, title="Close calendar",
        minimum_units=2, surface="business", contextual_headings=True)
    assert selected.contextual_headings
    assert selected.model_dump()["contextual_headings"] is True


@pytest.mark.parametrize("scope", ["mixed", "null", "single_with_null"])
def test_context_uses_complete_served_evidence_not_an_arbitrary_fact(scope: str) -> None:
    world = _world()
    ir = world.artifact_irs[0]
    # A reference in February reaches January's cell. Context must account for
    # the dependency, not just the fact attached to the local actual cell.
    section = ir.sections[1]
    table = section.table
    assert table is not None
    cells = {**table.rows[0].cells, "prior": Cell(value=100, formula=FormulaKind.REFERENCE,
        operands=["revenue-0:north:actual"])}
    changed_table = table.model_copy(update={"columns": [*table.columns, Column(key="prior", label="Prior")],
        "rows": [table.rows[0].model_copy(update={"cells": cells})]})
    sections = [ir.sections[0], section.model_copy(update={"table": changed_table})]
    facts = world._facts
    if scope == "null":
        facts = tuple(fact.model_copy(update={"period": None}) for fact in facts)
    elif scope == "single_with_null":
        facts = (facts[0].model_copy(update={"period": None}), facts[1])
    world = replace(world, _facts=facts, _artifact_irs=(ir.model_copy(update={"sections": sections}),))
    contents = prepare_business_content(world, _plan("xlsx"))
    assert contents[1].fact_ids == ("FACT-0", "FACT-1")
    expected = " — reporting period 2026-02" if scope == "single_with_null" else ""
    assert contents[1].heading == "Commitment" + expected
    assert contents[1].table.title == "Revenue" + expected
