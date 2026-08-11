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
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from .generators.operations import business_days_after, period_end
from . import documents, profiles as _profiles
from .models import Authority, Lifecycle
from .parameters import DEFAULT, Parameters
from .recipe import locale_of
from .rng import Rng
from .roles import unit_role_key

if TYPE_CHECKING:  # pragma: no cover
    from .generators.operations import CloseEpisode
    from .generators.planning import EstateReading
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


def filings(world: World) -> dict[str, float]:
    """Every artifact type this world's lore asks for or refuses, and by how much.

    The same quantity ``density_adjustment`` reads, at the targets that name an
    *artifact type* rather than a reporting theme (``facets.FILING_PREFIX``).
    Summed across commitments for the same reason density is: two claims about
    one target are two things a company is, and the world is what they come to
    together. A founder-led listed company keeps its audit committee pack —
    nothing suppresses that target — and loses its minutes, because one claim
    aims at that target and nothing outweighs it.

    Read by ``generators.planning``, which supplies the *base* each type starts
    from: a summed adjustment of zero means "the lore said nothing", which for
    ``meeting_minutes`` means it is still filed and for ``sponsor_pack`` means
    it is not. That split belongs to the planner, because which documents a
    company files by default is a statement about the episode rather than about
    the lore.

    Lore order decides nothing — the result is read by key — but the iteration
    is over ordered collections regardless, so two processes agree on the float
    even where addition does not commute in the last bit.
    """
    from .facets import FILING_PREFIX

    out: dict[str, float] = {}
    for commitment in world.lore:
        for constraint in commitment.constrains:
            if constraint.kind.value != "artifact_density":
                continue
            if not constraint.target.startswith(FILING_PREFIX):
                continue
            artifact_type = constraint.target[len(FILING_PREFIX):]
            out[artifact_type] = out.get(artifact_type, 0.0) + (constraint.magnitude or 0.0)
    return out


