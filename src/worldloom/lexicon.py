"""External taxonomies, measured priors, and world-specific surface packs.

This module is intentionally separate from :mod:`worldloom.vocabulary`.
``vocabulary`` renames an already-authored archetype without changing its
shape. ``lexicon`` is the evidence boundary used to *author* worlds: taxonomies
say what may exist, empirical corpora measure how often it exists, and packs
choose how one region/company says it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from enum import StrEnum
from importlib.resources import files
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceClass(StrEnum):
    """How strongly a lexicon or prior row is grounded."""

    MEASURED = "measured"
    CUSTOMER_AGGREGATE = "customer_aggregate"
    CUSTOMER_METADATA = "customer_metadata"
    HARVESTED_TAXONOMY = "harvested_taxonomy"
    AUTHORED_PRIOR = "authored_prior"


class LexiconRecord(BaseModel):
    """One surface form resolving to a canonical enterprise concept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    type: str
    label: str
    canonical: str | None = None
    alt_labels: tuple[dict[str, str], ...] = ()
    lang: str = "en"
    industry: str | None = None
    region: str | None = None
    weight: float = Field(default=1.0, ge=0.0)
    source: str
    license: str
    evidence: EvidenceClass = EvidenceClass.HARVESTED_TAXONOMY
    description: str | None = None
    fill_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def concept(self) -> str:
        return self.canonical or self.id


class DistributionPrior(BaseModel):
    """A measured/authored categorical distribution for one canonical field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    canonical: str
    probabilities: dict[str, float]
    source: str
    license: str
    evidence: EvidenceClass = EvidenceClass.MEASURED
    industry: str | None = None
    region: str | None = None

    @model_validator(mode="after")
    def probabilities_are_normalized(self) -> DistributionPrior:
        if not self.probabilities:
            raise ValueError("probabilities must not be empty")
        if any(value < 0 for value in self.probabilities.values()):
            raise ValueError("probabilities must be non-negative")
        total = sum(self.probabilities.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"probabilities must sum to 1, got {total}")
        return self


class ProcessPrior(BaseModel):
    """Measured process-shape prior derived from an event log."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    cases: int = Field(ge=0)
    events: int = Field(ge=0)
    rework_case_rate: float = Field(ge=0.0, le=1.0)
    state_transitions: dict[str, int]
    inter_activity_seconds: dict[str, float | None]
    evidence: EvidenceClass = EvidenceClass.MEASURED


class SurfacePack(BaseModel):
    """Company/region surface-form priors, explicitly not empirical truth."""

    model_config = ConfigDict(frozen=True, extra="allow")

    id: str
    regions: tuple[str, ...]
    fiscal_year_start: dict[str, str]
    cross_industry: dict[str, Any]
    industries: dict[str, Any]
    evidence: EvidenceClass = EvidenceClass.AUTHORED_PRIOR
    note: str | None = None


def canonical_index(records: Iterable[LexiconRecord]) -> dict[str, tuple[LexiconRecord, ...]]:
    """Group all surface forms under their canonical concept."""
    grouped: dict[str, list[LexiconRecord]] = {}
    for record in records:
        grouped.setdefault(record.concept, []).append(record)
    return {key: tuple(value) for key, value in grouped.items()}


def load_process_prior(name: str) -> ProcessPrior:
    """Load a compact process prior shipped with the package."""
    resource = files("worldloom").joinpath("_data", "priors", f"{name}.json")
    return ProcessPrior.model_validate_json(resource.read_text(encoding="utf-8"))


def source_catalog() -> dict[str, Any]:
    """Return the auditable catalogue of external evidence inputs."""
    resource = files("worldloom").joinpath("_data", "vocabulary-sources.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("vocabulary source catalog must be an object")
    return payload
