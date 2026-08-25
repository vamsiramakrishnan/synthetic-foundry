from __future__ import annotations

import json

import pytest

from worldloom import World
from worldloom.agent_evals import WorkflowSeed, compile_agent_evals, export_agent_evals


@pytest.fixture(scope="module")
def world() -> World:
    return World.load("retail-close")


def test_queries_are_business_language(world: World) -> None:
    for case in compile_agent_evals(world):
        text = case.request.lower()
        assert " as json" not in text
        assert "read jira issues as" not in text
        assert "mcp" not in text
        assert world.company.name.lower() in text


def test_mutations_are_grounded_idempotent_and_verified(world: World) -> None:
    for case in compile_agent_evals(world):
        assert set(case.expected_fact_ids) <= set(world.facts.ids())
        writes = [node for node in case.nodes if node.operation in {"create", "update"}]
        verifies = [node for node in case.nodes if node.kind == "verify"]
        assert len(writes) == len(verifies) == 1
        assert writes[0].arguments["idempotency_key"] == "${case.id}"
        assert verifies[0].depends_on == [writes[0].id]


def test_seed_is_deterministic_and_bounded(world: World) -> None:
    seed = WorkflowSeed(
        workflows=("incident_review", "risk_register"),
        destinations=("sharepoint", "drive"),
        max_cases=7,
    )
    first = compile_agent_evals(world, seed)
    assert first == compile_agent_evals(world, seed)
    assert len(first) == 7
    assert len({case.id for case in first}) == len(first)


def test_jsonl_round_trip(world: World, tmp_path) -> None:
    path = export_agent_evals(world, tmp_path / "agent-evals.jsonl")
    assert [json.loads(line) for line in path.read_text().splitlines()] == [
        case.model_dump(mode="json") for case in compile_agent_evals(world)
    ]
