"""Scenarios.

A scenario is a declaration of a situation, run against a built world to produce
events, facts, artifact intents, and evaluation cases.

There is deliberately no scenario DSL here. Designing one before a second vertical
exists would encode guesses rather than recurring structure, so `MonthEndClose` is
an ordinary frozen dataclass with a `run` method. The abstraction gets extracted at
build-order step 7, once IT services has shown which parts actually repeat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .rng import Rng

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


def lore_index(world: World) -> dict[str, list[str]]:
    """Map each lore constraint target to the commitments that touch it.

    This is how a generated fact records *why* it looks the way it does: the
    financial generator asks for ``forecast_miss/digital`` and gets back the
    replatform commitment, which then appears in the fact's ``lore_ids``.
    """
    index: dict[str, list[str]] = {}
    for commitment in world.lore:
        for constraint in commitment.constrains:
            index.setdefault(constraint.target, []).append(commitment.id)
    return index


def likelihood_multiplier(world: World, target: str) -> float:
    """The product of every ``event_likelihood`` magnitude aimed at *target*."""
    multiplier = 1.0
    for commitment in world.lore:
        for constraint in commitment.constrains:
            if constraint.kind.value == "event_likelihood" and constraint.target == target:
                multiplier *= constraint.magnitude if constraint.magnitude is not None else 1.0
    return multiplier


def density_adjustment(world: World, target: str) -> float:
    """The summed ``artifact_density`` magnitude aimed at *target*."""
    total = 0.0
    for commitment in world.lore:
        for constraint in commitment.constrains:
            if constraint.kind.value == "artifact_density" and constraint.target == target:
                total += constraint.magnitude or 0.0
    return total


@dataclass(frozen=True)
class MonthEndClose:
    """One month-end close, with or without an operational incident.

    ``include_operational_incident`` forces the incident on or off. Left as
    ``None``, whether it happens is decided by the seed weighted by lore — which
    is the interesting behaviour, because it means the 2024 decision to maintain a
    mapping table by hand is what makes a 2026 close go wrong.
    """

    period: str
    include_operational_incident: bool | None = None

    def run(self, world: World) -> World:
        """Return a new world with this episode's events, facts, and plans.

        The world passed in is not mutated.
        """
        from .generators import finance, operations, planning
        from .retail import BASE_INCIDENT_LIKELIHOOD

        if world.seed is None:
            raise ValueError("a scenario needs a seeded world; use RetailWorld(seed=...).build()")
        if world._minter is None:
            raise ValueError("this world was loaded from disk and cannot be advanced; build one from a seed")

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}")
        minter = world._minter
        roles = dict(world._roles)
        index = lore_index(world)

        likelihood = BASE_INCIDENT_LIKELIHOOD * likelihood_multiplier(
            world, "data_quality_incident/inventory"
        )

        episode = operations.generate(
            rng.derive("operations"), minter,
            period=self.period,
            company_id=world.company.id,
            roles=roles,
            lore_by_target=index,
            incident_likelihood=likelihood,
            force_incident=self.include_operational_incident,
        )

        unit_ids = {
            "food": roles["unit_food"],
            "gm": roles["unit_gm"],
            "digital": roles["unit_digital"],
        }
        from .generators.organisation import unit_shares

        financial_facts = finance.generate(
            rng.derive("finance"), minter,
            period=self.period,
            company_id=world.company.id,
            unit_ids=unit_ids,
            unit_shares=unit_shares(),
            erp_id=roles["sys_erp"],
            commerce_id=roles["sys_commerce"],
            finalised_at=episode.finalised_at,
            close_event_id=episode.close_event_id,
            annual_revenue=world._annual_revenue,
            lore_by_target=index,
        )

        intents = planning.artifact_intents(
            minter,
            episode=episode,
            roles=roles,
            financial_facts=financial_facts,
            period=self.period,
            density=1.0 + density_adjustment(world, "finance/status_reports"),
        )

        cases = planning.evaluation_cases(
            minter,
            episode=episode,
            financial_facts=financial_facts,
            company_id=world.company.id,
            unit_ids=unit_ids,
            unit_names={unit.id: unit.name for unit in world.business_units},
            period=self.period,
        )

        return world.extend(
            events=episode.events,
            facts=(*episode.facts, *financial_facts),
            artifact_intents=intents,
            evaluations=cases,
            period=self.period,
        )


__all__ = ["MonthEndClose", "lore_index", "likelihood_multiplier", "density_adjustment"]
