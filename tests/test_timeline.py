"""Histories that are sequences rather than counts.

Deliberately short. The three things worth pinning are the ones the feature
would be worthless without: a sampled history is reproducible from its seed, an
invalid one is refused with *every* reason at once, and the null density is
still the loop the build has always run — byte for byte, since CI regenerates a
corpus from its ledger and diffs it.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World, timeline
from worldloom.scenarios import Departure, Hire, Reorganisation


def fresh() -> World:
    """A world nobody has advanced yet.

    Built per test rather than shared, wherever a test actually runs anything:
    a ``World`` is immutable but its ``Minter`` is not, so two histories run
    against one built world mint from a counter the first one already moved.
    Comparing ids across them would then fail for a reason that has nothing to
    do with what is being tested.
    """
    return RetailWorld(seed=8128).build()


@pytest.fixture(scope="module")
def world() -> World:
    """Shared, for the tests that only read the organisation off it."""
    return fresh()


@pytest.fixture(scope="module")
def roster(world: World) -> timeline.Roster:
    return timeline.Roster.of(world)


# ---------------------------------------------------------------------------
# 1. Reproducible from the seed, and from nothing else
# ---------------------------------------------------------------------------


def test_sampling_is_reproducible(roster: timeline.Roster) -> None:
    def once() -> tuple[tuple[str, str], ...]:
        return timeline.sample(
            roster=roster, start="2026-01", periods=6, seed=8128,
            density=timeline.TURBULENT,
            openings=[timeline.Opening("digital_analyst", "Digital Trading Analyst",
                                       "Merchandising", "digital")],
        ).outline()

    assert once() == once()


def test_a_different_seed_casts_different_people(roster: timeline.Roster) -> None:
    """Placement is seed-free by design and casting is not, so two seeds give
    the same *shape* of history with different subjects in it. That split is
    the whole sampling argument — see `_spread`."""
    def sampled(seed: int) -> timeline.Timeline:
        return timeline.sample(roster=roster, start="2026-01", periods=12,
                               seed=seed, density=timeline.STEADY)

    first, second = sampled(8128), sampled(42)
    assert first.outline() == second.outline(), "the shape must not depend on the seed"
    departures = [
        tuple(step.role_key for step in history if isinstance(step, Departure))
        for history in (first, second)
    ]
    assert departures[0] != departures[1], "who leaves must depend on the seed"


# ---------------------------------------------------------------------------
# 2. The null density is still today's build loop, byte for byte
# ---------------------------------------------------------------------------


def test_quiet_sampling_is_the_loop_that_exists(roster: timeline.Roster) -> None:
    """`QUIET` states no incident anywhere and schedules no org change, so it
    has to reduce to the six identical closes `--periods 6` runs. If it did
    not, adopting this module anywhere would move a byte in every corpus."""
    sampled = timeline.sample(roster=roster, start="2026-01", periods=6, seed=8128)
    assert list(sampled) == list(timeline.monthly("2026-01", 6))
    assert list(sampled) == [MonthEndClose(period=period) for period in
                             ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06")]

    ran = sampled.run(fresh())
    looped = fresh()
    for period in sampled.periods():
        looped = looped.run(MonthEndClose(period=period))
    assert ran._recipe == looped._recipe
    assert ran.facts.ids() == looped.facts.ids()
    assert [fact.text_value for fact in ran.facts] == [f.text_value for f in looped.facts]


# ---------------------------------------------------------------------------
# 3. Refusal: all of it at once, each naming its rule
# ---------------------------------------------------------------------------


def test_every_violation_is_reported_not_the_first(roster: timeline.Roster) -> None:
    broken = timeline.of(
        # Hires over a role the retail engine resolves by name, into a unit
        # that does not exist, with no title.
        Hire(period="2026-01", role_key="controller", title="  ",
             function="Finance", unit_key="nowhere"),
        # Departs a role nobody holds; reorganises a unit that does not exist
        # and hands it to somebody sitting in another one.
        Departure(period="2026-02", role_key="head_of_nothing"),
        Reorganisation(period="2026-03", unit_key="food", new_leader_role="digital_bp"),
        # …and then runs the calendar backwards.
        MonthEndClose(period="2025-12"),
    )
    rules = {violation.rule for violation in timeline.review(broken, roster)}
    assert rules == {
        "hire_into_a_load_bearing_role",
        "unknown_unit",
        "untitled",
        "depart_an_unfilled_role",
        "leader_outside_the_unit",
        "history_runs_backwards",
    }

    with pytest.raises(timeline.TimelineError) as raised:
        timeline.ensure(broken, roster)
    # Every rule has to reach the message: a caller who fixes one and hits the
    # next has been made to discover their history one defect at a time.
    assert all(rule in str(raised.value) for rule in rules)


def test_a_change_may_not_precede_its_own_episode(roster: timeline.Roster) -> None:
    """`scenarios._period_boundary` puts an org change eight business days
    after its period's close, so the close it precedes in the list would be
    planned against a successor who took over after that month ended."""
    out_of_order = timeline.of(
        Departure(period="2026-01", role_key="controller"),
        MonthEndClose(period="2026-01"),
    )
    assert [violation.rule for violation in timeline.review(out_of_order, roster)] == [
        "change_lands_before_its_own_episode"
    ]
    assert not timeline.review(
        timeline.of(MonthEndClose(period="2026-01"),
                    Departure(period="2026-01", role_key="controller")),
        roster,
    )


def test_hiring_over_a_bound_key_is_refused_by_the_scenario_too(world: World) -> None:
    """The up-front review is the predictable rejection, not the only one."""
    with pytest.raises(ValueError, match="already bound"):
        world.run(Hire(period="2026-01", role_key="sys_erp", title="Analyst",
                       function="Finance", unit_key="food"))


# ---------------------------------------------------------------------------
# 4. The payoff: one corpus whose organisation changes inside its own history
# ---------------------------------------------------------------------------


def test_a_sampled_history_changes_who_signs_and_still_validates(
    roster: timeline.Roster,
) -> None:
    world = fresh()
    history = timeline.sample(
        roster=roster, start="2026-01", periods=6, seed=8128, density=timeline.STEADY,
    )
    departures = [step for step in history if isinstance(step, Departure)]
    assert departures, "STEADY over six periods should schedule a departure"
    leaver_role = departures[0].role_key
    leaver_id = world._roles[leaver_role]

    # Which months went wrong is stated in both directions, so "which one" is
    # answerable from the history rather than from the seed's coin.
    incidents = {step.period for step in history
                 if isinstance(step, MonthEndClose) and step.include_operational_incident}
    assert 0 < len(incidents) < len(history.periods())

    advanced = history.run(world)
    assert advanced._roles[leaver_role] != leaver_id, "the post changed hands"
    assert advanced.people.by_id(leaver_id).left is not None

    # The claim the whole feature rests on: the post is signed by two different
    # people inside one corpus. Before this module there was no way for a build
    # to produce that at all, which is why `author_already_departed` had never
    # had a corpus to fire on.
    successor_id = advanced._roles[leaver_role]
    authors = {intent.author_id for intent in advanced.artifact_intents}
    assert successor_id in authors

    # And `left` is exclusive, so the leaver's own final close is still theirs:
    # nothing they authored may be dated after they were gone. That is what
    # `_period_boundary`'s eight business days buy, and the validator's
    # temporal group re-checks it below over every rendered document.
    gone = {person.id: person.left for person in advanced.people if person.left is not None}
    assert leaver_id in gone
    occurred = {event.id: event.occurred_at for event in advanced.events}
    for intent in advanced.artifact_intents:
        left_at = gone.get(intent.author_id)
        if left_at is None:
            continue
        assert all(occurred[event_id] < left_at
                   for event_id in intent.triggered_by if event_id in occurred)

    report = advanced.compile().validate()
    assert report.ok, report.violations[:5]

    # And it rebuilds from what it wrote down, with no recipe verb added for it.
    from worldloom.recipe import rebuild

    replayed = rebuild(advanced._recipe)
    assert replayed.facts.ids() == advanced.facts.ids()
    assert replayed._roles == advanced._roles


def test_a_unit_may_be_handed_to_somebody_hired_after_it_existed() -> None:
    """A defect this feature found, kept as a test because it will come back.

    ``leader_not_yet_employed`` measured a unit's leader against the unit's
    *formation*, on the assumption that ``leader_id`` always names the founding
    leader — true only while nothing could reorganise. Seed 2 promotes somebody
    hired in 2024 to lead a division formed in 2022, which is an ordinary
    company and used to be a temporal violation.
    """
    world = RetailWorld(seed=2).build()
    history = timeline.sample(roster=timeline.Roster.of(world), start="2026-01",
                              periods=6, seed=2, density=timeline.STEADY)
    handovers = [step for step in history if isinstance(step, Reorganisation)]
    assert handovers, "seed 2 at STEADY should reorganise once"

    unit = world.business_units.by_id(world._roles[f"unit_{handovers[0].unit_key}"])
    leader = world.people.by_id(world._roles[handovers[0].new_leader_role])
    assert leader.joined > unit.formed, "the case is only interesting if they joined later"

    report = history.run(world).compile().validate()
    assert report.ok, report.violations[:5]
