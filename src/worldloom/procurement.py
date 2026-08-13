"""The procure-to-pay domain module — the fourth vertical, and the first that
is not the finance function.

Retail, banking and insurance are three readings of one department: a close, a
regulatory return, a valuation. This one buys things. It **composes** with the
finance function rather than replacing it — the month-end accrual for goods
received and not invoiced is a ``financial.*`` fact in the shared vocabulary,
posted at a ``close.*`` the retail engine would recognise — which is what
makes it able to pose a question none of the three could: *which document is a
general-ledger figure built from, when three documents disagree about the
quantity it is built on.*

Registration follows insurance's file-for-file, through the four seams and
nothing else: a validator check group (``validate.register_domain_checks``),
artifact types (``documents.register_artifact_types``), renderer ownership
(``render.xlsx.register`` and friends), the domain registry (``domains.py``),
a recipe verb (``recipe.register_step``), and an archetype (``archetypes.py``,
data only). ``recipe.py``, ``cli.py``, ``documents.py``, ``packs.py`` and
``validate.py`` are unedited, and ``tests/test_procurement.py`` pins that with
its own scan rather than trusting it.

Three misfits are deliberately *not* modelled, and recording them is part of
this module's job — the §7a pack interface gets extracted from strain
evidence, not memory:

* **A supplier is not an entity.** The corpus has ``Company``,
  ``BusinessUnit``, ``Employee``, ``System``, ``Service``, ``CostCentre``,
  ``Category`` and ``Site``, and a counterparty is none of them. So the
  supplier lives in a ``p2p.contract_counterparty`` fact's ``text_value`` and
  every document reads its name back from there
  (``procurement_documents._supplier_of``), which keeps two documents from
  disagreeing about who the order is with but leaves the supplier unable to
  own anything, be referenced by id, or appear in the referential checks. This
  is the sharpest entity-model gap the project has: banking recorded that a
  regulator is not an entity and insurance that an accident cohort is not one,
  and both could argue the thing genuinely sits outside the enterprise. A
  supplier is *inside* the enterprise's records — it has a master-data record,
  a bank account, a contract and a performance history — and the extraction
  trigger is a Counterparty axis beside the entity model, which a manufacturer
  modelling its customers would also want.

* **A purchase order is not an entity either**, and this one bites less.
  ``fact.subject`` is the spend category and ``fact.period`` is the month, so
  "the March order" is addressable as a (subject, period) pair and every check
  below buckets on exactly that. Safe today because one order is raised per
  month per category; a vertical that raised several would need an Order axis
  or would have to encode an order number into the subject string, and the
  second of those is the kind of thing that looks like it works.

* **``Category.buyer_id`` is exactly the wrong shape and is left empty.**
  Retail's dimension model has a buyer per category per unit, which is what a
  merchandise buyer is. This vertical's buyer is one ``category_manager``
  holding a delegation across every unit, and populating the field per unit
  would assert three buyers where there is one — so the accountability is
  carried by the ``p2p.exception_approved_by`` fact and the role table
  instead, and the field stays empty rather than plausibly wrong.

And one seam that is genuinely missing, stated here rather than worked around:
``parameters.DEFAULTS`` has **no registration seam**. A fourth vertical's
physics cannot be added to it without editing a core module, so this vertical's
seven ranges live in ``generators/procurement_match.SPANS`` and are layered
under whatever a caller supplies. The consequence is precise: ``worldloom pack
params`` cannot list them, ``Parameters.with_overrides`` refuses them by name,
and a pack therefore cannot tune this vertical's physics at all. See that
module's comment for the full shape of the gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import archetypes as archetype_registry
from . import validate as validate_module
from .archetypes import MIDSIZE_INFRASTRUCTURE_SERVICES, Archetype
from .ids import Minter
from .models import (
    ConstraintKind,
    LoreCommitment,
    LoreConstraint,
    LoreKind,
)
from .parameters import DEFAULT, Parameters
from .rng import Rng
from .validate import RECONCILIATION_TOLERANCE, Violation
from .world import World, extend_lore

# Imported for its side effects: registering procurement's artifact types with
# the document compiler, and registering its physics parameters. Kept at module
# scope so that importing `worldloom.procurement` — which `worldloom/__init__`
# always does — is sufficient for a corpus loaded in a fresh process to compile,
# validate, and access procurement's parameters identically everywhere.
from . import procurement_documents  # noqa: F401  (registration)
from .generators.procurement_match import SPANS as _PROCUREMENT_SPANS
from . import parameters as _parameters_module

_parameters_module.register(_PROCUREMENT_SPANS)

#: Archetype keys that build a ``ProcureToPayWorld``. The recipe rebuilder and
#: the CLI dispatch on this.
PROCUREMENT_ARCHETYPES = frozenset({MIDSIZE_INFRASTRUCTURE_SERVICES.key})

#: The lore targets this engine's generators consult — the pack author's
#: contract, same as ``banking.CONSULTED_TARGETS``. Each entry names its
#: reader. Every one is read today: this vertical publishes no target ahead of
#: its reader, because it has no increment 2 to defer one to.
CONSULTED_TARGETS: tuple[tuple[str, str], ...] = (
    ("<role_key>/<fact_kind>",
     "an accountability: mints the fact saying this role answers for that measure"
     " (org_builder.accountability_facts)"),
    ("receipting_visibility/subcontract",
     "tags the receipt event and the received-quantity facts — why a short delivery is"
     " visible at all (generators.procurement_cycle.generate)"),
    ("exception_approval",
     "tags the escalation, the tolerance facts and the approver fact"
     " (generators.procurement_cycle.generate)"),
    ("finance/pay_to_contract",
     "tags the price variance, the settlement and the credit note"
     " (generators.procurement_cycle.generate)"),
    ("vendor_master_dual_approval",
     "tags the vendor master change request and its held status"
     " (generators.procurement_cycle.generate)"),
)


def lore(minter: Minter) -> tuple[LoreCommitment, ...]:
    """The contractor archetype's lore: five commitments, every one load-bearing.

    The handheld rollout is why a short delivery is recorded rather than
    rounded away; the delegation is why an exception leaves the buyer; the
    pay-to-contract norm is why the settlement is at the order's rate and not
    the invoice's; the tension is why procurement and payables each paper
    their own position; and the dual-approval constraint is why one document
    in this corpus is held and unresolved for as long as the corpus runs.
    """
    return (
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.DECISION,
            assertion=(
                "A 2024 receipting programme replaced paper delivery dockets with handheld "
                "scanning at site. Partial deliveries are now recorded at the quantity that "
                "actually arrived, where the paper process signed the docket as presented "
                "and reconciled later, or not at all."
            ),
            effective_from="2024-05",
            constrains=[
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="receipting_visibility/subcontract",
                               effect="Short deliveries surface at the match instead of being absorbed",
                               magnitude=1.9),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY,
                               target="match_exception_report",
                               effect="Every cycle now produces an exception report the paper process never generated",
                               magnitude=0.4),
                LoreConstraint(kind=ConstraintKind.TERMINOLOGY,
                               target="goods_receipt",
                               effect="'Goods receipt' and 'delivery docket' both remain in use across the rollout boundary"),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.NORM,
            assertion=(
                "A three-way match variance within the standing tolerance may be cleared by "
                "the buyer. Above it the exception is Finance's, at controller level or "
                "above, and the person who raised the order may not clear an exception on "
                "it — whatever the schedule pressure on the project it belongs to."
            ),
            effective_from="2019-04",
            constrains=[
                LoreConstraint(kind=ConstraintKind.APPROVAL_CHAINS,
                               target="exception_approval",
                               effect="An above-tolerance variance needs a Finance approver who did not raise the order",
                               magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY,
                               target="payment_approval_memo",
                               effect="Every above-tolerance settlement needs a memo naming who approved it",
                               magnitude=0.3),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.NORM,
            assertion=(
                "Nothing is paid above the contracted rate without a signed variation. Where "
                "an invoice bills above the rate card and no variation exists, the group "
                "settles at the contracted rate for the quantity received and takes a credit "
                "note for the difference."
            ),
            effective_from="2018-07",
            constrains=[
                LoreConstraint(kind=ConstraintKind.RISK_APPETITE,
                               target="finance/pay_to_contract",
                               effect="Settlement is the received quantity at the contracted rate, never the invoiced amount",
                               magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.METRIC_EMPHASIS,
                               target="contract_rate",
                               effect="The contracted rate is the standing commercial measure every settlement is read against",
                               magnitude=1.0),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.TENSION,
            assertion=(
                "Procurement regards the rate card as the number, because it is what was "
                "agreed. Accounts payable regards the invoice as the number, because it is "
                "what the subledger holds and what the supplier will chase. Neither is "
                "wrong about its own system, and the two systems are never reconciled into "
                "one figure."
            ),
            effective_from="2025-02",
            constrains=[
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                               target="chief_procurement/insistent_on_the_contracted_rate",
                               effect="The order and the exception report state the agreed rate without softening it",
                               magnitude=0.4),
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                               target="accounts_payable_lead/anchored_on_the_ledger",
                               effect="The invoice is presented as posted, with no marker that any of it is disputed",
                               magnitude=0.3),
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="finance/pay_to_contract",
                               effect="The standing disagreement recurs on every order that bills above the rate card",
                               magnitude=1.4),
            ],
            visibility="tacit",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.CONSTRAINT,
            assertion=(
                "A change to a supplier's remittance details requires two Finance approvers "
                "and may not be actioned inside a payment run it would affect. Until the "
                "second approver signs, the payment run continues to use the details on "
                "file, and the request stays on the vendor master as pending."
            ),
            effective_from="2021-09",
            constrains=[
                LoreConstraint(kind=ConstraintKind.APPROVAL_CHAINS,
                               target="vendor_master_dual_approval",
                               effect="A remittance change is held, not applied, until a second Finance approver signs",
                               magnitude=1.0),
            ],
            visibility="acknowledged",
        ),
    )


@dataclass(frozen=True)
class ProcureToPayWorld:
    """An infrastructure-services group, built from a seed.

    Lazy, like its three siblings: constructing one does no work.

        world = ProcureToPayWorld(seed=8128).build()
        world = world.run(PurchaseToPayCycle(period="2026-03"))
        world = world.run(PurchaseToPayCycle(period="2026-04"))
    """

    seed: int
    archetype: Archetype = MIDSIZE_INFRASTRUCTURE_SERVICES
    employees: int | None = None
    annual_revenue: int | None = None
    pack: Any = None
    """An industry ``Pack``. See ``RetailWorld.pack`` — same contract."""
    estate: str | None = None
    """Refused, and stated rather than silently ignored.

    ``--estate`` grows a technology landscape out of a named vocabulary in
    ``worldloom.landscape``, and ``landscape.LANDSCAPES`` is a literal dict in
    a core module with **no registration seam** — the same gap
    ``parameters.DEFAULTS`` has. This module could define a ``Landscape`` of
    its own and pass it to ``generators.estate`` directly, which is what a
    fifth vertical will want to do, but it would then be invisible to
    ``worldloom pack landscapes`` and unreachable from ``--pack``: an estate
    vocabulary only one code path knows about is the "carried, citable and
    inert" failure this repository keeps finding.

    So the flag is refused with its reason rather than served half-way. The
    field exists at all because ``cli.py`` forwards ``estate=`` to whichever
    world a domain registered, and a ``TypeError`` out of a dataclass
    constructor is a worse answer than a sentence."""

    role_table: tuple[tuple[str, str, str, str | None], ...] | None = None
    """Who exists in this organisation (``worldloom.roles``).

    ``None`` is the engine's own table. A supplied one must have passed
    ``roles.check``: several of its keys are looked up by name in generator
    code, and a table missing one raises ``KeyError`` part-way through an
    episode rather than building a different company.

    Carried on the recipe as a whole table rather than as the shape it came
    from, for the reason the pack is embedded whole: a corpus that could only
    be rebuilt by whoever still had the probe that derived it would fail the
    reason recipes exist."""

    physics: Parameters = DEFAULT
    """The world physics the organisation is drawn under.

    Note what this *cannot* carry, and it is this vertical's own seam report:
    procurement's seven ranges are not in ``parameters.DEFAULTS``, so a
    ``Parameters`` built by ``with_overrides`` cannot hold one. The generators
    layer their own defaults under whatever arrives here
    (``generators.procurement_match._physics``), so the organisation and the
    cycle are still drawn under the same physics — which is the invariant that
    actually matters — but a pack cannot move a procurement range."""

    lore_claims: tuple[Any, ...] = ()
    """Lore a set of facet claims commits this group to (``facets.LoreClaim``).
    See ``RetailWorld.lore_claims`` — same contract, and ``world.extend_lore``
    argues where the seam lives and why ``()`` keeps an existing corpus
    byte-identical."""

    locale: Any = None
    """Where this group is (``worldloom.locales``). See ``RetailWorld.locale``
    — same contract, same precedence.

    Forwarded to the organisation generator in full from the first commit,
    which is the one piece of insurance's history this vertical got to skip:
    that module shipped without ``name_pools``, ``headquarters``, ``regions``
    or ``locale`` reaching ``generate``, so every insurer this tool built was
    unconditionally Australian and no argument would move it. The lesson was
    already paid for; there is no reason to buy it twice.

    ``Locale.suffixes_for("procurement")`` is consulted for the company's own
    name and falls back to the retail pool for a locale that predates this
    engine — which for a contractor is a defensible fallback rather than an
    embarrassing one, unlike an insurer named ``Handelsgruppe``. The engine's
    own pool is stated in ``procurement_org`` regardless."""

    policies: str | None = None
    """Standing documents (``worldloom.policies``): ``"core"`` or ``"full"``.

    The paperwork a company *has* rather than produces — an expense policy, a
    delegation of authority, a leave policy — as opposed to the episodic
    documents a close or an incident emits. ``None`` mints nothing, which is
    what keeps every corpus built before the knob existed byte-identical, the
    same guarantee ``estate`` and ``master_data`` make. The recipe records the
    level, never the documents, so a replay re-runs the same construction."""

    master_data: Any = None
    """Reference tables at scale — `RetailWorld.master_data`, verbatim: the
    same knob, the same no-op default, the same counts-on-the-recipe replay."""

    @classmethod
    def inspired_by(cls, description: str, *, seed: int) -> ProcureToPayWorld:
        """A world shaped like the contractor *description* names. Shape only."""
        shape = archetype_registry.inspired_by(description)
        if shape.key not in PROCUREMENT_ARCHETYPES:
            shape = MIDSIZE_INFRASTRUCTURE_SERVICES
        return cls(seed=seed, archetype=shape)

    @classmethod
    def from_pack(cls, pack: Any, *, seed: int) -> ProcureToPayWorld:
        """A contractor whose shape, lore, and name a pack authored.

        One structural requirement beyond the schema: the cycle raises a
        two-line order, so the pack must give some unit at least two spend
        categories. ``procurement_org`` names them by role handle where it
        recognises them and falls back to the two heaviest by group weight
        where it does not.
        """
        from . import packs as packs_module

        return cls(seed=seed, archetype=packs_module.archetype_of(pack), pack=pack)

    def build(self) -> World:
        from . import __version__ as worldloom_version
        from . import locales as locales_module
        from . import recipe as recipe_module
        from .generators import procurement_org

        if self.estate is not None:
            raise ValueError(
                "the procurement vertical has no estate vocabulary: `landscape.LANDSCAPES`"
                " is a closed table in core with no registration seam, so a procurement"
                " landscape would be invisible to `worldloom pack landscapes` and"
                " unreachable from a pack. Build without --estate, or register a"
                " landscape seam first."
            )

        rng = Rng(self.seed)
        minter = Minter()

        # Resolved before anything is minted, and refused here rather than
        # defaulted. See `RetailWorld.build`.
        locale = locales_module.resolve(self.locale)
        archetype = locale.applied_to(self.archetype)

        if self.pack is not None:
            from . import packs as packs_module

            commitments = packs_module.lore_of(self.pack, minter)
        else:
            commitments = lore(minter)
        # Before `generate`: lore is an input to the organisation, not a
        # decoration on it. See `world.extend_lore`.
        recipe = recipe_module.build_recipe(
            archetype=self.archetype.key,
            seed=self.seed,
            employees=self.employees,
            annual_revenue=self.annual_revenue,
            pack=self.pack,
            physics=self.physics,
            role_table=self.role_table,
            # What it was given, not what it resolved to — `RetailWorld.build`.
            locale=self.locale,
            master_data=self.master_data,
            policies=self.policies,
        )
        commitments, recipe = extend_lore(commitments, self.lore_claims, minter, recipe)
        org = procurement_org.generate(
            rng.derive("organisation"), minter,
            archetype=archetype, lore=commitments,
            company_name=self.pack.company_name if self.pack is not None else None,
            system_brands=dict(self.pack.system_brands) if self.pack is not None else None,
            voices=dict(self.pack.voices) if self.pack is not None else None,
            name_pools=self.pack.name_pools.model_dump() if self.pack is not None else None,
            headquarters=self.pack.headquarters if self.pack is not None else None,
            regions=tuple(self.pack.regions) if self.pack is not None and self.pack.regions else None,
            locale=locale,
            physics=self.physics,
            role_table=self.role_table,
            employees_total=self.employees,
        )

        world = World(
            company=org.company,
            _business_units=org.business_units,
            _people=org.people,
            _systems=org.systems,
            _services=org.services,
            _cost_centres=org.cost_centres,
            _categories=org.categories,
            _sites=org.sites,
            _personas=org.personas,
            _access_policies=org.access_policies,
            _lore=commitments,
            _events=org.milestones,
            _facts=org.founding_facts,
            seed=self.seed,
            _roles=org.roles,
            _minter=minter,
            _annual_revenue=self.annual_revenue or archetype.annual_revenue,
            _archetype=archetype,
            _generator_version=worldloom_version,
            _recipe=recipe,
        )
        # A strict no-op when nothing was asked for — see the field. After the
        # organisation so the register buckets vendors in this world's own
        # category names, under a stream root of its own so it moves nothing.
        from .generators import masterdata as masterdata_module

        world = masterdata_module.applied(world, self.master_data, locale=locale)
        # Last, and after the master data for the same reason that came after
        # the organisation: a standing document is planned against the roles
        # and the revenue this world actually ended up with. A strict no-op
        # when nothing was asked for — see the field.
        from . import policies as policies_module

        return policies_module.applied(world, self.policies)


# ---------------------------------------------------------------------------
# The procurement check group
# ---------------------------------------------------------------------------
#
# Registered with the core validator and run on every world, so the group
# starts from the same early-return banking's and insurance's do: a world with
# no `p2p.*` facts is not a procurement world, and the group must cost it
# nothing.
#
# **Bucketed once, deliberately.** `banking._checks` scans the whole fact list
# inside several per-period loops, which is why it is 94% of validate's runtime
# at scale. Everything below reads two indexes built in a single pass — the
# shape `validate.financial()` uses — so this group is linear in the corpus and
# a twelve-month build costs twelve times a one-month build rather than a
# hundred and forty-four times it.


def _checks(world: World) -> tuple[list[Violation], int]:
    facts = list(world.facts)
    if not any(f.kind.startswith("p2p.") for f in facts):
        return [], 0

    violations: list[Violation] = []
    checks = 0

    def fail(code: str, subject: str, detail: str) -> None:
        violations.append(Violation("procurement", code, subject, detail))

    # -- one pass, three indexes ---------------------------------------------
    # `current` is the answer to "what does the corpus say now", keyed by
    # (kind, period) -> subject -> fact. `chain` keeps every link including the
    # superseded ones, because the exception-status discipline is about the
    # chain rather than about its head. `superseded_ids` is who somebody
    # replaced, which is not the same question as `is_superseded` (a per-period
    # snapshot is neither closed nor replaced and is still not the latest).
    current: dict[tuple[str, str | None], dict[str, Any]] = {}
    chain: dict[tuple[str, str | None, str], list[Any]] = {}
    superseded_ids = {f.supersedes for f in facts if f.supersedes}
    for fact in facts:
        if not (fact.kind.startswith("p2p.") or fact.kind == "financial.accrual.grni"):
            continue
        chain.setdefault((fact.kind, fact.period, fact.subject), []).append(fact)
        if fact.is_superseded or fact.id in superseded_ids:
            continue
        current.setdefault((fact.kind, fact.period), {})[fact.subject] = fact

    def at(kind: str, period: str | None) -> dict[str, Any]:
        return current.get((kind, period), {})

    def close_enough(left: float, right: float) -> bool:
        return abs(left - right) <= RECONCILIATION_TOLERANCE

    company_id = world.company.id
    category_ids = {c.id for c in world.categories}
    # Every month the corpus has an order for, in one place, so nothing below
    # has to rediscover the period set by scanning facts again.
    periods = sorted({
        period for (kind, period) in current if kind == "p2p.ordered_quantity" and period
    })
    # Which month a purchase order is *for*, read off the period-keyed facts it
    # cites. A manifest entry carries no period of its own, and check (h) needs
    # one: "an order they raised themselves" is a claim about this month's
    # order, and a corpus of twelve months holds eleven other people's. Built
    # once, over the orders only, so a month's check is a membership test rather
    # than a rescan of the manifest.
    order_periods: dict[str, set[str]] = {}
    fact_periods = {f.id: f.period for f in facts if f.period}
    for entry in world.artifacts:
        if entry.artifact_type != "purchase_order":
            continue
        order_periods[entry.id] = {
            fact_periods[fact_id] for fact_id in entry.supporting_fact_ids
            if fact_id in fact_periods
        }

    for period in periods:
        rates = at("p2p.contract_rate", None)
        ordered_quantity = at("p2p.ordered_quantity", period)
        ordered_value = at("p2p.ordered_value", period)
        received_quantity = at("p2p.received_quantity", period)
        received_value = at("p2p.received_value", period)
        invoiced_quantity = at("p2p.invoiced_quantity", period)
        invoiced_price = at("p2p.invoiced_unit_price", period)
        invoiced_value = at("p2p.invoiced_value", period)
        quantity_variance = at("p2p.match_quantity_variance", period)
        price_variance = at("p2p.match_price_variance", period)
        total_variance = at("p2p.match_total_variance", period)

        lines = sorted(category_ids & set(ordered_quantity))

        for line in lines:
            rate = rates.get(line)
            if rate is None or rate.value is None:
                continue
            per_unit = rate.value.amount

            # -- (a) each document's own value is its quantity times its rate --
            # The purchase order and the goods receipt both price at the
            # contracted rate; only the invoice prices at its own. Checked per
            # document rather than once, because the whole point of the three
            # is that they are separately assertable and could separately be
            # wrong.
            for label, quantities, values, price in (
                ("ordered", ordered_quantity, ordered_value, per_unit),
                ("received", received_quantity, received_value, per_unit),
                ("invoiced", invoiced_quantity, invoiced_value,
                 invoiced_price[line].value.amount if line in invoiced_price
                 and invoiced_price[line].value else None),
            ):
                quantity, value = quantities.get(line), values.get(line)
                if quantity is None or value is None or price is None:
                    continue
                checks += 1
                derived = quantity.value.amount * price / 1000
                if not close_enough(derived, value.value.amount):
                    fail(f"{label}_value_does_not_reconcile", value.id,
                         f"{quantity.value.amount:,.0f} units at {price:,.0f} is "
                         f"{derived:,.2f}, but the {label} value states "
                         f"{value.value.amount:,.2f}")

            # -- (b) a receipt never exceeds its order -----------------------
            # Over-receipt is a real exception with a different resolution and
            # this engine does not model it, so the invariant is held rather
            # than trusted: a received quantity above the ordered one would
            # make the quantity variance negative and every downstream
            # reconciliation would still close, silently describing a world
            # this vertical never meant to build.
            if line in ordered_quantity and line in received_quantity:
                checks += 1
                if received_quantity[line].value.amount > ordered_quantity[line].value.amount:
                    fail("receipt_exceeds_order", received_quantity[line].id,
                         f"site receipted {received_quantity[line].value.amount:,.0f} against"
                         f" an order for {ordered_quantity[line].value.amount:,.0f}")

            # -- (c) the three-way match arithmetic, both halves -------------
            if line in invoiced_quantity and line in received_quantity and line in quantity_variance:
                checks += 1
                derived = (invoiced_quantity[line].value.amount
                           - received_quantity[line].value.amount) * per_unit / 1000
                if not close_enough(derived, quantity_variance[line].value.amount):
                    fail("quantity_variance_does_not_reconcile", quantity_variance[line].id,
                         f"invoiced less received at the contracted rate is {derived:,.2f},"
                         f" but the variance states {quantity_variance[line].value.amount:,.2f}")
            if line in invoiced_quantity and line in invoiced_price and line in price_variance:
                checks += 1
                derived = (invoiced_quantity[line].value.amount
                           * (invoiced_price[line].value.amount - per_unit) / 1000)
                if not close_enough(derived, price_variance[line].value.amount):
                    fail("price_variance_does_not_reconcile", price_variance[line].id,
                         f"invoiced quantity times the uplift over the contracted rate is"
                         f" {derived:,.2f}, but the variance states"
                         f" {price_variance[line].value.amount:,.2f}")

            # -- (d) the match identity: invoiced less variance is received --
            # The one line of arithmetic the whole vertical rests on, and it is
            # checked as its own claim rather than inferred from (c): the two
            # halves can each reconcile against their own inputs and still fail
            # to account for the gap between what was billed and what is owed,
            # if the corpus ever grew a third kind of variance without saying so.
            if line in invoiced_value and line in total_variance and line in received_value:
                checks += 1
                derived = invoiced_value[line].value.amount - total_variance[line].value.amount
                if not close_enough(derived, received_value[line].value.amount):
                    fail("match_does_not_account_for_the_gap", total_variance[line].id,
                         f"invoiced {invoiced_value[line].value.amount:,.2f} less variance"
                         f" {total_variance[line].value.amount:,.2f} is {derived:,.2f}, but"
                         f" the received value at the contracted rate is"
                         f" {received_value[line].value.amount:,.2f}")

        # -- (e) every group total is the sum of its own lines ---------------
        # `validate.financial()` covers `financial.*` roll-ups against the
        # business-unit hierarchy; these roll up across *spend categories* to a
        # company total, which that check has no view of.
        for kind, buckets in (
            ("p2p.ordered_value", ordered_value),
            ("p2p.received_value", received_value),
            ("p2p.invoiced_value", invoiced_value),
            ("p2p.match_quantity_variance", quantity_variance),
            ("p2p.match_price_variance", price_variance),
            ("p2p.match_total_variance", total_variance),
        ):
            total = buckets.get(company_id)
            parts = [buckets[line].value.amount for line in lines if line in buckets]
            if total is None or not parts:
                continue
            checks += 1
            if not close_enough(sum(parts), total.value.amount):
                fail("group_total_does_not_reconcile", total.id,
                     f"{len(parts)} {kind} line(s) sum to {sum(parts):,.2f} but the group"
                     f" total states {total.value.amount:,.2f}")

        # -- (f) the two variance halves account for the total ---------------
        quantity_total = quantity_variance.get(company_id)
        price_total = price_variance.get(company_id)
        variance_total = total_variance.get(company_id)
        if quantity_total and price_total and variance_total:
            checks += 1
            summed = quantity_total.value.amount + price_total.value.amount
            if not close_enough(summed, variance_total.value.amount):
                fail("variance_halves_do_not_sum", variance_total.id,
                     f"quantity {quantity_total.value.amount:,.2f} + price"
                     f" {price_total.value.amount:,.2f} = {summed:,.2f}, but the total"
                     f" variance states {variance_total.value.amount:,.2f}")

        # -- (g) the settlement pays the contract, not the invoice -----------
        # Two claims in one place because they are one decision: the credit
        # note covers the whole variance, and what is left is exactly the
        # received quantity at the contracted rate. A corpus where those two
        # drifted apart would be paying an amount no document justifies.
        credit = at("p2p.credit_note_value", period).get(company_id)
        approved = at("p2p.approved_payment_value", period).get(company_id)
        invoiced_total = invoiced_value.get(company_id)
        received_total = received_value.get(company_id)
        if credit and variance_total:
            checks += 1
            if not close_enough(credit.value.amount, variance_total.value.amount):
                fail("credit_note_does_not_cover_the_variance", credit.id,
                     f"credit note {credit.value.amount:,.2f} against a match variance of"
                     f" {variance_total.value.amount:,.2f}")
        if approved and invoiced_total and credit and received_total:
            checks += 1
            derived = invoiced_total.value.amount - credit.value.amount
            if not close_enough(derived, approved.value.amount):
                fail("settlement_does_not_reconcile", approved.id,
                     f"invoiced {invoiced_total.value.amount:,.2f} less credit"
                     f" {credit.value.amount:,.2f} is {derived:,.2f}, but the approved"
                     f" payment states {approved.value.amount:,.2f}")
            checks += 1
            if not close_enough(approved.value.amount, received_total.value.amount):
                fail("settlement_is_not_the_contracted_rate", approved.id,
                     f"approved {approved.value.amount:,.2f} against a received value at"
                     f" contracted rates of {received_total.value.amount:,.2f} — the"
                     " standing norm settles at the contract, so any other figure is"
                     " paying the invoice")

        # -- (h) an above-tolerance settlement is approved, and not by the buyer
        # The approval-chain lore, checked against the corpus rather than
        # against the generator that wrote it — `validate.py`'s actors group
        # states the reason: the runtime guards the run, and what somebody
        # downloads is a directory that can be edited. Manifest-driven, so it
        # is skipped on a world that has been run but not compiled; that guard
        # is stated rather than inherited, because unlike banking's
        # filing checks this one's driving set is facts, not artifacts.
        tolerance = at("p2p.approval_tolerance", period).get(company_id)
        approver = next(
            (f for (kind, fact_period), subjects in current.items()
             if kind == "p2p.exception_approved_by" and fact_period == period
             for f in subjects.values()),
            None,
        )
        if world.artifacts and tolerance and variance_total:
            if variance_total.value.amount > tolerance.value.amount:
                checks += 1
                if approver is None:
                    fail("unapproved_settlement", variance_total.id,
                         f"a match variance of {variance_total.value.amount:,.2f} exceeds the"
                         f" {tolerance.value.amount:,.2f} tolerance with no"
                         " p2p.exception_approved_by fact naming who cleared it")
                else:
                    checks += 1
                    # This month's orders, not the corpus's. The unscoped
                    # reading was the same figure while a corpus held one
                    # cycle, and two wrong things at twelve: a buyer who raised
                    # January's order and cleared an unrelated exception in
                    # August was reported as a breach they did not commit, and
                    # a real breach named whichever order sorted first in the
                    # manifest rather than the one the approver actually
                    # raised — an accusation citing the wrong evidence.
                    orders = [a for a in world.artifacts
                              if a.artifact_type == "purchase_order"
                              and a.author_id == approver.subject
                              and period in order_periods.get(a.id, ())]
                    if orders:
                        fail("segregation_of_duties_breached", approver.id,
                             f"{approver.subject} approved an above-tolerance exception on an"
                             f" order they raised themselves ({orders[0].id}) — the standing"
                             " delegation forbids exactly this")

        # -- (i) the accrual is the receipt, and nothing but the receipt -----
        # The composition, held to its own claim. This is the check that makes
        # the cross-domain question honest: if the accrual could quietly pick
        # up an invoiced figure the corpus would be posing a question whose
        # answer it does not itself guarantee.
        accrual = at("financial.accrual.grni", period).get(company_id)
        released = at("p2p.shortfall_released_value", period).get(company_id)
        if accrual and received_total and released:
            checks += 1
            derived = received_total.value.amount + released.value.amount
            if not close_enough(derived, accrual.value.amount):
                fail("accrual_is_not_the_receipt", accrual.id,
                     f"received at contracted rates {received_total.value.amount:,.2f} plus"
                     f" released {released.value.amount:,.2f} is {derived:,.2f}, but the"
                     f" accrual states {accrual.value.amount:,.2f}")

        # -- (j) the shortfall carries, and carries exactly ------------------
        shortfall_quantity = at("p2p.open_shortfall_quantity", period).get(company_id)
        if shortfall_quantity and quantity_total:
            checks += 1
            open_value = at("p2p.open_shortfall_value", period).get(company_id)
            if open_value and not close_enough(open_value.value.amount,
                                               quantity_total.value.amount):
                fail("shortfall_is_not_the_quantity_variance", open_value.id,
                     f"the open balance states {open_value.value.amount:,.2f} but the"
                     f" quantity billed and not received is"
                     f" {quantity_total.value.amount:,.2f}")

    # -- (k) each month releases exactly what the month before left ----------
    # Across periods rather than inside one, so it sits outside the loop and
    # reads the period list built once above. The first month releases nothing,
    # which is checked as a claim rather than skipped: a corpus whose first
    # month released a balance would have invented an order that never existed.
    for index, period in enumerate(periods):
        released = at("p2p.shortfall_released_value", period).get(company_id)
        if released is None:
            continue
        checks += 1
        if index == 0:
            if released.value.amount != 0:
                fail("released_before_anything_was_owed", released.id,
                     f"the first period on record releases {released.value.amount:,.2f}"
                     " against a prior short delivery that does not exist")
            continue
        earlier = at("p2p.open_shortfall_value", periods[index - 1]).get(company_id)
        if earlier is None:
            continue
        if not close_enough(released.value.amount, earlier.value.amount):
            fail("carry_forward_does_not_match", released.id,
                 f"{period} releases {released.value.amount:,.2f} but"
                 f" {periods[index - 1]} closed with {earlier.value.amount:,.2f}"
                 " outstanding")

    # -- (l) the three source records are immutable --------------------------
    # A purchase order, a goods receipt and a supplier invoice are what they
    # were. A wrong one is not edited and not superseded — a credit note is
    # posted beside it, which is why `p2p.credit_note_value` exists as its own
    # fact rather than as a correction to the invoice. Same discipline as
    # banking's `as_filed_touched` and insurance's `triangle_touched`, reached
    # independently by the same argument: evidence that can be edited is not
    # evidence.
    immutable = (
        "p2p.ordered_quantity", "p2p.ordered_value",
        "p2p.received_quantity", "p2p.received_value",
        "p2p.invoiced_quantity", "p2p.invoiced_unit_price", "p2p.invoiced_value",
    )
    for fact in facts:
        if fact.kind not in immutable:
            continue
        checks += 1
        if fact.valid_to is not None or fact.id in superseded_ids:
            fail("source_record_touched", fact.id,
                 f"a {fact.kind} is what the document said; closing or superseding it"
                 " erases what was ordered, received or billed, and the corpus's own"
                 " correction mechanism is a credit note posted beside it")

    # -- (m) the exception status walks one unbroken chain -------------------
    # Exactly one live status per month, and every superseded link handing over
    # at precisely the instant its successor opens. A torn window would leave a
    # moment the corpus has two answers for, or none, and the temporal question
    # the benchmark asks would have no defensible answer at that instant.
    for (kind, period, subject), links in sorted(
        ((key, value) for key, value in chain.items() if key[0] == "p2p.exception_status"),
        key=lambda item: (item[0][1] or "", item[0][2]),
    ):
        ordered_links = sorted(links, key=lambda f: f.valid_from)
        checks += 1
        live = [f for f in ordered_links if f.valid_to is None]
        if len(live) != 1:
            fail("exception_status_not_singular", f"{kind}/{subject}/{period}",
                 f"{len(live)} open status facts, expected exactly 1")
        for earlier, later in zip(ordered_links, ordered_links[1:]):
            checks += 1
            if earlier.valid_to != later.valid_from or later.supersedes != earlier.id:
                fail("exception_status_torn", earlier.id,
                     "does not hand over exactly where the next status opens, or the"
                     " next status does not record what it replaced")

    return violations, checks


validate_module.register_domain_checks("procurement", _checks)

# The domain registry entry: how the CLI and the recipe rebuilder find this
# vertical from an archetype key, without either naming procurement in core.
from .domains import Domain, register_domain  # noqa: E402
from .procurement_scenarios import PurchaseToPayCycle  # noqa: E402

from .generators.procurement_cycle import TEXT as _PROCUREMENT_TEXT  # noqa: E402
from .generators.procurement_evaluation import EVAL_TEXT as _PROCUREMENT_EVAL_TEXT  # noqa: E402
from .generators.procurement_org import _ROLES as _PROCUREMENT_ROLES  # noqa: E402

# The mosaic axes: what varies across a field of contractor groups. Without
# this registration `worldloom mosaic -e procurement` was refused while the
# other three engines built — the one gap between "procurement is a complete
# vertical" and it being usable as a volume multiplier. Each centre range is
# chosen so the whole band the axis carries (the engine's own span *width*,
# recentred — see `mosaic._candidate`, and the insurance `deterioration` axis
# for the failure mode) stays on the right side of its floor:
#
# * `tolerance` (width 0.8): low centre 0.6 keeps the band positive, and the
#   ends are the two kinds of group the span's own docstring names — a tightly
#   run 0.5% shop and a permissive near-5% one.
# * `breach` (width 1.05): the multiple must stay strictly above 1.0 or the
#   escalation this vertical exists to pose never happens; 1.6 is the lowest
#   centre whose whole band clears it.
# * `order_size` (width 700, integral): a small works package to a framework's
#   monthly call-off.
# * `rate_split` (width 0.25): stays inside (0, 1), and moving it moves which
#   document the disagreement lives in — price disputes argue on the invoice,
#   delivery shortfalls on the receipt.
from . import mosaic as _mosaic_module

# Structure minus the estate axis: `ProcureToPayWorld` refuses `estate=` by
# design — `landscape.LANDSCAPES` is a closed core table with no registration
# seam, and a procurement landscape would be invisible to `pack landscapes` —
# so a mosaic axis dealing estates to this engine would build worlds the world
# builder itself rejects. The axis is dropped rather than the guard loosened.
_mosaic_module.register_engine("procurement", tuple(
    axis for axis in _mosaic_module.STRUCTURE if axis.name != "estate"
) + (
    _mosaic_module.Axis(
        "tolerance", 0.6, 4.5, parameter="procurement.tolerance.pct",
        about="The approval tolerance as a share of committed order value — how"
              " much variance a buyer may clear alone. The single number that"
              " decides how much of the corpus is an exception at all."),
    _mosaic_module.Axis(
        "breach", 1.6, 3.4, parameter="procurement.tolerance.breach_multiple",
        about="How far past the tolerance the match variance lands — how bad"
              " the exception is. Stays above 1.0, because at it the"
              " escalation this vertical exists to pose stops happening."),
    _mosaic_module.Axis(
        "order_size", 500, 5_000, integral=True,
        parameter="procurement.order.contested_quantity",
        about="Crew-days committed on the contested line — the size of the"
              " order the three-way match runs against."),
    _mosaic_module.Axis(
        "rate_split", 0.25, 0.80, parameter="procurement.variance.price_fraction",
        about="The share of the variance that is a rate uplift rather than a"
              " short delivery — which document the disagreement lives in."),
))

register_domain(Domain(
    name="procurement",
    archetype_keys=PROCUREMENT_ARCHETYPES,
    default_archetype="midsize_infrastructure_services",
    world=ProcureToPayWorld,
    single_episode=PurchaseToPayCycle,
    # Monthly, unlike its two single-episode siblings. `--periods 12` is twelve
    # consecutive months, each one clearing the balance the month before left —
    # which is the shape `Domain.period_step_months` was generalised for and
    # the first vertical to use its default value for something.
    period_step_months=1,
    consulted_targets=CONSULTED_TARGETS,
    system_slots=(
        ("sourcing", "sourcing and contract management, holding the rate card and vendor master"),
        ("procure", "requisition-to-order system, the record of what was committed"),
        ("receipting", "site goods receipting, the record of what arrived"),
        ("ap_ledger", "accounts payable subledger, the record of what was billed"),
        ("general_ledger", "general ledger of record for the accrual and the close"),
    ),
    role_keys=tuple(row[0] for row in _PROCUREMENT_ROLES),
    unit_role_suffixes=("_md",),
    episode_text=tuple(_PROCUREMENT_TEXT.items()),
    evaluation_text=tuple(_PROCUREMENT_EVAL_TEXT.items()),
))

# Procurement's own fact kinds, in the process-global registry. This vertical
# carries the project's only period-keyed carry-forward (`p2p.open_shortfall_*`),
# so it is where `carries-forward-as(derive)` is a measured fact rather than a
# design intention. `financial.accrual.grni` is registered here, not by retail,
# despite the prefix: the procurement cycle mints it and answers for it.
from .factkinds import FactKind, register as _register_kinds  # noqa: E402

_register_kinds([
    FactKind(kind="p2p.contract_rate", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at", "standing"), about="The contracted unit rate."),
    FactKind(kind="p2p.contract_counterparty", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at", "standing"), about="Who the contract is with."),
    FactKind(kind="p2p.approval_tolerance_pct", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at", "standing"), about="The match tolerance, in per cent."),
    FactKind(kind="p2p.approval_tolerance", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at",), about="The tolerance in currency at this order's size."),
    FactKind(kind="p2p.ordered_quantity", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at",), about="What was committed."),
    FactKind(kind="p2p.ordered_value", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at", "reconciles-against(p2p.ordered_quantity, p2p.contract_rate)"),
             about="Quantity times rate, exactly."),
    FactKind(kind="p2p.received_quantity", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="What arrived."),
    FactKind(kind="p2p.received_value", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="What arrived, valued at contract."),
    FactKind(kind="p2p.invoiced_quantity", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="What was billed."),
    FactKind(kind="p2p.invoiced_unit_price", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="The billed unit price the match disputes."),
    FactKind(kind="p2p.invoiced_value", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at", "reconciles-against(p2p.invoiced_quantity, p2p.invoiced_unit_price)"),
             about="Billed quantity times billed price."),
    FactKind(kind="p2p.match_price_variance", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="The price leg of the failed match."),
    FactKind(kind="p2p.match_quantity_variance", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="The quantity leg of the failed match."),
    FactKind(kind="p2p.match_total_variance", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at", "reconciles-against(p2p.match_price_variance, p2p.match_quantity_variance)"),
             about="The two legs, summed — `_checks` recomputes the accrual arithmetic."),
    FactKind(kind="p2p.exception_status", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at", "supersedes-prior"),
             about="The exception's state chain; exactly one status is open at a time."),
    FactKind(kind="p2p.exception_approved_by", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="Who approved paying over the tolerance."),
    FactKind(kind="p2p.approved_payment_value", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="What was actually paid."),
    FactKind(kind="p2p.credit_note_value", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at",), about="The credit note that settles the price leg."),
    FactKind(kind="p2p.vendor_change_status", domain="procurement",
             generated_by="generators/procurement_match.py",
             invariants=("holds-at", "supersedes-prior"),
             about="The vendor-master change request's state chain."),
    FactKind(kind="p2p.open_shortfall_quantity", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at", "carries-forward-as(derive)"),
             about="Undelivered quantity at close; next month's is derived from it."),
    FactKind(kind="p2p.open_shortfall_value", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at", "carries-forward-as(derive)"),
             about="Undelivered value at close — the balance the accrual carries."),
    FactKind(kind="p2p.shortfall_released_quantity", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at",), about="Prior shortfall cleared by this month's receipts."),
    FactKind(kind="p2p.shortfall_released_value", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at",), about="The released balance, valued."),
    FactKind(kind="financial.accrual.grni", domain="procurement",
             generated_by="generators/procurement_cycle.py",
             invariants=("holds-at", "reconciles-against(p2p.open_shortfall_value, p2p.match_total_variance)"),
             about="Goods-received-not-invoiced accrual the close books."),
])


__all__ = [
    "MIDSIZE_INFRASTRUCTURE_SERVICES",
    "PROCUREMENT_ARCHETYPES",
    "ProcureToPayWorld",
    "lore",
]
