from __future__ import annotations

from dataclasses import replace

import pytest

from worldloom.eval_candidates import generate_candidates, validate_candidate
from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    plan_candidates,
)
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _build(plan):  # type: ignore[no-untyped-def]
    world = RetailWorld(seed=plan.seed).build()
    return world.run(MonthEndClose(period="2026-03"))


def _spec(*requirements: WorldRequirement) -> EvalSpec:
    return EvalSpec(
        id="EVALSPEC-CANDIDATE-ACCEPTANCE",
        capability="cross_surface_retrieval",
        persona="finance analyst",
        request_template="Find the close evidence and verify it against the source record.",
        steps=(
            EvalStepSpec(id="find", capability="search"),
            EvalStepSpec(id="verify", capability="verify", depends_on=("find",), effect="verify"),
        ),
        requirements=requirements,
        candidate_count=2,
    )


def test_eval_is_compiled_before_candidate_worlds_are_generated() -> None:
    spec = _spec(
        WorldRequirement(id="facts", kind=RequirementKind.FACT, minimum=1),
        WorldRequirement(
            id="email-evidence",
            kind=RequirementKind.CONNECTOR,
            selector={"connector": "email", "entity": "message"},
            minimum=1,
        ),
    )
    expected_plans = plan_candidates(spec)
    seen = []

    def builder(plan):  # type: ignore[no-untyped-def]
        seen.append(plan)
        return _build(plan)

    candidates = generate_candidates(spec, builder)

    assert tuple(seen) == expected_plans
    assert len(candidates) == 2
    assert all(candidate.validation.accepted for candidate in candidates)
    assert [candidate.world.seed for candidate in candidates] == [plan.seed for plan in expected_plans]


def test_candidate_builder_must_use_plan_seed() -> None:
    spec = _spec(WorldRequirement(id="facts", kind=RequirementKind.FACT))
    plan = plan_candidates(spec, count=1)[0]
    wrong_world = replace(_build(plan), seed=plan.seed + 1)

    with pytest.raises(ValueError, match="does not match plan seed"):
        validate_candidate(plan, spec, wrong_world)


def test_hard_unsatisfied_requirement_rejects_candidate() -> None:
    spec = _spec(
        WorldRequirement(
            id="impossible-artifact",
            kind=RequirementKind.ARTIFACT,
            selector={"artifact_type": "artifact_that_does_not_exist"},
        )
    )
    plan = plan_candidates(spec, count=1)[0]
    world = _build(plan)

    verdict = validate_candidate(plan, spec, world)

    assert not verdict.accepted
    assert verdict.checks[0].requirement_id == "impossible-artifact"
    assert verdict.checks[0].observed == 0


def test_soft_requirement_is_reported_but_does_not_reject() -> None:
    spec = _spec(
        WorldRequirement(
            id="optional-distractor",
            kind=RequirementKind.DISTRACTOR,
            selector={"artifact_type": "artifact_that_does_not_exist"},
            hard=False,
        ),
        WorldRequirement(id="facts", kind=RequirementKind.FACT),
    )
    plan = plan_candidates(spec, count=1)[0]
    verdict = validate_candidate(plan, spec, _build(plan))

    assert verdict.accepted
    by_id = {check.requirement_id: check for check in verdict.checks}
    assert not by_id["optional-distractor"].satisfied
    assert by_id["facts"].satisfied
