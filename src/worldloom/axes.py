"""What a company is cut by, declared per industry instead of assumed.

Not to be confused with ``spaces.BuildSpace.axes``, which landed in the same
wave and means something else entirely: the axes *a fleet of builds* varies
along — archetype, locale, periods — where these are the axes *one company's
figures* are cut along. A reader who greps for "axis" will find both. The test
is what a member of the axis is: a configuration of the generator there, a
division or an accident quarter here.

The measured problem. ``archetypes.Archetype.units`` is a hand-authored
``tuple[UnitSpec, ...]`` and ``UnitSpec`` is ``(key, name, kind, share,
categories, site_formats)``. Print the six shipped archetypes and the dimension
*names* are industry-appropriate — a bank has Residential Mortgages, an insurer
has Motor and Home, a contractor has Subcontract Labour — while the dimension
*structure* is identical in all of them. Three declared fields, five generated
dimensions (``unit``, ``category``, ``format``, ``site``, ``region``), nested
the same way, additive at every level, in a supermarket, a deposit-taking bank,
a long-tail insurer and a civil contractor alike.

A grocer really is cut by category and store. A bank is cut by book, portfolio
and origination vintage. A long-tail insurer is cut by class of business and
*accident quarter* — and this repository already built that axis, in
``episodes.CohortSpec``, because reserving could not be expressed without it. A
contractor is cut by project and cost type, and has no merchandise category at
all. Forcing every one of them through a supermarket's shape is what makes
every company the same company underneath, whatever its words.

The schema is already visibly straining, and it says so in the data rather than
in a comment. Of the 19 units the registry declares, **two carry no categories
and four carry no site formats** — ``midsize_adi``'s treasury desk and
``midsize_general_insurer``'s investment book among them — because a treasury
desk has no branches and an investment book has no classes of business. An
empty tuple where a dimension does not apply is the schema saying it is the
wrong schema: the honest statement is not "this unit has zero sites", it is
"this unit is not cut that way, it is cut by maturity bucket instead", and
``UnitSpec`` has nowhere to put that sentence.

So this module declares, per industry, **which axes a company has** — with the
four things an axis needs to be more than a label:

1. **What its members are** (``source``), in a closed vocabulary naming the
   seam that supplies them, plus ``populated_by``, the module a reader can
   open. Same shape and same argument as ``factkinds.FactKind``'s ``domain`` +
   ``generated_by``: documentation, not dispatch.
2. **Whether measures roll up along it** (``rollup``) — and, crucially, *by
   which invariant*. Not a boolean: ``episodes.py`` already distinguishes
   ``sums-to`` (one period decomposed across *subjects*) from ``rolls-up-to``
   (one subject decomposed across *cohort periods*) and warns that a check
   looking on the wrong axis "passes vacuously". An axis knows which of the two
   it is; nothing else does. ``""`` is the third case and it is real: a
   valuation date restates the same cohort's ultimate rather than holding a
   share of it, so amounts along that axis do not decompose at all.
3. **How deep it nests** (``nests_under``), a forest rather than a fixed
   three-level ladder, so ``unit → format → store`` is expressible and so is
   ``segment → project → project_vintage``.
4. **Which lines of business it cuts** (``applies_to``). This is the empty
   tuple's replacement. A branch axis that applies to retail and business
   banking and not to treasury states, positively, what ``site_formats=()``
   could only state by absence — and a treasury desk gets ``maturity_bucket``
   in its place rather than three empty tuples.

**The grammar is reused, not reinvented.** A cohort axis carries an actual
``episodes.CohortSpec``, not a copy of its three numbers: the shipped
accident-quarter axis here *is* ``CohortSpec(name="accident_quarter", count=4,
spacing_months=3, lag_months=3)``, the same value ``examples/packs/
longtail-insurer.json`` declares and ``generators/reserving.py`` generates
against. ``as_invariant`` emits an ``episodes.Invariant`` in the vocabulary
``factkinds.INVARIANT_HEADS`` closes, and ``subject_type`` is validated against
``episodes.FactKindSpec``'s own ``Literal`` read off the model field, so the two
cannot drift. Nothing here declares a fact kind; fact kinds have a mechanism
already, and a second one would be the defect this module is about.

**The honesty rule, one layer along from ``probe.MEASURES``.** That tuple's
comment states the rule for measures: a measure naming a kind no generator
mints "produces a fact about a person that nothing in the corpus can ever be
compared against". The same failure arrives here as an axis nothing generates
*members* for — a company declared to be cut by project, in a corpus with no
projects, so every document that cites the cut cites nothing. So the library
partitions: ``Shape.populated`` is what the engine enumerates today,
``Shape.unpopulated`` is what it does not, ``lint`` names every one of the
second kind with the generator it would need, and neither set is allowed to be
quiet about the other. Eleven of the thirty-five axes declared below are
unpopulated, and each is listed as a gap rather than shipped as a capability.

**Nothing changes by default.** ``LEGACY`` is the five-axis cut the engine
performs today, and it is what ``for_company`` returns for an industry with no
declared shape — so an unregistered pack's world is described exactly as it is
built. No generator, compiler or renderer imports this module; it describes the
estate, it does not build one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

from . import factkinds
from .episodes import CohortSpec, FactKindSpec, Invariant

if TYPE_CHECKING:  # pragma: no cover
    from .archetypes import Archetype

__all__ = [
    "Axis",
    "LEGACY",
    "Rollup",
    "Shape",
    "Source",
    "as_cohorts",
    "as_invariant",
    "declared",
    "for_company",
    "known_lines",
    "library",
    "lint",
    "register",
    "shape_of",
]


#: Where an axis's members come from. Closed for ``ConstraintKind``'s reason: a
#: source the engine has no seam for is a claim wearing a schema's clothes, and
#: the one value that means "no seam" has to be spelled out rather than left as
#: an empty string somebody forgot to fill in.
#:
#: - **units** / **categories** / **site_formats**: the three fields
#:   ``archetypes.UnitSpec`` declares, read by ``generators/hierarchy.py``.
#: - **sites**: the ``count`` sites ``hierarchy.generate`` mints *inside* each
#:   format. Distinct from ``site_formats`` on purpose — the format is a
#:   declared member set of size 1-2 and the stores are a generated member set
#:   of size 120, they nest, and the schema flattens them into one field.
#: - **regions**: ``locales.Locale.regions``, cycled onto every site.
#: - **cohort**: an ``episodes.CohortSpec`` — an origin axis carried in the
#:   fact's own ``period``.
#: - **supersession**: the *observation* axis, carried in ``valid_from`` and the
#:   supersession chain rather than in any member set. Its own value because it
#:   is its own mechanism: a cohort axis can be enumerated ("which four accident
#:   quarters are in view"), and this one can only be walked, which is exactly
#:   why ``prior_in_cohort`` had to exist beside ``prior``.
#: - **roster** / **estate**: people, and services/systems.
#: - **none**: nothing populates this axis. The honest value, and the one the
#:   lint reports on.
Source = Literal[
    "units", "categories", "site_formats", "sites", "regions",
    "cohort", "supersession", "roster", "estate", "none",
]

#: How a measure rolls up along an axis, named by the invariant that checks it.
#:
#: Two of ``factkinds.INVARIANT_HEADS`` and the empty string, and the choice
#: between the first two is not stylistic. ``episodes.Invariant``'s own
#: docstring: ``sums-to`` "decomposes one period across *subjects*", while
#: ``rolls-up-to`` "decomposes one subject across *cohort periods*, and a check
#: that conflated them would look for the breakdown on the wrong axis and pass
#: vacuously". An axis is exactly the thing that knows which it is.
#:
#: ``""`` means amounts do not decompose along this axis at all — the axis
#: classifies rather than partitions. A valuation date is the shipped example: a
#: later valuation *restates* an accident quarter's ultimate, it does not hold a
#: share of it, so summing across valuations double-counts the whole book.
Rollup = Literal["sums-to", "rolls-up-to", ""]

#: ``episodes.FactKindSpec.subject_type``'s own vocabulary, read off the model
#: field rather than retyped. Retyping it would work today and drift the first
#: time a subject type is added, and the drift would be silent: a shape naming a
#: subject type the fact grammar does not have produces facts nothing scopes.
SUBJECT_TYPES: frozenset[str] = frozenset(
    get_args(FactKindSpec.model_fields["subject_type"].annotation)
)


@dataclass(frozen=True)
class Axis:
    """One way a company's performance is cut."""

    name: str
    """The axis's key, lowercase. A cohort axis's name is also the name
    ``episodes.FactKindSpec.cohort`` addresses it by, which is why ``lint``
    refuses a cohort axis whose ``CohortSpec.name`` disagrees with it."""

    label: str
    """What a person calls this cut, in a heading or a question."""

    source: Source
    populated_by: str = ""
    """The module that mints this axis's members, as a path a reader can open.
    Empty exactly when ``source`` is ``"none"``. Documentation, not dispatch —
    ``factkinds.FactKind.generated_by``'s rule, for the same reason: a registry
    that resolved this to a callable would be a second dispatch table beside the
    generators, and the two would disagree the first time one moved."""

    nests_under: str = ""
    """The axis this one sits inside, or ``""`` for a cut of the company
    itself. A forest rather than a fixed ladder: a store sits inside a format
    which sits inside a unit, and today's schema can only say both sit inside
    the unit."""

    rollup: Rollup = "sums-to"

    subject_type: str = "any"
    """Which ``episodes.FactKindSpec.subject_type`` a fact cut this way carries.

    ``"any"`` is not a shrug in two places and both are findings rather than
    choices: the fact grammar's ``Literal`` has no ``site`` and no ``region``,
    while ``generators/finance.py`` mints ``financial.revenue.actual`` against
    ``site.id`` on every build. Recorded here so the gap is visible from the
    axis rather than only from the generator."""

    applies_to: frozenset[str] = frozenset()
    """The ``UnitSpec.kind`` values this axis cuts. Empty means every line of
    business the company runs.

    This field is what replaces the empty tuple. ``midsize_adi`` declares
    ``site_formats=()`` on its treasury unit, which reads as "this desk has zero
    branches" and means "a desk is not cut by branch"; those are different
    claims and only the second is true. Stating the applicability positively
    also makes the *absence* checkable: a company whose every line of business
    falls outside an axis simply does not have that axis, which is what
    ``for_company`` computes."""

    cohort: CohortSpec | None = None
    """When this axis is an origin cohort, the ``episodes.CohortSpec`` itself.

    Carried rather than copied. Restating ``count``/``spacing_months``/
    ``lag_months`` as three fields here would be a second declaration of an axis
    the episode grammar already owns, and the two would disagree about how many
    accident quarters are in view — which is a silently different triangle, not
    an error.

    Set on a ``source="none"`` axis too, and that is not a contradiction: a grid
    nothing mints cells for yet still has a stated geometry, and the three
    numbers are precisely what the generator that closes the gap would need."""

    about: str = ""
    """Why a company of this kind is cut this way, in a sentence or two."""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("an axis needs a name")

    @property
    def populated(self) -> bool:
        """Whether the engine enumerates this axis's members today."""
        return self.source != "none"

    def cuts(self, line: str) -> bool:
        """Whether this axis cuts a line of business of kind *line*."""
        return not self.applies_to or line in self.applies_to


