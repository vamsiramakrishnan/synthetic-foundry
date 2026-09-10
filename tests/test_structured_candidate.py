"""Document-free operational worlds remain subject to every requested check."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from worldloom.artifact_ecology import profile
from worldloom.eval_candidates import check_requirement, validate_candidate
from worldloom.eval_design import (
    ArtifactShapeRequirement,
    CandidatePlan,
    EvalShape,
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    design_digest,
)
from worldloom.eval_interventions import construct_candidate
from worldloom.retail import RetailWorld
from worldloom.retail_replenishment import (
    PROCESSES,
    RetailProcess,
    RetailProcessScope,
    build_retail_process,
    connected_program,
)


@pytest.fixture(scope="module")
def connected_world():
    base = RetailWorld(seed=8128).build()
    owner = next(iter(base.business_units)).name
    return build_retail_process(base, RetailProcess(
        program=connected_program(stores=1, products=2, ticks=8),
        scopes=tuple(RetailProcessScope(process=process, business_unit=owner, activity_id=process)
                     for process in PROCESSES),
        start=datetime(2026, 3, 1, tzinfo=UTC), max_cases=2,
    ))


def _design(*requirements, shape=None):
    shape = shape or EvalShape()
    spec = EvalSpec(id="structured", capability="search", persona="operator",
                    request_template="Find the inventory exception.",
                    steps=(EvalStepSpec(id="search", capability="search", connector="jira", entity="issue"),),
                    requirements=requirements, shape=shape)
    plan = CandidatePlan(eval_spec_id=spec.id, ordinal=0, seed=8128,
                         requirements=spec.requirements, shape=shape, design_digest=design_digest(spec))
    return spec, plan


def test_structured_construction_uses_existing_connected_records(connected_world, monkeypatch):
    from worldloom import eval_candidates

    def unexpected_ecology(world):
        raise AssertionError("structured requirements must not compile document ecology")

    monkeypatch.setattr(eval_candidates, "realism_profile", unexpected_ecology)
    requirement = WorldRequirement(id="inventory", kind=RequirementKind.CONNECTOR,
                                   selector={"connector": "jira", "entity": "issue",
                                             "process": "inventory_exception"})
    spec, plan = _design(requirement)
    assert not connected_world.artifact_intents
    result = construct_candidate(spec, plan, connected_world)
    assert result.candidate.validation.accepted
    assert result.candidate.validation.checks[0].observed == 2
    assert not result.applied_tactic_ids
    assert not result.findings
    assert not result.candidate.world.artifact_intents


@pytest.mark.parametrize("kind", [RequirementKind.ARTIFACT, RequirementKind.DISTRACTOR,
                                  RequirementKind.REVISION_CHAIN, RequirementKind.TEMPORAL_RELATION])
def test_absent_artifact_evidence_is_a_failed_check(connected_world, kind):
    requirement = WorldRequirement(id="missing", kind=kind)
    check = check_requirement(requirement, connected_world)
    assert not check.satisfied
    assert check.observed == 0
    spec, plan = _design(requirement)
    assert not validate_candidate(plan, spec, connected_world).accepted


def test_explicit_native_shape_still_requires_real_artifacts(connected_world):
    shape = EvalShape(artifacts=(ArtifactShapeRequirement(artifact_type="docx", locator_required=False),))
    spec, plan = _design(WorldRequirement(id="event", kind=RequirementKind.EVENT), shape=shape)
    verdict = validate_candidate(plan, spec, connected_world)
    assert not verdict.accepted
    assert verdict.checks[0].satisfied
    assert verdict.shape_checks[0].observed == 0
    assert verdict.shape_checks[0].required == 1
    ecology = profile(connected_world)
    assert not ecology.lifecycles
    assert not ecology.plans
