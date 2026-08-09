"""Widening a company: more divisions than its archetype declares.

An archetype fixes the *shape* of a business — three retail divisions, two
banking books, one insurance portfolio — and that shape is what a corpus's size
actually rests on. The close fans out per business unit and per category, so the
document count follows the structure and not the payroll. Measured directly:
scaling the modelled organisation from 23 people to 429 left facts at 8,021,
artifacts at 204 and evaluation cases at 596 — every one of them unchanged,
because 429 people were managing the same three divisions. 418 of those people
appeared in no document, no fact and no sentence.

So this is the knob that makes a corpus bigger, and ``organisation.headcount``
is not. A division brings its own categories, its own site formats, its own
revenue share and therefore its own row in every unit-level table, its own close
commentary, and its own questions.

**Widening is additive, never destructive.** The archetype's own divisions are
kept exactly as declared — their names, their categories, their formats — and
new ones are appended from a pool. Shares are renormalised, which is the one
number that has to move: shares are a fraction of group revenue and adding a
fourth division to three that already sum to 1.0 has to take something from
somebody. Everything else about the declared divisions is untouched, so a
widened company is recognisably the same business with more of it.

**No pool, no widening.** An industry this module has no divisions for is
refused by name rather than served a generic "Division 4" — a synthetic company
whose fourth division is called Division 4 tells a reader it is synthetic
without telling them anything else, and the whole point of an archetype is that
the shape means something.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from .generators.hierarchy import CategorySpec, SiteFormat, UnitSpec

if TYPE_CHECKING:  # `archetypes` reaches back into this module inside `get`,
    # so the runtime import would be a cycle; the annotation does not need one.
    from .archetypes import Archetype

__all__ = ["POOLS", "available", "register", "widen", "widened"]


#: How much smaller each successive added division is than the one before.
#: A company's fourth line of business is bigger than its fifth; a flat
#: rate here would say it acquires equals forever.
_DECLINE = 0.8


def _unit(key: str, name: str, kind: str, categories: Sequence[tuple[str, float, float]],
          formats: Sequence[tuple[str, int, float]] = ()) -> UnitSpec:
    """One pool entry, with its share left at zero.

    A pool division carries no share of its own: what fraction of the group it
    represents depends on how many divisions the company ends up with, and
    ``widen`` decides that. Carrying a number here would be a second opinion
    about it, and the two would drift.
    """
    return UnitSpec(
        key=key, name=name, kind=kind, share=0.0,
        categories=tuple(CategorySpec(n, s, m) for n, s, m in categories),
        site_formats=tuple(SiteFormat(n, c, w) for n, c, w in formats),
    )


#: Divisions a company of each industry plausibly also has, in the order they
#: are added. Ordered rather than a set, because the order *is* the answer to
#: "which division does a company acquire fourth" — and because an unordered
#: pool would make a widened company depend on dict iteration, which is the
#: determinism rule this repository holds everything to.
#:
#: Each is a real line of business rather than a relabelling: it earns its place
#: by having categories and an estate the existing divisions do not. A pool of
#: near-duplicates would grow the row count and not the company.
POOLS: dict[str, tuple[UnitSpec, ...]] = {
    "Omnichannel retail": (
        _unit("wholesale", "Wholesale and Franchise", "wholesale",
              (("Franchise Supply", 0.58, 0.11), ("Third-Party Wholesale", 0.42, 0.08)),
              (("Distribution Centre", 3, 0.0),)),
        _unit("financial_services", "Retail Financial Services", "financial_services",
              (("Store Card", 0.46, 0.62), ("Insurance Distribution", 0.31, 0.55),
               ("Payments and FX", 0.23, 0.48))),
        _unit("fuel", "Fuel and Convenience", "fuel_convenience",
              (("Fuel", 0.71, 0.04), ("Convenience Grocery", 0.29, 0.26)),
              (("Forecourt", 62, 0.55),)),
        _unit("property", "Property and Development", "property",
              (("Investment Portfolio", 0.64, 0.71), ("Development", 0.36, 0.22))),
        _unit("international", "International", "international",
              (("Franchised Markets", 0.55, 0.19), ("Owned Markets", 0.45, 0.23)),
              (("International Store", 24, 0.72),)),
    ),
    "Banking": (
        _unit("wealth", "Wealth and Advice", "wealth",
              (("Financial Advice", 0.57, 0.21), ("Platform Administration", 0.43, 0.17))),
        _unit("institutional", "Institutional Banking", "institutional_banking",
              (("Corporate Lending", 0.49, 0.022), ("Transaction Banking", 0.31, 0.044),
               ("Trade Finance", 0.20, 0.031))),
        _unit("cards", "Cards and Payments", "cards",
              (("Consumer Cards", 0.62, 0.089), ("Merchant Acquiring", 0.38, 0.037))),
    ),
    "General insurance": (
        _unit("commercial", "Commercial Lines", "commercial_lines",
              (("Property and Business Interruption", 0.44, 0.12),
               ("Liability", 0.33, 0.09), ("Marine and Cargo", 0.23, 0.14))),
        _unit("specialty", "Specialty and Reinsurance", "specialty",
              (("Inwards Reinsurance", 0.61, 0.16), ("Financial Lines", 0.39, 0.11))),
        _unit("health", "Health and Travel", "health_travel",
              (("Private Health", 0.68, 0.07), ("Travel", 0.32, 0.19))),
    ),
}


def available(industry: str) -> int:
    """How many extra divisions this industry's pool can supply."""
    return len(POOLS.get(industry, ()))


