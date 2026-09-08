from __future__ import annotations

import json
from dataclasses import replace

import pytest

from worldloom.eval_reference import ProofStatus
from worldloom.evals import (
    EvalCampaign,
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    emulator_executor,
)
from worldloom.models import EnterpriseEvent
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


def _event_campaign(*, candidate_count: int = 1) -> EvalCampaign:
    return EvalCampaign(EvalSpec(
        id="EVALSPEC-CAMPAIGN-EVENT",
        capability="incident_triage",
        persona="incident manager",
        request_template="Find the incident bridge announcement.",
        steps=(EvalStepSpec(id="find", capability="search"),),
        requirements=(WorldRequirement(
            id="bridge", kind=RequirementKind.EVENT,
            selector={"kind": "incident.bridge_opened"},
        ),),
        candidate_count=candidate_count,
    ))


def test_finalization_rebinds_evidence_and_retains_newly_rejected_attempts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    run = _event_campaign(candidate_count=2).construct(_builder)
    rejected_seed = run.attempts[1].plan.seed
    old_evidence = run.instances[0].oracle.event_ids

    def move_evidence(world):  # type: ignore[no-untyped-def]
        events = tuple(
            event.model_copy(update={
                "id": "EV-FINAL-BRIDGE",
                "kind": "incident.bridge_closed" if world.seed == rejected_seed else event.kind,
            }) if event.kind == "incident.bridge_opened" else event
            for event in world.events
        )
        return replace(world, _events=events)

    finalized = run.map_worlds(move_evidence)

    assert len(run.accepted) == 2, "finalization must leave the original snapshot intact"
    assert len(finalized.attempts) == 2
    assert len(finalized.accepted) == len(finalized.rejected) == 1
    assert len(finalized.instances) == 1
    assert finalized.instances[0].oracle.event_ids == ("EV-FINAL-BRIDGE",)
    assert finalized.instances[0].oracle.event_ids != old_evidence
    assert finalized.failed_requirements == {1: ("bridge",)}
    for before, after, candidate in zip(run.constructions, finalized.constructions, finalized.attempts, strict=True):
        assert after.candidate is candidate
        assert after.findings == before.findings
        assert after.applied_tactic_ids == before.applied_tactic_ids
    root = finalized.export(tmp_path / "finalized")
    manifest = json.loads((root / "manifest.json").read_text())
    assert len(manifest["attempts"]) == len(manifest["constructions"]) == 2
    assert [item["validation"]["accepted"] for item in manifest["attempts"]] == [True, False]
    assert manifest["failed_requirements"] == {"1": ["bridge"]}


def test_constructed_run_finalizes_proves_and_exports_without_rebuilding(tmp_path) -> None:  # type: ignore[no-untyped-def]
    campaign = EvalCampaign(EvalSpec(
        id="EVALSPEC-CAMPAIGN-ONCE",
        capability="message_search",
        persona="incident manager",
        request_template="Find the urgent message.",
        steps=(EvalStepSpec(id="find", capability="search", connector="teams",
                            entity="channel_message", operation="search"),),
        requirements=(WorldRequirement(
            id="urgent-message", kind=RequirementKind.CONNECTOR,
            selector={"connector": "teams", "entity": "channel_message", "importance": "urgent"},
        ),),
        candidate_count=1,
    ))
    calls = []

    def builder(plan):  # type: ignore[no-untyped-def]
        calls.append(plan.seed)
        return _builder(plan)

    constructed = campaign.construct(builder)
    finalized = constructed.map_worlds(lambda world: world.compile())
    proofs = finalized.prove(emulator_executor())
    root = finalized.export(tmp_path / "constructed", formats=("markdown",))

    assert calls == [campaign.plans()[0].seed]
    assert len(proofs) == 1
    assert proofs[0].status == ProofStatus.PROVEN_EXECUTABLE, proofs[0].failure
    assert proofs[0].steps[0].output_ids
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["candidate_count"] == 1
    assert manifest["constructions"][0]["applied"] == list(constructed.constructions[0].applied_tactic_ids)
    instance_path = root / manifest["candidates"][0]["path"] / "eval-instance.json"
    assert json.loads(instance_path.read_text())["oracle"] == finalized.instances[0].oracle.model_dump(mode="json")


