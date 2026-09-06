"""Procurement scenarios.

``PurchaseToPayCycle`` is an ordinary frozen dataclass with a ``run`` method,
exactly as ``scenarios.py``'s docstring prescribes and as
``QuarterlyCapitalReturn`` and ``QuarterlyReserving`` already exercise — the
fourth data point, not a new pattern.

What repeats, reused rather than re-invented: the lore index, ``period_end``
and the business-day arithmetic, the recipe step registration, the
standing-fact resolution shape (``existing_minimum`` in ``regulatory.py``),
and the extend/derive shape every scenario's ``run`` has. What does not
repeat: the cycle itself, which lives in ``generators/procurement_cycle.py``
and ``generators/procurement_match.py``.

**One run, two generators, and they answer different questions.** The cycle is
one purchase order and the three documents that disagree about it;
``generators/procurement_estate.py`` is the company that order was raised
inside — what each division buys in, what it has committed, what sits in the
yards. They are separate because their inputs are: the cycle's figures come
from a drawn quantity and a rate card, the estate's from the group's own
revenue, and a corpus that had sized the second from the first would have made
a contractor's whole cost base a function of one subcontract package. They
share a date and an event, so the position is the position at the close the
cycle finished.

**What does not repeat and should have: the multi-period guard.**
``QuarterlyReserving`` refuses a second run on one world, so the insurance
vertical is capped at a single period and cannot reach any scale. This
scenario runs over a history by construction, and the reason it can is that
every fact it carries between months is resolved from the *world's own
record* rather than from a counter threaded through the recipe — the standing
rate card, the delegation of authority, the counterparty, the undelivered
balance left at the previous close, and the order book that close struck. That
is the ``prior_incident_periods`` pattern ``operations.generate`` already
uses, applied to five things instead of one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .parameters import DEFAULT, Parameters
from .recipe import locale_of
from .rng import Rng
from .scenarios import lore_index

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


@dataclass(frozen=True)
class PurchaseToPayCycle:
    """One monthly purchase cycle: order, receipt, invoice, a failed three-way
    match, an escalation past the approval tolerance, and the accrual the close
    carries.

    ``period`` is the month as ``YYYY-MM`` — the same ``period_end`` /
    ``previous_periods`` arithmetic every other scenario uses.

    Consecutive runs on one world are supported and are the point. Month *N*
    prices its order at the rate card month 1 agreed, clears month *N-1*'s
    undelivered balance as an ordinary receipt, and leaves its own — so a
    corpus of six months carries six closes whose accruals differ for reasons
    the corpus itself records, rather than six copies of one month.
    """

    period: str
    physics: Parameters = DEFAULT
    """The world physics this month's figures are drawn under. A field with a
    default rather than a ``run`` argument, so it reaches the generators the
    same way ``period`` does and a caller that has one states it once."""

    def run(self, world: World) -> World:
        from . import procurement_documents
        from .generators import (
            cases,
            procurement_cycle,
            procurement_estate,
            procurement_evaluation,
            procurement_match,
        )
        from .generators.finance import previous_periods

        if world.seed is None:
            raise ValueError(
                "a scenario needs a seeded world; use ProcureToPayWorld(seed=...).build()"
            )
        if world._minter is None:
            raise ValueError(
                "this world was loaded from disk and cannot be advanced; build one from a seed"
            )
        if world._archetype is None:
            raise ValueError("this world has no archetype; build one with ProcureToPayWorld(...)")

        roles = dict(world._roles)
        if "cat_contested_line" not in roles or "cat_clean_line" not in roles:
            raise ValueError(
                "this world has no spend categories to raise an order against;"
                " PurchaseToPayCycle runs against a procurement archetype"
            )

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}")
        minter = world._minter
        index = lore_index(world)
        company_id = world.company.id
        contested_id, clean_id = roles["cat_contested_line"], roles["cat_clean_line"]

        # Everything a later month inherits from an earlier one, resolved from
        # the world before anything is generated — `regulatory.generate`'s
        # `existing_minimum` pattern, four times over. `period=None` on all but
        # the shortfall: a rate card, a delegation and a counterparty do not
        # belong to a month, and a lookup scoped to one would never find them.
        existing_rates = {
            category: fact
            for category in (contested_id, clean_id)
            for fact in (world.authoritative("p2p.contract_rate", category),)
            if fact is not None
        }
        existing_counterparty = {
            category: fact
            for category in (contested_id, clean_id)
            for fact in (world.authoritative("p2p.contract_counterparty", category),)
            if fact is not None
        }
        existing_tolerance = world.authoritative("p2p.approval_tolerance_pct", company_id)
        existing_vendor_change = world.authoritative("p2p.vendor_change_status", company_id)

        # The undelivered balance the *previous* month closed with. Scoped to
        # that month explicitly rather than taken as "the latest": every
        # month's shortfall fact stays open forever (they are per-period
        # snapshots, like `reserves.booked_total`), so an unscoped lookup would
        # find whichever one sorted last and quietly release the wrong balance.
        prior_period = previous_periods(self.period, 1)[0]
        prior_shortfall_value = world.authoritative(
            "p2p.open_shortfall_value", company_id, period=prior_period)
        prior_shortfall_quantity = world.authoritative(
            "p2p.open_shortfall_quantity", company_id, period=prior_period)
        # The order book last close struck, for the commitment movement's
        # opening balance — the fifth thing a later month inherits, resolved
        # the same way and period-scoped for the same reason as the shortfall:
        # every close's commitment fact stays open forever, and an unscoped
        # lookup would carry forward whichever one sorted last.
        prior_commitment = world.authoritative(
            procurement_estate.COMMITMENT, company_id, period=prior_period)

        # Drawn from a stream keyed on the *world*, not on the period, and that
        # is the whole reason it is drawn here rather than inside the figure
        # generator. Who the standing agreement is with is a property of the
        # company; drawing it from this month's stream would give month two a
        # different supplier while month one's counterparty fact — resolved
        # above and reused — still named the first, and the corpus would carry
        # two answers to "who is this order with".
        #
        # A world that opted into master data resolves the counterparty
        # against its own vendor register instead of the module's six-name
        # pool, so the standing agreement is with a supplier the corpus can
        # actually look up — same stream label either way, so the only worlds
        # whose supplier moves are the ones that asked for a register, which
        # no corpus had before the knob existed. The register outlives the
        # build (`masterdata.json`), so replay resolves the same name; the
        # month-two path above still reuses month one's counterparty fact
        # rather than redrawing.
        supplier_pool: tuple[str, ...] = procurement_cycle._SUPPLIERS
        table = world.masterdata
        if table is not None and table.vendors:
            supplier_pool = tuple(vendor.name for vendor in table.vendors)
        supplier = Rng(world.seed).derive("procurement/supplier").choice(supplier_pool)

        position = procurement_match.generate(
            rng.derive("match"),
            contested_category_id=contested_id,
            clean_category_id=clean_id,
            supplier=supplier,
            rate_overrides={
                category: fact.value.amount
                for category, fact in existing_rates.items() if fact.value
            },
            tolerance_pct=(
                existing_tolerance.value.amount
                if existing_tolerance is not None and existing_tolerance.value else None
            ),
            physics=self.physics,
        )

        episode = procurement_cycle.generate(
            rng.derive("cycle"), minter,
            period=self.period,
            company_id=company_id,
            roles=roles,
            position=position,
            category_names={c.id: c.name for c in world._categories},
            lore_by_target=index,
            # The archetype's own currency, never a literal — a pack that
            # states euros must not get a corpus of AUD_thousands facts with
            # euro labels on the documents that print them.
            money_unit=f"{world._archetype.currency}_{world._archetype.currency_unit}",
            rate_unit=f"{world._archetype.currency}_per_unit",
            supplier=supplier,
            # Pack episode-text overrides ride the recipe, so a pack-built
            # corpus rebuilds them with no pack file on hand.
            text=(world._recipe.get("pack") or {}).get("episode_text") or None,
            existing_tolerance_pct=existing_tolerance,
            existing_counterparty=existing_counterparty,
            existing_rates=existing_rates,
            existing_vendor_change=existing_vendor_change,
            prior_shortfall_value=prior_shortfall_value,
            prior_shortfall_quantity=prior_shortfall_quantity,
            tolerance_pct=position.tolerance_pct,
            # This corpus's own working week — see `MonthEndClose.run`. Every
            # date the cycle places is a period end plus a count of working
            # days, so without this a Gulf contractor receipts a delivery on a
            # Friday and closes its books on a Saturday.
            calendar=locale_of(world.recipe),
            physics=self.physics,
        )

        # The company the cycle happened inside. Generated *after* the cycle and
        # from the cycle's own close, so the position it states is dated at the
        # moment the ledger locked rather than at some hour of its own — and so
        # a reader who asks "what had we committed when this accrual was posted"
        # is reading two facts that share an event rather than two moments that
        # nearly agree.
        #
        # Its figures come from the company's revenue, not from the order: the
        # cycle raises one two-line order and the estate buys in a month, and a
        # generator that had sized the second from the first would have made a
        # group's whole cost base a function of one subcontract package.
        estate = procurement_estate.generate(
            rng.derive("estate"), minter,
            period=self.period,
            company_id=company_id,
            unit_ids={unit.key: roles[f"unit_{unit.key}"] for unit in world._archetype.units},
            unit_shares={unit.key: unit.share for unit in world._archetype.units},
            categories=world._categories,
            sites=world._sites,
            commercial_cost_centre_id=roles["cc_commercial"],
            finance_cost_centre_id=roles["cc_finance"],
            annual_revenue=world._annual_revenue,
            money_unit=f"{world._archetype.currency}_{world._archetype.currency_unit}",
            at=episode.closed_at,
            event_id=episode.keys["event_close_finalised"],
            procure_system_id=roles["sys_procure"],
            receipting_system_id=roles["sys_receipting"],
            general_ledger_id=roles["sys_general_ledger"],
            lore_by_target=index,
            opening_commitment=(
                int(prior_commitment.value.amount)
                if prior_commitment is not None and prior_commitment.value is not None
                else None
            ),
            physics=self.physics,
        )

        intents, errors = procurement_documents.artifact_intents(
            minter, episode=episode, estate=estate, roles=roles,
            # Once per corpus, not once per month. A supplier that re-requested
            # its remittance details every close would turn a control finding
            # into wallpaper, and the fact is standing for the same reason.
            mint_vendor_change=existing_vendor_change is None,
        )
        evaluation_cases = procurement_evaluation.evaluation_cases(
            minter, episode=episode, intents=intents, period=self.period,
            category_names={c.id: c.name for c in world._categories},
            # The world's whole plan, not just this month's. The cross-month
            # question asks about a balance an *earlier* month's memo carries,
            # and gating on this month's intents alone would drop precisely the
            # case a history exists to make askable. Still the same gate the
            # validator's `unreachable_answer` applies, which is also
            # world-wide.
            reachable=cases.reachable_fact_ids(world.artifact_intents, intents),
            text=(world._recipe.get("pack") or {}).get("evaluation_text") or None,
        )

        from .recipe import with_step

        # `episode.facts` carries the standing facts whether this month minted
        # them or reused ones already on the world's record — see
        # `regulatory.py`'s identical comment on why a reused fact must be
        # filtered back out before `world.extend`, which is append-only.
        known_fact_ids = set(world.facts.ids())
        new_facts = tuple(f for f in episode.facts if f.id not in known_fact_ids)
        # The estate's facts are minted fresh every month — a position is a
        # position at a date — so none of them can be a reuse and none needs the
        # filter above.
        new_facts += estate.facts

        return world.extend(
            events=episode.events,
            facts=new_facts,
            artifact_intents=intents,
            intentional_errors=errors,
            evaluations=evaluation_cases,
            period=self.period,
            recipe=with_step(world._recipe, "PurchaseToPayCycle", period=self.period),
        )


# The recipe verb: registered here, from procurement's own module, through
# `recipe.register_step` — the seam insurance paid for and this vertical is
# the first to get for free. `recipe.py` never learns this name, and
# `tests/test_procurement.py` pins that it has not.
from . import recipe as _recipe

_recipe.register_step("PurchaseToPayCycle", ("period",), PurchaseToPayCycle)


__all__ = ["PurchaseToPayCycle"]