def register(industry: str, divisions: Sequence[UnitSpec]) -> None:
    """Register a pool for *industry*. Redefinition is refused.

    The seam a fourth vertical uses, and it takes ``UnitSpec``s rather than the
    tuple shorthand above so a domain module never has to import this module's
    private helper. Refused on redefinition for ``locales.register``'s reason: a
    name is claimed once, so a collision is a wiring error and not an override.
    """
    if industry in POOLS and POOLS[industry] != tuple(divisions):
        raise ValueError(
            f"a different division pool is already registered for {industry!r};"
            f" pick another industry name rather than redefining, so a company"
            f" widened yesterday still widens the same way"
        )
    POOLS[industry] = tuple(divisions)


def widen(units: Sequence[UnitSpec], *, industry: str, count: int) -> tuple[UnitSpec, ...]:
    """*units*, extended to *count* divisions and renormalised to sum to 1.0.

    Refuses rather than truncates when *count* is below what the archetype
    already declares: dropping a division silently would remove every fact,
    document and question that division owned, and a corpus that quietly got
    smaller when somebody asked for a number is the worst kind of surprise.

    Refuses rather than invents when the pool runs out, naming how many are
    available — a caller can then register more or ask for fewer, and either is
    better than a division called ``Division 7``.
    """
    declared = tuple(units)
    if count == len(declared):
        return declared
    if count < len(declared):
        raise ValueError(
            f"this archetype declares {len(declared)} divisions and cannot be"
            f" narrowed to {count}: dropping one would remove every fact,"
            f" document and question it owns"
        )

    pool = POOLS.get(industry, ())
    wanted = count - len(declared)
    if wanted > len(pool):
        raise ValueError(
            f"asked for {count} divisions; {industry!r} declares"
            f" {len(declared)} and has {len(pool)} more in its pool, so"
            f" {len(declared) + len(pool)} is the most it can be widened to."
            f" `divisions.register` adds more."
        )

    added = pool[:wanted]
    taken = {unit.key for unit in declared}
    for unit in added:
        if unit.key in taken:
            raise ValueError(
                f"the {industry!r} pool offers a division keyed {unit.key!r},"
                f" which this archetype already declares — two divisions of one"
                f" key would collide in every table that groups by it"
            )

    # How big a new division is, and why it is not ``1 / count``.
    #
    # Equal shares were the first rule and they produce a company nobody has:
    # widening a 64/21/15 retailer to eight divisions gave Property a 12.5%
    # share against General Merchandise's 7.9% — an adjacent business
    # outweighing the core it was bolted onto. A division a company acquires
    # into is *smaller* than the ones it was built on, and each successive one
    # smaller again, which is what `_DECLINE` says.
    #
    # Sized against the smallest declared division rather than against the
    # average: the first addition is a peer of the company's smallest existing
    # business, which is the honest reading of "this company also does that".
    smallest = min(unit.share for unit in declared)
    raw_new = [smallest * (_DECLINE ** index) for index in range(len(added))]

    # Renormalised together, so the declared divisions keep their *relative*
    # sizes — 64/21/15 stays in that ratio however many arrive — and the whole
    # sums to one. That ratio is what makes a widened company the same company.
    total = sum(unit.share for unit in declared) + sum(raw_new)
    widened = [replace(unit, share=unit.share / total) for unit in declared]
    widened += [
        replace(unit, share=share / total) for unit, share in zip(added, raw_new)
    ]

    # The remainder lands on the largest division, so the shares sum to exactly
    # 1.0 rather than to 0.9999999999999999. Largest rather than first for
    # `generators/finance.allocate`'s reason: a rounding crumb is least visible
    # on the biggest number, and putting it on the smallest can move a small
    # division's revenue by a noticeable fraction.
    drift = 1.0 - sum(unit.share for unit in widened)
    if drift:
        biggest = max(range(len(widened)), key=lambda i: (widened[i].share, -i))
        widened[biggest] = replace(
            widened[biggest], share=widened[biggest].share + drift
        )
    return tuple(widened)


def widened(archetype: Archetype, count: int | None) -> Archetype:
    """*archetype* with *count* divisions, or unchanged.

    ``None`` is the byte-stable path and the default everywhere: a build that
    does not ask to be widened is the build that shipped before this module
    existed. The key is qualified — ``omnichannel_retailer+5div`` — for
    ``vocabulary.spoken``'s reason: a recipe records the archetype key and
    nothing else about the shape, so a key that did not say how wide the company
    was would rebuild a narrower one and report success.
    """
    if count is None or count == len(archetype.units):
        return archetype
    return replace(
        archetype,
        key=f"{archetype.key}+{count}div",
        units=widen(archetype.units, industry=archetype.industry, count=count),
    )
