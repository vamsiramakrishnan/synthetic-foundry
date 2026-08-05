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

# Imported unconditionally, not on demand: importing the banking module is what
# registers its validator check group and artifact types, and a corpus loaded
# in a fresh process must validate and compile identically to the process that
# generated it. Lazy registration would make coherence depend on import order.
from .banking import BankingWorld
from .banking_scenarios import QuarterlyCapitalReturn

# Same contract as the banking imports above, for the third vertical.
from .insurance import InsuranceWorld
from .insurance_scenarios import QuarterlyReserving

# Same contract as the banking imports above: importing this is what registers
# the `routine_notice` artifact type (build --distractors's plainest family),
# and a corpus that carries one must compile identically whether this process
# built it or is only reading it back.
from .generators import distractors as _distractors  # noqa: F401

# Same contract again, one level up: importing this is what registers the
# `Imperfections` recipe verb, and a corpus built with a messiness profile
# cannot rebuild itself in a process where that verb is unknown. `recipe.rebuild`
# would raise `unknown scenario` — a corpus that reports a clean recipe and
# refuses to replay, which is the exact failure lazy registration always is.
from . import messiness  # noqa: F401

__version__ = "0.1.0"

__all__ = [
    # entry points
    "World",
    "RetailWorld",
    "MonthEndClose",
    "BankingWorld",
    "QuarterlyCapitalReturn",
    "InsuranceWorld",
    "QuarterlyReserving",
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
