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

from . import archetypes
from .archetypes import AUSTRALIAN_GROCERY, OMNICHANNEL_RETAILER, Archetype
from .ids import Minter
from .models import ConstraintKind, LoreCommitment, LoreConstraint, LoreKind
from .rng import Rng
from .scenarios import MonthEndClose
from .world import World

#: Base probability of a data-quality incident during any given close, before
#: lore multipliers. Deliberately low: most closes are uneventful, and a corpus
#: where every period has a crisis is not a realistic one.
BASE_INCIDENT_LIKELIHOOD = 0.18


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

    @classmethod
    def inspired_by(cls, description: str, *, seed: int) -> RetailWorld:
        """A world shaped like the business *description* names.

        Shape only: unit mix, margin structure, store count, category depth. No
        figure, name, or fact about the described company is looked up or used —
        the point is a corpus that behaves like that *kind* of business while
        being wholly invented.
        """
        return cls(seed=seed, archetype=archetypes.inspired_by(description))

    def build(self) -> World:
        """Generate the organisation, its lore, and the lore's founding milestones.

        Every dated lore commitment arrives with a matching event and fact
        already on the timeline — the world's beginning, not yet any close.
        """
        from . import recipe as recipe_module
        from .generators import organisation

        rng = Rng(self.seed)
        minter = Minter()

        commitments = lore(minter)
        org = organisation.generate(
            rng.derive("organisation"), minter,
            archetype=self.archetype, lore=commitments,
        )

        return World(
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
            _annual_revenue=self.annual_revenue or self.archetype.annual_revenue,
            _archetype=self.archetype,
            _recipe=recipe_module.build_recipe(
                archetype=self.archetype.key,
                seed=self.seed,
                employees=self.employees,
                annual_revenue=self.annual_revenue,
            ),
        )


__all__ = [
    "RetailWorld",
    "MonthEndClose",
    "lore",
    "BASE_INCIDENT_LIKELIHOOD",
    "Archetype",
    "AUSTRALIAN_GROCERY",
    "OMNICHANNEL_RETAILER",
]
