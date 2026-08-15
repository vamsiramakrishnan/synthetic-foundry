"""The retail overhead and distribution generator: what a retailer's corporate
centre costs, and what its warehouses move.

**The measured problem this closes.** Retail was the vertical banking, insurance
and procurement were measured *against* — its stores, categories and divisions
were the one load-bearing estate in the repository, which is why one period of it
minted 588 facts against banking's 58. It was also the one vertical the wave that
made the other three load-bearing did not touch, and the measurement said so::

    archetype:omnichannel_retailer    cost centre 2/2
    archetype:australian_grocery      cost centre 2/2, site   44/1607
    pack:trading-retailer.json        cost centre 2/2, site    5/173
    pack:regional-insurer.json        cost centre 2/2      (a retail-engine pack)

Two holes, one cause each.

**Every retail company declares two cost centres and no fact named either.**
``organisation.generate`` mints Finance Shared Services and Data Platform
Engineering, stamps a cost centre on every person by function, and then nothing
in the close ever charged anything to one. A cost centre is where a charge
lands; a company that declares two and books to neither has an accounting
structure with no accounting in it. So the corporate cost base is decomposed
**twice** — by the centre that incurs it and, independently, by the division it
is recharged to — which is ``banking_network``'s shape in a retailer's own
vocabulary, and is a cross-check rather than two claims precisely because the
two sets of entities are different and sum to one figure.

**A zero-weight site was a site with nothing to say.** ``finance.generate``
drops sites whose ``revenue_weight`` is zero rather than allocating them a
turnover row, and that is right — a store P&L that gave a warehouse takings
would reconcile to the unit total and still be nonsense. What was wrong is that
the engine then cut *nothing else* by site, so 44 of the grocer's 1,607 sites
and 5 of ``trading-retailer.json``'s 173 were declared, named, regioned, dated
and reported on by nothing at all.

The fix is not to declare them structural. ``validate.Structural`` would have
taken them, and the exemption drafted for them in ``tests/test_reachability.py``
said in its own reason text how to disagree with it: "mint a throughput or a
cost-to-serve measure the estate owns, at which point the exemption should go
rather than be widened." That is what this module does, and the repository has
already run the experiment twice — insurance's claims centres and procurement's
materials yards carry the same ``revenue_weight == 0``, both engines minted the
measure their sites actually own (a claims count, held materials), and both
kinds of site now reach without an exemption. An industry-scoped exemption would
also have closed the grocer's 44 and left ``trading-retailer.json``'s 5 refused,
because the two companies spell their ``Company.industry`` differently
("Supermarkets and omnichannel retail" against "Omnichannel retail") — so the
allowlist-shaped path here is not merely weaker, it does not even generalise
across the two retail corpora this repository ships.

So a distribution centre owns two measures and a rate: the volume it dispatched,
what that cost, and the cost per carton those two make. A warehouse is a cost
centre with a throughput, which is exactly what a retailer's own logistics
report says about one.

Three rules, taken from ``finance.py`` rather than reinvented:

* **A total is drawn once and allocated down**, with ``finance.allocate``'s
  largest remainder, so the roll-up reconciles *exactly*. ``retail._checks``
  asserts it with ``==`` on integers and no tolerance: the allocator either adds
  up or it is broken, and a corpus that needed ``RECONCILIATION_TOLERANCE`` to
  agree with itself would be one round-and-hope away from a workbook that
  disagrees with the memo quoting it.
* **The recharge basis is the revenue the workbook already states.** Divisional
  recharge is allocated on each division's *actual* revenue for the period,
  read back off the facts ``finance.generate`` minted, rather than on the
  archetype's declared share. Those two are close and are not the same number,
  and a corpus in which the recovery percentage on the sheet cannot be
  recomputed from the revenue two tabs away is the class of defect this project
  exists to eliminate.
* **A rate is never summed.** Overhead recovery and cost per carton are ratios
  of the two amounts at the level they are stated, derived from the rounded
  figures rather than carried down from the draw, and the subtotal rows leave
  them blank. See ``columns.not_summable`` and ``Sheet.rate_kinds`` for the rule
  this repository has already paid for twice.

What is deliberately **not** modelled:

* **A trading store has no cost to serve here.** It plainly has one, and stating
  it would need a second allocation basis and a second argument about what a
  store's share of distribution cost is. This module cuts the distribution
  network by the sites that *are* the distribution network, which is the cut
  nothing else makes; inventing a store-level logistics recharge beside the
  store P&L would be a second, independently drawn claim about the same money.
* **A cost centre holds no headcount.** Every person already carries a
  ``cost_centre_id`` from ``organisation.generate``, so a headcount by centre
  would be a figure derivable from the roster and drawn anyway — two answers to
  one question. The corporate cost base is money, and money is what a cost
  centre is for.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..ids import Minter
from ..models import Authority, BusinessUnit, CanonicalFact, CostCentre, Quantity, Site
from ..parameters import DEFAULT, Parameters, Span
from ..rng import Rng
from .finance import allocate

#: Thousands of cartons dispatched. A carton rather than a pallet or a line: it
#: is the unit a retail distribution centre's own throughput report is written
#: in, and it is coarse enough that a month of a large grocer's volume is a
#: five-figure number rather than a nine-figure one.
CARTONS = "cartons_thousands"

PERCENT = "percent"

#: The fact kinds this module mints. Named here rather than spelled at each
#: ledger call because ``retail._checks`` and ``documents.finance_workbook``
#: both read them, and three literals of one string is how the seven-table
#: agreement ``columns.py`` was extracted to end starts again.
SHARED_COST = "overhead.shared_services.cost"
SHARED_RECHARGE = "overhead.shared_services.recharge"
SHARED_RECOVERY = "overhead.shared_services.recovery_pct"
THROUGHPUT = "logistics.throughput"
COST_TO_SERVE = "logistics.cost_to_serve"
COST_PER_CARTON = "logistics.cost_per_carton"

#: The two measures that decompose, and the rate beside each that does not.
#: Read by ``retail._checks`` so the reconciliation test and the generator
#: cannot disagree about which figures are supposed to add up.
ADDITIVE: tuple[str, ...] = (SHARED_COST, SHARED_RECHARGE, THROUGHPUT, COST_TO_SERVE)
RATES: tuple[str, ...] = (SHARED_RECOVERY, COST_PER_CARTON)


def _n(low: float, high: float, about: str, *, places: int | None = None) -> Span:
    return Span(low, high, "number", places, about)


#: This module's physics, registered globally from ``worldloom.retail`` — the
#: seam ``banking_network.SPANS`` and ``procurement_estate.SPANS`` both use, for
#: the reason ``parameters.register`` states: a vertical's ranges are declared
#: beside the generator that draws them.
SPANS: dict[str, Span] = {
    "retail.overhead.cost_pct": _n(
        0.018, 0.032, places=4,
        about="The corporate cost base as a share of a month's group revenue —"
              " finance, audit and the data platform, before any of it is"
              " recharged to a division. A retailer runs its centre thin: much"
              " above three per cent of turnover and the head office is the"
              " thing the business is about.",
    ),
    "retail.overhead.centre_weight": _n(
        0.75, 1.45, places=3,
        about="One cost centre's size relative to its peers. A cost centre has"
              " no size field on it — it is a place charges land, not a place"
              " that trades — so its share of the corporate base is drawn from a"
              " stream named for the centre itself, which is"
              " `banking.network.cost_centre_weight`'s argument in this engine.",
    ),
    "retail.overhead.service_intensity": _n(
        0.80, 1.30, places=3,
        about="How much of the corporate centre one division consumes relative"
              " to its size. Recharge is allocated on turnover *times* this, and"
              " the tilt is the whole reason the recovery column is a"
              " measurement: allocated on turnover alone, every division and the"
              " group recover the corporate base at exactly the same percentage"
              " — measured at 2.38 across all four of the grocer's divisions"
              " before this span existed — and a rate that never varies is a"
              " rate nobody reads (`banking.network.unit_funding_tilt`). It is"
              " also the more honest model: a digital division consumes the data"
              " platform out of all proportion to what it sells, which is the"
              " argument every real recharge negotiation is about.",
    ),
    "retail.logistics.cartons_per_thousand": _n(
        14.0, 26.0, places=2,
        about="Cartons dispatched through the distribution network per thousand"
              " of a division's revenue. What turns a month of turnover into a"
              " month of volume: a grocery carton retails for tens of dollars, a"
              " general-merchandise one for rather more, so the band is wide and"
              " is drawn per division rather than once for the group.",
    ),
    "retail.logistics.cost_per_carton": _n(
        2.6, 4.4, places=3,
        about="What it costs to receive, hold and dispatch one carton, in the"
              " company's own currency. The number a distribution director is"
              " actually judged on, and the reason cost-to-serve is derived from"
              " throughput rather than drawn beside it: a cost that did not track"
              " the volume it was incurred moving would be a second,"
              " unexplained claim about the same network.",
    ),
    "retail.logistics.centre_weight": _n(
        0.70, 1.40, places=3,
        about="One distribution centre's share of its division's volume. Drawn"
              " per site for `procurement.estate.yard_holding_spread`'s reason:"
              " the archetype gives every distribution centre a revenue weight of"
              " zero — deliberately, since a warehouse books no turnover — so"
              " there is no declared weight to allocate a throughput across, and"
              " an equal split would be a claim that 34 centres are the same"
              " size.",
    ),
    "retail.logistics.efficiency_tilt": _n(
        0.88, 1.15, places=3,
        about="How far one centre's unit cost departs from its division's. Cost"
              " is allocated on throughput *times* this, so the cost-per-carton"
              " column varies across the network — a single divisional rate"
              " applied to every site would make it a constant, and a rate that"
              " never varies is a rate nobody reads"
              " (`banking.network.unit_funding_tilt`).",
    ),
}


def _physics(physics: Parameters) -> Parameters:
    """*physics* with this module's spans available, layered underneath.

    ``procurement_estate._physics``, verbatim, and for its reason: a caller who
    has already named one of these means it, and a world built with overrides
    keeps the exact ``Parameters`` object it was handed.
    """
    if all(name in physics.spans for name in SPANS):
        return physics
    return Parameters({**SPANS, **dict(physics.spans)})


@dataclass(frozen=True)
class EstateCosts:
    """One period of corporate overhead and distribution volume, as facts.

    ``empty`` is the honest answer for a company with neither a distribution
    estate nor a cost centre — an archetype may declare no warehouses at all,
    and ``omnichannel_retailer`` declares exactly none — so the workbook plans no
    tab rather than planning one with no rows in it. That is
    ``documents.finance_workbook``'s own "an empty Store Performance tab is
    worse than no tab", one sheet along.
    """

    facts: tuple[CanonicalFact, ...]
    group_overhead: int
    group_cartons: int
    group_cost_to_serve: int

    @property
    def empty(self) -> bool:
        return not self.facts


class _Ledger:
    """Accumulates facts, so ``generate`` below reads as arithmetic.

    ``banking_network._Ledger``'s shape rather than an import of
    ``finance._Ledger``: that one is private to the module beside it, and
    widening it to carry a second unit vocabulary would make a read-only
    generator answerable to this one.
    """

    def __init__(self, minter: Minter, *, at: datetime, event: str | None,
                 source: str, money_unit: str) -> None:
        self.minter = minter
        self.facts: list[CanonicalFact] = []
        self.at = at
        self.event = event
        self.source = source
        self.money_unit = money_unit

    def measure(self, kind: str, subject: str, period: str, amount: float,
                unit: str, *, lore: list[str] | None = None) -> CanonicalFact:
        fact = CanonicalFact(
            id=self.minter.next("FACT"),
            kind=kind,
            subject=subject,
            period=period,
            value=Quantity(amount=amount, unit=unit),
            valid_from=self.at,
            authority=Authority.SYSTEM_OF_RECORD,
            source_system=self.source,
            event_id=self.event,
            lore_ids=lore or [],
        )
        self.facts.append(fact)
        return fact

    def money(self, kind: str, subject: str, period: str, amount: int,
              *, lore: list[str] | None = None) -> CanonicalFact:
        return self.measure(kind, subject, period, amount, self.money_unit, lore=lore)


def _rate(numerator: float, denominator: float) -> float:
    """A stated rate, derived from the rounded amounts it describes.

    ``banking_network._ratio_pct``'s rule without its ``* 100``, because only
    one of the two rates here is a percentage: a reader who divides the two
    columns on the sheet must get the number the sheet states, and the draw is a
    target the allocation has already rounded away from.
    """
    return round(numerator / denominator, 2) if denominator else 0.0


def distribution_estate(sites: Sequence[Site]) -> tuple[Site, ...]:
    """The sites that hold stock and sell nothing.

    Read off ``Site.revenue_weight``, whose own field docstring already states
    the meaning — "zero for a site that holds stock but sells nothing" — rather
    than off a list of format names. That is the same declaration
    ``validate.Structural``'s worked example reads, used to give these sites a
    measure instead of to excuse them from having one, and it is why a pack that
    invents a format called ``Fulfilment Centre`` is covered without naming it:
    ``trading-retailer.json`` declares three ``Distribution Centre`` and two
    ``Fulfilment Centre`` rows, and a name-matching predicate would have found
    three of the five.
    """
    return tuple(site for site in sites if site.revenue_weight == 0.0)


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    units: Sequence[BusinessUnit],
    sites: Sequence[Site],
    cost_centres: Sequence[CostCentre],
    revenue_by_subject: dict[str, int],
    at: datetime,
    event_id: str | None,
    erp_id: str,
    money_unit: str,
    currency: str,
    physics: Parameters = DEFAULT,
) -> EstateCosts:
    """The corporate centre and the distribution network, for one period.

    ``revenue_by_subject`` is the period's *actual* revenue by subject id, as
    ``finance.generate`` already minted it — group and every division. Passed in
    rather than redrawn, and that is the whole reason this generator runs after
    the financial one rather than beside it: the recharge on the sheet has to be
    a share of the revenue on the sheet, or the recovery percentage in between
    them is a number no reader can reproduce.

    ``event_id`` is the close this belongs to, or ``None``. Threaded rather than
    assumed, because a fact with no event is how ``validate.temporal`` tells a
    standing figure from one an episode produced.

    ``money_unit`` and ``currency`` are both taken because the rate needs the
    second and cannot be given the first. Money here is ``AUD_thousands`` and
    volume ``cartons_thousands``, so their quotient is *currency per carton* —
    stating it in ``AUD_thousands`` would be off by a factor of a thousand while
    reading perfectly plausibly, which is the class of unit error a corpus never
    notices because every check compares a figure against itself.
    """
    physics = _physics(physics)
    group_revenue = revenue_by_subject.get(company_id, 0)
    if group_revenue <= 0:
        # Nothing was booked for the period, so there is nothing to take a share
        # of. Minting a corporate cost base against an absent turnover would be
        # a figure with no denominator, and the recovery rate beside it would
        # divide by zero — see `_rate`, which returns 0.0 rather than raising and
        # would therefore state a recovery of nought per cent as though it were
        # a measurement.
        return EstateCosts(facts=(), group_overhead=0, group_cartons=0,
                           group_cost_to_serve=0)

    ledger = _Ledger(minter, at=at, event=event_id, source=erp_id,
                     money_unit=money_unit)

    # -- the corporate cost base, decomposed twice ---------------------------
    group_overhead = int(round(
        group_revenue * physics.number("retail.overhead.cost_pct", rng.derive("overhead"))
    ))
    centre_ids = [centre.id for centre in cost_centres]
    recharged = [unit for unit in units if revenue_by_subject.get(unit.id, 0) > 0]

    if centre_ids and recharged:
        ledger.money(SHARED_COST, company_id, period, group_overhead)
        # By the centre that incurs it. The weight is drawn from a stream named
        # for the centre rather than taken from a field, because a `CostCentre`
        # carries an owner and a unit and no size at all.
        for centre_id, amount in zip(centre_ids, allocate(
            group_overhead,
            [physics.number("retail.overhead.centre_weight",
                            rng.derive(f"centre/{cid}")) for cid in centre_ids],
        )):
            ledger.money(SHARED_COST, centre_id, period, amount)

        # And by the division that carries it. A genuine second decomposition
        # rather than a relabelling of the first: two centres and three
        # divisions are different sets of entities summing to one figure, which
        # is what makes either of them checkable. Recharged on turnover — the
        # basis a retail group actually uses, and the one the workbook can be
        # recomputed against, which is why the revenue column sits beside the
        # recharge on the sheet — tilted by how much of the centre each division
        # actually consumes. See `retail.overhead.service_intensity`: on turnover
        # alone the recovery rate is a constant, which is a column of one
        # repeated number wearing a measurement's heading.
        ledger.money(SHARED_RECHARGE, company_id, period, group_overhead)
        recharge = dict(zip(
            (unit.id for unit in recharged),
            allocate(group_overhead, [
                revenue_by_subject[u.id] * physics.number(
                    "retail.overhead.service_intensity",
                    rng.derive(f"recharge/{u.id}"))
                for u in recharged
            ]),
        ))
        for unit in recharged:
            ledger.money(SHARED_RECHARGE, unit.id, period, recharge[unit.id])
        # The rate, last and derived from the two rounded amounts above. Stated
        # at every level it is read at and summed at none of them: the group
        # recovery is group overhead over group revenue, never the total of
        # three divisional percentages.
        ledger.measure(SHARED_RECOVERY, company_id, period,
                       _rate(group_overhead * 100, group_revenue), PERCENT)
        for unit in recharged:
            ledger.measure(SHARED_RECOVERY, unit.id, period,
                           _rate(recharge[unit.id] * 100,
                                 revenue_by_subject[unit.id]), PERCENT)

    # -- the distribution network --------------------------------------------
    # A division's volume follows the revenue it sold, and its centres split
    # that volume; the group figure is the sum of the divisions that *have* a
    # network rather than a figure drawn for the company. `_sum_row`'s rule: a
    # total whose rows do not cover the whole parent must report the rows it
    # has, and a company total derived from group revenue would silently include
    # the volume of divisions with no warehouse to move it through.
    network: list[tuple[BusinessUnit, tuple[Site, ...]]] = []
    for unit in units:
        estate = distribution_estate(
            [s for s in sites if s.business_unit_id == unit.id]
        )
        if estate and revenue_by_subject.get(unit.id, 0) > 0:
            network.append((unit, estate))

    unit_cartons: dict[str, int] = {}
    unit_cost: dict[str, int] = {}
    site_cartons: dict[str, int] = {}
    site_cost: dict[str, int] = {}
    for unit, estate in network:
        unit_rng = rng.derive(f"logistics/{unit.id}")
        density = physics.number("retail.logistics.cartons_per_thousand", unit_rng)
        unit_rate = physics.number("retail.logistics.cost_per_carton", unit_rng)
        # Revenue is in thousands of currency and throughput in thousands of
        # cartons, so `revenue * cartons-per-thousand / 1000` lands in the right
        # unit and `cartons_thousands * currency-per-carton` lands back in
        # thousands of currency. Both divisions are exact in the sense that
        # matters: the figure minted is the figure allocated.
        cartons = int(round(revenue_by_subject[unit.id] * density / 1000))
        if cartons <= 0:
            continue
        cost = int(round(cartons * unit_rate))
        unit_cartons[unit.id] = cartons
        unit_cost[unit.id] = cost

        weights = [
            physics.number("retail.logistics.centre_weight",
                           rng.derive(f"dc/{site.id}"))
            for site in estate
        ]
        for site, amount in zip(estate, allocate(cartons, weights)):
            site_cartons[site.id] = amount
        # Cost is allocated on volume *times* an efficiency tilt, so the rate
        # column moves across the network. Allocating it on the same weights as
        # the volume would make every centre's cost per carton identical to its
        # division's, which is a column of one repeated number.
        cost_weights = [
            weight * physics.number("retail.logistics.efficiency_tilt",
                                    rng.derive(f"dc_cost/{site.id}"))
            for site, weight in zip(estate, weights)
        ]
        for site, amount in zip(estate, allocate(cost, cost_weights)):
            site_cost[site.id] = amount

    if unit_cartons:
        group_cartons = sum(unit_cartons.values())
        group_cost = sum(unit_cost.values())
        ledger.measure(THROUGHPUT, company_id, period, group_cartons, CARTONS)
        ledger.money(COST_TO_SERVE, company_id, period, group_cost)
        rate_unit = f"{currency}_per_carton"
        ledger.measure(COST_PER_CARTON, company_id, period,
                       _rate(group_cost, group_cartons), rate_unit)
        for unit, estate in network:
            if unit.id not in unit_cartons:
                continue
            ledger.measure(THROUGHPUT, unit.id, period, unit_cartons[unit.id], CARTONS)
            ledger.money(COST_TO_SERVE, unit.id, period, unit_cost[unit.id])
            ledger.measure(COST_PER_CARTON, unit.id, period,
                           _rate(unit_cost[unit.id], unit_cartons[unit.id]), rate_unit)
            for site in estate:
                ledger.measure(THROUGHPUT, site.id, period, site_cartons[site.id], CARTONS)
                ledger.money(COST_TO_SERVE, site.id, period, site_cost[site.id])
                ledger.measure(COST_PER_CARTON, site.id, period,
                               _rate(site_cost[site.id], site_cartons[site.id]),
                               rate_unit)
    else:
        group_cartons = 0
        group_cost = 0

    return EstateCosts(
        facts=tuple(ledger.facts),
        group_overhead=group_overhead if (centre_ids and recharged) else 0,
        group_cartons=group_cartons,
        group_cost_to_serve=group_cost,
    )


__all__ = [
    "ADDITIVE", "CARTONS", "COST_PER_CARTON", "COST_TO_SERVE", "EstateCosts",
    "RATES", "SHARED_COST", "SHARED_RECHARGE", "SHARED_RECOVERY", "SPANS",
    "THROUGHPUT", "distribution_estate", "generate",
]
