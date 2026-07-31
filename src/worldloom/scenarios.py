"""Scenarios.

A scenario is a declaration of a situation, run against a built world to produce
events, facts, artifact intents, and evaluation cases.

There is deliberately no scenario DSL here. Designing one before a second vertical
exists would encode guesses rather than recurring structure, so `MonthEndClose` is
an ordinary frozen dataclass with a `run` method. The abstraction gets extracted at
build-order step 7, once IT services has shown which parts actually repeat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .generators.operations import business_days_after, period_end
from .rng import Rng

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


def _period_boundary(period: str) -> datetime:
    """The instant an org change belonging to *period* happens at.

    Not the calendar end of the period — after it, once that period's close
    could have finished. Planning picks authors by role key, so a controller
    who departs here signs their own final close and the successor signs the
    next one, and `author_already_departed` holds without either planner
    knowing a succession happened. A departure placed mid-period would need
    every artifact in the period re-authored instead.

    Eight business days after period end is deliberately generous rather than
    the tightest bound that works. `operations.generate` can delay a close by
    one business day on an incident, and the slowest artifact any episode
    plans — the executive summary — is written up to a further day and 15
    hours after that. Eight business days clears the worst combination of
    both by more than a day in every month from 1900 to 2100 (checked by
    brute force when this constant was chosen); a tighter bound would drift
    back into `author_already_departed` the moment either lag changes. Pure
    arithmetic on the period string, the same style as `finance._closed_at`
    and `finance.previous_periods` — no clock, so replay stays byte-identical.
    """
    day = business_days_after(period_end(period), 8)
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)


def lore_index(world: World) -> dict[str, list[str]]:
    """Map each lore constraint target to the commitments that touch it.

    This is how a generated fact records *why* it looks the way it does: the
    financial generator asks for ``forecast_miss/digital`` and gets back the
    replatform commitment, which then appears in the fact's ``lore_ids``.
    """
    index: dict[str, list[str]] = {}
    for commitment in world.lore:
        for constraint in commitment.constrains:
            index.setdefault(constraint.target, []).append(commitment.id)
    return index


def likelihood_multiplier(world: World, target: str) -> float:
    """The product of every ``event_likelihood`` magnitude aimed at *target*."""
    multiplier = 1.0
    for commitment in world.lore:
        for constraint in commitment.constrains:
            if constraint.kind.value == "event_likelihood" and constraint.target == target:
                multiplier *= constraint.magnitude if constraint.magnitude is not None else 1.0
    return multiplier


def density_adjustment(world: World, target: str) -> float:
    """The summed ``artifact_density`` magnitude aimed at *target*."""
    total = 0.0
    for commitment in world.lore:
        for constraint in commitment.constrains:
            if constraint.kind.value == "artifact_density" and constraint.target == target:
                total += constraint.magnitude or 0.0
    return total


@dataclass(frozen=True)
class MonthEndClose:
    """One month-end close, with or without an operational incident.

    ``include_operational_incident`` forces the incident on or off. Left as
    ``None``, whether it happens is decided by the seed weighted by lore — which
    is the interesting behaviour, because it means the 2024 decision to maintain a
    mapping table by hand is what makes a 2026 close go wrong.
    """

    period: str
    include_operational_incident: bool | None = None
    comparative_months: int = 0
    """Prior months to generate at actual, for a trend. Zero keeps a close to itself.

    Off by default because a scenario run twice against the same world would then
    generate two sets of facts for the overlapping months, and the second would be
    a duplicate rather than a revision. A caller who wants a trend asks for one.
    """

    def run(self, world: World) -> World:
        """Return a new world with this episode's events, facts, and plans.

        The world passed in is not mutated.
        """
        from .generators import evaluation, finance, operations, planning
        from .retail import BASE_INCIDENT_LIKELIHOOD

        if world.seed is None:
            raise ValueError("a scenario needs a seeded world; use RetailWorld(seed=...).build()")
        if world._minter is None:
            raise ValueError("this world was loaded from disk and cannot be advanced; build one from a seed")

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}")
        minter = world._minter
        roles = dict(world._roles)
        index = lore_index(world)

        likelihood = BASE_INCIDENT_LIKELIHOOD * likelihood_multiplier(
            world, "data_quality_incident/inventory"
        )

        episode = operations.generate(
            rng.derive("operations"), minter,
            period=self.period,
            company_id=world.company.id,
            roles=roles,
            lore_by_target=index,
            incident_likelihood=likelihood,
            force_incident=self.include_operational_incident,
            prior_incident_periods=tuple(
                fact.period
                for fact in world.facts.where(kind="ops.incident_opened")
                if fact.period
            ),
        )

        # Unit keys come from the world rather than a literal list, because the
        # unit mix is an archetype decision — a grocer with a New Zealand division
        # and a mid-size retailer without one run the same scenario.
        unit_ids = {
            key.removeprefix("unit_"): value
            for key, value in roles.items()
            if key.startswith("unit_")
        }
        from .generators.organisation import unit_shares

        if world._archetype is None:
            raise ValueError("this world has no archetype; build one with RetailWorld(...)")

        financials = finance.generate(
            rng.derive("finance"), minter,
            period=self.period,
            company_id=world.company.id,
            unit_ids=unit_ids,
            unit_shares=unit_shares(world._archetype),
            categories=world._categories,
            sites=world._sites,
            erp_id=roles["sys_erp"],
            commerce_id=roles["sys_commerce"],
            pos_id=roles.get("sys_pos"),
            finalised_at=episode.finalised_at,
            close_event_id=episode.close_event_id,
            annual_revenue=world._annual_revenue,
            lore_by_target=index,
            comparative_months=self.comparative_months,
        )
        financial_facts = financials.headline

        intents = planning.artifact_intents(
            minter,
            episode=episode,
            roles=roles,
            financial_facts=financial_facts,
            period=self.period,
            density=1.0 + density_adjustment(world, "finance/status_reports"),
            workbook_facts=financials.facts,
            prior_intents=world._artifact_intents,
        )

        cases = evaluation.evaluation_cases(
            minter,
            episode=episode,
            facts=financials.facts,
            subjects=evaluation.Subjects(
                company_id=world.company.id,
                unit_ids=unit_ids,
                names=world.entity_names(),
                categories_by_unit={
                    unit.id: [c.id for c in world.categories if c.business_unit_id == unit.id]
                    for unit in world.business_units
                },
                sites_by_unit={
                    unit.id: [s.id for s in world.sites if s.business_unit_id == unit.id]
                    for unit in world.business_units
                },
            ),
            intents=intents,
            period=self.period,
            history=world._facts,
            prior_intents=world._artifact_intents,
        )

        return world.extend(
            events=episode.events,
            facts=(*episode.facts, *financials.facts),
            artifact_intents=intents,
            evaluations=cases,
            period=self.period,
        )


def _announcer(world, change):
    """Who signs the notice: whoever the change put in post, else the leader.

    Deterministic and derived rather than chosen — the notice's author must be
    somebody the change itself names, or the artifact would cite a person with
    no connection to the event it announces.
    """
    for person in change.people:
        if person.left is None:
            return person
    for role_id in sorted(change.roles.values()):
        person = world.people.get(role_id)
        if person is not None:
            return person
    return world.people.by_id(world._roles["ceo"])


def _personnel_notice(minter, change, successor, period: str) -> tuple:
    """The document a real company would issue when somebody leaves.

    Without this, an org change is a fact nobody wrote down. The corpus had a
    history — a departure, a hand-over, a milestone — and not one artifact
    required any of it, so `validate`'s `unreachable_answer` check correctly
    refused every evaluation case that tried to ask about it. The history was
    coherent and unaskable, which is the same as the feature not existing.

    Deliberately small and `all_staff`: an internal announcement is exactly the
    document that carries a succession, and making it a bounded note rather than
    a report keeps the narrative fan-out honest — one short piece of prose, not a
    section per fact.
    """
    from .models import ArtifactIntent

    if not change.facts:
        return ()
    return (
        ArtifactIntent(
            id=minter.next("ART"),
            artifact_type="personnel_notice",
            domain="people",
            audience="all_staff",
            author_id=successor.id,
            triggered_by=[event.id for event in change.events],
            required_fact_ids=[fact.id for fact in change.facts],
            size_profile="small",
            rationale=(
                "A change of post is announced to the organisation. It is the only "
                "record that names both the person leaving and the person taking over, "
                "which is what makes a succession answerable at all."
            ),
        ),
    )


@dataclass(frozen=True)
class Hire:
    """A new person joins the company, effective at the boundary of *period*.

    ``role_key`` becomes reachable through the world's role table from this
    point on, exactly like every role the organisation generator mints — a
    later scenario can ask for ``roles[role_key]`` without knowing whether the
    person behind it has been here since the world was built or started this
    period.
    """

    period: str
    role_key: str
    title: str
    function: str
    unit_key: str

    def run(self, world: World) -> World:
        from .generators import personnel

        if world.seed is None:
            raise ValueError("a scenario needs a seeded world; use RetailWorld(seed=...).build()")
        if world._minter is None:
            raise ValueError("this world was loaded from disk and cannot be advanced; build one from a seed")

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}/{self.role_key}")
        minter = world._minter
        roles = dict(world._roles)
        at = _period_boundary(self.period)

        change = personnel.hire(
            rng, minter,
            company_id=world.company.id,
            title=self.title,
            function=self.function,
            business_unit_id=roles[f"unit_{self.unit_key}"],
            # The unit's managing director is the default line for a new
            # position in that unit. A caller wanting a different manager has
            # no way to say so yet — this verb does not expose one — which is
            # fine for the shapes this corpus needs so far and a real gap the
            # day it does not.
            manager_id=roles[f"{self.unit_key}_md"],
            # Neither cost centres nor personas are per-unit in this world
            # (only Finance and the data platform have one; see
            # `organisation.generate`), so there is no sensible non-null
            # default for either and guessing one would be worse than leaving
            # it unset — both fields are optional on `Employee`.
            cost_centre_id=None,
            persona_id=None,
            at=at,
            period=self.period,
        )
        new_person = change.people[0]

        return world.extend(
            events=change.events,
            facts=change.facts,
            people=change.people,
            business_units=change.business_units,
            roles={**change.roles, self.role_key: new_person.id},
            period=self.period,
        )


@dataclass(frozen=True)
class Departure:
    """The holder of *role_key* leaves; the world names a successor.

    The successor is never invented — chosen deterministically from people
    already employed at the departure moment. A direct report is preferred,
    since promoting from within is the ordinary case; failing that, someone
    else in the same function, since a controller with no reports still has
    Finance peers who could plausibly take the role. Ties break on the
    lowest person id, which is also the most senior by hire order — a
    defensible tie-break that does not require inventing a performance model.
    """

    period: str
    role_key: str

    def run(self, world: World) -> World:
        from .generators import personnel

        if world.seed is None:
            raise ValueError("a scenario needs a seeded world; use RetailWorld(seed=...).build()")
        if world._minter is None:
            raise ValueError("this world was loaded from disk and cannot be advanced; build one from a seed")

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}/{self.role_key}")
        minter = world._minter
        roles = dict(world._roles)
        at = _period_boundary(self.period)

        leaver = world.people.by_id(roles[self.role_key])
        employed = world.org_at(at)

        reports = [p for p in employed if p.manager_id == leaver.id]
        peers = [p for p in employed if p.id != leaver.id and p.function == leaver.function]
        candidates = reports or peers
        if not candidates:
            raise ValueError(
                f"no eligible successor for {leaver.id} ({leaver.title}): no direct reports and "
                f"nobody else in {leaver.function} is employed at {at.isoformat()}"
            )
        successor = min(candidates, key=lambda p: p.id)

        change = personnel.depart(
            rng, minter,
            person=leaver,
            successor=successor,
            roles=roles,
            units=world._business_units,
            at=at,
            period=self.period,
        )

        return world.extend(
            events=change.events,
            facts=change.facts,
            people=change.people,
            business_units=change.business_units,
            roles=change.roles,
            artifact_intents=_personnel_notice(minter, change, _announcer(world, change), self.period),
            period=self.period,
        )


@dataclass(frozen=True)
class Reorganisation:
    """A business unit changes hands without anyone leaving.

    Distinct from ``Departure`` on purpose: the outgoing leader stays
    employed, so no ``left`` window closes and nothing but the unit's own
    leadership moves. ``new_leader_role`` names the role key of the person
    taking over — they must already be in this unit, or the graph check that
    a unit's leader belongs to it would fail the moment this scenario ran.
    """

    period: str
    unit_key: str
    new_leader_role: str

    def run(self, world: World) -> World:
        from .generators import personnel

        if world.seed is None:
            raise ValueError("a scenario needs a seeded world; use RetailWorld(seed=...).build()")
        if world._minter is None:
            raise ValueError("this world was loaded from disk and cannot be advanced; build one from a seed")

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}/{self.unit_key}")
        minter = world._minter
        roles = dict(world._roles)
        at = _period_boundary(self.period)

        unit = world.business_units.by_id(roles[f"unit_{self.unit_key}"])
        new_leader = world.people.by_id(roles[self.new_leader_role])

        change = personnel.promote(
            rng, minter,
            person=new_leader,
            title=f"Managing Director, {unit.name}",
            role_key=f"{self.unit_key}_md",
            units=(unit,),
            at=at,
            period=self.period,
        )

        return world.extend(
            events=change.events,
            facts=change.facts,
            people=change.people,
            business_units=change.business_units,
            roles=change.roles,
            artifact_intents=_personnel_notice(minter, change, _announcer(world, change), self.period),
            period=self.period,
        )


__all__ = [
    "MonthEndClose",
    "Hire",
    "Departure",
    "Reorganisation",
    "lore_index",
    "likelihood_multiplier",
    "density_adjustment",
]
