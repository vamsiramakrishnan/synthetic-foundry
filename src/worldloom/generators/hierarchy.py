"""The reporting hierarchy: categories and sites.

A retailer's financials do not live at business-unit level. They live at category
level and roll up — category → unit → group — and the interesting management
question is almost always which category moved, not which division. A corpus whose
P&L has three rows cannot pose that question at all.

So this generates the dimensions that make a workbook worth opening: merchandise
categories with their own margin profiles, and a store network with formats and
regions. Both are entities rather than strings on a fact, because a category has a
buyer who is accountable for it and a store has a region that explains it.

Nothing here is industry-neutral. It is retail shape, and it belongs in a retail
module — which is why the *content* comes from the archetype and only the
mechanism lives here.

**And it was retail shape for every industry.** ``generate`` cut unit → category
→ format → site → region whatever the company was, because that is what its
signature took: ``units: tuple[UnitSpec, ...]``, and a ``UnitSpec`` has a
``categories`` field and a ``site_formats`` field and nowhere to say that a
treasury desk is cut by maturity bucket instead. ``axes.py`` declares the
alternative — per industry, which cuts a company has, what populates each and
how they nest — and until this module read it, nothing did.

``shape`` is that declaration arriving here. It is optional and ``None``
reproduces the five-axis cut byte-for-byte, because every world this repository
has ever built was cut that way and a shape is a description of the company
rather than a change to it. What passing one buys is stated in ``plan``: the two
things a shape can say that ``UnitSpec`` cannot, and the four things it can say
that this generator refuses to guess at.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import axes
from ..ids import Minter
from ..locales import DEFAULT as DEFAULT_LOCALE
from ..locales import Locale
from ..models import Category, Site
from ..parameters import DEFAULT, Parameters
from ..rng import Rng


@dataclass(frozen=True)
class CategorySpec:
    """One merchandise category in an archetype."""

    name: str
    share: float
    """Share of its business unit's revenue."""
    margin: float
    """Typical gross margin, before the period's erosion."""


@dataclass(frozen=True)
class SiteFormat:
    """One store format in an archetype: what it is called, how many, how big.

    ``revenue_weight`` is relative, not absolute — a Metro trades at roughly a
    third of a full supermarket — and zero means the format holds stock but books
    no revenue. Distribution centres are the reason that case is spelled out
    rather than inferred: a store-level P&L that gave a warehouse turnover would
    reconcile to the unit total and still be nonsense.
    """

    name: str
    count: int
    revenue_weight: float = 1.0


@dataclass(frozen=True)
class UnitSpec:
    """One business unit in an archetype."""

    key: str
    name: str
    kind: str
    share: float
    """Share of group revenue."""
    categories: tuple[CategorySpec, ...]
    site_formats: tuple[SiteFormat, ...] = ()
    """Empty for a unit with no physical estate."""


@dataclass(frozen=True)
class Dimensions:
    """Everything the hierarchy generator produces."""

    categories: tuple[Category, ...]
    sites: tuple[Site, ...]
    categories_by_unit: dict[str, tuple[str, ...]]
    sites_by_unit: dict[str, tuple[str, ...]]

    gaps: tuple[str, ...] = ()
    """Axes the shape declared and this cut did not perform, named.

    Empty for the legacy cut, which declares nothing and so misses nothing.
    Under a shape it is the difference between "this company is cut seven ways"
    and "this company is declared to be cut seven ways and was cut five" — and a
    caller holding only a ``Dimensions`` has no other way to tell those apart,
    because both produce the same five member sets.

    Two kinds land here and they are different absences, which is why the names
    are carried rather than a count. An axis nothing populates at all
    (``Source`` ``"none"`` — a contractor's ``project``, a bank's
    ``risk_grade``) is a gap in the engine. An axis populated by *another*
    module (the insurer's ``accident_quarter``, from ``generators/
    triangles.py``) is not a gap at all — it is somebody else's cut, and this
    generator listing it as one it did not make is how a reader finds out the
    company has a dimension that does not come from here.

    Defaulted rather than required so that every construction that predates it —
    ``generate`` is the only one — is the value it was.
    """


#: Australian state and territory abbreviations, for regional attribution — the
#: engine default, drawn whenever a pack leaves ``Pack.regions`` empty. Every
#: other geographic string the corpus prints (``headquarters``) is a single
#: pack-authored value, not a pool; this one is a pool because a site estate
#: needs several regions to distribute across, cycled by ``generate`` below.
#:
#: The tuple now lives in ``locales.AUSTRALIA`` and this is an alias, the same
#: move ``landscape.py`` made on ``estate.PROFILES``: the name is what callers
#: and ``Pack.regions``'s docstring refer to, so it stays, but two copies of a
#: pool is one copy that can stop being the one the generator draws from.
REGIONS: tuple[str, ...] = DEFAULT_LOCALE.regions


