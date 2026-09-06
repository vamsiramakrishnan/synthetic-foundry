"""Typed, version-bound evidence addresses shared by artifacts and tool grading."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import Model


class FieldLocator(Model):
    kind: Literal["field"] = "field"
    connector: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    field: str = Field(min_length=1)


class SlideLocator(Model):
    kind: Literal["pptx"] = "pptx"
    slide: int = Field(ge=1)
    element: Literal["text", "table", "chart", "notes", "image"]
    shape_id: int | None = Field(default=None, ge=1)
    series: str | None = None
    point: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _chart_address(self) -> SlideLocator:
        if (self.series is not None or self.point is not None) and self.element != "chart":
            raise ValueError("series and point address chart elements only")
        return self


class CellLocator(Model):
    kind: Literal["xlsx"] = "xlsx"
    sheet: str = Field(min_length=1)
    cell: str = Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]*$")

    @model_validator(mode="after")
    def _excel_bounds(self) -> CellLocator:
        letters = self.cell.rstrip("0123456789")
        column = 0
        for letter in letters:
            column = column * 26 + ord(letter) - ord("A") + 1
        if column > 16384 or int(self.cell[len(letters):]) > 1048576:
            raise ValueError("cell is outside worksheet bounds")
        return self


class PageLocator(Model):
    kind: Literal["pdf", "docx"]
    page: int = Field(ge=1)
    paragraph: int | None = Field(default=None, ge=1)


Locator = Annotated[FieldLocator | SlideLocator | CellLocator | PageLocator, Field(discriminator="kind")]


class EvidenceRef(Model):
    fact_ids: tuple[str, ...] = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: Locator

    @model_validator(mode="after")
    def _unique(self) -> EvidenceRef:
        if len(set(self.fact_ids)) != len(self.fact_ids) or any(not fid for fid in self.fact_ids):
            raise ValueError("evidence fact IDs must be nonempty and unique")
        return self


def field_evidence(record_id: str, *, connector: str, entity: str, external_id: str,
                   field: str, fact_ids: Sequence[str], content_digest: str) -> EvidenceRef:
    return EvidenceRef(fact_ids=tuple(fact_ids), artifact_id=record_id,
                       content_digest=content_digest,
                       locator=FieldLocator(connector=connector, entity=entity,
                                            external_id=external_id, field=field))


__all__ = ["CellLocator", "EvidenceRef", "FieldLocator", "Locator", "PageLocator", "SlideLocator", "field_evidence"]