def _estate_reading(world: World, episode: CloseEpisode) -> EstateReading | None:
    """What the technology landscape says about the paperwork this incident makes.

    Three integers, and no graph: ``generators.planning`` takes readings rather
    than the estate itself, for the same reason ``evaluation_cases`` takes a
    graph rather than the world — a plan that could reach into a `DiGraph`
    would sooner or later start deciding something on a field nobody meant it
    to see.

    The two anchors are derived from the episode's own facts rather than from
    role keys, exactly as ``generators/evaluation._EstateReading`` derives
    them: the failed feed is whatever ``ops.feed_status`` is about, and the
    system holding the unowned mapping table is whatever ``ops.
    mapping_table_owner`` is about. A composed or re-voiced estate moves those
    ids; it does not move what they mean. An anchor that is not in the graph at
    all — a vertical whose episode names no service, an estate that renamed
    everything — reads zero, so the filings it gates simply do not happen,
    which is the honest answer rather than a guess.

    ``None`` without an incident: every reading here is about an incident's
    reach, and a clean close has none.
    """
    if not episode.had_incident:
        return None

    from . import graphs
    from .generators.planning import EstateReading

    # Some callers reconstruct the narrow episode reading from its fact/key
    # record only (not the full generator result). Such a legacy record has no
    # finalised_at; its world also predates lifecycle windows, so the complete
    # graph is the exact historical answer.
    graph = graphs.dependency_graph(world, at=getattr(episode, "finalised_at", None))
    by_id = {fact.id: fact for fact in episode.facts}

    def reach(key: str) -> int:
        fact = by_id.get(episode.keys.get(key, ""))
        if fact is None or fact.subject not in graph:
            return 0
        return len(graphs.blast_radius(graph, fact.subject))

    return EstateReading(
        scale=graph.number_of_nodes(),
        incident_reach=reach("fact_feed_status"),
        unowned_reach=reach("fact_owner"),
    )


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

    conversations: bool = False
    """Produce the episode's knowledge layer beside its facts and artifacts.

    An event mints facts and makes artifacts necessary — *including people
    talking*. With this on, ``worldloom.conversation`` derives the third output:
    who was told what, by whom, and therefore who in the company knew each fact
    at each moment. It adds no facts, no events and no documents; it records the
    epistemics of the ones the episode already produced, and
    ``worldloom.asymmetry`` turns that record into evaluation cases nothing else
    in the corpus can pose.

    Off by default, and off is byte-for-byte what every corpus already built is:
    nothing runs, and ``World.export`` writes the two files only when they have
    rows. Refused together with ``actors``, which produces the same two records
    itself and from richer input — two producers for one ledger is two accounts
    of who knew what.
    """

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

    storyline: str = "hierarchy_mapping"
    """Which incident storyline this close's failure tells
    (``operations.STORYLINES``).

    Surface only: the causal chain, its fact ids, and its machine values are
    identical under every storyline, because a storyline is applied through
    the same episode-text seam a pack re-voices. The default is the storyline
    this engine always told, so a close that never names one is byte-identical
    to every close built before the library existed. The library exists
    because a 24-period build measured 24 copies of one incident — the same
    confirmed cause, monthly — which no company's operational history looks
    like."""

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
        if self.conversations and self.actors is not None:
            # Both write `observations` and `messages`. Refused rather than
            # merged: two producers appending to one knowledge ledger would put
            # two learned_at values on one (person, fact) pair, and every
            # asymmetry answer derived from it would depend on which producer
            # ran second.
            raise ValueError(
                "conversations and actors both produce this episode's knowledge"
                " ledger; an actor episode already derives its own"
            )

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
            # The corpus's own working week. `operations.generate` has accepted
            # a calendar since locales landed and no caller passed one, so the
            # working week was carried and inert: a Gulf company closed on
            # Monday-to-Friday arithmetic and its due date fell on a Friday it
            # does not work. Read off the recipe rather than the world because
            # that is where the jurisdiction is recorded, and `locale_of`
            # answers `locales.DEFAULT` for a corpus that names none — the same
            # object `operations.CALENDAR` already was, so every existing
            # corpus is the bytes it was.
            calendar=locale_of(world.recipe),
            lore_by_target=index,
            incident_likelihood=likelihood,
            force_incident=self.include_operational_incident,
            # Only earlier closes that told the *same* storyline count as
            # recurrence: each storyline's recurrence text names its own
            # artefact ("the same mapping table", "the same rate table"), and
            # citing a prior period whose confirmed cause was a different
            # failure would be the corpus contradicting itself. Read off the
            # recipe rather than the facts because the recipe is where the
            # storyline is recorded; a step that predates the field is the
            # classic storyline by definition. For a world whose steps never
            # name one, every period matches — the exact tuple this always was.
            prior_incident_periods=tuple(
                fact.period
                for fact in world.facts.where(kind="ops.incident_opened")
                if fact.period and fact.period in {
                    step["period"]
                    for step in world._recipe.get("steps", ())
                    if step.get("scenario") == "MonthEndClose"
                    and step.get("storyline", "hierarchy_mapping") == self.storyline
                }
            ),
            # A pack's episode-text overrides ride the recipe, which is what
            # lets a pack-built corpus rebuild them with no pack file on hand.
            # The storyline overlay sits *under* the pack's: a pack that
            # re-voices an incident key authored those words for its own
            # world, and a rotation knob must not argue with an author. The
            # classic storyline's overlay is empty, so the merged dict — and
            # the `or None` — reproduce the exact value this call always
            # passed.
            text={
                **operations.storyline_text(self.storyline),
                **((world._recipe.get("pack") or {}).get("episode_text") or {}),
            } or None,
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
            sites=tuple(world.sites_at(episode.finalised_at)),
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
            for unit in world.business_units_at(episode.finalised_at)
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
            # What kind of company this is, in the three shapes the plan can
            # read it. Each is a *reading* rather than the thing itself: the
            # planner takes no world, and handing it one so it could compute
            # these would give it the whole ledger to reach into.
            filings=filings(world),
            estate=_estate_reading(world, episode),
            # The org builder's dated lore witnesses, so the plan can put the
            # company's own history in a document — see the timeline block at
            # the end of `planning.artifact_intents`.
            milestones=tuple(f for f in world._facts if f.kind == "lore.milestone"),
            # Counts, not collections — the same discipline as `filings` and
            # `estate` above: the plan gates on how much of each there is, and
            # only the compiled builders read the rows themselves.
            estate_services=len(list(world.services)),
            # `masterdata` is None on any world that never asked for it, which
            # is every world the flagless CLI builds.
            masterdata_rows=(
                len(world.masterdata.vendors) + len(world.masterdata.customers)
                + len(world.masterdata.skus)
            ) if world.masterdata is not None else 0,
            # The trading year, at this period. `self.seasonality or DEFAULT`
            # is the same fallback `finance.generate` is given above, and it
            # has to be: the plan must judge the month against the same year
            # the figures were drawn under, or a corpus would review a peak its
            # own budget never had.
            seasonal_index=(self.seasonality or _profiles.DEFAULT).of(self.period),
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

        conversation = None
        if self.conversations:
            from .conversation import derive as derive_conversation

            # Derived from the whole world rather than from this period's slice:
            # who knew what is cumulative, and a controller who learned the
            # mapping table was unowned in an earlier period still knows it. The
            # observation ledger is keyed on (observer, fact) and appended, so a
            # second period adds only what is new.
            conversation = derive_conversation(advanced, minter=minter, roles=roles)
            actor_state = {
                "observations": conversation.observations,
                "messages": conversation.messages,
            }

        from . import graphs
        # Imported here rather than at module scope for the reason `graphs` is:
        # `evaluate` pulls in the render layer through its index, and a
        # scenario is imported by everything that builds anything.
        from .evaluate import phrasing

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
                    unit.id: [s.id for s in world.sites_at(episode.finalised_at)
                              if s.business_unit_id == unit.id]
                    for unit in world.business_units_at(episode.finalised_at)
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
            # What the corpus already asks, so the per-episode families cannot
            # re-mint a standing question verbatim each period. Six episodes
            # used to mean six copies of every policy and abstention case.
            prior_cases=world._evaluations,
            density=self.eval_density,
            # The estate, as the graph it has always been. The taxonomy owns
            # what it asks; it cannot own what it can *see*, and until this
            # line it could see names and figures but no structure — so a
            # world running 101 services with 18 chokepoints was asked exactly
            # the questions a nine-service prop list was. Passed as a graph
            # rather than as the world so a family here cannot quietly start
            # reading some other field of it.
            estate=graphs.dependency_graph(world, at=episode.finalised_at),
            # A pack's evaluation-text overrides ride the recipe, the same
            # seam `episode_text` uses for the episode itself, so a
            # re-voiced benchmark rebuilds with no pack file on hand.
            #
            # A world that speaks a dealt vocabulary re-voices the benchmark
            # too, through the same seam and *underneath* the pack: the
            # taxonomy's phrasing is the same sentence in every world, so a
            # mosaic of five companies asked thirty-one of its questions
            # byte-identically five times. `evaluate.phrasing` deals each
            # vocabulary a wording (`overrides` returns None for every world
            # that speaks none, which is every stock build, so this line is a
            # no-op wherever it was one before). Pack overrides win, because an
            # author who re-voiced a question said what they meant and a deal
            # is a default.
            # The storyline's benchmark overlay sits *above* the dealt
            # phrasing and *below* the pack: seven of the engine's answer
            # templates state the classic failure in words, and an answer
            # asserting a mapping table failed in a month whose confirmed
            # cause was an expired credential grades retrievers against a
            # lie — content correctness outranks vocabulary variety. The
            # classic overlay is empty, so every stock build's merge is the
            # exact dict it always was.
            text={**(phrasing.overrides(world) or {}),
                  **operations.storyline_eval_text(self.storyline),
                  **((world._recipe.get("pack") or {}).get("evaluation_text") or {})} or None,
        )

        if self.actors is not None:
            from .actors import evaluation as actor_evaluation

            cases = (
                *cases,
                *actor_evaluation.cases(minter, world=advanced, entries=actor_state["actor_ledger"],
                                        observations=actor_state["observations"],
                                        tasks=actor_state["tasks"], period=self.period),
            )

        if conversation is not None and conversation.observations:
            from .asymmetry import cases as asymmetry_cases

            # Generated against a world that already carries the ledger, because
            # every case here has to be checkable by the corpus a reader gets:
            # `validate` re-derives nothing, it reads `observations.jsonl`.
            enriched = advanced.extend(
                observations=conversation.observations,
                messages=conversation.messages,
            )
            cases = (
                *cases,
                *asymmetry_cases(
                    minter,
                    world=enriched,
                    # The whole ledger, so "who already held it" names everyone
                    # who did — including people who learned it in an earlier
                    # period — while `eligible` keeps the *questions* about what
                    # this close newly put in front of somebody.
                    observations=tuple(enriched.observations),
                    messages=tuple(enriched.messages),
                    period=self.period,
                    eligible=frozenset(o.fact_id for o in conversation.observations),
                ),
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
                # And again. `conversations` is the newest of the three and the
                # cheapest to get wrong: writing `false` unconditionally would
                # move the recipe of every default build, which is precisely the
                # byte-for-byte diff CI runs on every push.
                **({} if not self.conversations else {"conversations": True}),
                # Same conditional-write rule. The default name is the story
                # this engine always told, so a close that never chose one
                # leaves the recipe exactly as it was — and the recurrence
                # filter above, which reads this key back, sees every prior
                # period, exactly as it always did.
                **({} if self.storyline == "hierarchy_mapping"
                   else {"storyline": self.storyline}),
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


#: `personnel_notice` is minted below and declared by nobody, so `standing`
#: falls through and a succession announcement is an unreviewed draft that
#: nothing chose — `documents.declared_types`' own docstring states the gap and
#: says the fix is a registration from whichever module owns the scenario. This
#: is not that fix; deciding a succession note's authority is a modelling
#: decision of its own. What it is, is the *name* being spoken for, and that
#: became load-bearing when artifact types became authorable: the compiler's
#: tables are process-global, so a pack declaring this key would set the
#: authority of a document in some other world built by the same process, and
#: `register_artifact_types` cannot refuse it because nothing registered a value
#: for it to disagree with.
documents.reserve_artifact_types("personnel_notice")
documents.register_artifact_types(
    standing={"estate_change_notice": (Authority.WORKING_DOCUMENT, Lifecycle.PUBLISHED)},
    lags={"estate_change_notice": timedelta(hours=1)},
    outlines={
        "estate_change_notice": (
            documents.SectionPlan(
                "Operating estate",
                ("estate.",),
                "any",
                "State the new structural counts and signed movements. Explain only"
                " what changed; do not invent a rationale beyond the recorded event.",
            ),
        ),
    },
)


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
class WorkforceChange:
    """An aggregate workforce target effective after *period* closes.

    The company row carries the current total; the two facts preserve the
    snapshot and signed delta that produced it.  This deliberately does not
    mint or retire one ``Employee`` per head: named employees are the bounded
    decision-making graph, while payroll-scale population remains structured
    aggregate data.  That separation is what lets a million-person world stay
    buildable without making workforce size inert.
    """

    period: str
    headcount: int

    def run(self, world: World) -> World:
        from .models import ArtifactIntent, Authority, CanonicalFact, EnterpriseEvent, Quantity
        from .recipe import with_step

        if world._minter is None:
            raise ValueError(
                "this world was loaded from disk and cannot be advanced; build one from a seed"
            )

        at = _period_boundary(self.period)
        modelled = len(world.org_at(at))
        if self.headcount < modelled:
            raise ValueError(
                f"headcount {self.headcount:,} is smaller than the {modelled:,}"
                " named employees active at the workforce boundary"
            )

        previous = world.company.employees_total
        if self.headcount == previous:
            raise ValueError(
                f"headcount is already {self.headcount:,}; a workforce episode"
                " that changes nothing would mint a false audit trail"
            )

        delta = self.headcount - previous
        direction = "expanded" if delta > 0 else "reduced"
        author_id = world._roles.get("head_of_people", world._roles["ceo"])
        event = EnterpriseEvent(
            id=world._minter.next("EV"),
            kind=f"workforce_{direction}",
            occurred_at=at,
            summary=(
                f"The workforce {direction} from {previous:,} to"
                f" {self.headcount:,} employees."
            ),
            actors=[author_id],
        )
        facts = (
            CanonicalFact(
                id=world._minter.next("FACT"),
                kind="org.headcount",
                subject=world.company.id,
                period=self.period,
                value=Quantity(amount=float(self.headcount), unit="employees"),
                valid_from=at,
                authority=Authority.SYSTEM_OF_RECORD,
                event_id=event.id,
            ),
            CanonicalFact(
                id=world._minter.next("FACT"),
                kind="org.headcount.delta",
                subject=world.company.id,
                period=self.period,
                value=Quantity(amount=float(delta), unit="employees"),
                valid_from=at,
                authority=Authority.SYSTEM_OF_RECORD,
                event_id=event.id,
            ),
        )
        notice = ArtifactIntent(
            id=world._minter.next("ART"),
            artifact_type="personnel_notice",
            domain="people",
            audience="all_staff",
            author_id=author_id,
            triggered_by=[event.id],
            required_fact_ids=[fact.id for fact in facts],
            size_profile="small",
            rationale=(
                "An aggregate workforce movement is announced with both the"
                " new total and the signed change, so organisation scale is"
                " visible in the document corpus rather than only in metadata."
            ),
        )

        return world.extend(
            company=world.company.model_copy(
                update={"employees_total": self.headcount}
            ),
            events=(event,),
            facts=facts,
            artifact_intents=(notice,),
            period=self.period,
            recipe=with_step(
                world._recipe,
                "WorkforceChange",
                period=self.period,
                headcount=self.headcount,
            ),
        )


@dataclass(frozen=True)
class StructuralChange:
    """Exact active estate sizes effective after *period* closes.

    Entity rows are never deleted. Growth appends deterministic entities and
    contraction closes their validity windows, so an artifact written before a
    closure still resolves the unit, site, system or service it cited. Targets
    are exact; a target below the dependency- or ownership-safe floor is refused
    instead of silently producing a different size.
    """

    period: str
    business_units: int
    sites: int
    systems: int
    services: int

    def run(self, world: World) -> World:
        from .models import (
            ArtifactIntent,
            Authority,
            BusinessUnit,
            CanonicalFact,
            EnterpriseEvent,
            Quantity,
            Service,
            Site,
            System,
        )
        from .recipe import with_step

        if world._minter is None:
            raise ValueError(
                "this world was loaded from disk and cannot be advanced; build one from a seed"
            )
        requested = {
            "business_units": self.business_units,
            "sites": self.sites,
            "systems": self.systems,
            "services": self.services,
        }
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
               for value in requested.values()):
            raise ValueError(f"estate targets must be non-negative integers; got {requested}")
        if self.services and not self.systems:
            raise ValueError("a non-empty service estate needs at least one active system")

        at = _period_boundary(self.period)
        active_units = list(world.business_units_at(at))
        active_sites = list(world.sites_at(at))
        active_systems = list(world.systems_at(at))
        active_services = list(world.services_at(at))
        previous = {
            "business_units": len(active_units),
            "sites": len(active_sites),
            "systems": len(active_systems),
            "services": len(active_services),
        }
        if requested == previous:
            raise ValueError(
                "estate is already at the requested size; a structural episode"
                " that changes nothing would mint a false audit trail"
            )

        minter = world._minter
        role_bound = frozenset(world._roles.values())
        changed_units: list[BusinessUnit] = []
        changed_sites: list[Site] = []
        changed_systems: list[System] = []
        changed_services: list[Service] = []

        # Units grow before sites so the same episode can open locations in a
        # newly formed unit. They carry no reporting share or category: those
        # are separate financial-model decisions, never inferred from a count.
        while len(active_units) < self.business_units:
            sequence = len(world._business_units) + len(changed_units) + 1
            unit = BusinessUnit(
                id=minter.next("BU"),
                name=f"Enterprise Unit {sequence}",
                company_id=world.company.id,
                leader_id=world._roles["ceo"],
                kind="support",
                formed=at,
            )
            active_units.append(unit)
            changed_units.append(unit)

        if self.sites > 0 and not active_units:
            raise ValueError("an active site needs at least one active business unit")
        while len(active_sites) < self.sites:
            sequence = len(world._sites) + len(changed_sites) + 1
            unit = active_units[(sequence - 1) % len(active_units)]
            site = Site(
                id=minter.next("SITE"),
                name=f"Enterprise Site {sequence}",
                business_unit_id=unit.id,
                format="office",
                region=world.company.headquarters,
                opened=str(at.year),
                activated_at=at,
                revenue_weight=0.0,
            )
            active_sites.append(site)
            changed_sites.append(site)

        while len(active_systems) < self.systems:
            sequence = len(world._systems) + len(changed_systems) + 1
            system = System(
                id=minter.next("SYS"),
                name=f"Enterprise Platform {sequence}",
                purpose=f"Shared enterprise capability {sequence}",
                owner_id=world._roles.get("cio", world._roles["ceo"]),
                is_system_of_record_for=[],
                introduced=at,
            )
            active_systems.append(system)
            changed_systems.append(system)

        while len(active_services) < self.services:
            sequence = len(world._services) + len(changed_services) + 1
            system = active_systems[(sequence - 1) % len(active_systems)]
            dependencies = [active_services[-1].id] if active_services else []
            service = Service(
                id=minter.next("SVC"),
                name=f"Enterprise Service {sequence}",
                purpose=f"Operates shared enterprise capability {sequence}",
                owner_id=world._roles.get("cio", world._roles["ceo"]),
                system_id=system.id,
                criticality_tier=3,
                depends_on=dependencies,
                introduced=at,
            )
            active_services.append(service)
            changed_services.append(service)

        # Retire leaf services first. A role-bound service and a service another
        # active service depends on are both part of the exact safe floor.
        while len(active_services) > self.services:
            depended_on = {target for service in active_services for target in service.depends_on}
            candidate = next(
                (service for service in reversed(active_services)
                 if service.id not in role_bound and service.id not in depended_on),
                None,
            )
            if candidate is None:
                raise ValueError(
                    f"service target {self.services} is below the safe floor"
                    f" {len(active_services)} (role-bound or depended-on services remain)"
                )
            active_services.remove(candidate)
            changed_services.append(candidate.model_copy(update={"retired": at}))

        while len(active_systems) > self.systems:
            used = {
                service.system_id for service in active_services
            } | {
                target for service in active_services for target in service.depends_on
            }
            candidate = next(
                (system for system in reversed(active_systems)
                 if system.id not in role_bound and system.id not in used),
                None,
            )
            if candidate is None:
                raise ValueError(
                    f"system target {self.systems} is below the safe floor"
                    f" {len(active_systems)} (role-bound or live-service systems remain)"
                )
            active_systems.remove(candidate)
            changed_systems.append(candidate.model_copy(update={"retired": at}))

        while len(active_sites) > self.sites:
            candidate = next(
                (site for site in reversed(active_sites) if site.id not in role_bound), None
            )
            if candidate is None:
                raise ValueError(
                    f"site target {self.sites} is below the role-bound floor {len(active_sites)}"
                )
            active_sites.remove(candidate)
            changed_sites.append(candidate.model_copy(update={"closed_at": at}))

        occupied_units = {
            person.business_unit_id for person in world.org_at(at)
            if person.business_unit_id is not None
        } | {
            category.business_unit_id for category in world.categories
        } | {
            site.business_unit_id for site in active_sites
        }
        while len(active_units) > self.business_units:
            candidate = next(
                (unit for unit in reversed(active_units)
                 if unit.id not in role_bound and unit.id not in occupied_units),
                None,
            )
            if candidate is None:
                raise ValueError(
                    f"business-unit target {self.business_units} is below the safe floor"
                    f" {len(active_units)} (people, categories, sites or roles remain)"
                )
            active_units.remove(candidate)
            changed_units.append(candidate.model_copy(update={"dissolved": at}))

        actual = {
            "business_units": len(active_units),
            "sites": len(active_sites),
            "systems": len(active_systems),
            "services": len(active_services),
        }
        if actual != requested:  # defensive: every loop above promises exactness
            raise AssertionError(f"estate change resolved {actual}, expected {requested}")

        author_id = world._roles.get("cio", world._roles["ceo"])
        event = EnterpriseEvent(
            id=minter.next("EV"),
            kind="structural_estate_changed",
            occurred_at=at,
            summary=(
                "The operating estate changed to"
                f" {self.business_units} business units, {self.sites} sites,"
                f" {self.systems} systems and {self.services} services."
            ),
            actors=[author_id],
        )
        facts: list[CanonicalFact] = []
        for key, unit in (
            ("business_units", "business_units"),
            ("sites", "sites"),
            ("systems", "systems"),
            ("services", "services"),
        ):
            for suffix, amount in (("count", actual[key]), ("delta", actual[key] - previous[key])):
                facts.append(CanonicalFact(
                    id=minter.next("FACT"),
                    kind=f"estate.{key}.{suffix}",
                    subject=world.company.id,
                    period=self.period,
                    value=Quantity(amount=float(amount), unit=unit),
                    valid_from=at,
                    authority=Authority.SYSTEM_OF_RECORD,
                    event_id=event.id,
                ))
        notice = ArtifactIntent(
            id=minter.next("ART"),
            artifact_type="estate_change_notice",
            domain="operations",
            audience="all_staff",
            author_id=author_id,
            triggered_by=[event.id],
            required_fact_ids=[fact.id for fact in facts],
            size_profile="small",
            rationale=(
                "A structural movement is published with exact counts and deltas,"
                " making estate scale visible in the document corpus and audit trail."
            ),
        )
        return world.extend(
            business_units=tuple(changed_units),
            sites=tuple(changed_sites),
            systems=tuple(changed_systems),
            services=tuple(changed_services),
            events=(event,),
            facts=tuple(facts),
            artifact_intents=(notice,),
            period=self.period,
            recipe=with_step(world._recipe, "StructuralChange", period=self.period, **requested),
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

        active = len(world.org_at(at))
        if active >= world.company.employees_total:
            raise ValueError(
                f"cannot hire into a workforce of {world.company.employees_total:,}:"
                f" all {active:,} employee places are already occupied by named"
                " people. Increase aggregate headcount or depart somebody first."
            )

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
            manager_id=roles[unit_role_key(self.unit_key, "_md")],
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
            # Refused, never skipped. A scenario that quietly did nothing would
            # report success while the corpus lost a succession its recipe says
            # happened — and `--replay` would then rebuild a different history
            # than the one that shipped.
            #
            # `timeline` budgets departures per function so a *sampled* history
            # does not schedule more than the organisation can serve, which is
            # why this fires far later than it used to. It can still fire,
            # because that budget is deliberately approximate: a successor drawn
            # from direct reports may come from another function, and
            # `Reorganisation` and `Hire` move people between functions after
            # the budget was struck. The remedy is in the message rather than in
            # a guess here, because only the caller knows which they want.
            #
            # The message deliberately does *not* suggest a larger *stated*
            # workforce. ``--employees`` now controls aggregate headcount, but
            # aggregate employees are not invented candidates for a named role;
            # succession capacity comes from the authored/modelled role table.
            # Advice that conflates those two populations would still cost a
            # failed build to discover.
            remaining = sorted(
                {person.function for person in employed if person.id != leaver.id}
            )
            raise ValueError(
                f"no eligible successor for {leaver.id} ({leaver.title}): no direct"
                f" reports and nobody else in {leaver.function} is employed at"
                f" {at.isoformat()}. {len(employed)} people remain, across"
                f" {', '.join(remaining) or 'no other function'}. Shorten"
                " `--periods`, or use `--timeline quiet`, which schedules no"
                " departures and builds 96 periods clean."
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
            role_key=unit_role_key(self.unit_key, "_md"),
            units=(unit,),
            at=at,
            period=self.period,
            # Access follows the post. A divisional MD is named on the finance
            # policy so they can read — and sign — their own division's close
            # pack, and a handover that moved the title without moving the
            # access left the corpus recording a signature from somebody it
            # also recorded as unable to open the document.
            policies=world._access_policies,
        )

        from .recipe import with_step

        return world.extend(
            events=change.events,
            facts=change.facts,
            people=change.people,
            business_units=change.business_units,
            roles=change.roles,
            access_policies=change.access_policies,
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
    "WorkforceChange",
    "StructuralChange",
    "lore_index",
    "likelihood_multiplier",
    "density_adjustment",
    "filings",
]