#: This module's own path, as ``axes.Axis.populated_by`` spells it. Compared
#: rather than assumed: an axis that names *another* module as its populator is
#: another generator's business and this one leaves it alone, and the only way to
#: tell those apart is to read the field.
_POPULATED_BY = "generators/hierarchy.py"

#: The ``axes.Source`` values this generator has a branch for. ``units`` is in
#: the set without being a member set this function returns: the caller mints the
#: units and passes them, and a shape still has to declare the outermost cut for
#: those units to be part of the company at all. ``regions`` likewise — a region
#: is minted *onto* every site rather than as a collection, and it is still a cut
#: this function performs.
#:
#: A tuple rather than a frozenset even though it is only ever a membership
#: test: it is also iterated to build the per-unit lookup below, whose keys
#: decide the order refusals are reported in, and a frozenset's iteration order
#: is not stable across processes. Sorted, so the reported order is the same
#: everywhere the message is read.
_MINTS: tuple[str, ...] = (
    "categories", "regions", "site_formats", "sites", "units",
)


@dataclass(frozen=True)
class Cut:
    """How one company is cut, resolved from a shape before anything is minted.

    Unit *keys*, not ids: this is settled from ``UnitSpec`` alone, so it can be
    read — and refused — without a minter, an rng or a single allocated
    identifier. That is what makes the refusals in ``plan`` plan-time rather
    than a half-built world with an exception in the middle of it.
    """

    categories: frozenset[str]
    """Unit keys whose declared categories are a cut of this company."""

    sites: frozenset[str]
    """Unit keys whose declared site formats are a cut of this company."""

    by_format: frozenset[str]
    """Unit keys whose estate is cut by format *and then* by site.

    The one structural difference a shape makes to what this generator emits,
    and it is a difference the shapes actually declare. Retail nests
    ``store`` inside ``format`` inside ``division``, because a Metro trading at
    a third of a full supermarket is a cut a grocer manages by. The bank, the
    insurer and the contractor all nest their site axis straight under the unit
    and say why in the axis's own ``about``: an operations centre is not a
    smaller branch, a claims centre is not a smaller branch, a materials yard is
    not a smaller depot. Where the format is not a cut, the unit's estate is one
    sequence — so the ordinal and the region cycle run across the whole book
    rather than restarting at 001 in the first region for every format.
    """

    gaps: tuple[str, ...] = ()
    """See ``Dimensions.gaps``, which this is carried through to."""


