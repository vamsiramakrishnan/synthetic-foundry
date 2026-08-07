"""The infrastructure-services organisation generator.

The fourth vertical's own organisation module, for the reason ``banking_org``
and ``insurance_org`` are each their own: byte identity. The minting
*mechanism* — depth-sorted roles, per-role join streams, manager wiring, unit
formation, founding milestones — is ``org_builder``, shared unchanged. What
stays here is content: a role table shaped like a procure-to-pay function's
three actors (procurement, operations, finance), the personas each writes
with, the systems the cycle runs on, and the access policies its commercial
papers are read under.

**What this shape adds that none of the three before it could express: the
buyer and the payer report to different executives.** The Chief Procurement
Officer reports to the CEO and the Accounts Payable Lead reports to the CFO,
so the purchase order's authority and the accounts-payable ledger's authority
are two *functions*, not two systems inside one. That is what makes "the
order says one rate and the ledger says another" a structural disagreement
rather than a finance function contradicting itself — the same argument
``insurance_org`` makes for the appointed actuary reporting to the CEO, and
the same one banking makes for the CRO. And it is load-bearing here in a way
it is not there: the segregation-of-duties check in ``worldloom.procurement``
refuses an exception cleared by the person who raised the order, which is a
rule about two reporting lines and would be vacuous under one.

A third line is needed and is genuinely a third: goods receipting happens at
site, under Operations. Three documents, three functions, three reporting
lines into the CEO — which is precisely the three-way match, drawn as an org
chart.
"""

from __future__ import annotations

from collections.abc import Sequence

from dataclasses import dataclass
from typing import Any

from ..ids import Minter
from ..locales import DEFAULT as DEFAULT_LOCALE, Locale
from ..models import (
    AccessPolicy,
    BusinessUnit,
    CanonicalFact,
    Company,
    CostCentre,
    Employee,
    EnterpriseEvent,
    LoreCommitment,
    Persona,
    Service,
    Site,
    System,
)
from ..parameters import DEFAULT, Parameters
from ..rng import Rng
from ..roles import UnitRole, parse_unit_role
from . import hierarchy, names
from .org_builder import (
    accountability_facts,
    apply_traits,
    form_units,
    founding_milestones,
    mint_people,
    sorted_roles,
    stated_headcount,
    wire_managers,
)


@dataclass(frozen=True)
class ProcurementOrganisation:
    """Everything the infrastructure-services organisation generator produces."""

    company: Company
    business_units: tuple[BusinessUnit, ...]
    people: tuple[Employee, ...]
    systems: tuple[System, ...]
    services: tuple[Service, ...]
    cost_centres: tuple[CostCentre, ...]
    personas: tuple[Persona, ...]
    access_policies: tuple[AccessPolicy, ...]
    categories: tuple[hierarchy.Category, ...]
    sites: tuple[Site, ...]
    roles: dict[str, str]
    milestones: tuple[EnterpriseEvent, ...]
    founding_facts: tuple[CanonicalFact, ...]


#: The published role keys the procure-to-pay episode needs, plus the roles
#: that exist to make the org chart coherent.
#:
#: Three of these are the three-way match, and their *managers* are the point:
#: ``category_manager`` raises the order under ``chief_procurement``,
#: ``site_receiving_lead`` signs the receipt under ``operations_director``,
#: and ``accounts_payable_lead`` posts the invoice under the CFO. No two of
#: the three share a manager below the CEO, which is what the segregation-of-
#: duties check in ``worldloom.procurement`` actually rests on.
_ROLES: tuple[tuple[str, str, str, str | None], ...] = (
    ("ceo", "Group Chief Executive Officer", "Executive", None),
    ("cfo", "Group Chief Financial Officer", "Finance", "ceo"),
    ("chief_procurement", "Chief Procurement Officer", "Procurement", "ceo"),  # not under the CFO
    ("operations_director", "Group Operations Director", "Operations", "ceo"),
    ("financial_controller", "Group Financial Controller", "Finance", "cfo"),
    ("accounts_payable_lead", "Accounts Payable Lead", "Finance", "financial_controller"),
    ("category_manager", "Category Manager, Subcontract and Plant", "Procurement",
     "chief_procurement"),
    ("site_receiving_lead", "Site Receiving Lead", "Operations", "operations_director"),
    ("audit", "Chief Internal Auditor", "Audit", "ceo"),
)

