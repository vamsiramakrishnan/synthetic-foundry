"""A corpus's history, as a value.

Until now a Worldloom history was a *count*. ``worldloom build --periods 6``
runs six ``MonthEndClose`` scenarios one month apart, and that is the whole
vocabulary: the organisation that signs month six is the organisation that
signed month one, every close is drawn from the same distribution, and the
three org-change scenarios ``scenarios.py`` has always defined — ``Hire``,
``Departure``, ``Reorganisation`` — are unreachable from any build because
nothing schedules them. Six identical months with the dates changed is not an
enterprise history. It is one month photocopied.

This module makes the history the thing a caller holds:

    from worldloom import RetailWorld, timeline

    world = RetailWorld(seed=8128).build()
    history = timeline.sample(
        roster=timeline.Roster.of(world),
        start="2026-01", periods=6, seed=8128,
        density=timeline.STEADY,
    )
    world = history.run(world)

A ``Timeline`` is an ordered tuple of scenario instances and nothing else. It
composes (``then``, ``+``), it is iterable (so ``sdk.Built.run(*history)`` takes
one without this module and that one knowing about each other — that path is the
raw escape hatch and runs no review, unlike ``Timeline.run``), and it carries no
world state — which is what lets the same history be sampled once and run
against a field of worlds.

**Why this is not a wrapper around the loop.** Three things become expressible
that were not:

* A controller who departs in period 2 means periods 3-6 are signed by their
  successor, and the temporal check ``author_already_departed`` becomes a real
  question about the corpus rather than a hypothetical about the validator. The
  timing that makes it work is ``scenarios._period_boundary``'s and is not
  re-litigated here — a change belonging to period P lands *after* P's close,
  so the leaver signs their own final close. What this module adds is the
  refusal that follows from it: a change for P placed *before* P's episode in
  the list would have the successor sign a month they did not run.
* An incident in period 3 and not period 4 makes "which month went wrong"
  answerable from the corpus. A build that forces ``--incident`` forces it on
  every period, which answers the question by making it vacuous.
* A reorganisation moves who reports to whom *within one corpus*, which is the
  single most enterprise-like thing a synthetic history can carry and which no
  Worldloom corpus has ever contained.

**What is deliberately not here.** No new recipe verb, and no change to
``recipe.STEPS``. Every scenario a timeline can hold already records itself
through its own ``with_step`` call, so a sampled history rebuilds from the
corpus it produced with nothing added — and a timeline that needed its own
recipe entry would be a second, redundant account of a history the steps
already describe. Sampling is reproducible from ``(seed, roster, density)``,
so the seed in the recipe is the sample.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .dispersion import farthest_first, halton
from .rng import Rng
from .roles import Rejection, unit_role_key

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


class TimelineError(Exception):
    """A history that cannot be run, with every reason it cannot.

    All of them at once, each naming its rule — the posture ``roles.review``
    and ``validate`` already take, and for the same reason: a caller who fixes
    one refusal and immediately hits the next has been made to discover their
    history one defect at a time.
    """

    def __init__(self, violations: Sequence[Rejection]) -> None:
        self.violations = tuple(violations)
        super().__init__(
            f"this history cannot be run — {len(self.violations)} problem(s):\n"
            + "\n".join(f"  {violation}" for violation in self.violations)
        )


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------


def _is_period(period: str) -> bool:
    year, _, month = period.partition("-")
    return (
        len(year) == 4 and year.isdigit()
        and len(month) == 2 and month.isdigit() and 1 <= int(month) <= 12
    )


def period_after(period: str, steps: int = 1, *, months: int = 1) -> str:
    """*period* advanced by *steps* steps of *months* months.

    The same arithmetic as ``cli._step_period`` and ``sdk._step``, and
    deliberately a third copy rather than an import: this module must be
    importable without pulling in Typer (``cli``) or the blueprint layer
    (``sdk``, which already imports scenarios and domains), and six lines of
    integer division are a smaller cost than either dependency. All three are
    total-month arithmetic on the string with no clock anywhere near them,
    which is what keeps a replayed build byte-identical.
    """
    if not _is_period(period):
        raise ValueError(f"a period is YYYY-MM; got {period!r}")
    year, month = (int(part) for part in period.split("-"))
    year, month = divmod(year * 12 + (month - 1) + steps * months, 12)
    return f"{year:04d}-{month + 1:02d}"


def periods_from(start: str, count: int, *, months: int = 1) -> tuple[str, ...]:
    """*count* consecutive periods beginning at *start*."""
    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")
    return tuple(period_after(start, index, months=months) for index in range(count))


# ---------------------------------------------------------------------------
# What exists to schedule against
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Roster:
    """The organisation a history is scheduled against, as facts about keys.

    Not a world. A timeline is sampled and checked against *what role and unit
    keys exist*, which is all any of the org verbs actually consult, and taking
    the whole world here would mean a history could not be composed before the
    world it runs on has been built — which is exactly the arrangement the SDK
    is for (one history, a field of worlds).
    """

    engine: str
    """The engine whose spine applies (``roles.SPINE``). Empty when the world's
    archetype belongs to no registered domain — a pack on an unregistered base
    — in which case the load-bearing-role rule below cannot be checked and is
    skipped rather than guessed at."""

    role_keys: frozenset[str]
    """Keys that a *person* holds. A world's role table is a mixed index — it
    binds ``sys_erp`` to a system, ``svc_checkout`` to a service, ``policy_all``
    to an access policy and ``cc_finance`` to a cost centre alongside the
    fourteen keys that name employees — and only the person rows are things a
    history can hire into, depart, or promote. Filtering by "does this resolve
    to somebody in ``world.people``" rather than by a name prefix is
    deliberate: the prefixes are an organisation generator's convention and a
    pack is free not to share it, whereas what the key resolves to is what
    ``Departure`` actually looks at."""

    unit_keys: tuple[str, ...]

    bound_keys: frozenset[str] = frozenset()
    """Every key the table binds, people and everything else. This, not
    ``role_keys``, is what a new post must not collide with — ``Hire`` writes
    straight into the table, so hiring somebody as ``sys_erp`` would replace the
    ERP system's id with a person id and every later ``roles["sys_erp"]`` would
    resolve to an employee."""

    unit_by_role: Mapping[str, str | None] = field(default_factory=dict)
    """Which business unit each role sits in, by unit key. ``None`` for the
    group roles that belong to no unit — a group CFO is nobody's divisional
    anything, and ``personnel.promote`` treats exactly that case as free to
    lead any unit."""

    succeedable: frozenset[str] = frozenset()
    """Roles that had somebody able to take over, at the moment this roster was
    taken. ``Departure`` picks a successor from direct reports or same-function
    peers and raises when there are none; this is that predicate, precomputed,
    so the sampler can avoid scheduling a departure the engine will refuse."""

    function_by_role: Mapping[str, str] = field(default_factory=dict)
    """Which function each role's holder sits in.

    Carried because ``succeedable`` is a *per-role* predicate and the constraint
    it stands in for is *per-function*: Finance holding three people makes all
    three of its roles succeedable, and departing all three is impossible,
    because the third leaver has no peer left to hand to. A 45-period history
    hit exactly that and died mid-build with "nobody else in Finance is
    employed" — 40 periods after the schedule that doomed it was chosen."""

    function_size: Mapping[str, int] = field(default_factory=dict)
    """Employed headcount per function when this roster was taken. With
    ``function_by_role``, what lets the sampler bound a family it can exhaust."""

    employees_total: int = 0
    """The company's stated workforce, including people not materialised."""

    modelled_headcount: int = 0
    """Named employees active when this roster was taken."""

    def __hash__(self) -> int:
        """Hashable despite the Mapping, the same fix ``Parameters`` made and
        for the same reason: a frozen dataclass wrapping a Mapping gets a
        generated ``__hash__`` that raises, and a value an SDK might key a
        cache on should not be the one thing in the module that cannot."""
        return hash((self.engine, self.role_keys, self.unit_keys, self.bound_keys,
                     tuple(sorted(self.unit_by_role.items())), self.succeedable,
                     tuple(sorted(self.function_by_role.items())),
                     tuple(sorted(self.function_size.items())),
                     self.employees_total, self.modelled_headcount))

    @classmethod
    def of(cls, world: World) -> Roster:
        """The roster a built world presents."""
        from . import domains

        bindings = dict(world._roles)
        unit_keys = tuple(sorted(
            key.removeprefix("unit_") for key in bindings if key.startswith("unit_")
        ))
        unit_of_id = {bindings[f"unit_{key}"]: key for key in unit_keys}

        # Successor eligibility, mirroring `Departure.run`: a direct report
        # first, else anyone else in the same function. Counted over people who
        # have not left rather than over `org_at(some moment)`, because the
        # moment a departure lands is decided by the period it is scheduled in
        # and this roster is taken before any of that is known.
        reports: dict[str, int] = {}
        by_function: dict[str, int] = {}
        for person in world.people:
            if person.left is not None:
                continue
            if person.manager_id is not None:
                reports[person.manager_id] = reports.get(person.manager_id, 0) + 1
            by_function[person.function] = by_function.get(person.function, 0) + 1

        role_keys: set[str] = set()
        unit_by_role: dict[str, str | None] = {}
        function_by_role: dict[str, str] = {}
        succeedable: set[str] = set()
        for key in sorted(bindings):
            if key.startswith("unit_"):
                continue
            person = world.people.get(bindings[key])
            if person is None:
                continue
            role_keys.add(key)
            unit_by_role[key] = unit_of_id.get(person.business_unit_id)
            function_by_role[key] = person.function
            if person.left is None and (
                reports.get(person.id, 0) > 0 or by_function.get(person.function, 0) > 1
            ):
                succeedable.add(key)

        archetype = world._archetype
        domain = None if archetype is None else domains.for_archetype(archetype.key)
        return cls(
            engine="" if domain is None else domain.name,
            role_keys=frozenset(role_keys),
            unit_keys=unit_keys,
            bound_keys=frozenset(bindings),
            unit_by_role=unit_by_role,
            succeedable=frozenset(succeedable),
            function_by_role=function_by_role,
            function_size=dict(by_function),
            employees_total=world.company.employees_total,
            modelled_headcount=sum(1 for person in world.people if person.left is None),
        )

    def reserved(self) -> frozenset[str]:
        """Role keys the engine resolves by name — spine plus per-unit roles.

        Straight from ``roles.required``, never a copy of it: that list is
        computed against a scan of the package (see ``roles``'s docstring and
        ``tests/test_roles.py``), so a lookup added anywhere starts constraining
        histories here without anyone remembering to update this module.
        """
        from . import roles as role_table

        if self.engine not in role_table.SPINE:
            return frozenset()
        return frozenset(role_table.required(self.engine, self.unit_keys))

    def roles_in(self, unit_key: str) -> tuple[str, ...]:
        """Every role key sitting in *unit_key*, sorted."""
        return tuple(sorted(
            key for key, unit in self.unit_by_role.items() if unit == unit_key
        ))


