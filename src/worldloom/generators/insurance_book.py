"""The insurer's book, cut by the organisation that actually writes it.

The measured problem this module exists to close. A one-period build of the
insurance vertical produced **62 facts and four documents**, and its entire
organisational spine reached none of them: three business units, twenty
branches, three claims centres, six underwriting offices, five systems and two
cost centres were declared by the archetype, minted into the world, named by no
fact and carried by no document. Retail produces 604 facts from one period
*because* its estate is load-bearing; here the estate was scenery.

``reserves.*`` could not close that gap and must not be asked to. A reserve is
already cut by accident quarter over a cohort axis — the deliberate pun on
``fact.period`` that ``worldloom.insurance``'s docstring records — so cutting it
a second time by site would put two incompatible decompositions on one
vocabulary and make "which quarter is this" ambiguous on every ``reserves.``
fact. So this module asks the other question instead: **what does a place
own?**

* An **underwriting office or branch** writes premium, and carries a book of
  policies while it does. Both are the site's own, and both decompose their
  unit exactly the way retail's stores decompose a division.
* A **claims centre** writes no premium at all. The archetype says so already —
  ``SiteFormat("Claims Centre", 3, 0.0)``, the same zero-weight shape a
  distribution centre carries — and the shipped comment beside it ("a claims
  centre processes claims, not premium") is the design being followed here
  rather than a description being repeated. It owns the operational claims
  counts: notified and settled, never reserved, because reserving is the cohort
  axis's business and this module does not touch it.
* A **cost centre** owns operating expense, which is the only thing a cost
  centre has ever been for.
* A **system of record** owns the count of records it is the system of record
  for. ``System.is_system_of_record_for`` was a declared field that nothing in
  this repository read.

Two disciplines are taken from ``generators/finance.py`` verbatim, because they
are the reason a roll-up here reconciles by construction rather than nearly:

1. **A total is drawn once and split, never drawn per row and summed.** Unit
   premium is drawn per unit and the *group* figure is their sum; line-of-
   business and site figures are ``finance.allocate``'d down from the unit
   total by largest remainder. Two independent decompositions of one unit total
   are a real cross-check; two independently drawn ones are two contradictions.
2. **A zero-weight site gets no row rather than a zero row.** A claims centre
   with a premium line of 0 reads as an office that sold nothing, which is a
   different claim from "this place does not sell".

One measure legitimately builds the other way, and the direction is decided by
where the number is owned rather than by taste: **policies in force is drawn
per site and summed upward**. A branch's book is a property of the branch, not
a share of a group figure handed down to it — and ``finance.py``'s rule is that
a parent is a *sum* and never an independent draw, which is exactly what
summing upward satisfies. Allocation is what you do when the parent was drawn
first; there is no group policy count to draw.

**No rate is minted anywhere in here.** A loss ratio, an expense ratio and a
combined ratio are all ratios of totals and never totals of ratios, so a
site-level or cost-centre-level rate would produce a subtotal row stating a
number three times any of its children — the rule ``columns.py``'s
``not_summable`` and ``documents._RATE_KINDS`` already record, and which this
repository has paid for twice. The workbook derives the ratios it wants from
the amounts, in the sheet, where a subtotal cannot add them up.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..ids import Minter
from ..models import (
    Authority,
    CanonicalFact,
    Category,
    CostCentre,
    EnterpriseEvent,
    Quantity,
    Site,
    System,
)
from ..parameters import DEFAULT, Parameters, Span
from ..rng import Rng
from .finance import allocate

COUNT = "records"
POLICIES = "policies"
CLAIMS = "claims"

#: This module's physics, registered into the global registry by
#: ``worldloom.insurance`` through ``parameters.register``. Registered rather
#: than kept module-private so ``worldloom pack params`` lists them and a pack
#: can tune what kind of insurer this is.
#:
#: Namespaced ``book.<subject>.<measure>``, which ``tests/test_parameters.py``
#: requires of every name: a flat namespace would put four industries' physics
#: in one undifferentiated table. ``book.`` rather than ``reserves.`` because
#: these decide the size of the *company*, and the reserving parameters decide
#: the size of one long-tail book inside it — two different claims, and a pack
#: tuning one should not have to think about the other.
SPANS: dict[str, Span] = {
    "book.premium.miss_pct": Span(
        low=-0.062, high=0.031, kind="number", places=4,
        about="How far a unit's written premium lands from its own plan."
              " Skewed adverse, like retail's `retail.revenue.miss_pct`: a"
              " quarter in which every division beat plan is not the quarter"
              " anybody writes a memo about.",
    ),
    "book.portfolio.office_policies": Span(
        low=3_400, high=14_800, kind="integer",
        about="The book of policies one underwriting office or branch carries"
              " into the valuation. Drawn per site and summed upward, because a"
              " branch's book is the branch's own rather than a share of a group"
              " number — see this module's docstring on which direction each"
              " measure reconciles in.",
    ),
    "book.claims.notification_rate": Span(
        low=0.021, high=0.038, kind="number", places=4,
        about="Claims notified in the quarter as a fraction of the policies in"
              " force behind them. A general insurer's quarterly notification"
              " frequency; the long tail is in how they develop, not in how"
              " many arrive.",
    ),
    "book.claims.settlement_rate": Span(
        low=0.78, high=0.93, kind="number", places=4,
        about="Claims settled in the quarter as a fraction of those notified."
              " Below 1.0 by construction — a claims function that closed"
              " everything it opened would have no open portfolio for the"
              " reserving cycle to be about.",
    ),
    "book.claims.centre_caseload": Span(
        low=0.62, high=1.55, kind="number", places=4,
        about="One claims centre's share weight of its unit's caseload. A"
              " weight rather than a count: the unit total is drawn first and"
              " allocated, so the centres reconcile to it exactly.",
    ),
    "book.expense.operating_ratio": Span(
        low=0.215, high=0.284, kind="number", places=4,
        about="Group operating expense as a fraction of the quarter's revenue."
              " Stated as a ratio here and minted only as an *amount*: the"
              " expense ratio is a ratio of totals and would not sum if it were"
              " cut by cost centre.",
    ),
    "book.expense.cost_centre_weight": Span(
        low=0.74, high=1.42, kind="number", places=4,
        about="One cost centre's share weight of group operating expense.",
    ),
    "book.systems.records_held": Span(
        low=9_000, high=1_400_000, kind="integer",
        about="How many records a system holds for the domain it is the system"
              " of record for. Wide because the domains are: a treaty register"
              " and a general ledger are the same kind of claim about very"
              " different orders of magnitude.",
    ),
}


@dataclass(frozen=True)
class UnderwritingBook:
    """One quarter of the book, cut by the organisation that wrote it."""

    events: tuple[EnterpriseEvent, ...]
    facts: tuple[CanonicalFact, ...]
    period: str
    keys: dict[str, str]
    """Named handles for the events documents cite. Facts are addressed by
    ``(kind, subject)`` through ``ids_for`` instead — there are 157 of them and
    a key per fact would be a second, hand-maintained copy of the ledger."""

    def ids_for(self, *kinds: str, subjects: tuple[str, ...] | None = None) -> list[str]:
        """Fact ids of *kinds*, in mint order, optionally narrowed to *subjects*.

        Mint order rather than sorted: ``ArtifactIntent.required_fact_ids`` is
        compared byte-for-byte on replay, and a set's iteration order is not
        stable across processes.
        """
        wanted = None if subjects is None else set(subjects)
        return [
            fact.id for fact in self.facts
            if fact.kind in kinds and (wanted is None or fact.subject in wanted)
        ]


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    unit_ids: dict[str, str],
    unit_shares: dict[str, float],
    categories: tuple[Category, ...],
    sites: tuple[Site, ...],
    cost_centres: tuple[CostCentre, ...],
    systems: tuple[System, ...],
    quarterly_revenue: int,
    money_unit: str,
    recorded_at: datetime,
    caused_by: list[str],
    lore_by_target: dict[str, list[str]],
    policy_admin_id: str,
    claims_system_id: str,
    general_ledger_id: str,
    physics: Parameters = DEFAULT,
) -> UnderwritingBook:
    """Cut one quarter's book by unit, line of business, office and cost centre.

    ``quarterly_revenue`` is the archetype's own annual figure divided by four —
    passed in already divided, because how many periods a year holds is the
    episode's arithmetic and not this generator's.

    ``unit_shares`` are the archetype's declared shares of group revenue, used
    unchanged. That matters for what the group line *means*: the two
    underwriting units book gross written premium and Group Investments books
    investment income, so the group figure is an insurer's total revenue rather
    than its premium. Splitting the two into separate vocabularies was the
    alternative and it costs more than it buys — the shares are already declared
    against one denominator, and a second denominator would make "what share of
    the group is Personal Lines" have two answers.

    ``financial.revenue.*`` is deliberately the shared vocabulary rather than a
    ``premium.*`` of this vertical's own. ``validate.financial`` — the single
    most important check in the project — reconciles units to the group,
    categories to their unit, sites to their unit, and variance to actual less
    budget, and it does all four by fact-kind prefix. Minting a private kind
    would have meant writing a second reconciler beside the first, which is two
    checkers that can disagree about one arithmetic. ``procurement_cycle.py``
    already mints ``financial.accrual.grni`` on the same argument and states it
    in the same words: ``financial.`` is shared vocabulary.
    """
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}

    def event(kind: str, at: datetime, summary: str, *, actors: Sequence[str] = (),
              systems_: Sequence[str] = (), because: Sequence[str] = ()) -> EnterpriseEvent:
        made = EnterpriseEvent(id=minter.next("EV"), kind=kind, occurred_at=at,
                               summary=summary, actors=list(actors), systems=list(systems_),
                               caused_by=list(because))
        events.append(made)
        keys[f"event_{kind}"] = made.id
        return made

    def fact(kind: str, subject: str, amount: float, unit: str, *, source: str,
             event_id: str, lore: list[str] | None = None) -> CanonicalFact:
        made = CanonicalFact(
            id=minter.next("FACT"), kind=kind, subject=subject, period=period,
            value=Quantity(amount=amount, unit=unit), valid_from=recorded_at,
            authority=Authority.SYSTEM_OF_RECORD, source_system=source,
            event_id=event_id, lore_ids=lore or [],
        )
        facts.append(made)
        return made

    recorded = event(
        "book_position_recorded", recorded_at,
        "The quarter's written premium, policies in force, claims handled and "
        "operating expense were cut by business unit, line of business, "
        "underwriting office, claims centre and cost centre.",
        systems_=[policy_admin_id, claims_system_id, general_ledger_id],
        because=caused_by,
    )
    at = recorded.id

    # -- who writes what ----------------------------------------------------
    # Two lookups, both filtered the way `finance.generate` filters its own: a
    # unit the archetype gave no books gets no line rows, and a site the
    # archetype gave no revenue weight gets no premium row at all. The second
    # is what keeps the three claims centres off the premium sheet — they
    # process claims and write none, and a row of zeroes beside twenty branches
    # would state that they tried and failed to.
    lines_of: dict[str, list[Category]] = {unit_id: [] for unit_id in unit_ids.values()}
    for category in categories:
        if category.business_unit_id in lines_of:
            lines_of[category.business_unit_id].append(category)

    # The split is on `revenue_weight`, not on `format`, and that is the point
    # rather than a shortcut. A format name is a label a pack author chose —
    # "Claims Centre", "Service Centre", "Claims Hub" — and branching on it
    # would mean this generator holding a list of the words it recognises and
    # silently doing nothing for the ones it does not. The weight is the
    # archetype's *declaration* that a place does not sell, which is the claim
    # actually being read here: in an insurer, a site that writes no premium is
    # where claims are handled.
    offices_of: dict[str, list[Site]] = {unit_id: [] for unit_id in unit_ids.values()}
    centres_of: dict[str, list[Site]] = {unit_id: [] for unit_id in unit_ids.values()}
    for site in sites:
        if site.business_unit_id not in offices_of:
            continue
        if site.revenue_weight > 0:
            offices_of[site.business_unit_id].append(site)
        else:
            centres_of[site.business_unit_id].append(site)

    # -- written premium, drawn per unit and split downward ------------------
    budget: dict[str, int] = {}
    actual: dict[str, int] = {}
    for key in unit_ids:
        unit_rng = rng.derive(f"premium/{key}")
        unit_budget = round(quarterly_revenue * unit_shares[key])
        miss = physics.number("book.premium.miss_pct", unit_rng)
        budget[key] = unit_budget
        actual[key] = round(unit_budget * (1 + miss))

    # The group is the sum, never a draw. `quarterly_revenue` is what the units
    # were *sized from*; stating it as the group figure would leave the group
    # off by the rounding of three shares and by the whole of the miss.
    group_budget = sum(budget.values())
    group_actual = sum(actual.values())

    for basis, per_unit, group_total in (
        ("budget", budget, group_budget),
        ("actual", actual, group_actual),
    ):
        kind = f"financial.revenue.{basis}"
        for key, unit_id in unit_ids.items():
            members = lines_of[unit_id]
            if members:
                shares = allocate(per_unit[key], [c.revenue_share for c in members])
                for category, amount in zip(members, shares):
                    fact(kind, category.id, amount, money_unit,
                         source=policy_admin_id, event_id=at)
            estate = offices_of[unit_id]
            if estate:
                shares = allocate(per_unit[key], [s.revenue_weight for s in estate])
                for site, amount in zip(estate, shares):
                    fact(kind, site.id, amount, money_unit,
                         source=policy_admin_id, event_id=at)
            fact(kind, unit_id, per_unit[key], money_unit,
                 source=policy_admin_id, event_id=at)
        fact(kind, company_id, group_total, money_unit,
             source=general_ledger_id, event_id=at)

    # Variance is a difference at every level, and the differences of two exact
    # allocations are themselves exact — which is why it is allocated from the
    # two allocations rather than allocated in its own right. Allocating the
    # unit variance directly would put the largest remainder on a different row
    # from the one that carried it in actual, and the sheet's `=actual-budget`
    # would disagree with the fact by a unit.
    for key, unit_id in unit_ids.items():
        members = lines_of[unit_id]
        if members:
            weights = [c.revenue_share for c in members]
            gaps = [a - b for a, b in zip(allocate(actual[key], weights),
                                          allocate(budget[key], weights))]
            for category, gap in zip(members, gaps):
                fact("financial.revenue.variance", category.id, gap, money_unit,
                     source=policy_admin_id, event_id=at)
        estate = offices_of[unit_id]
        if estate:
            weights = [s.revenue_weight for s in estate]
            gaps = [a - b for a, b in zip(allocate(actual[key], weights),
                                          allocate(budget[key], weights))]
            for site, gap in zip(estate, gaps):
                fact("financial.revenue.variance", site.id, gap, money_unit,
                     source=policy_admin_id, event_id=at)
        fact("financial.revenue.variance", unit_id, actual[key] - budget[key], money_unit,
             source=policy_admin_id, event_id=at,
             lore=lore_by_target.get(f"written_premium/{key}", []))
    fact("financial.revenue.variance", company_id, group_actual - group_budget, money_unit,
         source=general_ledger_id, event_id=at)

    # -- policies in force, drawn per office and summed upward --------------
    policies_of_unit: dict[str, int] = {}
    for _key, unit_id in unit_ids.items():
        estate = offices_of[unit_id]
        if not estate:
            continue
        book = 0
        for site in estate:
            held = physics.integer(
                "book.portfolio.office_policies", rng.derive(f"policies/{site.id}")
            )
            fact("portfolio.policies_in_force", site.id, held, POLICIES,
                 source=policy_admin_id, event_id=at)
            book += held
        policies_of_unit[unit_id] = book
        fact("portfolio.policies_in_force", unit_id, book, POLICIES,
             source=policy_admin_id, event_id=at)
    if policies_of_unit:
        fact("portfolio.policies_in_force", company_id, sum(policies_of_unit.values()),
             POLICIES, source=policy_admin_id, event_id=at)

    # -- claims handled, from the book behind them --------------------------
    # Derived from policies in force rather than drawn free, so a unit that
    # writes more business also notifies more claims. Only the units that were
    # given a claims centre split their figure by site: Commercial Lines
    # notifies claims and has no dedicated centre to handle them in, which is
    # the archetype's own statement about how this insurer is arranged, not an
    # omission this generator gets to fill in with an invented place.
    notified_of_unit: dict[str, int] = {}
    settled_of_unit: dict[str, int] = {}
    for key, unit_id in unit_ids.items():
        book = policies_of_unit.get(unit_id)
        if not book:
            continue
        claims_rng = rng.derive(f"claims/{key}")
        notified = round(book * physics.number("book.claims.notification_rate", claims_rng))
        settled = round(notified * physics.number("book.claims.settlement_rate", claims_rng))
        notified_of_unit[unit_id] = notified
        settled_of_unit[unit_id] = settled

        centres = centres_of[unit_id]
        if centres:
            weights = [
                physics.number("book.claims.centre_caseload", rng.derive(f"caseload/{site.id}"))
                for site in centres
            ]
            for site, count in zip(centres, allocate(notified, weights)):
                fact("claims_ops.notified_count", site.id, count, CLAIMS,
                     source=claims_system_id, event_id=at)
            for site, count in zip(centres, allocate(settled, weights)):
                fact("claims_ops.settled_count", site.id, count, CLAIMS,
                     source=claims_system_id, event_id=at)
        fact("claims_ops.notified_count", unit_id, notified, CLAIMS,
             source=claims_system_id, event_id=at)
        fact("claims_ops.settled_count", unit_id, settled, CLAIMS,
             source=claims_system_id, event_id=at)
    if notified_of_unit:
        fact("claims_ops.notified_count", company_id, sum(notified_of_unit.values()),
             CLAIMS, source=claims_system_id, event_id=at)
        fact("claims_ops.settled_count", company_id, sum(settled_of_unit.values()),
             CLAIMS, source=claims_system_id, event_id=at)

    # -- operating expense, by cost centre ----------------------------------
    # Drawn at group and allocated down, the opposite direction from policies
    # in force and for the reason stated in the module docstring: a shared
    # service centre's cost is a share of what the group spends to run itself,
    # not a figure the centre sets on its own.
    if cost_centres:
        total = round(group_actual * physics.number(
            "book.expense.operating_ratio", rng.derive("expense")))
        weights = [
            physics.number("book.expense.cost_centre_weight", rng.derive(f"expense/{cc.id}"))
            for cc in cost_centres
        ]
        for centre, amount in zip(cost_centres, allocate(total, weights)):
            fact("expense.operating", centre.id, amount, money_unit,
                 source=general_ledger_id, event_id=at)
        fact("expense.operating", company_id, total, money_unit,
             source=general_ledger_id, event_id=at)

    # -- what each system of record actually holds --------------------------
    # `System.is_system_of_record_for` has been a declared field since this
    # vertical shipped and nothing read it. A system that is the system of
    # record for something holds a countable number of records of it, and that
    # count is the one measure every system in this world owns — which is why
    # this is one kind across five systems rather than five kinds.
    for system in systems:
        if not system.is_system_of_record_for:
            continue
        fact("data.records_of_record", system.id,
             physics.integer("book.systems.records_held", rng.derive(f"records/{system.id}")),
             COUNT, source=system.id, event_id=at)

    return UnderwritingBook(
        events=tuple(events), facts=tuple(facts), period=period, keys=keys,
    )


__all__ = ["SPANS", "UnderwritingBook", "generate"]
