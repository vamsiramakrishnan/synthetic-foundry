from __future__ import annotations

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_fields import (
    estimated_payload_bytes,
    estimated_populated_fields,
    synthesize_custom_fields,
)


def test_three_hundred_custom_fields_are_deterministic() -> None:
    first = synthesize_custom_fields(
        connector="jira", entity="bug", count=300, seed=8128
    )
    replay = synthesize_custom_fields(
        connector="jira", entity="bug", count=300, seed=8128
    )

    assert first == replay
    assert len(first) == 300
    assert len({field.id for field in first}) == 300
    assert len({field.canonical for field in first}) == 300
    assert all(field.query_name is not None for field in first)


def test_wide_schema_is_metadata_heavy_but_population_sparse() -> None:
    fields = synthesize_custom_fields(
        connector="jira", entity="bug", count=300, seed=8128
    )

    assert estimated_populated_fields(fields) < 100
    assert estimated_payload_bytes(fields) > 0
    assert any(field.deprecated for field in fields)
    assert any(not field.writable for field in fields)


def test_field_overlay_updates_query_and_payload_compatibility_views() -> None:
    jira = load_connector_definition("jira")
    fields = synthesize_custom_fields(
        connector="jira", entity="bug", count=3, seed=7, start=20_000
    )

    widened = jira.with_fields("bug", fields)

    assert jira.fields_for("bug") == ()
    assert len(widened.fields_for("bug")) == 3
    for field in fields:
        assert widened.resolve_field("bug", field.id) == field
        assert widened.resolve_field("bug", field.name) == field
        assert widened.custom_fields[field.canonical] == field.id
        assert widened.query_fields[field.canonical] == field.query_name
