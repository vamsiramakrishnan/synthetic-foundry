"""Authored industry factors -> deterministic company process plans.

Use ``compile_company(default_company("retail"))`` to bind the supplied factors.
Use ``worldloom.process.open_from_catalogue`` to author an executable episode
through the existing refusal/acceptance gates, not around them.
"""
from .compiler import (
    authoring_context,
    compile_company,
    default_company,
    load_catalogue,
)
from .io import export_compilations, replay_plan, to_lexicon
from .models import (
    ActivityInstance,
    Catalogue,
    CompanyProcessSpec,
    Compilation,
    CoverageCell,
    Diagnostic,
    Unit,
)

__all__ = [
    "Catalogue", "CompanyProcessSpec", "Unit", "Compilation", "ActivityInstance", "CoverageCell", "Diagnostic",
    "load_catalogue", "default_company", "compile_company", "authoring_context", "to_lexicon", "export_compilations", "replay_plan",
]
