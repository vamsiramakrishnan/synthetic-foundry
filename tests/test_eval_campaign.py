from __future__ import annotations

from worldloom.evals import (
    EvalCampaign,
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _campaign() -> EvalCampaign:
    return EvalCampaign(
        EvalSpec(
            id="EVALSPEC-CAMPAIGN",
            capability="evidence_retrieval",
            persona="controller",
            request_template="Find the evidence and verify the result.",
            steps=(
                EvalStepSpec(id="find", capability="search"),
                EvalStepSpec(id="verify", capability="verify", depends_on=("find",), effect="verify"),
            ),
            requirements=(WorldRequirement(id="facts", kind=RequirementKind.FACT),),
            candidate_count=1,
        )
    )


def test_plans_exist_without_running_builder() -> None:
    campaign = _campaign()
    called = False

    def builder(plan):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return RetailWorld(seed=plan.seed).build()

    plans = campaign.plans()

    assert plans
    assert not called
    assert builder is not None


def test_campaign_instantiates_only_after_candidate_generation() -> None:
    campaign = _campaign()
    seen = []

    def builder(plan):  # type: ignore[no-untyped-def]
        seen.append(plan.seed)
        return RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03"))

    instances = campaign.instantiate(builder)

    assert len(instances) == 1
    assert seen == [campaign.plans()[0].seed]
    assert instances[0].candidate_seed == seen[0]
    assert instances[0].oracle.fact_ids
