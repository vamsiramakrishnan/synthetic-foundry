from __future__ import annotations

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_seed import compile_seed_manifest, hydrate_emulator


def test_seed_manifest_uses_definition_owned_create_tool() -> None:
    jira = load_connector_definition("jira")
    manifest = compile_seed_manifest(
        jira,
        [
            {
                "fid": "jr:bug:1",
                "server": "jira",
                "entity": "bug",
                "ident": "PHX-203",
                "name": "Duplicate charge on retry",
                "project": "PHX",
                "status": "open",
            }
        ],
    )

    seed = manifest.records[0]
    assert seed.create_tool == "create_issue"
    assert not seed.fixture_only
    assert seed.native_payload_bytes > 0
    assert len(seed.digest) == 64


def test_read_only_product_surface_is_explicitly_fixture_only() -> None:
    rovo = load_connector_definition("rovo")
    manifest = compile_seed_manifest(
        rovo,
        [
            {
                "fid": "rv:document:1",
                "server": "rovo",
                "entity": "document",
                "ident": "ari:doc:1",
                "name": "Settlement runbook",
                "body": "Backout procedure",
                "source": "confluence",
            }
        ],
    )

    assert manifest.records[0].create_tool is None
    assert manifest.records[0].fixture_only


def test_legacy_drive_file_alias_does_not_invent_one_write_api() -> None:
    drive = load_connector_definition("drive")
    manifest = compile_seed_manifest(
        drive,
        [
            {
                "fid": "legacy:file:1",
                "server": "drive",
                "entity": "file",
                "ident": "file-1",
                "name": "Legacy projection",
            }
        ],
    )

    assert manifest.records[0].fixture_only


def test_manifest_hydrates_the_same_generic_emulator() -> None:
    teams = load_connector_definition("teams")
    manifest = compile_seed_manifest(
        teams,
        [
            {
                "fid": "tm:message:1",
                "server": "teams",
                "entity": "channel_message",
                "ident": "m-1",
                "team": "ops",
                "channel": "incidents",
                "body": "Payments degraded",
            }
        ],
    )

    emulator = hydrate_emulator(teams, manifest)
    result = emulator.call("list_channel_messages")

    assert result["total"] == 1
    assert result["items"][0]["channelIdentity"]["channelId"] == "incidents"
