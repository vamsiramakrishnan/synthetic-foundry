"""Canonical ancestry is trusted source provenance, not client asserted independence."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from worldloom.evalrun.qualification import audit_splits, evidence_components
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
from worldloom.native_eval_bridge import (
    NativeGrader,
    native_runner,
    native_source_digest,
    native_task_cases,
)
from worldloom.native_query_evidence import SourceEvidenceIndex
from worldloom.native_query_planning import NativeWorkloadPlan, plan_native_workload
from worldloom.world import World


def _sources(format: str = "docx") -> tuple:
    facts = tuple(CanonicalFact(id="FACT-" + name.upper(), kind="financial.revenue.actual", subject="store:" + name,
        period="2026-01", value=Quantity(amount=amount, unit="AUD"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD) for name, amount in (("root", 125), ("left", 100), ("right", 110), ("other", 200)))
    facts = (facts[0], facts[1].model_copy(update={"derived_from": (facts[0].id,)}),
        facts[2].model_copy(update={"supersedes": facts[0].id}), facts[3])
    irs = tuple(ArtifactIR(id="ART-" + name.upper(), intent_id="INTENT-" + name.upper(), title=name + " revenue",
        sections=[ArtifactSection(heading=name + " revenue", body="Reported revenue: {{fact:" + fact.id + "}}.")])
        for name, fact in zip(("left", "right", "other"), facts[1:], strict=True))
    world = World(seed=8128, company=Company(id="CO-1", name="Northstar Retail", industry="retail", headquarters="Sydney",
        fiscal_year_start_month=7, employees_total=100), _facts=facts, _artifact_irs=irs)
    rendered = {ir.id: render_native_corpus(world, NativeCorpusPlan(artifact_id=ir.id, format=format, title=ir.title,
        surface="business", contents=(NativeContent(source_artifact_id=ir.id, section_index=0),))) for ir in irs}
    workload = plan_native_workload(world, rendered, NativeWorkloadPlan(use_case_id="review", objective="Review revenue.",
        formats=(format,), operations=("read",), discovery_scope="artifact"))
    return world, rendered, workload


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
def test_derived_and_superseded_siblings_share_independence_without_changing_tasks(format: str) -> None:
    world, rendered, workload = _sources(format)
    cases = native_task_cases(workload.tasks, rendered, world=world, namespace="northstar/revenue")
    assert cases and workload.reference_qualified == len(cases)
    assert len(set(evidence_components(cases).values())) == 2
    left = tuple(case for case in cases if case.row["native_lineage"][0]["artifact_id"] == "ART-LEFT")
    right = tuple(case for case in cases if case.row["native_lineage"][0]["artifact_id"] == "ART-RIGHT")
    assert left and right and not audit_splits(left, right).isolated
    for case in (*left, *right):
        assert "FACT-ROOT" in case.row["expected_fact_ids"]
        assert "FACT-ROOT" not in case.row["native_lineage"][0]["direct_fact_ids"]
        task = next(task for task in workload.tasks if task.id == case.id)
        assert case.row["native_task"] == task.model_dump(mode="json")
        assert "FACT-ROOT" not in case.query


@pytest.mark.parametrize("defect", ["missing_derived", "missing_superseded", "mixed_cycle"])
def test_unverifiable_canonical_ancestry_refuses_compilation(defect: str) -> None:
    world, rendered, workload = _sources()
    facts = list(world.facts)
    if defect == "mixed_cycle":
        facts[1] = facts[1].model_copy(update={"derived_from": (facts[2].id,)})
        facts[2] = facts[2].model_copy(update={"supersedes": facts[1].id})
        message = "ancestry cycle"
    else:
        fields = {"derived_from": ("FACT-MISSING",)} if defect == "missing_derived" else {"supersedes": "FACT-MISSING"}
        facts[1] = facts[1].model_copy(update=fields)
        message = "ancestry names an unknown fact"
    changed = replace(world, _facts=tuple(facts))
    with pytest.raises(ValueError, match=message):
        native_task_cases(workload.tasks, rendered, world=changed, namespace="northstar/revenue")


def test_canonical_closure_handles_long_chains_and_excludes_unrelated_bad_edges() -> None:
    world, _, _ = _sources()
    template = world.facts[0]
    facts = tuple(template.model_copy(update={"id": f"FACT-{index:04}",
        "derived_from": (f"FACT-{index - 1:04}",) if index else ()}) for index in range(1500))
    unused = template.model_copy(update={"id": "FACT-UNUSED", "derived_from": ("FACT-MISSING",)})
    source = SourceEvidenceIndex(replace(world, _facts=(*facts, unused)))
    expected = tuple(fact.id for fact in facts)
    assert source.fact_closure((facts[-1].id,)) == expected
    assert source.fact_closure((facts[-1].id, facts[-1].id)) == expected


def test_runner_recomputes_ancestry_instead_of_trusting_consistent_forged_case_fields() -> None:
    world, rendered, workload = _sources()
    cases = native_task_cases(workload.tasks, rendered, world=world, namespace="northstar/revenue")
    left = next(case for case in cases if case.row["native_lineage"][0]["artifact_id"] == "ART-LEFT")
    lineage = [{**source, "fact_ids": source["direct_fact_ids"]} for source in left.row["native_lineage"]]
    direct = sorted({fid for source in lineage for fid in source["fact_ids"]})
    forged = left.model_copy(update={"row": {**left.row, "native_lineage": lineage, "expected_fact_ids": direct},
        "outcomes": left.outcomes.model_copy(update={"unstructured": left.outcomes.unstructured.model_copy(
            update={"required_fact_ids": tuple(direct)})})})

    def submit(*_: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("unverified ancestry must fail before target execution")

    runner = native_runner(rendered, submit, world=world, namespace="northstar/revenue", submit_identity={"adapter": "v1"})
    runner.validate_cases(cases)
    with pytest.raises(ValueError, match="actual source manifests"):
        runner.validate_cases((forged,))


def test_source_graph_changes_pin_grading_and_refuse_stale_cases_with_unchanged_bytes() -> None:
    world, rendered, workload = _sources()
    cases = native_task_cases(workload.tasks, rendered, world=world, namespace="northstar/revenue")
    changed = replace(world, _facts=tuple(fact.model_copy(update={"derived_from": ("FACT-OTHER",)})
        if fact.id == "FACT-LEFT" else fact for fact in world.facts))
    assert native_source_digest(world) != native_source_digest(changed)
    runner = native_runner(rendered, lambda *_: None, world=world, namespace="northstar/revenue", submit_identity={"adapter": "v1"})
    identity = runner.grading_identity(NativeGrader())
    runner.worlds = {key: changed for key in rendered}
    assert runner.grading_identity(NativeGrader()) != identity
    with pytest.raises(ValueError, match="actual source manifests"):
        runner.validate_cases(cases)


def test_runner_requires_an_evaluator_world_for_every_artifact() -> None:
    world, rendered, _ = _sources()
    with pytest.raises(ValueError, match="trusted source world for every served artifact"):
        native_runner(rendered, lambda *_: None, world={"ART-LEFT": world}, namespace="northstar/revenue", submit_identity={"adapter": "v1"})
