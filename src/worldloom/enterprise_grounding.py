"""What a world can ground: the evidence-bearing records behind each source.

A planned row reads its sources for evidence, and the validator accepts a
record as evidence only when ``carries_evidence`` holds for it. The planner
used to admit any source its registry named, so on a world with no ServiceNow
incidents it planned incident reviews, the corpus builder minted fact-less
filler records to meet the count, and the validator refused them, aborting
every shipped world and profile at the last step. The inventory here is the
count of evidence-bearing records the world offers each source, derived from
the same connector data generation the build runs, so the planner can refuse
a source the world cannot ground before a row is ever planned over it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .connector_data import (
    ConnectorProjectionRegistry,
    builtin_projections,
    generate_connector_data,
)
from .enterprise_evidence import carries_evidence

if TYPE_CHECKING:
    from .enterprise_specs import SpecRegistry
    from .world import World


def entity_matches(connector: str, requested: str, actual: str) -> bool:
    """Alias-aware: a source role asking for a ``file`` is met by a ``docx``.

    File connectors project one record per artifact and format, under the
    definition's entity for that format; the role vocabulary still says
    ``file``, which the definition resolves through its alias.
    """

    if requested == actual:
        return True
    return _alias_matches(connector, requested, actual)


@lru_cache(maxsize=4096)
def _alias_matches(connector: str, requested: str, actual: str) -> bool:
    # Memoised per triple: materialisation asks this once per requirement and
    # record, and a corpus of ten thousand records must not parse the
    # definition ten thousand times.
    from .connector_definition import is_reference_connector, load_connector_definition

    if not is_reference_connector(connector):
        return False
    try:
        return load_connector_definition(connector).entity_matches(requested, actual)
    except KeyError:
        return False


def registry_sources(registry: SpecRegistry) -> tuple[tuple[str, str], ...]:
    """Every (connector, entity) a source role in the registry names, sorted."""
    return tuple(sorted({
        (role.connector, entity)
        for workflow in registry.workflows.values()
        for role in workflow.sources
        for entity in role.entities
    }))


def groundable_inventory(
    world: World,
    registry: SpecRegistry,
    *,
    projections: ConnectorProjectionRegistry | None = None,
) -> dict[tuple[str, str], int]:
    """Count the evidence-bearing records the world offers each source the registry names.

    The count is keyed by the source's own (connector, entity), so a ``file``
    role counts the ``docx`` and ``xlsx`` records its alias resolves to. The
    data comes from ``generate_connector_data`` over every registry connector
    the projections know, the call the build makes, so the inventory and the
    corpus agree record for record. A connector no projection serves grounds
    nothing.
    """
    projections = projections or builtin_projections()
    sources = registry_sources(registry)
    connectors = tuple(sorted(set(registry.connectors) & set(projections.names)))
    records = (
        generate_connector_data(world, connectors=connectors, projections=projections).records
        if connectors else []
    )
    evidence = [record for record in records if carries_evidence(record)]
    return {
        (connector, entity): sum(
            record.connector == connector and entity_matches(connector, entity, record.entity)
            for record in evidence
        )
        for connector, entity in sources
    }


__all__ = ["entity_matches", "groundable_inventory", "registry_sources"]
