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

Lazy on purpose (the startup budget)
------------------------------------

This module used to import the whole domain surface eagerly, and because a
submodule import always executes its package's ``__init__`` first, that made
``import worldloom.cli`` — the console script's floor — pay ~0.6s of pydantic
and vertical modules before ``--help`` could print a word. The imports now
live in :func:`_install`, and *nothing here imports them at module scope*.

What must not change is the contract those imports carried: **registration is
all-or-nothing.** Every comment inside ``_install`` describes a defect that
happened when some registration depended on which module a process happened to
import first. Laziness is safe only because ``_install`` is a single switch —
the first trigger installs *everything*, so no two processes that both
triggered it can disagree about what is registered. The triggers are the
places a fresh process enters the engine:

- any public attribute of this package (:func:`__getattr__`, PEP 562), so
  ``from worldloom import World`` behaves exactly as the eager module did;
- the CLI's app callback, which runs before any command body — command bodies
  import submodules directly and must find the tables full, as they always
  have;
- ``World.load`` and ``validate.validate``, for library callers who import
  submodules directly and never touch a package attribute;
- ``registries.scoped()``, before it snapshots: a first install *inside* a
  scope would be rolled back at scope exit and — modules being cached in
  ``sys.modules`` — never re-run, leaving the process permanently
  under-registered. Installing before the snapshot makes that impossible
  wherever a later trigger happens to sit.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

# The full public surface, re-imported under TYPE_CHECKING so mypy (and any
# IDE) sees exactly the names the eager module exported, while the runtime
# pays for none of it until `_install` runs. The `X as X` form marks each name
# as an intentional re-export.
if TYPE_CHECKING:
    from .banking import BankingWorld as BankingWorld
    from .banking_scenarios import QuarterlyCapitalReturn as QuarterlyCapitalReturn
    from .insurance import InsuranceWorld as InsuranceWorld
    from .insurance_scenarios import QuarterlyReserving as QuarterlyReserving
    from .models import (
        AccessPolicy as AccessPolicy,
    )
    from .models import (
        ArtifactIntent as ArtifactIntent,
    )
    from .models import (
        ArtifactIR as ArtifactIR,
    )
    from .models import (
        ArtifactManifestEntry as ArtifactManifestEntry,
    )
    from .models import (
        Authority as Authority,
    )
    from .models import (
        BusinessUnit as BusinessUnit,
    )
    from .models import (
        CanonicalFact as CanonicalFact,
    )
    from .models import (
        Company as Company,
    )
    from .models import (
        ConstraintKind as ConstraintKind,
    )
    from .models import (
        CostCentre as CostCentre,
    )
    from .models import (
        Employee as Employee,
    )
    from .models import (
        EnterpriseEvent as EnterpriseEvent,
    )
    from .models import (
        EvaluationCase as EvaluationCase,
    )
    from .models import (
        EvaluationType as EvaluationType,
    )
    from .models import (
        GenerationLedgerEntry as GenerationLedgerEntry,
    )
    from .models import (
        IntentionalError as IntentionalError,
    )
    from .models import (
        Lifecycle as Lifecycle,
    )
    from .models import (
        LoreCommitment as LoreCommitment,
    )
    from .models import (
        LoreConstraint as LoreConstraint,
    )
    from .models import (
        LoreKind as LoreKind,
    )
    from .models import (
        Persona as Persona,
    )
    from .models import (
        Quantity as Quantity,
    )
    from .models import (
        Service as Service,
    )
    from .models import (
        System as System,
    )
    from .procurement import ProcureToPayWorld as ProcureToPayWorld
    from .procurement_scenarios import PurchaseToPayCycle as PurchaseToPayCycle
    from .retail import RetailWorld as RetailWorld
    from .scenarios import MonthEndClose as MonthEndClose
    from .validate import (
        CoherenceError as CoherenceError,
    )
    from .validate import (
        ValidationReport as ValidationReport,
    )
    from .validate import (
        Violation as Violation,
    )
    from .workforce import HiringRound as HiringRound
    from .workforce import PerformanceCycle as PerformanceCycle
    from .world import World as World

__version__ = "0.1.0"

_installed = False


