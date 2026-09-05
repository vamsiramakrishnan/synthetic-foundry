from __future__ import annotations

import json

import pytest

from worldloom.evals import (
    EvalCampaign,
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _campaign(*, candidate_count: int = 1) -> EvalCampaign:
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
            candidate_count=candidate_count,
        )
    )


def _builder(plan):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03"))


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


def test_campaign_compiles_demands_and_tactics_before_data() -> None:
    campaign = _campaign()

    demands = campaign.demands()
    tactics = campaign.tactics()

    assert demands.eval_spec_id == campaign.spec.id
    assert demands.demands
    assert tactics.eval_spec_id == campaign.spec.id
    assert tactics.complete
    assert tactics.proposals


def test_campaign_instantiates_only_after_candidate_generation() -> None:
    campaign = _campaign()
    seen = []

    def builder(plan):  # type: ignore[no-untyped-def]
        seen.append(plan.seed)
        return _builder(plan)

    instances = campaign.instantiate(builder)

    assert len(instances) == 1
    assert seen == [campaign.plans()[0].seed]
    assert instances[0].candidate_seed == seen[0]
    assert instances[0].oracle.fact_ids


def test_campaign_run_keeps_rejected_attempts_as_search_feedback() -> None:
    campaign = EvalCampaign(
        EvalSpec(
            id="EVALSPEC-REJECTION-FEEDBACK",
            capability="revision_reasoning",
            persona="controller",
            request_template="Find the approved workbook and compare it with its predecessor.",
            steps=(EvalStepSpec(id="find", capability="search"),),
            requirements=(
                WorldRequirement(id="facts", kind=RequirementKind.FACT),
                WorldRequirement(
                    id="revision-chain",
                    kind=RequirementKind.REVISION_CHAIN,
                    selector={"artifact_type": "finance_workbook"},
                    minimum=2,
                ),
            ),
            candidate_count=2,
        )
    )

    run = campaign.run(_builder)

    assert len(run.attempts) == 2
    assert not run.accepted
    assert len(run.rejected) == 2
    assert not run.instances
    assert run.failed_requirements == {0: ("revision-chain",), 1: ("revision-chain",)}


def test_campaign_can_select_diverse_valid_worlds_by_outcome() -> None:
    run = _campaign(candidate_count=3).run(_builder)

    selected = run.diverse(2)

    assert len(selected) == 2
    assert all(candidate.validation.accepted for candidate in selected)
    assert len({candidate.plan.ordinal for candidate in selected}) == 2
    assert run.diverse(2) == selected
    with pytest.raises(ValueError, match="cannot select"):
        run.diverse(4)


def test_campaign_export_pairs_eval_with_exact_candidate_corpus(tmp_path) -> None:  # type: ignore[no-untyped-def]
    campaign = _campaign()
    root = campaign.export(_builder, tmp_path / "campaign")

    spec = json.loads((root / "eval-spec.json").read_text())
    demands = json.loads((root / "demand-set.json").read_text())
    tactics = json.loads((root / "tactic-plan.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    assert spec["id"] == campaign.spec.id
    assert demands["eval_spec_id"] == campaign.spec.id
    assert tactics["eval_spec_id"] == campaign.spec.id
    assert tactics["proposals"]
    assert manifest["schema"] == "worldloom.eval-campaign/v1"
    assert manifest["attempt_count"] == 1
    assert manifest["candidate_count"] == 1
    assert manifest["rejected_count"] == 0
    assert manifest["failed_requirements"] == {}
    assert manifest["tactic_count"] == len(tactics["proposals"])
    assert manifest["demand_digest"] == tactics["demand_digest"]

    candidate_dir = root / manifest["candidates"][0]["path"]
    instance = json.loads((candidate_dir / "eval-instance.json").read_text())
    world = json.loads((candidate_dir / "corpus" / "world.json").read_text())
    validation = json.loads((candidate_dir / "candidate-validation.json").read_text())

    assert instance["candidate_seed"] == world["seed"]
    assert instance["candidate_seed"] == manifest["candidates"][0]["seed"]
    assert validation["accepted"] is True
    assert set(instance["oracle"]["fact_ids"])
    assert (candidate_dir / "corpus" / "facts.jsonl").is_file()
