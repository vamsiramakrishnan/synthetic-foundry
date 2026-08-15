"""The estate spend generator: what a contracting group's divisions, spend
categories, depots, project offices and materials yards buy in, have committed
and are holding at one close.

**The measured problem this closes.** A one-period build of this vertical
produced 52 facts across six documents, and its entire organisational spine
reached none of them: three business units, eighty-one depots and project
offices and both cost centres were named by no fact and carried by no document.
Retail produces 604 facts from the same single period *because* its estate is
load-bearing — ``generators/finance.py`` draws a unit total once and splits it
to categories and to sites with ``allocate``, so the roll-up reconciles by
construction rather than by arithmetic performed afterwards. This module is
that shape in a contractor's own vocabulary.

**Three measures, because the archetype already says there are three kinds of
place.** ``MIDSIZE_INFRASTRUCTURE_SERVICES`` declares depots, project offices
and materials yards, and a generator that gave all three one measure would have
thrown that distinction away — or worse, kept it and produced a materials yard
with a month of bought-in spend, which is the "distribution centre with $40k of
turnover" ``hierarchy.SiteFormat`` already argues against.

* a **depot** is where goods and services physically arrive, so it carries
  third-party spend *and* the order book behind it;
* a **project office** raises and manages commitment and takes no delivery, so
  it carries commitment and no spend — a project office with a receipting line
  would be asserting a gate it does not have;
* a **materials yard** books no spend at all (the archetype gives it
  ``revenue_weight=0.0`` for exactly that reason) and holds stock instead.

The union of the three populations is the whole estate, which is the property
that makes this close the gap rather than move it: every site carries a measure,
and no site carries one its format cannot own.

**Two independent decompositions of one total, and a third across cost
centres.** A division's bought-in spend is split by spend category *and*
by delivery point, both from the same divisional figure, exactly as a retail
month is split by merchandise category and by store. The open commitment is
split by site and, independently, across the two cost centres it is coded to.
Two decompositions that each reconcile to the same parent are a cross-check;
two independently drawn ones are two contradictions.

**What is deliberately not here, and would be the next increment.** A
commitment is a stock, so the reading a contractor's cost report actually opens
with is its *movement*: closing commitment is opening commitment plus what was
placed less what was received. Stating that would need a fourth measure
(commitment placed in the period) and a cross-period resolution of the opening
balance — the ``prior_shortfall_value`` shape ``procurement_scenarios`` already
uses. It is worth having and it is a bigger change than making the estate reach
anything at all, so it is named rather than half-built.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..ids import Minter
from ..models import Authority, CanonicalFact, Category, Quantity, Site
from ..parameters import DEFAULT, Parameters, Span
from ..rng import Rng
from .finance import allocate

#: What a site's format makes it, in this vertical's own words.
DELIVERS = "delivers"
"""Goods and services arrive here: a depot, a network depot, a facilities hub."""

COMMITS = "commits"
"""Commitment is raised and managed here and nothing is delivered: a project office."""

HOLDS = "holds"
"""Stock sits here and nothing is bought in against it: a materials yard."""


def _n(low: float, high: float, about: str, *, places: int | None = None) -> Span:
    return Span(low, high, "number", places, about)


#: This module's physics. Registered through ``parameters.register`` from
#: ``worldloom.procurement`` beside ``procurement_match.SPANS``, and layered
#: under a caller's own by ``_physics`` for the same reason that module states:
#: a caller who has already named one of these means it.
SPANS: dict[str, Span] = {
    "procurement.estate.bought_in_pct": _n(
        0.58, 0.72, places=4,
        about="Third-party spend as a share of a month's revenue. A services"
              " contractor's cost base is bought in — subcontractors, plant,"
              " materials — which is why the purchase order is where the money is"
              " committed rather than a back-office artifact. Below about half"
              " the business is self-delivering and the P2P cycle stops being"
              " where its cost lives.",
    ),
    "procurement.estate.commitment_cover": _n(
        1.6, 2.9, places=4,
        about="Open purchase-order commitment as a multiple of one month's"
              " bought-in spend — how far forward the order book runs. A"
              " framework contractor calling off monthly sits near one; a group"
              " placing subcontract packages a quarter ahead sits near three.",
    ),
    "procurement.estate.materials_pct": _n(
        0.035, 0.085, places=4,
        about="Materials held in the yards, as a share of a month's bought-in"
              " spend. A contractor holds days rather than months of stock:"
              " material is called to site, not warehoused.",
    ),
    "procurement.estate.indirect_share": _n(
        0.05, 0.12, places=4,
        about="The share of open commitment coded to the finance shared-services"
              " cost centre rather than to the commercial one — overheads and"
              " corporate services against direct project spend.",
    ),
    "procurement.estate.yard_holding_spread": _n(
        0.6, 1.5, places=4,
        about="Relative size of one materials yard's holding. Drawn per yard"
              " because the archetype gives every yard a revenue weight of zero"
              " — deliberately, since a yard books no turnover — so there is no"
              " declared weight to allocate a stock balance across.",
    ),
}


def _physics(physics: Parameters) -> Parameters:
    """*physics* with this module's spans available, layered underneath.

    See ``procurement_match._physics``: same contract, same reason, and the
    same "returns the argument untouched when nothing is missing" so a world
    built with overrides keeps the exact ``Parameters`` it was handed.
    """
    if all(name in physics.spans for name in SPANS):
        return physics
    return Parameters({**SPANS, **dict(physics.spans)})


#: What each shipped site format is. A table of content, in the module that
#: owns this vertical's content — the same arrangement ``procurement_org`` uses
#: for its role table, its persona table and its system name pools.
#:
#: ``SiteFormat`` carries a name, a count and a revenue weight and has **no
#: field for what kind of place it is**, which is the gap this table stands in
#: for and the extraction trigger a fifth vertical would hit: a hospital's ward
#: and its loading dock are the same distinction. Until that field exists, a
#: format this table has never heard of falls back to the one structural signal
#: the model does carry — a zero revenue weight is already how the corpus says
#: "holds stock, books nothing", which is exactly a yard.
_FORMAT_ROLE: dict[str, str] = {
    "Depot": DELIVERS,
    "Network Depot": DELIVERS,
    "Facilities Hub": DELIVERS,
    "Project Office": COMMITS,
    "Materials Yard": HOLDS,
}


def role_of(site: Site) -> str:
    """What kind of place *site* is, for the measures it can own."""
    role = _FORMAT_ROLE.get(site.format)
    if role is not None:
        return role
    # A pack's own format. Zero weight is the corpus's existing way of saying a
    # site holds stock and books no turnover, so it resolves to a yard; anything
    # that trades resolves to a delivery point, which is the reading that leaves
    # no site carrying nothing.
    return HOLDS if site.revenue_weight == 0.0 else DELIVERS


#: Which roles own which measure. Stated as data beside the roles rather than
#: as three ``if`` s in the emitter, so "what does a project office carry" is
#: answerable by reading one table.
SPEND_ROLES: tuple[str, ...] = (DELIVERS,)
COMMITMENT_ROLES: tuple[str, ...] = (DELIVERS, COMMITS)
MATERIALS_ROLES: tuple[str, ...] = (HOLDS,)

SPEND = "p2p.third_party_spend"
COMMITMENT = "p2p.open_commitment"
MATERIALS = "p2p.materials_on_hand"


@dataclass(frozen=True)
class EstatePosition:
    """One month's spend, commitment and stock position across the estate."""

    facts: tuple[CanonicalFact, ...]
    """Every fact minted, group first, then divisions, then the cuts. Ordered,
    because the document that reports them requires all of them and a document
    is compared against its plan fact by fact."""

    spend_total: int
    commitment_total: int
    materials_total: int


