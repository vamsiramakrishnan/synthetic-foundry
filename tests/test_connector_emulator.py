from __future__ import annotations

import json

import pytest

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator, ConnectorError
from worldloom.connector_fields import synthesize_custom_fields


def _jira_records(count: int = 80) -> list[dict[str, object]]:
    return [
        {
            "fid": f"jr:bug:{index:04d}",
            "server": "jira",
            "entity": "bug",
            "ident": f"PHX-{100 + index}",
            "name": f"Bug {index}",
            "summary": f"Bug {index}",
            "project": "PHX",
            "status": "open" if index % 2 else "todo",
            "priority": "High",
        }
        for index in range(count)
    ]


def test_search_uses_definition_paging_and_projection() -> None:
    jira = load_connector_definition("jira").with_fields(
        "bug",
        synthesize_custom_fields(
            connector="jira", entity="bug", count=300, seed=8128
        ),
    )
    emulator = ConnectorEmulator(jira, _jira_records())

    page = emulator.call(
        "search_issues",
        entity="bug",
        predicate={"project": "PHX"},
        fields=["summary", "status", "customfield_10000"],
        max_results=200,
    )

    assert page["total"] == 80
    assert page["max_results"] == 50  # Jira definition owns this, not the engine.
    assert len(page["items"]) == 50
    assert set(page["items"][0]["fields"]) == {
        "summary",
        "status",
        "customfield_10000",
    }
    assert emulator.trace[0].items == 50
    assert emulator.trace[0].bytes == len(
        json.dumps(page, sort_keys=True, separators=(",", ":")).encode()
    )


def test_forks_are_mutation_isolated_and_snapshot_is_deterministic() -> None:
    surface = ConnectorEmulator(load_connector_definition("jira"), _jira_records(2))
    baseline = surface.snapshot()
    left = surface.fork()
    right = surface.fork()

    left.call("update_issue", id="PHX-100", fields={"priority": "Highest"})

    assert left.snapshot() != baseline
    assert right.snapshot() == baseline
    assert surface.snapshot() == baseline
    assert right.call("get_issue", id="PHX-100")["fields"]["priority"]["name"] == "High"


def test_workflow_transition_is_definition_driven() -> None:
    emulator = ConnectorEmulator(load_connector_definition("jira"), _jira_records(1))

    emulator.call("transition_issue", id="PHX-100", state="blocked")
    with pytest.raises(ConnectorError) as caught:
        emulator.call("transition_issue", id="PHX-100", state="done")

    assert caught.value.kind == "bad_transition"
    assert emulator.trace[-1].error is not None


def test_acl_hides_records_from_search_and_denies_direct_read() -> None:
    records = _jira_records(3)
    emulator = ConnectorEmulator(
        load_connector_definition("jira"),
        records,
        acl={"jr:bug:0001": {"denied": True}},
    )

    result = emulator.call("search_issues", entity="bug", predicate={"project": "PHX"})

    assert result["total"] == 2
    with pytest.raises(ConnectorError) as caught:
        emulator.call("get_issue", id="PHX-101")
    assert caught.value.kind == "denied"


def test_native_query_and_structured_predicate_reach_same_records() -> None:
    emulator = ConnectorEmulator(load_connector_definition("jira"), _jira_records(6))

    structured = emulator.call(
        "search_issues",
        entity="bug",
        predicate={"project": "PHX", "status": "open"},
    )
    native = emulator.call(
        "search_issues",
        entity="bug",
        query="project = 'PHX' AND status = 'open'",
    )

    assert [item["key"] for item in structured["items"]] == [
        item["key"] for item in native["items"]
    ]


def test_legacy_jira_issue_alias_searches_existing_generic_records() -> None:
    records = [
        {
            "fid": "legacy:issue:1",
            "server": "jira",
            "entity": "issue",
            "ident": "WL-1",
            "name": "Legacy projected task",
            "status": "todo",
            "project": "WL",
        }
    ]
    emulator = ConnectorEmulator(load_connector_definition("jira"), records)

    result = emulator.call("search_issues", entity="issue", predicate={"project": "WL"})

    assert result["total"] == 1
    assert result["items"][0]["key"] == "WL-1"


def test_outlook_and_teams_use_the_same_engine() -> None:
    outlook = ConnectorEmulator(
        load_connector_definition("outlook"),
        [
            {
                "fid": "ol:1",
                "server": "outlook",
                "entity": "message",
                "ident": "m-1",
                "subject": "Close review",
                "body": "Please review.",
                "sender": "cfo@example.invalid",
            }
        ],
    )
    teams = ConnectorEmulator(
        load_connector_definition("teams"),
        [
            {
                "fid": "tm:1",
                "server": "teams",
                "entity": "channel_message",
                "ident": "t-1",
                "team": "finance",
                "channel": "close",
                "body": "Please review.",
            }
        ],
    )

    assert outlook.call("list_messages")["items"][0]["subject"] == "Close review"
    assert teams.call("list_channel_messages")["items"][0]["channelIdentity"]["channelId"] == "close"


def test_every_identity_a_shaped_payload_hands_out_resolves_back() -> None:
    """A search item's identity, under whatever key the product uses, is a handle.

    The first fix indexed the shaped ``id`` only, which resolved Jira and left
    ServiceNow refusing its own ``sys_id``. Checked over every connector that
    projects records, for every identity key ``shape_payload`` emits.
    """
    from worldloom.connector_data import builtin_projections
    from worldloom.connector_definition import builtin_connector_definitions
    from worldloom.connector_payload import shape_payload
    from worldloom.retail import RetailWorld
    from worldloom.scenarios import MonthEndClose

    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    identity_keys = ("id", "Id", "sys_id", "key", "number", "ts", "ari")
    checked: set[tuple[str, str]] = set()
    for name, definition in sorted(builtin_connector_definitions().items()):
        try:
            records = builtin_projections().project(name, world)
        except ValueError:
            continue
        if not records:
            continue
        emulator = ConnectorEmulator(definition, records)
        for record in records:
            shaped = shape_payload(definition, emulator.records[record.id])
            for key in identity_keys:
                value = shaped.get(key)
                if isinstance(value, (str, int)) and not isinstance(value, bool):
                    assert emulator.resolve(value) == record.id, (name, key, value)
                    checked.add((name, key))
    assert ("servicenow", "sys_id") in checked
    assert ("jira", "id") in checked and ("jira", "key") in checked