# ---------------------------------------------------------------------------
# The history itself
# ---------------------------------------------------------------------------

#: Scenario class names this module knows the shape of. A closed vocabulary for
#: the same reason ``recipe.STEPS`` is one: each of these has a bespoke set of
#: arguments with rules of its own, and a step whose name is not here is treated
#: as an episode — which is right for a registered vertical's own scenario, all
#: of which take nothing but a period and are checked for exactly that.
ORG_VERBS: frozenset[str] = frozenset({
    "Hire", "Departure", "Reorganisation", "WorkforceChange", "StructuralChange",
})


@dataclass(frozen=True)
class Timeline:
    """An ordered history: scenario instances, and nothing derived from them.

    Order is the whole content, the same claim ``recipe.with_step`` makes about
    a recipe's steps: three closes with a departure between them are a
    different corpus from three closes and then a departure.
    """

    steps: tuple[Any, ...] = ()

    def __iter__(self) -> Iterator[Any]:
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    def __bool__(self) -> bool:
        return bool(self.steps)

    def __add__(self, other: Timeline) -> Timeline:
        if not isinstance(other, Timeline):
            return NotImplemented
        return Timeline(self.steps + other.steps)

    def then(self, *steps: Any) -> Timeline:
        """This history with *steps* appended. Returns a new timeline."""
        return Timeline(self.steps + tuple(steps))

    def periods(self) -> tuple[str, ...]:
        """Every period this history touches, in order of first appearance."""
        seen: list[str] = []
        for step in self.steps:
            period = getattr(step, "period", None)
            if isinstance(period, str) and period not in seen:
                seen.append(period)
        return tuple(seen)

    def outline(self) -> tuple[tuple[str, str], ...]:
        """``(period, scenario name)`` per step — what an SDK prints to decide
        whether a sampled history is the one it wanted before building it."""
        return tuple(
            (str(getattr(step, "period", "")), type(step).__name__) for step in self.steps
        )

    def run(self, world: World, *, review_first: bool = True) -> World:
        """Run every step against *world*, in order, and return the result.

        Reviewed before the first step runs, not as it goes: a history that is
        going to be refused at step five should be refused before step one has
        minted an id, because the alternative is a half-advanced world the
        caller now has to throw away. ``review_first=False`` is the escape
        hatch for a caller running against a world whose roster the review
        cannot see the whole of.
        """
        if review_first:
            ensure(self, Roster.of(world))
        for step in self.steps:
            world = world.run(step)
        return world


