from __future__ import annotations

from types import SimpleNamespace

import pytest

from worldloom.artifact_ecology import (
    ArtifactProposal,
    Surface,
    enrich_connector_records,
    review_proposal,
)
from worldloom.connector_data import ConnectorRecord
from worldloom.eval_candidates import (
    _check_records,
    _check_temporal_relation,
    validate_candidate,
)
from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    plan_candidates,
)
from worldloom.eval_instances import bind_eval_instance
from worldloom.eval_reference import ExecutionStep, ProofStatus, execute_reference
from worldloom.recipe import rebuild
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose
from worldloom.world_transforms import AddIrrelevantFacts


def _world(seed: int = 8128):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=seed).build().run(MonthEndClose(period="2026-03"))


def _spec(*requirements: WorldRequirement) -> EvalSpec:
    return EvalSpec(
        id="EVALSPEC-PR33-MERGE-GATE", capability="find_evidence",
        persona="controller", request_template="Verify the evidence.",
        steps=(EvalStepSpec(id="find", capability="find_evidence", operation="find", effect="read"),),
        requirements=requirements, candidate_count=1,
    )


def test_connector_selectors_see_nested_business_fields() -> None:
    requirement = WorldRequirement(
        id="incident", kind=RequirementKind.CONNECTOR,
        selector={"priority": "1", "state": "Resolved"},
    )
    record = ConnectorRecord(
        id="sn-1", connector="servicenow", entity="incident", external_id="INC-1",
        title="Incident", fields={"priority": "1", "state": "Resolved"},
    )
    check = _check_records(requirement, [record])
    assert check.satisfied and check.evidence_ids == ("sn-1",)


def test_temporal_selector_matches_requested_endpoints_not_any_edge() -> None:
    requirement = WorldRequirement(
        id="relation", kind=RequirementKind.TEMPORAL_RELATION,
        selector={"edge_kind": "references", "source": "RCA-1", "target": "INC-1"},
    )
    realism = SimpleNamespace(graph=SimpleNamespace(edges=(
        SimpleNamespace(kind="references", source="OTHER", target="INC-1"),
        SimpleNamespace(kind="references", source="RCA-1", target="INC-1"),
    )))
    check = _check_temporal_relation(requirement, realism)
    assert check.observed == 1
    assert check.evidence_ids == ("RCA-1->INC-1:references",)


def test_candidate_acceptance_requires_world_coherence(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(WorldRequirement(id="facts", kind=RequirementKind.FACT))
    plan = plan_candidates(spec, count=1)[0]
    world = _world(plan.seed)
    monkeypatch.setattr(type(world), "validate", lambda self: SimpleNamespace(ok=False))
    assert not validate_candidate(plan, spec, world).accepted


def _bound_read():  # type: ignore[no-untyped-def]
    spec = _spec(WorldRequirement(id="facts", kind=RequirementKind.FACT))
    plan = plan_candidates(spec, count=1)[0]
    world = _world(plan.seed)
    from worldloom.eval_candidates import GeneratedCandidate
    validation = validate_candidate(plan, spec, world)
    candidate = GeneratedCandidate(plan=plan, world=world, validation=validation)
    return world, bind_eval_instance(spec, candidate)


def test_reference_proof_rejects_wrong_operation() -> None:
    world, instance = _bound_read()
    proof = execute_reference(
        instance, world,
        lambda current, step, bound: (current, ExecutionStep(
            step_id=step.id, operation="wrong", output_ids=bound.oracle.fact_ids,
        )),
    )
    assert proof.status == ProofStatus.PROVEN_UNSAT


def test_reference_proof_rejects_missing_required_outputs() -> None:
    world, instance = _bound_read()
    proof = execute_reference(
        instance, world,
        lambda current, step, bound: (current, ExecutionStep(
            step_id=step.id, operation="find", output_ids=(),
        )),
    )
    assert proof.status == ProofStatus.PROVEN_UNSAT


@pytest.mark.parametrize("copy", ["20%", "42", "2026-03-04", "$1,200"])
def test_proposal_rejects_bare_figure_forms(copy: str) -> None:
    world = _world()
    intent = next(iter(world.artifact_intents))
    proposal = ArtifactProposal(
        artifact_id=intent.id, surface=Surface.PDF, family="memo", density="balanced",
        title_register="sentence", copy_blocks=(f"Unsupported claim {copy}",),
    )
    assert "bare_numeric_claim" in {finding.code for finding in review_proposal(world, proposal)}


def test_servicenow_history_stops_at_current_state() -> None:
    world = _world().extend(recipe={**_world().recipe, "artifact_realism": "ecology/v1"})
    record = ConnectorRecord(
        id="sn-resolved", connector="servicenow", entity="incident",
        external_id="INC-RESOLVED", title="Resolved incident",
        fields={"state": "Resolved", "priority": "1", "opened_at": "2026-03-01T00:00:00"},
    )
    enriched = enrich_connector_records(world, [record])[0]
    assert enriched.fields["state_history"][-1]["state"] == "Resolved"
    assert all(note["kind"] != "closure" for note in enriched.fields["work_notes"])


def test_irrelevant_fact_transform_round_trips_through_recipe() -> None:
    world = _world(seed=91)
    transformed = AddIrrelevantFacts(2).apply(world, seed=4001).world
    assert transformed.recipe["steps"][-1] == {
        "scenario": "AddIrrelevantFacts", "seed": 4001, "count": 2,
    }
    replayed = rebuild(transformed.recipe)
    noise = tuple(fact.id for fact in transformed.facts if fact.kind == "metamorphic_irrelevant_context")
    replayed_noise = tuple(fact.id for fact in replayed.facts if fact.kind == "metamorphic_irrelevant_context")
    assert noise == replayed_noise
