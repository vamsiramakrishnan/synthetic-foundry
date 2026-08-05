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


#: What a mosaic varies. Seven axes, and the count is not arbitrary: the Halton
#: sequence's high bases correlate, so past roughly a dozen dimensions it stops
#: covering better than a grid. These are chosen to be the things a *reader*
#: would name if asked how two corpora differed — not the things easiest to vary.
AXES: tuple[Axis, ...] = (
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
    Axis("calendar", 0, len(_CALENDARS) - 1e-9, integral=False,
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
         about="How far a unit's revenue lands from budget. Decides whether the"
               " corpus is about a bad month or an ordinary one."),
)

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

    def role_table(self, engine: str = "retail") -> tuple[tuple[str, str, str, str | None], ...]:
        return to_rows(from_shape(
            functions=self.functions, headcount=self.headcount,
            span=self.span, levels=self.levels, engine=engine,
        ))

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "seed": self.seed,
            "headcount": self.headcount,
            "span": self.span,
            "levels": self.levels,
            "calendar": self.calendar,
            "functions": list(self.functions),
            "physics": {name: span.as_dict() for name, span in sorted(self.overrides.items())},
        }

    def summary(self) -> str:
        return (f"{self.headcount} people, spans of {self.span}, {self.levels} levels,"
                f" {self.calendar} calendar")


def _candidate(index: int, coordinates: Sequence[float], *, seed: int) -> Variant | None:
    """One variant from one point in the unit cube, or ``None`` if unbuildable."""
    values = {axis.name: axis.at(coordinate)
              for axis, coordinate in zip(AXES, coordinates, strict=True)}

    overrides: dict[str, Span] = {}
    for axis in AXES:
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
        calendar=_CALENDARS[int(values["calendar"])],
        overrides=overrides,
        coordinates=tuple(coordinates),
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
    pool: int = _POOL,
) -> tuple[Variant, ...]:
    """*count* variants, covered then chosen for maximum dispersion.

    Every world gets a seed derived from the base by index, so a mosaic's third
    world is reproducible without rebuilding the first two — and so two mosaics
    of different sizes agree on the worlds they share.
    """
    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")
    if count == 0:
        return ()

    feasible: list[Variant] = []
    points: list[tuple[float, ...]] = []
    for offset, coordinates in enumerate(halton(len(AXES), pool)):
        variant = _candidate(len(feasible), coordinates, seed=seed + len(feasible))
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
        )
        for position, at in enumerate(chosen)
    )


def describe() -> dict[str, Any]:
    """What a mosaic varies, without building anything."""
    return {
        "axes": [
            {"name": axis.name, "low": axis.low, "high": axis.high,
             "about": axis.about, "parameter": axis.parameter}
            for axis in AXES
        ],
        "calendars": list(_CALENDARS),
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
        "calendars": sorted({v.calendar for v in variants}),
        "distinct_shapes": len({(v.headcount, v.span, v.levels) for v in variants}),
        "closest_pair": round(min(
            (manhattan(a.coordinates, b.coordinates)
             for i, a in enumerate(variants) for b in variants[i + 1:]),
            default=0.0,
        ), 4),
    }


__all__ = ["AXES", "Axis", "Variant", "describe", "field", "spread"]
