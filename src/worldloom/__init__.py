"""Worldloom — coherent synthetic enterprise worlds.

The top-level namespace stays small on purpose. A senior engineer should be able
to discover the library from autocomplete alone::

    from worldloom import World

    world = World.load("retail-close")
    world.validate().raise_if_failed()
    print(world.summary())

Or generate one from a seed::

    from worldloom import RetailWorld, MonthEndClose

    world = RetailWorld(seed=8128).build()
    world = world.run(MonthEndClose(period="2026-03"))

Everything else is reachable from a ``World``.
"""

from .models import (
    AccessPolicy,
    ArtifactIntent,
    ArtifactIR,
    ArtifactManifestEntry,
    Authority,
    BusinessUnit,
    CanonicalFact,
    Company,
    ConstraintKind,
    CostCentre,
    Employee,
    EnterpriseEvent,
    EvaluationCase,
    EvaluationType,
    GenerationLedgerEntry,
    IntentionalError,
    Lifecycle,
    LoreCommitment,
    LoreConstraint,
    LoreKind,
    Persona,
    Quantity,
    Service,
    System,
)
from .validate import CoherenceError, ValidationReport, Violation
from .world import World
from .scenarios import MonthEndClose
from .retail import RetailWorld

__version__ = "0.1.0"

__all__ = [
    # entry points
    "World",
    "RetailWorld",
    "MonthEndClose",
    # entities
    "Company",
    "BusinessUnit",
    "Employee",
    "System",
    "Service",
    "CostCentre",
    "Persona",
    # lore
    "LoreCommitment",
    "LoreConstraint",
    "LoreKind",
    "ConstraintKind",
    # simulation
    "EnterpriseEvent",
    "CanonicalFact",
    "Quantity",
    "Authority",
    # artifacts
    "ArtifactIntent",
    "ArtifactIR",
    "ArtifactManifestEntry",
    "Lifecycle",
    "AccessPolicy",
    "IntentionalError",
    # evaluation
    "EvaluationCase",
    "EvaluationType",
    # generation
    "GenerationLedgerEntry",
    # validation
    "ValidationReport",
    "Violation",
    "CoherenceError",
    "__version__",
]
