"""Public SDK for artifact ecology.

This is deliberately a thin facade over existing Worldloom contracts. The world
still owns facts and IR; renderers still own bytes; ecology only adds stable
style/lifecycle policy, richer connector evidence, and mechanical realism gates.
"""

from __future__ import annotations

from dataclasses import dataclass

from .artifact_ecology import RealismProfile, enrich_world, profile
from .connector_data import ConnectorDataset, ConnectorProjectionRegistry
from .connector_realism import generate_realistic_connector_data
from .realism import RealismReport, evaluate
from .world import World


@dataclass(frozen=True)
class EcologyResult:
    world: World
    profile: RealismProfile
    realism: RealismReport


def prepare(world: World) -> EcologyResult:
    """Compile and annotate a world with deterministic artifact ecology."""
    enriched = enrich_world(world)
    return EcologyResult(
        world=enriched,
        profile=profile(enriched),
        realism=evaluate(enriched),
    )


def render(world: World, *formats: str) -> EcologyResult:
    """Render through ordinary Worldloom renderers after ecology annotation."""
    prepared = prepare(world)
    rendered = prepared.world.render(*formats)
    return EcologyResult(
        world=rendered,
        profile=profile(rendered),
        realism=evaluate(rendered),
    )


def connectors(
    world: World,
    names: tuple[str, ...] = (
        "jira",
        "confluence",
        "sharepoint",
        "drive",
        "servicenow",
        "salesforce",
        "email",
    ),
    *,
    projections: ConnectorProjectionRegistry | None = None,
) -> ConnectorDataset:
    """Generate product-specific connector evidence using ecology semantics."""
    prepared = prepare(world)
    return generate_realistic_connector_data(
        prepared.world,
        names,
        projections=projections,
    )
