"""Deterministic relational microdata, paired interventions and behavioral search.

This opt-in layer leaves existing World recipes and golden corpora unchanged.
It simulates declared business mechanisms; it does not fit real customer data
or claim differential privacy, statistical calibration or macro reconciliation.
"""

from __future__ import annotations

from .compiler import compile_program
from .connectors import (
    IncidentRule,
    exception_episodes,
    operational_profile,
    operational_projections,
)
from .engine import Delta, Simulator, compare
from .models import (
    Column,
    Constraint,
    Expr,
    Intervention,
    Limits,
    Parameter,
    Program,
    Relation,
    Row,
    SynthesisError,
    Table,
    expr,
    lag,
    literal,
    param,
    ref,
    uniform,
)
from .programs import banking, retail
from .search import (
    Axis,
    Metric,
    SearchPlan,
    Target,
    banking_search_plan,
    measure,
    retail_search_plan,
    search,
    with_parameters,
)
from .storage import export, iter_export, load_simulator, merge_exports, verify_export

__all__ = [
    "Column", "Constraint", "Expr", "Intervention", "Limits", "Parameter",
    "Program", "Relation", "Row", "SynthesisError", "Table", "expr", "lag",
    "literal", "param", "ref", "uniform", "compile_program",
    "Delta", "Simulator", "compare", "banking", "retail",
    "Axis", "Metric", "SearchPlan", "Target", "banking_search_plan", "measure",
    "retail_search_plan", "search", "with_parameters",
    "export", "iter_export", "load_simulator", "merge_exports", "verify_export",
    "IncidentRule", "exception_episodes", "operational_profile", "operational_projections",
]
