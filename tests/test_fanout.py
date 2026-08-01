"""The fan-out layer: minutes, threads, and per-unit commentary.

The property under test is not "more documents" — it is that every added
document is a *projection* of structure the episode already established:
minutes attendees come from the meeting's own event, a thread's early messages
cannot cite facts that did not yet exist, and a unit's commentary cites only
that unit's own figures. If any of these could smuggle in knowledge, the
fan-out would be diluting the corpus's epistemics instead of publishing them.
"""

from __future__ import annotations

import pytest

from worldloom import (
    Authority,
    BankingWorld,
    MonthEndClose,
    QuarterlyCapitalReturn,
    RetailWorld,
    World,
)


@pytest.fixture(scope="module")
def retail() -> World:
    return (
        RetailWorld(seed=8128)
        .build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True))
        .compile()
    )


@pytest.fixture(scope="module")
def banking() -> World:
    return (
        BankingWorld(seed=8128)
        .build()
        .run(QuarterlyCapitalReturn(period="2026-03"))
        .compile()
    )


def _ir(world: World, artifact_type: str):
    intent = next(i for i in world.artifact_intents if i.artifact_type == artifact_type)
    return intent, world.artifact_irs.by_id(intent.id)


# ---------------------------------------------------------------------------
# Minutes are the meeting's own record
# ---------------------------------------------------------------------------


def test_minutes_attendance_is_the_events_own(retail: World) -> None:
    intent, ir = _ir(retail, "meeting_minutes")
    event = retail.events.by_id(intent.triggered_by[0])
    attendance = next(t for t in ir.tables() if t.key == "attendees")
    assert [row.key for row in attendance.rows] == event.actors
    # The meeting that moved the close was the controller escalating to the
    # CFO — the roster the who-was-in-the-room evaluation resolves against.
    titles = {retail.people.by_id(pid).title for pid in event.actors}
    assert titles == {"Group Financial Controller", "Group Chief Financial Officer"}


def test_minutes_separate_decided_from_tabled(retail: World) -> None:
    """A fact this meeting's event minted is a decision of this meeting;
    everything else was merely in front of it. Conflating the two would let
    minutes claim credit for the whole episode."""
    intent, ir = _ir(retail, "meeting_minutes")
    event_id = intent.triggered_by[0]
    tables = {t.key: t for t in ir.tables()}
    for row_id in (r.key for r in tables["decisions"].rows):
        assert retail.facts.by_id(row_id).event_id == event_id
    for row_id in (r.key for r in tables["tabled"].rows):
        assert retail.facts.by_id(row_id).event_id != event_id


def test_minutes_need_no_prose(retail: World) -> None:
    """Fully resolved by design: minutes add zero narration burden, which is
    what lets them exist in the reference corpus without reference prose."""
    _, ir = _ir(retail, "meeting_minutes")
    assert not any(section.awaiting_prose for section in ir.sections)


# ---------------------------------------------------------------------------
# Threads know only what their moment knew
# ---------------------------------------------------------------------------


def test_thread_messages_learn_in_order(retail: World) -> None:
    """The epistemic staircase: the first report cannot cite the confirmed
    cause, the last message can. This is the property that makes the thread a
    record of knowledge arriving rather than a summary wearing timestamps."""
    intent, ir = _ir(retail, "email_thread")
    cause = next(
        f.id for f in retail.facts.where(kind="ops.cause")
        if f.authority is Authority.CONFIRMED
    )
    messages = [s for s in ir.sections if not s.hidden]
    assert len(messages) >= 3
    assert cause not in messages[0].fact_ids
    assert cause in {fid for section in messages[-2:] for fid in section.fact_ids}
    for section in messages:
        assert section.awaiting_prose  # a message body is prose, always


def test_banking_thread_carries_the_live_disagreement(banking: World) -> None:
    """Message one states the treatment; message two challenges it; message
    three approves anyway. The thread is the contested window as it was
    lived, before any of the formal documents existed."""
    intent, ir = _ir(banking, "email_thread")
    challenge = next(
        f.id for f in banking.facts.where(kind="review.challenge")
    )
    messages = [s for s in ir.sections if not s.hidden]
    assert challenge not in messages[0].fact_ids
    assert challenge in messages[1].fact_ids


# ---------------------------------------------------------------------------
# Commentary stays inside its unit
# ---------------------------------------------------------------------------


def test_commentary_exists_per_unit_and_stays_home(retail: World) -> None:
    commentaries = [
        i for i in retail.artifact_intents if i.artifact_type == "unit_close_commentary"
    ]
    assert len(commentaries) == len(retail.business_units)
    unit_of_bp = {
        person.id: person.business_unit_id for person in retail.people
    }
    for intent in commentaries:
        subjects = {retail.facts.by_id(f).subject for f in intent.required_fact_ids}
        assert len(subjects) == 1, "a unit's commentary cites one unit's facts"
        assert unit_of_bp[intent.author_id] == next(iter(subjects)), (
            "the author is the finance partner of the unit they argue"
        )


# ---------------------------------------------------------------------------
# The corpus holds, evaluations included
# ---------------------------------------------------------------------------


def test_both_corpora_stay_coherent(retail: World, banking: World) -> None:
    assert retail.validate().ok
    assert banking.validate().ok


def test_the_minutes_evaluations_are_reachable(banking: World) -> None:
    """The approval-meeting cases exist and expect only facts the minutes (or
    another planned document) actually carry."""
    cases = [
        c for c in banking.evaluations
        if "meeting" in c.question and "approved" in c.question
    ]
    assert len(cases) == 2
    reachable = {
        fact_id
        for intent in banking.artifact_intents
        for fact_id in intent.required_fact_ids
    }
    for case in cases:
        assert set(case.expected_fact_ids) <= reachable
