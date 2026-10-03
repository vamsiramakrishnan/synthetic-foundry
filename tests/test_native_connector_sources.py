"""Real native evidence reaches controlled harness DAGs through one adapter."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from worldloom import RetailWorld
from worldloom.benchmarks.connector_sources import (
    NativeConnectorProjection,
    project_native_sources,
)
from worldloom.benchmarks.scenarios import NativeScenarioDemand, build_native_scenarios
from worldloom.benchmarks.tactics import NativeRealismProfile
from worldloom.enterprise_rows import runtime_records
from worldloom.evalrun.harness_dags import (
    HarnessDagConfig,
    HarnessDagReference,
    build_harness_dags,
)
from worldloom.evalrun.runner import run_cases, service_for
from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Company,
    Quantity,
)
from worldloom.native_corpus import plan_native_corpus, render_native_corpus
from worldloom.world import World

_MEASURE = "native.supplier_reconciliation.total.actual"


@pytest.fixture(scope="module")
def cohort():
    base = RetailWorld(seed=8128).build()
    profile = NativeRealismProfile(revision_views=("reviewed",))
    first = build_native_scenarios(base, NativeScenarioDemand(
        episodes=1, processes=("supplier_reconciliation",), batch_id="alpha", realism=profile))
    second = build_native_scenarios(first.world, NativeScenarioDemand(
        episodes=1, processes=("supplier_reconciliation",), batch_id="bravo", realism=profile))
    rendered = (*first.render(formats=("xlsx", "docx")).values(),
                *second.render(formats=("xlsx", "docx")).values())
    return second.world, rendered


def _config(world, **kwargs):
    return NativeConnectorProjection(measure_kind=_MEASURE, unit=world.company.currency, **kwargs)


@pytest.mark.parametrize("refine", [False, True])
def test_real_native_cents_reconcile_through_public_only_harness_dags(cohort, refine) -> None:
    world, rendered = cohort
    projection = project_native_sources(world, rendered, _config(world))
    assert len(projection.records) == 4 and len(projection.excluded_formats) == 4
    assert projection.representation == "extracted_content"
    approved = [record for record in projection.records if record.fields["authority"] == "approved_report"]
    assert len(approved) == 2
    assert sorted(Decimal(str(record.fields["amount"])) for record in approved) == [Decimal("11191.36"), Decimal("12919.59")]
    assert all(record.fields["unit"] == world.company.currency for record in projection.records)
    assert {record.fields["authority"] for record in projection.records} == {"approved_report", "working_document"}
    assert len({record.fields["source_family"] for record in projection.records}) == 2
    suite = build_harness_dags(projection.records, HarnessDagConfig(
        cases=6, value_field="amount", scope_field="scope", authority_field="authority", authority_value="approved_report"))
    report = run_cases(service_for(suite.cases, runtime_records(suite.records), surface="native"),
                       suite.cases, HarnessDagReference(suite.tasks, refine=refine))
    assert len(report.results) == 6
    for result in report.results:
        assert result.graded and result.score and result.score.passed, (result.error, result.score)
        assert result.score.trajectory.retrieval.recovered == int(refine)
    private_ids = {fact.id for fact in world.facts}
    for record in projection.records:
        assert not any(identifier in str(record.fields) for identifier in private_ids)
    assert len({case.dimensions["family_id"] for case in suite.cases}) == 1


def test_byte_digests_and_formula_provenance_are_checked(cohort) -> None:
    world, rendered = cohort
    native = next(item for item in rendered if item.manifest.format == "xlsx" and "REVIEWED" not in item.manifest.artifact_id)
    with pytest.raises(ValueError, match="source bytes changed"):
        project_native_sources(world, (replace(native, payload=native.payload + b"changed"),), _config(world))
    formula = next(entry for entry in native.manifest.evidence if entry.kind == "formula")
    corrupted = formula.model_copy(update={"value": 1.23})
    entries = tuple(corrupted if item is formula else item for item in native.manifest.evidence)
    with pytest.raises(ValueError, match="native table value disagrees"):
        project_native_sources(world, (replace(native, manifest=native.manifest.model_copy(update={"evidence": entries})),), _config(world))


def test_measure_and_unit_are_explicit_and_cannot_be_inferred(cohort) -> None:
    world, rendered = cohort
    with pytest.raises(ValueError, match="wrong unit"):
        project_native_sources(world, rendered, NativeConnectorProjection(measure_kind=_MEASURE, unit="units"))
    with pytest.raises(ValueError, match="no grounded measure"):
        project_native_sources(world, rendered, NativeConnectorProjection(measure_kind="native.supplier_reconciliation.total", unit=world.company.currency))
    with pytest.raises(ValueError, match="distinct"):
        _config(world, value_field="content")
    with pytest.raises(ValueError, match="max_content_bytes"):
        project_native_sources(world, rendered, _config(world, max_content_bytes=1))


def test_replicas_do_not_buy_more_sources_and_formats_share_lineage(cohort) -> None:
    world, rendered = cohort
    native = next(item for item in rendered if item.manifest.format == "xlsx")
    copied = replace(native, manifest=native.manifest.model_copy(update={"artifact_id": native.manifest.artifact_id + "-copy"}))
    projection = project_native_sources(world, (*rendered, copied), _config(world))
    assert len(projection.records) == 4
    assert projection.deduplicated_artifact_ids == (copied.manifest.artifact_id,)
    documents = project_native_sources(world, rendered, _config(world, format="docx"))
    left = {binding.selected_fact_id: binding.family_id for binding in projection.bindings}
    right = {binding.selected_fact_id: binding.family_id for binding in documents.bindings}
    assert left == right
    assert projection == project_native_sources(world, tuple(reversed((*rendered, copied))), _config(world))


def _simple_world(*, ambiguous=False, superseded=False, overlap=False):
    first = CanonicalFact(id="FACT-0001", kind=_MEASURE, subject="CO-1", period="2026-01",
                          value=Quantity(amount=12.34, unit="AUD"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                          authority=Authority.APPROVED_REPORT)
    second = first.model_copy(update={"id": "FACT-0002", "value": Quantity(amount=56.78, unit="AUD"),
                                      "supersedes": first.id if superseded else None,
                                      "derived_from": (first.id,) if overlap else ()})
    selected = (first, second) if ambiguous else (first,)
    sections = [ArtifactSection(heading=f"Recorded amount {index}", body="Recorded amount: {{fact:" + fact.id + "}}",
                                fact_ids=[fact.id]) for index, fact in enumerate(selected)]
    world = World(company=Company(id="CO-1", name="Northstar Retail", industry="retail", headquarters="Sydney",
                                  fiscal_year_start_month=7, employees_total=100),
                  _facts=(first, second) if superseded or ambiguous or overlap else (first,),
                  _artifact_irs=(ArtifactIR(id="ART-1", intent_id="INTENT-1", title="Amounts", sections=sections,
                                           metadata={"authority": "approved_report"}),))
    plan = plan_native_corpus(world, artifact_id="amounts", format="xlsx", title="Amounts", minimum_units=len(selected))
    return world, render_native_corpus(world, plan)


def test_ambiguous_and_superseded_numeric_values_are_refused() -> None:
    world, native = _simple_world(ambiguous=True)
    with pytest.raises(ValueError, match="ambiguous matching"):
        project_native_sources(world, (native,), _config(world))
    world, native = _simple_world(superseded=True)
    with pytest.raises(ValueError, match="superseded or expired"):
        project_native_sources(world, (native,), _config(world))


def test_overlapping_derived_values_cannot_be_counted_independently() -> None:
    world, first = _simple_world(overlap=True)
    artifact = world._artifact_irs[0].model_copy(update={"id": "ART-2", "intent_id": "INTENT-2",
        "sections": [ArtifactSection(heading="Later amount", body="Later amount: {{fact:FACT-0002}}", fact_ids=["FACT-0002"])]})
    world = replace(world, _artifact_irs=(*world._artifact_irs, artifact))
    plan = plan_native_corpus(world, artifact_id="later-amount", format="xlsx", title="Later amount", minimum_units=1,
                             source_artifact_ids=("ART-2",))
    second = render_native_corpus(world, plan)
    with pytest.raises(ValueError, match="share canonical ancestry"):
        project_native_sources(world, (first, second), _config(world))


def test_presentation_variants_keep_family_but_change_byte_identity() -> None:
    base = RetailWorld(seed=31).build()
    plain = build_native_scenarios(base, NativeScenarioDemand(episodes=1, processes=("supplier_reconciliation",), batch_id="variant"))
    variant = build_native_scenarios(base, NativeScenarioDemand(episodes=1, processes=("supplier_reconciliation",), batch_id="variant",
        realism=NativeRealismProfile(row_order="reversed", decision_placement="back")))
    before = project_native_sources(plain.world, tuple(plain.render(formats=("xlsx",)).values()), _config(plain.world))
    after = project_native_sources(variant.world, tuple(variant.render(formats=("xlsx",)).values()), _config(variant.world))
    assert before.bindings[0].family_id == after.bindings[0].family_id
    assert before.bindings[0].source_sha256 != after.bindings[0].source_sha256
    assert before.records[0].id != after.records[0].id
    assert before.records[0].fields["amount"] == after.records[0].fields["amount"]


def test_custom_query_field_names_preserve_source_values(cohort) -> None:
    world, rendered = cohort
    projection = project_native_sources(world, rendered, _config(world, value_field="balance", scope_field="account_scope",
        period_field="reporting_month", authority_field="document_status"))
    assert all("amount" not in record.fields and "balance" in record.fields for record in projection.records)
    assert all(record.fields["reporting_month"] == "2026-01" for record in projection.records)