@dataclass(frozen=True)
class Shape:
    """The axes a particular company has, and where they came from."""

    industry: str
    axes: tuple[Axis, ...] = ()

    declared: bool = True
    """False when no industry registered a shape and ``LEGACY`` was substituted.

    Reported rather than hidden, and it is the difference between "this business
    is cut these five ways" and "nobody has said how this business is cut, so it
    got the supermarket's". A caller that cannot tell those apart will publish
    the second as the first."""

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for axis in self.axes:
            if axis.name in seen:
                # Refused rather than linted, for ``columns.Sheet``'s reason: a
                # duplicate does not produce a wrong shape, it produces a shape
                # whose lookups and whose nesting chain disagree about how many
                # axes there are.
                raise ValueError(
                    f"shape {self.industry!r} declares axis {axis.name!r} twice"
                )
            seen.add(axis.name)

    # -- lookups ---------------------------------------------------------

    def get(self, name: str) -> Axis | None:
        return next((axis for axis in self.axes if axis.name == name), None)

    def names(self) -> tuple[str, ...]:
        return tuple(axis.name for axis in self.axes)

    @property
    def populated(self) -> tuple[Axis, ...]:
        """The axes the engine enumerates members for today."""
        return tuple(axis for axis in self.axes if axis.populated)

    @property
    def unpopulated(self) -> tuple[Axis, ...]:
        """The axes nothing populates — declared, and inert until something does."""
        return tuple(axis for axis in self.axes if not axis.populated)

    def for_line(self, line: str) -> tuple[Axis, ...]:
        """The axes that cut a line of business of kind *line*.

        The question ``UnitSpec`` cannot answer. "What is a treasury desk cut
        by" reads as "nothing" off ``categories=()`` and ``site_formats=()``,
        and reads as "book and maturity bucket" here."""
        return tuple(axis for axis in self.axes if axis.cuts(line))

    # -- structure -------------------------------------------------------

    def chain(self, name: str) -> tuple[str, ...]:
        """The nesting chain from the outermost axis down to *name*.

        Stops at an unknown or repeated parent rather than looping: ``lint``
        reports both, and a structural reading must not hang on a shape it is
        being asked to describe.
        """
        walked: list[str] = []
        current = name
        while current:
            if current in walked:
                break
            walked.append(current)
            axis = self.get(current)
            if axis is None:
                break
            current = axis.nests_under
        return tuple(reversed(walked))

    def depth(self) -> int:
        """The longest nesting chain. Today's engine is 3 (unit → format → site)."""
        return max((len(self.chain(name)) for name in self.names()), default=0)

    def signature(self) -> tuple[tuple[str, ...], ...]:
        """The shape's structure with its *words* removed, sorted.

        One entry per axis: the source, the source of its parent, the roll-up
        invariant, and whether anything populates it. Names are deliberately
        excluded — calling a bank's second cut a "portfolio" and a grocer's a
        "category" is a vocabulary difference, and a headline number that
        counted renames as structural discrimination would be measuring its own
        thesaurus. Two shapes with the same signature are cut the same way in
        different words; two with different signatures are cut differently.
        """
        rows = []
        for axis in self.axes:
            parent = self.get(axis.nests_under)
            rows.append((
                axis.source,
                parent.source if parent is not None else "",
                axis.rollup,
                "populated" if axis.populated else "unpopulated",
            ))
        return tuple(sorted(rows))


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------


