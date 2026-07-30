"""The organisation generator.

Builds the entity graph: company, business units, people, systems, services, cost
centres, personas, access policies. Deterministic throughout — the model proposes
*shape* in later steps, but the graph itself is built and validated here, because
referential integrity and acyclicity are correctness concerns.

Lore reaches this generator through two constraint kinds: ``org_shape`` adjusts
topology, and ``persona_trait`` adjusts how specific people write.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ids import Minter
from ..models import (
    AccessPolicy,
    BusinessUnit,
    Category,
    Company,
    CostCentre,
    Employee,
    LoreCommitment,
    Persona,
    Service,
    Site,
    System,
)
from ..rng import Rng
from . import hierarchy, names


@dataclass(frozen=True)
class Organisation:
    """Everything the organisation generator produces."""

    company: Company
    business_units: tuple[BusinessUnit, ...]
    people: tuple[Employee, ...]
    systems: tuple[System, ...]
    services: tuple[Service, ...]
    cost_centres: tuple[CostCentre, ...]
    personas: tuple[Persona, ...]
    access_policies: tuple[AccessPolicy, ...]
    categories: tuple[Category, ...]
    sites: tuple[Site, ...]
    dimensions: hierarchy.Dimensions
    roles: dict[str, str]
    """Role key to person ID, so scenarios can find the controller without guessing."""


#: The people every retail-close episode needs, in reporting order. Titles are
#: structural: a scenario asks for ``roles["controller"]``, never for a name.
_ROLES: tuple[tuple[str, str, str, str | None], ...] = (
    # (role key, title, function, manager role key)
    ("ceo", "Group Chief Executive Officer", "Executive", None),
    ("cfo", "Group Chief Financial Officer", "Finance", "ceo"),
    ("cio", "Chief Information Officer", "Technology", "ceo"),
    ("controller", "Group Financial Controller", "Finance", "cfo"),
    ("reporting_manager", "Group Reporting Manager", "Finance", "controller"),
    ("audit", "Internal Audit Manager", "Audit", "cfo"),
    ("platform_lead", "Head of Data Platform", "Technology", "cio"),
    ("platform_senior", "Senior Data Platform Engineer", "Technology", "platform_lead"),
    ("platform_engineer", "Data Platform Engineer", "Technology", "platform_lead"),
    ("svc_lead", "Head of Service Operations", "ServiceOperations", "cio"),
    ("svc_desk", "Service Desk Analyst", "ServiceOperations", "svc_lead"),
    ("svc_incident", "Major Incident Manager", "ServiceOperations", "svc_lead"),
    ("merch_lead", "Head of Merchandising Systems", "Merchandising", "gm_md"),
    ("merch_analyst", "Merchandising Systems Analyst", "Merchandising", "merch_lead"),
)

_PERSONAS: tuple[tuple[str, str, str, str, str, float, float, float, tuple[str, ...]], ...] = (
    ("PERSONA-CFO", "Group CFO", "measured, numeric, unsentimental", "medium", "low", -0.1, -0.4, 0.8,
     ("on a like-for-like basis", "materially")),
    ("PERSONA-CONTROLLER", "Financial controller", "precise, procedural, cautious", "high", "low", -0.2, -0.7, 0.5,
     ("control environment", "for completeness")),
    ("PERSONA-FIN-BP", "Finance business partner", "commercial, explanatory", "medium", "low", 0.1, -0.2, 0.6,
     ("run-rate", "phasing")),
    ("PERSONA-ENG-LEAD", "Engineering leader", "direct, systems-oriented", "medium", "high", 0.0, 0.1, 0.4,
     ("upstream", "idempotent")),
    ("PERSONA-ENG-PLATFORM", "Platform engineer", "terse, technical, evidence-first", "low", "high", -0.1, 0.2, 0.1,
     ("root cause", "blast radius")),
    ("PERSONA-SVC-LEAD", "Service operations leader", "procedural, status-driven", "medium", "medium", 0.0, -0.3, 0.5,
     ("per the runbook", "time to restore")),
    ("PERSONA-SVC-OPS", "Service desk", "clipped, template-driven", "low", "medium", 0.3, 0.0, 0.1,
     ("awaiting update", "under investigation")),
    ("PERSONA-MERCH-LEAD", "Merchandising leader", "commercial, defensive under scrutiny", "medium", "low", 0.2, 0.1, 0.7,
     ("range architecture", "category")),
    ("PERSONA-MERCH", "Merchandising analyst", "operational, detail-heavy", "low", "medium", 0.0, -0.1, 0.2,
     ("mapping table", "hierarchy node")),
    ("PERSONA-AUDIT", "Internal audit", "formal, control-oriented", "high", "low", -0.3, -0.8, 0.6,
     ("control objective", "evidence")),
    ("PERSONA-EXEC", "Executive", "brief, confident, outcome-focused", "low", "low", 0.4, 0.2, 0.9,
     ("strategically", "headwinds")),
)

#: Which persona each role writes with.
_ROLE_PERSONA = {
    "ceo": "PERSONA-EXEC",
    "cfo": "PERSONA-CFO",
    "cio": "PERSONA-EXEC",
    "controller": "PERSONA-CONTROLLER",
    "reporting_manager": "PERSONA-CONTROLLER",
    "audit": "PERSONA-AUDIT",
    "platform_lead": "PERSONA-ENG-LEAD",
    "platform_senior": "PERSONA-ENG-PLATFORM",
    "platform_engineer": "PERSONA-ENG-PLATFORM",
    "svc_lead": "PERSONA-SVC-LEAD",
    "svc_desk": "PERSONA-SVC-OPS",
    "svc_incident": "PERSONA-SVC-OPS",
    "merch_lead": "PERSONA-MERCH-LEAD",
    "merch_analyst": "PERSONA-MERCH",
}

#: Business-unit finance partners all write with the same persona.
_UNIT_ROLE_PERSONA = {"_md": "PERSONA-EXEC", "_bp": "PERSONA-FIN-BP", "buyer": "PERSONA-MERCH-LEAD"}


def _merch_unit(unit_ids: dict[str, str]) -> str:
    """Which unit merchandising systems sits under.

    General merchandise when there is one, since that is where range architecture
    is fought over; otherwise the first unit.
    """
    return "gm" if "gm" in unit_ids else next(iter(unit_ids))


def _persona_traits(lore: tuple[LoreCommitment, ...], role_ids: dict[str, str]) -> dict[str, dict[str, float]]:
    """Apply lore ``persona_trait`` constraints, keyed by person ID.

    A constraint target is written ``ROLE/trait`` — a role rather than a person
    ID, because lore is authored before the graph exists and cannot know who
    ``PERSON-0017`` will be.
    """
    out: dict[str, dict[str, float]] = {}
    for commitment in lore:
        for constraint in commitment.constrains:
            if constraint.kind.value != "persona_trait":
                continue
            role, _, trait = constraint.target.partition("/")
            person_id = role_ids.get(role)
            if person_id is None or not trait:
                continue
            out.setdefault(person_id, {})[trait] = constraint.magnitude or 0.0
    return out


def generate(
    rng: Rng,
    minter: Minter,
    *,
    archetype,  # type: ignore[no-untyped-def]
    lore: tuple[LoreCommitment, ...] = (),
) -> Organisation:
    """Build the organisation for an archetype. Same seed, same graph, same IDs."""
    company_rng = rng.derive("company")
    company_id = minter.next("CO")
    units = archetype.units

    # Business units first, so unit leaders can be assigned as people are minted.
    unit_ids = {unit.key: minter.next("BU") for unit in units}

    # People. Per-unit roles are appended to the role table so the whole graph is
    # minted in one pass and every manager exists before its reports.
    role_table = list(_ROLES)
    for unit in units:
        role_table.append((f"{unit.key}_md", f"Managing Director, {unit.name}", "Executive", "ceo"))
        role_table.append((f"{unit.key}_bp", f"Finance Business Partner, {unit.name}", "Finance", "controller"))
        role_table.append((f"{unit.key}_buyer", f"Head of Buying, {unit.name}", "Merchandising", f"{unit.key}_md"))
    role_table.sort(key=lambda row: _depth(row[0], dict((r[0], r[3]) for r in role_table)))

    person_names = names.people_names(rng.derive("people"), len(role_table))
    role_ids: dict[str, str] = {}
    people: list[Employee] = []

    finance_cc = minter.next("CC")
    platform_cc = minter.next("CC")

    for (role, title, function, manager_role), person_name in zip(role_table, person_names):
        person_id = minter.next("PERSON")
        role_ids[role] = person_id
        business_unit = None
        if role.endswith(("_md", "_bp")):
            business_unit = unit_ids[role[:-3]]
        elif role.endswith("_buyer"):
            business_unit = unit_ids[role[:-6]]
        elif role.startswith("merch_"):
            business_unit = unit_ids[_merch_unit(unit_ids)]
        people.append(
            Employee(
                id=person_id,
                name=person_name,
                title=title,
                manager_id=None,  # filled below, once every role has an ID
                business_unit_id=business_unit,
                function=function,
                cost_centre_id=(
                    finance_cc if function in ("Finance", "Audit")
                    else platform_cc if title.endswith(("Engineer", "Data Platform"))
                    else None
                ),
                persona_id=(
                    _ROLE_PERSONA.get(role)
                    or _UNIT_ROLE_PERSONA.get(role[-3:])
                    or _UNIT_ROLE_PERSONA["buyer"]
                ),
            )
        )

    manager_of = {row[0]: row[3] for row in role_table}
    role_of_person = {pid: role for role, pid in role_ids.items()}
    people = [
        person.model_copy(
            update={"manager_id": role_ids.get(manager_of[role_of_person[person.id]] or "", None)}
        )
        for person in people
    ]

    business_units = tuple(
        BusinessUnit(
            id=unit_ids[unit.key],
            name=unit.name,
            company_id=company_id,
            leader_id=role_ids[f"{unit.key}_md"],
            kind=unit.kind,
        )
        for unit in units
    )

    dimensions = hierarchy.generate(
        rng.derive("hierarchy"), minter,
        units=units,
        unit_ids=unit_ids,
        buyers={unit.key: role_ids[f"{unit.key}_buyer"] for unit in units},
    )

    system_names = names.system_names(rng.derive("systems"))
    erp, mdm, platform, commerce, pos = (minter.next("SYS") for _ in range(5))
    systems = (
        System(id=erp, name=system_names["erp"], purpose="Group finance system of record",
               owner_id=role_ids["controller"], is_system_of_record_for=["general_ledger", "financial_reporting"]),
        System(id=mdm, name=system_names["mdm"], purpose="Master data for products, categories, and the product hierarchy",
               owner_id=role_ids["merch_lead"], is_system_of_record_for=["product_hierarchy", "range_architecture"]),
        System(id=platform, name=system_names["platform"], purpose="Analytical data platform and reporting pipelines",
               owner_id=role_ids["platform_lead"], is_system_of_record_for=["inventory_valuation"]),
        System(id=commerce, name=system_names["commerce"], purpose="Online storefront, basket, and checkout",
               owner_id=role_ids["platform_engineer"], is_system_of_record_for=["online_orders"]),
        System(id=pos, name=system_names["pos"], purpose="In-store point of sale and transaction capture",
               owner_id=role_ids[f"{next(iter(unit_ids))}_md"], is_system_of_record_for=["store_transactions"]),
    )

    # Not named `hierarchy`: that is the dimensions module imported above, and
    # shadowing it makes the earlier call to it fail with an unbound local.
    valuation, hierarchy_sync, orchestrator, checkout = (minter.next("SVC") for _ in range(4))
    services = (
        Service(id=valuation, name="inventory-valuation", purpose="Values on-hand stock nightly for financial reporting",
                owner_id=role_ids["platform_senior"], system_id=platform, criticality_tier=1,
                depends_on=[hierarchy_sync, platform]),
        Service(id=hierarchy_sync, name="product-hierarchy-sync",
                purpose="Publishes the product hierarchy from the merchandising master to the data platform",
                owner_id=role_ids["platform_engineer"], system_id=mdm, criticality_tier=2, depends_on=[mdm]),
        Service(id=orchestrator, name="month-end-close-orchestrator",
                purpose="Sequences the month-end close jobs and gates the ledger lock",
                owner_id=role_ids["platform_senior"], system_id=erp, criticality_tier=1,
                depends_on=[valuation, erp]),
        Service(id=checkout, name="checkout-api", purpose="Handles online basket and checkout requests",
                owner_id=role_ids["platform_engineer"], system_id=commerce, criticality_tier=1, depends_on=[commerce]),
    )

    traits = _persona_traits(lore, role_ids)
    personas = tuple(
        Persona(
            id=persona_id,
            label=label,
            voice=voice,
            sentence_complexity=complexity,  # type: ignore[arg-type]
            technical_depth=depth,  # type: ignore[arg-type]
            optimism=optimism,
            risk_tolerance=risk,
            political_awareness=political,
            favourite_phrases=list(phrases),
            traits={},
        )
        for persona_id, label, voice, complexity, depth, optimism, risk, political, phrases in _PERSONAS
    )

    # Lore-driven traits attach to the person, not the shared persona, so one
    # defensive individual does not make every merchandiser defensive.
    people = tuple(
        person if person.id not in traits else person.model_copy(update={"traits": traits[person.id]})
        for person in people
    )

    cost_centres = (
        CostCentre(id=finance_cc, name="Finance Shared Services", owner_id=role_ids["controller"], business_unit_id=None),
        CostCentre(id=platform_cc, name="Data Platform Engineering", owner_id=role_ids["platform_lead"], business_unit_id=None),
    )

    policies = (
        AccessPolicy(id=minter.next("POLICY"), label="All staff"),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Finance and audit only",
            allow_functions=["Finance", "Audit"],
            allow_people=[role_ids["ceo"], role_ids["cio"]],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Executive committee only",
            allow_functions=["Executive"],
            allow_people=[role_ids["cfo"]],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Technology and service operations",
            allow_functions=["Technology", "ServiceOperations"],
            allow_people=[role_ids["cio"]],
        ),
    )

    company = Company(
        id=company_id,
        name=names.company_name(company_rng),
        industry=archetype.industry,
        headquarters=names.headquarters(company_rng.derive("hq")),
        fiscal_year_start_month=archetype.fiscal_year_start_month,
        currency=archetype.currency,
        currency_unit=archetype.currency_unit,
        employees_total=archetype.employees,
    )

    return Organisation(
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
        dimensions=dimensions,
        roles={
            **role_ids,
            **{f"unit_{unit.key}": unit_ids[unit.key] for unit in units},
            "sys_erp": erp,
            "sys_mdm": mdm,
            "sys_platform": platform,
            "sys_commerce": commerce,
            "sys_pos": pos,
            "svc_valuation": valuation,
            "svc_hierarchy": hierarchy_sync,
            "svc_orchestrator": orchestrator,
            "svc_checkout": checkout,
            "policy_all": policies[0].id,
            "policy_finance": policies[1].id,
            "policy_exec": policies[2].id,
            "policy_tech": policies[3].id,
            "cc_finance": finance_cc,
            "cc_platform": platform_cc,
        },
    )


def unit_shares(archetype) -> dict[str, float]:  # type: ignore[no-untyped-def]
    """Revenue share per unit key, used by the financial generator."""
    return {unit.key: unit.share for unit in archetype.units}


def _depth(role: str, managers: dict[str, str | None], seen: frozenset[str] = frozenset()) -> int:
    """Distance from the root, so people are minted parents-first."""
    if role in seen:
        raise ValueError(f"reporting cycle at {role}")
    manager = managers.get(role)
    return 0 if manager is None else 1 + _depth(manager, managers, seen | {role})