def test_finalization_can_recover_previously_rejected_attempts() -> None:
    campaign = _event_campaign()
    run = campaign.run(_builder)
    assert len(run.rejected) == 1

    def add_evidence(world):  # type: ignore[no-untyped-def]
        event = EnterpriseEvent(
            id="EV-FINAL-BRIDGE", kind="incident.bridge_opened",
            occurred_at=max(event.occurred_at for event in world.events),
            summary="Incident bridge opened.",
        )
        return replace(world, _events=(*world._events, event))

    finalized = run.map_worlds(add_evidence)

    assert len(finalized.attempts) == len(finalized.accepted) == 1
    assert finalized.instances[0].oracle.event_ids == ("EV-FINAL-BRIDGE",)
    assert len(run.rejected) == 1


def test_finalization_retains_refused_constructions() -> None:
    campaign = EvalCampaign(_campaign().spec.model_copy(update={
        "requirements": (WorldRequirement(
            id="unavailable-fact", kind=RequirementKind.FACT,
            selector={"kind": "unavailable_fact"},
        ),),
    }))
    run = campaign.construct(_builder)
    assert run.constructions[0].findings

    finalized = run.map_worlds(lambda world: world.compile())

    assert len(finalized.rejected) == 1
    assert finalized.constructions[0].findings == run.constructions[0].findings
    assert finalized.constructions[0].candidate is finalized.attempts[0]


def test_campaign_search_reuses_adaptive_feedback_and_keeps_all_attempts() -> None:
    campaign = _event_campaign(candidate_count=2)
    histories = []

    def builder(context):  # type: ignore[no-untyped-def]
        histories.append(context.history)
        world = _builder(context.plan)
        if context.plan.ordinal == 0:
            return world
        event = EnterpriseEvent(
            id="EV-SEARCH-BRIDGE", kind="incident.bridge_opened",
            occurred_at=max(event.occurred_at for event in world.events),
            summary="Incident bridge opened.",
        )
        return replace(world, _events=(*world._events, event))

    run = campaign.search(builder)

    assert len(run.attempts) == 2
    assert len(run.rejected) == len(run.accepted) == len(run.instances) == 1
    assert histories[0] == ()
    assert histories[1][0].failed == ("bridge",)
    assert not histories[1][0].accepted


def test_finalization_never_promotes_deselected_candidates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    run = _event_campaign(candidate_count=3).construct(_builder)
    chosen = run.select(1)
    assert len(chosen.attempts) == len(chosen.accepted) == 3
    assert len(chosen.selected) == len(chosen.instances) == 1
    selected_seed = chosen.selected[0].plan.seed
    visited = []

    def remove_selected_evidence(world):  # type: ignore[no-untyped-def]
        visited.append(world.seed)
        if world.seed != selected_seed:
            return world
        return replace(world, _events=tuple(
            event for event in world.events if event.kind != "incident.bridge_opened"
        ))

    finalized = chosen.map_worlds(remove_selected_evidence)

    assert visited == [candidate.plan.seed for candidate in run.attempts]
    assert finalized.selected_ordinals == chosen.selected_ordinals
    assert len(finalized.accepted) == 2
    assert not finalized.selected
    assert not finalized.instances
    assert finalized.prove(emulator_executor()) == ()
    root = finalized.export(tmp_path / "selected")
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["attempt_count"] == 3
    assert manifest["accepted_count"] == 2
    assert manifest["candidate_count"] == 0
    assert manifest["selected_ordinals"] == list(chosen.selected_ordinals)
    assert not manifest["candidates"]