_PERSONAS: tuple[tuple[str, str, str, str, str, float, float, float, tuple[str, ...]], ...] = (
    ("PERSONA-P2P-EXEC", "Executive", "brief, confident, outcome-focused", "low", "low",
     0.3, 0.1, 0.9, ("delivered to programme", "within budget")),
    ("PERSONA-P2P-CFO", "Group CFO", "measured, numeric, protective of working capital",
     "medium", "low", -0.1, -0.3, 0.8, ("on a cash basis", "against the committed spend")),
    ("PERSONA-CPO", "Chief Procurement Officer",
     "commercial, contract-first, insistent on the agreed rate", "high", "high",
     -0.1, -0.4, 0.6, ("the contracted rate", "under the agreement")),
    ("PERSONA-CATEGORY", "Category manager", "practical, supplier-facing, specific",
     "medium", "high", 0.0, -0.2, 0.3, ("against the rate card", "line by line")),
    ("PERSONA-RECEIVING", "Site receiving lead", "operational, literal, terse",
     "low", "medium", 0.0, 0.0, 0.1, ("signed for", "short delivered")),
    ("PERSONA-AP", "Accounts payable", "procedural, ledger-anchored, precise",
     "medium", "medium", -0.2, -0.5, 0.2, ("as posted", "per the invoice")),
    ("PERSONA-P2P-CONTROLLER", "Group Financial Controller",
     "precise, procedural, deadline-driven", "high", "low", -0.2, -0.4, 0.4,
     ("as accrued", "per policy")),
    ("PERSONA-P2P-AUDIT", "Internal audit", "formal, control-oriented, conclusive",
     "high", "low", -0.3, -0.8, 0.5, ("control objective", "we uphold the finding")),
)

#: Which persona each role writes with. Exhaustive over ``_ROLES``, and
#: ``tests/test_procurement.py`` holds it that way — the ``.get(role, default)``
#: this shape replaced could not tell a role deliberately left to the default
#: from one nobody had got round to mapping.
_ROLE_PERSONA = {
    "ceo": "PERSONA-P2P-EXEC",
    "cfo": "PERSONA-P2P-CFO",
    "chief_procurement": "PERSONA-CPO",
    "operations_director": "PERSONA-P2P-EXEC",
    "financial_controller": "PERSONA-P2P-CONTROLLER",
    "accounts_payable_lead": "PERSONA-AP",
    "category_manager": "PERSONA-CATEGORY",
    "site_receiving_lead": "PERSONA-RECEIVING",
    "audit": "PERSONA-P2P-AUDIT",
}

#: The rows ``generate`` mints per business unit — MDs only, as in banking and
#: insurance. Shares ``roles.UnitRole``/``unit_role_key`` with the siblings so
#: the key format exists in exactly one place.
_UNIT_ROLES: tuple[UnitRole, ...] = (
    UnitRole("_md", "Managing Director, {unit}", "Executive", manager="ceo"),
)

#: The per-unit roles ``generate`` appends, by suffix — unit MDs only, as in
#: banking and insurance.
_UNIT_ROLE_PERSONA = {"_md": "PERSONA-P2P-EXEC"}

#: By function, for a role neither table above names — an authored role table
#: (``roles.review``) is mostly roles this module has never seen, which is what
#: makes the function layer load-bearing rather than theoretical.
_FUNCTION_PERSONA = {
    "Executive": "PERSONA-P2P-EXEC",
    "Finance": "PERSONA-P2P-CONTROLLER",
    "Procurement": "PERSONA-CATEGORY",
    "Operations": "PERSONA-RECEIVING",
    "Audit": "PERSONA-P2P-AUDIT",
}

