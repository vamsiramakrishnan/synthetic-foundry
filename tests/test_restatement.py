"""The fourth artifact relationship: restatement.

Build-order §7 names it as the thing regulated industries force: a filed return
is immutable, so a correction is not a new version (``revises``), not a
replacement (``supersedes``), and not a derivative (``derived_from``) — it is a
restatement, and its contract *inverts* the other two. They retire their
predecessor; a restatement leaves it standing, because a filing that vanished
from the record would defeat the reason filings are immutable.

Landed ahead of the banking vertical deliberately: this is core-schema work the
vertical needs whichever episode design wins, and schema that arrives together
with its first user tends to be shaped by that user's accidents.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from worldloom import World
from worldloom.models import ArtifactIntent, ArtifactManifestEntry, Authority, Lifecycle

WHEN = datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)


def entry(artifact_id: str, *, artifact_type: str = "regulatory_return",
          created_at: datetime = WHEN, lifecycle: Lifecycle = Lifecycle.PUBLISHED,
          restates: str | None = None, supersedes: str | None = None,
          revises: str | None = None, version: int = 1) -> ArtifactManifestEntry:
    return ArtifactManifestEntry(
        id=artifact_id,
        title="A filed return",
        artifact_type=artifact_type,
        domain="finance",
        path="",
        media_type="application/x-worldloom-ir",
        author_id="PERSON-0002",
        audience="finance",
        created_at=created_at,
        authority=Authority.SYSTEM_OF_RECORD,
        lifecycle=lifecycle,
        restates=restates,
        supersedes=supersedes,
        revises=revises,
        version=version,
    )


@pytest.fixture(scope="module")
def base() -> World:
    """The golden episode, whose artifacts we graft restatement pairs onto.

    Grafting onto a real world rather than a stub means every added entry is
    also run through the referential, temporal, and access checks — a fixture
    that only exercised the new block would pass with entries no corpus could
    actually carry.
    """
    return World.load("retail-close")


def violations(world: World, *added: ArtifactManifestEntry) -> set[str]:
    grafted = replace(world, _artifacts=world._artifacts + tuple(added))
    return {v.code for v in grafted.validate().violations}


def test_a_wellformed_restatement_is_coherent(base: World) -> None:
    """The pair the relationship exists for: original filed and standing,
    correction later, same kind — and the original NOT retired."""
    codes = violations(
        base,
        entry("ART-9001"),
        entry("ART-9002", created_at=LATER, restates="ART-9001"),
    )
    assert not codes & {
        "self_restated", "conflated_relationship", "restated_twice",
        "restates_later_artifact", "restates_different_kind",
        "restated_original_retired", "dangling_ref",
    }


def test_the_original_must_stay_on_the_record(base: World) -> None:
    """The defining rule, and the inversion of supersedes/revises: a restated
    filing marked SUPERSEDED — with nothing else having replaced it — is an
    edit of an immutable document wearing a different name."""
    codes = violations(
        base,
        entry("ART-9001", lifecycle=Lifecycle.SUPERSEDED),
        entry("ART-9002", created_at=LATER, restates="ART-9001"),
    )
    assert "restated_original_retired" in codes


def test_a_correction_cannot_also_retire(base: World) -> None:
    codes = violations(
        base,
        entry("ART-9001", lifecycle=Lifecycle.SUPERSEDED),
        entry("ART-9002", created_at=LATER, restates="ART-9001", supersedes="ART-9001"),
    )
    assert "conflated_relationship" in codes

    with pytest.raises(ValueError, match="exclusive"):
        ArtifactIntent(
            id="ART-9003", artifact_type="regulatory_return", domain="finance",
            audience="finance", author_id="PERSON-0002",
            restates="ART-9001", revises="ART-9001",
        )


def test_a_restatement_cannot_precede_its_filing(base: World) -> None:
    codes = violations(
        base,
        entry("ART-9001", created_at=LATER),
        entry("ART-9002", created_at=WHEN, restates="ART-9001"),
    )
    assert "restates_later_artifact" in codes


def test_two_corrections_restate_in_a_chain_not_a_fork(base: World) -> None:
    """A second correction restates the first restatement. Two documents both
    restating the original would leave a reader unable to say which correction
    is current."""
    forked = violations(
        base,
        entry("ART-9001"),
        entry("ART-9002", created_at=LATER, restates="ART-9001"),
        entry("ART-9003", created_at=LATER, restates="ART-9001"),
    )
    assert "restated_twice" in forked

    chained = violations(
        base,
        entry("ART-9001"),
        entry("ART-9002", created_at=LATER, restates="ART-9001"),
        entry("ART-9003", created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
              restates="ART-9002"),
    )
    assert "restated_twice" not in chained


def test_a_restatement_matches_its_filings_kind(base: World) -> None:
    codes = violations(
        base,
        entry("ART-9001"),
        entry("ART-9002", artifact_type="working_note", created_at=LATER,
              restates="ART-9001"),
    )
    assert "restates_different_kind" in codes


def test_being_restated_by_something_else_replaced_is_legitimate(base: World) -> None:
    """SUPERSEDED on a restated artifact is fine when something else genuinely
    replaced it — the check attributes retirement, it does not ban it."""
    codes = violations(
        base,
        entry("ART-9001", lifecycle=Lifecycle.SUPERSEDED),
        entry("ART-9002", created_at=LATER, restates="ART-9001"),
        entry("ART-9004", created_at=LATER, supersedes="ART-9001"),
    )
    assert "restated_original_retired" not in codes


def test_provenance_carries_both_directions(base: World) -> None:
    grafted = replace(
        base,
        _artifacts=base._artifacts + (
            entry("ART-9001"),
            entry("ART-9002", created_at=LATER, restates="ART-9001"),
        ),
    )
    assert grafted.provenance("ART-9002")["restates"] == "ART-9001"
    assert grafted.provenance("ART-9001")["restated_by"] == ["ART-9002"]
