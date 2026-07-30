"""Tests for temporal lifetimes and the third artifact relationship.

Nothing in the corpus yet sets `joined`, `left`, `formed`, `dissolved`, or
`revises`, so the whole suite passes vacuously against generated worlds. These
tests hand-build the cases the fields exist for — a departure, a unit that
closes, a revision chain — so the semantics are pinned down before a generator
has to honour them.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from worldloom import RetailWorld, World
from worldloom.models import (
    ArtifactIntent,
    ArtifactManifestEntry,
    Authority,
    BusinessUnit,
    CanonicalFact,
    Employee,
    Lifecycle,
    Quantity,
)


@pytest.fixture(scope="module")
def world() -> World:
    # A freshly built world, before any scenario has run: no facts, intents, or
    # artifacts yet, so a hand-built violation is never confused with a real one.
    return RetailWorld(seed=8128).build()


# -- doctoring helpers ---------------------------------------------------
# `World` and its entities are all frozen, so every case here is built by
# replacing one field on a copy — never by mutating the fixture.


def _employee_with(world: World, employee_id: str, **updates) -> World:
    """A copy of *world* with one employee's fields overridden."""
    updated = world.people.by_id(employee_id).model_copy(update=updates)
    people = tuple(updated if p.id == employee_id else p for p in world._people)
    return replace(world, _people=people)


def _unit_with(world: World, unit_id: str, **updates) -> World:
    """A copy of *world* with one business unit's fields overridden."""
    updated = world.business_units.by_id(unit_id).model_copy(update=updates)
    units = tuple(updated if u.id == unit_id else u for u in world._business_units)
    return replace(world, _business_units=units)


def _artifact(artifact_id: str, *, author_id: str, created_at: datetime, artifact_type: str = "working_note", **updates) -> ArtifactManifestEntry:
    """A minimal, otherwise-innocuous manifest entry to doctor one field on."""
    return ArtifactManifestEntry(
        id=artifact_id,
        title=artifact_id,
        artifact_type=artifact_type,
        domain="finance",
        path="",
        media_type="text/markdown",
        author_id=author_id,
        audience="all_staff",
        created_at=created_at,
        authority=Authority.WORKING_DOCUMENT,
        lifecycle=Lifecycle.DRAFT,
        **updates,
    )


def _with_artifacts(world: World, *entries: ArtifactManifestEntry) -> World:
    return replace(world, _artifacts=world._artifacts + entries)


def _violation_codes(world: World) -> set[str]:
    return {v.code for v in world.validate().violations}


# ---------------------------------------------------------------------------
# World.org_at — the window semantics
# ---------------------------------------------------------------------------


def test_org_at_returns_the_whole_roster_when_nobody_joins_or_leaves(world: World) -> None:
    """joined=None/left=None is the compatibility guarantee: a world that
    predates windows must answer org_at the same way at every moment, which is
    exactly what it did before windows existed."""
    everybody = set(world.people.ids())
    for moment in (datetime(2000, 1, 1), datetime(2026, 3, 15), datetime(2099, 12, 31)):
        assert set(world.org_at(moment).ids()) == everybody


def test_org_at_is_present_from_the_instant_joined(world: World) -> None:
    person_id = world.people[5].id
    joined = datetime(2026, 6, 1, 9, 0)
    doctored = _employee_with(world, person_id, joined=joined)

    assert person_id not in doctored.org_at(joined - timedelta(days=1)).ids()
    assert person_id in doctored.org_at(joined).ids(), "inclusive at the start"
    assert person_id in doctored.org_at(joined + timedelta(days=1)).ids()


def test_org_at_left_is_exclusive_at_the_instant(world: World) -> None:
    """The subtle off-by-one this suite exists to pin down: someone's last day
    is a day they worked, so `left` is the instant the window closes rather
    than the last instant inside it."""
    person_id = world.people[5].id
    left = datetime(2026, 6, 1, 17, 0)
    doctored = _employee_with(world, person_id, left=left)

    assert person_id in doctored.org_at(left - timedelta(microseconds=1)).ids()
    assert person_id not in doctored.org_at(left).ids()


