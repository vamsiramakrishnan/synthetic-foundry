from worldloom.eval_candidates import validate_candidate
from worldloom.eval_construction import apply_revision_family
from worldloom.eval_design import EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement
from worldloom.eval_tactics import TacticKind, TacticProposal
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _world(seed: int = 8128):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=seed).build().run(MonthEndClose(period="2026-03"))


def test_revision_tactic_constructs_real_revises_chain() -> None:
    world = _world()
    base = next(intent for intent in world.artifact_intents if intent.artifact_type == "finance_workbook")
    proposal = TacticProposal(
        id="tactic:revision-family",
        kind=TacticKind.REVISION_FAMILY,
        covers=("revision-chain",),
        cost=4,
        parameters={"artifact_type": "finance_workbook", "minimum": 3},
    )

    revised = apply_revision_family(world, proposal)
    matching = [intent for intent in revised.artifact_intents if intent.artifact_type == "finance_workbook"]

    assert len(matching) >= 3
    revisions = {intent.id: intent.revises for intent in matching}
    assert any(predecessor == base.id for predecessor in revisions.values())
    assert len(revised.artifact_irs) == 0
    assert proposal.id in revised.recipe["eval_tactics"]


def test_revision_tactic_makes_revision_eval_valid() -> None:
    spec = EvalSpec(
        id="EVALSPEC-CONSTRUCT-REVISIONS",
        capability="revision_reasoning",
        persona="controller",
        request_template="Compare the current workbook with prior revisions.",
        steps=(EvalStepSpec(id="find", capability="find"),),
        requirements=(
            WorldRequirement(id="facts", kind=RequirementKind.FACT),
            WorldRequirement(
                id="revision-chain",
                kind=RequirementKind.REVISION_CHAIN,
                selector={"artifact_type": "finance_workbook"},
                minimum=3,
            ),
        ),
        candidate_count=1,
    )
    plan = spec.model_copy(update={"candidate_count": 1})
    from worldloom.eval_design import plan_candidates

    candidate_plan = plan_candidates(plan)[0]
    world = _world(candidate_plan.seed)
    before = validate_candidate(candidate_plan, spec, world)
    proposal = TacticProposal(
        id="tactic:revision-family",
        kind=TacticKind.REVISION_FAMILY,
        covers=("revision-chain",),
        cost=4,
        parameters={"artifact_type": "finance_workbook", "minimum": 3},
    )
    revised = apply_revision_family(world, proposal)
    after = validate_candidate(candidate_plan, spec, revised)

    assert not before.accepted
    assert after.accepted
    check = next(item for item in after.checks if item.requirement_id == "revision-chain")
    assert check.observed >= 3
    assert len(check.evidence_ids) >= 3


def test_revision_tactic_is_idempotent_once_requirement_is_met() -> None:
    world = _world()
    proposal = TacticProposal(
        id="tactic:revision-family",
        kind=TacticKind.REVISION_FAMILY,
        covers=("revision-chain",),
        cost=4,
        parameters={"artifact_type": "finance_workbook", "minimum": 2},
    )

    once = apply_revision_family(world, proposal)
    twice = apply_revision_family(once, proposal)

    assert twice == once
