"""Build independent input files from complete authored evidence components."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from worldloom.benchmarks.core import NativeBenchmark
from worldloom.benchmarks.partitions import partition_benchmarks, plan_native_partitions
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
from worldloom.native_query_planning import NativeWorkloadPlan
from worldloom.world import World


@pytest.fixture(scope="module")
def world() -> World:
    facts = tuple(CanonicalFact(id=f"FACT-{index:04}", kind="financial.revenue.actual", subject=f"Store {chr(65 + index)}",
        period="2026-01", value=Quantity(amount=100 + index, unit="AUD"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD) for index in range(3))
    return World(seed=8128, company=Company(id="CO-1", name="Northstar", industry="retail", headquarters="Sydney",
        fiscal_year_start_month=7, employees_total=100), _facts=facts,
        _artifact_irs=tuple(ArtifactIR(id="ART-" + chr(65 + index), intent_id="INTENT-" + chr(65 + index),
            title=f"Store {chr(65 + index)} review", sections=[ArtifactSection(heading=f"Store {chr(65 + index)} revenue",
                body=f"Store {chr(65 + index)} revenue: {{{{fact:{fact.id}}}}}", fact_ids=[])])
            for index, fact in enumerate(facts)))


def workload() -> NativeWorkloadPlan:
    return NativeWorkloadPlan(use_case_id="close", objective="Read the store revenue evidence.",
        formats=("docx",), operations=("read",), max_tasks=32, discovery_scope="artifact")


def test_disjoint_authored_sources_render_as_actual_independent_units(world: World) -> None:
    plan = plan_native_partitions(world, formats=("docx", "xlsx"), minimum_families=3)
    assert plan.ready and plan.available_families == len(plan.families) == 3
    assert all(len(family.fact_ids) == len(family.contents) == 1 for family in plan.families)
    assert all(native.contextual_headings for family in plan.families for native in family.plans)
    rendered = plan.render(world)
    assert len(rendered) == 6
    benchmark = NativeBenchmark.from_rendered(world, rendered,
        workload().model_copy(update={"formats": ("docx", "xlsx")}))
    assert benchmark.assess().independent_units == 3
    reordered = replace(world, _artifact_irs=tuple(reversed(world.artifact_irs)), _facts=tuple(reversed(world.facts)))
    assert plan == plan_native_partitions(reordered, formats=("xlsx", "docx"), minimum_families=3)


def test_shared_facts_and_copied_prose_do_not_buy_extra_families(world: World) -> None:
    shared = ArtifactIR(id="ART-SHARED", intent_id="INTENT-SHARED", title="Related review", sections=[
        ArtifactSection(heading="Related revenue evidence", body="Repeated revenue evidence: {{fact:FACT-0000}}.")])
    duplicate = world.artifact_irs[0].model_copy(update={"id": "ART-COPY", "title": "Renamed review"})
    changed = replace(world, _artifact_irs=(*world.artifact_irs, shared, duplicate))
    plan = plan_native_partitions(changed, formats=("docx",), minimum_families=4)
    assert not plan.ready and plan.available_families == 3
    group = next(family for family in plan.families if "FACT-0000" in family.fact_ids)
    assert len(group.contents) == 2
    assert any(item.code == "duplicate_grounded_content" for item in plan.exclusions)
    with pytest.raises(ValueError, match="need 4 independent families; found 3"):
        plan.render(changed)


def test_formula_dependencies_join_sections_even_without_declared_section_facts(world: World) -> None:
    inputs = Table(key="inputs", title="Store inputs", columns=[Column(key="revenue", label="Revenue")], rows=[
        Row(key="north", label="North", cells={"revenue": Cell(value=100, fact_id="FACT-0000")}),
        Row(key="south", label="South", cells={"revenue": Cell(value=101, fact_id="FACT-0001")}),
        Row(key="total", label="Group", cells={"revenue": Cell(value=201, formula=FormulaKind.SUM,
            operands=["north", "south"])})])
    summary = Table(key="summary", title="Management total", columns=[Column(key="revenue", label="Revenue")], rows=[
        Row(key="group", label="Group", cells={"revenue": Cell(value=201, formula=FormulaKind.REFERENCE,
            operands=["inputs:total:revenue"])})])
    artifact = ArtifactIR(id="ART-TABLES", intent_id="INTENT-TABLES", title="Management revenue", sections=[
        ArtifactSection(heading="Management total", table=summary), ArtifactSection(heading="Store inputs", table=inputs)])
    changed = replace(world, _artifact_irs=(artifact, world.artifact_irs[2]))
    plan = plan_native_partitions(changed, formats=("docx", "xlsx"))
    assert plan.available_families == 2
    dependent = next(family for family in plan.families if len(family.contents) == 2)
    assert dependent.fact_ids == ("FACT-0000", "FACT-0001")
    assert all(len(native.contents) == 2 for native in dependent.plans)
    assert len(plan.render(changed)) == 4


def test_canonical_derivation_and_supersession_join_source_families(world: World) -> None:
    facts = (*world.facts[:2], world.facts[2].model_copy(update={"derived_from": ("FACT-0000",), "supersedes": "FACT-0001"}))
    changed = replace(world, _facts=facts)
    plan = plan_native_partitions(changed, formats=("docx", "pptx"))
    assert plan.available_families == 1
    assert plan.families[0].fact_ids == tuple(fact.id for fact in world.facts)
    assert len(plan.families[0].contents) == 3
    assert len(plan.render(changed)) == 2


def test_caps_omit_whole_components_and_private_sources_remain_excluded(world: World) -> None:
    private = world.artifact_irs[0].model_copy(update={"id": "ART-PRIVATE", "sections": [
        world.artifact_irs[0].sections[0].model_copy(update={"hidden": True})]})
    changed = replace(world, _artifact_irs=(*world.artifact_irs, private))
    plan = plan_native_partitions(changed, formats=("docx",), max_families=1)
    assert plan.available_families == 3 and len(plan.families) == 1 and len(plan.omissions) == 2
    assert any(item.code == "private_native_section" for item in plan.exclusions)
    assert len(plan.render(changed)) == 1
    with pytest.raises(ValueError, match="source artifact IDs"):
        plan_native_partitions(world, source_artifact_ids=("unknown",))
    with pytest.raises(ValueError, match="source changed"):
        plan.render(world)


def test_partition_package_builds_and_exact_resume_revalidates_support(world: World, tmp_path: Path) -> None:
    directory = tmp_path / "partitions"
    report = partition_benchmarks(world, workload(), training_families=1, heldout_families=2, directory=directory)
    assert report.split_audit.isolated and report.split_audit.training_units == 1 and report.split_audit.heldout_units == 2
    assert report.training_tasks and report.heldout_tasks
    training = NativeBenchmark.load(Path(report.training_directory))
    heldout = NativeBenchmark.load(Path(report.heldout_directory))
    assert training.qualify().passed and heldout.qualify().passed
    before = {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
    assert report == partition_benchmarks(world, workload(), training_families=1, heldout_families=2,
        directory=directory, resume=True)
    assert before == {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="resume configuration changed"):
        partition_benchmarks(world, workload().model_copy(update={"objective": "Different objective."}),
            training_families=1, heldout_families=2, directory=directory, resume=True)


def test_insufficient_source_and_task_caps_never_publish_false_support(world: World, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot fund 4 independent families; found 3"):
        partition_benchmarks(world, workload(), training_families=2, heldout_families=2, directory=tmp_path / "short")
    assert not (tmp_path / "short").exists()
    with pytest.raises(ValueError, match="does not cover the requested disjoint families"):
        partition_benchmarks(world, workload().model_copy(update={"max_tasks": 1}),
            training_families=1, heldout_families=2, directory=tmp_path / "truncated")
    assert not (tmp_path / "truncated").exists()


def test_rewritten_receipt_cannot_swap_valid_source_family_allocations(world: World, tmp_path: Path) -> None:
    import json
    import shutil

    from worldloom.benchmarks.partitions import _receipt, _support
    from worldloom.corpus import write_json

    directory = tmp_path / "partitions"
    report = partition_benchmarks(world, workload(), training_families=1, heldout_families=2, directory=directory)
    rendered = report.plan.render(world)
    moved_ids = {native.artifact_id for native in report.plan.families[-1].plans}
    replacement_train = NativeBenchmark.from_rendered(world, {key: value for key, value in rendered.items()
        if key in moved_ids}, workload())
    replacement_held = NativeBenchmark.from_rendered(world, {key: value for key, value in rendered.items()
        if key not in moved_ids}, workload())
    audit = _support(replacement_train, replacement_held, training_families=1, heldout_families=2)
    saved = json.loads((directory / "partition.json").read_text())
    shutil.rmtree(directory / "training")
    shutil.rmtree(directory / "heldout")
    replacement_train.export(directory / "training")
    replacement_held.export(directory / "heldout")
    write_json(directory / "partition.json", _receipt(saved["configuration"], replacement_train, replacement_held, audit))
    with pytest.raises(ValueError, match="family allocation changed"):
        partition_benchmarks(world, workload(), training_families=1, heldout_families=2, directory=directory, resume=True)


def _period_world(world: World) -> World:
    months = ("January", "February", "March", "April")
    facts = tuple(world.facts[0].model_copy(update={"id": f"FACT-{position:04}", "period": f"2026-{position + 1:02}",
        "subject": world.company.id, "value": Quantity(amount=100 + position, unit="AUD")}) for position in range(4))
    artifacts = tuple(ArtifactIR(id=f"ART-{month.upper()}", intent_id=f"INTENT-{month.upper()}", title=month + " review",
        sections=[ArtifactSection(heading="Recorded revenue", body=f"Recorded revenue: {{{{fact:{fact.id}}}}}.")])
        for month, fact in zip(months, facts, strict=True))
    return replace(world, _facts=facts, _artifact_irs=artifacts)


def test_grouping_spends_source_independence_to_support_cross_period_updates(world: World, tmp_path: Path) -> None:
    from worldloom.native_reference import reference_submission
    from worldloom.native_tasks import grade_native_task

    periods = _period_world(world)
    assert plan_native_partitions(periods, formats=("docx",)).available_families == 4
    specification = workload().model_copy(update={"operations": ("read", "update")})
    report = partition_benchmarks(periods, specification, training_families=1, heldout_families=1,
        directory=tmp_path / "grouped")
    assert report.plan.available_families == 2 and report.plan.available_components == 4
    assert len(report.plan.components) == 4 and all(component.content_units == 1 for component in report.plan.components)
    assert all(len(family.component_ids) == len(family.contents) == 2 for family in report.plan.families)
    assert report.split_audit.isolated and report.split_audit.training_units == report.split_audit.heldout_units == 1
    for path in (report.training_directory, report.heldout_directory):
        benchmark = NativeBenchmark.load(Path(path))
        updates = [task for task in benchmark.workload.tasks if task.operation == "update"]
        assert updates and benchmark.assess().coverage_complete
        for task in updates:
            response = reference_submission(task, benchmark.inputs)
            assert grade_native_task(task, benchmark.inputs, response).passed


@pytest.mark.parametrize("changed", [{"subject": "Different company"}, {"kind": "financial.units.actual"}])
def test_cross_period_prose_pairing_requires_matching_measure_and_subject(world: World, changed: dict) -> None:
    from worldloom.benchmarks.partitions import _group_partitions

    periods = _period_world(world)
    periods = replace(periods, _facts=(periods.facts[0], periods.facts[1].model_copy(update=changed)),
        _artifact_irs=periods.artifact_irs[:2])
    plan = _group_partitions(periods, plan_native_partitions(periods, formats=("docx",)), 1)
    benchmark = NativeBenchmark.from_rendered(periods, plan.render(periods),
        workload().model_copy(update={"operations": ("read", "update")}))
    assert benchmark.workload.operation_counts["read"]
    assert not benchmark.workload.operation_counts.get("update")
    assert any(finding.code == "operation_unavailable" and finding.operation == "update" for finding in benchmark.workload.findings)


def test_grouping_balances_table_singletons_after_forming_related_prose_pairs(world: World) -> None:
    from worldloom.benchmarks.partitions import _group_partitions

    periods = _period_world(world)
    facts = list(periods.facts)
    artifacts = list(periods.artifact_irs)
    for position in range(4):
        fact = world.facts[0].model_copy(update={"id": f"FACT-TABLE-{position}", "kind": "operating.cost.actual",
            "subject": "Operations", "period": f"2026-{position + 1:02}", "value": Quantity(amount=200 + position, unit="AUD")})
        facts.append(fact)
        artifacts.append(ArtifactIR(id=f"ART-TABLE-{position}", intent_id=f"INTENT-TABLE-{position}", title="Operating costs",
            sections=[ArtifactSection(heading="Operating costs", table=Table(key="costs", title="Costs",
                columns=[Column(key="cost", label="Cost")], rows=[Row(key="operations", label="Operations",
                    cells={"cost": Cell(value=200 + position, fact_id=fact.id)})]))]))
    mixed = replace(world, _facts=tuple(facts), _artifact_irs=tuple(artifacts))
    base = plan_native_partitions(mixed, formats=("docx",))
    assert base.available_families == 8
    grouped = _group_partitions(mixed, base, 4)
    irs = {artifact.id: artifact for artifact in mixed.artifact_irs}
    prose_counts = [sum(bool(irs[content.source_artifact_id].sections[content.section_index].body)
        for content in family.contents) for family in grouped.families]
    # Once the two viable prose pairs exist, the four table-only singletons
    # need grouping. Combining the prose pairs again would destroy one unit
    # of update support while leaving avoidably sparse table files behind.
    assert sorted(prose_counts) == [0, 0, 2, 2]
    assert all(len(family.contents) == 2 for family in grouped.families)


def test_grouped_monthly_tables_keep_visible_period_context_for_analysis(world: World, tmp_path: Path) -> None:
    from worldloom.native_artifacts import inspect_artifact

    periods = _period_world(world)
    tables = tuple(artifact.model_copy(update={"sections": [ArtifactSection(heading="Operating costs",
        table=Table(key="costs", title="Operating costs", columns=[Column(key="value", label="Value")], rows=[
            Row(key="company", label=world.company.name, cells={"value": Cell(value=fact.value.amount, fact_id=fact.id)})]))]})
        for artifact, fact in zip(periods.artifact_irs, periods.facts, strict=True))
    periods = replace(periods, _artifact_irs=tables)
    specification = workload().model_copy(update={"formats": ("docx", "xlsx"), "operations": ("read", "analyze")})
    report = partition_benchmarks(periods, specification, training_families=1, heldout_families=1,
        directory=tmp_path / "monthly-tables")
    for path in (report.training_directory, report.heldout_directory):
        benchmark = NativeBenchmark.load(Path(path))
        assert benchmark.workload.operation_counts["read"] and benchmark.workload.operation_counts["analyze"]
        assert benchmark.assess().independent_units == 1 and benchmark.qualify().passed
        assert benchmark.rendered is not None
        for result in benchmark.rendered.values():
            assert any("reporting period" in unit.text for unit in inspect_artifact(result.payload, result.manifest.format).units)


def test_task_budget_preserves_small_sources_beside_a_large_native_document(world: World) -> None:
    from worldloom.native_corpus import (
        NativeContent,
        NativeCorpusPlan,
        render_native_corpus,
    )
    from worldloom.native_query_planning import _sample, _sample_sources

    count = 210
    facts = tuple(world.facts[0].model_copy(update={"id": f"FACT-BUDGET-{position:04}",
        "subject": f"store:{position}", "value": Quantity(amount=1000 + position, unit="AUD")}) for position in range(count))
    sections = [ArtifactSection(heading=f"Revenue evidence {position}",
        body=f"Recorded store revenue: {{{{fact:{fact.id}}}}}.") for position, fact in enumerate(facts)]
    artifacts = [ArtifactIR(id="ART-HEAVY", intent_id="INTENT-HEAVY", title="Large operating review", sections=sections[:200])]
    artifacts.extend(ArtifactIR(id=f"ART-SMALL-{position}", intent_id=f"INTENT-SMALL-{position}",
        title=f"Store review {position}", sections=[section]) for position, section in enumerate(sections[200:]))
    varied = replace(world, _facts=facts, _artifact_irs=tuple(artifacts))
    plans = [NativeCorpusPlan(artifact_id="a-heavy", format="docx", title="Large operating review", surface="business",
        contents=tuple(NativeContent(source_artifact_id="ART-HEAVY", section_index=position) for position in range(200)))]
    plans.extend(NativeCorpusPlan(artifact_id=f"small-{position}", format="docx", title="Store operating review", surface="business",
        contents=(NativeContent(source_artifact_id=f"ART-SMALL-{position}", section_index=0),)) for position in range(10))
    rendered = {plan.artifact_id: render_native_corpus(varied, plan) for plan in plans}
    benchmark = NativeBenchmark.from_rendered(varied, rendered, workload().model_copy(update={"max_tasks": 32}))
    assert len(benchmark.workload.tasks) == benchmark.workload.reference_qualified == 32
    assert {item.artifact_id for task in benchmark.workload.tasks for item in task.inputs} == set(rendered)
    assert benchmark.assess().independent_units == 11
    assert benchmark.qualify().passed
    # One-slot budgets remain well-defined at the same bounded sampler seam.
    assert _sample(("first", "second"), 1) == ["first"]
    assert _sample_sources(("first", "second"), 1, key=lambda item: (item, "docx")) == ["first"]
