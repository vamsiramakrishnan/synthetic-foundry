"""The world's beginning: founding milestones, and validity windows on entities.

Two gaps closed at once. Lore asserts dated things ("remapped in 2024-08") that,
before this, nothing on the timeline witnessed — every dated commitment now gets
a milestone event and a fact. And every ``Employee``/``BusinessUnit`` used to have
``joined``/``formed`` fixed at ``None``, which made the temporal invariants in
``validate.py`` (``leader_not_yet_employed``, ``author_not_yet_employed``, ...)
vacuously true. This is what actually exercises them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from worldloom.retail import RetailWorld, MonthEndClose

#: The earliest a close period can start in this corpus (the CLI's own default
#: is "2026-03"); every generated `joined` must sit comfortably before this.
EARLIEST_CLOSE = datetime(2026, 1, 1, tzinfo=timezone.utc)


# -- founding milestones ------------------------------------------------------


def test_every_dated_lore_commitment_gets_a_milestone() -> None:
    world = RetailWorld(seed=8128).build()
    dated = [c for c in world.lore if c.effective_from]

    assert len(world.events) == len(dated)
    assert len(world.facts) == len(dated)

    events_by_lore = {lore_id: e for e in world.events for lore_id in e.lore_ids}
    facts_by_lore = {lore_id: f for f in world.facts for lore_id in f.lore_ids}

    for commitment in dated:
        assert commitment.id in events_by_lore, f"{commitment.id} has no milestone event"
        assert commitment.id in facts_by_lore, f"{commitment.id} has no founding fact"


def test_a_milestone_events_month_matches_its_commitments_effective_from() -> None:
    world = RetailWorld(seed=8128).build()
    for commitment in world.lore:
        if not commitment.effective_from:
            continue
        year, month = (int(part) for part in commitment.effective_from.split("-"))
        event = next(e for e in world.events if commitment.id in e.lore_ids)
        assert (event.occurred_at.year, event.occurred_at.month) == (year, month)


def test_a_founding_facts_valid_from_equals_its_events_occurred_at() -> None:
    """`validate.py`'s `fact_precedes_event` would otherwise catch this."""
    world = RetailWorld(seed=8128).build()
    for fact in world.facts:
        event = world.events.by_id(fact.event_id)
        assert fact.valid_from == event.occurred_at


def test_a_founding_facts_lore_ids_name_its_own_commitment() -> None:
    """The whole point: `World.provenance()` on a document citing this fact
    reaches the lore that shaped it."""
    world = RetailWorld(seed=8128).build()
    for fact in world.facts:
        assert len(fact.lore_ids) == 1
        commitment = world.lore.by_id(fact.lore_ids[0])
        assert fact.text_value == commitment.assertion


# -- validity windows on people and units -------------------------------------


def test_every_person_has_joined_and_nobody_has_left() -> None:
    """Departures are a scenario's concern (another agent's work); a freshly
    built world only establishes the beginning."""
    world = RetailWorld(seed=8128).build()
    assert len(world.people) > 0
    for person in world.people:
        assert person.joined is not None
        assert person.left is None


def test_every_join_date_precedes_the_earliest_close_period() -> None:
    """A `joined` on or after a close period would fail `author_not_yet_employed`
    the moment that person authors anything in it."""
    world = RetailWorld(seed=8128).build()
    for person in world.people:
        assert person.joined < EARLIEST_CLOSE, f"{person.id} joined too late: {person.joined}"


def test_join_dates_are_spread_not_uniform() -> None:
    """An executive who has been here a decade and an analyst hired last year —
    not everyone starting on the same day, which is what makes `org_at` produce
    a different roster at different moments."""
    world = RetailWorld(seed=8128).build()
    joined = {p.joined for p in world.people}
    assert len(joined) > 1


def test_every_units_leader_joined_on_or_before_it_formed() -> None:
    world = RetailWorld(seed=8128).build()
    for unit in world.business_units:
        assert unit.formed is not None
        assert unit.dissolved is None
        leader = world.people.by_id(unit.leader_id)
        assert leader.joined <= unit.formed, (
            f"{unit.id} formed {unit.formed} under {leader.id}, who joined {leader.joined}"
        )


# -- the world stays coherent --------------------------------------------------


def test_a_freshly_built_world_validates_clean() -> None:
    report = RetailWorld(seed=8128).build().validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_a_world_with_a_close_run_still_validates_clean() -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    report = world.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


# -- determinism ----------------------------------------------------------------


def test_founding_is_deterministic() -> None:
    """Same seed, same joins, same milestone ids — the whole point of `Rng`
    and `Minter` being seeded rather than drawing from the process clock."""
    first = RetailWorld(seed=8128).build()
    second = RetailWorld(seed=8128).build()

    assert [p.joined for p in first.people] == [p.joined for p in second.people]
    assert [u.formed for u in first.business_units] == [u.formed for u in second.business_units]
    assert first.events.ids() == second.events.ids()
    assert first.facts.ids() == second.facts.ids()


def test_a_different_seed_spreads_joins_differently() -> None:
    first = RetailWorld(seed=8128).build()
    other = RetailWorld(seed=9001).build()
    assert [p.joined for p in first.people] != [p.joined for p in other.people]


# -- the id-stability regression guard ------------------------------------------


def test_founding_milestones_do_not_renumber_existing_entity_ids() -> None:
    """Founding events and facts are minted last, and facts use their own
    "MFACT" sequence rather than "FACT" — see the comment on
    `organisation._founding_milestones` for why. If either of these ids ever
    changes, a PERSON or BU id shifted underneath the reference narration in
    `examples/grocery-close/narration.json`, which cites facts by id and will
    start rejecting on `worldloom narrate accept`.

    seed=8128, the default archetype: PERSON-0005 is the person who was the
    fifth minted into the role table (Managing Director, General Merchandise),
    and BU-0001 is the first business unit (Food) — both minted before any
    founding milestone exists, so neither should ever move.
    """
    world = RetailWorld(seed=8128).build()

    person = world.people.by_id("PERSON-0005")
    assert person.title == "Managing Director, General Merchandise"

    unit = world.business_units.by_id("BU-0001")
    assert unit.name == "Food"

    # Founding facts must never take a "FACT" number: that sequence belongs to
    # whatever a scenario mints first (the close calendar's due date has always
    # been FACT-0001), and the reference narration cites it by that exact id.
    assert all(f.id.startswith("MFACT-") for f in world.facts)
    assert all(e.id.startswith("EV-") for e in world.events)
