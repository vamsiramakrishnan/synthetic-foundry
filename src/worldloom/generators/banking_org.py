"""The banking organisation generator.

Banking gets its own generator rather than a parameterisation of
``organisation.generate``, and the reason is byte identity, not taste: retail's
generator mints ids and draws rng streams in an order that the checked-in
narration replay depends on, and threading a second role table through it would
have to preserve that order forever. Two small machines that cannot disturb each
other beat one configurable machine that must never be touched.

The minting *mechanism* the two machines share — depth-sorted roles, per-role
join-date streams, manager wiring, unit formation, founding milestones — was
extracted to ``org_builder`` once both existed, per §7a's extract-after-two
rule. What stays here is banking content: the role table with its three lines
of defence, the personas, the systems a bank runs, and the policies its
filings are read under.

What banking's shape adds that retail's could not express: the three lines of
defence. The Chief Risk Officer reports to the CEO, **not** the CFO — the
independent reporting line is the whole point of a second line — and internal
audit reports administratively to the CEO while its functional reporting to the
board audit committee is recorded as lore (``banking.lore``), because a
committee is not an ``Employee`` and pretending otherwise would put a fake
person in the org tree. No evaluation may key audit independence on the
reporting graph; standing questions resolve through authority rank, access
policies, and the charter norm instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ids import Minter
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
from ..rng import Rng
from . import hierarchy, names
from .org_builder import (
    apply_traits,
    form_units,
    founding_milestones,
    mint_people,
    sorted_roles,
    wire_managers,
)


@dataclass(frozen=True)
class BankOrganisation:
    """Everything the banking organisation generator produces."""

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


#: The people a capital-return episode needs, in reporting order. The first
#: line prepares and files, the second line challenges, the third line rules —
#: the table is the topology the episode exercises, so the lines are labelled.
_ROLES: tuple[tuple[str, str, str, str | None], ...] = (
    ("ceo", "Group Chief Executive Officer", "Executive", None),
    ("cfo", "Group Chief Financial Officer", "Finance", "ceo"),          # 1st line
    ("cro", "Chief Risk Officer", "Risk", "ceo"),                        # 2nd line — NOT under the CFO
    ("cio", "Chief Information Officer", "Technology", "ceo"),
    ("audit", "Chief Internal Auditor", "Audit", "ceo"),                 # 3rd line, administratively
    ("controller", "Group Financial Controller", "Finance", "cfo"),
    ("reg_reporting_manager", "Regulatory Reporting Manager", "Finance", "cfo"),
    ("treasurer", "Group Treasurer", "Treasury", "cfo"),
    ("reg_analyst", "Regulatory Reporting Analyst", "Finance", "reg_reporting_manager"),
    ("liquidity_analyst", "Liquidity Reporting Analyst", "Treasury", "treasurer"),
    ("prudential_risk_head", "Head of Prudential Risk", "Risk", "cro"),
    ("credit_risk_lead", "Head of Credit Risk Analytics", "Risk", "cro"),
    ("audit_manager", "Internal Audit Manager", "Audit", "audit"),
    ("platform_lead", "Head of Risk Data Platform", "Technology", "cio"),
    ("platform_senior", "Senior Risk Platform Engineer", "Technology", "platform_lead"),
    ("svc_lead", "Head of Service Operations", "ServiceOperations", "cio"),
    ("svc_desk", "Service Desk Analyst", "ServiceOperations", "svc_lead"),
    ("svc_incident", "Major Incident Manager", "ServiceOperations", "svc_lead"),
)

_PERSONAS: tuple[tuple[str, str, str, str, str, float, float, float, tuple[str, ...]], ...] = (
    ("PERSONA-BANK-CFO", "Group CFO", "measured, numeric, decisive under deadline", "medium", "low", -0.1, -0.3, 0.8,
     ("on a normalised basis", "within appetite")),
    ("PERSONA-REG-REPORTING", "Regulatory reporting", "precise, procedural, deadline-driven", "high", "low", -0.2, -0.6, 0.4,
     ("as submitted", "per the standard")),
    ("PERSONA-PRUDENTIAL", "Prudential risk", "formal, insistent on the record", "high", "low", -0.3, -0.7, 0.6,
     ("on the record", "cannot be confirmed")),
    ("PERSONA-CREDIT-RISK", "Credit risk analytics", "quantitative, methodology-first", "medium", "medium", -0.1, -0.4, 0.3,
     ("risk-weight methodology", "collateral coverage")),
    ("PERSONA-BANK-AUDIT", "Internal audit", "formal, control-oriented, conclusive", "high", "low", -0.3, -0.8, 0.5,
     ("control objective", "we uphold the finding")),
    ("PERSONA-TREASURY", "Treasury", "terse, market-facing, daily-cadence", "low", "medium", 0.0, 0.1, 0.3,
     ("as at close of business", "coverage ratio")),
    ("PERSONA-RISK-PLATFORM", "Risk platform engineer", "terse, technical, evidence-first", "low", "high", -0.1, 0.2, 0.1,
     ("upstream feed", "reconciliation break")),
    ("PERSONA-BANK-SVC", "Service operations", "clipped, template-driven", "low", "medium", 0.3, 0.0, 0.1,
     ("awaiting update", "under investigation")),
    ("PERSONA-BANK-EXEC", "Executive", "brief, confident, outcome-focused", "low", "low", 0.3, 0.1, 0.9,
     ("well capitalised", "prudent")),
)

_ROLE_PERSONA = {
    "ceo": "PERSONA-BANK-EXEC",
    "cfo": "PERSONA-BANK-CFO",
    "cro": "PERSONA-PRUDENTIAL",
    "cio": "PERSONA-BANK-EXEC",
    "audit": "PERSONA-BANK-AUDIT",
    "audit_manager": "PERSONA-BANK-AUDIT",
    "controller": "PERSONA-REG-REPORTING",
    "reg_reporting_manager": "PERSONA-REG-REPORTING",
    "reg_analyst": "PERSONA-REG-REPORTING",
    "treasurer": "PERSONA-TREASURY",
    "liquidity_analyst": "PERSONA-TREASURY",
    "prudential_risk_head": "PERSONA-PRUDENTIAL",
    "credit_risk_lead": "PERSONA-CREDIT-RISK",
    "platform_lead": "PERSONA-RISK-PLATFORM",
    "platform_senior": "PERSONA-RISK-PLATFORM",
    "svc_lead": "PERSONA-BANK-SVC",
    "svc_desk": "PERSONA-BANK-SVC",
    "svc_incident": "PERSONA-BANK-SVC",
}

#: Name pools for what a bank runs. Module-owned, like the role table: pushing
#: these into ``generators/names.py`` would grow a "temporary" file the docs
#: already promise to delete, and the telco experiment showed shared pools are
#: one of the six places retail leaks into a supposedly different vertical.
_BANK_SUFFIX = ("Banking Group", "Bank", "Banking Corporation", "Mutual Bank")
_CORE = ("Ledgerline Core", "Meridian Core Banking", "Basis Core", "Vaultline")
_COLLATERAL = ("Collateral Register", "Security Interest Hub", "Collateral Central")
_RISK = ("Prudent Risk Platform", "Basel Analytics Platform", "Riskline Aggregation")
_PORTAL = ("PSA Direct", "Regulatory Lodgement Portal", "Prudential Gateway")
_MARKET = ("Rateswire", "Market Data Fabric", "EOD Rates Service")


def generate(
    rng: Rng,
    minter: Minter,
    *,
    archetype,  # type: ignore[no-untyped-def]
    lore: tuple[LoreCommitment, ...] = (),
    company_name: str | None = None,
    system_brands: dict[str, str] | None = None,
    voices: dict[str, Any] | None = None,
) -> BankOrganisation:
    """Build the bank for an archetype. Same seed, same graph, same ids.

    ``company_name``, ``system_brands`` and ``voices`` are the pack override
    trio — see ``organisation.generate``. Overrides can never reshuffle a
    downstream stream: the company name is drawn regardless, and each system
    name comes from its own derived stream that nothing else reads.
    """
    company_rng = rng.derive("company")
    brands = system_brands or {}
    company_id = minter.next("CO")
    units = archetype.units
    unit_ids = {unit.key: minter.next("BU") for unit in units}

    role_table = list(_ROLES)
    for unit in units:
        role_table.append((f"{unit.key}_md", f"Managing Director, {unit.name}", "Executive", "ceo"))
    role_table, depth_of = sorted_roles(role_table)

    finance_cc = minter.next("CC")
    risk_cc = minter.next("CC")

    # See organisation.py: voiced roles write with pack personas, cloned from
    # their defaults after the default tuple is built.
    pack_voice_ids = {
        role: f"PERSONA-PACK-{role.upper().replace('_', '-')}"
        for role in (voices or {})
    }

    def assign(role: str, title: str, function: str):  # type: ignore[no-untyped-def]
        """Banking's one decision per person: MDs sit in their unit and the
        treasury desk in its own; cost centres split finance-side from
        risk-and-platform; personas come from the role table."""
        business_unit = None
        if role.endswith("_md"):
            business_unit = unit_ids[role[:-3]]
        elif role in ("treasurer", "liquidity_analyst") and "treasury" in unit_ids:
            business_unit = unit_ids["treasury"]
        cost_centre = (
            finance_cc if function in ("Finance", "Audit", "Treasury")
            else risk_cc if function in ("Risk", "Technology")
            else None
        )
        persona = pack_voice_ids.get(role) or _ROLE_PERSONA.get(role, "PERSONA-BANK-EXEC")
        return business_unit, cost_centre, persona

    role_ids, people = mint_people(rng, minter, role_table, depth_of, assign=assign)
    people = wire_managers(people, role_table, role_ids)
    business_units = form_units(units, unit_ids, role_ids, people, company_id, lore)

    # Product books and the branch estate through the shared dimension
    # machinery. `buyers` is empty on purpose: a book's accountable executive is
    # a role, not a retail buyer, and punning `Category.buyer_id` into
    # "portfolio head" would read as a retail assumption at pack-extraction
    # time. The accountability lives in the role table (business_md,
    # credit_risk_lead) instead, and the misfit is recorded in
    # ``worldloom.banking``'s docstring as §7a evidence.
    dimensions = hierarchy.generate(
        rng.derive("hierarchy"), minter,
        units=units,
        unit_ids=unit_ids,
        buyers={},
    )

    core = minter.next("SYS")
    collateral = minter.next("SYS")
    risk_platform = minter.next("SYS")
    reg_portal = minter.next("SYS")
    market_data = minter.next("SYS")
    # Drawn first, then re-branded — the pack override trio's rule.
    systems = (
        System(id=core,
               name=brands.get("core_banking") or company_rng.derive("core").choice(_CORE),
               purpose="Core banking ledger and general ledger of record",
               owner_id=role_ids["controller"],
               is_system_of_record_for=["general_ledger", "financial_reporting"]),
        System(id=collateral,
               name=brands.get("collateral") or company_rng.derive("collateral").choice(_COLLATERAL),
               purpose="Collateral management: security interests and revaluation schedules",
               owner_id=role_ids["credit_risk_lead"],
               is_system_of_record_for=["collateral_valuations"]),
        System(id=risk_platform,
               name=brands.get("risk_platform") or company_rng.derive("risk").choice(_RISK),
               purpose="Risk data aggregation for capital and liquidity calculation",
               owner_id=role_ids["platform_lead"],
               is_system_of_record_for=["risk_weighted_assets", "liquidity_coverage"]),
        System(id=reg_portal,
               name=brands.get("reg_portal") or company_rng.derive("portal").choice(_PORTAL),
               purpose="Regulatory filing portal; a lodged return is immutable here",
               owner_id=role_ids["reg_reporting_manager"],
               is_system_of_record_for=["regulatory_filings"]),
        System(id=market_data,
               name=brands.get("market_data") or company_rng.derive("market").choice(_MARKET),
               purpose="Market data and end-of-day FX rates",
               owner_id=role_ids["platform_senior"],
               is_system_of_record_for=["fx_rates"]),
    )

    # The dependency graph is the episode's physics stated structurally: two
    # tier-1 consumers share one upstream, and only the daily one reconciles
    # against the collateral system. That is why the daily cadence catches the
    # quarterly cadence's error, and no document has to say so for it to be
    # true in the corpus.
    collateral_sync = minter.next("SVC")
    rwa_engine = minter.next("SVC")
    lcr_daily = minter.next("SVC")
    filing_gateway = minter.next("SVC")
    services = (
        Service(id=collateral_sync, name="collateral-valuation-sync",
                purpose="Publishes collateral valuations from the collateral register to the risk platform",
                owner_id=role_ids["platform_senior"], system_id=collateral,
                criticality_tier=2, depends_on=[collateral]),
        Service(id=rwa_engine, name="rwa-capital-engine",
                purpose="Calculates risk-weighted assets and the capital ratios for the quarterly return",
                owner_id=role_ids["platform_senior"], system_id=risk_platform,
                criticality_tier=1, depends_on=[collateral_sync, risk_platform]),
        Service(id=lcr_daily, name="lcr-daily-calculator",
                purpose="Calculates the daily liquidity coverage ratio, reconciling inputs against the collateral register",
                owner_id=role_ids["platform_lead"], system_id=risk_platform,
                criticality_tier=1, depends_on=[collateral_sync, risk_platform]),
        Service(id=filing_gateway, name="regulatory-filing-gateway",
                purpose="Assembles and lodges returns to the regulatory portal",
                owner_id=role_ids["platform_lead"], system_id=reg_portal,
                criticality_tier=1, depends_on=[reg_portal]),
    )

    personas = tuple(
        Persona(
            id=persona_id, label=label, voice=voice,
            sentence_complexity=complexity,  # type: ignore[arg-type]
            technical_depth=depth,  # type: ignore[arg-type]
            optimism=optimism, risk_tolerance=risk, political_awareness=political,
            favourite_phrases=list(phrases), traits={},
        )
        for persona_id, label, voice, complexity, depth, optimism, risk, political, phrases in _PERSONAS
    )
    if voices:
        by_id = {p.id: p for p in personas}
        clones = []
        for role, spec in sorted(voices.items()):
            if role not in role_ids:
                continue  # linted upstream; an unknown role must not orphan a persona
            base = by_id[_ROLE_PERSONA.get(role, "PERSONA-BANK-EXEC")]
            clones.append(base.model_copy(update={
                "id": pack_voice_ids[role],
                "label": f"{base.label} ({role})",
                "voice": spec.voice or base.voice,
                "favourite_phrases": list(spec.phrases) or list(base.favourite_phrases),
            }))
        personas += tuple(clones)
    people = apply_traits(people, lore, role_ids)

    cost_centres = (
        CostCentre(id=finance_cc, name="Finance and Treasury Shared Services",
                   owner_id=role_ids["controller"], business_unit_id=None),
        CostCentre(id=risk_cc, name="Risk and Data Platform",
                   owner_id=role_ids["platform_lead"], business_unit_id=None),
    )

    # Labels double as audience keys: `World._policy_for` matches an intent's
    # audience against a policy label before anything else, so "finance_and_risk"
    # resolves to "Finance and risk" without a table in core naming it.
    policies = (
        AccessPolicy(id=minter.next("POLICY"), label="All staff"),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Finance and risk",
            allow_functions=["Finance", "Risk", "Audit", "Treasury"],
            allow_people=[role_ids["ceo"], role_ids["cio"]],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Technology and risk",
            allow_functions=["Technology", "ServiceOperations", "Risk"],
            allow_people=[role_ids["cio"]],
        ),
        # Audit reads the bank's copy of every filing without being on the
        # preparing team — that grant is the third line's charter made
        # mechanical, and the banking check group asserts it holds.
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Prudential regulator",
            allow_functions=["Finance", "Risk", "Audit", "Executive"],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Board risk committee",
            allow_functions=["Executive", "Audit"],
            allow_people=[role_ids["cfo"], role_ids["cro"]],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Executive committee",
            allow_functions=["Executive"],
            allow_people=[role_ids["cfo"], role_ids["cro"], role_ids["audit"]],
        ),
    )

    generated_name = f"{company_rng.choice(names.COMPANY_FIRST)} {company_rng.choice(_BANK_SUFFIX)}"
    company = Company(
        id=company_id,
        name=company_name or generated_name,
        industry=archetype.industry,
        headquarters=names.headquarters(company_rng.derive("hq")),
        fiscal_year_start_month=archetype.fiscal_year_start_month,
        currency=archetype.currency,
        currency_unit=archetype.currency_unit,
        employees_total=archetype.employees,
    )

    milestones, founding_facts = founding_milestones(minter, lore, company_id)

    # The affected book gets a named handle because the episode's error is
    # scoped to it — the affected-book fact and the correction-scope check both
    # need to name one book. The stock archetype's is SME Secured Lending by
    # name; a pack that names its books differently gets the heaviest book by
    # group weight (unit share × category share), which is deterministic and
    # is also the book a real revaluation lapse would hurt most.
    sme_book = next(
        (c.id for c in dimensions.categories if c.name == "SME Secured Lending"), None
    )
    if sme_book is None and dimensions.categories:
        unit_share = {unit_ids[unit.key]: unit.share for unit in units}
        sme_book = max(
            dimensions.categories,
            key=lambda c: (unit_share.get(c.business_unit_id, 0.0) * c.revenue_share, c.id),
        ).id

    return BankOrganisation(
        company=company,
        business_units=business_units,
        people=tuple(people),
        systems=systems,
        services=services,
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
            "sys_core_banking": core,
            "sys_collateral": collateral,
            "sys_risk_platform": risk_platform,
            "sys_reg_portal": reg_portal,
            "sys_market_data": market_data,
            "svc_collateral_sync": collateral_sync,
            "svc_rwa_engine": rwa_engine,
            "svc_lcr_daily": lcr_daily,
            "svc_filing_gateway": filing_gateway,
            **({"cat_sme_secured": sme_book} if sme_book else {}),
            "policy_all": policies[0].id,
            "policy_finance_risk": policies[1].id,
            "policy_tech_risk": policies[2].id,
            "policy_regulator": policies[3].id,
            "policy_board_risk": policies[4].id,
            "policy_exec": policies[5].id,
            "cc_finance": finance_cc,
            "cc_risk": risk_cc,
        },
    )