# ---------------------------------------------------------------------------
# _merged — the merge-by-id semantics on World.extend
# ---------------------------------------------------------------------------


def test_extend_replaces_an_existing_person_without_growing_the_roster(world: World) -> None:
    person_id = world.people[3].id
    updated = world.people.by_id(person_id).model_copy(update={"title": "Retired"})

    grown = world.extend(people=(updated,))

    assert len(grown.people) == len(world.people)
    assert grown.people.by_id(person_id).title == "Retired"


def test_extend_keeps_the_replacements_original_position(world: World) -> None:
    """Order reaches the corpus files and the manifest, so a merge that appended
    updates instead would reshuffle a world merely because someone left."""
    person_id = world.people[10].id
    original_index = world.people.ids().index(person_id)
    updated = world.people.by_id(person_id).model_copy(update={"left": datetime(2026, 6, 1)})

    grown = world.extend(people=(updated,))

    assert grown.people.ids().index(person_id) == original_index


def test_extend_appends_a_new_person_at_the_tail(world: World) -> None:
    new_person = Employee(id="PERSON-9999", name="New Hire", title="Analyst", function="Finance")

    grown = world.extend(people=(new_person,))

    assert len(grown.people) == len(world.people) + 1
    assert grown.people.ids()[-1] == "PERSON-9999"


def test_extend_mixes_replacement_and_append_in_one_call(world: World) -> None:
    replaced_id = world.people[7].id
    original_index = world.people.ids().index(replaced_id)
    replaced = world.people.by_id(replaced_id).model_copy(update={"left": datetime(2026, 6, 1)})
    new_person = Employee(id="PERSON-9998", name="New Hire", title="Analyst", function="Finance")

    grown = world.extend(people=(replaced, new_person))

    assert len(grown.people) == len(world.people) + 1
    assert grown.people.ids().index(replaced_id) == original_index
    assert grown.people.ids()[-1] == "PERSON-9998"


def test_extend_merges_business_units_by_id_the_same_way(world: World) -> None:
    unit_id = world.business_units[0].id
    original_index = world.business_units.ids().index(unit_id)
    dissolved = world.business_units.by_id(unit_id).model_copy(update={"dissolved": datetime(2026, 6, 1)})
    new_unit = BusinessUnit(id="BU-9999", name="New Unit", company_id=world.company.id, leader_id=world.people[0].id, kind="test")

    grown = world.extend(business_units=(dissolved, new_unit))

    assert len(grown.business_units) == len(world.business_units) + 1
    assert grown.business_units.ids().index(unit_id) == original_index
    assert grown.business_units.by_id(unit_id).dissolved == datetime(2026, 6, 1)
    assert grown.business_units.ids()[-1] == "BU-9999"


def test_extend_with_neither_leaves_both_tuples_the_very_same_object(world: World) -> None:
    """`_merged` returns the existing tuple by identity when nothing is passed
    in — the meaningful guarantee, since extend() should not even reallocate a
    roster that did not change."""
    grown = world.extend(period="2026-03")

    assert grown._people is world._people
    assert grown._business_units is world._business_units


def test_extend_roles_merges_rather_than_replaces(world: World) -> None:
    """Naming one post in a scenario must not blank out every other role key —
    otherwise a departure would erase the CEO from the corpus along with the
    controller who actually left."""
    assert "ceo" in world._roles and "controller" in world._roles

    grown = world.extend(roles={"controller": "PERSON-9997"})

    assert grown._roles["controller"] == "PERSON-9997"
    assert grown._roles["ceo"] == world._roles["ceo"]


def test_extend_never_mutates_the_original_world(world: World) -> None:
    before_people = tuple(world._people)
    before_units = tuple(world._business_units)
    before_roles = dict(world._roles)

    world.extend(
        people=(world.people.by_id(world.people[0].id).model_copy(update={"title": "Changed"}),),
        business_units=(world.business_units.by_id(world.business_units[0].id).model_copy(update={"kind": "changed"}),),
        roles={"controller": "PERSON-0000"},
    )

    assert world._people == before_people
    assert world._business_units == before_units
    assert world._roles == before_roles


