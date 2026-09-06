from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator


def test_slack_post_then_reply_mints_distinct_thread_message() -> None:
    emulator = ConnectorEmulator(load_connector_definition("slack"), ())

    root = emulator.call(
        "post_message",
        entity="message",
        name="Release status",
        fields={"channel": "C-OPS", "text": "release is green", "client_msg_id": "m1"},
    )
    root_id = emulator.trace[-1].writes[0]
    reply = emulator.call("reply_message", id=root_id, body="confirmed")

    assert root_id in emulator.records
    assert emulator.trace[-1].writes[0] != root_id
    reply_id = emulator.trace[-1].writes[0]
    assert emulator.records[reply_id]["reply_to"] == root_id
    assert emulator.records[reply_id]["text"] == "confirmed"
    assert reply != root


def test_outlook_forward_creates_a_new_message_without_mutating_source() -> None:
    emulator = ConnectorEmulator(load_connector_definition("outlook"), ())
    original = emulator.call(
        "send_message",
        entity="message",
        name="Quarter close",
        fields={
            "subject": "Quarter close",
            "body": "Close is complete",
            "to": ["finance@example.invalid"],
        },
    )
    source_id = emulator.trace[-1].writes[0]

    forwarded = emulator.call(
        "forward_message",
        id=source_id,
        to=["audit@example.invalid"],
        body="For review",
    )

    forwarded_id = emulator.trace[-1].writes[0]
    assert forwarded_id != source_id
    assert emulator.records[source_id]["body"] == "Close is complete"
    assert emulator.records[forwarded_id]["forwarded_from"] == source_id
    assert emulator.records[forwarded_id]["to"] == ["audit@example.invalid"]
    assert forwarded != original


def test_onedrive_upload_and_download_use_same_definition() -> None:
    emulator = ConnectorEmulator(load_connector_definition("onedrive"), ())
    uploaded = emulator.call(
        "upload_file",
        entity="docx",
        name="Operating-Review.docx",
        parent="/Shared Documents",
        fields={"content": "synthetic body"},
    )
    fid = emulator.trace[-1].writes[0]

    downloaded = emulator.call("download_content", id=fid)

    assert uploaded["name"] == "Operating-Review.docx"
    assert downloaded["content"] == "synthetic body"
    assert emulator.trace[-1].reads == (fid,)
