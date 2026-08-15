"""The build-configuration space as a declared thing, so a fleet is planned.

Not to be confused with ``axes.py``, which landed in the same wave and also
speaks of axes: those are the dimensions *one company's figures* are cut along
— division, accident quarter, cost type — where these are the knobs *a fleet of
builds* varies. A member of an axis here is a configuration of the generator;
there it is a division or a quarter.

The measured problem: this repository chooses fleets of builds in two places and
neither can say what it missed.

* ``tools/sweep.py`` — the determinism gate — enumerates the CLI's own
  configuration space, covers it with ``dispersion.halton``, and takes the eight
  furthest apart. Measured on the shipped default (``--seed 8128 -n 8``), those
  eight configurations cover **220 of the 918 pairs** of this module's
  `build_space` — 24%. It has no way to report that, because a Halton point
  knows its coordinates and not the combinations nobody landed on. Thirty
  nightly seeds — 240 configurations, 480 builds — reach 41.4%, and 538 pairs
  remain. One of them is ``archetype=midsize_adi`` with ``periods=3``: the gate
  has never built a multi-period bank, because ``sweep._config`` collapses
  ``periods`` to 1 for every single-episode vertical, citing a CLI refusal that
  no longer exists. A three-quarter bank builds and validates clean today
  (2,526 checks). That is the shape of finding this module exists to surface,
  and no amount of further dispersion produces it — the pair is unreachable
  under that projection however many nights run.
* ``mosaic`` builds *N* companies as unlike each other as the constraints allow,
  and ``mosaic.spread`` reports what varied: the headcounts, the calendars, the
  estates *observed*. Never the combination not observed.

**How this differs from `dispersion` and `mosaic`, honestly. It is a difference
of guarantee, not of quality.**

* ``dispersion.halton`` is a low-discrepancy sequence over a *continuous* cube,
  and its guarantee is a bound on discrepancy. Project it onto a categorical
  axis and a value occupying a sixth of the interval turns up in about a sixth
  of the points — and "about" is the whole problem. There is no *n* at which a
  particular pair is certain to have appeared, and no way to ask which one has
  not.
* ``dispersion.farthest_first`` gives a *relative* guarantee: each pick is as
  far as it can be from the picks before it. Change the pool and every pick
  changes. It has a distance and no vocabulary, so it cannot name a region it
  missed — the same asymmetry `archive` already states against it, one layer up.
* A covering array gives an *absolute* guarantee against a vocabulary the caller
  declared: at strength *t*, every combination of *t* values appears in at least
  one row. That is a stopping condition. "Generate twelve worlds" is a budget;
  "cover every pair" is a target, and `holes` is the work list when it is not
  met yet.

What it is emphatically **not** is a claim that these are better corpora.
Thirty-six rows off a covering array are not more spread out than thirty-six
worlds off a farthest-point traversal — they are usually less so, since nothing
here maximises any distance. They compose in the obvious direction: cover the
categorical axes here, disperse the continuous ones with ``mosaic``.

**The price, stated up front: a covering array has no constraint language.**
Real build configurations exclude each other — ``--incident`` and ``--timeline``
cannot both decide, ``--conversations`` is refused beside ``--actors``, and a
single-episode vertical refuses six of the retail close's flags outright. IPOG
knows none of that and will happily emit a row nobody can build. Two techniques
answer it and both are used here rather than described:

1. **Merge conflicting knobs into one axis.** Two flags that refuse each other
   are one decision with more values than either flag has. `build_space`'s
   ``history`` axis is ``--incident``/``--no-incident``/``--timeline`` merged,
   and ``knowledge`` is ``--conversations``/``--actors``; both exclusions become
   unrepresentable rather than merely unlikely. This is exact and costs nothing
   but a wider axis.
2. **Project, then measure what projection cost.** Where a constraint is between
   *different* axes — an estate on a vertical with no landscape vocabulary — the
   caller collapses the row to what that engine can build, exactly as
   ``sweep._config`` already does, and then calls `holes` on the projected rows.
   That second step is the one nothing here could do before: projection silently
   destroys coverage, and until now the only record of it was a tally of *how
   many* rows collapsed, never *which pairs went with them*.

Constrained IPOG — refusing forbidden tuples inside the construction — is the
real fix for case 2 and is not attempted here. It would be the honest way to put
``facets`` in `build_space`; see that function for the arithmetic on why the
naive alternatives are worse.

Deterministic, and with nothing to be non-deterministic *with*: no ``Rng``, no
clock, no set iteration reaching output. Every ordering is the caller's declared
axis order or `covering`'s stated canonical one.

A pure library — the standard library, `covering`, `archive`, and (only inside
`build_space`, only at call time) the registries that say what the CLI accepts.
No world objects, no ``World``, no CLI import.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

from . import archive, covering

#: Re-exported so a caller that plans a fleet needs one import rather than two.
#: These are `covering`'s types unchanged, not aliases of a parallel vocabulary:
#: a `Row` handed back by `cover` is the same dict `covering.coverage` reads.
Row = covering.Row
Combination = covering.Combination


@dataclass(frozen=True)
class BuildSpace:
    """The axes a fleet of corpora may vary along.

    A thin frozen wrapper over `covering.Parameter`, and thin on purpose: the
    value is in the axes being *declared somewhere* rather than implied by
    whatever a sampler happened to reach. Two fleets that name the same
    `BuildSpace` can be compared; two fleets that each hardcode their own axis
    list cannot, which is the state ``tools/sweep.py`` and ``mosaic`` are in
    today.
    """

    axes: tuple[covering.Parameter, ...]

    def __post_init__(self) -> None:
        if not self.axes:
            raise ValueError(
                "a build space needs at least one axis; an empty space reports"
                " 100% coverage of nothing, which is the one reading a coverage"
                " number must never be able to give"
            )
        names = [axis.name for axis in self.axes]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            # `covering` refuses this too, but only when an array is actually
            # built. Refused at declaration instead, because a duplicated axis
            # makes `exhaustive` and `size_at` wrong immediately — they multiply
            # widths — and a caller who only ever prints those numbers would
            # never reach the construction that would have told them.
            raise ValueError(
                f"axis name(s) {', '.join(repeated)} appear more than once; a row"
                " is keyed by name, so two axes sharing one collapse into a single"
                " column and every combination between them reports as covered"
            )

    @property
    def names(self) -> tuple[str, ...]:
        """Axis names, in declared order."""
        return tuple(axis.name for axis in self.axes)

    @property
    def exhaustive(self) -> int:
        """How many configurations the space describes — the full product.

        The number `cover` is measured against, and the reason to bother: it
        grows multiplicatively while a pairwise array grows with the product of
        the two *widest* axes alone.
        """
        return math.prod(len(axis.values) for axis in self.axes)

    def size_at(self, strength: int) -> int:
        """How many *strength*-way combinations exist — the denominator of
        `coverage`, and a very different number from `exhaustive`."""
        return sum(
            math.prod(len(self.axes[j].values) for j in subset)
            for subset in itertools.combinations(range(len(self.axes)), strength)
        )

    def axis(self, name: str) -> covering.Parameter:
        """The axis called *name*, or `KeyError` listing the ones there are."""
        for axis in self.axes:
            if axis.name == name:
                return axis
        raise KeyError(f"no axis {name!r}; this space has {', '.join(self.names)}")

    def select(self, names: Sequence[str]) -> BuildSpace:
        """The subspace over *names*, in the order given.

        The reading that makes a fleet's coverage number fair. A fleet that
        never touches five of twelve axes scores terribly against the whole
        space for a reason that is true but uninformative — it is not that its
        selection was poor, it is that those knobs have no front door in the
        tool that built it. Scoring it against the axes it *does* vary separates
        "chose badly" from "cannot reach"; `unvaried` names the other half.
        """
        return BuildSpace(tuple(self.axis(name) for name in names))

    def row(self, **values: str) -> Row:
        """A validated configuration, or `ValueError` naming what is wrong.

        Rows reaching `coverage` and `holes` are deliberately forgiving — an
        unknown value there is a coverage question rather than an error, since
        rows arrive from generators that legitimately know more or less than the
        space does. That forgiveness is exactly wrong when a caller is *writing*
        a row by hand: a typo'd value would silently cover nothing and read as a
        hole in whatever built it. So the strict door is here and the lenient
        one stays where the measuring happens.
        """
        for name, value in sorted(values.items()):
            axis = self.axis(name)
            if value not in axis.values:
                raise ValueError(
                    f"{value!r} is not a value of axis {name!r};"
                    f" expected one of {', '.join(axis.values)}"
                )
        missing = [name for name in self.names if name not in values]
        if missing:
            raise ValueError(
                f"row is missing axis/axes {', '.join(missing)}; a partial row"
                " covers no combination that reaches a missing axis, which reads"
                " as a hole rather than as the omission it is"
            )
        # Keyed in declared axis order, which is the one ordering of a row
        # somebody stated on purpose — `covering.Row` says the same.
        return {name: values[name] for name in self.names}

    def __repr__(self) -> str:
        # Spelled out rather than inherited: the default carries a memory
        # address, and this repository diffs its own output.
        axes = " x ".join(f"{a.name}({len(a.values)})" for a in self.axes)
        return f"BuildSpace({axes}: {self.exhaustive} configurations)"


# ---------------------------------------------------------------------------
# Planning a fleet, and reading what one covered
# ---------------------------------------------------------------------------
#
# Every function below takes the space *first*, where `covering`'s take it
# second. The flip is deliberate and it is a small tax worth paying: here the
# space is the subject — you ask a space to be covered, and you ask it what a
# fleet missed — and a module whose argument order changed halfway through would
# be worse. Getting it backwards raises rather than silently answering, since a
# `BuildSpace` has no `.get` and a list of rows has no `.axes`.


def cover(space: BuildSpace, *, strength: int = 2) -> tuple[Row, ...]:
    """A fleet in which every *strength*-way combination of axis values appears.

    The stopping condition this module exists for. At ``strength=2`` the
    returned rows are within a few of the shortest pairwise array that exists
    over the space, and the floor is the product of the two widest axes — so
    `build_space`, whose two widest are both 6, cannot be covered pairwise in
    fewer than 36 rows however clever the construction. It takes 39.

    A pure function of the space: no ``Rng``, no clock. Two calls return the
    same rows in the same order, which is what lets a fleet's plan be a
    checked-in artifact rather than a run to be repeated.
    """
    return covering.covering_array(space.axes, strength=strength)


def coverage(space: BuildSpace, rows: Sequence[Row], *, strength: int = 2) -> float:
    """The fraction in ``[0, 1]`` of *strength*-way combinations *rows* covers.

    Invariant to the order of *rows*: it is a question about two sets. A row
    that omits an axis, or carries a value the axis does not declare, covers no
    combination reaching that axis rather than raising — see `BuildSpace.row`
    for why the strict door is elsewhere.
    """
    return covering.coverage(rows, space.axes, strength=strength)


def holes(
    space: BuildSpace, built: Sequence[Row], *, strength: int = 2
) -> tuple[Combination, ...]:
    """The combinations *built* never produced, sorted canonically.

    The actionable half of `coverage`, and the whole reason this module is not
    just `cover`. A fleet is almost never a covering array — it is whatever
    ``tools/sweep.py`` selected last night, or the twelve corpora somebody
    happened to build — and the question worth asking of it is not "how spread
    out was it" but "what has never been built". That question had no answer
    here before: `mosaic.spread` reports the values observed and a Halton point
    knows only its own coordinates.

    Pass rows in whatever shape the fleet actually has, including partial ones.
    A configuration that was *projected* — an estate dropped because the engine
    has no landscape vocabulary — should carry the value it was projected to,
    not the one that was asked for, because the pair the fleet covered is the
    pair it built.
    """
    return covering.holes(built, space.axes, strength=strength)


def unvaried(space: BuildSpace, built: Sequence[Row]) -> tuple[str, ...]:
    """The axes *built* never moved at all, in declared order.

    A different finding from a hole and a much blunter one. A hole says a pair
    was missed; this says a knob was never turned — which is usually not a
    selection failure but a *front door* failure, a flag the tool that built the
    fleet has no way to set. Measured on the shipped determinism sweep, five of
    `build_space`'s twelve axes come back here — ``policies``, ``storyline``,
    ``genome``, ``eval_density``, ``knowledge``, none of which that tool has an
    axis for — and reading its 698 holes without that fact first is reading
    several hundred consequences of five causes.

    An axis no row mentions at all counts as unvaried, which is the same finding
    arrived at by omission rather than by constancy.
    """
    return tuple(
        axis.name
        for axis in space.axes
        # `set` for a count only, never iterated — no ordering reaches output.
        if len({row.get(axis.name) for row in built} - {None}) <= 1
    )


# ---------------------------------------------------------------------------
# The archive over a space
# ---------------------------------------------------------------------------


def archive_of(space: BuildSpace, *, over: Sequence[str] | None = None) -> archive.Archive:
    """An archive whose niches are this space's configurations.

    Each axis becomes an `archive.Axis` with the same name and the same values
    as buckets, so a `Row` *is* a niche coordinate (`niche_of` converts) and a
    fleet fills the archive by considering one candidate per build.

    What this adds over `holes`, which also reports what is missing: an archive
    carries a **fitness**, so when several builds land in one niche it keeps the
    best rather than the first, and `Archive.elites` is then "the best corpus
    per configuration" — a champion list. `holes` answers a question about
    *t*-way combinations; this answers one about whole cells, and keeps
    something in each.

    **Read `over` before using this on the real space.** `build_space` has
    3,732,480 configurations, so `archive_of(build_space())` is an archive with
    3,732,480 niches, `fill()` of roughly zero forever, and a `holes()` nobody
    can read — precisely the failure `archive.Archive.capacity` warns about. The
    axes worth archiving over are the two or three a reader would name, and
    `over` selects them: ``archive_of(space, over=("archetype", "messiness"))``
    is 24 niches and a report that fits on a screen.
    """
    chosen = space if over is None else space.select(over)
    return archive.Archive([
        archive.Axis(name=axis.name, buckets=axis.values) for axis in chosen.axes
    ])


def niche_of(
    space: BuildSpace, row: Row, *, over: Sequence[str] | None = None
) -> archive.Coordinates:
    """*row* as coordinates for the archive `archive_of` builds under the same
    *over*.

    Kept beside `archive_of` and taking the same argument, because the pairing
    is the invariant: an archive built over three axes and a coordinate built
    over twelve is a `ValueError` from `Archive.consider`, and the two calls
    that must agree should be reading from one place.
    """
    chosen = space if over is None else space.select(over)
    missing = [name for name in chosen.names if name not in row]
    if missing:
        raise ValueError(
            f"row has no value for {', '.join(missing)}, so it has no niche."
            " A projected configuration should carry what it was projected to;"
            " a genuinely absent axis means this row belongs to a different space"
        )
    return tuple(row[name] for name in chosen.names)


# ---------------------------------------------------------------------------
# The space this repository actually has
# ---------------------------------------------------------------------------


#: How many consecutive episodes a fleet varies over. Levels rather than a
#: range, because a covering array needs a finite vocabulary and because the
#: interesting distinctions are ordinal and few: 1 is the default and the only
#: shape with no recurrence at all; 3 is the smallest build with supersession
#: and a cross-period question; 12 is a year, which is where seasonality, a
#: trend and the twelve-copies-of-one-shape problem all first appear. The
#: shipped determinism sweep has never built the third one — see this module's
#: docstring.
_PERIODS: tuple[str, ...] = ("1", "3", "12")


def build_space() -> BuildSpace:
    """The axes ``worldloom build`` actually accepts, read from the registries.

    Derived at call time and never cached, for ``tools/sweep.py``'s reason: a
    hand-written list of archetypes or locales is stale the moment somebody
    registers one, and a coverage number that silently stops covering a new
    value is worse than no number, because it still reports a percentage. The
    four axes that are *not* registry-derived — ``history``, ``periods``,
    ``genome``, ``eval_density`` — are literal tuples in ``cli.py`` with nothing
    that registers into them, and each names its flag below so a reader can
    check it against the source.

    **Two axes are merges, and that is how an exclusion is expressed here.**
    ``history`` is ``--incident``/``--no-incident``/``--timeline`` as one
    decision, because the CLI refuses a forced incident beside a density that
    schedules its own; ``knowledge`` is ``--conversations``/``--actors``,
    refused together because two producers appending to one knowledge ledger is
    two accounts of who knew what. Merged, the contradictions cannot be written
    down. Left as four independent booleans they would be rows IPOG emits and
    nobody can build.

    **Three axes are constrained *against* ``archetype``, and this space does
    not express it.** A single-episode vertical — everything but the two retail
    archetypes — refuses ``--incident``, ``--timeline``, ``--conversations``,
    ``--actors`` and a non-``standard`` ``--eval-density`` outright
    (``cli.py``'s single-episode refusal block), and procurement has no entry in
    ``landscape.LANDSCAPES`` so it refuses ``--estate``. Every one of those
    axes therefore carries the value that *is* legal everywhere as its first —
    ``unforced``, ``none``, ``standard``, ``none`` — so a caller projecting a
    row for one of those engines has somewhere honest to project it *to*, and
    the pairs that projection destroys are then exactly what `holes` reports.
    Encoding the constraint here instead would mean either a constrained IPOG
    (the real answer, not attempted) or an ``archetype``-keyed axis set, which
    is a different space per engine and no longer one thing to compare fleets
    against.

    **``--facet`` is deliberately absent, with arithmetic.** Seven facet
    dimensions would be seven more axes and 6,480 more configurations, but six
    of their cross-dimension pairs are contradictions ``facets.resolve``
    refuses — there is no listed mutual, no premium monopolist — and a pairwise
    array is *obliged* to emit all six. The alternative, one ``facets`` axis
    carrying ``facets.combinations()``, is 3,720 values, and a pairwise array
    over an axis that wide is at least 3,720 rows: the exhaustive product of
    that one axis, wearing a covering array's name. Neither is worth shipping.
    A caller who wants faceted coverage should cover this space, cross each row
    with a facet assignment, and use `holes` on what survives ``facets.resolve``.
    """
    from . import archetypes, locales, messiness, policies
    from .scenarios import ACCESS_LEVELS

    return BuildSpace((
        # `--archetype`. The engine is *implied* by the archetype rather than
        # being an axis of its own, which is what the CLI does — there is no
        # `--engine` flag — and it removes the largest exclusion in the space in
        # passing: an engine axis crossed with an archetype axis is 4x6 cells of
        # which 6 are buildable, so 75% of every pair reaching either one would
        # be a row nobody can build.
        covering.Parameter("archetype", tuple(archetypes.available())),
        # `--locale`, plus its own absence. Omitting it is not the same build as
        # naming `australia`: the flag rides the recipe, and every world built
        # before locales existed carries none.
        covering.Parameter("locale", ("none", *sorted(locales.LOCALES))),
        # `--estate`. "none" is the engine's own nine nodes and a legitimate
        # world, not a skipped configuration.
        covering.Parameter("estate", ("none", "small", "medium", "large")),
        # `--policies`. `policies.LEVELS` already begins with "none".
        covering.Parameter("policies", tuple(policies.LEVELS)),
        # `--messiness`. `pristine` is the flag's default *and* a nameable
        # value that writes nothing, so it stands for the omitted flag too and
        # the axis needs no extra "none" — unlike `locale`, where omission and
        # any named value differ.
        covering.Parameter("messiness", tuple(sorted(messiness.PROFILES))),
        # `--access`: how much of the corpus is gated. `standard` is the flag's
        # default and an identity that records nothing, so it stands for the
        # omitted flag the way `pristine` does one line up — and it is the
        # value to project a row to for an engine whose org module declares no
        # STRICT_ACCESS table, since `open`/`strict` are refused rather than
        # ignored there (`scenarios.AccessProfile`). The tuple is imported
        # rather than restated: `ACCESS_LEVELS` is the one literal, and the
        # CLI's `--access` choices read the same name, so this axis cannot
        # drift from the flag the way the hand-synced axes above can.
        covering.Parameter("access", ACCESS_LEVELS),
        # `--incident` / `--no-incident` / `--timeline`, merged. "unforced" is
        # the CLI's own default — neither flag given, the seed and the lore
        # decide — and it is the only value a single-episode vertical accepts.
        covering.Parameter(
            "history",
            ("unforced", "incident", "no_incident", "quiet", "steady", "turbulent"),
        ),
        covering.Parameter("periods", _PERIODS),
        # `--vary-incidents`: the same failure retold monthly, or a rotation of
        # storylines across periods. Inert on a single-episode vertical rather
        # than refused, so a projection here is to "fixed".
        covering.Parameter("storyline", ("fixed", "varied")),
        # `--section-omission` and `--variant-bias`, the two mechanisms of the
        # structural genome, as one axis of four states. Two axes would be the
        # more literal encoding and a worse one: they are not independent
        # claims about a corpus, they are two ways of answering "does every
        # document of a type look the same", and a reader comparing fleets wants
        # the four states rather than a 2x2 they have to recombine.
        covering.Parameter("genome", ("authored", "omission", "variant_bias", "both")),
        covering.Parameter("eval_density", ("low", "standard", "high")),
        # `--conversations` / `--actors`, merged: refused together, because two
        # producers appending to one knowledge ledger is two accounts of who
        # knew what. `agent` is not a value — it is an interactive protocol
        # rather than a build configuration, and a fleet cannot take forty turns
        # per row.
        covering.Parameter("knowledge", ("none", "conversations", "actors")),
        # Which front door states the company. Both are supported build paths
        # resolving through different code, so a fleet that only ever drives one
        # covers half the door — `tools/sweep.py`'s own argument, kept.
        covering.Parameter("surface", ("flags", "spec")),
    ))


__all__ = [
    "BuildSpace",
    "Combination",
    "Row",
    "archive_of",
    "build_space",
    "cover",
    "coverage",
    "holes",
    "niche_of",
    "unvaried",
]