class _Ledger:
    """Accumulates facts, so the body below reads as allocation rather than plumbing."""

    def __init__(self, minter: Minter, *, money_unit: str, at: datetime,
                 period: str, event_id: str) -> None:
        self.minter = minter
        self.money_unit = money_unit
        self.at = at
        self.period = period
        self.event_id = event_id
        self.facts: list[CanonicalFact] = []

    def money(self, kind: str, subject: str, amount: int, *, source: str,
              lore: Sequence[str] = ()) -> CanonicalFact:
        fact = CanonicalFact(
            id=self.minter.next("FACT"),
            kind=kind,
            subject=subject,
            period=self.period,
            value=Quantity(amount=amount, unit=self.money_unit),
            valid_from=self.at,
            authority=Authority.SYSTEM_OF_RECORD,
            source_system=source,
            event_id=self.event_id,
            lore_ids=list(lore),
        )
        self.facts.append(fact)
        return fact


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    unit_ids: dict[str, str],
    unit_shares: dict[str, float],
    categories: Sequence[Category],
    sites: Sequence[Site],
    commercial_cost_centre_id: str,
    finance_cost_centre_id: str,
    annual_revenue: int,
    money_unit: str,
    at: datetime,
    event_id: str,
    procure_system_id: str,
    receipting_system_id: str,
    general_ledger_id: str,
    lore_by_target: dict[str, list[str]] | None = None,
    physics: Parameters = DEFAULT,
) -> EstatePosition:
    """The month's position across the divisions, the categories and the estate.

    ``unit_ids`` and ``unit_shares`` are keyed by the archetype's unit key and
    iterated in *its* order, not in the order a set happens to yield: the ids
    minted below are part of the corpus and a build whose fact ids depended on
    iteration order would not replay.

    Every figure is allocated, never drawn twice. The group is drawn once, split
    to divisions by declared share, and each division split again — by spend
    category, by delivery point, by whatever the estate carries — so a division
    total and the rows under it cannot disagree. ``allocate`` is
    largest-remainder, so the integer parts add to the integer whole exactly and
    there is no residual line to explain.
    """
    physics = _physics(physics)
    lore_by_target = lore_by_target or {}
    ledger = _Ledger(minter, money_unit=money_unit, at=at, period=period, event_id=event_id)

    keys = list(unit_ids)
    # A month of revenue, the same anchor `finance.generate` uses, then the
    # share of it that is bought in. Drawn from a stream named for what it is,
    # per period, so two months of a history are two months rather than one
    # photocopied.
    monthly = annual_revenue // 12
    bought_in = physics.number("procurement.estate.bought_in_pct", rng.derive("bought_in"))
    spend_total = int(round(monthly * bought_in, -2))
    cover = physics.number("procurement.estate.commitment_cover", rng.derive("cover"))
    commitment_total = int(round(spend_total * cover, -2))
    holding = physics.number("procurement.estate.materials_pct", rng.derive("materials"))
    materials_total = int(round(spend_total * holding, -2))
    indirect = physics.number("procurement.estate.indirect_share", rng.derive("indirect"))

    by_unit: dict[str, list[Site]] = {unit_ids[key]: [] for key in keys}
    for site in sites:
        if site.business_unit_id in by_unit:
            by_unit[site.business_unit_id].append(site)
    cats_of: dict[str, list[Category]] = {unit_ids[key]: [] for key in keys}
    for category in categories:
        if category.business_unit_id in cats_of:
            cats_of[category.business_unit_id].append(category)

    def estate(unit_id: str, roles: tuple[str, ...]) -> list[Site]:
        return [site for site in by_unit[unit_id] if role_of(site) in roles]

    # The lore that explains why a short delivery is visible at all is the same
    # lore that explains why a receipted figure is trustworthy per depot, so the
    # spend facts carry it. Named through the same target the cycle reads.
    rollout = lore_by_target.get("receipting_visibility/subcontract", [])
    contract = lore_by_target.get("finance/pay_to_contract", [])

    # Materials sit only where there is somewhere to put them. A division with
    # no yard gets no fact at all rather than a zero, and a *company* with no
    # yard anywhere states no group figure either: "this company holds nothing"
    # and "this company has nowhere to hold anything" are different claims, and
    # a zero states the first while meaning the second. It is also what keeps
    # the group total decomposable — a figure at the top with no division under
    # it is a total that reconciles against nothing.
    holders = [key for key in keys if estate(unit_ids[key], MATERIALS_ROLES)]

    # -- group ---------------------------------------------------------------
    ledger.money(SPEND, company_id, spend_total,
                 source=receipting_system_id, lore=rollout)
    ledger.money(COMMITMENT, company_id, commitment_total,
                 source=procure_system_id, lore=contract)
    if holders:
        ledger.money(MATERIALS, company_id, materials_total, source=general_ledger_id)

    # -- divisions -----------------------------------------------------------
    shares = [unit_shares[key] for key in keys]
    unit_spend = dict(zip(keys, allocate(spend_total, shares)))
    unit_commitment = dict(zip(keys, allocate(commitment_total, shares)))
    unit_materials = dict(zip(
        holders, allocate(materials_total, [unit_shares[key] for key in holders])
    )) if holders else {}

    for key in keys:
        ledger.money(SPEND, unit_ids[key], unit_spend[key],
                     source=receipting_system_id, lore=rollout)
    for key in keys:
        ledger.money(COMMITMENT, unit_ids[key], unit_commitment[key],
                     source=procure_system_id, lore=contract)
    for key in holders:
        ledger.money(MATERIALS, unit_ids[key], unit_materials[key], source=general_ledger_id)

    # -- by spend category ---------------------------------------------------
    # The second decomposition of the same divisional figure, and the level a
    # category manager is actually accountable at.
    for key in keys:
        unit_id = unit_ids[key]
        members = cats_of[unit_id]
        weights = [category.revenue_share for category in members]
        if not members or sum(weights) <= 0:
            continue
        for category, amount in zip(members, allocate(unit_spend[key], weights)):
            ledger.money(SPEND, category.id, amount,
                         source=receipting_system_id, lore=rollout)

    # -- by delivery point ---------------------------------------------------
    for key in keys:
        unit_id = unit_ids[key]
        delivery = estate(unit_id, SPEND_ROLES)
        weights = [site.revenue_weight for site in delivery]
        if not delivery or sum(weights) <= 0:
            continue
        for site, amount in zip(delivery, allocate(unit_spend[key], weights)):
            ledger.money(SPEND, site.id, amount,
                         source=receipting_system_id, lore=rollout)

    # -- commitment, by the places that hold it ------------------------------
    for key in keys:
        unit_id = unit_ids[key]
        committing = estate(unit_id, COMMITMENT_ROLES)
        weights = [site.revenue_weight for site in committing]
        if not committing or sum(weights) <= 0:
            continue
        for site, amount in zip(committing, allocate(unit_commitment[key], weights)):
            ledger.money(COMMITMENT, site.id, amount, source=procure_system_id, lore=contract)

    # -- commitment, by cost centre ------------------------------------------
    # The group figure cut a second way, and the cut follows the *charge* rather
    # than the org chart: every order is coded somewhere, and a delegation that
    # could not say how much sits against corporate services against how much
    # sits against project work is a delegation nobody can review. The two
    # centres are `procurement_org`'s own split — commercial and supply chain
    # against finance shared services — read here as direct against indirect.
    direct, overhead = allocate(commitment_total, [1.0 - indirect, indirect])
    ledger.money(COMMITMENT, commercial_cost_centre_id, direct, source=procure_system_id)
    ledger.money(COMMITMENT, finance_cost_centre_id, overhead, source=procure_system_id)

    # -- materials, by yard --------------------------------------------------
    # Weighted by a drawn holding rather than by `revenue_weight`, which is zero
    # for every yard by construction: `allocate` refuses weights that sum to
    # zero, and rightly — an equal split would be a claim that five yards hold
    # the same stock, which is a figure nobody would print.
    for key in holders:
        unit_id = unit_ids[key]
        yards = estate(unit_id, MATERIALS_ROLES)
        weights = [
            physics.number(
                "procurement.estate.yard_holding_spread", rng.derive(f"yard/{site.id}")
            )
            for site in yards
        ]
        for site, amount in zip(yards, allocate(unit_materials[key], weights)):
            ledger.money(MATERIALS, site.id, amount, source=general_ledger_id)

    return EstatePosition(
        facts=tuple(ledger.facts),
        spend_total=spend_total,
        commitment_total=commitment_total,
        materials_total=materials_total,
    )


__all__ = [
    "COMMITMENT", "COMMITMENT_ROLES", "COMMITS", "DELIVERS", "EstatePosition",
    "HOLDS", "MATERIALS", "MATERIALS_ROLES", "SPANS", "SPEND", "SPEND_ROLES",
    "generate", "role_of",
]