def plan(units: tuple[UnitSpec, ...], shape: axes.Shape) -> Cut:
    """Resolve *shape* against *units*, or refuse, before anything is minted.

    Four refusals, collected and raised together the way ``doctypes`` raises a
    lint. Each is a shape that constructs fine, lints clean, and describes a
    company this generator cannot build:

    1. **A member the company declares that no axis cuts.** The one that fires
       in practice, and the one that pays for the whole exercise:
       ``customer_owned_bank`` hands over a wealth arm with two categories while
       the Banking shape said a wealth arm was cut by nothing below the book, so
       building it would have quietly produced a division with no books in it.
       A silent drop is worse than the hardcode — the hardcode at least keeps
       the member — so it raises, and ``axes.py`` gained the ``service_line``
       axis rather than this gaining a tolerance.
    2. **A source this generator does not mint, claimed as this generator's.**
       ``axes.Axis.populated_by`` is documentation and not dispatch, which means
       nothing keeps it honest but a check like this one: an axis naming this
       module while carrying a ``Source`` there is no branch for is a cut the
       library promises and nobody performs.
    3. **Two axes of one source cutting one line.** Which one wins would depend
       on declaration order, and both name the same member set.
    4. **Sites without regions.** ``models.Site.region`` is not optional, so a
       shape that cuts a line by sites and not by regions is asking for an
       entity the thin waist has no shape for. Named rather than filled in with
       an empty string, which would render as a site nobody can place.

    What is *not* refused is a gap. Every shipped shape names axes nothing
    populates — that is the deliverable of ``axes.py``, eleven of thirty-six,
    each already reported by ``axes.lint`` — so raising on one would refuse all
    four verticals and the parameter would be unusable on every company this
    repository ships. They are carried out on ``Cut.gaps`` instead, which is
    what "not produce an empty dimension" asks for: no empty member set is
    invented for a ``project`` axis, and the omission is named.
    """
    problems: list[str] = []

    for axis in shape.populated:
        if axis.populated_by == _POPULATED_BY and axis.source not in _MINTS:
            problems.append(
                f"axis {axis.name!r} names {_POPULATED_BY} as what populates it"
                f" and carries source {axis.source!r}, which this generator has"
                f" no branch for ({', '.join(sorted(_MINTS))}). `populated_by`"
                " is documentation rather than dispatch, so nothing but this"
                " check stops the library promising a cut nobody performs."
            )

    categories: set[str] = set()
    sites: set[str] = set()
    by_format: set[str] = set()
    by_name = {axis.name: axis for axis in shape.axes}

    for unit in units:
        found = {source: shape.cut_by(unit.kind, source) for source in _MINTS}
        for source, axes_of in found.items():
            if len(axes_of) > 1:
                problems.append(
                    f"unit {unit.key!r} ({unit.kind}) is cut by"
                    f" {len(axes_of)} axes drawing on {source!r}"
                    f" ({', '.join(axis.name for axis in axes_of)}). They name"
                    " one member set twice, and which of them the cut is"
                    " reported under would depend on declaration order."
                )
        if not found["units"]:
            problems.append(
                f"unit {unit.key!r} ({unit.kind}) is a line of business the"
                f" shape for {shape.industry!r} has no unit axis for, so the"
                " company would carry a division that is not one of its cuts."
            )
        if unit.categories and not found["categories"]:
            problems.append(
                f"unit {unit.key!r} ({unit.kind}) declares"
                f" {len(unit.categories)} categories"
                f" ({', '.join(spec.name for spec in unit.categories)}) and no"
                f" axis of the shape for {shape.industry!r} cuts that line of"
                " business into them. Dropping them would remove every fact,"
                " document and question those categories own and report"
                " success; either an axis `applies_to` this line, or the"
                " archetype should not declare the members."
            )
        if unit.site_formats and not found["sites"]:
            problems.append(
                f"unit {unit.key!r} ({unit.kind}) declares an estate of"
                f" {sum(fmt.count for fmt in unit.site_formats)} sites across"
                f" {len(unit.site_formats)} formats and no axis of the shape"
                f" for {shape.industry!r} cuts that line of business by site."
            )
        if found["sites"] and not found["regions"]:
            problems.append(
                f"unit {unit.key!r} ({unit.kind}) is cut by site and not by"
                " region. `models.Site.region` is required, so every site this"
                " generator mints is placed somewhere; a shape that drops the"
                " region axis while keeping the site axis describes an entity"
                " the thin waist has no shape for."
            )

        if found["categories"]:
            categories.add(unit.key)
        if found["sites"]:
            sites.add(unit.key)
            # A format axis the site axis does not actually nest inside is a
            # format that classifies the estate without cutting it — so the
            # chain is walked rather than the presence of the axis tested.
            # `Shape.chain` stops on an unknown or repeated parent, so a shape
            # `lint` would fail on cannot hang this.
            chain = shape.chain(found["sites"][0].name)
            if any(by_name[name].source == "site_formats"
                   for name in chain[:-1] if name in by_name):
                by_format.add(unit.key)

    if problems:
        raise ValueError(
            f"the shape declared for {shape.industry!r} cannot be built as"
            " declared:\n  - " + "\n  - ".join(problems)
        )

    cut_names = {
        axis.name for axis in shape.populated
        if axis.populated_by == _POPULATED_BY
    }
    return Cut(
        categories=frozenset(categories),
        sites=frozenset(sites),
        by_format=frozenset(by_format),
        # Filtered in *declaration* order rather than built from the set above:
        # these names reach a report and a set's iteration order is not stable
        # across processes, so the same corpus would describe its own gaps in a
        # different order on a different run.
        gaps=tuple(axis.name for axis in shape.axes if axis.name not in cut_names),
    )