def of(*steps: Any) -> Timeline:
    """A history from scenario instances, written out by hand."""
    return Timeline(tuple(steps))


# ---------------------------------------------------------------------------
# Validity
# ---------------------------------------------------------------------------


def review(timeline: Timeline, roster: Roster) -> list[Rejection]:
    """Every reason this history cannot be run against this roster. All of them.

    The checks are the ones the engine would otherwise discover by crashing
    part-way through a build — a ``KeyError`` from inside ``Hire.run``, a
    ``ValueError`` from ``personnel.promote`` — stated up front so a history can
    be refused before a world has been advanced at all. Same division
    ``roles.review`` draws, and the engine keeps its own guards regardless:
    this is the predictable rejection, not the last line of defence.

    Walked forward with a running set of bound role keys, because validity is
    not a property of a step but of a step *at its position*: departing a role
    hired two steps earlier is fine, and departing it two steps before it is
    hired is not.
    """
    found: list[Rejection] = []

    def refuse(subject: str, rule: str, detail: str) -> None:
        found.append(Rejection(subject, rule, detail))

    if not timeline.steps:
        refuse("(empty)", "nothing_happens",
               "a history with no steps advances nothing. Running one is a"
               " no-op that looks like a build, which is the failure mode most"
               " expensive to notice.")
        return found

    held = set(roster.role_keys)          # keys a person holds — departable, promotable
    bound = set(roster.bound_keys)        # every key the table binds — un-hireable-into
    units = set(roster.unit_keys)
    unit_by_role = dict(roster.unit_by_role)
    succeedable = set(roster.succeedable)
    reserved = roster.reserved()
    headcount = roster.employees_total
    modelled_headcount = roster.modelled_headcount

    closed: set[str] = set()
    changed: dict[str, int] = {}  # period -> position of the first org change in it
    latest: str | None = None

    for position, step in enumerate(timeline):
        name = type(step).__name__
        subject = f"step {position} ({name})"
        period = getattr(step, "period", None)

        if not isinstance(period, str) or not _is_period(period):
            refuse(subject, "bad_period",
                   f"a period is YYYY-MM; this step carries {period!r}. Every"
                   " date in a corpus is arithmetic on that string — no clock"
                   " is consulted anywhere — so a malformed one has nothing to"
                   " be arithmetic on.")
            continue
        if latest is not None and period < latest:
            refuse(subject, "history_runs_backwards",
                   f"{period} follows {latest}. Facts are minted in step order"
                   " and dated by their own period, so a history that goes"
                   " backwards produces a corpus whose ledger order and whose"
                   " calendar disagree — and `finance.previous_periods` reads"
                   " the calendar.")
        else:
            latest = period

        if name == "Hire":
            key, unit_key = step.role_key, step.unit_key
            if key in reserved:
                refuse(subject, "hire_into_a_load_bearing_role",
                       f"{key!r} is a role the {roster.engine} engine looks up by"
                       " name. `Hire` rebinds the key, so from this period on"
                       " every generator that resolves it gets somebody hired"
                       " this month with no tenure and no history, while the"
                       " person the world was built around stays employed and"
                       " unreachable — an org change with nothing witnessing"
                       " it. Depart them instead, or hire under a new key.")
            elif key in bound:
                refuse(subject, "hire_over_an_incumbent",
                       f"{key!r} is already bound in the world's role table."
                       " `Hire` writes straight into it: if a person holds the"
                       " key they leave the post with no departure event and no"
                       " fact recording that they did, and if a system, service,"
                       " policy or cost centre holds it the key stops resolving"
                       " to that thing at all.")
            if not key or not key.replace("_", "").isalnum():
                refuse(subject, "bad_role_key",
                       f"{key!r}: role keys are lowercase alphanumerics and"
                       " underscores — they land in the world's role table and"
                       " the org generators parse `_md`/`_bp`/`_buyer` off the"
                       " end of them.")
            if unit_key not in units:
                refuse(subject, "unknown_unit",
                       f"there is no unit {unit_key!r}. `Hire` resolves both"
                       f" `unit_{unit_key}` and `{unit_key}_md` — the unit and"
                       " the manager the new post reports to — and would raise"
                       f" KeyError. Units here: {', '.join(roster.unit_keys) or '(none)'}")
            if not str(step.title).strip():
                refuse(subject, "untitled",
                       "a new post needs a title; it is what every document"
                       " that names this person prints.")
            if not str(step.function).strip():
                refuse(subject, "no_function",
                       "a new post needs a function; succession, cost centre"
                       " and persona are all decided from it.")
            bound.add(key)
            held.add(key)
            modelled_headcount += 1
            unit_by_role[key] = unit_key
            # The new post reports to the unit's MD by construction (see
            # `Hire.run`), so that role now has a direct report and can be
            # departed. Nothing else is assumed: a hire also creates a peer in
            # its own function, and under-claiming there is the safe direction.
            succeedable.add(unit_role_key(unit_key, "_md"))
            changed.setdefault(period, position)

        elif name == "Departure":
            key = step.role_key
            if key not in held:
                refuse(subject, "depart_an_unfilled_role",
                       f"no person holds {key!r} at this point in the history."
                       " A role has to have been hired into before anybody can"
                       " leave it — and a key bound to a system or a service is"
                       " not a post somebody can vacate.")
            elif key not in succeedable:
                refuse(subject, "no_eligible_successor",
                       f"{key!r} had no direct reports and nobody else in its"
                       " function when this roster was taken, and no hire in"
                       " this history has given it one. `Departure` picks a"
                       " successor from the org rather than inventing a person,"
                       " so it would raise rather than mint one.")
            elif key in held:
                modelled_headcount = max(0, modelled_headcount - 1)
            changed.setdefault(period, position)

        elif name == "Reorganisation":
            unit_key, leader = step.unit_key, step.new_leader_role
            incumbent = unit_role_key(unit_key, "_md")
            if unit_key not in units:
                refuse(subject, "unknown_unit",
                       f"there is no unit {unit_key!r} to reorganise. Units"
                       f" here: {', '.join(roster.unit_keys) or '(none)'}")
            if leader not in held:
                refuse(subject, "unfilled_leader_role",
                       f"no person holds {leader!r} at this point in the"
                       " history, so there is nobody to hand the unit to.")
            elif leader == incumbent:
                refuse(subject, "already_leads",
                       f"{leader!r} is the unit's managing director already."
                       " A reorganisation that changes nothing still mints an"
                       " event and a leadership fact, so the corpus would"
                       " record a hand-over that did not happen.")
            elif unit_by_role.get(leader) not in (None, unit_key):
                refuse(subject, "leader_outside_the_unit",
                       f"{leader!r} sits in {unit_by_role.get(leader)!r}."
                       " `personnel.promote` refuses this outright: a unit's"
                       " leader has to belong to it or to no unit at all, which"
                       " is what the graph check `leader_elsewhere` enforces.")
            if unit_key in units:
                unit_by_role[incumbent] = unit_key
                unit_by_role[leader] = unit_key
            changed.setdefault(period, position)

        elif name == "WorkforceChange":
            target = step.headcount
            if not isinstance(target, int) or isinstance(target, bool) or target < 0:
                refuse(subject, "bad_headcount",
                       f"headcount must be a non-negative integer; got {target!r}.")
            elif target < modelled_headcount:
                refuse(subject, "headcount_below_named_roster",
                       f"{target:,} is smaller than the {modelled_headcount:,}"
                       " named employees active at this point. Aggregate scale"
                       " may exceed the roster; it cannot contradict it.")
            elif target == headcount:
                refuse(subject, "headcount_did_not_change",
                       f"the stated workforce is already {target:,}. A no-op"
                       " workforce episode would create a false audit trail.")
            else:
                headcount = target
            changed.setdefault(period, position)

        elif name == "StructuralChange":
            targets = (step.business_units, step.sites, step.systems, step.services)
            if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
                   for value in targets):
                refuse(subject, "bad_estate_size",
                       f"estate targets must be non-negative integers; got {targets}.")
            if step.services and not step.systems:
                refuse(subject, "services_without_systems",
                       "a non-empty service estate needs at least one system.")
            changed.setdefault(period, position)

        else:
            # Anything this module does not recognise is an episode — the
            # resident domain's close, or a registered vertical's own scenario.
            if period in closed:
                refuse(subject, "period_closed_twice",
                       f"{period} already has an episode in this history. A"
                       " second one generates a whole second set of facts for"
                       " the same month, which reads as a duplicate rather than"
                       " a revision — the same reason `comparative_months`"
                       " belongs to the first close of a build and no other.")
            closed.add(period)
            first_change = changed.get(period)
            if first_change is not None:
                refuse(subject, "change_lands_before_its_own_episode",
                       f"step {first_change} changes the organisation in"
                       f" {period}, and this episode for {period} runs after"
                       " it. An org change belonging to a period lands eight"
                       " business days *after* that period's close (see"
                       " `scenarios._period_boundary`), which is what lets a"
                       " departing controller sign their own final close. Put"
                       " the episode first, or move the change to a later"
                       " period.")

    return found


