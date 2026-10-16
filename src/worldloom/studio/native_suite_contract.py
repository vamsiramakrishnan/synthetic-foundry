"""Typed request shared by native suite workers and synchronous SDK callers."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from ..models import Model


class NativeSuiteRequest(Model):
    use_case_id: str = Field(min_length=1)
    formats: tuple[Literal["docx", "pptx", "xlsx"], ...] = ("docx", "pptx", "xlsx")
    operations: tuple[Literal["read", "analyze", "update", "create"], ...] = ("read", "analyze", "update", "create")
    minimum_units: int = Field(default=2, ge=1, le=10000, strict=True)
    max_cases: int = Field(default=12, ge=1, le=256, strict=True)
    source_artifact_ids: tuple[str, ...] = ()
    query_style: Literal["located", "discovery"] = "located"
    discovery_scope: Literal["artifact", "cross_artifact", "mixed"] = "mixed"
    max_tasks_per_case: int = Field(default=64, ge=1, le=10000, strict=True)

    @model_serializer(mode="wrap")
    def _compatibility_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for name, default in (("query_style", "located"), ("discovery_scope", "mixed"), ("max_tasks_per_case", 64)):
            if data.get(name) == default:
                data.pop(name, None)
        return data

    @model_validator(mode="after")
    def contract(self) -> NativeSuiteRequest:
        for values in (self.formats, self.operations):
            if not values or len(set(values)) != len(values):
                raise ValueError("choose distinct formats and operations")
        if self.query_style == "located" and "analyze" in self.operations and "xlsx" not in self.formats:
            raise ValueError("arithmetic analysis requires xlsx evidence")
        return self
