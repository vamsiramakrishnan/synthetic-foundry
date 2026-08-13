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

# And the fourth. Worth naming what this line is, because it is the one seam a
# vertical needs that is not a registry: there is no plugin discovery, so a
# domain module registers by *being imported*, and the only thing that imports
# it unconditionally is this file. Everything else procurement touches in core
# it reaches through `register_domain`, `register_step`,
# `register_artifact_types` and `register_domain_checks`; this import is the
# fifth seam, and it is a hand edit.
from .procurement import ProcureToPayWorld
from .procurement_scenarios import PurchaseToPayCycle

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

# And once more for the episode grammar: importing this registers the
# `AuthoredEpisode` recipe verb. The verb resolves the episode *name* against
# the process's installed specs at run time — so a rebuild without the spec
# fails loudly in `AuthoredEpisode.run`, not with `unknown scenario` here.
from . import episodes as _episodes  # noqa: F401

# And for the cohort axis's check group, which is a registration and nothing
# else. It has to be here rather than reached from `episodes`: the group reads
# the *installed* specs at check time, so nothing imports it on the way to
# building a world, and a corpus validated in a fresh process (`worldloom
# validate <corpus>`) would otherwise have its grids checked by nobody while
# reporting a clean run — the failure mode `register_domain_checks` names.
from . import cohorts as _cohorts  # noqa: F401

# And once more for the standing documents. `policies` registers ten artifact
# types by being imported, and it was reached only from inside a world
# builder's `build()` — so a process that had not built with `--policies` did
# not know those types existed, and `documents.declared_types()` returned two
# different answers depending on what had run before it. Caught by
# `tests/test_doctypes.py` passing alone and failing in a full suite, which is
# exactly how this class of defect announces itself and exactly why
# `register_artifact_types` says registration belongs at package import.
from . import policies as _policies  # noqa: F401

# Same contract for the workforce rounds: importing this registers five
# artifact types and ten fact kinds, and `policies` paid for learning that a
# lazy registration makes `documents.declared_types()` depend on what has run.
from .workforce import HiringRound, PerformanceCycle  # noqa: F401

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
    "ProcureToPayWorld",
    "PurchaseToPayCycle",
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
