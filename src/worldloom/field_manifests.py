"""Canonical-to-native field schemas shared by synthesis and tool contracts."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from .ids import content_key
from .models import Model
from .predicates import Predicate, evaluate
from .rng import Rng


class FieldSpec(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    canonical: str | None = None
    aliases: tuple[str, ...] = ()
    type: Literal["text", "number", "boolean", "date", "option", "multi", "user"] = "text"
    options: tuple[str, ...] = ()
    required: bool = False
    required_for: tuple[tuple[str, str], ...] = ()
    screens: tuple[Literal["create", "edit"], ...] = ("create", "edit")
    fill_rate: float = Field(default=.5, ge=0, le=1)
    present_when: Predicate | None = None
    deprecated: bool = False

    @model_validator(mode="after")
    def _options(self) -> FieldSpec:
        if self.type == "option" and not self.options:
            raise ValueError(f"{self.id}: option field requires options")
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"{self.id}: duplicate options")
        if self.present_when is not None and (self.present_when.as_of is not None or self.present_when.joins):
            raise ValueError("field presence conditions must be record-local")
        return self

    def required_in(self, project: str | None, issue_type: str | None) -> bool:
        return self.required or (project, issue_type) in self.required_for

    def valid_value(self, value: Any) -> bool:
        if value is None:
            return True
        if self.type in {"text", "user"}:
            return isinstance(value, str)
        if self.type == "boolean":
            return isinstance(value, bool)
        if self.type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        if self.type == "option":
            return isinstance(value, str) and value in self.options
        if self.type == "multi":
            return isinstance(value, (list, tuple)) and all(isinstance(item, str) and (not self.options or item in self.options) for item in value)
        if self.type == "date":
            if not isinstance(value, str):
                return False
            try:
                date.fromisoformat(value)
                return True
            except ValueError:
                return False
        return False


class FieldFinding(Model):
    field: str
    code: str
    detail: str


class FieldManifest(Model):
    connector: str
    entity: str
    project: str | None = None
    issue_type: str | None = None
    fields: tuple[FieldSpec, ...]
    evidence: Literal["authored", "harvested_schema", "measured_aggregate"] = "authored"
    source_digest: str | None = None

    @model_validator(mode="after")
    def _unique(self) -> FieldManifest:
        ids = [field.id for field in self.fields]
        canonical = [field.canonical for field in self.fields if field.canonical]
        if len(ids) != len(set(ids)) or len(canonical) != len(set(canonical)):
            raise ValueError("native field IDs and canonical mappings must be unique within a scope")
        if self.evidence != "authored" and not self.source_digest:
            raise ValueError("harvested metadata requires a source digest")
        return self

    @property
    def key(self) -> str:
        return content_key(self.model_dump(mode="json"))

    def resolve(self, name: str) -> FieldSpec:
        direct = [field for field in self.fields if field.id == name]
        if direct:
            return direct[0]
        found = [field for field in self.fields if name.casefold() in {
            alias.casefold() for alias in (field.name, field.canonical or "", *field.aliases)
        }]
        if len(found) != 1:
            raise ValueError(f"{name}: {'ambiguous' if found else 'unknown'} field in {self.connector}/{self.entity}")
        return found[0]

    def canonicalize(self, native: Mapping[str, Any]) -> dict[str, Any]:
        mapping = {field.id: field.canonical or field.id for field in self.fields}
        output: dict[str, Any] = {}
        for key, value in native.items():
            target = mapping.get(key, key)
            if target in output:
                raise ValueError(f"multiple native values map to {target}")
            output[target] = deepcopy(value)
        return output

    def project_fields(self, native: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
        resolved = [self.resolve(name).id for name in fields]
        if len(resolved) != len(set(resolved)):
            raise ValueError("projection names resolve to duplicate fields")
        missing = set(resolved) - set(native)
        if missing:
            raise ValueError(f"projection fields unavailable in this view: {sorted(missing)}")
        return {name: deepcopy(native[name]) for name in resolved}

    def validate_fields(self, native: Mapping[str, Any], *, mode: Literal["create", "edit", "snapshot"] = "create",
                        existing: Mapping[str, Any] | None = None) -> tuple[FieldFinding, ...]:
        known = {field.id: field for field in self.fields}
        merged = dict(existing or {})
        merged.update(native)
        canonical = self.canonicalize(merged)
        findings: list[FieldFinding] = []
        for key, value in native.items():
            field = known.get(key)
            if field is None:
                findings.append(FieldFinding(field=key, code="unknown_field", detail="field is not in this scoped manifest"))
            elif mode != "snapshot" and mode not in field.screens:
                findings.append(FieldFinding(field=key, code="field_not_on_screen", detail=mode))
            elif not field.valid_value(value):
                findings.append(FieldFinding(field=key, code="invalid_value", detail=field.type))
        for field in self.fields:
            enabled = field.present_when is None or evaluate(field.present_when, canonical)
            value = merged.get(field.id)
            if enabled and field.required_in(self.project, self.issue_type) and value in (None, "", [], ()):
                findings.append(FieldFinding(field=field.id, code="required_field", detail="missing required value"))
            if not enabled and value is not None:
                findings.append(FieldFinding(field=field.id, code="field_dependency", detail="presence condition is false"))
        return tuple(findings)

    def sample(self, canonical: Mapping[str, Any], *, seed: int, record_key: str) -> dict[str, Any]:
        """Populate shape, not truth. Mapped fields require supplied canonical values.

        Only unmapped nuisance fields may be sampled. Field-keyed streams make
        adding a new schema field independent of every existing field's value.
        """
        output: dict[str, Any] = {}
        for field in self.fields:
            rng = Rng(seed).derive(content_key("field-shape/v1", record_key, field.id))
            enabled = field.present_when is None or evaluate(field.present_when, canonical)
            required = field.required_in(self.project, self.issue_type)
            if not enabled or (not required and not rng.chance(field.fill_rate)):
                output[field.id] = None
            elif field.canonical:
                output[field.id] = deepcopy(canonical.get(field.canonical))
            elif field.type == "option":
                output[field.id] = rng.choice(field.options)
            elif field.type == "multi":
                output[field.id] = [rng.choice(field.options)] if field.options else []
            elif field.type == "number":
                output[field.id] = rng.integer(0, 1000)
            elif field.type == "boolean":
                output[field.id] = rng.chance(.5)
            elif field.type == "date":
                output[field.id] = canonical.get(field.id)
            else:
                output[field.id] = f"synthetic-{content_key(record_key, field.id)[:12]}"
        findings = self.validate_fields(output, mode="snapshot")
        if findings:
            raise ValueError("; ".join(f"{finding.field}: {finding.code}" for finding in findings))
        return output


__all__ = ["FieldFinding", "FieldManifest", "FieldSpec"]