def ensure(timeline: Timeline, roster: Roster) -> Timeline:
    """*timeline*, or ``TimelineError`` naming every rule it breaks."""
    violations = review(timeline, roster)
    if violations:
        raise TimelineError(violations)
    return timeline


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------


def _close(period: str, incident: bool | None) -> Any:
    """The resident domain's episode — retail's month-end close.

    Named here for the same reason ``cli`` and ``sdk`` name it: retail is the
    resident domain and its close is what a caller who states no episode
    means. Every other vertical registers a ``single_episode`` and passes it
    through the ``episode`` argument below, which is why that argument exists
    rather than a domain lookup — ``monthly`` and ``sample`` are given a
    roster, not a world, and a roster deliberately does not carry a builder.
    """
    from .scenarios import MonthEndClose

    return MonthEndClose(period=period, include_operational_incident=incident)


def monthly(
    start: str,
    count: int,
    *,
    months: int = 1,
    incident: bool | None = None,
    comparatives: int = 0,
    trend_pct: float = 0.0,
    eval_density: float = 1.0,
    physics: Any = None,
    seasonality: Any = None,
    actors: Any = None,
    actor_ledger: tuple = (),
) -> Timeline:
    """The build loop that exists today, as a value: *count* consecutive closes.

    Exactly what ``worldloom build --periods N`` runs, including the rule that
    comparatives and a trend belong to the *first* close only — they backfill
    months before it, and a later episode asking for them again would generate
    a second set of facts for months the corpus already has. Reproduced here
    rather than approximated so that this is a refactoring target for the CLI
    rather than a second, subtly different history engine beside it.

    A history with no org change in it. That is the point of having it: it is
    the null hypothesis ``sample`` is measured against, and a corpus built
    through it is byte-identical to one built through the loop.
    """
    from .parameters import DEFAULT
    from .scenarios import MonthEndClose

    steps = tuple(
        MonthEndClose(
            period=period,
            include_operational_incident=incident,
            comparative_months=comparatives if index == 0 else 0,
            trend_pct=trend_pct if index == 0 else 0.0,
            actors=actors,
            actor_ledger=actor_ledger,
            eval_density=eval_density,
            seasonality=seasonality,
            physics=DEFAULT if physics is None else physics,
        )
        for index, period in enumerate(periods_from(start, max(1, count), months=months))
    )
    return Timeline(steps)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Density:
    """How eventful a history is, as rates *per period*.

    **Why this is not a ``parameters.Span``.** The parameter registry is the
    world's *physics*: ranges a generator draws from inside an episode, with a
    byte-identity contract (``Parameters.number`` forwards the literal's exact
    arguments) and a recipe that records only the spans a pack actually moved.
    None of that fits here. Density decides *how many steps a caller asked
    for*, before any world exists and outside any episode; no generator ever
    draws from it; and putting it in the registry would mean a recipe's
    ``physics`` block grew a key that no ``rng`` call consults — a parameter
    that lies about being physics. The one genuinely physical neighbour,
    ``ops.incident.likelihood``, stays exactly where it is and answers a
    different question: given a close, how likely is *that* close to go wrong.
    This one answers how many of six months a caller wants to have gone wrong.

    Rates rather than counts so a density is reusable across histories of
    different length — a field of worlds run for three, six and twelve periods
    at ``STEADY`` should get proportionally eventful histories, not the same
    three events crammed into three months and rattling around in twelve.
    """

    incidents: float = 0.0
    departures: float = 0.0
    reorganisations: float = 0.0
    hires: float = 0.0

    def over(self, periods: int) -> dict[str, int]:
        """How many of each family a history of *periods* periods asks for."""
        return {
            "incidents": _events(self.incidents, periods),
            "departures": _events(self.departures, periods),
            "reorganisations": _events(self.reorganisations, periods),
            "hires": _events(self.hires, periods),
        }

    def scaled_for(self, headcount: int) -> Density:
        """Event density adjusted by workforce order of magnitude.

        The multiplier is logarithmic and capped: an 80,000-person company has
        more simultaneous organisational change than an 800-person company,
        not one hundred times as much.  Integer digit bands avoid a floating
        logarithm deciding whether a half-up count crosses an event boundary,
        preserving replay across Python and platform versions.

        This method is only applied when a caller explicitly supplies a
        ``Workforce`` trajectory. Existing timeline builds remain byte-identical.
        """
        if headcount < 0:
            raise ValueError(f"headcount must be non-negative, got {headcount}")
        digits = len(str(max(1, headcount)))
        multiplier = min(3.0, max(0.5, (digits - 2) * 0.5))
        return Density(
            incidents=self.incidents * multiplier,
            departures=self.departures * multiplier,
            reorganisations=self.reorganisations * multiplier,
            hires=self.hires * multiplier,
        )