#: Last resort: an authored role in a function this engine has never heard of.
_DEFAULT_PERSONA = "PERSONA-P2P-EXEC"


def _persona_for(role: str, function: str = "") -> str:
    """The persona a role writes with — see ``organisation._persona_for`` for
    the layering and for why an unmapped role is resolved rather than refused."""
    if role in _ROLE_PERSONA:
        return _ROLE_PERSONA[role]
    parsed = parse_unit_role(role, tuple(_UNIT_ROLE_PERSONA))
    if parsed is not None:
        return _UNIT_ROLE_PERSONA[parsed[1]]
    return _FUNCTION_PERSONA.get(function, _DEFAULT_PERSONA)


def _check_persona_ids(voiced: dict[str, Any], minted: dict[str, str]) -> None:
    """Refuse a pack ``persona`` naming an id this world does not have — see
    ``organisation._check_persona_ids``."""
    engine = frozenset(persona[0] for persona in _PERSONAS)
    for role, spec in voiced.items():
        if not spec.persona:
            continue
        allowed = engine if role in minted else engine | frozenset(minted.values())
        if spec.persona not in allowed:
            raise ValueError(
                f"voices[{role!r}].persona names {spec.persona!r}, which is not a"
                f" persona this world has: {', '.join(sorted(allowed))}"
            )


#: Name pools for what a contracting group runs and is called. Module-owned,
#: like the role table — see ``banking_org``'s identical comment for why these
#: do not move to ``generators/names.py``.
#:
#: The suffix pool, and **it is currently unreachable from any shipped
#: locale** — stated rather than quietly carried, because a pool nothing draws
#: from is exactly the "carried, citable and inert" failure this repository
#: keeps finding.
#:
#: ``Locale.industry_suffixes`` is a closed table in ``locales.py`` naming
#: three engines, and ``suffixes_for`` answers an engine it has never heard of
#: with the *retail* pool rather than raising — deliberately, so a new vertical
#: is not made unbuildable by a naming table. So a contractor built today is
#: named from ``company_suffixes`` and comes out as "Ardent Holdings", which is
#: a perfectly plausible contractor and is not this engine's own vocabulary.
#: The gap is the same class as ``parameters.DEFAULTS`` and
#: ``landscape.LANDSCAPES``: a core table with no registration seam.
#:
#: This pool stays because it *is* reached the moment either of two things
#: happens — a locale (or a pack-authored one) states an empty pool, or
#: ``industry_suffixes`` grows a seam — and deleting it would mean rediscovering
#: what a contracting group is called in the jurisdiction this engine was
#: written for.
_CONTRACTOR_SUFFIX = ("Infrastructure", "Group Services", "Contracting", "Infrastructure Group")
_SOURCING = ("Sourcemark", "Contract Vault", "Vendorline")
_PROCURE = ("Requisite P2P", "OrderBridge", "Procureflow")
_RECEIPTING = ("SiteReceipt", "Fieldlog Receipting", "Deliverypoint")
_AP_LEDGER = ("PayablesOne", "Invoice Register", "Settleworks")
_GENERAL_LEDGER = ("Ledgerbase", "Meridian General Ledger", "Groupledger")


