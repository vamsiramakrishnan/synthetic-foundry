"""Artifact-ecology connector projection.

The legacy connector projection remains byte-stable. Call this surface when a
recipe opts into ``artifact_realism=ecology/v1``; the ordinary connector engine
then adds product-specific workflow history exactly once.
"""

from __future__ import annotations

from .connector_data import (
    ConnectorDataset,
    ConnectorProjectionRegistry,
    generate_connector_data,
)
from .world import World


def generate_realistic_connector_data(
    world: World,
    connectors: tuple[str, ...] = (
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
    """Generate connector records through the ecology-aware core path.

    ``connector_data.generate_connector_data`` owns enrichment once the recipe
    carries ``artifact_realism=ecology/v1``. Keeping this wrapper thin prevents
    histories or comments from being appended twice while preserving an obvious
    SDK entry point for callers that want realistic enterprise connectors.
    """
    return generate_connector_data(world, connectors, projections=projections)
