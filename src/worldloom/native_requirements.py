"""Declared native evaluation demands, separate from descriptive task counts."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .models import Model


class CoverageDimension(Model):
    """An exact selector over independently verified case or source metadata."""

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)


class CoverageRequirement(Model):
    """One required measured cell; selectors are intersected, never expanded.

    The minimum applies to training coverage. Every fresh held-out tranche must
    additionally meet the qualification policy's independent-unit floor. A
    format copy or another question on the same source cannot buy support.
    """

    name: str = Field(min_length=1)
    operation: Literal["read", "analyze", "update", "create"] | None = None
    format: Literal["docx", "pptx", "xlsx"] | None = None
    format_role: Literal["operation", "input", "output", "any"] = "operation"
    calculation: Literal["sum", "difference", "ratio"] | None = None
    scope: Literal["artifact", "cross_artifact"] | None = None
    dimensions: tuple[CoverageDimension, ...] = ()
    min_independent_units: int = Field(default=1, ge=1, strict=True)

    @model_validator(mode="after")
    def _selectors(self) -> CoverageRequirement:
        if not self.name.strip() or not any((self.operation, self.format, self.calculation, self.scope, self.dimensions)):
            raise ValueError("coverage requirements need a name and at least one measured selector")
        if len({item.name for item in self.dimensions}) != len(self.dimensions):
            raise ValueError("coverage requirement dimensions must have distinct names")
        return self


class BenchmarkRequirements(Model):
    """Explicit required cells; operation/format products are never implicit.

    Requested plan operations and formats remain mandatory independently of
    these additional cells. Empty additional requirements cannot disable them.
    """

    schema_version: Literal["worldloom.benchmark-requirements/v1"] = "worldloom.benchmark-requirements/v1"
    cells: tuple[CoverageRequirement, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> BenchmarkRequirements:
        if len({cell.name for cell in self.cells}) != len(self.cells):
            raise ValueError("coverage requirement names must be distinct")
        return self


__all__ = ["BenchmarkRequirements", "CoverageDimension", "CoverageRequirement"]
