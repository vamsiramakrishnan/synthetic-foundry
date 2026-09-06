"""The eval drives generation: a demand becomes world state, replayably.

Before this layer existed, ``construct_candidate`` executed one tactic kind
and reported every other requirement as ``unsupported_construction``, so an
eval could only *filter* the worlds a vertical happened to build. These tests
pin the contract of the constructive layer: a base world that fails the eval
is made to pass it through recipe verbs, the validator that accepts it is the
one that knows nothing about the constructions, the emulator finds what was
minted through the same search an agent would run, near misses fail by one
clause, and the whole candidate rebuilds from its recipe in a fresh world.
"""
from __future__ import annotations

from datetime import UTC, datetime

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator
from worldloom.eval_candidates import _connector_records, validate_candidate
from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    plan_candidates,
)
from worldloom.eval_interventions import construct_candidate
from worldloom.eval_reference import ProofStatus, execute_reference
from worldloom.eval_witnesses import witness_payload
from worldloom.evals import EvalCampaign, emulator_executor
from worldloom.predicates import Predicate
from worldloom.recipe import rebuild
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose

AT = datetime(2026, 9, 1, 9, tzinfo=UTC)


def _base(seed: int):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=seed).build().run(MonthEndClose(period="2026-03"))


def _spec() -> EvalSpec:
    """A design no retail close satisfies on its own, across five demand kinds."""

    return EvalSpec(
        id="EVALSPEC-CONSTRUCTED",
        capability="incident_triage",
        persona="major incident manager",
        request_template="Find the open critical incidents, note them on the tracking issue.",
        steps=(
            EvalStepSpec(id="find", capability="search", connector="servicenow",
                         entity="incident", operation="search"),
            EvalStepSpec(id="ask", capability="search", connector="teams",
                         entity="channel_message", operation="search", depends_on=("find",)),
            EvalStepSpec(id="note", capability="comment", connector="jira", entity="issue",
                         operation="comment", effect="write", depends_on=("find", "ask")),
        ),
        requirements=(
            WorldRequirement(
                id="critical-incidents", kind=RequirementKind.CONNECTOR,
                selector={"connector": "servicenow", "entity": "incident",
                          "priority": "1 - Critical", "state": "New"},
                minimum=2,
            ),
            WorldRequirement(
                id="teams-thread", kind=RequirementKind.CONNECTOR,
                selector={"connector": "teams", "entity": "channel_message", "importance": "urgent"},
            ),
            WorldRequirement(
                id="board-policy", kind=RequirementKind.PERMISSION,
                selector={"label": "Incident bridge"},
            ),
            WorldRequirement(
                id="three-workbooks", kind=RequirementKind.ARTIFACT,
                selector={"artifact_type": "finance_workbook"}, minimum=3,
            ),
            WorldRequirement(
                id="bridge-event", kind=RequirementKind.EVENT,
                selector={"kind": "incident.bridge_opened"},
            ),
        ),
        candidate_count=1,
    )


def _construct():  # type: ignore[no-untyped-def]
    spec = _spec()
    plan = plan_candidates(spec)[0]
    base = _base(plan.seed)
    return spec, plan, base, construct_candidate(spec, plan, base, occurred_at=AT)


def test_the_base_world_fails_the_eval_and_the_constructed_one_passes() -> None:
    spec, plan, base, result = _construct()

    before = validate_candidate(plan, spec, base)
    assert not before.accepted
    assert {check.requirement_id for check in before.checks if not check.satisfied} == {
        "critical-incidents", "teams-thread", "board-policy", "three-workbooks", "bridge-event",
    }

    assert result.findings == ()
    assert result.candidate.validation.accepted
    # Six tactics: five requirement demands plus the write step's precondition.
    assert len(result.applied_tactic_ids) == 6


def test_witnesses_are_found_by_the_emulator_and_near_misses_fail_one_clause() -> None:
    _, _, _, result = _construct()
    world = result.candidate.world
    definition = load_connector_definition("servicenow")
    emulator = ConnectorEmulator(definition, _connector_records(world, "servicenow"))

    asked = Predicate.equalities({"priority": "1 - Critical", "state": "New"}, entity="incident")
    page = emulator.call("search_incidents" if "search_incidents" in definition.tools
                         else definition.tool_for("incident", "search"),
                         entity="incident", predicate=asked, max_results=50)
    assert page["total"] == 2

    # One near miss per constrained field, each failing exactly its own clause.
    misses = [event for event in world.events
              if (payload := witness_payload(event)) and payload["role"] == "near_miss"
              and payload["connector"] == "servicenow"]
    assert sorted(payload["near_miss_of"] for payload in map(witness_payload, misses)) == ["priority", "state"]
    for event in misses:
        payload = witness_payload(event)
        assert payload is not None
        fields = payload["fields"]
        failing = [f for f in ("priority", "state") if fields[f] != asked.where[[w.field for w in asked.where].index(f)].value]
        assert failing == [payload["near_miss_of"]]
    # Picklist near misses are values the product would accept.
    priority_miss = next(witness_payload(e) for e in misses if witness_payload(e)["near_miss_of"] == "priority")  # type: ignore[index]
    assert priority_miss["fields"]["priority"] in definition.options["priority"]


