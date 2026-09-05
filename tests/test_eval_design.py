from __future__ import annotations

import pytest
from pydantic import ValidationError

from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    candidate_seed,
    design_digest,
    plan_candidates,
)


def _spec() -> EvalSpec:
    return EvalSpec(
        id="EVALSPEC-FORECAST-AUTHORITY",
        capability="cross_surface_authority_resolution",
        persona="finance director",
        request_template=(
            "Find the approved forecast, explain why it changed from the prior version, "
            "and identify the unresolved operational risk behind the largest downside."
        ),
        steps=(
            EvalStepSpec(id="find", capability="search", connector="drive"),
            EvalStepSpec(
                id="compare", capability="version_compare", depends_on=("find",), effect="transform"
            ),
            EvalStepSpec(
                id="trace-risk",
                capability="cross_connector_join",
                depends_on=("compare",),
                connector="servicenow",
            ),
            EvalStepSpec(
                id="verify", capability="evidence_check", depends_on=("trace-risk",), effect="verify"
            ),
        ),
        requirements=(
            WorldRequirement(
                id="forecast-chain",
                kind=RequirementKind.REVISION_CHAIN,
                selector={"artifact_type": "finance_workbook"},
                minimum=2,
            ),
            WorldRequirement(
                id="approved-forecast",
                kind=RequirementKind.ARTIFACT,
                selector={"artifact_type": "finance_workbook", "lifecycle": "approved"},
            ),
            WorldRequirement(
                id="operational-risk",
                kind=RequirementKind.CONNECTOR,
                selector={"connector": "servicenow", "record_type": "incident"},
            ),
            WorldRequirement(
                id="stale-copy",
                kind=RequirementKind.DISTRACTOR,
                selector={"artifact_type": "finance_workbook", "lifecycle": "superseded"},
            ),
        ),
        candidate_count=3,
        difficulty="hard",
    )


def test_candidate_plans_are_deterministic_and_distinct() -> None:
    spec = _spec()
    first = plan_candidates(spec)
    second = plan_candidates(spec)

    assert first == second
    assert [plan.ordinal for plan in first] == [0, 1, 2]
    assert len({plan.seed for plan in first}) == 3
    assert {plan.design_digest for plan in first} == {design_digest(spec)}


def test_eval_edit_changes_candidate_family() -> None:
    spec = _spec()
    changed = spec.model_copy(update={"difficulty": "medium"})

    assert design_digest(changed) != design_digest(spec)
    assert candidate_seed(changed, 0) != candidate_seed(spec, 0)


def test_task_dag_refuses_forward_dependencies() -> None:
    with pytest.raises(ValidationError, match="missing or later"):
        EvalSpec(
            id="EVALSPEC-BROKEN",
            capability="broken",
            persona="operator",
            request_template="Do the thing",
            steps=(
                EvalStepSpec(id="second", capability="write", depends_on=("first",)),
                EvalStepSpec(id="first", capability="read"),
            ),
            requirements=(WorldRequirement(id="fact", kind=RequirementKind.FACT),),
        )


def test_eval_requires_world_conditions_before_candidates_exist() -> None:
    with pytest.raises(ValidationError, match="at least one world requirement"):
        EvalSpec(
            id="EVALSPEC-NO-WORLD",
            capability="retrieval",
            persona="analyst",
            request_template="Find it",
            steps=(EvalStepSpec(id="read", capability="search"),),
            requirements=(),
        )


def test_candidate_count_override_does_not_mutate_design() -> None:
    spec = _spec()
    plans = plan_candidates(spec, count=1)

    assert len(plans) == 1
    assert plans[0].seed == candidate_seed(spec, 0)
    assert spec.candidate_count == 3
