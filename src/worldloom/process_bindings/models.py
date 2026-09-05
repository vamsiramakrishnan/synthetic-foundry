"""Closed contracts for authored process structure, never simulated transactions."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field, model_validator

from ..models import Model

OwnerKind = Literal["BU", "shared_service", "group_function"]
OwnerResolution = Literal["exact", "fallback", "ambiguous"]
BindingStatus = Literal["bound", "objects_unspecified", "unknown_class", "unknown_product"]
StreamKind = Literal["universal", "industry_specific"]
Archetype = Literal["product_line", "geography", "customer_segment", "channel", "shared_service_centre", "legal_entity", "group_function"]


class BusinessUnit(Model):
    name: str = Field(min_length=1)
    archetype: Archetype
    countries: tuple[str, ...] = ()


class CompanySpec(Model):
    name: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    operating_model: Literal["centralised", "federated", "decentralised"]
    countries: tuple[str, ...] = Field(min_length=1)
    bus: tuple[BusinessUnit, ...] = Field(min_length=1)
    landscape: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_scope(self) -> CompanySpec:
        if len(set(self.countries)) != len(self.countries):
            raise ValueError("duplicate country")
        names = [bu.name for bu in self.bus]
        if len(set(names)) != len(names):
            raise ValueError("duplicate business-unit name")
        for bu in self.bus:
            if len(set(bu.countries)) != len(bu.countries):
                raise ValueError(f"{bu.name}: duplicate country")
            if set(bu.countries) - set(self.countries):
                raise ValueError(f"{bu.name}: country outside company footprint")
        return self


class Activity(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    apqc: str
    function: str
    sor_class: str
    type: Literal["capture", "approve", "execute", "reconcile", "notify", "escalate", "decide", "report"]
    control: str
    exception: str
    tags: tuple[str, ...]


class ChannelPrior(Model):
    channel: str
    probability: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class Finding(Model):
    code: str
    severity: Literal["warning", "error"]
    subject: str
    message: str


class ActivityBinding(Model):
    id: str
    company: str
    industry: str
    activity_id: str
    stream: str
    stream_name: str
    activity: str
    apqc: str
    pcf_status: Literal["unverified_hint"] = "unverified_hint"
    function: str
    owner_kind: OwnerKind
    owner_bu: str
    bu_archetype: Archetype
    country: str
    owner_resolution: OwnerResolution
    sor_class: str
    sor_product: str
    sor_objects: tuple[str, ...]
    binding_status: BindingStatus
    type: str
    channels: tuple[str, ...]
    channels_optional: tuple[str, ...]
    channel_priors: tuple[ChannelPrior, ...]
    control: str
    exception: str
    variant_json: str
    eval_templates: tuple[str, ...]
    calibration_targets: tuple[str, ...]
    core: bool
    kind: StreamKind
    source: str
    license: str = "NOASSERTION"
    evidence: Literal["authored_prior"] = "authored_prior"

    @property
    def variant(self) -> dict[str, Any]:
        return json.loads(self.variant_json)

    def legacy_record(self) -> dict[str, Any]:
        """Comparable to the upload, without promoting its evidence claims."""
        names = ("activity_id", "stream", "stream_name", "activity", "apqc", "function",
                 "owner_kind", "owner_bu", "bu_archetype", "country", "sor_class",
                 "sor_product", "sor_objects", "type", "channels", "channels_optional",
                 "control", "exception", "eval_templates")
        payload = self.model_dump(mode="json")
        result = {name: payload[name] for name in names}
        result["variant"] = self.variant
        return result


class CoverageCell(Model):
    industry: str
    stream: str
    status: Literal["backbone", "overlay", "missing_definition"]
    activities: int = Field(ge=0)
    activity_instances: int = Field(ge=0)
    core: bool
    calibration_targets: tuple[str, ...] = ()
    calibration_status: Literal["not_requested", "unresolved"] = "not_requested"


class CompiledCatalogue(Model):
    schema_version: Literal["worldloom.process-catalogue/v1"] = "worldloom.process-catalogue/v1"
    company: str
    industry: str
    core_only: bool = False
    digest: str
    catalogue_digest: str
    spec_json: str
    rows: tuple[ActivityBinding, ...]
    coverage: tuple[CoverageCell, ...]
    findings: tuple[Finding, ...]
    template_definitions_json: str
    licenses_json: str

    @property
    def ready(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    def require_ready(self) -> None:
        if not self.ready:
            errors = "; ".join(f"{f.code}: {f.subject}" for f in self.findings if f.severity == "error")
            raise ValueError(errors)

    def select(self, **criteria: str | int | bool) -> tuple[ActivityBinding, ...]:
        from ..predicates import Predicate, evaluate
        unknown = set(criteria) - set(ActivityBinding.model_fields)
        if unknown:
            raise ValueError(f"unknown activity-binding fields: {sorted(unknown)}")
        predicate = Predicate.equalities(criteria, entity="activity_binding")
        return tuple(row for row in self.rows if evaluate(predicate, row.model_dump(mode="json"), entity="activity_binding"))