def generate(
    rng: Rng,
    minter: Minter,
    *,
    units: tuple[UnitSpec, ...],
    unit_ids: dict[str, str],
    buyers: dict[str, str],
    regions: tuple[str, ...] | None = None,
    locale: Locale = DEFAULT_LOCALE,
    physics: Parameters = DEFAULT,
    shape: axes.Shape | None = None,
) -> Dimensions:
    """Build the category and site dimensions for a set of business units.

    ``locale`` supplies the region pool; ``regions`` overrides it outright for
    the one caller that has a narrower claim to make. Both exist, and which
    wins is the point: a *locale* says where the company is, and a pack's
    ``Pack.regions`` says which labels this particular estate uses, which is a
    finer-grained thing than a jurisdiction. A pack that names regions has said
    something more specific than "put this company in Germany", so it wins.

    ``regions=None`` means "the locale's", which is what makes an un-passed
    argument byte-identical to before either parameter existed — the default
    locale's pool *is* the ``REGIONS`` literal. An empty tuple is still a
    caller bug rather than a valid "no locale" state: ``Pack.regions`` treats
    an empty list as "use the default pool" and the callers never forward an
    empty one past that point.

    Cycled by index rather than drawn, unchanged — the sequence must stay
    exhaustive and evenly spread across a large estate, which an rng draw would
    not guarantee.

    ``shape`` is the company's declared cut, from ``axes.for_company``. ``None``
    is the five-axis cut this engine has always performed and is byte-identical
    to it — deliberately, since ``LEGACY`` is that cut written down and a shape
    is a description rather than a change. ``plan`` resolves it, and refuses
    before any id is minted; see its docstring for what it refuses and what it
    only reports.
    """
    regions = regions if regions else locale.regions
    cut = plan(units, shape) if shape is not None else None
    categories: list[Category] = []
    sites: list[Site] = []
    categories_by_unit: dict[str, list[str]] = {}
    sites_by_unit: dict[str, list[str]] = {}

    for unit in units:
        unit_id = unit_ids[unit.key]
        categories_by_unit[unit_id] = []
        sites_by_unit[unit_id] = []

        # `plan` has already refused a unit whose declared members no axis cuts,
        # so this reads "the shape says nothing here" only where the unit
        # declares nothing either — which is why it can be a skip rather than a
        # filter that could silently shorten the member set.
        declared_categories = (
            unit.categories if cut is None or unit.key in cut.categories else ()
        )
        declared_formats = (
            unit.site_formats if cut is None or unit.key in cut.sites else ()
        )
        # Whether the estate is cut by format, which decides the scope of both
        # the ordinal and the region cycle below. `True` without a shape: that
        # is what the engine has always done, and `LEGACY` declares it.
        by_format = cut is None or unit.key in cut.by_format

        for spec in declared_categories:
            category = Category(
                id=minter.next("CAT"),
                name=spec.name,
                business_unit_id=unit_id,
                buyer_id=buyers.get(unit.key),
                margin_profile=spec.margin,
                revenue_share=spec.share,
            )
            categories.append(category)
            categories_by_unit[unit_id].append(category.id)

        site_rng = rng.derive(f"sites/{unit.key}")
        placed = 0
        for fmt in declared_formats:
            for index in range(fmt.count):
                # Where the format is a cut of the estate, a site's ordinal and
                # its region are its position *within its format* — the grocer's
                # shape, and what this generator has always done. Where it is
                # not, the unit's estate is one sequence and both run across it:
                # a bank's single operations centre is the 119th site of the
                # retail book rather than the first of a format of one, and it
                # takes the region the cycle had reached rather than always the
                # first in the pool. The whole difference is one index, because
                # the shape's whole claim is one level of nesting.
                ordinal = index if by_format else placed + index
                region = regions[ordinal % len(regions)]
                # Store sizes vary within a format, so the weight is jittered.
                # A zero-revenue format stays exactly zero rather than becoming a
                # small non-zero number — a distribution centre with $40k of
                # turnover would reconcile and still be wrong.
                #
                # The `round` stays here and `org.site.revenue_spread` must carry
                # no `places`: what is published to four decimals is the *weight*,
                # after the format's own multiplier, not the spread that produced
                # it. Rounding the draw as well is a second rounding, and it moves
                # roughly one site in seven off the value it had before this
                # registry existed.
                weight = (
                    0.0 if fmt.revenue_weight == 0.0
                    else round(
                        fmt.revenue_weight * physics.number("org.site.revenue_spread", site_rng), 4
                    )
                )
                site = Site(
                    id=minter.next("SITE"),
                    # Numbered rather than named: a thousand invented place names
                    # would read as a thousand claims about real geography.
                    name=f"{fmt.name} {region} {ordinal + 1:03d}",
                    business_unit_id=unit_id,
                    format=fmt.name,
                    region=region,
                    opened=f"{physics.integer('org.site.opened_year', site_rng)}",
                    revenue_weight=weight,
                )
                sites.append(site)
                sites_by_unit[unit_id].append(site.id)
            placed += fmt.count

    return Dimensions(
        categories=tuple(categories),
        sites=tuple(sites),
        categories_by_unit={k: tuple(v) for k, v in categories_by_unit.items()},
        sites_by_unit={k: tuple(v) for k, v in sites_by_unit.items()},
        gaps=cut.gaps if cut is not None else (),
    )
