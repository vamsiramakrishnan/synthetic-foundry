"""The retail domain module.

Industry specifics live here, never in the core `World` model. When the IT-services
vertical lands at build-order step 7 it gets its own module, and only what both
require gets promoted to core — the second implementation determines the
architecture, the first only gives an opinion.

The lore here is hand-authored, which is the honest position at step 3: lore is a
generative concern, and there is no model in the loop yet. What *is* real is that
these commitments drive generation rather than decorate it — `event_likelihood`
changes whether the incident happens, `persona_trait` attaches to a person,
`artifact_density` changes what gets written. Step 8 replaces the constant with a
lore pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import archetypes
from .archetypes import AUSTRALIAN_GROCERY, OMNICHANNEL_RETAILER, Archetype
from .ids import Minter
from .models import ConstraintKind, LoreCommitment, LoreConstraint, LoreKind
from .parameters import DEFAULT, Parameters
from .rng import Rng
from .scenarios import MonthEndClose
from .world import World, extend_lore

#: Base probability of a data-quality incident during any given close, before
#: lore multipliers. Deliberately low: most closes are uneventful, and a corpus
#: where every period has a crisis is not a realistic one.
#:
#: Read from the registry rather than typed here. It is a public name and a
#: test asserts on it, so it stays — but two copies of a load-bearing
#: probability is one copy that can quietly stop being the one the engine
#: draws with, which is exactly the failure the registry exists to end.
BASE_INCIDENT_LIKELIHOOD = DEFAULT.probability("ops.incident.likelihood")

#: The lore-constraint targets this engine's generators actually consult, and
#: what each one changes. This is the pack author's contract: a commitment
#: aimed anywhere else is carried and cited but changes nothing, and
#: ``worldloom pack check`` says so by name. Kept beside the engine rather
#: than derived, and each entry names the code that reads it, so drift is a
#: review comment away from being caught.
CONSULTED_TARGETS: tuple[tuple[str, str], ...] = (
    ("<role_key>/<fact_kind>",
     "an accountability: mints the fact saying this role answers for that measure"
     " (org_builder.accountability_facts)"),
    ("data_quality_incident/inventory",
     "multiplies the close incident likelihood (scenarios.MonthEndClose.run)"),
    ("close_cycle_time",
     "tags the close calendar's events and facts (operations.generate)"),
    ("hierarchy_mapping_change",
     "tags the control-failure chain (operations._incident_chain)"),
    ("finance/status_reports",
     "raises artifact density: the knowledge article and per-unit commentary (planning)"),
    ("forecast_miss/<unit_key>",
     "tags a unit's revenue variance with why it misses (finance.generate)"),
    ("promotional_depth",
     "tags the margin-impact driver metric (finance._drivers)"),
    ("online_conversion_rate",
     "tags the conversion metrics, when a digital unit exists (finance._drivers)"),
)


def lore(minter: Minter) -> tuple[LoreCommitment, ...]:
    """The retail archetype's lore.

    Five commitments, each constraining at least one downstream decision — the
    schema will not accept one that constrains nothing. Constraint targets name
    *roles* rather than person IDs, because lore is authored before the graph
    exists and cannot know who will hold a job.
    """
    return (
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.DECISION,
            assertion=(
                "The product hierarchy was remapped for a new category structure. The mapping between "
                "the legacy and new hierarchy has been maintained manually ever since, rather than being "
                "migrated into the merchandising master."
            ),
            effective_from="2024-08",
            constrains=[
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="data_quality_incident/inventory",
                               effect="Manual mapping drifts from the master, so valuation failures recur",
                               magnitude=2.5),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY,
                               target="merchandising/runbooks",
                               effect="The manual step was never written down",
                               magnitude=-0.4),
                LoreConstraint(kind=ConstraintKind.TERMINOLOGY,
                               target="hierarchy_node",
                               effect="Legacy 'department' and new 'category' are both in use and not interchangeable"),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.CONSTRAINT,
            assertion=(
                "No team owns the legacy-to-new hierarchy mapping table. Merchandising believes the data "
                "platform owns it because it is consumed there; the data platform believes Merchandising "
                "owns it because it is master data."
            ),
            effective_from="2024-11",
            constrains=[
                LoreConstraint(kind=ConstraintKind.APPROVAL_CHAINS,
                               target="hierarchy_mapping_change",
                               effect="No required reviewer, because no owner is registered",
                               magnitude=0.0),
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                               target="merch_lead/defensive_about_ownership",
                               effect="Ownership questions are answered defensively in writing",
                               magnitude=0.3),
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="recurrence_after_remediation",
                               effect="Fixes address the symptom because no owner drives the control",
                               magnitude=1.8),
            ],
            visibility="tacit",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.NORM,
            assertion=(
                "Month-end close is expected to complete within four business days of period end. "
                "Overruns are escalated to the Group CFO the same day."
            ),
            effective_from="2022-01",
            constrains=[
                LoreConstraint(kind=ConstraintKind.METRIC_EMPHASIS, target="close_cycle_time",
                               effect="Close cycle time is a standing CFO metric", magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY, target="finance/status_reports",
                               effect="Status reporting increases sharply during close", magnitude=0.5),
                LoreConstraint(kind=ConstraintKind.RISK_APPETITE, target="finance/manual_workarounds",
                               effect="Manual workarounds are tolerated to protect the close date",
                               magnitude=0.6),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.EVENT,
            assertion=(
                "The checkout and loyalty stack was replatformed. Conversion has been volatile since, and "
                "forecasting for the online unit has not been re-baselined against post-replatform behaviour."
            ),
            effective_from="2025-09",
            constrains=[
                LoreConstraint(kind=ConstraintKind.METRIC_EMPHASIS, target="online_conversion_rate",
                               effect="Conversion is watched weekly by the Digital MD", magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD, target="forecast_miss/digital",
                               effect="Digital forecasts miss more often than other units", magnitude=1.6),
                LoreConstraint(kind=ConstraintKind.TECH_POSTURE, target="release_cadence",
                               effect="Change freezes are applied around peak trading", magnitude=-0.2),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.TENSION,
            assertion=(
                "General Merchandise defends margin performance by pointing to promotional depth agreed "
                "with Food for joint campaigns. Food regards those campaigns as General Merchandise's "
                "commercial choice."
            ),
            effective_from="2025-02",
            constrains=[
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT, target="gm_md/hedging",
                               effect="Margin commentary attributes cause outside the unit", magnitude=0.3),
                LoreConstraint(kind=ConstraintKind.METRIC_EMPHASIS, target="promotional_depth",
                               effect="Promotional depth is reported separately by unit", magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY, target="strategy/steering_papers",
                               effect="Joint campaign governance generates extra papers", magnitude=0.2),
            ],
            visibility="tacit",
        ),
    )


@dataclass(frozen=True)
class RetailWorld:
    """A retail archetype, built from a seed.

    Lazy: constructing one does no work. ``build()`` is the expensive call.

        world = RetailWorld(seed=8128).build()
        world = world.run(MonthEndClose(period="2026-03"))

    The archetype decides scale and shape — how many divisions, what they sell,
    how many stores. Everything in the world is generated from the seed; the
    archetype contributes no data of its own::

        world = RetailWorld.inspired_by("a large Australian grocer", seed=8128).build()
    """

    seed: int
    archetype: Archetype = OMNICHANNEL_RETAILER
    employees: int | None = None
    annual_revenue: int | None = None
    """Override the archetype's scale. ``None`` takes the archetype's own."""
    estate: str | None = None
    """Grow a service landscape around the episode's own services:
    ``"small"``, ``"medium"`` or ``"large"`` (``generators/estate.PROFILES``).
    ``None`` mints nothing, which is what keeps every corpus built before this
    existed byte-identical — the estate appends ids after the core's, and
    ``Minter`` counts per prefix, so no other entity moves either."""
    pack: Any = None
    """An industry ``Pack`` supplying the archetype, lore, and company name.
    Set via ``from_pack``; carried on the instance so ``build`` can embed it in
    the recipe, which is what makes a pack-built corpus rebuild itself."""
    seasonality: Any = None
    """The trading year (``worldloom.profiles``). ``None`` is the engine's own
    general-retail profile — a 21% December — which every world built before
    this field existed traded on, insurers included."""

    role_table: tuple[tuple[str, str, str, str | None], ...] | None = None
    """Who exists in this organisation (``worldloom.roles``).

    ``None`` is the engine's own table, which is what every world built before
    this field existed used. A supplied one must have passed ``roles.check``:
    several of its keys are looked up by name in generator code, and a table
    missing one raises ``KeyError`` part-way through an episode rather than
    building a different company.

    Carried on the recipe as a whole table rather than as the shape it came
    from, for the reason the pack is embedded whole: a corpus that could only
    be rebuilt by whoever still had the probe that derived it would fail the
    reason recipes exist."""

    physics: Parameters = DEFAULT
    """The world physics the organisation is generated under
    (``worldloom.parameters``). The engine's own by default, which is what an
    un-overridden build has always used."""

    lore_claims: tuple[Any, ...] = ()
    """Lore a set of facet claims commits this company to
    (``facets.LoreClaim``), appended to whatever lore this build already has.

    Claims and not commitments: a facet knows what it asserts and what kind of
    commitment that is, but not which world it lands in, so it cannot mint an id
    or pick an effective date. ``world.extend_lore`` supplies both, and its
    docstring argues why the seam is here rather than on a pack.

    ``()`` appends nothing and mints nothing, which is what keeps every corpus
    built before this existed byte-identical — the same guarantee ``estate``
    above makes, and for the same structural reason."""

    locale: Any = None
    """Where this company is (``worldloom.locales``): a registry name or a
    ``Locale``.

    ``None`` is ``locales.DEFAULT`` — Australia, which is what every world built
    before this field existed *was*, so an un-set locale is byte-identical
    rather than close.

    **Why it is a build field and not only a recipe key.** A locale decides two
    halves. The *render* half — the digit grammar — is read back off the recipe
    at render time and needs nothing here. The *build* half is what this field
    is for: the region labels printed into every site name, the pools the
    people are drawn from, the city the headquarters is in, the second word of
    the company's name, and (through ``Locale.applied_to``) the currency every
    money fact is denominated in and the month its financial year opens. All of
    those are decided inside ``organisation.generate``, so a locale that arrives
    after ``build()`` arrives too late — the same argument ``lore_claims`` above
    makes about lore being an input, and the same failure if it is ignored: a
    corpus that is entirely plausible and quietly not the one that was asked
    for.

    A name or a ``Locale``, and ``build`` records *what it was given* on the
    recipe rather than what it resolved to — see ``recipe._locale_document``. A
    corpus that said ``"germany"`` must rebuild still saying it, not carrying a
    frozen copy of what the registry said about Germany that day.

    A pack's own ``regions``, ``name_pools`` and ``headquarters`` still win
    where they overlap, and an authored archetype keeps its currency and
    financial year: a pack is a claim about *this company*, a locale about the
    country it is in."""

    policies: str | None = None
    """Standing documents (``worldloom.policies``): ``"core"`` or ``"full"``.

    The paperwork a company *has* rather than produces — an expense policy, a
    delegation of authority, a leave policy — as opposed to the episodic
    documents a close or an incident emits. ``None`` mints nothing, which is
    what keeps every corpus built before the knob existed byte-identical, the
    same guarantee ``estate`` and ``master_data`` make. The recipe records the
    level, never the documents, so a replay re-runs the same construction."""

    master_data: Any = None
    """Reference tables at scale (``generators/masterdata.py``): a mapping of
    ``vendors``/``customers``/``skus`` to row counts, e.g.
    ``{"vendors": 2000}``. ``None`` mints nothing and writes nothing, which is
    what keeps every corpus built before the knob existed byte-identical —
    the same guarantee ``estate`` makes, by the same mechanism (a stream of
    its own under the world seed, a corpus file written only when populated).
    The recipe records the counts, never the rows, so a replay re-runs the
    same construction — ``lore_claims``' posture."""

    @classmethod
    def inspired_by(cls, description: str, *, seed: int,
                    physics: Parameters = DEFAULT) -> RetailWorld:
        """A world shaped like the business *description* names.

        Shape only: unit mix, margin structure, store count, category depth. No
        figure, name, or fact about the described company is looked up or used —
        the point is a corpus that behaves like that *kind* of business while
        being wholly invented.
        """
        return cls(seed=seed, archetype=archetypes.inspired_by(description), physics=physics)

    @classmethod
    def from_pack(cls, pack: Any, *, seed: int,
                  physics: Parameters = DEFAULT) -> RetailWorld:
        """A world whose shape, lore, and name a pack authored.

        The pack decides the texture; this engine keeps the physics. See
        ``worldloom.packs`` for what that boundary means and why.
        """
        from . import packs as packs_module

        return cls(seed=seed, archetype=packs_module.archetype_of(pack), pack=pack,
                   physics=physics,
                   # The pack's own trading year, or None for the engine's. This
                   # is the line that stops a pack-authored insurer trading like
                   # a supermarket.
                   seasonality=packs_module.seasonality_of(pack))

    def build(self) -> World:
        """Generate the organisation, its lore, and the lore's founding milestones.

        Every dated lore commitment arrives with a matching event and fact
        already on the timeline — the world's beginning, not yet any close.
        """
        from . import __version__ as worldloom_version
        from . import locales as locales_module
        from . import recipe as recipe_module
        from .generators import organisation

        rng = Rng(self.seed)
        minter = Minter()

        # Resolved before anything is minted, and refused here if it does not
        # resolve — `locales.named` refuses an unknown name for the reason that
        # applies with most force at this exact line: a build that fell back to
        # Australia's pools would produce a Frankfurt company whose people are
        # called Rafferty, whose sites are in NSW and whose every figure is
        # plausible, with nothing in the corpus to notice the drop by.
        locale = locales_module.resolve(self.locale)
        # The archetype's own two jurisdiction-decided fields, rebound. Applied
        # to the local name and not to `self.archetype`, so the spec a caller
        # holds is unchanged and `World._archetype` below carries the archetype
        # the world was actually built at — the currency every money fact is
        # stated in comes off it, in this module and again in `MonthEndClose`.
        archetype = locale.applied_to(self.archetype)

        if self.pack is not None:
            from . import packs as packs_module

            commitments = packs_module.lore_of(self.pack, minter)
        else:
            commitments = lore(minter)
        # Before `generate`, not after: lore is an *input* to the organisation —
        # it dates the business units, attaches persona traits, and decides
        # artifact density. Commitments minted afterwards would be carried and
        # inert, which is the failure this seam exists to end rather than move.
        recipe = recipe_module.build_recipe(
            archetype=self.archetype.key,
            seed=self.seed,
            employees=self.employees,
            annual_revenue=self.annual_revenue,
            pack=self.pack,
            estate=self.estate,
            physics=self.physics,
            role_table=self.role_table,
            seasonality=self.seasonality,
            # `self.locale`, not the resolved `locale`: the recipe stores what
            # it was given. A corpus built as "germany" replays as "germany" and
            # picks up any correction the registry later makes; storing the
            # resolved dict would freeze a copy of the registry into it.
            locale=self.locale,
            master_data=self.master_data,
            policies=self.policies,
        )
        commitments, recipe = extend_lore(commitments, self.lore_claims, minter, recipe)
        org = organisation.generate(
            rng.derive("organisation"), minter,
            archetype=archetype, lore=commitments,
            company_name=self.pack.company_name if self.pack is not None else None,
            system_brands=dict(self.pack.system_brands) if self.pack is not None else None,
            voices=dict(self.pack.voices) if self.pack is not None else None,
            estate_profile=self.estate,
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


# Retail owns its archetypes in the domain registry, like every vertical. No
# single_episode: the close loop's flags (periods, incident, comparatives,
# actors) are retail's own, and the CLI drives them directly rather than
# flattening them into the shared interface.
# This vertical's other physics, declared beside the generator that draws them
# and registered here — `parameters.register`'s seam, used exactly as
# `banking.py` uses it for `banking_network.SPANS`. Registered at import so the
# ranges exist before any world is built: a span that appeared only when some
# module happened to have been imported would make a corpus's figures depend on
# import order, which is a determinism bug wearing a plugin's clothes.
from . import parameters as _parameters_module
from .domains import Domain, register_domain
from .generators.retail_estate import SPANS as _RETAIL_ESTATE_SPANS

_parameters_module.register(_RETAIL_ESTATE_SPANS)

from .generators.evaluation import EVAL_TEXT as _RETAIL_EVAL_TEXT
from .generators.operations import TEXT as _RETAIL_TEXT
from .generators.organisation import _ROLES as _RETAIL_ROLES

register_domain(Domain(
    name="retail",
    archetype_keys=frozenset({AUSTRALIAN_GROCERY.key, OMNICHANNEL_RETAILER.key}),
    default_archetype="omnichannel_retailer",
    world=RetailWorld,
    consulted_targets=CONSULTED_TARGETS,
    system_slots=(
        ("erp", "group finance system of record"),
        ("mdm", "master data: products, categories, the hierarchy the incident corrupts"),
        ("platform", "analytical data platform running the valuation pipeline"),
        ("commerce", "online storefront and checkout"),
        ("pos", "in-store point of sale"),
    ),
    role_keys=tuple(row[0] for row in _RETAIL_ROLES),
    unit_role_suffixes=("_md", "_bp", "_buyer"),
    episode_text=tuple(_RETAIL_TEXT.items()),
    evaluation_text=tuple(_RETAIL_EVAL_TEXT.items()),
))

# The fact kinds this vertical answers for, in the process-global registry
# (`worldloom.factkinds`) — the fifth registration seam, and the one
# `lob.lint_responsibilities` and the episode grammar's lint consult. Retail
# registers the shared vocabularies too: `close.*` and the incident-chain
# `ops.*` kinds are minted verbatim by banking's and procurement's episodes
# ("reuses retail's close.* kinds verbatim" — `generators/regulatory.py`), and
# a kind has *one* declaration whoever's episode mints it — the other verticals
# register only what is theirs alone.
from .factkinds import FactKind
from .factkinds import register as _register_kinds

_register_kinds([
    FactKind(kind="close.due_date", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at",), about="The committed close date for the period."),
    FactKind(kind="close.revised_date", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at",), about="The moved close date, when an incident moves it."),
    FactKind(kind="close.status", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at", "supersedes-prior"),
             about="Where the close stands; a delayed status is superseded, never edited."),
    FactKind(kind="close.delay", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at",), about="Business days the close slipped."),
    FactKind(kind="financial.revenue.actual", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at", "sums-to(financial.revenue.actual)"),
             about="Actual revenue; child subjects sum to their parent's figure exactly."),
    FactKind(kind="financial.revenue.budget", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at", "sums-to(financial.revenue.budget)"),
             about="Budgeted revenue, rolled up the same way."),
    FactKind(kind="financial.revenue.variance", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at", "reconciles-against(financial.revenue.actual, financial.revenue.budget)"),
             about="Actual less budget, exactly — validate.financial() recomputes it."),
    FactKind(kind="financial.gross_profit.actual", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at", "sums-to(financial.gross_profit.actual)"),
             about="Actual gross profit."),
    FactKind(kind="financial.gross_profit.budget", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at", "sums-to(financial.gross_profit.budget)"),
             about="Budgeted gross profit."),
    FactKind(kind="financial.gross_profit.variance", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at", "reconciles-against(financial.gross_profit.actual, financial.gross_profit.budget)"),
             about="Actual less budget on gross profit."),
    FactKind(kind="financial.gross_margin_pct.actual", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at", "reconciles-against(financial.gross_profit.actual, financial.revenue.actual)"),
             about="The stated margin, derived from the amounts beside it."),
    FactKind(kind="financial.gross_margin_pct.budget", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at", "reconciles-against(financial.gross_profit.budget, financial.revenue.budget)"),
             about="The budgeted margin, same derivation."),
    FactKind(kind="financial.incident_pl_impact", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at",), about="The P&L cost the incident is assessed at."),
    FactKind(kind="metric.gross_margin_variance", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at",), about="Margin variance in points, for the memo."),
    FactKind(kind="metric.online_conversion_rate.actual", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at",), about="Online conversion as landed."),
    FactKind(kind="metric.online_conversion_rate.forecast", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at",), about="Online conversion as forecast."),
    FactKind(kind="metric.promotional_depth_margin_impact", domain="retail", generated_by="generators/finance.py",
             invariants=("holds-at",), about="What promotional depth took off margin."),
    # The incident chain. Shared vocabulary: banking's regulatory episode mints
    # most of these kinds too, against its own incident, under this declaration.
    FactKind(kind="ops.incident_opened", domain="retail",
             generated_by="generators/operations.py (reused by banking's regulatory.py)",
             invariants=("holds-at", "precedes-event"), about="The raised ticket."),
    FactKind(kind="ops.cause", domain="retail",
             generated_by="generators/operations.py (reused by banking's regulatory.py)",
             invariants=("holds-at", "supersedes-prior"),
             about="What broke. The confirmed cause supersedes the initial hypothesis;"
                   " the hypothesis stays on the record as a past belief."),
    FactKind(kind="ops.cause_ruled_out", domain="retail",
             generated_by="generators/operations.py (reused by banking's regulatory.py)",
             invariants=("holds-at",), about="The evidence that dismissed the hypothesis."),
    FactKind(kind="ops.feed_status", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at",), about="The failed feed's state."),
    FactKind(kind="ops.valuation_status", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at",), about="Whether inventory valuation completed."),
    FactKind(kind="ops.workaround", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at",), about="The applied workaround."),
    FactKind(kind="ops.mapping_table_owner", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at",), about="Who owns the mapping table — 'unassigned' is the finding."),
    FactKind(kind="ops.previous_similar_incident", domain="retail", generated_by="generators/operations.py",
             invariants=("holds-at",),
             about="The named earlier period a comparable failure occurred in."),
    FactKind(kind="ops.root_cause_classification", domain="retail",
             generated_by="generators/operations.py (reused by banking's regulatory.py)",
             invariants=("holds-at",), about="The audit classification of the failure."),
    FactKind(kind="ops.remediation", domain="retail",
             generated_by="generators/operations.py (reused by banking's regulatory.py)",
             invariants=("holds-at",), about="The tickets raised to fix it."),
    FactKind(kind="ops.remediation_addresses", domain="retail",
             generated_by="generators/operations.py (reused by banking's regulatory.py)",
             invariants=("holds-at",), about="Which remediation addresses the control failure."),
    FactKind(kind="ops.affected_records", domain="retail",
             generated_by="generators/operations.py (reused by banking's regulatory.py)",
             invariants=("holds-at",), about="The blast radius the ticket quotes."),
    # The corporate centre and the distribution network. Both blocks exist
    # because `validate.reachability` measured this vertical's own organisation
    # as decorative: two cost centres declared by every retail company and named
    # by no fact, and — on any archetype with warehouses — an estate of
    # zero-weight sites the store P&L correctly refuses turnover to and nothing
    # else said anything about. `generators/retail_estate.py` opens with the
    # counts.
    FactKind(kind="overhead.shared_services.cost", domain="retail",
             generated_by="generators/retail_estate.py",
             invariants=("holds-at", "sums-to(overhead.shared_services.cost)"),
             about="The corporate cost base, by the cost centre that incurs it;"
                   " the centres sum to the group figure exactly."),
    FactKind(kind="overhead.shared_services.recharge", domain="retail",
             generated_by="generators/retail_estate.py",
             invariants=("holds-at", "sums-to(overhead.shared_services.recharge)"),
             about="The same base, by the division it is recharged to. A second"
                   " decomposition of one figure over a different set of"
                   " entities, which is what makes either checkable."),
    FactKind(kind="overhead.shared_services.recovery_pct", domain="retail",
             generated_by="generators/retail_estate.py",
             invariants=("holds-at",
                         "reconciles-against(overhead.shared_services.recharge,"
                         " financial.revenue.actual)"),
             about="Recharge as a share of the subject's own revenue. A rate:"
                   " stated at every level it is read at and summed at none."),
    FactKind(kind="logistics.throughput", domain="retail",
             generated_by="generators/retail_estate.py",
             invariants=("holds-at", "sums-to(logistics.throughput)"),
             about="Cartons dispatched through a distribution centre. The"
                   " measure a site that sells nothing actually owns."),
    FactKind(kind="logistics.cost_to_serve", domain="retail",
             generated_by="generators/retail_estate.py",
             invariants=("holds-at", "sums-to(logistics.cost_to_serve)"),
             about="What moving that volume cost, by the centre that moved it."),
    FactKind(kind="logistics.cost_per_carton", domain="retail",
             generated_by="generators/retail_estate.py",
             invariants=("holds-at",
                         "reconciles-against(logistics.cost_to_serve,"
                         " logistics.throughput)"),
             about="Cost over volume at the level it is stated. A rate — the"
                   " network's figure is its own two amounts divided, never the"
                   " total of its centres' rates."),
])


# ---------------------------------------------------------------------------
# Retail's own check group
# ---------------------------------------------------------------------------


def _checks(world: World) -> tuple[list[Any], int]:
    """The roll-ups `validate.financial` structurally cannot perform.

    That check reads kinds beginning ``financial.`` and rolls them up through
    the reporting hierarchy — group ← units ← categories and stores. Neither of
    the two decompositions this module's generator adds fits that shape:

    * shared-services **cost** rolls up over *cost centres*, which are not in
      any reporting hierarchy at all — a cost centre is where a charge lands,
      not a cut of performance, which is why ``validate._KIND_LABELS`` maps it
      to no axis;
    * shared-services **recharge** and the two logistics measures roll up over
      units and sites, but ``financial.``-prefixed kinds are the only ones that
      check reads, and naming these ``financial.*`` to get inside it would put a
      figure with no budget and no variance into the machinery that derives
      both.

    So retail's own roll-up lives here, in retail's check group, exactly as
    banking's branch network lives in ``banking._checks`` and for the reason
    that function states.

    **Exact, with no tolerance, and that is the point.** ``retail_estate``
    allocates every one of these from a total drawn once, by largest remainder,
    so the parts sum to the whole *by construction*; any drift at all is a
    defect in the allocation rather than a rounding note.
    ``RECONCILIATION_TOLERANCE`` would absorb the difference and let a later
    slide back to round-and-hope pass — which is precisely how a workbook comes
    to disagree with the memo quoting it.
    """
    from .generators import retail_estate as _estate
    from .validate import Violation

    violations: list[Violation] = []
    checks = 0

    def fail(code: str, subject: str, detail: str) -> None:
        violations.append(Violation(
            group="retail", code=code, subject=subject, detail=detail))

    stated: dict[tuple[str, str | None], dict[str, float]] = {}
    for fact in world.facts:
        if fact.value is None or fact.is_superseded:
            continue
        if fact.kind not in _estate.ADDITIVE and fact.kind not in _estate.RATES:
            continue
        stated.setdefault((fact.kind, fact.period), {})[fact.subject] = fact.value.amount

    company_id = world.company.id
    unit_ids = [unit.id for unit in world.business_units]
    centre_ids = [centre.id for centre in world.cost_centres]

    # -- the corporate base, decomposed twice --------------------------------
    # The centres that *incur* the cost and the divisions that *carry* it are
    # different sets of entities summing to one number, so each is a check on
    # the other. Two independent decompositions of one total are a cross-check;
    # two independently drawn ones would be two contradictions — the argument
    # `finance.generate` makes for allocating a store estate rather than
    # drawing it.
    for (_kind, period), subjects in sorted(
        ((key, value) for key, value in stated.items()
         if key[0] == _estate.SHARED_COST),
        key=lambda item: item[0][1] or "",
    ):
        if company_id not in subjects:
            continue
        group = subjects[company_id]
        incurred = [subjects[c] for c in centre_ids if c in subjects]
        if incurred:
            checks += 1
            if sum(incurred) != group:
                fail("shared_services_does_not_reconcile", f"{period}/{company_id}",
                     f"cost centres sum to {sum(incurred):,.2f} but the group states"
                     f" {group:,.2f} (difference {sum(incurred) - group:,.2f})")
        recharge = stated.get((_estate.SHARED_RECHARGE, period), {})
        carried = [recharge[u] for u in unit_ids if u in recharge]
        if carried:
            checks += 1
            if sum(carried) != group:
                fail("shared_services_recharge_does_not_reconcile",
                     f"{period}/{company_id}",
                     f"divisions carry {sum(carried):,.2f} of a corporate base of"
                     f" {group:,.2f} — every dollar incurred is recharged to"
                     " somebody, so the two decompositions state one number")

    # -- the distribution network --------------------------------------------
    # Only over the divisions that *have* one: a company total derived from a
    # subset of divisions is `documents._sum_row`'s case, and asserting the
    # group against every unit would refuse a corpus whose digital division
    # ships from a third party.
    network_of = {
        unit.id: [s.id for s in _estate.distribution_estate(
            [s for s in world.sites if s.business_unit_id == unit.id])]
        for unit in world.business_units
    }
    for kind in (_estate.THROUGHPUT, _estate.COST_TO_SERVE):
        for (fact_kind, period), subjects in sorted(
            ((key, value) for key, value in stated.items() if key[0] == kind),
            key=lambda item: item[0][1] or "",
        ):
            for unit_id, estate in sorted(network_of.items()):
                if unit_id not in subjects or not estate:
                    continue
                parts = [subjects[s] for s in estate if s in subjects]
                if not parts:
                    continue
                checks += 1
                if sum(parts) != subjects[unit_id]:
                    fail("distribution_network_does_not_reconcile",
                         f"{fact_kind}/{period}/{unit_id}",
                         f"its centres sum to {sum(parts):,.2f} but the division"
                         f" states {subjects[unit_id]:,.2f}")
            if company_id not in subjects:
                continue
            divisions = [subjects[u] for u in unit_ids if u in subjects]
            if not divisions:
                continue
            checks += 1
            if sum(divisions) != subjects[company_id]:
                fail("distribution_network_does_not_reconcile",
                     f"{fact_kind}/{period}/{company_id}",
                     f"divisions sum to {sum(divisions):,.2f} but the network"
                     f" states {subjects[company_id]:,.2f}")

    # -- the two rates are their own amounts divided -------------------------
    # `banking._checks`' `loan_to_deposit_disagrees_with_balances`, twice. A
    # reader who divides the two columns on the sheet must get the number the
    # sheet states, and a rate carried down from its draw would not survive the
    # rounding the allocation already did.
    for rate_kind, numerator_kind, denominator_kind, scale in (
        (_estate.SHARED_RECOVERY, _estate.SHARED_RECHARGE,
         "financial.revenue.actual", 100.0),
        (_estate.COST_PER_CARTON, _estate.COST_TO_SERVE, _estate.THROUGHPUT, 1.0),
    ):
        # Overhead recovery divides by a `financial.` kind, which `stated` does
        # not hold — it is indexed over this module's own measures only, so the
        # denominator has to be gathered from the ledger. Gathered here rather
        # than folded into `stated` above so the roll-up loops keep reading a
        # dictionary that contains nothing but what this generator minted.
        denominators = stated
        if denominator_kind not in _estate.ADDITIVE:
            denominators = {}
            for fact in world.facts:
                if fact.kind != denominator_kind or fact.value is None or fact.is_superseded:
                    continue
                denominators.setdefault((denominator_kind, fact.period), {})[
                    fact.subject] = fact.value.amount
        for (_, period), subjects in sorted(
            ((key, value) for key, value in stated.items() if key[0] == rate_kind),
            key=lambda item: item[0][1] or "",
        ):
            top = stated.get((numerator_kind, period), {})
            bottom = denominators.get((denominator_kind, period), {})
            for subject, rate in sorted(subjects.items()):
                if subject not in top or not bottom.get(subject):
                    continue
                checks += 1
                derived = round(top[subject] * scale / bottom[subject], 2)
                if abs(derived - rate) > 0.01:
                    fail("rate_disagrees_with_its_amounts", f"{rate_kind}/{period}/{subject}",
                         f"states {rate:.2f} but {top[subject]:,.0f} /"
                         f" {bottom[subject]:,.0f} = {derived:.2f}")

    return violations, checks


from . import validate as _validate_module

_validate_module.register_domain_checks("retail", _checks)


__all__ = [
    "RetailWorld",
    "MonthEndClose",
    "lore",
    "BASE_INCIDENT_LIKELIHOOD",
    "Archetype",
    "AUSTRALIAN_GROCERY",
    "OMNICHANNEL_RETAILER",
]