# ---------------------------------------------------------------------------
# The validator's new invariants — assert they actually fire
# ---------------------------------------------------------------------------


def test_author_not_yet_employed_fires_and_clears(world: World) -> None:
    author_id = world.people[8].id
    created_at = datetime(2026, 3, 15)
    artifact = _artifact("ART-TEST-JOIN", author_id=author_id, created_at=created_at)

    too_late = _with_artifacts(_employee_with(world, author_id, joined=created_at + timedelta(days=1)), artifact)
    assert "author_not_yet_employed" in _violation_codes(too_late)

    in_time = _with_artifacts(_employee_with(world, author_id, joined=created_at - timedelta(days=1)), artifact)
    assert "author_not_yet_employed" not in _violation_codes(in_time)


def test_author_already_departed_boundary_matches_org_ats_exclusivity(world: World) -> None:
    """`left == created_at` must fail — the author's window is already closed by
    the strict `<=` in the check, matching org_at's exclusive `left`. One
    microsecond later, the same artifact is fine."""
    author_id = world.people[9].id
    created_at = datetime(2026, 3, 15, 9, 0)
    artifact = _artifact("ART-TEST-LEFT", author_id=author_id, created_at=created_at)

    exactly_at_left = _with_artifacts(_employee_with(world, author_id, left=created_at), artifact)
    assert "author_already_departed" in _violation_codes(exactly_at_left)

    just_after_left = _with_artifacts(
        _employee_with(world, author_id, left=created_at + timedelta(microseconds=1)), artifact
    )
    assert "author_already_departed" not in _violation_codes(just_after_left)


def test_employment_reversed_fires_when_left_precedes_joined(world: World) -> None:
    person_id = world.people[6].id

    reversed_world = _employee_with(world, person_id, joined=datetime(2026, 6, 1), left=datetime(2026, 1, 1))
    assert "employment_reversed" in _violation_codes(reversed_world)

    ordered_world = _employee_with(world, person_id, joined=datetime(2026, 1, 1), left=datetime(2026, 6, 1))
    assert "employment_reversed" not in _violation_codes(ordered_world)


def test_unit_window_reversed_fires_when_dissolved_precedes_formed(world: World) -> None:
    unit_id = world.business_units[0].id

    reversed_world = _unit_with(world, unit_id, formed=datetime(2026, 6, 1), dissolved=datetime(2026, 1, 1))
    assert "unit_window_reversed" in _violation_codes(reversed_world)

    ordered_world = _unit_with(world, unit_id, formed=datetime(2026, 1, 1), dissolved=datetime(2026, 6, 1))
    assert "unit_window_reversed" not in _violation_codes(ordered_world)


def test_leader_not_yet_employed_fires_when_leader_joins_after_the_unit_forms(world: World) -> None:
    unit = world.business_units[0]
    formed = datetime(2026, 3, 1)

    late_leader = _employee_with(world, unit.leader_id, joined=formed + timedelta(days=1))
    violating = _unit_with(late_leader, unit.id, formed=formed)
    assert "leader_not_yet_employed" in _violation_codes(violating)

    early_leader = _employee_with(world, unit.leader_id, joined=formed - timedelta(days=1))
    fixed = _unit_with(early_leader, unit.id, formed=formed)
    assert "leader_not_yet_employed" not in _violation_codes(fixed)


# ---------------------------------------------------------------------------
# Version derivation and the revision chain
# ---------------------------------------------------------------------------


def _chained_intents(world: World, count: int, *, revise: bool, artifact_type: str = "working_note"):
    """*count* intents citing one fact, chained by `revises` unless *revise* is False."""
    fact = CanonicalFact(
        id="FACT-CHAIN-0001",
        kind="test.chain",
        subject=world.company.id,
        value=Quantity(amount=1.0, unit="unit"),
        valid_from=datetime(2026, 1, 1),
        authority=Authority.CONFIRMED,
    )
    author_id = world.people[0].id
    intents = []
    for i in range(1, count + 1):
        previous = f"ART-CHAIN-{i - 1:04d}" if revise and i > 1 else None
        intents.append(
            ArtifactIntent(
                id=f"ART-CHAIN-{i:04d}",
                artifact_type=artifact_type,
                domain="finance",
                audience="all_staff",
                author_id=author_id,
                required_fact_ids=[fact.id],
                revises=previous,
            )
        )
    return world.extend(facts=(fact,), artifact_intents=tuple(intents))


