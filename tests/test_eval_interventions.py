import json
from datetime import UTC, datetime

from worldloom.eval_demands import compile_demands
from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.eval_interventions import demand_events, intervene
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _spec() -> EvalSpec:
    return EvalSpec(
        id="EVALSPEC-DEMAND-EVENTS",
        capability="incident_research",
        persona="sre",
        request_template="Find the matching incident.",
        steps=(
            EvalStepSpec(
                id="search",
                capability="search",
                connector="servicenow",
                operation="search",
            ),
        ),
        requirements=(
            WorldRequirement(
                id="incident",
                kind=RequirementKind.CONNECTOR,
                selector={"connector": "servicenow", "priority": "P1"},
                minimum=2,
            ),
        ),
        candidate_count=1,
    )


def test_compiled_demands_materialize_as_deterministic_events() -> None:
    demands = compile_demands(_spec())
    at = datetime(2026, 9, 1, 9, tzinfo=UTC)

    first = demand_events(demands, occurred_at=at)
    second = demand_events(demands, occurred_at=at)

    assert first == second
    assert all(event.kind.startswith("demand.") for event in first)
    payload = json.loads(first[0].summary)
    assert "selector" in payload
    assert first[0].caused_by


def test_intervention_appends_provenance_without_satisfying_requirement() -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    demands = compile_demands(_spec())
    at = datetime(2026, 9, 1, 9, tzinfo=UTC)

    intervened = intervene(world, demands, occurred_at=at)

    assert len(intervened.events) == len(world.events) + len(demands.demands)
    assert tuple(intervened.events)[: len(world.events)] == tuple(world.events)
    assert all(event.kind.startswith("demand.") for event in intervened.events[len(world.events) :])
