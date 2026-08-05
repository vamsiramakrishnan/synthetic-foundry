"""The retail organisation generator.

Builds the entity graph: company, business units, people, systems, services, cost
centres, personas, access policies. Deterministic throughout — the model proposes
*shape* in later steps, but the graph itself is built and validated here, because
referential integrity and acyclicity are correctness concerns.

The minting mechanism — depth-sorted roles, per-role join-date streams, manager
wiring, unit formation, founding milestones — lives in ``org_builder``, shared
with the banking generator since the second vertical proved which parts repeat.
What stays here is retail content: the role table, the personas, the systems a
retailer runs, and the policies its documents are read under.

Lore reaches this generator through two constraint kinds: ``org_shape`` adjusts
topology, and ``persona_trait`` adjusts how specific people write.
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
    Category,
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
    accountability_facts,
    form_units,
    founding_milestones,
    mint_people,
    sorted_roles,
    wire_managers,
)


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
    milestones: tuple[EnterpriseEvent, ...]
    """One event per dated lore commitment, so the corpus's own timeline carries
    the assertions its lore makes. See ``founding_facts`` for the paired fact —
    kept as two fields rather than one combined type because callers already
    consume events and facts as two separate streams (``World._events`` and
    ``World._facts``), and a combined type would just be unzipped again at every
    call site."""
    founding_facts: tuple[CanonicalFact, ...]
    """The fact half of each founding milestone. Same length and order as
    ``milestones``; ``founding_facts[i].event_id == milestones[i].id``."""


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

#: Which persona each role writes with. Exhaustive over ``_ROLES`` — a role
#: missing from here used to be indistinguishable from one deliberately left to
#: a default, so ``tests/test_personas.py`` asserts the coverage rather than
#: trusting it.
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

#: The per-unit roles ``generate`` appends (``roles.UNIT_ROLES``), by suffix.
#: ``_buyer`` is named here now; it used to be reached through the catch-all
#: default below, which is exactly what disguised that default as load-bearing
#: when it was an accident.
_UNIT_ROLE_PERSONA = {"_md": "PERSONA-EXEC", "_bp": "PERSONA-FIN-BP", "_buyer": "PERSONA-MERCH-LEAD"}

#: By function, for a role neither table above names — which means an authored
#: table (``roles.from_shape`` invents ``role_017``), since the engine's own is
#: covered. ``roles.review`` already tells whoever wrote that table that a
#: role's function is what decides "cost centre and persona"; until this
#: existed it decided only the cost centre.
_FUNCTION_PERSONA = {
    "Executive": "PERSONA-EXEC",
    "Finance": "PERSONA-FIN-BP",
    "Audit": "PERSONA-AUDIT",
    "Technology": "PERSONA-ENG-PLATFORM",
    "ServiceOperations": "PERSONA-SVC-OPS",
    "Merchandising": "PERSONA-MERCH",
}

#: Last resort: an authored role in a function this engine has never heard of.
#: Named, and the same choice banking and insurance already made — a role with
#: no other claim on a register writes as general management.
_DEFAULT_PERSONA = "PERSONA-EXEC"


def _persona_for(role: str, function: str = "") -> str:
    """The persona a role writes with — one lookup, used both to assign people
    and to base a pack's voice override on.

    Four layers, narrowing to widest, and the widest is the one that was wrong.
    This used to end at ``_UNIT_ROLE_PERSONA["buyer"]``, so every role the key
    and suffix layers missed wrote in a supermarket merchandising leader's
    register: an authored ``chief_actuary`` on this engine included, and every
    ``role_017`` a synthesised organisation contains.

    Not an error instead, though a missing mapping reads like one. The engine's
    own table is covered exhaustively and a test holds it that way, which
    catches a gap before it ships rather than after; and a table from
    ``roles.from_shape`` legitimately invents keys and functions this module has
    never seen, so refusing them would make the authorable organisation
    unbuildable — the one thing ``roles`` exists to allow.
    """
    if role in _ROLE_PERSONA:
        return _ROLE_PERSONA[role]
    for suffix, persona in _UNIT_ROLE_PERSONA.items():
        if role.endswith(suffix):
            return persona
    return _FUNCTION_PERSONA.get(function, _DEFAULT_PERSONA)


def _check_persona_ids(voiced: dict[str, Any], minted: dict[str, str]) -> None:
    """Refuse a pack ``persona`` naming an id this world does not have.

    A dangling id would otherwise leave the role on its default, which is
    discovered as a register reading slightly wrong three thousand lines of
    prose later — the same silent-miss shape as the fallthrough above, and the
    reason this refuses where an unknown *role* key is merely skipped: a role
    the engine does not have is a pack over-specifying, while a persona id
    nothing answers to is a reference that goes nowhere.
    """
    engine = frozenset(persona[0] for persona in _PERSONAS)
    for role, spec in voiced.items():
        if not spec.persona:
            continue
        # A clone inherits its numeric temperament from its base and a pack may
        # not author that (see `packs.PackVoice`), so a clone's base is always
        # an engine persona — which also makes a chain of clones
        # unrepresentable rather than merely discouraged.
        allowed = engine if role in minted else engine | frozenset(minted.values())
        if spec.persona not in allowed:
            raise ValueError(
                f"voices[{role!r}].persona names {spec.persona!r}, which is not a"
                f" persona this world has: {', '.join(sorted(allowed))}"
            )


def _merch_unit(unit_ids: dict[str, str]) -> str:
    """Which unit merchandising systems sits under.

    General merchandise when there is one, since that is where range architecture
    is fought over; otherwise the first unit.
    """
    return "gm" if "gm" in unit_ids else next(iter(unit_ids))


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
    # Where this company is. Everything below it in this signature is a *narrower*
    # claim about the same subject — `headquarters` names the one city,
    # `regions` names this estate's labels, `name_pools` names these people —
    # and each therefore wins over the locale where the two overlap. Defaulted
    # to Australia, which is what every world built before `locales` existed
    # was made of, so an un-passed locale is byte-identical rather than close.
    locale: Locale = DEFAULT_LOCALE,
    estate_profile: str | None = None,
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
) -> Organisation:
    """Build the organisation for an archetype. Same seed, same graph, same IDs.

    ``company_name`` lets a pack name its own fiction; ``system_brands``
    re-brands system slots (keys per ``names.system_names``); ``voices`` maps
    role keys to voice overrides (``packs.PackVoice``-shaped); ``name_pools``
    supplies ``given``/``family`` person-name pools (``packs.PackNamePools``-
    shaped); ``headquarters`` and ``regions`` are the pack's own narrower
    geography (a single string and a pool of region labels, respectively — see
    ``generators/hierarchy.REGIONS``); ``locale`` is the jurisdiction the rest
    of it falls back to. Every generated value is still drawn either way, so a
    pack that overrides any of them never reshuffles a single downstream draw
    relative to one that does not — and neither does a locale, which changes
    which pool each draw reads and never how many draws there are.
    """
    company_rng = rng.derive("company")
    company_id = minter.next("CO")
    units = archetype.units

    # Business units first, so unit leaders can be assigned as people are minted.
    unit_ids = {unit.key: minter.next("BU") for unit in units}

    # People. Per-unit roles are appended to the role table so the whole graph is
    # minted in one pass and every manager exists before its reports. The
    # merchandising lead's manager in `_ROLES` is written as "gm_md", which is
    # only a name for "the MD of whichever unit merchandising sits under" —
    # resolved here through `_merch_unit`, because an archetype without a "gm"
    # unit (the first insurer pack) otherwise leaves merch_lead managerless and
    # the org tree with two roots.
    merch_md = f"{_merch_unit(unit_ids)}_md"
    role_table = [
        (role, title, function, merch_md if manager == "gm_md" else manager)
        for role, title, function, manager in (_ROLES if role_table is None else role_table)
    ]
    for unit in units:
        role_table.append((f"{unit.key}_md", f"Managing Director, {unit.name}", "Executive", "ceo"))
        role_table.append((f"{unit.key}_bp", f"Finance Business Partner, {unit.name}", "Finance", "controller"))
        role_table.append((f"{unit.key}_buyer", f"Head of Buying, {unit.name}", "Merchandising", f"{unit.key}_md"))
    role_table, depth_of = sorted_roles(role_table)

    finance_cc = minter.next("CC")
    platform_cc = minter.next("CC")

    # A voiced role writes with a pack persona — a clone of its base, built
    # after the defaults below. The ids are derivable from the role alone,
    # which is what lets `assign` name them before the clones exist. A spec
    # that only remaps mints nothing: it points its role at a persona that
    # already exists, and a role writing in an existing register does not need
    # a second copy of it under a new id.
    #
    # Roles the table does not hold are dropped here rather than at the clone
    # loop, because such a role must not orphan a persona *or* be nameable as
    # another role's base.
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
        """Retail's one decision per person: unit by role-key convention, cost
        centre by function, persona by ``_persona_for`` — which reads the
        function too, so the pair are decided from the same fact."""
        business_unit = None
        if role.endswith(("_md", "_bp")):
            business_unit = unit_ids[role[:-3]]
        elif role.endswith("_buyer"):
            business_unit = unit_ids[role[:-6]]
        elif role.startswith("merch_"):
            business_unit = unit_ids[_merch_unit(unit_ids)]
        cost_centre = (
            finance_cc if function in ("Finance", "Audit")
            else platform_cc if title.endswith(("Engineer", "Data Platform"))
            else None
        )
        return business_unit, cost_centre, (
            pack_voice_ids.get(role)
            or persona_remap.get(role)
            or _persona_for(role, function)
        )

    pools = name_pools or {}
    role_ids, people = mint_people(
        rng, minter, role_table, depth_of, assign=assign,
        given=pools.get("given") or None, family=pools.get("family") or None,
        locale=locale,
        physics=physics,
    )
    people = wire_managers(people, role_table, role_ids)
    business_units = form_units(units, unit_ids, role_ids, people, company_id, lore)

    dimensions = hierarchy.generate(
        rng.derive("hierarchy"), minter,
        units=units,
        unit_ids=unit_ids,
        buyers={unit.key: role_ids[f"{unit.key}_buyer"] for unit in units},
        # Forwarded as-is, both of them. This used to read
        # `regions if regions else hierarchy.REGIONS`, which looked like a
        # harmless restatement of the callee's own default and was not: it
        # substituted the *module* default for the absent value, so a caller
        # who had chosen a locale got Australian state abbreviations printed
        # into every site name and no signal that its choice had been dropped.
        # `hierarchy.generate` resolves the pair itself — a pack's regions are
        # the narrower claim and win — and passing None is how it is told that
        # nobody made that narrower claim.
        regions=regions,
        locale=locale,
        physics=physics,
    )

    # Drawn first, then re-branded: a pack renames the products, never the
    # roles the systems play in the episode.
    system_names = {**names.system_names(rng.derive("systems")), **(system_brands or {})}
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

    # The estate, if one was asked for: everything the organisation runs that
    # the episode does not itself name. Appended after the core, never mixed
    # into it — see `generators/estate.py` on why the four services above are
    # untouchable.
    if estate_profile is not None:
        from . import estate as estate_module

        landscape = estate_module.generate(
            rng.derive("estate"), minter,
            profile=estate_profile,
            core_services=services,
            core_systems=systems,
            # Who may own a service. Engineering and platform roles only: a
            # merchandising buyer owning the event bus is the kind of detail
            # that makes a corpus read as generated.
            owner_ids=tuple(sorted(
                role_ids[key] for key in ("platform_lead", "platform_senior", "platform_engineer")
                if key in role_ids
            )) or (role_ids[next(iter(role_ids))],),
        )
        systems = (*systems, *landscape.systems)
        services = (*services, *landscape.services)

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
    # Pack voices: each voiced role gets a clone of its base persona with the
    # authored fields swapped — a clone per role rather than an edit of the
    # shared persona, so voicing the CFO never re-voices everyone who shares the
    # CFO's register. The base is the pack's if it named one and the role's own
    # default otherwise. Numeric temperament stays the engine's either way,
    # which is what makes an unnamed field mean "keep" rather than "clear".
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

    # Drawn before the override is applied — see the docstring: a pack naming
    # the company (or its headquarters) must not change what any other stream
    # draws.
    generated_name = names.company_name(company_rng, locale=locale)
    generated_hq = names.headquarters(company_rng.derive("hq"), locale=locale)
    company = Company(
        id=company_id,
        name=company_name or generated_name,
        industry=archetype.industry,
        headquarters=headquarters or generated_hq,
        fiscal_year_start_month=archetype.fiscal_year_start_month,
        currency=archetype.currency,
        currency_unit=archetype.currency_unit,
        employees_total=archetype.employees,
    )

    # Last of all: every entity above already has its id, so founding milestones
    # can only ever append to the "EV"/"MFACT" sequences, never disturb one that
    # names a person, unit, category, or site.
    milestones, founding_facts = founding_milestones(minter, lore, company_id)

    # Appended to the founding facts rather than given a field of their own:
    # they are canonical facts about people and every consumer already reads
    # `founding_facts` as "the facts this organisation carries before any
    # episode runs". Empty unless lore names an accountability, so no shipped
    # world mints one and every existing corpus is byte-identical.
    founding_facts = founding_facts + accountability_facts(minter, lore, role_ids)

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
        milestones=milestones,
        founding_facts=founding_facts,
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
