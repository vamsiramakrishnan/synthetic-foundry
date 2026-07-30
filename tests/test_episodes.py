"""More than one close on one world.

Recurrence, superseded documents, and "did the fix hold" are the families this
corpus claims to be about, and until a world ran more than one period they were
all argued from a single episode's worth of evidence. A second close is what
makes them real:

- a close calendar is republished and *replaces* the last one, so two documents
  that look equally authoritative exist and only one is current;
- an incident review of a recurrence is *derived from* the earlier review, which
  is different — neither supersedes the other, and both stay true;
- the recurrence fact names the period it recurred from, so "when did this last
  happen" has an answer rather than a gesture.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.models import EvaluationType, Lifecycle

PERIODS = ("2026-03", "2026-04", "2026-05")


@pytest.fixture(scope="module")
def series() -> World:
    world = RetailWorld(seed=8128).build()
    for period in PERIODS:
        world = world.run(MonthEndClose(period=period, include_operational_incident=True))
    return world.compile()


def test_the_series_validates(series: World) -> None:
    report = series.validate()
    assert report.ok, report.violations[:5]


def test_each_period_is_present_exactly_once(series: World) -> None:
    periods = {f.period for f in series.facts if f.period}
    assert periods == set(PERIODS)
    for period in PERIODS:
        closes = [f for f in series.facts if f.period == period and f.kind == "close.delay"]
        assert len(closes) == 1, f"{period} closed {len(closes)} times"


# ---------------------------------------------------------------------------
# Supersession: replacing
# ---------------------------------------------------------------------------


def test_each_calendar_replaces_the_last(series: World) -> None:
    calendars = [a for a in series.artifacts if a.artifact_type == "close_calendar"]
    assert len(calendars) == len(PERIODS)

    chain = [a for a in calendars if a.supersedes]
    assert len(chain) == len(PERIODS) - 1, "every calendar but the first replaces one"
    for entry in chain:
        earlier = series.artifacts.by_id(entry.supersedes)
        assert earlier.artifact_type == entry.artifact_type
        assert earlier.created_at < entry.created_at


def test_a_replaced_calendar_is_marked_superseded(series: World) -> None:
    """Two published calendars with no way to tell which is current is worse than
    one — a reader would answer confidently from the wrong document."""
    calendars = [a for a in series.artifacts if a.artifact_type == "close_calendar"]
    replaced = {a.supersedes for a in calendars if a.supersedes}

    current = [a for a in calendars if a.id not in replaced]
    assert len(current) == 1, "exactly one calendar may be current"
    assert current[0].lifecycle is not Lifecycle.SUPERSEDED

    for entry in calendars:
        if entry.id in replaced:
            assert entry.lifecycle is Lifecycle.SUPERSEDED, entry.id


def test_nothing_is_superseded_twice(series: World) -> None:
    replaced = [a.supersedes for a in series.artifacts if a.supersedes]
    assert len(replaced) == len(set(replaced))


# ---------------------------------------------------------------------------
# Derivation: building on, without replacing
# ---------------------------------------------------------------------------


def test_a_later_review_derives_from_the_earlier_one(series: World) -> None:
    """Derivation is not replacement. An earlier review of an earlier incident
    stays true about that incident, which is what makes "did the remediation
    work" answerable at all."""
    reviews = [a for a in series.artifacts if a.artifact_type == "incident_rca"]
    assert len(reviews) >= 2

    later = [a for a in reviews if a.derived_from]
    assert later, "a recurrence review should build on its predecessor"
    for entry in later:
        for parent in entry.derived_from:
            assert series.artifacts.by_id(parent).created_at < entry.created_at

    for entry in reviews:
        assert entry.lifecycle is not Lifecycle.SUPERSEDED, (
            "a review is not made false by a later incident"
        )
        assert entry.supersedes is None


def test_the_recurrence_names_the_period_it_recurred_from(series: World) -> None:
    """"A comparable failure happened before" is unfalsifiable and unanswerable."""
    recurrences = list(series.facts.where(kind="ops.previous_similar_incident"))
    assert len(recurrences) == len(PERIODS)

    later = recurrences[-1]
    assert any(period in (later.text_value or "") for period in PERIODS[:-1]), (
        f"the recurrence should name an earlier period: {later.text_value!r}"
    )


# ---------------------------------------------------------------------------
# The questions a single close cannot pose
# ---------------------------------------------------------------------------


def test_the_series_asks_across_episodes(series: World) -> None:
    questions = [c.question for c in series.evaluations]
    assert any("last occur" in q for q in questions), "no recurrence question"
    assert any("currently in force" in q for q in questions), "no current-document question"


def test_the_hard_families_are_no_longer_thin(series: World) -> None:
    """One case proves nothing. This is the whole reason for running three closes."""
    from collections import Counter

    counts = Counter(c.evaluation_type for c in series.evaluations)
    for kind in (
        EvaluationType.TEMPORAL_STATE,
        EvaluationType.AUTHORITY_RESOLUTION,
        EvaluationType.CAUSAL_MULTI_HOP,
    ):
        assert counts[kind] >= 6, f"{kind.value} has only {counts[kind]} cases"


def test_a_superseded_document_is_named_as_a_distractor(series: World) -> None:
    current = next(
        c for c in series.evaluations if "currently in force" in c.question
    )
    assert current.distractor_artifact_ids
    for artifact_id in current.distractor_artifact_ids:
        assert series.artifacts.by_id(artifact_id).artifact_type == "close_calendar"


# ---------------------------------------------------------------------------
# The validator has to be able to fail
# ---------------------------------------------------------------------------


def test_superseding_a_later_document_is_caught(series: World) -> None:
    entries = list(series._artifacts)
    calendars = [i for i, a in enumerate(entries) if a.artifact_type == "close_calendar"]
    first, last = calendars[0], calendars[-1]
    # Point the *oldest* calendar at the newest: a document replacing its own future.
    entries[first] = entries[first].model_copy(update={"supersedes": entries[last].id})
    broken = World(**{**series.__dict__, "_artifacts": tuple(entries)})

    codes = {v.code for v in broken.validate().violations}
    assert "supersedes_later_artifact" in codes


def test_an_unmarked_superseded_document_is_caught(series: World) -> None:
    entries = list(series._artifacts)
    index = next(i for i, a in enumerate(entries) if a.lifecycle is Lifecycle.SUPERSEDED)
    entries[index] = entries[index].model_copy(update={"lifecycle": Lifecycle.PUBLISHED})
    broken = World(**{**series.__dict__, "_artifacts": tuple(entries)})

    codes = {v.code for v in broken.validate().violations}
    assert "superseded_not_marked" in codes
