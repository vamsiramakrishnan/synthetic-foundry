from __future__ import annotations

import pytest

from worldloom import World
from worldloom.query_planning import (
    build_query_driven_corpus,
    plan_query_set,
    query_space,
    query_space_size,
)


@pytest.fixture(scope="module")
def world() -> World:
    return World.load("retail-close")


def test_space_is_massive_but_declared() -> None:
    space = query_space()
    assert query_space_size() == space.exhaustive
    assert space.exhaustive > 100_000_000
    assert set(space.names) == {
        "workflow",
        "source_set",
        "write_target",
        "output",
        "audience",
        "content_verb",
        "topology",
        "failure",
        "verification",
    }


def test_plan_precedes_generation_and_is_deterministic(world: World) -> None:
    first = plan_query_set(world, strength=1, limit=40)
    second = plan_query_set(world, strength=1, limit=40)
    assert first == second
    assert len(first) == 40
    assert len({plan.id for plan in first}) == len(first)


def test_queries_do_not_leak_transport_formats(world: World) -> None:
    for plan in plan_query_set(world, strength=1, limit=100):
        lowered = plan.query.lower()
        assert " as json" not in lowered
        assert "mcp" not in lowered
        assert world.company.name.lower() in lowered


def test_plan_drives_records_and_failure_fixtures(world: World) -> None:
    corpus = build_query_driven_corpus(world, strength=1, limit=80)
    records = {record.id for record in corpus.connector_data.records}
    assert len(corpus.plan) == len(corpus.fixtures) == 80
    for plan, fixture in zip(corpus.plan, corpus.fixtures, strict=True):
        assert plan.id == fixture.query_id
        assert {
            record_id
            for ids in fixture.input_record_ids.values()
            for record_id in ids
        } <= records
        if plan.mutation.preexisting_record:
            assert fixture.output_record_id in records
        else:
            assert fixture.output_record_id is None


def test_create_and_update_have_different_fixture_preconditions(world: World) -> None:
    plans = plan_query_set(world, strength=1, limit=200)
    assert any(not plan.mutation.preexisting_record for plan in plans)
    assert any(plan.mutation.preexisting_record for plan in plans)
