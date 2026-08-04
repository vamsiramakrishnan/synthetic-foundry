"""The insurer organisation generator.

The third vertical's own organisation module, for the same reason
``banking_org.py`` is not a parameterisation of ``organisation.generate``:
byte identity. The minting *mechanism* — depth-sorted roles, per-role join
streams, manager wiring, unit formation, founding milestones — is
``org_builder``, shared unchanged since the second vertical. What stays here
is insurer content: a role table shaped like an insurer's three actors
(actuarial, finance, claims), the personas each writes with, the systems an
insurer runs, and the access policies its reserving papers are read under.

What this shape adds that neither retail's nor banking's could express: the
appointed actuary reports to the CEO, not the CFO. Actuarial independence is
the whole reason the central estimate and the booked reserve are allowed to
disagree forever — a chief actuary who reported to the CFO would make "the
actuary said X, finance booked Y" read as one function overruling itself
rather than two authorities that are structurally allowed to differ.
"""

from __future__ import annotations

from collections.abc import Sequence

from dataclasses import dataclass
from typing import Any

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
from ..parameters import DEFAULT, Parameters
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
class InsurerOrganisation:
    """Everything the insurer organisation generator produces."""

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


#: The published role keys the reserving episode needs, plus the roles that
#: exist to make the org chart wiring coherent. ``chief_actuary`` reports to
#: the CEO — not the CFO — the same independent-reporting-line shape banking's
#: CRO carries, and for the same reason: the central estimate has to be able
#: to disagree with the booked reserve without that reading as insubordination.
_ROLES: tuple[tuple[str, str, str, str | None], ...] = (
    ("ceo", "Group Chief Executive Officer", "Executive", None),
    ("cfo", "Group Chief Financial Officer", "Finance", "ceo"),
    ("chief_actuary", "Chief Actuary", "Actuarial", "ceo"),                 # independent of the CFO
    ("financial_controller", "Group Financial Controller", "Finance", "cfo"),
    ("reserving_actuary", "Reserving Actuary", "Actuarial", "chief_actuary"),
    ("claims_director", "Claims Director", "Claims", "ceo"),
    ("audit", "Chief Internal Auditor", "Audit", "ceo"),
)

_PERSONAS: tuple[tuple[str, str, str, str, str, float, float, float, tuple[str, ...]], ...] = (
    ("PERSONA-INS-EXEC", "Executive", "brief, confident, outcome-focused", "low", "low", 0.3, 0.1, 0.9,
     ("well capitalised", "within appetite")),
    ("PERSONA-INS-CFO", "Group CFO", "measured, numeric, protective of the combined ratio", "medium", "low", -0.1, -0.3, 0.8,
     ("on a normalised basis", "within the combined-ratio target")),
    ("PERSONA-CHIEF-ACTUARY", "Chief Actuary", "formal, insistent on the full central estimate", "high", "high", -0.2, -0.6, 0.3,
     ("the central estimate", "on an undiscounted basis")),
    ("PERSONA-RESERVING-ACTUARY", "Reserving actuary", "precise, methodology-first, cautious", "high", "high", -0.2, -0.5, 0.2,
     ("actual versus expected", "development pattern")),
    ("PERSONA-CLAIMS", "Claims director", "operational, case-level, terse", "medium", "medium", 0.0, 0.0, 0.2,
     ("case reserve", "claims closed")),
    ("PERSONA-INS-CONTROLLER", "Group Financial Controller", "precise, procedural, deadline-driven", "high", "low", -0.2, -0.4, 0.4,
     ("as booked", "per policy")),
    ("PERSONA-INS-AUDIT", "Internal audit", "formal, control-oriented, conclusive", "high", "low", -0.3, -0.8, 0.5,
     ("control objective", "we uphold the finding")),
)

_ROLE_PERSONA = {
    "ceo": "PERSONA-INS-EXEC",
    "cfo": "PERSONA-INS-CFO",
    "chief_actuary": "PERSONA-CHIEF-ACTUARY",
    "financial_controller": "PERSONA-INS-CONTROLLER",
    "reserving_actuary": "PERSONA-RESERVING-ACTUARY",
    "claims_director": "PERSONA-CLAIMS",
    "audit": "PERSONA-INS-AUDIT",
}

