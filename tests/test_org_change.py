"""Org change: people join, people leave, units get new leaders.

The corpus's central claim is that a change is only real if it is witnessed —
an event, a fact, and (for a departure or a leadership change) a roster entry
that keeps its identity rather than being replaced by a new one. This module
exercises the succession path hardest, because it is the one with a temporal
trap built in: a controller who signs a report and later leaves must never be
made to look like they signed it after they were gone.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.generators import personnel
from worldloom.ids import Minter
from worldloom.rng import Rng
from worldloom.scenarios import Departure


@pytest.fixture(scope="module")
def base() -> World:
    """One close, so a departure has something to succeed and something to sign."""
    return RetailWorld(seed=8128).build().run(MonthEndClose("2026-03"))


@pytest.fixture(scope="module")
def succession(base: World) -> World:
    """The departure this whole module is about: the controller leaves."""
    return base.run(Departure("2026-03", "controller"))


# ---------------------------------------------------------------------------
# 1. A departure keeps the person's identity
# ---------------------------------------------------------------------------


def test_departure_keeps_person_id_and_count(base: World, succession: World) -> None:
    """The roster does not grow. A person who leaves is the person who was
    here — not a second record with the same name, which would be a
    different human wearing their job title."""
    leaver_id = base._roles["controller"]

    assert len(succession.people) == len(base.people)
    assert leaver_id in succession.people.ids()

    leaver = succession.people.by_id(leaver_id)
    assert leaver.name == base.people.by_id(leaver_id).name
    assert leaver.left is not None
    assert leaver.joined == base.people.by_id(leaver_id).joined


# ---------------------------------------------------------------------------
# 2. org_at respects the departure window, and the window is half-open
# ---------------------------------------------------------------------------


def test_org_at_reflects_the_departure_window(base: World, succession: World) -> None:
    leaver_id = base._roles["controller"]
    departed_at = succession.people.by_id(leaver_id).left
    assert departed_at is not None

    before = departed_at - timedelta(seconds=1)
    assert leaver_id in succession.org_at(before).ids()

    after = departed_at + timedelta(seconds=1)
    assert leaver_id not in succession.org_at(after).ids()

    # `left` is exclusive: the instant the window closes, not the last
    # instant inside it. Someone's last day is a day they worked, which is
    # exactly what makes the artifacts they signed that day still valid.
    assert leaver_id not in succession.org_at(departed_at).ids()


# ---------------------------------------------------------------------------
# 3. The rebind is what makes the next close plan against the successor
# ---------------------------------------------------------------------------


def test_departure_rebinds_roles_for_the_next_close(base: World, succession: World) -> None:
    leaver_id = base._roles["controller"]
    successor_id = succession._roles["controller"]
    assert successor_id != leaver_id

    before_ids = set(succession.artifact_intents.ids())
    after = succession.run(MonthEndClose("2026-04"))
    new_intents = [i for i in after.artifact_intents if i.id not in before_ids]

    assert new_intents, "the April close should have planned something"
    authored_by = {i.author_id for i in new_intents}
    assert leaver_id not in authored_by, "the person who left cannot author a later period"
    assert successor_id in authored_by, "the successor should sign what the controller used to"


# ---------------------------------------------------------------------------
# 4. The real test: the whole series still validates clean
# ---------------------------------------------------------------------------


def test_the_series_validates_clean(succession: World) -> None:
    series = succession.run(MonthEndClose("2026-04")).compile()
    report = series.validate()
    assert report.ok, report.violations[:5]


# ---------------------------------------------------------------------------
# 5. Determinism
# ---------------------------------------------------------------------------


def _build_series() -> World:
    world = RetailWorld(seed=8128).build()
    world = world.run(MonthEndClose("2026-03"))
    world = world.run(Departure("2026-03", "controller"))
    world = world.run(MonthEndClose("2026-04"))
    return world


def test_determinism() -> None:
    first = _build_series()
    second = _build_series()

    assert first.people.ids() == second.people.ids()
    assert first.events.ids() == second.events.ids()
    assert first.facts.ids() == second.facts.ids()
    assert first._roles == second._roles


# ---------------------------------------------------------------------------
# 6. An incoherent succession must not be produced
# ---------------------------------------------------------------------------


def test_departure_rejects_a_successor_not_yet_employed(base: World) -> None:
    leaver_id = base._roles["controller"]
    leaver = base.people.by_id(leaver_id)
    at = leaver.joined or list(base.events)[0].occurred_at

    # A person who joins strictly after the departure moment cannot have
    # already been holding the fort — the exact bug `depart` exists to refuse
    # rather than let the validator discover three scenarios later.
    not_yet_employed = base.people.by_id(base._roles["reporting_manager"]).model_copy(
        update={"joined": at + timedelta(days=1)}
    )

    with pytest.raises(ValueError):
        personnel.depart(
            Rng(base.seed or 0),
            Minter(),
            person=leaver,
            successor=not_yet_employed,
            roles=dict(base._roles),
            units=base._business_units,
            at=at,
            period="2026-03",
        )