def test_a_connector_with_no_engine_projection_is_still_constructible() -> None:
    _, _, _, result = _construct()
    records = _connector_records(result.candidate.world, "teams")
    assert [record.entity for record in records].count("channel_message") >= 1
    assert all(record.fields["importance"] == "urgent" for record in records
               if record.fields.get("witness_role") == "witness")


def test_constructions_are_recipe_verbs_and_replay() -> None:
    _, _, _, result = _construct()
    world = result.candidate.world
    verbs = [step["scenario"] for step in world.recipe["steps"]]
    assert {"EvalDemands", "EvalWitnesses", "EvalPrecondition", "EvalAccessPolicy",
            "EvalArtifactFamily", "EvalEvents"} <= set(verbs)

    again = rebuild(world.recipe)
    assert again.recipe == world.recipe
    assert tuple(again.events) == tuple(world.events)
    assert [i.model_dump() for i in again.artifact_intents] == [i.model_dump() for i in world.artifact_intents]
    assert tuple(again.access_policies) == tuple(world.access_policies)


def test_construction_is_deterministic() -> None:
    _, _, _, first = _construct()
    _, _, _, second = _construct()
    assert tuple(first.candidate.world.events) == tuple(second.candidate.world.events)
    assert first.applied_tactic_ids == second.applied_tactic_ids


def test_a_fact_demand_is_refused_with_the_seam_that_owns_it() -> None:
    spec = EvalSpec(
        id="EVALSPEC-FACT-REFUSAL", capability="lookup", persona="analyst",
        request_template="Find the figure.",
        steps=(EvalStepSpec(id="find", capability="search"),),
        requirements=(WorldRequirement(id="figure", kind=RequirementKind.FACT,
                                       selector={"kind": "no_such_fact_kind"}),),
        candidate_count=1,
    )
    plan = plan_candidates(spec)[0]
    result = construct_candidate(spec, plan, _base(plan.seed), occurred_at=AT)
    assert not result.candidate.validation.accepted
    assert [f.code for f in result.findings] == ["construction_refused"]
    assert "episode" in result.findings[0].detail


def test_the_campaign_constructs_binds_and_proves_through_the_emulator() -> None:
    campaign = EvalCampaign(_spec())

    run = campaign.construct(lambda plan: _base(plan.seed), occurred_at=AT)

    assert len(run.instances) == 1
    assert run.constructions[0].findings == ()
    instance = run.instances[0]
    assert instance.oracle.connector_record_ids
    proof = execute_reference(instance, run.accepted[0].world, emulator_executor())
    assert proof.status == ProofStatus.PROVEN_EXECUTABLE, proof.failure
    by_step = {step.step_id: step for step in proof.steps}
    assert by_step["find"].output_ids
    assert by_step["note"].effect_ids, "the comment landed on the precondition record"


def test_a_satisfied_requirement_is_left_to_the_vertical() -> None:
    """A demand the base already meets mints nothing: the engine's state wins."""

    spec = EvalSpec(
        id="EVALSPEC-ALREADY-THERE", capability="lookup", persona="analyst",
        request_template="Find a workbook.",
        steps=(EvalStepSpec(id="find", capability="search"),),
        requirements=(WorldRequirement(id="one-workbook", kind=RequirementKind.ARTIFACT,
                                       selector={"artifact_type": "finance_workbook"}),),
        candidate_count=1,
    )
    plan = plan_candidates(spec)[0]
    base = _base(plan.seed)
    result = construct_candidate(spec, plan, base, occurred_at=AT)
    assert result.candidate.validation.accepted
    assert result.applied_tactic_ids == ()
    assert tuple(result.candidate.world.artifact_intents) == tuple(base.artifact_intents)


def test_a_constructed_campaign_exports_its_findings_beside_the_corpora(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    campaign = EvalCampaign(_spec())
    root = campaign.export(lambda plan: _base(plan.seed), tmp_path / "campaign",
                           construct=True, occurred_at=AT, formats=("markdown",))
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["candidate_count"] == 1
    assert manifest["constructions"][0]["findings"] == []
    assert len(manifest["constructions"][0]["applied"]) == 6
    corpus = root / "candidates" / manifest["candidates"][0]["path"].split("/")[-1] / "corpus"
    recipe = json.loads((corpus / "world.json").read_text())["recipe"]
    assert "EvalWitnesses" in {step["scenario"] for step in recipe["steps"]}