def lint(shape: Shape | Sequence[Axis]) -> list[str]:
    """Findings an author should read before a shape reaches anything.

    Same contract as ``columns.lint`` and ``doctypes.lint``: a list of strings,
    each naming a place where what was declared and what the engine will do
    diverge, and nothing here raises. The construction refusals on ``Axis`` and
    ``Shape`` cover what makes a shape incoherent as a *value*; everything below
    is a shape that constructs fine and describes a company that does not exist.
    """
    axes = tuple(shape.axes) if isinstance(shape, Shape) else tuple(shape)
    where = shape.industry if isinstance(shape, Shape) else "axes"
    findings: list[str] = []
    present = {axis.name: axis for axis in axes}
    lines = known_lines()

    for index, axis in enumerate(axes):
        at = f"{where}.axes[{index}] ({axis.name!r})"

        # -- the honesty rule, from `probe.MEASURES`' comment ---------------
        if axis.source == "none":
            findings.append(
                f"{at}: declared, and nothing populates its members. A company"
                " cut this way in a corpus with no members on the axis produces"
                " documents that cite the cut and state nothing against it —"
                " `probe.MEASURES`' rule ('carried, cited, and inert') arriving"
                " at the dimension instead of the figure. Either a generator"
                " mints members and `populated_by` names it, or this is a gap"
                " and should be read as one."
            )
        elif not axis.populated_by:
            findings.append(
                f"{at}: source is {axis.source!r} but `populated_by` is empty."
                " The two fields are one claim stated twice — which seam, and"
                " which module — and a reader who cannot open the module has"
                " only the claim."
            )

        # -- the roll-up ---------------------------------------------------
        if axis.rollup and axis.rollup not in factkinds.INVARIANT_HEADS:
            findings.append(
                f"{at}: rolls up by {axis.rollup!r}, which is not in the closed"
                " invariant vocabulary"
                f" ({', '.join(sorted(factkinds.INVARIANT_HEADS))}). An"
                " invariant `episodes.py` cannot derive a check from is a rule"
                " nothing enforces."
            )
        # `sums-to` on a cohort axis is the vacuous-pass `episodes.Invariant`
        # warns about: it looks for the breakdown across subjects, a grid
        # decomposes across cohort periods, so the check finds no children and
        # succeeds having compared nothing.
        if axis.cohort is not None and axis.rollup == "sums-to":
            findings.append(
                f"{at}: is a cohort axis rolling up by 'sums-to'. That check"
                " decomposes one period across *subjects*; a grid decomposes"
                " one subject across *cohort periods*, so it would find no"
                " children and pass having compared nothing. Use 'rolls-up-to'."
            )
        if axis.cohort is None and axis.rollup == "rolls-up-to":
            findings.append(
                f"{at}: rolls up by 'rolls-up-to' without a cohort. That"
                " invariant reads the cells of a grid at one observation, and"
                " there is no grid here — declare a `CohortSpec` or use"
                " 'sums-to'."
            )

        # -- the cohort binding --------------------------------------------
        #
        # Deliberately *not* "a spec iff the source is cohort". A grid the
        # engine does not mint yet is still a grid of a stated geometry, and
        # saying "four quarters, three months apart, lagged one" about an
        # unpopulated vintage axis is the difference between naming a gap and
        # gesturing at one — the generator that closes it needs those three
        # numbers and nowhere else holds them. What is refused is the reverse:
        # a `cohort` source with no spec (the runner has nothing to read), and
        # a spec on an axis whose members come from somewhere else entirely
        # (two accounts of what a member is).
        if axis.source == "cohort" and axis.cohort is None:
            findings.append(
                f"{at}: source is 'cohort' and no `CohortSpec` is carried."
                " `as_cohorts` hands the spec straight to the episode grammar,"
                " so there is nothing here for the runner to build a grid from."
            )
        if axis.cohort is not None and axis.source not in ("cohort", "none"):
            findings.append(
                f"{at}: carries a `CohortSpec` while its members come from"
                f" {axis.source!r}. A cohort is its own member set; two"
                " accounts of what a member of this axis is will disagree."
            )
        if axis.cohort is not None and axis.cohort.name != axis.name:
            findings.append(
                f"{at}: carries a CohortSpec named {axis.cohort.name!r}."
                " `episodes.FactKindSpec.cohort` addresses an axis by that"
                " name, so a kind declared on this axis would name the spec and"
                " nothing would join it back to the dimension."
            )

        # -- the fact grammar ----------------------------------------------
        if axis.subject_type not in SUBJECT_TYPES:
            findings.append(
                f"{at}: subject type {axis.subject_type!r} is not one the fact"
                " grammar has"
                f" ({', '.join(sorted(SUBJECT_TYPES))}). A fact scoped to a"
                " subject type `episodes.FactKindSpec` does not declare is a"
                " fact no artifact outline can scope."
            )

        # -- applicability --------------------------------------------------
        unknown = sorted(axis.applies_to - lines)
        if unknown:
            findings.append(
                f"{at}: applies to line(s) of business"
                f" {', '.join(repr(k) for k in unknown)}, which no registered"
                " archetype and no division pool declares. `for_company`"
                " intersects this set with the company's own unit kinds, so a"
                " typo here does not fail — the axis silently never resolves."
            )

        # -- nesting ---------------------------------------------------------
        if axis.nests_under:
            parent = present.get(axis.nests_under)
            if parent is None:
                findings.append(
                    f"{at}: nests under {axis.nests_under!r}, which this shape"
                    " does not declare. The chain from the company down to this"
                    " axis is broken, so nothing can say what a member of it is"
                    " a part of."
                )
            else:
                if parent.rollup == "" and axis.rollup:
                    findings.append(
                        f"{at}: rolls up by {axis.rollup!r} into"
                        f" {parent.name!r}, which does not decompose amounts at"
                        " all. A share of something that holds no shares is a"
                        " subtotal with no total."
                    )
                # Sorted, because a frozenset's iteration order is not stable
                # across processes and this text reaches a report.
                orphan = sorted(axis.applies_to - parent.applies_to) if parent.applies_to else []
                if orphan:
                    findings.append(
                        f"{at}: cuts line(s) {', '.join(repr(k) for k in orphan)}"
                        f" that its parent {parent.name!r} does not. A member"
                        " would sit inside a parent that has no members for its"
                        " line of business."
                    )

    findings.extend(_cycles(axes))
    return findings


