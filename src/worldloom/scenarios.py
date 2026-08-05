"""Scenarios.

A scenario is a declaration of a situation, run against a built world to produce
events, facts, artifact intents, and evaluation cases.

There is deliberately no scenario DSL here. Designing one before a second vertical
exists would encode guesses rather than recurring structure, so `MonthEndClose` is
an ordinary frozen dataclass with a `run` method. The abstraction gets extracted at
build-order step 7, once IT services has shown which parts actually repeat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .generators.operations import business_days_after, period_end
from . import profiles as _profiles
from .parameters import DEFAULT, Parameters
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
    trend_pct: float = 0.0
    """Monthly compound growth behind the comparative history. Zero is flat.

    Only meaningful with ``comparative_months``: it shapes the *history*, and
    a close with no history has nothing to shape. Zero by default, and zero
    multiplies every figure by exactly 1.0, so a corpus built without it is
    byte-identical to one built before the knob existed — the same discipline
    ``eval_density`` follows below and for the same reason.
    """
    actors: Any = field(default=None, compare=False)
    """An ``ActorProvider``. ``None`` keeps the deterministic plan.

    When set, the incident's *organisational* layer — the ticket, the work notes,
    the assignments, the close decision, and the seven documents that come out of
    it — is produced by employees calling tools on what they had actually
    observed, rather than by a planner reading the whole fact ledger. What does
    not change is the world's physics: the pipeline still fails because the
    operational generator says so, and the cause is still the stale mapping,
    because an actor that could choose the root cause would be authoring
    canonical truth.
    """
    actor_ledger: tuple = field(default=(), compare=False)
    """Recorded actor decisions to replay instead of asking the provider."""

    eval_density: float = 1.0
    """The ``--eval-density`` knob's numeric value: 0.0/1.0/2.0 for
    low/standard/high, or any value a caller composes directly.

    Threads into both `generators.evaluation.evaluation_cases` (more direct
    lookups, comparisons, and cross-period questions once the world actually
    has more to ask about — see that module's docstring) and this method's
    own `planning.artifact_intents` call (more fan-out documents to ask
    those questions of). ``1.0`` reproduces every build this scenario has
    ever produced, byte for byte; that is the default for exactly that
    reason, not because 1.0 is an otherwise meaningful point on the scale.
    """

    seasonality: Any = None
    """The trading year this business has (``worldloom.profiles``).

    ``None`` means the engine's own general-retail profile, which is what every
    close before this field existed used. A bank or an insurer wants ``flat``:
    a premium book that peaks at Christmas is not a subtle error, it is a
    different industry."""

    physics: Parameters = DEFAULT
    """The world physics this close is generated under (``worldloom.parameters``).

    Compared and hashed like any other field. It was briefly excluded from
    both, because a frozen dataclass hashes its comparable fields and a
    ``Parameters`` carries a Mapping — but excluding it makes two closes with
    *different physics* compare equal, which is worse than the problem. The fix
    belongs in ``Parameters``, which now defines its own ``__hash__``.
    """

    def run(self, world: World) -> World:
        """Return a new world with this episode's events, facts, and plans.

        The world passed in is not mutated.
        """
        from .generators import evaluation, finance, operations, planning

        if world.seed is None:
            raise ValueError("a scenario needs a seeded world; use RetailWorld(seed=...).build()")
        if world._minter is None:
            raise ValueError("this world was loaded from disk and cannot be advanced; build one from a seed")
        # Checked here rather than only where `finance.generate` needs it
        # below: `operations.generate` now also reads the archetype, for the
        # currency its one financial fact is stated in.
        if world._archetype is None:
            raise ValueError("this world has no archetype; build one with RetailWorld(...)")

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}")
        minter = world._minter
        roles = dict(world._roles)
        index = lore_index(world)

        # `probability` and not `chance`: the base rate is decided here, the
        # lore multiplier is applied here, and the coin is flipped two layers
        # down in `operations`. A parameter's accessor stops where its
        # authority stops.
        likelihood = self.physics.probability(
            "ops.incident.likelihood",
            scale=likelihood_multiplier(world, "data_quality_incident/inventory"),
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
            # A pack's episode-text overrides ride the recipe, which is what
            # lets a pack-built corpus rebuild them with no pack file on hand.
            text=(world._recipe.get("pack") or {}).get("episode_text") or None,
            money_unit=f"{world._archetype.currency}_{world._archetype.currency_unit}",
            physics=self.physics,
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
            trend_pct=self.trend_pct,
            # The archetype's own currency, not the generator's constant — a
            # pack's `currency`/`currency_unit` used to reach every other
            # surface (documents, narrative rendering) except the fact ledger
            # itself, which minted "AUD_thousands" regardless.
            money_unit=f"{world._archetype.currency}_{world._archetype.currency_unit}",
            seasonality=self.seasonality or _profiles.DEFAULT,
            physics=self.physics,
        )
        financial_facts = financials.headline

        # Built once, for both the planner (which categories does a high
        # `eval_density` argue below unit level) and the taxonomy's `Subjects`
        # below — the same grouping, so a category that got a commentary
        # document and a category the benchmark asks about are never computed
        # two different ways that could quietly disagree.
        categories_by_unit = {
            unit.id: [c.id for c in world.categories if c.business_unit_id == unit.id]
            for unit in world.business_units
        }

        # The lore-driven artifact density (status reporting swells during a
        # close the way LORE-0003 says it does) and `eval_density` are
        # deliberately independent knobs added to the same total: a pack's
        # in-world reason for more status reporting must not be silently
        # cancelled by someone asking for a small benchmark, and `--eval-
        # density low` must not depend on which lore a particular archetype
        # happens to carry to have any effect at all. `<= 0.5` is `low`'s
        # numeric value (0.0) with headroom for a caller-composed knob that
        # lands just above it; `low` is the one setting allowed to override
        # lore, because it is asking for the floor a retriever benchmark
        # needs to exist at all, not the floor a plausible company would
        # produce.
        artifact_density = 1.0 + density_adjustment(world, "finance/status_reports")
        if self.eval_density <= 0.5:
            artifact_density = 0.0

        # Accountability facts are those that pair a person with a measure and tolerance.
        # They exist if lore specified accountability constraints; no shipped lore does.
        accountability_facts = tuple(
            f for f in world.facts
            if f.kind == "org.accountability" and not f.is_superseded
        )

        intents = planning.artifact_intents(
            minter,
            episode=episode,
            roles=roles,
            financial_facts=financial_facts,
            period=self.period,
            density=artifact_density,
            workbook_facts=financials.facts,
            prior_intents=world._artifact_intents,
            actor_authored=self.actors is not None,
            categories_by_unit=categories_by_unit,
            eval_density=self.eval_density,
            accountability_facts=accountability_facts,
        )

        # The world has to carry this period's events, facts, and standing
        # documents before anyone can observe them — an actor woken by a
        # pipeline failure that is not yet in the world would see nothing.
        prior_intents = world._artifact_intents
        advanced = world.extend(
            events=episode.events,
            facts=(*episode.facts, *financials.facts),
            artifact_intents=intents,
            period=self.period,
        )
        actor_state: dict[str, tuple] = {}
        if self.actors is not None:
            from .actors.runtime import run_episode

            run = run_episode(
                advanced, self.actors, period=self.period, ledger=self.actor_ledger
            )
            advanced = run.world
            actor_state = {
                "observations": run.observations,
                "messages": run.messages,
                "tasks": run.tasks,
                "actor_ledger": run.entries,
                "ledger": run.generation_ledger,
            }
            # Evaluation runs against everything this period produced, actor
            # documents included. Generating cases from the deterministic plan
            # alone would silently drop every incident family the moment actors
            # were switched on — the facts are carried, just by a document the
            # planner did not write.
            intents = tuple(advanced._artifact_intents[len(prior_intents):])

        cases = evaluation.evaluation_cases(
            minter,
            episode=episode,
            facts=financials.facts,
            subjects=evaluation.Subjects(
                company_id=world.company.id,
                unit_ids=unit_ids,
                names=world.entity_names(),
                categories_by_unit=categories_by_unit,
                sites_by_unit={
                    unit.id: [s.id for s in world.sites if s.business_unit_id == unit.id]
                    for unit in world.business_units
                },
                # Only the people who belong to a unit. A group CFO belongs to
                # none, and a question about "their unit's variance" would have
                # no subject — the accountability family skips them rather than
                # picking one.
                unit_by_person={
                    person.id: person.business_unit_id
                    for person in world.people
                    if person.business_unit_id is not None
                },
            ),
            intents=intents,
            period=self.period,
            history=world._facts,
            prior_intents=prior_intents,
            density=self.eval_density,
            # A pack's evaluation-text overrides ride the recipe, the same
            # seam `episode_text` uses for the episode itself, so a
            # re-voiced benchmark rebuilds with no pack file on hand.
            text=(world._recipe.get("pack") or {}).get("evaluation_text") or None,
        )

        if self.actors is not None:
            from .actors import evaluation as actor_evaluation

            cases = (
                *cases,
                *actor_evaluation.cases(minter, world=advanced, entries=actor_state["actor_ledger"],
                                        observations=actor_state["observations"],
                                        tasks=actor_state["tasks"], period=self.period),
            )

        from .recipe import with_step

        return advanced.extend(
            evaluations=cases,
            period=self.period,
            # Recorded on the world rather than left to the caller's shell
            # history. A corpus that cannot say how it was made cannot be
            # rebuilt, and the actor handshake resumes an episode by rebuilding.
            recipe=with_step(
                world._recipe,
                "MonthEndClose",
                period=self.period,
                incident=self.include_operational_incident,
                comparatives=self.comparative_months,
                actors=self.actors is not None,
                # Recorded only away from its default, unlike its neighbours
                # above — this field did not exist before this knob did, and
                # every corpus already built or documented was built at 1.0.
                # Writing it unconditionally would put a new key in every
                # future recipe for a value that changes nothing, which is
                # exactly the byte-for-byte default-build diff the project's
                # own CI gate exists to catch. `rebuild` below defaults an
                # absent key to 1.0, so an old recipe and an explicit `1.0`
                # recipe replay identically either way.
                **({} if self.eval_density == 1.0 else {"eval_density": self.eval_density}),
                # Same conditional-write rule, same reason: a knob added after
                # corpora were built must not appear in the recipe of a build
                # that did not use it.
                **({} if self.trend_pct == 0.0 else {"trend_pct": self.trend_pct}),
            ),
            **actor_state,
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

        # The role table is a mixed index — people, but also systems, services,
        # access policies and cost centres — and `world.extend` merges the
        # `roles` returned below over it. So a hire into a key that is already
        # bound does not add a post, it *replaces* whatever that key meant, with
        # no event and no fact recording that it changed: the incumbent stays
        # employed and unreachable, or `roles["sys_erp"]` starts resolving to an
        # employee. Refused here rather than left to the validator because
        # nothing downstream can tell the difference between a rebind and a key
        # that always meant this. `timeline.review` states the same rule up
        # front, where a whole history can be refused before any of it runs;
        # this is the last line, for a caller running the scenario directly.
        if self.role_key in roles:
            raise ValueError(
                f"{self.role_key!r} is already bound in this world (to"
                f" {roles[self.role_key]}); hiring into it would silently"
                " replace what that key resolves to. Use a new role key, or"
                " run a Departure first if somebody is leaving the post."
            )

        # A pack's own name pools, if any — so a person hired mid-corpus
        # reads as the same locale as everyone the world minted at the
        # beginning, rather than falling back to the engine's defaults the
        # moment the roster grows. Same recipe-riding trick as `episode_text`.
        pack_pools = (world._recipe.get("pack") or {}).get("name_pools") or {}

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
            given=pack_pools.get("given") or None,
            family=pack_pools.get("family") or None,
        )
        new_person = change.people[0]

        from .recipe import with_step

        return world.extend(
            events=change.events,
            facts=change.facts,
            people=change.people,
            business_units=change.business_units,
            roles={**change.roles, self.role_key: new_person.id},
            period=self.period,
            recipe=with_step(
                world._recipe, "Hire", period=self.period, role_key=self.role_key,
                title=self.title, function=self.function, unit_key=self.unit_key,
            ),
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

        from .recipe import with_step

        return world.extend(
            events=change.events,
            facts=change.facts,
            people=change.people,
            business_units=change.business_units,
            roles=change.roles,
            artifact_intents=_personnel_notice(minter, change, _announcer(world, change), self.period),
            period=self.period,
            recipe=with_step(
                world._recipe, "Departure", period=self.period, role_key=self.role_key
            ),
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

        from .recipe import with_step

        return world.extend(
            events=change.events,
            facts=change.facts,
            people=change.people,
            business_units=change.business_units,
            roles=change.roles,
            artifact_intents=_personnel_notice(minter, change, _announcer(world, change), self.period),
            period=self.period,
            recipe=with_step(
                world._recipe, "Reorganisation", period=self.period,
                unit_key=self.unit_key, new_leader_role=self.new_leader_role,
            ),
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