def _events(rate: float, periods: int) -> int:
    """*rate* per period over *periods* periods, rounded half-up.

    Half-up written out rather than ``round``, which is banker's rounding:
    ``round(0.5)`` is 0 and ``round(1.5)`` is 2, so a rate of 0.1 would give no
    events over five periods and two over fifteen. Deterministic either way;
    only one of them is explicable to whoever asked for "one incident every six
    months" and got none.
    """
    if rate <= 0.0:
        return 0
    return max(0, int(rate * periods + 0.5))


#: A history with nothing in it but its episodes — what a build does today, and
#: the default, for the discipline `eval_density=1.0` and `trend_pct=0.0`
#: already follow: a knob added after corpora were built must reproduce them.
QUIET = Density()

#: One incident and one org change in roughly every six months. A company that
#: has a bad month twice a year and reorganises once.
STEADY = Density(incidents=1 / 6, departures=1 / 6, reorganisations=1 / 12)

#: A year that went badly: a crisis a quarter and leadership moving under it.
TURBULENT = Density(incidents=1 / 3, departures=1 / 4, reorganisations=1 / 6, hires=1 / 6)


@dataclass(frozen=True)
class Workforce:
    """Exact stated headcount from the first to the final period.

    Values between the anchors are linearly interpolated with integer half-up
    rounding. A target for period N is applied after period N-1 closes, matching
    every other organisation change: the new workforce is therefore in force
    when period N's episode begins.
    """

    initial: int
    final: int

    def __post_init__(self) -> None:
        if self.initial < 0 or self.final < 0:
            raise ValueError(
                f"workforce anchors must be non-negative; got"
                f" {self.initial:,} and {self.final:,}"
            )

    def headcounts(self, periods: int) -> tuple[int, ...]:
        if periods < 1:
            raise ValueError(f"a workforce trajectory needs at least one period, got {periods}")
        if periods == 1:
            if self.initial != self.final:
                raise ValueError(
                    "a one-period trajectory cannot move headcount; use at least"
                    " two periods or make --headcount-end equal --employees"
                )
            return (self.initial,)

        denominator = periods - 1
        delta = self.final - self.initial
        values: list[int] = []
        for index in range(periods):
            numerator = delta * index
            if numerator >= 0:
                offset = (numerator + denominator // 2) // denominator
            else:
                offset = -((-numerator + denominator // 2) // denominator)
            values.append(self.initial + offset)
        return tuple(values)

    @property
    def typical(self) -> int:
        """The exact integer midpoint used to scale event density."""
        return (self.initial + self.final) // 2


@dataclass(frozen=True)
class EstateSize:
    """One exact active structural-estate snapshot."""

    business_units: int
    sites: int
    systems: int
    services: int

    def __post_init__(self) -> None:
        values = (self.business_units, self.sites, self.systems, self.services)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
               for value in values):
            raise ValueError(f"estate sizes must be non-negative integers; got {values}")
        if self.services and not self.systems:
            raise ValueError("a non-empty service estate needs at least one system")


def _integer_path(initial: int, final: int, periods: int) -> tuple[int, ...]:
    if periods < 1:
        raise ValueError(f"a trajectory needs at least one period, got {periods}")
    if periods == 1:
        if initial != final:
            raise ValueError("a one-period trajectory cannot move; use at least two periods")
        return (initial,)
    denominator = periods - 1
    delta = final - initial
    values: list[int] = []
    for index in range(periods):
        numerator = delta * index
        offset = (
            (numerator + denominator // 2) // denominator
            if numerator >= 0
            else -((-numerator + denominator // 2) // denominator)
        )
        values.append(initial + offset)
    return tuple(values)


@dataclass(frozen=True)
class Estate:
    """Exact business-unit, site, system and service trajectory.

    Each dimension is interpolated independently using the same integer
    half-up rule as :class:`Workforce`. The first snapshot describes the built
    world; later snapshots become ``StructuralChange`` episodes between closes.
    """

    initial: EstateSize
    final: EstateSize

    def sizes(self, periods: int) -> tuple[EstateSize, ...]:
        paths = (
            _integer_path(self.initial.business_units, self.final.business_units, periods),
            _integer_path(self.initial.sites, self.final.sites, periods),
            _integer_path(self.initial.systems, self.final.systems, periods),
            _integer_path(self.initial.services, self.final.services, periods),
        )
        return tuple(EstateSize(*values) for values in zip(*paths))


@dataclass(frozen=True)
class Opening:
    """A post a caller wants filled at some point in the history.

    Hires are the one org change whose *content* cannot be derived. A
    departure's successor comes out of the org (reports, then same-function
    peers); a reorganisation's new leader is a role that already exists. A new
    post's title and function are a business decision, and nothing in a built
    world contains them — a sampler that invented "Head of Something, level 3"
    would be writing the least plausible sentence in the corpus. So the sampler
    decides *when* an opening lands, which is what a timeline is for, and never
    what it is.
    """

    role_key: str
    title: str
    function: str
    unit_key: str | None = None
    """``None`` lets the sampler place the post in one of the roster's units."""


#: Where each event family starts reading the Halton sequence. Without this
#: every family of the same size lands on the same month — one incident, one
#: departure and one reorganisation over six periods all take Halton's first
#: point, which is the midpoint, and a feature built to stop a history being one
#: month photocopied would put its whole history in one month. ``skip`` is
#: already the sequence's own parameter (``halton`` skips the origin by default
#: for a related reason), so phasing costs nothing and stays Rng-free. The
#: values are small and distinct rather than meaningful: they make the families'
#: first buckets differ for every history length worth sampling.
_PHASE: Mapping[str, int] = {
    "incidents": 1, "departures": 2, "reorganisations": 3, "hires": 5,
}


def _spread(periods: int, count: int, *, skip: int = 1) -> tuple[int, ...]:
    """*count* period indices out of *periods*, as far apart as they go.

    Halton for the candidates, farthest-first for the pick — precisely the
    composition ``dispersion``'s docstring describes: cover the space evenly,
    then take the few least like each other. In one dimension over a line of
    periods that is not decoration. Halton base 2 visits the midpoint, then the
    quarters, then the eighths, so the first candidate is the middle month
    rather than the first; farthest-first then resolves the collisions that
    bucketing floats into a small number of months inevitably produces, by the
    only distance a calendar has.

    **Placement draws no ``Rng``, and that is the design call.** ``dispersion``
    is explicit that a diversity mechanism seeded from the world seed would
    make "how varied is this corpus" depend on which world you happened to
    build. Where the incidents fall is exactly that kind of claim: two
    incidents in six months should be four months apart in every world, not
    adjacent in the unlucky ones. *Which* role departs is the opposite kind of
    claim — a fact about this particular company, whose candidate set differs
    world to world — and comes from a named ``Rng`` stream below.
    """
    if count <= 0 or periods <= 0:
        return ()
    if count >= periods:
        return tuple(range(periods))

    order: list[int] = []
    seen: set[int] = set()
    for point in halton(1, periods * 4, skip=skip):
        index = min(int(point[0] * periods), periods - 1)
        if index not in seen:
            seen.add(index)
            order.append(index)
        if len(seen) == periods:
            break
    # Halton over four times as many points as there are periods covers every
    # bucket for any length worth sampling, but the fallback is written rather
    # than asserted: a caller with a very long history should get a correct
    # answer, not an IndexError from `farthest_first`.
    order.extend(index for index in range(periods) if index not in seen)

    chosen = farthest_first(order, lambda a, b: float(abs(a - b)), count)
    return tuple(sorted(order[index] for index in chosen))


def sample(
    *,
    roster: Roster,
    start: str,
    periods: int,
    seed: int,
    density: Density = QUIET,
    workforce: Workforce | None = None,
    estate: Estate | None = None,
    openings: Sequence[Opening] = (),
    months: int = 1,
    episode: Callable[[str, bool | None], Any] = _close,
) -> Timeline:
    """A reproducible history: *periods* episodes with *density*'s events in them.

    Deterministic from ``(seed, roster, density, workforce, openings, periods)`` and
    nothing else — no clock, no ``random``, no iteration over a set. Sampling
    the same arguments twice gives the same timeline, and running that timeline
    gives the same corpus, which is what makes a sampled history rebuildable
    from the recipe its own steps wrote.

    Incidents are stated in **both** directions once ``density.incidents`` is
    non-zero: scheduled periods get ``True`` and the rest get ``False``,
    rather than leaving the unscheduled ones to the seed's own coin. A
    schedule that only says where an incident *is* is not a schedule, and
    "which month went wrong" stops being answerable from the history alone the
    moment an unscheduled month can also go wrong. At the default density of
    zero no close states anything, every close keeps ``None``, and the world's
    physics decides as it always has.

    Ordering within a period is fixed and not sampled: the episode first, then
    that period's org changes. That is ``scenarios._period_boundary``'s timing
    made explicit — a change belonging to a period lands after that period's
    close, so a departing controller signs their own final close and the
    successor signs the next one.
    """
    if periods < 1:
        raise ValueError(f"a history needs at least one period, got {periods}")
    if workforce is not None and workforce.initial != roster.employees_total:
        raise ValueError(
            f"workforce starts at {workforce.initial:,}, but the world states"
            f" {roster.employees_total:,}; a trajectory must begin at the"
            " organisation it is sampled against"
        )

    stamps = periods_from(start, periods, months=months)
    rng = Rng(seed, "timeline")
    effective_density = (
        density if workforce is None else density.scaled_for(workforce.typical)
    )
    wants = effective_density.over(periods)

    incident_at = set(_spread(periods, wants["incidents"], skip=_PHASE["incidents"]))
    state_incidents = bool(incident_at)

    # Each event family gets its own named stream and its own dispersed
    # placement, for the reason `rng`'s module docstring gives: sharing one
    # stream would mean adding a departure reshuffled where the incidents fell,
    # and a seed would stop meaning the same history across versions.
    changes: dict[int, list[Any]] = {}

    def at(index: int, step: Any) -> None:
        changes.setdefault(index, []).append(step)

    from .roles import ROOT
    from .scenarios import Departure, Hire, Reorganisation, StructuralChange, WorkforceChange

    # Aggregate workforce first within each period's boundary. The path's
    # second value becomes effective after the first close, so the second close
    # sees it; this is the same temporal rule departures and reorganisations use.
    if workforce is not None:
        path = workforce.headcounts(periods)
        for index, target in enumerate(path[1:]):
            if target != path[index]:
                at(index, WorkforceChange(period=stamps[index], headcount=target))

    if estate is not None:
        path = estate.sizes(periods)
        for index, target in enumerate(path[1:]):
            if target != path[index]:
                at(index, StructuralChange(
                    period=stamps[index],
                    business_units=target.business_units,
                    sites=target.sites,
                    systems=target.systems,
                    services=target.services,
                ))

    # Departures first, because they are the family with a candidate set that
    # can be exhausted: a role is departed at most once per sampled history
    # (the successor holds the key afterwards, and departing it again would be
    # a second hand-over of the same post inside a year, which reads as churn
    # nobody modelled rather than as history). The root is excluded — a
    # sampled chief-executive succession is a corpus-defining event that
    # should be asked for by name, not arrived at by a rate.
    departable = sorted(roster.succeedable - {ROOT})
    wanted = min(wants["departures"], len(departable))
    leaving: set[str] = set()
    if wanted:
        picked = rng.derive("departures").sample(departable, wanted)
        placed = _spread(periods, wanted, skip=_PHASE["departures"])
        # A function of N people sustains at most N-1 departures: each one
        # consumes a leaver and hands the key to somebody already inside the
        # organisation, so the last person standing has nobody to hand to.
        # `succeedable` cannot express that — it is asked once per role, and
        # this is a budget shared across every role in a function.
        #
        # Conservative on purpose. A successor drawn from *direct reports* may
        # come from another function, so the true capacity is sometimes higher;
        # deriving it exactly would mean reimplementing `personnel.depart`'s
        # choice here, and a planner that models the engine approximately is a
        # second source of truth about the organisation. Scheduling one
        # departure fewer than possible costs a corpus nothing. Scheduling one
        # too many costs it the whole build, 40 periods in.
        room = {name: count - 1 for name, count in roster.function_size.items()}
        for index, role_key in zip(placed, picked, strict=True):
            function = roster.function_by_role.get(role_key)
            if function is not None:
                if room.get(function, 0) <= 0:
                    # Dropped, not deferred, and every other family keeps the
                    # placement it already had — a history missing one
                    # succession is a history; one whose incidents all moved
                    # because a succession was dropped is a different corpus.
                    continue
                room[function] -= 1
            at(index, Departure(period=stamps[index], role_key=role_key))
            leaving.add(role_key)

    # Reorganisations: a unit, and somebody already inside it who is not
    # already its MD. Both constraints come straight from `personnel.promote`,
    # which refuses a leader assigned to another unit outright.
    #
    # Roles this history departs are excluded, and that is not fastidiousness:
    # after a departure the key points at the *successor*, who was chosen from
    # reports or same-function peers and may sit in a different unit entirely.
    # Handing a unit to that key would then be handing it to somebody assigned
    # elsewhere, which `promote` refuses outright — a sampler must not be able
    # to emit a history the engine will reject.
    seats = [
        (unit_key, candidate)
        for unit_key in roster.unit_keys
        for candidate in roster.roles_in(unit_key)
        if candidate != unit_role_key(unit_key, "_md") and candidate not in leaving
    ]
    wanted = min(wants["reorganisations"], len(seats))
    if wanted:
        picked = rng.derive("reorganisations").sample(seats, wanted)
        placed = _spread(periods, wanted, skip=_PHASE["reorganisations"])
        for index, (unit_key, leader) in zip(placed, picked, strict=True):
            at(index, Reorganisation(
                period=stamps[index], unit_key=unit_key, new_leader_role=leader,
            ))

    # Hires: placement is the sampler's, content is the caller's (see `Opening`).
    wanted = min(wants["hires"], len(openings))
    if wanted:
        unit_rng = rng.derive("openings")
        placed = _spread(periods, wanted, skip=_PHASE["hires"])
        for index, opening in zip(placed, openings[:wanted], strict=True):
            unit_key = opening.unit_key
            if unit_key is None:
                if not roster.unit_keys:
                    raise ValueError(
                        f"opening {opening.role_key!r} names no unit and this"
                        " roster has none to put it in"
                    )
                unit_key = unit_rng.choice(roster.unit_keys)
            at(index, Hire(
                period=stamps[index], role_key=opening.role_key, title=opening.title,
                function=opening.function, unit_key=unit_key,
            ))

    steps: list[Any] = []
    for index, stamp in enumerate(stamps):
        steps.append(episode(stamp, (index in incident_at) if state_incidents else None))
        steps.extend(changes.get(index, ()))
    return Timeline(tuple(steps))


__all__ = [
    "Density", "Opening", "ORG_VERBS", "QUIET", "Roster", "STEADY", "TURBULENT",
    "Workforce", "EstateSize", "Estate",
    "Timeline", "TimelineError", "ensure", "monthly", "of", "period_after",
    "periods_from", "review", "sample",
]