def _cycles(axes: Sequence[Axis]) -> list[str]:
    """Axes that nest inside themselves, however many hops away.

    Not a hang here — ``Shape.chain`` stops on a repeat — which is exactly why
    it needs saying. A cycle produces a shape with no outermost axis, so every
    roll-up in it is defined in terms of a roll-up that is defined in terms of
    it, and the arithmetic reconciles against itself and agrees.
    """
    by_name = {axis.name: axis for axis in axes}

    def route(start: str, name: str, path: tuple[str, ...]) -> tuple[str, ...] | None:
        axis = by_name.get(name)
        if axis is None or not axis.nests_under:
            return None
        parent = axis.nests_under
        if parent == start:
            return path + (start,)
        if parent in path:
            return None  # a cycle that does not pass through `start`; its own turn comes
        return route(start, parent, path + (parent,))

    # Sorted, and only the first reported: a cycle has no canonical member, so
    # one finding per axis on it would turn one defect into three and the
    # wording would depend on declaration order. `columns._cycles`' argument.
    for start in sorted(by_name):
        cycle = route(start, start, (start,))
        if cycle is not None:
            return [
                f"axis {start!r} nests inside itself ({' -> '.join(cycle)})."
                " The shape has no outermost axis, so every roll-up along it is"
                " checked against a total that is itself a part."
            ]
    return []


# ---------------------------------------------------------------------------
# Bridges into the grammars that already exist
# ---------------------------------------------------------------------------


