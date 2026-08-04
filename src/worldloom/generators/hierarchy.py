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
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ids import Minter
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


#: Australian state and territory abbreviations, for regional attribution — the
#: engine default, drawn whenever a pack leaves ``Pack.regions`` empty. Every
#: other geographic string the corpus prints (``headquarters``) is a single
#: pack-authored value, not a pool; this one is a pool because a site estate
#: needs several regions to distribute across, cycled by ``generate`` below.
REGIONS: tuple[str, ...] = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT")


def generate(
    rng: Rng,
    minter: Minter,
    *,
    units: tuple[UnitSpec, ...],
    unit_ids: dict[str, str],
    buyers: dict[str, str],
    regions: tuple[str, ...] = REGIONS,
    physics: Parameters = DEFAULT,
) -> Dimensions:
    """Build the category and site dimensions for a set of business units.

    ``regions`` defaults to the module's own pool; a pack overrides it via
    ``Pack.regions`` (threaded through ``organisation``/``banking_org``), the
    only geography besides ``headquarters`` a generated corpus surfaces.
    Cycled by index rather than drawn, same as before the override existed —
    the sequence must stay exhaustive and evenly spread across a large estate,
    which an rng draw would not guarantee. An empty tuple here is a caller
    bug, not a valid "no locale" state — ``Pack.regions`` treats an empty list
    as "use the default pool" and the callers below never forward an empty
    one past that point, so this parameter should never actually see one.
    """
    categories: list[Category] = []
    sites: list[Site] = []
    categories_by_unit: dict[str, list[str]] = {}
    sites_by_unit: dict[str, list[str]] = {}

    for unit in units:
        unit_id = unit_ids[unit.key]
        categories_by_unit[unit_id] = []
        sites_by_unit[unit_id] = []

        for spec in unit.categories:
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
        for fmt in unit.site_formats:
            for index in range(fmt.count):
                region = regions[index % len(regions)]
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
                    name=f"{fmt.name} {region} {index + 1:03d}",
                    business_unit_id=unit_id,
                    format=fmt.name,
                    region=region,
                    opened=f"{physics.integer('org.site.opened_year', site_rng)}",
                    revenue_weight=weight,
                )
                sites.append(site)
                sites_by_unit[unit_id].append(site.id)

    return Dimensions(
        categories=tuple(categories),
        sites=tuple(sites),
        categories_by_unit={k: tuple(v) for k, v in categories_by_unit.items()},
        sites_by_unit={k: tuple(v) for k, v in sites_by_unit.items()},
    )
