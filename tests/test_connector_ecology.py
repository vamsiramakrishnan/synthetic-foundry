from datetime import datetime

import pytest

from worldloom import MonthEndClose, RetailWorld
from worldloom.ecology import connectors


@pytest.fixture(scope="module")
def world():  # type: ignore[no-untyped-def]
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )


def _times(history: list[dict[str, object]]) -> list[datetime]:
    return [datetime.fromisoformat(str(item["at"])) for item in history]


def test_servicenow_history_advances_in_simulated_time(world) -> None:  # type: ignore[no-untyped-def]
    data = connectors(world, ("servicenow",))
    incidents = [record for record in data.records if record.entity == "incident"]
    assert incidents
    for incident in incidents:
        history = incident.fields["state_history"]
        times = _times(history)
        assert times == sorted(times)
        if len(times) > 1:
            assert len(set(times)) == len(times)
        note_times = _times(incident.fields["work_notes"])
        assert note_times == sorted(note_times)


def test_jira_history_is_temporal_not_just_a_final_status(world) -> None:  # type: ignore[no-untyped-def]
    data = connectors(world, ("jira",))
    issues = [record for record in data.records if record.entity == "issue"]
    assert issues
    for issue in issues:
        history = issue.fields["status_history"]
        assert history[0]["to"] == "To Do"
        times = _times(history)
        assert times == sorted(times)
        assert issue.fields["activity"][0]["at"]


def test_confluence_has_page_version_and_navigation_semantics(world) -> None:  # type: ignore[no-untyped-def]
    data = connectors(world, ("confluence",))
    pages = [record for record in data.records if record.entity == "page"]
    assert pages
    for page in pages:
        fields = page.fields
        assert fields["space_key"]
        assert fields["canonical_url"].endswith(str(fields.get("page_id", page.external_id)))
        assert fields["version_history"]
        assert fields["macros"]


def test_email_thread_replies_reference_existing_messages(world) -> None:  # type: ignore[no-untyped-def]
    data = connectors(world, ("email",))
    messages = [record for record in data.records if record.entity == "message"]
    assert messages
    ids = {record.external_id for record in messages}
    for message in messages:
        reply_to = message.fields.get("in_reply_to")
        if reply_to:
            assert reply_to in ids
            assert message.fields["reply_type"] == "reply"
        assert message.fields["conversation_index"]
        assert message.fields["client"] in {"outlook-desktop", "outlook-web", "mobile"}