def test_version_is_derived_from_the_length_of_the_revises_chain(world: World) -> None:
    """version is derived from chain length, not carried — a chain of three
    intents must produce manifest versions 1, 2, 3."""
    chained = _chained_intents(world, 3, revise=True)
    compiled = chained.compile()

    versions = {a.intent_id: a.version for a in compiled.artifacts}
    assert versions["ART-CHAIN-0001"] == 1
    assert versions["ART-CHAIN-0002"] == 2
    assert versions["ART-CHAIN-0003"] == 3


def test_a_revised_predecessor_is_marked_superseded(world: World) -> None:
    chained = _chained_intents(world, 3, revise=True)
    compiled = chained.compile()

    by_intent = {a.intent_id: a for a in compiled.artifacts}
    assert by_intent["ART-CHAIN-0001"].lifecycle is Lifecycle.SUPERSEDED
    assert by_intent["ART-CHAIN-0002"].lifecycle is Lifecycle.SUPERSEDED
    assert by_intent["ART-CHAIN-0003"].lifecycle is not Lifecycle.SUPERSEDED


def test_a_world_with_no_revisions_has_every_artifact_at_version_one(world: World) -> None:
    """The default has to be right, because every existing corpus — including
    the golden episode — has never carried a revision and relies on this."""
    unrelated = _chained_intents(world, 3, revise=False)
    compiled = unrelated.compile()

    assert all(a.version == 1 for a in compiled.artifacts)


def test_self_revised_is_caught(world: World) -> None:
    author_id = world.people[0].id
    entry = _artifact("ART-SELFREV", author_id=author_id, created_at=datetime(2026, 3, 1), revises="ART-SELFREV")

    doctored = _with_artifacts(world, entry)
    assert "self_revised" in _violation_codes(doctored)


def test_revised_twice_is_caught(world: World) -> None:
    """A version history is a line, not a tree: one predecessor cannot have two
    successors both claiming to be the next version of it."""
    author_id = world.people[0].id
    original = _artifact("ART-REV-ORIG", author_id=author_id, created_at=datetime(2026, 3, 1))
    first_revision = _artifact(
        "ART-REV-A", author_id=author_id, created_at=datetime(2026, 3, 2), revises="ART-REV-ORIG", version=2
    )
    second_revision = _artifact(
        "ART-REV-B", author_id=author_id, created_at=datetime(2026, 3, 3), revises="ART-REV-ORIG", version=2
    )

    doctored = _with_artifacts(world, original, first_revision, second_revision)
    assert "revised_twice" in _violation_codes(doctored)


def test_version_not_advanced_is_caught(world: World) -> None:
    author_id = world.people[0].id
    original = _artifact("ART-VER-ORIG", author_id=author_id, created_at=datetime(2026, 3, 1), version=2)
    stalled = _artifact(
        "ART-VER-NEW", author_id=author_id, created_at=datetime(2026, 3, 2), revises="ART-VER-ORIG", version=2
    )

    doctored = _with_artifacts(world, original, stalled)
    assert "version_not_advanced" in _violation_codes(doctored)


def test_revises_different_kind_is_caught(world: World) -> None:
    author_id = world.people[0].id
    original = _artifact(
        "ART-KIND-ORIG", author_id=author_id, created_at=datetime(2026, 3, 1), artifact_type="working_note"
    )
    revision = _artifact(
        "ART-KIND-NEW",
        author_id=author_id,
        created_at=datetime(2026, 3, 2),
        artifact_type="knowledge_article",
        revises="ART-KIND-ORIG",
        version=2,
    )

    doctored = _with_artifacts(world, original, revision)
    assert "revises_different_kind" in _violation_codes(doctored)