def generate(
    rng: Rng,
    minter: Minter,
    *,
    archetype,  # type: ignore[no-untyped-def]
    lore: tuple[LoreCommitment, ...] = (),
    company_name: str | None = None,
    system_brands: dict[str, str] | None = None,
    voices: dict[str, Any] | None = None,
    name_pools: dict[str, list[str]] | None = None,
    headquarters: str | None = None,
    regions: tuple[str, ...] | None = None,
    locale: Locale = DEFAULT_LOCALE,
    employees_total: int | None = None,
    # This module's own `_ROLES`, replaced. `None` means use them. A supplied
    # table still has the per-unit roles appended below and must have gone
    # through `roles.review` first: several of these keys are looked up by name
    # in generator code, and a table missing one raises `KeyError` part-way
    # through an episode rather than building a different company.
    role_table: Sequence[tuple[str, str, str, str | None]] | None = None,
    physics: Parameters = DEFAULT,
) -> ProcurementOrganisation:
    """Build the contracting group for an archetype. Same seed, same graph, same ids.

    ``company_name``, ``system_brands``, ``voices``, ``name_pools``,
    ``headquarters``, ``regions`` and ``locale`` are the pack override set —
    see ``organisation.generate`` for what each means and for why the narrower
    claim beats the locale. Every value is drawn whether or not it is
    overridden, so none of them reshuffles a downstream stream. That rule is
    why the two company draws below happen before ``company_name`` and
    ``headquarters`` are consulted rather than inside an ``if``.
    """
    company_rng = rng.derive("company")
    brands = system_brands or {}
    company_id = minter.next("CO")
    units = archetype.units
    unit_ids = {unit.key: minter.next("BU") for unit in units}

    role_table = list(_ROLES if role_table is None else role_table)
    for unit in units:
        for spec in _UNIT_ROLES:
            role_table.append(spec.row(unit.key, unit.name))
    role_table, depth_of = sorted_roles(role_table)

    finance_cc = minter.next("CC")
    commercial_cc = minter.next("CC")

    # See organisation.py: a voiced role writes with a clone of its base, a
    # remap points its role at a persona that already exists.
    function_of = {row[0]: row[2] for row in role_table}
    voiced: dict[str, Any] = {
        role: spec for role, spec in sorted((voices or {}).items()) if role in function_of
    }
    pack_voice_ids = {
        role: f"PERSONA-PACK-{role.upper().replace('_', '-')}"
        for role, spec in voiced.items() if not spec.is_remap()
    }
    persona_remap = {role: spec.persona for role, spec in voiced.items() if spec.is_remap()}
    _check_persona_ids(voiced, pack_voice_ids)

    def assign(role: str, title: str, function: str):  # type: ignore[no-untyped-def]
        """One decision per person: MDs sit in their unit; cost centres split
        the finance side from the commercial side; personas come from the role
        table.

        The cost-centre split follows the *dispute*, not the org chart:
        Procurement and Operations share a centre because they are the two
        functions that commit and receive, and Finance and Audit share the
        other because they are the two that pay and check. A split by
        reporting line would have put Operations with the CEO and said nothing.
        """
        business_unit = None
        parsed = parse_unit_role(role, tuple(spec.suffix for spec in _UNIT_ROLES))
        if parsed is not None:
            business_unit = unit_ids[parsed[0]]
        cost_centre = (
            finance_cc if function in ("Finance", "Audit")
            else commercial_cc if function in ("Procurement", "Operations")
            else None
        )
        persona = (
            pack_voice_ids.get(role)
            or persona_remap.get(role)
            or _persona_for(role, function)
        )
        return business_unit, cost_centre, persona

    pools = name_pools or {}
    role_ids, people = mint_people(
        rng, minter, role_table, depth_of, assign=assign,
        given=pools.get("given") or None, family=pools.get("family") or None,
        locale=locale,
        physics=physics,
    )
    people = wire_managers(people, role_table, role_ids)
    business_units = form_units(units, unit_ids, role_ids, people, company_id, lore)

    # Spend categories through the shared dimension machinery. `buyers` is
    # empty and that is the one place this vertical's misfit shows: retail's
    # `Category.buyer_id` is exactly the field a procurement corpus wants —
    # "who buys this category" — but the buyer here is a *role* held by one
    # person across every unit (`category_manager`), not a per-unit merchandise
    # buyer, and populating it per unit would assert three buyers where there
    # is one. Recorded in `worldloom.procurement`'s docstring rather than
    # papered over.
    dimensions = hierarchy.generate(
        rng.derive("hierarchy"), minter,
        units=units,
        unit_ids=unit_ids,
        buyers={},
        regions=regions,
        locale=locale,
        physics=physics,
    )

    sourcing = minter.next("SYS")
    procure = minter.next("SYS")
    receipting = minter.next("SYS")
    ap_ledger = minter.next("SYS")
    general_ledger = minter.next("SYS")
    systems = (
        System(id=sourcing,
               name=brands.get("sourcing") or company_rng.derive("sourcing").choice(_SOURCING),
               purpose="Sourcing and contract management: rate cards, terms, and the vendor master",
               owner_id=role_ids["chief_procurement"],
               is_system_of_record_for=["contracts", "vendor_master"]),
        System(id=procure,
               name=brands.get("procure") or company_rng.derive("procure").choice(_PROCURE),
               purpose="Requisition to purchase order: what was committed, to whom, at what rate",
               owner_id=role_ids["category_manager"],
               is_system_of_record_for=["purchase_orders"]),
        System(id=receipting,
               name=brands.get("receipting") or company_rng.derive("receipting").choice(_RECEIPTING),
               purpose="Goods and services receipting at site: what actually arrived",
               owner_id=role_ids["site_receiving_lead"],
               is_system_of_record_for=["goods_receipts"]),
        System(id=ap_ledger,
               name=brands.get("ap_ledger") or company_rng.derive("ap_ledger").choice(_AP_LEDGER),
               purpose="Accounts payable subledger: supplier invoices as posted, and the match",
               owner_id=role_ids["accounts_payable_lead"],
               is_system_of_record_for=["supplier_invoices", "match_exceptions"]),
        System(id=general_ledger,
               name=brands.get("general_ledger") or company_rng.derive("gl").choice(_GENERAL_LEDGER),
               purpose="General ledger: the accrual for what was received, and the close",
               owner_id=role_ids["financial_controller"],
               is_system_of_record_for=["general_ledger", "financial_reporting"]),
    )

    personas = tuple(
        Persona(
            id=persona_id, label=label, voice=voice,
            sentence_complexity=complexity,  # type: ignore[arg-type]
            technical_depth=depth,  # type: ignore[arg-type]
            optimism=optimism, risk_tolerance=risk, political_awareness=political,
            favourite_phrases=list(phrases), traits={},
        )
        for persona_id, label, voice, complexity, depth, optimism, risk, political, phrases
        in _PERSONAS
    )
    if pack_voice_ids:
        by_id = {p.id: p for p in personas}
        clones = []
        for role, persona_id in pack_voice_ids.items():
            spec = voiced[role]
            base = by_id[spec.persona or _persona_for(role, function_of[role])]
            clones.append(base.model_copy(update={
                "id": persona_id,
                "label": f"{base.label} ({role})",
                "voice": spec.voice or base.voice,
                "sentence_complexity": spec.sentence_complexity or base.sentence_complexity,
                "technical_depth": spec.technical_depth or base.technical_depth,
                "favourite_phrases": list(spec.phrases) or list(base.favourite_phrases),
            }))
        personas += tuple(clones)
    people = apply_traits(people, lore, role_ids)

    cost_centres = (
        CostCentre(id=finance_cc, name="Finance Shared Services",
                   owner_id=role_ids["financial_controller"], business_unit_id=None),
        CostCentre(id=commercial_cc, name="Commercial and Supply Chain",
                   owner_id=role_ids["chief_procurement"], business_unit_id=None),
    )

    # Four policies, and the third is the one this vertical exists to exercise.
    #
    # `World._policy_for` maps an intent's *audience* onto a policy by matching
    # the audience with underscores replaced by spaces against the policy
    # label, so these labels are an interface: `audience="vendor_master"` finds
    # "Vendor master" and nothing else. The vendor master is the only policy
    # here that denies a function outright — Operations may sign for a delivery
    # and may not see a supplier's banking details, which is the segregation
    # the dual-approval norm is written about. A policy that admitted everyone
    # would make the access checks decoration.
    policies = (
        AccessPolicy(id=minter.next("POLICY"), label="All staff"),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Procurement and finance",
            allow_functions=["Procurement", "Finance", "Operations", "Audit"],
            allow_people=[role_ids["ceo"]],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Vendor master",
            allow_functions=["Procurement", "Finance", "Audit"],
            allow_people=[role_ids["ceo"]],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Commercial review",
            allow_functions=["Executive", "Procurement", "Finance", "Operations", "Audit"],
        ),
    )

    # Drawn before either override is applied — the pack override rule: naming
    # the company or its headquarters must not change what any other stream
    # draws.
    suffixes = locale.suffixes_for("procurement") or _CONTRACTOR_SUFFIX
    generated_name = f"{company_rng.choice(names.COMPANY_FIRST)} {company_rng.choice(suffixes)}"
    generated_hq = names.headquarters(company_rng.derive("hq"), locale=locale)
    company = Company(
        id=company_id,
        name=company_name or generated_name,
        industry=archetype.industry,
        headquarters=headquarters or generated_hq,
        fiscal_year_start_month=archetype.fiscal_year_start_month,
        currency=archetype.currency,
        currency_unit=archetype.currency_unit,
        employees_total=stated_headcount(
            employees_total,
            archetype_headcount=archetype.employees,
            modelled_headcount=len(people),
        ),
    )

    milestones, founding_facts = founding_milestones(minter, lore, company_id)
    founding_facts = founding_facts + accountability_facts(minter, lore, role_ids)

    # The two categories the cycle's order sits on get named handles, because
    # the episode is scoped to them: one contested line and one clean line, in
    # the *same* three documents. A pack that names its categories differently
    # gets the two heaviest by group weight, deterministically — the same
    # fallback `banking_org` and `insurance_org` use, extended to a pair
    # because this episode needs two lines and not one.
    #
    # Sorted by (weight, id) descending and then re-sorted by id, so the pair
    # is chosen by weight and *ordered* by id: minting order has to be a
    # function of identity alone, or a pack whose weights shifted by a
    # rounding would silently swap which line is the contested one.
    by_name = {c.name: c.id for c in dimensions.categories}
    contested = by_name.get("Subcontract Labour")
    clean = by_name.get("Plant Hire")
    if (contested is None or clean is None) and len(dimensions.categories) >= 2:
        unit_share = {unit_ids[unit.key]: unit.share for unit in units}
        ranked = sorted(
            dimensions.categories,
            key=lambda c: (-(unit_share.get(c.business_unit_id, 0.0) * c.revenue_share), c.id),
        )
        contested, clean = (c.id for c in sorted(ranked[:2], key=lambda c: c.id))

    handles: dict[str, str] = {}
    if contested and clean:
        handles = {"cat_contested_line": contested, "cat_clean_line": clean}

    return ProcurementOrganisation(
        company=company,
        business_units=business_units,
        people=tuple(people),
        systems=systems,
        # Empty, like the insurer's. A contracting group certainly runs
        # services, but this engine's episode names none of them, and minting
        # a catalogue nothing depends on would put nodes in the topology with
        # no edges — the flat-list failure `worldloom topology` exists to
        # report. `--estate` is where a landscape belongs, and
        # `ProcureToPayWorld.estate` states why this vertical has none yet.
        services=(),
        cost_centres=cost_centres,
        personas=personas,
        access_policies=policies,
        categories=dimensions.categories,
        sites=dimensions.sites,
        milestones=milestones,
        founding_facts=founding_facts,
        roles={
            **role_ids,
            **{f"unit_{unit.key}": unit_ids[unit.key] for unit in units},
            "sys_sourcing": sourcing,
            "sys_procure": procure,
            "sys_receipting": receipting,
            "sys_ap_ledger": ap_ledger,
            "sys_general_ledger": general_ledger,
            **handles,
            "policy_all": policies[0].id,
            "policy_procurement_finance": policies[1].id,
            "policy_vendor_master": policies[2].id,
            "policy_commercial_review": policies[3].id,
            "cc_finance": finance_cc,
            "cc_commercial": commercial_cc,
        },
    )
