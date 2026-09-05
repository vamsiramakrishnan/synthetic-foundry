"""Deterministic generation-tactic planning for eval-first worlds.

Tactics describe *how* an existing Worldloom builder should be steered. They do
not construct connector records directly and they never decide candidate
validity. The planner intentionally starts with weighted greedy cover; a solver
is unnecessary until the tactic vocabulary becomes expressive enough to earn it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .eval_demands import DemandKind, DemandSet, WorldDemand
from .models import Model


class TacticKind(StrEnum):
    EVIDENCE_EPISODE = "evidence_episode"
    SEARCH_WITNESSES = "search_witnesses"
    ARTIFACT_FAMILY = "artifact_family"
    REVISION_FAMILY = "revision_family"
    ACCESS_POLICY = "access_policy"
    TEMPORAL_SEQUENCE = "temporal_sequence"
    MUTATION_PRECONDITION = "mutation_precondition"
    DISTRACTOR_SET = "distractor_set"


class TacticProposal(Model):
    id: str
    kind: TacticKind
    covers: tuple[str, ...]
    cost: int = Field(ge=1)
    parameters: dict[str, str | int | bool] = Field(default_factory=dict)


class TacticPlan(Model):
    eval_spec_id: str
    demand_digest: str
    proposals: tuple[TacticProposal, ...]
    uncovered: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.uncovered


def _selector_key(demand: WorldDemand) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in demand.selector.items()))


def _proposal_for(demand: WorldDemand) -> TacticProposal:
    selector = {key: value for key, value in demand.selector.items() if key != "requirement_kind"}
    common = dict(selector)
    common["minimum"] = demand.minimum
    if demand.kind == DemandKind.SEARCH:
        kind = TacticKind.SEARCH_WITNESSES
        cost = 2 + demand.minimum
    elif demand.kind == DemandKind.ARTIFACT:
        kind = TacticKind.ARTIFACT_FAMILY
        cost = 3
    elif demand.kind == DemandKind.PERMISSION:
        kind = TacticKind.ACCESS_POLICY
        cost = 2
    elif demand.kind == DemandKind.TEMPORAL:
        kind = TacticKind.TEMPORAL_SEQUENCE
        cost = 2
    elif demand.kind == DemandKind.MUTATION:
        kind = TacticKind.MUTATION_PRECONDITION
        cost = 3
    elif demand.kind == DemandKind.CARDINALITY:
        kind = TacticKind.DISTRACTOR_SET
        cost = 1 + demand.minimum
    elif demand.kind == DemandKind.STATE and demand.selector.get("requirement_kind") == "revision_chain":
        kind = TacticKind.REVISION_FAMILY
        cost = 2 + demand.minimum
    else:
        kind = TacticKind.EVIDENCE_EPISODE
        cost = 2
    return TacticProposal(
        id=f"tactic:{kind.value}:{demand.id}",
        kind=kind,
        covers=(demand.id,),
        cost=cost,
        parameters=common,
    )


def propose_tactics(demands: DemandSet) -> tuple[TacticProposal, ...]:
    """Produce a bounded deterministic tactic field.

    Compatible evidence/search/artifact demands with the same selector are also
    offered as one episode proposal. This is the first anti-Frankenstein rule:
    prefer one coherent episode when it can satisfy several obligations.
    """

    proposals = [_proposal_for(demand) for demand in demands.demands]
    groups: dict[tuple[tuple[str, str], ...], list[WorldDemand]] = {}
    for demand in demands.demands:
        if demand.kind in {DemandKind.EVIDENCE, DemandKind.SEARCH, DemandKind.ARTIFACT, DemandKind.STATE}:
            groups.setdefault(_selector_key(demand), []).append(demand)
    for key, group in sorted(groups.items(), key=lambda item: repr(item[0])):
        if len(group) < 2:
            continue
        covered = tuple(sorted(demand.id for demand in group))
        parameters = {name: value for name, value in key if name != "requirement_kind"}
        proposals.append(
            TacticProposal(
                id="tactic:evidence_episode:" + "+".join(covered),
                kind=TacticKind.EVIDENCE_EPISODE,
                covers=covered,
                cost=max(2, sum(_proposal_for(demand).cost for demand in group) // 2),
                parameters=parameters,
            )
        )
    return tuple(sorted(proposals, key=lambda proposal: proposal.id))


def plan_tactics(demands: DemandSet) -> TacticPlan:
    """Cover hard demands using deterministic weighted greedy set cover."""

    import hashlib
    import json

    field = list(propose_tactics(demands))
    hard = {demand.id for demand in demands.demands if demand.hard}
    uncovered = set(hard)
    chosen: list[TacticProposal] = []
    while uncovered:
        candidates: list[tuple[float, int, str, TacticProposal]] = []
        for proposal in field:
            gain = len(uncovered & set(proposal.covers))
            if not gain:
                continue
            score = gain / proposal.cost
            candidates.append((-score, proposal.cost, proposal.id, proposal))
        if not candidates:
            break
        _, _, _, best = min(candidates)
        chosen.append(best)
        uncovered -= set(best.covers)
        field = [proposal for proposal in field if proposal.id != best.id]

    payload = json.dumps(demands.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return TacticPlan(
        eval_spec_id=demands.eval_spec_id,
        demand_digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        proposals=tuple(chosen),
        uncovered=tuple(sorted(uncovered)),
    )


__all__ = ["TacticKind", "TacticPlan", "TacticProposal", "plan_tactics", "propose_tactics"]
