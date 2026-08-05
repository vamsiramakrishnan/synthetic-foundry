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
        return ", ".join(parts)


def _candidate(
    index: int, coordinates: Sequence[float], *, seed: int, engine: str = "retail",
) -> Variant | None:
    """One variant from one point in the unit cube, or ``None`` if unbuildable."""
    axes = ENGINES[engine]
    values = {axis.name: axis.at(coordinate)
              for axis, coordinate in zip(axes, coordinates, strict=True)}

    overrides: dict[str, Span] = {}
    for axis in axes:
        if axis.parameter is None:
            continue
        engine_span = DEFAULT.span(axis.parameter)
        centre = values[axis.name]
        # A band around the sampled point rather than the point itself. A span
        # whose ends are equal is a constant, and a world whose every figure is
        # the same number is not a world — the width is the engine's own,
        # carried across so the *variation within* a corpus stays what the
        # engine intended while the *level* moves.
        half = (engine_span.high - engine_span.low) / 2.0
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
        estate=_ESTATES[int(values["estate"])],
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

    feasible: list[Variant] = []
    points: list[tuple[float, ...]] = []
    for coordinates in halton(len(ENGINES[engine]), pool):
        variant = _candidate(len(feasible), coordinates,
                             seed=seed + len(feasible), engine=engine)
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


__all__ = ["AXES", "ENGINES", "Axis", "Variant", "describe", "field", "spread"]
