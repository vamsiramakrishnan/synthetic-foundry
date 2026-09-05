"""Authored industry catalogue -> company bindings -> authoring and eval demands.

Opt-in: no existing World recipe, macro facts or operational simulator changes.
"""
from __future__ import annotations

from .adapters import (
    ProcessDemand,
    authoring_brief,
    dataset,
    demands,
    lexicon_records,
    sample_channels,
    tool_surface,
    verify_ownership,
)
from .compiler import compile_company, default_company, load_catalogue
from .models import (
    ActivityBinding,
    BusinessUnit,
    CompanySpec,
    CompiledCatalogue,
    CoverageCell,
    Finding,
)
from .storage import (
    baseline_parity,
    replay_builtin,
    summary,
    verify_export,
    write_compilation,
)

__all__ = [
    "ActivityBinding", "BusinessUnit", "CompanySpec", "CompiledCatalogue", "CoverageCell", "Finding",
    "ProcessDemand", "compile_company", "default_company", "load_catalogue",
    "authoring_brief", "dataset", "demands", "lexicon_records", "sample_channels", "tool_surface", "verify_ownership",
    "baseline_parity", "replay_builtin", "summary", "verify_export", "write_compilation",
]
