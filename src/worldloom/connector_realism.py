"""Artifact-ecology connector projection.

The legacy connector projection remains byte-stable. Call this surface when a
recipe opts into ``artifact_realism=ecology/v1``; it enriches the same records
with product-specific workflow history instead of inventing another data path.
"""

from __future__ import annotations

from .artifact_ecology import enrich_connector_records
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
    """Generate connector records and apply ecology detail when enabled.

    Keeping this as a wrapper gives callers a migration seam: old corpus recipes
    keep their exact records, while an ecology recipe gains histories, SLAs,
    conversation metadata, backlinks, and product-specific workflow semantics.
    """
    base = generate_connector_data(world, connectors, projections=projections)
    enriched = enrich_connector_records(world, base.records)
    return ConnectorDataset(capabilities=base.capabilities, records=enriched)