def _install() -> None:
    """Import the whole domain surface — registrations included — exactly once.

    The flag is set *before* the imports rather than after: several of these
    modules import each other back through this package, and a re-entrant call
    mid-install must be a no-op, not a loop. A failure part-way leaves the
    flag set with the process broken — the same state a failed eager import
    left it in, and the exception is the same one the eager module raised.
    """
    global _installed
    if _installed:
        return
    _installed = True

    # And for the cohort axis's check group, which is a registration and nothing
    # else. It has to be here rather than reached from `episodes`: the group reads
    # the *installed* specs at check time, so nothing imports it on the way to
    # building a world, and a corpus validated in a fresh process (`worldloom
    # validate <corpus>`) would otherwise have its grids checked by nobody while
    # reporting a clean run — the failure mode `register_domain_checks` names.
    from . import cohorts as _cohorts  # noqa: F401

    # And once more for the episode grammar: importing this registers the
    # `AuthoredEpisode` recipe verb. The verb resolves the episode *name* against
    # the process's installed specs at run time — so a rebuild without the spec
    # fails loudly in `AuthoredEpisode.run`, not with `unknown scenario` here.
    from . import episodes as _episodes  # noqa: F401

    # Same contract again, one level up: importing this is what registers the
    # `Imperfections` recipe verb, and a corpus built with a messiness profile
    # cannot rebuild itself in a process where that verb is unknown. `recipe.rebuild`
    # would raise `unknown scenario` — a corpus that reports a clean recipe and
    # refuses to replay, which is the exact failure lazy registration always is.
    from . import messiness  # noqa: F401

    # And once more for the standing documents. `policies` registers ten artifact
    # types by being imported, and it was reached only from inside a world
    # builder's `build()` — so a process that had not built with `--policies` did
    # not know those types existed, and `documents.declared_types()` returned two
    # different answers depending on what had run before it. Caught by
    # `tests/test_doctypes.py` passing alone and failing in a full suite, which is
    # exactly how this class of defect announces itself and exactly why
    # `register_artifact_types` says registration belongs at package import.
    from . import policies as _policies  # noqa: F401

    # Imported unconditionally, not on demand: importing the banking module is what
    # registers its validator check group and artifact types, and a corpus loaded
    # in a fresh process must validate and compile identically to the process that
    # generated it. Lazy registration would make coherence depend on import order.
    from .banking import BankingWorld
    from .banking_scenarios import QuarterlyCapitalReturn

    # Same contract as the banking imports above: importing this is what registers
    # the `routine_notice` artifact type (build --distractors's plainest family),
    # and a corpus that carries one must compile identically whether this process
    # built it or is only reading it back.
    from .generators import distractors as _distractors  # noqa: F401

    # Same contract as the banking imports above, for the third vertical.
    from .insurance import InsuranceWorld
    from .insurance_scenarios import QuarterlyReserving
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

    # And the fourth. Worth naming what this line is, because it is the one seam a
    # vertical needs that is not a registry: there is no plugin discovery, so a
    # domain module registers by *being imported*, and the only thing that imports
    # it unconditionally is this file. Everything else procurement touches in core
    # it reaches through `register_domain`, `register_step`,
    # `register_artifact_types` and `register_domain_checks`; this import is the
    # fifth seam, and it is a hand edit.
    from .procurement import ProcureToPayWorld
    from .procurement_scenarios import PurchaseToPayCycle
    from .retail import RetailWorld
    from .scenarios import MonthEndClose
    from .validate import CoherenceError, ValidationReport, Violation

    # Same contract for the workforce rounds: importing this registers five
    # artifact types and ten fact kinds, and `policies` paid for learning that a
    # lazy registration makes `documents.declared_types()` depend on what has run.
    from .workforce import HiringRound, PerformanceCycle
    from .world import World

    # Publish the names on the package, so after the first trigger every access
    # is a plain attribute read and `__getattr__` never fires again for them.
    globals().update(
        World=World,
        RetailWorld=RetailWorld,
        MonthEndClose=MonthEndClose,
        BankingWorld=BankingWorld,
        QuarterlyCapitalReturn=QuarterlyCapitalReturn,
        InsuranceWorld=InsuranceWorld,
        QuarterlyReserving=QuarterlyReserving,
        ProcureToPayWorld=ProcureToPayWorld,
        PurchaseToPayCycle=PurchaseToPayCycle,
        HiringRound=HiringRound,
        PerformanceCycle=PerformanceCycle,
        Company=Company,
        BusinessUnit=BusinessUnit,
        Employee=Employee,
        System=System,
        Service=Service,
        CostCentre=CostCentre,
        Persona=Persona,
        LoreCommitment=LoreCommitment,
        LoreConstraint=LoreConstraint,
        LoreKind=LoreKind,
        ConstraintKind=ConstraintKind,
        EnterpriseEvent=EnterpriseEvent,
        CanonicalFact=CanonicalFact,
        Quantity=Quantity,
        Authority=Authority,
        ArtifactIntent=ArtifactIntent,
        ArtifactIR=ArtifactIR,
        ArtifactManifestEntry=ArtifactManifestEntry,
        Lifecycle=Lifecycle,
        AccessPolicy=AccessPolicy,
        IntentionalError=IntentionalError,
        EvaluationCase=EvaluationCase,
        EvaluationType=EvaluationType,
        GenerationLedgerEntry=GenerationLedgerEntry,
        ValidationReport=ValidationReport,
        Violation=Violation,
        CoherenceError=CoherenceError,
    )


def __getattr__(name: str) -> Any:
    """PEP 562: a re-exported name installs the whole surface; a submodule does not.

    The split is load-bearing, not an optimisation. ``from . import columns``
    inside a module body reaches here while that submodule attribute is unset,
    and it must behave exactly as it did under the eager init — a plain
    submodule import — because ``_install`` fired at that moment closes a
    circular import: ``documents``' own body resolves ``columns`` through this
    function, and installing would re-enter half-initialized ``documents``
    via ``policies`` (measured: ``ImportError: cannot import name 'FilingPlan'
    from partially initialized module`` in every fresh process that imported
    ``worldloom.compiler`` first). Underscored names are refused outright —
    `copy`, `pickle` and `inspect` probe modules for dunders, and a probe must
    not import anything.
    """
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name in _EXPORTS:
        _install()
        return globals()[name]
    try:
        return import_module(f".{name}", __name__)
    except ModuleNotFoundError as exc:
        # Only "worldloom.<name> does not exist" becomes AttributeError; a
        # missing *dependency* inside a real submodule stays an ImportError,
        # or the diagnosis would point at a module that exists.
        if exc.name != f"{__name__}.{name}":
            raise
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def __dir__() -> list[str]:
    # `__all__` plus whatever is actually present — before install that is the
    # honest discovery surface, after install it includes the submodules too.
    return sorted(set(globals()) | set(__all__))


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

#: The names `__getattr__` answers by installing: the eager module's public
#: re-exports — `__all__` minus the version string (a plain module global
#: above), plus the two workforce rounds, which were importable without being
#: listed in `__all__`. Derived rather than restated so the lists cannot
#: drift; `_install` publishing a name this set does not admit would strand it.
_EXPORTS = frozenset(__all__) - {"__version__"} | {"HiringRound", "PerformanceCycle"}
