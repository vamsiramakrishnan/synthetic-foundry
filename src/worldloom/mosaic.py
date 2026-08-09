"""Many companies from one command, as unlike each other as the rules allow.

Everything below this module makes a world *variable*. ``parameters`` names the
ranges a figure is drawn from, ``roles`` lets an organisation be a shape rather
than a fixed table, ``profiles`` gives a business its own trading year, and
``probe`` lets a model derive all of it by asking. None of that changes what
comes out of ``worldloom build``, because nothing drives it: five seeds still
produce one company with different names on the same twenty-three people.

That is the gap this closes. A mosaic is *N* worlds chosen to be as unlike each
other as the constraints permit, each one internally coherent, all of them
reproducible from a number.

**Why not just vary the seed.** Because the seed is not connected to any of
this. It decides names, figures, and which month the incident lands in; it does
not decide headcount, span of control, reporting depth, trading calendar, or
how fast an organisation finds the cause of an outage. Those are the things a
reader would call a different company, and until this module they were reachable
only by hand.

**The algorithm, and why it is this one.**

*Cover, then choose.* Candidates come from a Halton sequence over the unit
hypercube rather than from random draws, because the goal is coverage of a
space and random points clump — with a few hundred draws in seven dimensions
that is not a subtlety, it is most of the space unvisited, and an unvisited
region is a company shape the tool can never produce. Then
``dispersion.farthest_first`` takes the *N* furthest apart. Generating *N*
directly and hoping they differ is the thing this deliberately does not do.

*Feasible before dispersed.* A candidate is discarded if its shape cannot be
built — three levels of eleven people, or more people than the engine has
distinct names for. Filtering before selection rather than after matters: a
farthest-first traversal that picks an infeasible extreme and then drops it
returns *N-1* worlds and, worse, spends its first pick on the corner of the
space furthest from everything real.

*Normalised before measured.* Distance is L1 over the unit coordinates, not
over the values they map to. Headcount runs to forty and a margin runs from
0.2 to 0.6; unmeasured against their own ranges, headcount would decide
entirely what "unlike" means and every world would differ in one dimension
while looking identical in the rest.

**Determinism.** No clock, no ``random``, no set iteration deciding anything.
The same request returns the same mosaic on every machine, each world carries a
recipe that rebuilds it alone, and ``mosaic --describe`` prints what varies
without building anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import profiles
from .dispersion import farthest_first, halton, manhattan
from .parameters import DEFAULT, Parameters, Span
from .roles import from_shape, measure, to_rows

#: How many candidates are covered before dispersion chooses from them. The
#: filter below throws most away — an infeasible shape is common near the edges
#: of the space — so this is sized to leave a real field to choose from rather
#: than to be a sample of anything.
_POOL = 512

#: The trading years a mosaic will pick between. Every profile the registry
#: ships, in a fixed order: a discrete dimension needs a stable index or the
#: same coordinate would mean a different calendar between runs.
_CALENDARS: tuple[str, ...] = tuple(sorted(profiles.PROFILES))

#: What an engine that does not vary a calendar gets: the engine's own,
#: which for a bank or an insurer is the one its figures were always drawn
#: under, since no generator on those paths reads it.
_DEFAULT_CALENDAR = "retail_christmas"


@dataclass(frozen=True)
class Axis:
    """One thing a mosaic varies, and the range it varies over.

    Named and listed rather than hardcoded into the sampler so that
    ``mosaic --describe`` can print what will differ *before* anything is built.
    A user deciding whether five worlds are worth generating should be able to
    see what makes them five.
    """

    name: str
    low: float
    high: float
    about: str
    integral: bool = False
    parameter: str | None = None
    """The registry parameter this axis moves, when it moves one. ``None`` for
    the axes that shape the organisation rather than its physics."""
    band: float | None = None
    """Half the width of the span each world gets, when it should not be the
    engine's own.

    ``None`` means "carry the engine's width across", which is right for this
    module's own axes: they move a parameter's *level* over a range wider than
    the engine's, and the engine's width is the variation-within-a-corpus the
    engine intended. It is wrong for a probe-derived axis, where the interval
    is not a range of levels but the *envelope a model argued for* — so there
    the band is a fraction of that envelope and every world's span stays inside
    what the model actually claimed. Widening past it would spend the model's
    reasoning and report having honoured it."""

    def at(self, coordinate: float) -> float:
        value = self.low + coordinate * (self.high - self.low)
        return float(round(value)) if self.integral else value


#: The estate sizes a mosaic will pick between, plus no estate at all. The
#: engine's own default is "none" — nine nodes, whatever the archetype's scale —
#: so it stays in the field rather than being quietly dropped: a corpus with a
#: thin landscape is a legitimate world and one axis should not decide
#: otherwise.
_ESTATES: tuple[str | None, ...] = (None, "small", "medium", "large")

#: What every mosaic varies, whatever engine it runs. An organisation's shape
#: and its technology landscape are not industry-specific claims — a bank and a
#: grocer both have a headcount, a span of control and a number of reporting
#: levels, and both either do or do not have a landscape worth reading.
_STRUCTURE: tuple[Axis, ...] = (
    Axis("headcount", 14, 31, integral=True,
         about="How many people the organisation has. Capped at what the engine"
               " has distinct names for; a pack with its own name pools lifts it."),
    Axis("span", 3, 9, integral=True,
         about="Reports per manager. The difference between a flat organisation"
               " and one with a layer of middle management."),
    Axis("levels", 2, 5, integral=True,
         about="Reporting levels below the chief executive. With headcount and"
               " span this is over-determined, so infeasible combinations are"
               " discarded rather than rounded into feasibility."),
    Axis("estate", 0, len(_ESTATES) - 1e-9,
         about="How much technology landscape the company has, from none to"
               " large. Decides whether the corpus can be asked what has a blast"
               " radius and what nothing routes around."),
)

#: The physics each engine varies, on top of the structure above. Separate per
#: engine because the parameters are: `retail.margin.erosion` means nothing to a
#: bank, and a mosaic that moved it would report varying something it had not.
#:
#: Each set is chosen the same way — the things a *reader* would name if asked
#: how two corpora differed, not the things easiest to vary. Every engine gets
#: an incident-tempo axis, because how fast an organisation finds a cause is the
#: clearest single statement a corpus makes about how it is run.
_PHYSICS: Mapping[str, tuple[Axis, ...]] = {
    "retail": (
        # Retail only, and not an oversight: `finance.generate` is the one
        # generator that reads a trading year, and only this engine runs it. A
        # banking mosaic carrying this axis would report varying a calendar
        # that changed nothing, which is precisely the failure this module
        # splits its axes per engine to avoid.
        Axis("calendar", 0, len(_CALENDARS) - 1e-9,
             about="Which trading year the business has, from `worldloom pack"
                   " profiles`. A flat book, a Christmas peak, a harvest."),
        Axis("margin_erosion", 0.002, 0.060, parameter="retail.margin.erosion",
             about="How much promotional activity takes off budgeted margin — the"
                   " size of the story the variance memo has to tell."),
        Axis("incident_tempo", 12, 180, integral=True,
             parameter="ops.incident.hypothesis_minutes",
             about="Minutes from detection to a first hypothesis. This is the"
                   " organisation's operational maturity: twenty minutes is a"
                   " capable team, three hours is a struggling one."),
        Axis("revenue_miss", -0.12, 0.01, parameter="retail.revenue.miss_pct",
             about="How far a unit's revenue lands from budget. Decides whether"
                   " the corpus is about a bad month or an ordinary one."),
    ),
    "banking": (
        Axis("capital_headroom", 10.6, 16.0, parameter="capital.ratio.target_pct",
             about="The CET1 ratio the bank targets. A mutual runs high; a bank"
                   " under a capital plan runs at its floor, and the whole"
                   " challenged-return story reads differently at each."),
        Axis("understatement", 0.01, 0.12, parameter="capital.error.understatement_pct",
             about="How badly the filed risk-weighted assets understate the truth"
                   " — the severity of the error the second line challenges."),
        Axis("incident_tempo", 20, 240, integral=True,
             parameter="capital.incident.hypothesis_minutes",
             about="Minutes from detection to a first hypothesis on the"
                   " reconciliation break."),
        Axis("balance_sheet", 60, 400, integral=True,
             parameter="capital.rwa.filed_hundreds",
             about="Risk-weighted assets as filed, in hundreds. The size of the"
                   " bank."),
    ),
    "insurance": (
        Axis("tail_length", 0.30, 0.92, parameter="reserves.cohort.incurred_ratio",
             about="How much of ultimate cost is already incurred. Near 0.95 is a"
                   " short-tail book settling fast; near 0.4 is long-tail motor"
                   " injury, and the vertical reads as a different business at"
                   " each end."),
        # The low end is 1.25 and not 1.05, and the arithmetic is the reason: a
        # physics axis carries the engine's own *width* across (see `_candidate`),
        # and this parameter's is 0.4 — so a centre of 1.05 generates a span
        # starting at 0.85 and `triangles.generate` refuses it, correctly. The
        # first version of this axis did exactly that and every insurance mosaic
        # died on it. 1.25 is the lowest centre whose whole band clears 1.0.
        Axis("deterioration", 1.25, 2.20, parameter="reserves.decision.movement_multiple",
             about="How far the recommended strengthening exceeds the release —"
                   " how bad the news the actuary has to deliver is. Stays above"
                   " 1.0, because at or below it the held-versus-central gap this"
                   " vertical exists to pose stops opening."),
        Axis("book_size", 20, 160, integral=True, parameter="reserves.cohort.ultimate",
             about="An accident cohort's ultimate claims cost. The size of the"
                   " book being reserved."),
        Axis("benign_share", 0.10, 0.70, parameter="reserves.attribution.pattern_fraction",
             about="How much of the movement is pattern change rather than genuine"
                   " deterioration — how defensible the actuary's position is."),
    ),
}

#: Every engine a mosaic can build, and what it varies.
ENGINES: Mapping[str, tuple[Axis, ...]] = {
    engine: _STRUCTURE + physics for engine, physics in _PHYSICS.items()
}

#: Retail's, for callers that predate `engine=` and for `AXES` as a public name.
AXES: tuple[Axis, ...] = ENGINES["retail"]

#: The structural axes alone, public because `register_engine` needs them: a
#: vertical registering from its own module composes `STRUCTURE + (its physics
#: axes)`, the same sum `ENGINES` is built from — reaching into another
#: engine's tuple and filtering out its physics would encode the accident that
#: structural axes happen to carry no `parameter`.
STRUCTURE: tuple[Axis, ...] = _STRUCTURE

#: Functions to draw an organisation's departments from, longest-first so a
#: bigger company gets more of them. Ordered, never shuffled: a mosaic's shapes
#: must be a function of its coordinates alone.
_FUNCTIONS: tuple[str, ...] = (
    "Executive", "Finance", "Technology", "Operations", "Merchandising",
    "ServiceOperations", "Risk", "Supply Chain", "Digital", "People",
)


@dataclass(frozen=True)
class Variant:
    """One world in the mosaic: everything that makes it not the others."""

    index: int
    seed: int
    headcount: int
    span: int
    levels: int
    calendar: str
    overrides: Mapping[str, Span]
    coordinates: tuple[float, ...]
    engine: str = "retail"
    estate: str | None = None
    vocabulary: str = ""
    """Which ``worldloom.vocabulary`` preset this world's divisions are named
    from. Empty is the archetype's own words.

    Not an ``Axis``, and that is a decision rather than an omission. The axes
    are a *continuous* space that ``farthest_first`` disperses over, and every
    world's whole shape is read off its coordinates — adding a twelfth dimension
    would move every existing world's headcount and span in order to vary a
    string, which would make the before/after this exists to be measured by
    unreadable. Vocabularies are instead dealt out in `_field` from a permuted
    registry, which guarantees what dispersion only approximates: no two worlds
    of a mosaic speak the same words until the registry runs out."""

    @property
    def functions(self) -> tuple[str, ...]:
        """Departments, scaled to the organisation's size.

        A fourteen-person company with ten functions is ten people who each
        *are* a department, which is not a small company — it is a spreadsheet.
        """
        return _FUNCTIONS[:max(3, min(len(_FUNCTIONS), self.levels + self.span // 2))]

    @property
    def physics(self) -> Parameters:
        return DEFAULT.with_overrides(dict(self.overrides))

    @property
    def seasonality(self) -> profiles.Seasonality:
        return profiles.named(self.calendar)

    def role_table(self, engine: str | None = None) -> tuple[tuple[str, str, str, str | None], ...]:
        return to_rows(from_shape(
            functions=self.functions, headcount=self.headcount,
            span=self.span, levels=self.levels, engine=engine or self.engine,
        ))

    def speaks(self, shape: Any) -> Any:
        """*shape*, saying this world's words — or *shape* itself, unchanged.

        Returns the archetype it was given whenever this variant has no
        vocabulary, which is every engine whose unit kinds nothing in
        ``worldloom.vocabulary`` names, and every archetype a pack authored.
        A build that goes through here and gets nothing back is therefore
        byte-identical to one that never called it, which is what lets the
        caller apply it unconditionally.
        """
        from .vocabulary import spoken

        return spoken(shape, self.vocabulary)

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "seed": self.seed,
            "headcount": self.headcount,
            "span": self.span,
            "levels": self.levels,
            "engine": self.engine,
            "calendar": self.calendar,
            "estate": self.estate,
            "vocabulary": self.vocabulary,
            "functions": list(self.functions),
            "physics": {name: span.as_dict() for name, span in sorted(self.overrides.items())},
        }

    def summary(self) -> str:
        parts = [f"{self.headcount} people", f"spans of {self.span}",
                 f"{self.levels} levels"]
        # Named only when this engine actually reads one. Printing
        # "retail_christmas calendar" beside a bank would tell a reader the
        # mosaic varied something it did not.
        if any(axis.name == "calendar" for axis in ENGINES[self.engine]):
            parts.append(f"{self.calendar} calendar")
        parts.append("no estate" if self.estate is None else f"{self.estate} estate")
        # Named only when there is one, for `calendar`'s reason above: printing
        # "no vocabulary" beside every world of an engine this registry does not
        # cover would report a dimension the mosaic did not actually vary.
        if self.vocabulary:
            parts.append(f"{self.vocabulary} vocabulary")
        return ", ".join(parts)


def _candidate(
    index: int, coordinates: Sequence[float], *, seed: int, engine: str = "retail",
    axes: Sequence[Axis] | None = None,
) -> Variant | None:
    """One variant from one point in the unit cube, or ``None`` if unbuildable."""
    axes = ENGINES[engine] if axes is None else tuple(axes)
    values = {axis.name: axis.at(coordinate)
              for axis, coordinate in zip(axes, coordinates, strict=True)}
    # The raw unit coordinate as well as the value it maps to. A banded axis
    # needs the coordinate: it squeezes the centre inward by half a band, which
    # is a different mapping from `Axis.at`'s, and using the already-mapped
    # value here put a margin envelope of [0.50, 0.58] at 0.79.
    unit = {axis.name: coordinate
            for axis, coordinate in zip(axes, coordinates, strict=True)}

    overrides: dict[str, Span] = {}
    for axis in axes:
        if axis.parameter is None:
            continue
        engine_span = DEFAULT.span(axis.parameter)
        # A band around the sampled point rather than the point itself. A span
        # whose ends are equal is a constant, and a world whose every figure is
        # the same number is not a world.
        half = axis.band if axis.band is not None else (engine_span.high - engine_span.low) / 2.0
        # For a derived axis the sampled centre is squeezed inward by the band,
        # so the resulting span cannot escape the envelope the probe argued
        # for. `Axis.at` maps the coordinate across the whole interval, which is
        # what this module's own axes want and what a probe's must not have.
        centre = (values[axis.name] if axis.band is None
                  else axis.low + half
                  + unit[axis.name] * max(0.0, (axis.high - axis.low) - 2 * half))
        low, high = centre - half, centre + half
        if engine_span.kind == "integer":
            low, high = round(low), round(high)
            if low >= high:
                high = low + 1
        overrides[axis.parameter] = Span(low, high)

    variant = Variant(
        index=index,
        seed=seed,
        headcount=int(values["headcount"]),
        span=int(values["span"]),
        levels=int(values["levels"]),
        calendar=(_CALENDARS[int(values["calendar"])]
                  if "calendar" in values else _DEFAULT_CALENDAR),
        overrides=overrides,
        coordinates=tuple(coordinates),
        engine=engine,
        # An engine may register without the estate axis — procurement's world
        # builder refuses `estate=` outright, so dealing it one would build
        # worlds the builder rejects. Absent axis, no estate, same as the
        # `calendar` fallback two lines up.
        estate=_ESTATES[int(values["estate"])] if "estate" in values else None,
    )
    try:
        table = variant.role_table()
    except ValueError:
        # Over-determined: headcount, span and depth cannot all hold. Discarded
        # rather than nudged into feasibility, because nudging would quietly
        # pile candidates onto the boundary of the feasible region and the
        # dispersion would then be over a distorted space.
        return None
    shape = measure(list(_roles(table)))
    if shape["levels"] != variant.levels:
        return None
    return variant


def _roles(rows: Sequence[tuple[str, str, str, str | None]]):  # type: ignore[no-untyped-def]
    from .roles import from_rows

    return from_rows(rows)


def field(
    count: int,
    *,
    seed: int = 8128,
    engine: str = "retail",
    pool: int = _POOL,
) -> tuple[Variant, ...]:
    """*count* variants, covered then chosen for maximum dispersion.

    Every world gets a seed derived from the base by index, so a mosaic's third
    world is reproducible without rebuilding the first two — and so two mosaics
    of different sizes agree on the worlds they share.
    """
    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")
    if engine not in ENGINES:
        raise KeyError(
            f"unknown engine {engine!r}; a mosaic can be built for"
            f" {sorted(ENGINES)}. Each varies its own physics, because"
            " `retail.margin.erosion` means nothing to a bank and a mosaic that"
            " moved it would report varying something it had not."
        )
    if count == 0:
        return ()
    return _field(count, seed=seed, engine=engine, axes=ENGINES[engine], pool=pool)


def _field(
    count: int, *, seed: int, engine: str, axes: Sequence[Axis], pool: int = _POOL,
) -> tuple[Variant, ...]:
    """``field``, over an explicit axis set. Shared with ``from_probe``."""
    if count == 0:
        return ()
    feasible: list[Variant] = []
    points: list[tuple[float, ...]] = []
    for coordinates in halton(len(axes), pool):
        variant = _candidate(len(feasible), coordinates,
                             seed=seed + len(feasible), engine=engine, axes=axes)
        if variant is None:
            continue
        feasible.append(variant)
        points.append(tuple(coordinates))

    if not feasible:
        raise ValueError(
            f"no feasible world among {pool} candidates — every combination of"
            " headcount, span and depth this mosaic sampled was over-determined."
            " Widen an axis or raise the pool."
        )
    if count > len(feasible):
        raise ValueError(
            f"asked for {count} worlds and only {len(feasible)} of {pool} candidates"
            " are buildable. The binding constraint is usually headcount against"
            " the engine's name pools; a pack with its own pools lifts it."
        )

    chosen = farthest_first(points, manhattan, count)
    dialects = _vocabularies(engine, seed)
    # Re-indexed and re-seeded in selection order so world 1 is the first
    # chosen, not whichever candidate happened to survive the filter first.
    return tuple(
        Variant(
            index=position + 1,
            seed=seed + position,
            headcount=feasible[at].headcount,
            span=feasible[at].span,
            levels=feasible[at].levels,
            calendar=feasible[at].calendar,
            overrides=feasible[at].overrides,
            coordinates=feasible[at].coordinates,
            engine=feasible[at].engine,
            estate=feasible[at].estate,
            # By position, so `mosaic -n 3` and `mosaic -n 5` agree on the words
            # of the worlds they share — the property `field`'s docstring
            # already promises for seeds and shapes, extended to vocabulary
            # because a corpus a user rebuilt with a larger `-n` renaming every
            # division of the worlds they already had would be worse than no
            # variation at all.
            vocabulary=dialects[position % len(dialects)] if dialects else "",
        )
        for position, at in enumerate(chosen)
    )


def _vocabularies(engine: str, seed: int) -> tuple[str, ...]:
    """The words this mosaic's worlds will be dealt, in the order they are dealt.

    A permutation rather than a per-world draw. Five independent draws from
    eleven names collide about half the time, and two worlds of a mosaic being
    the same company is the exact defect this varies vocabulary to fix — the
    module already refuses to let dispersion be approximated by sampling, and
    this is the same argument one dimension over.

    Permuted rather than taken in registry order because the alternative makes
    ``mosaic --seed`` a lie about words: every seed would produce the same five
    companies with different figures inside them. ``rng.Rng`` gives the stream a
    name of its own, so adding a draw here can never reshuffle anything else a
    seed decides.

    Cycles when the registry is shorter than the mosaic — a nine-world banking
    mosaic reuses three vocabularies. Cycling and not refusing, because a world
    that shares another's words still differs in headcount, depth, estate and
    physics, and a mosaic that would not build at all is a worse answer than one
    that repeats a name.
    """
    from .rng import Rng
    from .vocabulary import for_engine

    available = for_engine(engine)
    if not available:
        return ()
    return tuple(Rng(seed).derive("vocabulary").shuffled(available))


def from_probe(
    session: Any,
    count: int,
    *,
    seed: int = 8128,
    engine: str = "retail",
) -> tuple[Variant, ...]:
    """A mosaic whose axes a model reasoned its way to, rather than this module's.

    The two halves of this project's variety machinery have until now been
    unable to talk to each other. ``probe`` lets a model derive a world by
    Socratic questioning and hands back ranges it argued for; ``field`` samples
    a space this module hardcoded and hands back worlds. A model that reasoned
    carefully to "specialty apparel clears six units in ten at full price, so
    margin lives in [0.50, 0.58]" then had to watch that range be ignored,
    because a mosaic sampled ``retail.margin.erosion`` across the engine's own
    bounds regardless.

    So: the probe decides **what varies and between which bounds**, and the
    algorithm decides **which N**. That division is the point. A model is good
    at arguing that a business of this kind has margins in that band and bad at
    picking five points that cover a seven-dimensional space; a farthest-point
    traversal is the reverse. Neither half is asked to do the other's job.

    Concretely, every terminal the probe bound becomes an axis over the interval
    the probe settled on, replacing this module's default axis for that
    parameter if it had one and adding it if it did not. Axes the probe said
    nothing about keep their defaults — a probe that reasoned about margin and
    ignored reporting depth should still get five different reporting depths,
    not five copies of the engine's.

    A probe that bound *nothing* is refused rather than silently falling back to
    the default field: it means the model answered every question without ever
    reaching the engine, and returning an ordinary mosaic would report success
    for work that changed nothing.
    """
    from . import probe as probe_module

    if engine not in ENGINES:
        raise KeyError(f"unknown engine {engine!r}; known: {sorted(ENGINES)}")

    resolution = probe_module.resolve(session.graph)
    if not resolution.usable:
        raise ValueError(
            "this probe cannot produce physics yet: "
            + "; ".join([*resolution.unanswered,
                         *(str(c) for c in resolution.contradictions)])
        )
    if not resolution.overrides:
        raise ValueError(
            "this probe bound no terminal parameter, so there is nothing for a"
            " mosaic to vary that it would not have varied anyway. Every leaf"
            " is unbound: "
            + ", ".join(u.key for u in resolution.unbound[:5])
            + ". Bind one to a parameter from `worldloom pack params`, or ask"
            " for an ordinary mosaic."
        )

    derived: list[Axis] = []
    for name, span in sorted(resolution.overrides.items()):
        engine_span = DEFAULT.span(name)
        derived.append(Axis(
            name=name.rsplit(".", 1)[-1],
            low=span.low, high=span.high,
            integral=engine_span.kind == "integer",
            parameter=name,
            # A quarter of the envelope, so a world's band is narrow enough for
            # the five to differ and wide enough that no world's figures are all
            # one number. The envelope itself is never exceeded.
            band=(span.high - span.low) / 4.0,
            about=f"Derived: {span.source or 'this probe'} settled it at"
                  f" [{span.low:g}, {span.high:g}].",
        ))

    claimed = {axis.parameter for axis in derived}
    kept = tuple(axis for axis in ENGINES[engine]
                 if axis.parameter is None or axis.parameter not in claimed)
    return _field(count, seed=seed, engine=engine, axes=kept + tuple(derived))


#: How many parameter-dispersed candidates an outcome selection measures before
#: choosing from them. Six times the mosaic asked for, which is a judgement and
#: is written here so it can be argued with: the candidates are already the
#: *best-dispersed* worlds the parameter algorithm can offer, so this is not a
#: search over a haystack — it is asking whether the parameter algorithm's top
#: thirty rank the same way once their corpora are read. Below about four times
#: the count there is nothing for a different selector to disagree about; above
#: it the cost is linear in builds and the disagreement stops growing.
_OUTCOME_POOL = 6


def outcome_field(
    count: int,
    *,
    seed: int = 8128,
    engine: str = "retail",
    pool: int | None = None,
    period: str = "2026-03",
    periods: int = 1,
    incident: bool | None = None,
) -> tuple[Variant, ...]:
    """*count* variants chosen by measuring their corpora, not their parameters.

    ``field`` covers a hypercube and takes the *N* furthest apart in it. That is
    a good algorithm pointed at a proxy: it has never looked at what came out.
    This runs the loop a dataset actually needs — build a pool of candidates
    cheaply, measure the corpora, select on the measurements — using
    ``worldloom.outcomes`` for the measuring and the same
    ``dispersion.farthest_first`` for the choosing.

    **The candidate pool is ``field`` itself**, which is what makes the two
    comparable. Gonzalez's traversal is prefix-consistent, so ``field(30)[:5]``
    *is* ``field(5)`` — the parameter-dispersed mosaic and the outcome-selected
    one are therefore two orderings of one candidate set, and a comparison
    between them isolates the selector rather than confounding it with a
    different generator. ``tools/outcome_selection.py`` runs exactly that
    comparison.

    **Seeds are preserved, indices are not.** ``field`` re-seeds by selection
    position, which is harmless there because nothing about a parameter
    coordinate depends on a seed. Here it would be a lie: a world is measured
    at seed *s* and re-seeding it to *s'* on the way out would hand back a
    corpus nobody read. So a chosen variant keeps the seed it was measured
    under, and only ``index`` — the ``world-NN`` a caller writes it to — is
    renumbered. The cost is that this loses ``field``'s "world *N* uses
    ``seed + N - 1``" property, and losing it is the correct trade: that
    property exists so a mosaic's third world rebuilds without the first two,
    and every variant here still carries its own seed for exactly that.

    **Words are dealt, never selected on**, and the candidates are measured
    with none. ``Variant.vocabulary`` already argues why a vocabulary is not an
    axis: it is dealt from a permuted registry by *position*, which guarantees
    what dispersion only approximates — no two worlds of a mosaic speak the
    same words until the registry runs out. A selection that reordered
    positions while carrying each candidate's position-dealt vocabulary would
    destroy that guarantee, and the first version of this function did exactly
    that: it returned five worlds of which two were ``wholesale_club`` and two
    ``convenience_forecourt``, which is measurably worse than the parameter
    mosaic it was meant to improve on — a vocabulary swap alone moves two
    otherwise identical worlds 0.73 apart in question space, so a repeat is
    close to a repeated world however far apart the physics is.

    So the pool is measured with the vocabulary stripped and the words are
    re-dealt by selection position. That keeps the measurement honest — the
    reading never saw a vocabulary, so re-dealing cannot invalidate it — and it
    is the one respect in which the world handed back is not the world that was
    read.

    Costs one build, one episode run and one compile per candidate — no
    narration, no rendering, nothing on disk. A pool of thirty retail worlds is
    a few seconds; see ``tools/outcome_selection.py``, which prints the figure
    for the machine it ran on rather than this docstring asserting one.
    """
    from dataclasses import replace as _replace

    from . import outcomes, sdk

    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")
    if count == 0:
        return ()
    size = max(count, pool if pool is not None else count * _OUTCOME_POOL)
    candidates = field(size, seed=seed, engine=engine)
    blueprints = [
        _replace(sdk._from_variant(variant), vocabulary_name="")
        for variant in candidates
    ]
    measured = outcomes.pool(
        blueprints, start=period, periods=periods, incident=incident,
        names=[f"candidate-{variant.index:02d}" for variant in candidates],
    )
    chosen = measured.select(count)
    dialects = _vocabularies(engine, seed)
    return tuple(
        _replace(
            candidates[at],
            index=position + 1,
            vocabulary=dialects[position % len(dialects)] if dialects else "",
        )
        for position, at in enumerate(chosen)
    )


def describe(engine: str = "retail") -> dict[str, Any]:
    """What a mosaic varies, without building anything."""
    if engine not in ENGINES:
        raise KeyError(f"unknown engine {engine!r}; known: {sorted(ENGINES)}")
    return {
        "engine": engine,
        "engines": sorted(ENGINES),
        "axes": [
            {"name": axis.name, "low": axis.low, "high": axis.high,
             "about": axis.about, "parameter": axis.parameter}
            for axis in ENGINES[engine]
        ],
        **({"calendars": list(_CALENDARS)}
           if any(a.name == "calendar" for a in ENGINES[engine]) else {}),
        "estates": [e or "none" for e in _ESTATES],
    }


def spread(variants: Sequence[Variant]) -> dict[str, Any]:
    """How unlike each other a mosaic's worlds actually are.

    Reported rather than claimed. A mosaic that returned five near-identical
    worlds would look exactly like one that worked, right up until somebody
    read the corpora — and this project's position on diversity is that it is
    measured, not hoped for.
    """
    if not variants:
        return {"worlds": 0}
    return {
        "worlds": len(variants),
        "headcounts": sorted({v.headcount for v in variants}),
        "spans": sorted({v.span for v in variants}),
        "levels": sorted({v.levels for v in variants}),
        **({"calendars": sorted({v.calendar for v in variants})}
           if any(a.name == "calendar" for a in ENGINES[variants[0].engine]) else {}),
        "estates": sorted({v.estate or "none" for v in variants}),
        "distinct_shapes": len({(v.headcount, v.span, v.levels) for v in variants}),
        "closest_pair": round(min(
            (manhattan(a.coordinates, b.coordinates)
             for i, a in enumerate(variants) for b in variants[i + 1:]),
            default=0.0,
        ), 4),
    }


def register_engine(engine: str, axes: tuple[Axis, ...]) -> None:
    """Register the axes that a mosaic will vary for a vertical.

    Called by domain modules (procurement, future verticals) to define what
    varies in a mosaic of their worlds. Redefinition is refused — every engine
    may appear only once. An engine is registered by only one vertical, so a
    collision is a wiring error rather than a legitimate override.

    Raised rather than silently absorbed if an engine is already known, because
    a duplicate in the registration chain is a wiring error: either the module
    was imported twice, or two domains collided on the same engine name. Neither
    is silent-and-plausible.
    """
    if engine in ENGINES:
        raise KeyError(
            f"engine {engine!r} is already registered. Each engine may appear"
            f" only once; a collision is a wiring error in one of the modules"
            f" calling register_engine."
        )
    ENGINES[engine] = axes


__all__ = ["AXES", "ENGINES", "STRUCTURE", "Axis", "Variant", "describe", "field",
           "outcome_field", "spread", "register_engine"]
