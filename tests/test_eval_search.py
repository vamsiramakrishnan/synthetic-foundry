from __future__ import annotations

from worldloom.eval_design import EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement
from worldloom.eval_search import CandidateContext, search_candidates
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _spec() -> EvalSpec:
    return EvalSpec(
        id="EVALSPEC-ADAPTIVE",
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
        candidate_count=3,
    )


def test_adaptive_builder_receives_deterministic_prior_validation_only() -> None:
    seen: list[CandidateContext] = []

    def builder(context: CandidateContext):  # type: ignore[no-untyped-def]
        seen.append(context)
        return RetailWorld(seed=context.plan.seed).build().run(MonthEndClose(period="2026-03"))

    attempts = search_candidates(_spec(), builder)

    assert len(attempts) == 3
    assert [len(context.history) for context in seen] == [0, 1, 2]
    assert seen[1].history[0].ordinal == 0
    assert seen[1].history[0].failed == ("revision-chain",)
    assert not seen[1].history[0].accepted
    assert seen[2].history == tuple(
        feedback
        for context in seen[1:]
        for feedback in context.history[-1:]
    )
    assert all(not attempt.validation.accepted for attempt in attempts)


def test_adaptive_search_replays_identically() -> None:
    def builder(context: CandidateContext):  # type: ignore[no-untyped-def]
        return RetailWorld(seed=context.plan.seed).build().run(MonthEndClose(period="2026-03"))

    first = search_candidates(_spec(), builder)
    second = search_candidates(_spec(), builder)

    assert [attempt.plan for attempt in first] == [attempt.plan for attempt in second]
    assert [attempt.validation for attempt in first] == [attempt.validation for attempt in second]