def as_cohorts(shape: Shape) -> tuple[CohortSpec, ...]:
    """The ``episodes.CohortSpec``s this shape's cohort axes *are*.

    Not built from the axis — carried by it. An episode spec declaring a
    reserving triangle can take these verbatim, which is the whole reason the
    axis holds the spec rather than three integers.
    """
    return tuple(axis.cohort for axis in shape.axes if axis.cohort is not None)


def as_invariant(axis: Axis, child_kind: str) -> Invariant | None:
    """The roll-up check a parent fact carries when decomposed along *axis*.

    Returns an ``episodes.Invariant`` in the vocabulary ``factkinds`` closes, so
    a shape's claim about additivity and a fact kind's declaration are the same
    sentence rather than two. ``None`` for an axis that does not decompose
    amounts — and ``None`` is the right answer there rather than an invariant
    with no operands, because the alternative is a declared check that passes on
    everything.
    """
    if not axis.rollup:
        return None
    return Invariant(
        kind=axis.rollup,  # type: ignore[arg-type]
        operands=[child_kind],
        detail=(
            f"{child_kind} decomposes {axis.label.lower()} by {axis.name}"
            f" ({axis.rollup})."
        ),
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

#: Declared shapes, by ``Archetype.industry``. Keyed by the industry string for
#: ``divisions.POOLS``' reason — that is the key the registry already uses for
#: "what else does a company of this kind have", and a second key for a second
#: question about the same company would have to be kept in step by hand.
#:
#: Module state on purpose, and the same posture as ``factkinds.register``:
#: identical re-registration is a harmless module reload, a *different*
#: declaration under a known industry is refused, because a lint whose verdict
#: depended on import order is worse than no lint.
_REGISTRY: dict[str, Shape] = {}


def register(shape: Shape) -> None:
    """Register *shape* under its industry. A fourth vertical's entry point."""
    existing = _REGISTRY.get(shape.industry)
    if existing is not None:
        if existing == shape:
            return
        raise ValueError(
            f"industry {shape.industry!r} already declares a shape"
            f" ({', '.join(existing.names())}) — one industry is cut one way,"
            " and a second, different declaration would make `for_company`'s"
            " answer depend on import order"
        )
    _REGISTRY[shape.industry] = shape


def declared() -> tuple[str, ...]:
    """Every industry with a declared shape, sorted."""
    return tuple(sorted(_REGISTRY))


def shape_of(industry: str) -> Shape | None:
    """The shape declared for *industry*, before any company narrows it.

    ``for_company`` is the resolver and this is the declaration — an author
    adding a fifth vertical reads one of these to see what a shape looks like,
    and a reader comparing two industries wants the candidate axes rather than
    the ones one particular company's lines of business happen to keep.
    """
    return _REGISTRY.get(industry)


def library() -> tuple[Axis, ...]:
    """Every axis declared anywhere, ordered by industry then declaration.

    Sorted by industry rather than by dict order, because a registry's
    insertion order depends on import order and this tuple reaches reports.
    ``LEGACY``'s axes come first: they are the ones the engine performs today
    and every industry shape narrows or renames them.

    De-duplicated by *value*, not by identity. Two industries that share a
    shape (a supermarket group and an omnichannel retailer do) hold the same
    axis objects, and ``id()`` would work for that and would silently start
    listing an axis twice the day somebody re-typed one instead of sharing it.
    """
    seen: set[Axis] = set()
    out: list[Axis] = []
    for shape in (LEGACY, *(_REGISTRY[industry] for industry in sorted(_REGISTRY))):
        for axis in shape.axes:
            if axis in seen:
                continue
            seen.add(axis)
            out.append(axis)
    return tuple(out)


def known_lines() -> frozenset[str]:
    """Every ``UnitSpec.kind`` any registered archetype or division pool declares.

    Computed rather than maintained, ``probe.MEASURES``' argument at a smaller
    scale: a hand-kept vocabulary of lines of business would be wrong the first
    time a pool gained a division, and wrong *silently* — the failure is an axis
    that resolves for nobody, and an axis that resolves for nobody looks exactly
    like an axis nobody's company happens to have.
    """
    from . import archetypes as archetypes_module
    from . import divisions as divisions_module

    lines = {
        unit.kind
        for key in archetypes_module.available()
        for unit in archetypes_module.get(key).units
    }
    lines |= {
        unit.kind
        for pool in divisions_module.POOLS.values()
        for unit in pool
    }
    return frozenset(lines)


def for_company(archetype: Archetype) -> Shape:
    """The axes *archetype* is cut along.

    Two stages, and the division between them is the design. **Industry decides
    the candidate axes** — a bank is cut by book, portfolio, branch, vintage and
    risk grade whoever the bank is. **The company's own lines of business decide
    which of those it actually has** — a bank with a treasury desk has a
    maturity-bucket axis and a bank with a wealth arm does not, and neither of
    them has to say so twice.

    That second stage is the empty tuple's replacement, and it discriminates
    where the industry string cannot: ``midsize_adi`` and ``customer_owned_bank``
    are both ``industry="Banking"``, so any resolution keyed on industry alone
    would hand them the same answer while one runs a trading book and the other
    runs a financial-advice business.

    An unregistered industry gets ``LEGACY`` with ``declared=False`` rather than
    a refusal. A pack may name any industry it likes, and the honest answer for
    one nobody has described is "cut the way the engine cuts everything", which
    is true and is exactly what the corpus will contain.
    """
    shape = _REGISTRY.get(archetype.industry)
    if shape is None:
        return Shape(industry=archetype.industry, axes=LEGACY.axes, declared=False)
    # Declaration order preserved, never `applies_to` iteration order: a
    # frozenset's order is not stable across processes and these names reach
    # headings, reports and — once anything consumes this — documents.
    lines = {unit.kind for unit in archetype.units}
    return Shape(
        industry=shape.industry,
        axes=tuple(axis for axis in shape.axes if any(axis.cuts(line) for line in lines)),
        declared=True,
    )


# ---------------------------------------------------------------------------
# The shape the engine performs today
# ---------------------------------------------------------------------------

#: The five dimensions every company this engine builds is cut along, whatever
#: it is. Three of them are the three fields of ``UnitSpec``; the other two
#: (``format``, ``region``) are generated inside ``site_formats`` and are real
#: cuts nobody declared — ``Site.format`` and ``Site.region`` are fields on
#: every site ever minted.
#:
#: This is the baseline the rest of the module is measured against, and it is
#: what an undeclared industry gets, so a corpus is never described as having a
#: shape it does not have.
LEGACY = Shape(
    industry="",
    declared=False,
    axes=(
        Axis(
            name="unit", label="Business unit", source="units",
            populated_by="generators/hierarchy.py", rollup="sums-to",
            subject_type="unit",
            about="The archetype's declared divisions, each holding a share of"
                  " group revenue. The one axis every vertical genuinely has.",
        ),
        Axis(
            name="category", label="Category", source="categories",
            populated_by="generators/hierarchy.py", nests_under="unit",
            rollup="sums-to", subject_type="category",
            about="A merchandise category, and — in the three non-retail"
                  " verticals — whatever had to be squeezed into the field: a"
                  " lending portfolio, a class of business, a cost type. All"
                  " three carry `CategorySpec.share` of unit revenue and a"
                  " `margin`, because that is what a grocer's category has.",
        ),
        Axis(
            name="format", label="Site format", source="site_formats",
            populated_by="generators/hierarchy.py", nests_under="unit",
            rollup="sums-to", subject_type="any",
            about="Supermarket, Branch, Depot, Claims Centre. Declared as a"
                  " member set of one or two per unit, and never addressed as"
                  " an axis — `Site.format` is a string on every site and no"
                  " check, column or question groups by it.",
        ),
        Axis(
            name="site", label="Site", source="sites",
            populated_by="generators/hierarchy.py", nests_under="format",
            rollup="sums-to", subject_type="any",
            about="The individual store, branch or depot. Revenue is allocated"
                  " to it by `revenue_weight`, which is why a distribution"
                  " centre's weight is exactly zero rather than small.",
        ),
        Axis(
            name="region", label="Region", source="regions",
            populated_by="generators/hierarchy.py", nests_under="site",
            rollup="", subject_type="any",
            about="The locale's region pool, cycled onto every site by index."
                  " Rolls up by nothing because it is not a cut of the estate"
                  " at all as built: a region is an attribute of a site, sites"
                  " nest under formats, and no fact is ever minted against a"
                  " region — so summing along it would be summing an attribute.",
        ),
    ),
)


# ---------------------------------------------------------------------------
# The declared shapes
#
# Each is the same company the engine already builds, described as the business
# it is rather than as a supermarket with different words. The renamed axes
# (`portfolio`, `class_of_business`, `cost_type`) read the same `UnitSpec`
# fields and change no byte; the added ones are the shape the engine does not
# have, and every one of them is `source="none"` and reported by `lint`.
# ---------------------------------------------------------------------------

_BANK_LENDING = frozenset({
    "retail_banking", "business_banking", "cards", "institutional_banking",
})

#: The retail cut, shared by the two retail archetypes rather than declared
#: twice. ``omnichannel_retailer`` and ``australian_grocery`` carry different
#: ``industry`` strings — "Omnichannel retail" and "Supermarkets and omnichannel
#: retail" — and are the same business at two scales, so they are cut the same
#: ways. Sharing the tuple rather than re-typing it is what makes that a fact
#: about the registry instead of a coincidence two editors have to maintain.
_RETAIL_AXES: tuple[Axis, ...] = (
    Axis(
        name="division", label="Division", source="units",
        populated_by="generators/hierarchy.py", rollup="sums-to",
        subject_type="unit",
        about="Food, General Merchandise, Digital. The trading divisions a"
              " group P&L is first cut by.",
    ),
    Axis(
        name="category", label="Merchandise category", source="categories",
        populated_by="generators/hierarchy.py", nests_under="division",
        rollup="sums-to", subject_type="category",
        about="The axis the whole schema was designed around, and the one place"
              " it fits: a category has a revenue share and a gross margin, and"
              " a grocer's group margin moves because the mix between them did.",
    ),
    Axis(
        name="format", label="Store format", source="site_formats",
        populated_by="generators/hierarchy.py", nests_under="division",
        rollup="sums-to", subject_type="any",
        about="Supermarket, Metro, Department Store, Distribution Centre. A"
              " real cut: a Metro trades at roughly a third of a full"
              " supermarket, which `SiteFormat.revenue_weight` already says.",
    ),
    Axis(
        name="store", label="Store", source="sites",
        populated_by="generators/hierarchy.py", nests_under="format",
        rollup="sums-to", subject_type="any",
        about="The individual trading site. A grocer manages at this level and"
              " the engine mints revenue here already.",
    ),
    Axis(
        name="region", label="Region", source="regions",
        populated_by="generators/hierarchy.py", nests_under="store",
        rollup="", subject_type="any",
        about="State or territory, cycled onto every site. Not a decomposition"
              " as built — no fact is minted against a region.",
    ),
    Axis(
        name="channel", label="Channel", source="none", nests_under="category",
        rollup="sums-to", subject_type="any",
        about="In-store, online, click-and-collect. The axis the word"
              " *omnichannel* in this archetype's own name refers to, and the"
              " engine cannot express it: the only way to say 'sold online' is"
              " to make Digital a separate division owning a category called"
              " Online Grocery, so a grocer's online fresh produce is not the"
              " same category as its in-store fresh produce. Needs a channel"
              " dimension on the revenue allocation in `generators/finance.py`.",
    ),
    Axis(
        name="comparability", label="Comparable store status", source="none",
        nests_under="store", rollup="sums-to", subject_type="any",
        about="Comparable versus new and refitted. Like-for-like is the figure"
              " a retailer is actually judged on, and it is a cut of the estate"
              " rather than a formula: it needs each site classified against a"
              " trading anniversary, which `Site.opened` could support and"
              " nothing reads.",
    ),
)

register(Shape(industry="Omnichannel retail", axes=_RETAIL_AXES))
register(Shape(industry="Supermarkets and omnichannel retail", axes=_RETAIL_AXES))

register(Shape(industry="Banking", axes=(
    Axis(
        name="book", label="Book", source="units",
        populated_by="generators/hierarchy.py", rollup="sums-to",
        subject_type="unit",
        about="Retail, Business, Treasury. `capital.rwa_by_book` already sums"
              " to `capital.rwa_total` along exactly this axis.",
    ),
    Axis(
        name="portfolio", label="Portfolio", source="categories",
        populated_by="generators/hierarchy.py", nests_under="book",
        rollup="sums-to", subject_type="category",
        about="Residential Mortgages, Credit Cards, SME Secured Lending. Read"
              " out of `UnitSpec.categories` and therefore carrying a gross"
              " margin, which a lending portfolio does not have — it has a net"
              " interest margin and a risk weight, and neither has a field.",
        applies_to=_BANK_LENDING,
    ),
    Axis(
        name="branch", label="Branch", source="sites",
        populated_by="generators/hierarchy.py", nests_under="book",
        rollup="sums-to", subject_type="any",
        applies_to=frozenset({"retail_banking", "business_banking"}),
        about="Branches and business banking centres. Declared applicable"
              " rather than left to an empty tuple: the treasury desk's"
              " `site_formats=()` is not 'zero branches', it is 'not cut that"
              " way', and only one of those two is true. Nested straight under"
              " the book with no `format` level between, unlike retail: the"
              " engine does generate `Site.format` here (Branch, Operations"
              " Centre), and an operations centre is an estate classification"
              " rather than a smaller branch — nobody manages a bank by"
              " comparing the two, which is exactly what a grocer does with"
              " Metro against full supermarket.",
    ),
    Axis(
        name="region", label="Region", source="regions",
        populated_by="generators/hierarchy.py", nests_under="branch",
        rollup="", subject_type="any",
        applies_to=frozenset({"retail_banking", "business_banking"}),
        about="Where the branch is. Same non-decomposition as everywhere else.",
    ),
    Axis(
        name="vintage", label="Origination vintage", source="none",
        nests_under="portfolio", rollup="rolls-up-to", subject_type="unit",
        applies_to=_BANK_LENDING,
        cohort=CohortSpec(name="vintage", count=8, spacing_months=3, lag_months=3),
        about="The quarter a loan was written in. A mortgage book's credit"
              " performance is a triangle — arrears by vintage by observation"
              " date — and it is the *same grid* the insurer's accident"
              " quarters already are, so the machinery exists and only the"
              " generator does not. Eight quarters rather than the insurer's"
              " four: a mortgage's losses emerge over years, and a two-year"
              " window is the shortest one in which a vintage effect is"
              " visible at all.",
    ),
    Axis(
        name="risk_grade", label="Risk grade", source="none",
        nests_under="portfolio", rollup="sums-to", subject_type="category",
        applies_to=_BANK_LENDING,
        about="The internal rating band an exposure sits in. Risk-weighted"
              " assets decompose along it exactly as they decompose by book,"
              " and `capital.rwa_understatement` — the corpus's contested"
              " figure — is a claim about which grades were assigned, which"
              " nothing can be cut by today.",
    ),
    Axis(
        name="maturity_bucket", label="Maturity bucket", source="none",
        nests_under="book", rollup="sums-to", subject_type="unit",
        applies_to=frozenset({"treasury"}),
        about="Overnight, 8-day, 30-day, beyond. What a treasury desk has"
              " instead of branches, and what `liquidity.lcr` is computed over"
              " — the ratio is a 30-day window by construction and the corpus"
              " states it as a single number with no window to look into.",
    ),
)))

register(Shape(industry="General insurance", axes=(
    Axis(
        name="segment", label="Segment", source="units",
        populated_by="generators/hierarchy.py", rollup="sums-to",
        subject_type="unit",
        about="Personal Lines, Commercial Lines, Group Investments.",
    ),
    Axis(
        name="class_of_business", label="Class of business", source="categories",
        populated_by="generators/hierarchy.py", nests_under="segment",
        rollup="sums-to", subject_type="category",
        applies_to=frozenset({"personal_lines", "commercial_lines"}),
        about="Motor, Home, Travel, Public and Products Liability. Carried in"
              " `UnitSpec.categories`, so each one declares a gross margin — an"
              " insurer has a loss ratio and an expense ratio instead, and the"
              " field it is being stored in cannot hold either.",
    ),
    Axis(
        name="office", label="Office", source="sites",
        populated_by="generators/hierarchy.py", nests_under="segment",
        rollup="sums-to", subject_type="any",
        applies_to=frozenset({"personal_lines", "commercial_lines"}),
        about="Branches, claims centres, underwriting offices. No `format`"
              " level, for the banking axis's reason: a claims centre is a"
              " different function rather than a smaller branch.",
    ),
    Axis(
        name="region", label="Region", source="regions",
        populated_by="generators/hierarchy.py", nests_under="office",
        rollup="", subject_type="any",
        applies_to=frozenset({"personal_lines", "commercial_lines"}),
        about="Where the office is.",
    ),
    Axis(
        name="accident_quarter", label="Accident quarter", source="cohort",
        populated_by="generators/triangles.py", nests_under="segment",
        rollup="rolls-up-to", subject_type="unit",
        applies_to=frozenset({"personal_lines", "commercial_lines"}),
        cohort=CohortSpec(
            name="accident_quarter", count=4, spacing_months=3, lag_months=3,
        ),
        about="The quarter a claim was incurred in, four in view, three months"
              " apart, lagged a quarter. This is the axis that proves the"
              " point: the repository already built it — `episodes.CohortSpec`,"
              " `generators/reserving.py`, and the same four numbers in"
              " `examples/packs/longtail-insurer.json` — because reserving"
              " could not be written without it, and it lives entirely outside"
              " `Archetype`, so the insurer's own shape does not know it has"
              " one. The spec here is that spec, carried rather than copied.",
    ),
    Axis(
        name="valuation", label="Valuation", source="supersession",
        populated_by="generators/reserving.py", nests_under="accident_quarter",
        rollup="", subject_type="unit",
        applies_to=frozenset({"personal_lines", "commercial_lines"}),
        about="When the triangle was looked at. The one axis in this module"
              " that decomposes nothing: a later valuation *restates* an"
              " accident quarter's ultimate rather than holding a share of it,"
              " so summing across valuations counts the same book twice. That"
              " is what `prior_in_cohort(reserves.ultimate)` steps along, and"
              " it is why the roll-up vocabulary needed a third value rather"
              " than a boolean.",
    ),
    Axis(
        name="peril", label="Peril", source="none",
        nests_under="class_of_business", rollup="sums-to", subject_type="category",
        applies_to=frozenset({"personal_lines", "commercial_lines"}),
        about="Storm, fire, theft, liability. A home book's quarter is bad"
              " because of one peril, and the reserving commentary can only say"
              " the class deteriorated.",
    ),
    Axis(
        name="reinsurance_layer", label="Reinsurance layer", source="none",
        nests_under="segment", rollup="", subject_type="unit",
        applies_to=frozenset({"personal_lines", "commercial_lines"}),
        about="Gross, ceded, net. Not a decomposition — net is gross *less*"
              " ceded, a reconciliation rather than a share — which is why it"
              " rolls up by nothing. Every reserve figure in the corpus is"
              " silently gross, and a general insurer's board reads net.",
    ),
    Axis(
        name="asset_class", label="Asset class", source="none",
        nests_under="segment", rollup="sums-to", subject_type="category",
        applies_to=frozenset({"investments"}),
        about="What the investment book is cut by, and the direct answer to its"
              " `categories=()`: the book is not uncategorised, it is cut by"
              " asset class and the field cannot say so.",
    ),
)))

register(Shape(industry="Infrastructure services and contracting", axes=(
    Axis(
        name="segment", label="Segment", source="units",
        populated_by="generators/hierarchy.py", rollup="sums-to",
        subject_type="unit",
        about="Transport Infrastructure, Utilities and Energy, Facilities"
              " Management.",
    ),
    Axis(
        name="cost_type", label="Cost type", source="categories",
        populated_by="generators/hierarchy.py", nests_under="segment",
        rollup="sums-to", subject_type="category",
        about="Subcontract Labour, Civil Materials, Plant Hire. The schema"
              " straining hardest anywhere in the registry: these are *cost*"
              " lines, and `CategorySpec` gives each of them a share of unit"
              " *revenue* and a gross margin, so the corpus states that"
              " Subcontract Labour earned 42% of Transport Infrastructure's"
              " turnover at a 9.6% gross margin. The names are right and every"
              " number attached to them is a merchandise category's number.",
    ),
    Axis(
        name="depot", label="Depot", source="sites",
        populated_by="generators/hierarchy.py", nests_under="segment",
        rollup="sums-to", subject_type="any",
        about="Depots, yards, project offices. Revenue is allocated to them by"
              " `revenue_weight` exactly as it is to a supermarket, and a"
              " contractor books revenue on a *project*, not at the depot that"
              " houses the plant. No `format` level, for the banking axis's"
              " reason: a materials yard is not a smaller depot.",
    ),
    Axis(
        name="region", label="Region", source="regions",
        populated_by="generators/hierarchy.py", nests_under="depot",
        rollup="", subject_type="any",
        about="Where the depot is.",
    ),
    Axis(
        name="project", label="Project", source="none", nests_under="segment",
        rollup="sums-to", subject_type="any",
        about="The contract being delivered. A contractor's primary cut — its"
              " revenue, its margin, its risk and its cash are all per project"
              " — and the engine has no project entity at all, so the axis a"
              " civil contractor manages by is the one axis it does not have.",
    ),
    Axis(
        name="contract_type", label="Contract type", source="none",
        nests_under="project", rollup="sums-to", subject_type="any",
        about="Fixed price, schedule of rates, cost plus. The single largest"
              " determinant of where margin risk sits, and a lump-sum contract"
              " and a cost-plus one behave nothing alike in a bad quarter.",
    ),
    Axis(
        name="project_vintage", label="Project vintage", source="none",
        nests_under="project", rollup="rolls-up-to", subject_type="any",
        cohort=CohortSpec(
            name="project_vintage", count=4, spacing_months=3, lag_months=3,
        ),
        about="The quarter a project started. Work in progress runs off from a"
              " start date the way a claims cohort develops from an accident"
              " date — structurally the same grid as `accident_quarter`, on the"
              " same machinery, which is the argument for declaring the axis"
              " even while nothing populates it: the second cohort axis this"
              " engine needs is not a new mechanism, it is the one it has.",
    ),
)))
