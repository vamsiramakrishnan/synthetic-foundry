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
from .compiler import compile_company, default_company, load_catalogue, stream_names
from .models import (
    ActivityBinding,
    BusinessUnit,
    CompanySpec,
    CompiledCatalogue,
    CoverageCell,
    Finding,
)
from .ownership import materialize_owners
from .situations import Situation, coverage, situations, situations_for
from .storage import (
    replay_builtin,
    summary,
    verify_export,
    write_compilation,
)

__all__ = [
    "ActivityBinding", "BusinessUnit", "CompanySpec", "CompiledCatalogue", "CoverageCell", "Finding",
    "ProcessDemand", "Situation", "compile_company", "coverage", "default_company",
    "load_catalogue",
    "stream_names", "situations", "situations_for",
    "materialize_owners",
    "authoring_brief", "dataset", "demands", "lexicon_records", "sample_channels", "tool_surface", "verify_ownership",
    "replay_builtin", "summary", "verify_export", "write_compilation",
]
