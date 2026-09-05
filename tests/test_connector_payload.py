from __future__ import annotations

import json

import pytest

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_fields import synthesize_custom_fields
from worldloom.connector_payload import shape_payload


def test_three_hundred_field_jira_payload_is_real_shape_not_metadata_only() -> None:
    jira = load_connector_definition("jira")
    fields = synthesize_custom_fields(
        connector="jira", entity="bug", count=300, seed=8128
    )
    widened = jira.with_fields("bug", fields)
    record = {
        "fid": "jr:bug:F00001",
        "entity": "bug",
        "external_id": "PHX-203",
        "summary": "Duplicate charge on retry",
        "status": "open",
        "priority": "High",
        "project": "PHX",
    }

    payload = shape_payload(widened, record)

    assert payload["key"] == "PHX-203"
    assert len(payload["fields"]) >= 300
    assert all(field.id in payload["fields"] for field in fields)
    # Real wide schemas are mostly empty. The keys still cost context unless the
    # agent uses projection, which is the behavior this eval shape is meant to test.
    nulls = sum(payload["fields"][field.id] is None for field in fields)
    assert nulls > 150


def test_projection_dramatically_reduces_wide_jira_payload() -> None:
    jira = load_connector_definition("jira").with_fields(
        "bug",
        synthesize_custom_fields(
            connector="jira", entity="bug", count=300, seed=8128
        ),
    )
    record = {
        "fid": "jr:bug:F00001",
        "entity": "bug",
        "external_id": "PHX-203",
        "summary": "Duplicate charge on retry",
        "status": "open",
        "project": "PHX",
    }

    full = shape_payload(jira, record)
    projected = shape_payload(
        jira,
        record,
        fields=("summary", "status", "customfield_10000"),
    )

    assert set(projected["fields"]) == {
        "summary",
        "status",
        "customfield_10000",
    }
    assert len(json.dumps(projected)) < len(json.dumps(full)) / 10


@pytest.mark.parametrize(
    ("connector", "record", "identity_key", "nested_key"),
    [
        (
            "outlook",
            {
                "fid": "ol:message:1",
                "entity": "message",
                "subject": "Quarter close",
                "sender": "cfo@example.invalid",
                "recipients": ["finance@example.invalid"],
                "body": "Please reconcile the workbook.",
            },
            "id",
            "body",
        ),
        (
            "onedrive",
            {
                "fid": "od:pptx:1",
                "entity": "pptx",
                "name": "Q3-Review.pptx",
                "size": 40_000_000,
                "parent": "/SteerCo",
            },
            "id",
            "file",
        ),
        (
            "teams",
            {
                "fid": "tm:channel_message:1",
                "entity": "channel_message",
                "team": "team-1",
                "channel": "ops",
                "sender": "Dana",
                "body": "Checkout is degraded.",
            },
            "id",
            "channelIdentity",
        ),
        (
            "slack",
            {
                "fid": "sl:message:1",
                "entity": "message",
                "channel": "C123",
                "sender": "U456",
                "body": "Checkout is degraded.",
            },
            "ts",
            "text",
        ),
        (
            "teamwork_graph",
            {
                "fid": "tg:work_item:1",
                "entity": "work_item",
                "title": "PHX-203",
                "url": "https://example.invalid/PHX-203",
            },
            "ari",
            "__typename",
        ),
        (
            "rovo",
            {
                "fid": "rv:document:1",
                "entity": "document",
                "title": "Settlement runbook",
                "body": "Backout steps",
                "source": "confluence",
            },
            "id",
            "source",
        ),
    ],
)
def test_new_surfaces_are_shaped_by_the_same_engine(
    connector: str,
    record: dict[str, object],
    identity_key: str,
    nested_key: str,
) -> None:
    definition = load_connector_definition(connector)

    payload = shape_payload(definition, record)

    assert payload[identity_key]
    assert nested_key in payload


def test_payload_shaping_never_mutates_canonical_record() -> None:
    record = {
        "fid": "tm:channel_message:1",
        "entity": "channel_message",
        "sender": "Dana",
        "body": "Original text",
    }
    before = dict(record)

    shape_payload(load_connector_definition("teams"), record)

    assert record == before