#: Name pools for what a general insurer runs. Module-owned, like the role
#: table — see ``banking_org``'s identical comment for why these do not move
#: to ``generators/names.py``.
_INSURER_SUFFIX = ("Insurance Group", "General Insurance", "Assurance", "Mutual Insurance")
_POLICY_ADMIN = ("PolicyCore", "Underwrite Direct", "Coverline Admin")
_CLAIMS = ("ClaimsFirst", "Resolve Claims Platform", "Claimsline")
_ACTUARIAL = ("Reserving Workbench", "ActuarialSuite", "Provision Analytics")
_GENERAL_LEDGER = ("Ledgerbase", "Meridian General Ledger", "Groupledger")
_REINSURANCE = ("Cession Register", "Treaty Ledger", "Reinsurance Central")


def generate(
    rng: Rng,
    minter: Minter,
    *,
    archetype,  # type: ignore[no-untyped-def]
    lore: tuple[LoreCommitment, ...] = (),
    company_name: str | None = None,
    system_brands: dict[str, str] | None = None,
    voices: dict[str, Any] | None = None,
    # This module's own `_ROLES`, replaced. `None` means use them, so an
    # unpassed table is byte-identical to before this argument existed.
    #
    # A supplied table still has the per-unit roles appended below — those are
    # derived from the archetype's units rather than authored — and must have
    # gone through `roles.review` first. Several of these keys are looked up by
    # name in generator code, and a table missing one raises `KeyError`
    # part-way through an episode rather than building a different company.
    role_table: Sequence[tuple[str, str, str, str | None]] | None = None,
    physics: Parameters = DEFAULT,
) -> InsurerOrganisation:
    """Build the insurer for an archetype. Same seed, same graph, same ids.

    ``company_name``, ``system_brands`` and ``voices`` are the pack override
    trio — see ``organisation.generate``.
    """
    company_rng = rng.derive("company")
    brands = system_brands or {}
    company_id = minter.next("CO")
    units = archetype.units
    unit_ids = {unit.key: minter.next("BU") for unit in units}

    role_table = list(_ROLES if role_table is None else role_table)
    for unit in units:
        role_table.append((f"{unit.key}_md", f"Managing Director, {unit.name}", "Executive", "ceo"))
    role_table, depth_of = sorted_roles(role_table)

    finance_cc = minter.next("CC")
    actuarial_cc = minter.next("CC")

    pack_voice_ids = {
        role: f"PERSONA-PACK-{role.upper().replace('_', '-')}"
        for role in (voices or {})
    }

    def assign(role: str, title: str, function: str):  # type: ignore[no-untyped-def]
        """One decision per person: MDs sit in their unit; cost centres split
        finance-side from actuarial-and-claims; personas come from the role
        table."""
        business_unit = None
        if role.endswith("_md"):
            business_unit = unit_ids[role[:-3]]
        cost_centre = (
            finance_cc if function in ("Finance", "Audit")
            else actuarial_cc if function in ("Actuarial", "Claims")
            else None
        )
        persona = pack_voice_ids.get(role) or _ROLE_PERSONA.get(role, "PERSONA-INS-EXEC")
        return business_unit, cost_centre, persona

    role_ids, people = mint_people(
        rng, minter, role_table, depth_of, assign=assign, physics=physics
    )
    people = wire_managers(people, role_table, role_ids)
    business_units = form_units(units, unit_ids, role_ids, people, company_id, lore)

    # Lines of business through the shared dimension machinery. `buyers` is
    # empty for the same reason banking's is: a book's accountable executive
    # is a role (chief_actuary, claims_director), not a retail buyer, and the
    # misfit is recorded in ``worldloom.insurance``'s docstring.
    dimensions = hierarchy.generate(
        rng.derive("hierarchy"), minter,
        units=units,
        unit_ids=unit_ids,
        buyers={},
        physics=physics,
    )

    policy_admin = minter.next("SYS")
    claims = minter.next("SYS")
    actuarial = minter.next("SYS")
    general_ledger = minter.next("SYS")
    reinsurance = minter.next("SYS")
    systems = (
        System(id=policy_admin,
               name=brands.get("policy_admin") or company_rng.derive("policy_admin").choice(_POLICY_ADMIN),
               purpose="Policy administration: quotes, binds, and renews cover",
               owner_id=role_ids["financial_controller"],
               is_system_of_record_for=["policies"]),
        System(id=claims,
               name=brands.get("claims") or company_rng.derive("claims").choice(_CLAIMS),
               purpose="Claims management: notification through to settlement",
               owner_id=role_ids["claims_director"],
               is_system_of_record_for=["claims_paid", "claims_incurred"]),
        System(id=actuarial,
               name=brands.get("actuarial") or company_rng.derive("actuarial").choice(_ACTUARIAL),
               purpose="Actuarial reserving platform: cohort triangles and estimates",
               owner_id=role_ids["chief_actuary"],
               is_system_of_record_for=["reserve_estimates"]),
        System(id=general_ledger,
               name=brands.get("general_ledger") or company_rng.derive("gl").choice(_GENERAL_LEDGER),
               purpose="General ledger: booked reserves and the close",
               owner_id=role_ids["financial_controller"],
               is_system_of_record_for=["general_ledger", "financial_reporting"]),
        System(id=reinsurance,
               name=brands.get("reinsurance") or company_rng.derive("reinsurance").choice(_REINSURANCE),
               purpose="Reinsurance register: treaties and cessions",
               owner_id=role_ids["claims_director"],
               is_system_of_record_for=["reinsurance_treaties"]),
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
                continue
            base = by_id[_ROLE_PERSONA.get(role, "PERSONA-INS-EXEC")]
            clones.append(base.model_copy(update={
                "id": pack_voice_ids[role],
                "label": f"{base.label} ({role})",
                "voice": spec.voice or base.voice,
                "favourite_phrases": list(spec.phrases) or list(base.favourite_phrases),
            }))
        personas += tuple(clones)
    people = apply_traits(people, lore, role_ids)

    cost_centres = (
        CostCentre(id=finance_cc, name="Finance Shared Services",
                   owner_id=role_ids["financial_controller"], business_unit_id=None),
        CostCentre(id=actuarial_cc, name="Actuarial and Claims",
                   owner_id=role_ids["chief_actuary"], business_unit_id=None),
    )

    policies = (
        AccessPolicy(id=minter.next("POLICY"), label="All staff"),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Claims and actuarial",
            allow_functions=["Claims", "Actuarial", "Finance"],
            allow_people=[role_ids["ceo"]],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Finance and actuarial",
            allow_functions=["Finance", "Actuarial", "Audit"],
            allow_people=[role_ids["ceo"]],
        ),
        AccessPolicy(
            id=minter.next("POLICY"),
            label="Reserving committee",
            allow_functions=["Executive", "Finance", "Actuarial", "Claims", "Audit"],
        ),
    )

    generated_name = f"{company_rng.choice(names.COMPANY_FIRST)} {company_rng.choice(_INSURER_SUFFIX)}"
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
    # scoped to it — the role handle the reserving episode refuses to run
    # without. The stock archetype's long-tail book is named by role; a pack
    # that names its books differently gets the heaviest long-tail-shaped book
    # by group weight, deterministically, mirroring `banking_org`'s fallback.
    lt_book = next(
        (c.id for c in dimensions.categories if c.name == "Public and Products Liability"), None
    )
    if lt_book is None and dimensions.categories:
        unit_share = {unit_ids[unit.key]: unit.share for unit in units}
        lt_book = max(
            dimensions.categories,
            key=lambda c: (unit_share.get(c.business_unit_id, 0.0) * c.revenue_share, c.id),
        ).id

    return InsurerOrganisation(
        company=company,
        business_units=business_units,
        people=tuple(people),
        systems=systems,
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
            "sys_policy_admin": policy_admin,
            "sys_claims": claims,
            "sys_actuarial": actuarial,
            "sys_general_ledger": general_ledger,
            "sys_reinsurance": reinsurance,
            **({"cat_lt_liability": lt_book} if lt_book else {}),
            "policy_all": policies[0].id,
            "policy_claims_actuarial": policies[1].id,
            "policy_finance_actuarial": policies[2].id,
            "policy_committee": policies[3].id,
            "cc_finance": finance_cc,
            "cc_actuarial": actuarial_cc,
        },
    )
