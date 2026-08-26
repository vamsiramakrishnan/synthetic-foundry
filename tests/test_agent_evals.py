from __future__ import annotations

import json

import pytest

from worldloom import World
from worldloom.agent_evals import WorkflowSeed, compile_agent_evals, export_agent_evals
from worldloom.connector_data import (
    canonical_verb,
    ConnectorVerb,
    ContentVerb,
    generate_connector_data,
)


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
        writes = [
            node
            for node in case.nodes
            if node.operation in {"create", "update", "draft", "reply"}
        ]
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


def test_connector_projections_are_grounded_and_linkable(world: World) -> None:
    dataset = generate_connector_data(world)
    assert {record.connector for record in dataset.records} == {
        "jira",
        "servicenow",
        "email",
    }
    fact_ids = set(world.facts.ids())
    event_ids = set(world.events.ids())
    for record in dataset.records:
        assert set(record.fact_ids) <= fact_ids
        assert set(record.event_ids) <= event_ids
        assert record.external_id


def test_email_has_real_transport_and_content_verbs(world: World) -> None:
    dataset = generate_connector_data(world, connectors=("email",))
    capability = dataset.capabilities[0]
    assert {ConnectorVerb.READ, ConnectorVerb.DRAFT, ConnectorVerb.SEND, ConnectorVerb.REPLY} <= set(capability.verbs)
    assert {ContentVerb.SUMMARIZE, ContentVerb.EXTRACT} <= set(capability.content_verbs)
    assert all(record.fields["from"] and record.fields["to"] for record in dataset.records)


def test_generate_and_mutation_verbs_are_not_conflated(world: World) -> None:
    case = compile_agent_evals(world)[0]
    assert any(node.intent == "content.generate" for node in case.nodes)
    write = next(node for node in case.nodes if node.id == "write-1")
    assert write.operation in {"create", "update", "draft", "reply"}
    assert canonical_verb("modify", target="record") == "update"
    assert canonical_verb("modify", target="content") == "transform"
