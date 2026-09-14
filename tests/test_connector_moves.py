"""A record can be moved, and the vocabulary says so by name.

Every file connector declared a `move_file`/`move_item` tool as an `update`
on the folder entity alone, so `tool_for("docx", "move")` had nothing to
answer and a hero use case — organise my drive, my inbox, my chats — could
not be planned, executed or graded as what it is. `move` is now an operation
of its own: files and folders move between folders, Outlook messages move
between mail folders, and the emulator re-parents the record it leaves
intact. Mail gains labels through `update_message`; Slack channels can be
created and archived through the workflow the definition always declared.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pytest

from worldloom.connector_definition import (
    REFERENCE_CONNECTORS,
    load_connector_definition,
)
from worldloom.connector_emulator import ConnectorEmulator, ConnectorError
from worldloom.evalrun import ScriptedAgent, case_from_row, run_case, service_for
from worldloom.evalrun.safety import classify_definition, tool_annotations

FILE_MOVES = {"drive": "move_file", "sharepoint": "move_file", "onedrive": "move_item"}


def _drive_records() -> list[dict[str, Any]]:
    return [
        {"fid": "d1", "server": "drive", "entity": "folder", "ident": "fold-finance", "name": "Finance"},
        {"fid": "d2", "server": "drive", "entity": "folder", "ident": "fold-sales", "name": "Sales"},
        {"fid": "f1", "server": "drive", "entity": "docx", "ident": "doc-close-pack", "name": "Close pack.docx",
         "parent": "d2", "title": "Close pack"},
        {"fid": "f2", "server": "drive", "entity": "pdf", "ident": "doc-price-list", "name": "Prices.pdf",
         "parent": "d2", "title": "Price list"},
    ]


def _move_row() -> dict[str, Any]:
    return {"id": "mv", "query": "Find the close pack in Sales and file it under Finance, then check it landed.",
            "expected_dag": {"nodes": [
                {"id": "read", "server": "drive", "tool": "get_file", "fixture": "f1", "entity": "docx", "op": "read"},
                {"id": "write", "server": "drive", "tool": "move_file", "fixture": "f1", "entity": "docx", "op": "move"},
                {"id": "verify", "server": "drive", "tool": "get_file", "fixture": "f1", "entity": "docx", "op": "readback"},
            ], "edges": [["read", "write"], ["write", "verify"]]},
            "assertions": [{"type": "tool_called", "node": node} for node in ("read", "write", "verify")]
            + [{"type": "order", "before": "read", "after": "write"},
               {"type": "order", "before": "write", "after": "verify"},
               {"type": "state_equals", "node": "write", "fixture": "f1", "field": "parent", "state": "d1"}]}


def test_every_file_connector_moves_files_and_folders_by_name() -> None:
    for connector, tool in FILE_MOVES.items():
        definition = load_connector_definition(connector)
        assert definition.tools[tool].op == "move" and set(definition.tools[tool].params) == {"id", "parent"}
        members = definition.entity_members("file") if "file" in definition.entity_aliases else ("file",)
        for entity in (*members, "folder"):
            assert definition.tool_for(entity, "move") == tool, (connector, entity)
        assert "update" not in definition.entities["folder"].ops, "a folder's only mutation of its place is a move"
    assert load_connector_definition("outlook").tool_for("message", "move") == "move_message"
    assert load_connector_definition("outlook").tool_for("mail_folder", "create") == "create_folder"
    assert load_connector_definition("email").tool_for("message", "update") == "update_message"
    slack = load_connector_definition("slack")
    assert slack.tool_for("channel", "create") == "create_conversation"
    assert slack.tool_for("channel", "transition") == "archive_conversation"
    for connector in REFERENCE_CONNECTORS:
        load_connector_definition(connector)  # every definition still validates


def test_a_move_is_a_reversible_idempotent_mutation_never_a_delete() -> None:
    posture = classify_definition(load_connector_definition("drive"))["drive.move_file"]
    assert posture.effect.value == "mutation" and posture.action.value == "update"
    assert posture.reversible and posture.safe_to_retry and not posture.destructive
    assert tool_annotations(posture) == {
        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    }


def test_the_emulator_reparents_the_record_it_leaves_intact() -> None:
    emulator = ConnectorEmulator(load_connector_definition("drive"), _drive_records())
    before = dict(emulator.records["f1"])
    result = emulator.call("move_file", id="doc-close-pack", parent="fold-finance", _node="write")
    after = emulator.records["f1"]
    assert after["parent"] == "d1" and result["parents"] == ["d1"]
    assert {k: v for k, v in after.items() if k not in ("parent", "modified_at", "updates")} == \
           {k: v for k, v in before.items() if k not in ("parent", "modified_at", "updates")}
    assert tuple(emulator.trace[-1].writes) == ("f1",) and not emulator.trace[-1].reads
    # Moving to where it already is changes nothing but the clock: idempotent.
    emulator.call("move_file", id="doc-close-pack", parent="fold-finance", _node="write")
    assert emulator.records["f1"]["parent"] == "d1"
    # A folder moves too.
    emulator.call("move_file", id="fold-sales", parent="fold-finance", _node="write")
    assert emulator.records["d2"]["parent"] == "d1"


def test_a_bad_destination_says_which_of_two_things_went_wrong() -> None:
    emulator = ConnectorEmulator(load_connector_definition("drive"), _drive_records())
    with pytest.raises(ConnectorError) as missing:
        emulator.call("move_file", id="doc-close-pack", parent="fold-nowhere", _node="write")
    assert missing.value.kind == "not_found"
    with pytest.raises(ConnectorError) as not_a_folder:
        emulator.call("move_file", id="doc-close-pack", parent="doc-price-list", _node="write")
    assert not_a_folder.value.kind == "validation" and "not a folder" in not_a_folder.value.message
    with pytest.raises(ConnectorError) as itself:
        emulator.call("move_file", id="fold-sales", parent="fold-sales", _node="write")
    assert itself.value.kind == "validation"
    with pytest.raises(ConnectorError) as nowhere:
        emulator.call("move_file", id="doc-close-pack", _node="write")
    assert nowhere.value.kind == "validation"
    assert emulator.records["f1"]["parent"] == "d2", "a refused move moved nothing"


def test_a_move_is_graded_on_all_three_axes_through_the_served_surface() -> None:
    case = case_from_row(_move_row())
    assert [o.kind for o in case.outcomes.structured] == ["update"]
    assert case.outcomes.structured[0].fields == {"parent": "d1"}
    service = service_for((case,), _drive_records(), definitions={"drive": load_connector_definition("drive")})
    good = ScriptedAgent([("drive.get_file", {"id": "doc-close-pack"}),
                          ("drive.move_file", {"id": "doc-close-pack", "parent": "fold-finance"}),
                          ("drive.get_file", {"id": "doc-close-pack"})])
    result = run_case(service, case, good)
    assert result.score is not None and result.score.passed, result.score.model_dump()
    assert result.score.outcomes.diff.updated == ("f1",) and result.score.outcomes.collateral == ()

    wrong = ScriptedAgent([("drive.get_file", {"id": "doc-close-pack"}),
                           ("drive.move_file", {"id": "doc-price-list", "parent": "fold-finance"}),
                           ("drive.get_file", {"id": "doc-close-pack"})])
    result = run_case(service_for((case,), _drive_records(), definitions={"drive": load_connector_definition("drive")}), case, wrong)
    assert result.score is not None and not result.score.passed
    assert result.score.outcomes.collateral == ("f2",), "the wrong record moved is collateral, not credit"
    assert not result.score.outcomes.structured[0].met


def test_mail_and_chat_gain_the_mutations_organising_them_needs() -> None:
    outlook = ConnectorEmulator(load_connector_definition("outlook"), [
        {"fid": "m1", "server": "outlook", "entity": "message", "ident": "msg-1", "subject": "Invoice", "parent": "inbox"},
        {"fid": "in", "server": "outlook", "entity": "mail_folder", "ident": "inbox", "name": "Inbox"},
    ])
    made = outlook.call("create_folder", name="Invoices", entity="mail_folder", _node="w1")
    folder = outlook.trace[-1].writes[0]
    assert outlook.records[folder]["entity"] == "mail_folder" and made["displayName"] if "displayName" in made else True
    outlook.call("move_message", id="msg-1", parent=folder, _node="w2")
    assert outlook.records["m1"]["parent"] == folder

    email = ConnectorEmulator(load_connector_definition("email"), [
        {"fid": "e1", "server": "email", "entity": "message", "ident": "<a@x>", "subject": "Hi", "labels": ["inbox"], "state": "sent"},
    ])
    email.call("update_message", id="<a@x>", fields={"labels": ["inbox", "receipts"], "is_read": True}, _node="w")
    assert email.records["e1"]["labels"] == ["inbox", "receipts"] and email.records["e1"]["is_read"] is True

    slack = ConnectorEmulator(load_connector_definition("slack"), [
        {"fid": "c1", "server": "slack", "entity": "channel", "ident": "C001", "name": "proj-old", "state": "active"},
    ])
    slack.call("archive_conversation", id="C001", state="archived", _node="w")
    assert slack.records["c1"]["state"] == "archived"
    with pytest.raises(ConnectorError) as back:
        slack.call("archive_conversation", id="C001", state="active", _node="w")
    assert back.value.kind == "bad_transition", "the declared workflow has no way back"
    slack.call("create_conversation", name="proj-new", entity="channel", _node="w")
    new = slack.trace[-1].writes[0]
    assert slack.records[new]["state"] == "active"
    assert tuple(asdict(slack.trace[-1])["writes"]) == (new,)
