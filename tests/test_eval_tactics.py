from worldloom.eval_demands import DemandKind, DemandSet, WorldDemand
from worldloom.eval_tactics import TacticKind, plan_tactics, propose_tactics


def _demands() -> DemandSet:
    return DemandSet(
        eval_spec_id="EVALSPEC-TACTICS",
        design_digest="abc",
        demands=(
            WorldDemand(
                id="incident-search",
                kind=DemandKind.SEARCH,
                source_requirement_ids=("r1",),
                selector={"connector": "servicenow", "episode": "incident"},
                minimum=3,
            ),
            WorldDemand(
                id="incident-evidence",
                kind=DemandKind.EVIDENCE,
                source_requirement_ids=("r2",),
                selector={"episode": "incident", "connector": "servicenow"},
            ),
            WorldDemand(
                id="access",
                kind=DemandKind.PERMISSION,
                source_requirement_ids=("r3",),
                selector={"persona": "operator", "effect": "deny"},
            ),
        ),
    )


def test_tactic_field_contains_combined_episode_cover() -> None:
    proposals = propose_tactics(_demands())
    combined = [proposal for proposal in proposals if len(proposal.covers) > 1]

    assert len(combined) == 1
    assert combined[0].kind == TacticKind.EVIDENCE_EPISODE
    assert set(combined[0].covers) == {"incident-search", "incident-evidence"}


def test_weighted_cover_prefers_coherent_episode() -> None:
    plan = plan_tactics(_demands())

    assert plan.complete
    assert any(set(proposal.covers) == {"incident-search", "incident-evidence"} for proposal in plan.proposals)
    assert any(proposal.kind == TacticKind.ACCESS_POLICY for proposal in plan.proposals)
    assert len(plan.proposals) == 2


def test_revision_chain_maps_to_revision_family() -> None:
    demands = DemandSet(
        eval_spec_id="EVALSPEC-REVISIONS",
        design_digest="abc",
        demands=(
            WorldDemand(
                id="revisions",
                kind=DemandKind.STATE,
                source_requirement_ids=("r1",),
                selector={"requirement_kind": "revision_chain", "artifact_type": "finance_workbook"},
                minimum=3,
            ),
        ),
    )

    plan = plan_tactics(demands)
    assert plan.complete
    assert plan.proposals[0].kind == TacticKind.REVISION_FAMILY
    assert plan.proposals[0].parameters["minimum"] == 3
