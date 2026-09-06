"""The branch-network generator: what a division and a branch actually own.

The measured problem this module exists to close. A one-period banking build
produced **58 facts across 11 documents, and its whole organisation reached
nothing**: three business units, 133 branches and both cost centres were named
by no fact and carried by no document. Retail produces 604 facts from one period
*because* its estate is load-bearing — every store carries revenue, budget and
variance and the workbook reports them. A bank with 133 invisible branches is
the same corpus with the estate turned into scenery, and no reader can ask it a
question about a branch, a division, or what the bank spends running itself.

So this generates the other half of a retail bank's quarterly performance
conversation, beside the capital return: deposits, lending, new lending settled,
income and front-line headcount, by division and by branch, plus the shared
services cost the divisions are recharged for.

Three rules, taken from ``finance.py`` rather than reinvented:

* **A total is drawn once at the top and allocated down.** Group deposits are
  split to divisions and divisions to branches with ``finance.allocate``'s
  largest-remainder, so the roll-up reconciles *exactly* rather than nearly —
  there is no step at which a total is stated and hoped to match.
* **Two decompositions of one total are a cross-check, not two claims.** The
  bank's shared-services cost decomposes by the cost centre that incurs it and,
  independently, by the division it is recharged to; both sum to the same
  figure, which is what makes either checkable.
* **A rate never sums.** Loan-to-deposit is a ratio of the two balances at the
  level it is stated, derived from the rounded amounts, and is minted at group
  and division only. See ``columns.not_summable`` and ``documents._RATE_KINDS``
  for the rule this repository has already paid for twice.

What is *not* modelled, and why:

* **A unit with no branches carries no customer balances.** Treasury and
  Markets earns income and holds no deposit or lending relationship; a mutual's
  wealth arm earns fees. Both are minted income and neither is minted a
  balance, which is the honest statement — the alternative is inventing a
  deposit book for a trading desk. It is retail's "the digital unit had no
  estate" rule, in a bank's vocabulary.
* **A book has no balance.** ``capital.rwa_by_book`` already cuts the balance
  sheet by product book, and a second, independently drawn balance per book
  would be a figure the RWA could disagree with. The balance sheet is cut by
  *branch* here, which is the cut nothing else makes.
* **The operations centre trades nothing and is still staffed.** It carries
  front-line headcount and no money at all, which is why headcount is weighted
  by ``1 + revenue_weight`` rather than by trading scale alone: a site that
  sells nothing still has people in it, and a zero-weight site that carried no
  fact whatsoever would be the invisible-estate defect surviving in miniature.
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

PCT = "pct"
FTE = "fte"


def _n(low: float, high: float, about: str, *, places: int | None = None) -> Span:
    return Span(low, high, "number", places, about)


#: This generator's physics, layered under the caller's by ``_physics`` and
#: registered globally by ``banking.py`` — the seam
#: ``procurement_match.SPANS`` documents, used the same way. Every figure the
#: branch network states is drawn from exactly one of these.
SPANS: dict[str, Span] = {
    "banking.network.average_risk_weight": _n(
        0.34, 0.42, places=3,
        about="Risk-weighted assets over the lending book. What turns the capital"
              " return's RWA into a balance sheet: a mortgage-heavy ADI sits near"
              " a third, a business-lending book nearer a half. This is the one"
              " number that decides how large the bank's loan book is, and it is"
              " read *from* the filed RWA so the two can never disagree.",
    ),
    "banking.network.loan_to_deposit_pct": _n(
        96.0, 112.0, places=1,
        about="Group lending over group deposits. Under 100 the branch network"
              " funds the book on its own; above it the bank is buying the"
              " difference wholesale, which is the single most-quoted funding"
              " number in a retail bank's performance pack.",
    ),
    "banking.network.unit_funding_tilt": _n(
        0.88, 1.14, places=3,
        about="How far one division's funding mix departs from the group's. A"
              " business bank lends more than it gathers and a branch network"
              " gathers more than it lends, so a single group ratio applied to"
              " every division would make the divisional loan-to-deposit column"
              " a constant — a rate that never varies is a rate nobody reads.",
    ),
    "banking.network.site_funding_tilt": _n(
        0.82, 1.20, places=3,
        about="The same departure at branch level. Two branches of equal size do"
              " not hold equal deposits: a suburban branch funds itself and a"
              " growth-corridor branch does not.",
    ),
    "banking.network.settlement_rate": _n(
        0.042, 0.078, places=4,
        about="New lending settled in the quarter as a share of the closing"
              " lending balance. Turnover of the book — how much of a branch's"
              " loan portfolio it wrote this quarter rather than inherited.",
    ),
    "banking.network.income_quarter_pct": _n(
        0.94, 1.06, places=3,
        about="This quarter's net operating income against a flat quarter of the"
              " company's stated annual income. A bank's year has no December"
              " peak — its revenue is a book, not a till — so the variation is"
              " small and is what makes one quarter distinguishable from the"
              " next in a multi-period build.",
    ),
    "banking.network.fte_per_site_weight": _n(
        4.0, 7.0, places=2,
        about="Front-line headcount per unit of site weight, where a plain branch"
              " weighs two — one for being open and one for what it trades. So"
              " the band puts eight to fourteen people in a branch and half"
              " again as many in a business banking centre. Drawn as a rate and"
              " multiplied up rather than drawn as a network total, because a"
              " total divided by 133 branches is how a corpus ends up staffing a"
              " suburban branch with fifty people. The product is still one draw"
              " allocated down.",
    ),
    "banking.network.shared_services_pct": _n(
        0.09, 0.15, places=4,
        about="The shared-services cost base as a share of net operating income."
              " What finance, treasury, risk and the data platform cost the bank"
              " before any of it is recharged to a division.",
    ),
    "banking.network.cost_centre_weight": _n(
        0.75, 1.45, places=3,
        about="One cost centre's size relative to its peers. A cost centre has no"
              " size field on it — it is a place costs are booked, not a place"
              " that trades — so its share of the shared-services base is drawn"
              " from a stream named for the centre itself.",
    ),
}


def _physics(physics: Parameters) -> Parameters:
    """*physics* with this generator's own spans available.

    Layered *under* the caller's, never over — ``procurement_match._physics``,
    verbatim, and for its reason: a caller who has already stated one of these
    names means it.
    """
    if all(name in physics.spans for name in SPANS):
        return physics
    return Parameters({**SPANS, **dict(physics.spans)})


@dataclass(frozen=True)
class Network:
    """One quarter of divisional and branch performance, as facts.

    ``facts`` is everything minted, in mint order. ``empty`` is the honest
    answer for a bank whose archetype declares no estate at all: nothing is
    minted, and the caller plans no performance pack rather than planning one
    with no rows in it — the "empty Store Performance tab" argument
    ``documents.finance_workbook`` makes, in this vertical.
    """

    facts: tuple[CanonicalFact, ...]
    group_deposits: int
    group_lending: int
    group_income: int
    group_shared_cost: int

    @property
    def empty(self) -> bool:
        return not self.facts


class _Ledger:
    """Accumulates facts, so the generator below reads as arithmetic.

    ``finance._Ledger``'s shape, not an import: that one is private to the
    shared retail generator and threading a second money unit and a second
    authority through it would make a read-only module answerable to banking.
    """

    def __init__(self, minter: Minter, *, at: datetime, event: str,
                 source: str, money_unit: str) -> None:
        self.minter = minter
        self.facts: list[CanonicalFact] = []
        self.at = at
        self.event = event
        self.source = source
        self.money_unit = money_unit

    def measure(self, kind: str, subject: str, period: str,
                amount: float, unit: str) -> CanonicalFact:
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
        )
        self.facts.append(fact)
        return fact

    def money(self, kind: str, subject: str, period: str, amount: int) -> CanonicalFact:
        return self.measure(kind, subject, period, amount, self.money_unit)


def _ratio_pct(numerator: int, denominator: int) -> float:
    """A stated ratio, derived from the rounded amounts it describes.

    Two decimals, and derived rather than carried down from the draw: a reader
    who divides the two balances on the sheet must get the number the sheet
    states, and the draw is a target the allocation has already rounded away
    from.
    """
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    units: Sequence[BusinessUnit],
    sites: Sequence[Site],
    cost_centres: Sequence[CostCentre],
    unit_share_of: dict[str, float],
    rwa_total: int,
    annual_income: int,
    employees_total: int,
    at: datetime,
    event_id: str,
    source_system: str,
    money_unit: str,
    physics: Parameters = DEFAULT,
) -> Network:
    """One quarter of the branch network, allocated from group totals.

    ``rwa_total`` is the quarter's filed risk-weighted assets: the balance sheet
    is derived *from* it rather than beside it, so the lending book a branch
    reports and the capital the bank holds against it are one number seen twice.

    ``unit_share_of`` maps a business-unit id to its share of group income — the
    archetype's own ``UnitSpec.share`` — and is what makes income decompose to
    every division including the ones with no branches.

    ``annual_income`` is the company's stated annual net operating income; a
    quarter is a flat quarter of it, moved by one draw. Banking has no trading
    year (``profiles.PROFILES["flat"]`` is the right answer for a business whose
    revenue is a book rather than a till), so there is no seasonal index here
    and none is wanted.
    """
    physics = _physics(physics)

    # Sites that trade, by unit, and every site by unit. The two lists differ by
    # exactly the zero-weight sites — an operations centre holds work, not
    # income — and both are needed: money decomposes over the first, headcount
    # over the second. `finance.generate` drops zero-weight sites outright,
    # which is right for a store P&L and would leave this bank's operations
    # centre reaching nothing at all.
    trading_of: dict[str, list[Site]] = {}
    staffed_of: dict[str, list[Site]] = {}
    for unit in units:
        estate = [s for s in sites if s.business_unit_id == unit.id]
        staffed_of[unit.id] = estate
        trading_of[unit.id] = [s for s in estate if s.revenue_weight > 0]

    # A division holds customer balances when it has branches to hold them in.
    # Stated as a property of the estate rather than of the archetype's unit
    # keys, because a pack names its own divisions: `unit.key == "treasury"` is
    # exactly the assumption `regulatory.generate`'s `affected_unit_id` was
    # rewritten to stop making.
    balance_units = [unit for unit in units if trading_of[unit.id]]
    income_units = list(units)
    if not balance_units:
        # No estate at all: mint nothing rather than mint a group balance sheet
        # with no division under it. A corpus whose only deposit fact is the
        # group's would reach no more of the organisation than it did before.
        return Network(facts=(), group_deposits=0, group_lending=0,
                       group_income=0, group_shared_cost=0)

    ledger = _Ledger(minter, at=at, event=event_id, source=source_system,
                     money_unit=money_unit)

    # -- the group totals, each drawn exactly once --------------------------
    risk_weight = physics.number("banking.network.average_risk_weight",
                                 rng.derive("risk_weight"))
    group_lending = int(round(rwa_total / risk_weight, -1))
    ltd_target = physics.number("banking.network.loan_to_deposit_pct",
                                rng.derive("loan_to_deposit"))
    group_deposits = int(round(group_lending / (ltd_target / 100), -1))
    group_income = round(
        annual_income / 4
        * physics.number("banking.network.income_quarter_pct", rng.derive("income"))
    )
    group_settled = int(round(
        group_lending
        * physics.number("banking.network.settlement_rate", rng.derive("settlement")),
        -1,
    ))
    group_shared_cost = round(
        group_income
        * physics.number("banking.network.shared_services_pct", rng.derive("shared_services"))
    )

    # -- income: every division, then every trading branch -------------------
    income_weights = [max(unit_share_of.get(unit.id, 0.0), 1e-9) for unit in income_units]
    income_by_unit = dict(zip(
        (unit.id for unit in income_units), allocate(group_income, income_weights)
    ))

    # -- balances: the divisions with an estate, tilted by funding mix -------
    # A division's balance weight is its income share; its *deposit* weight is
    # that share divided by its funding tilt and its *lending* weight the same
    # share multiplied by it. One tilt moves both sides in opposite directions,
    # which is what a funding mix is — a division cannot be simultaneously more
    # deposit-rich and more lending-heavy than the group.
    unit_tilt = {
        unit.id: physics.number("banking.network.unit_funding_tilt",
                                rng.derive(f"unit_tilt/{unit.id}"))
        for unit in balance_units
    }
    balance_share = {
        unit.id: max(unit_share_of.get(unit.id, 0.0), 1e-9) for unit in balance_units
    }
    balance_ids = [unit.id for unit in balance_units]
    deposits_by_unit = dict(zip(balance_ids, allocate(
        group_deposits, [balance_share[u] / unit_tilt[u] for u in balance_ids]
    )))
    lending_by_unit = dict(zip(balance_ids, allocate(
        group_lending, [balance_share[u] * unit_tilt[u] for u in balance_ids]
    )))
    # New lending follows the book it was written into, not the deposits beside
    # it, so it is allocated on the lending weights rather than drawn per
    # division: a settlement figure that did not track the balance it grows
    # would be a second, unexplained claim about the same book.
    settled_by_unit = dict(zip(balance_ids, allocate(
        group_settled, [balance_share[u] * unit_tilt[u] for u in balance_ids]
    )))

    # -- front-line headcount ------------------------------------------------
    # Weighted by `1 + revenue_weight`: every site needs people because it is
    # open, and more of them the more it trades. The group figure is the rate
    # multiplied by the estate's total weight and is then allocated down like
    # any other total, so the draw is still one draw and the roll-up is still
    # exact.
    site_staff_weight = {s.id: 1.0 + s.revenue_weight for s in sites}
    staffed_units = [unit for unit in units if staffed_of[unit.id]]
    estate_weight = sum(
        site_staff_weight[s.id] for unit in staffed_units for s in staffed_of[unit.id]
    )
    group_fte = round(
        estate_weight
        * physics.number("banking.network.fte_per_site_weight", rng.derive("fte"))
    )
    # The network cannot be larger than the bank. Binds only for a pack whose
    # stated headcount is small against its estate; the shipped ADI draws about
    # a quarter of its people into the network, which is what a bank with a
    # head office, an operations centre and a technology division looks like.
    group_fte = min(group_fte, int(employees_total * 0.8))
    staffed_ids = [unit.id for unit in staffed_units]
    fte_by_unit = dict(zip(staffed_ids, allocate(
        group_fte,
        [sum(site_staff_weight[s.id] for s in staffed_of[u]) for u in staffed_ids],
    )))

    # -- shared services, decomposed twice -----------------------------------
    centre_ids = [centre.id for centre in cost_centres]
    cost_by_centre = dict(zip(centre_ids, allocate(
        group_shared_cost,
        [physics.number("banking.network.cost_centre_weight",
                        rng.derive(f"cost_centre/{cid}")) for cid in centre_ids],
    ))) if centre_ids else {}
    # Recharged on income share, which is the basis a bank actually uses and is
    # also why this is a genuine second decomposition rather than a relabelling
    # of the first: the centres that *incur* the cost and the divisions that
    # *carry* it are different sets of entities summing to one number.
    recharge_by_unit = dict(zip(
        (unit.id for unit in income_units), allocate(group_shared_cost, income_weights)
    ))

    # -- minted, group first, then division, then branch ---------------------
    # Group before division before branch so a reader of the raw ledger meets
    # the total before its parts, and so a truncated read is a coarser view
    # rather than a partial one.
    ledger.money("banking.deposits.balance", company_id, period, group_deposits)
    ledger.money("banking.lending.balance", company_id, period, group_lending)
    ledger.money("banking.lending.settled", company_id, period, group_settled)
    ledger.money("banking.net_operating_income", company_id, period, group_income)
    ledger.measure("banking.network.fte", company_id, period, group_fte, FTE)
    ledger.measure("banking.loan_to_deposit_pct", company_id, period,
                   _ratio_pct(group_lending, group_deposits), PCT)

    for unit in income_units:
        ledger.money("banking.net_operating_income", unit.id, period, income_by_unit[unit.id])
    for unit in balance_units:
        ledger.money("banking.deposits.balance", unit.id, period, deposits_by_unit[unit.id])
        ledger.money("banking.lending.balance", unit.id, period, lending_by_unit[unit.id])
        ledger.money("banking.lending.settled", unit.id, period, settled_by_unit[unit.id])
        ledger.measure("banking.loan_to_deposit_pct", unit.id, period,
                       _ratio_pct(lending_by_unit[unit.id], deposits_by_unit[unit.id]), PCT)
    for unit in staffed_units:
        ledger.measure("banking.network.fte", unit.id, period, fte_by_unit[unit.id], FTE)

    for unit in balance_units:
        estate = trading_of[unit.id]
        tilt = {
            s.id: physics.number("banking.network.site_funding_tilt",
                                 rng.derive(f"site_tilt/{s.id}"))
            for s in estate
        }
        trading_weight = [s.revenue_weight for s in estate]
        deposit_weight = [s.revenue_weight / tilt[s.id] for s in estate]
        lending_weight = [s.revenue_weight * tilt[s.id] for s in estate]
        for site, amount in zip(estate, allocate(deposits_by_unit[unit.id], deposit_weight)):
            ledger.money("banking.deposits.balance", site.id, period, amount)
        for site, amount in zip(estate, allocate(lending_by_unit[unit.id], lending_weight)):
            ledger.money("banking.lending.balance", site.id, period, amount)
        for site, amount in zip(estate, allocate(settled_by_unit[unit.id], lending_weight)):
            ledger.money("banking.lending.settled", site.id, period, amount)
        for site, amount in zip(estate, allocate(income_by_unit[unit.id], trading_weight)):
            ledger.money("banking.net_operating_income", site.id, period, amount)

    for unit in staffed_units:
        estate = staffed_of[unit.id]
        for site, count in zip(estate, allocate(
            fte_by_unit[unit.id], [site_staff_weight[s.id] for s in estate]
        )):
            ledger.measure("banking.network.fte", site.id, period, count, FTE)

    ledger.money("banking.shared_services_cost", company_id, period, group_shared_cost)
    for centre_id in centre_ids:
        ledger.money("banking.shared_services_cost", centre_id, period, cost_by_centre[centre_id])
    for unit in income_units:
        ledger.money("banking.shared_services_recharge", unit.id, period,
                     recharge_by_unit[unit.id])

    return Network(
        facts=tuple(ledger.facts),
        group_deposits=group_deposits,
        group_lending=group_lending,
        group_income=group_income,
        group_shared_cost=group_shared_cost,
    )
