"""Worldloom — coherent synthetic enterprise worlds.

The top-level namespace stays small on purpose. A senior engineer should be able
to discover the library from autocomplete alone::

    from worldloom import World

    world = World.load("retail-close")
    world.validate().raise_if_failed()
    print(world.summary())

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

__version__ = "0.0.1"

__all__ = [
    # entry point
    "World",
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
