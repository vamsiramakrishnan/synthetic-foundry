"""Validated authored process factors. Source references are not measurements."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ACTIVITY_COLUMNS = (
    "id", "name", "apqc", "function", "sor_class", "type", "control", "exception", "tags",
)
OwnerKind = Literal["BU", "shared_service", "group_function"]
ActivityKind = Literal["capture", "approve", "execute", "reconcile", "notify", "escalate", "decide", "report"]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Nonempty = Annotated[str, Field(min_length=1, pattern=r"\S")]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Activity(Model):
    id: Nonempty
    name: Nonempty
    apqc: Nonempty
    function: Nonempty
    sor_class: Nonempty
    type: ActivityKind
    control: Nonempty
    exception: Nonempty
    tags: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def positional_row(cls, value: Any) -> Any:
        if isinstance(value, (tuple, list)):
            if len(value) != len(ACTIVITY_COLUMNS):
                raise ValueError("activity must have exactly nine columns; refusing truncated rows")
            return dict(zip(ACTIVITY_COLUMNS, value, strict=True))
        return value


class ValueStream(Model):
    name: Nonempty
    apqc: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    calibrate: tuple[str, ...] = ()
    activities: tuple[Activity, ...] = Field(min_length=1)


class IndustryOverlay(Model):
    pcf: Nonempty
    sector_framework: Nonempty
    core_streams: tuple[str, ...]
    support_streams: Literal["all_universal"]
    specific: dict[str, ValueStream]


class EvalTemplate(Model):
    id: Nonempty
    text: Nonempty
    answer_from: Nonempty
    difficulty_features: tuple[str, ...]


class Catalogue(Model):
    meta: dict[str, Any]
    function_families: dict[str, str]
    bu_archetypes: tuple[str, ...]
    operating_models: dict[str, dict[OwnerKind, tuple[str, ...]]]
    channel_types: tuple[str, ...]
    channel_priors: dict[ActivityKind, dict[str, Probability]]
    sor_classes: dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]]
    value_streams: dict[str, ValueStream]
    industry_overlays: dict[str, IndustryOverlay]
    industry_crosswalk: dict[str, str]
    regional_variants: dict[str, dict[str, str | list[str]]]
    variant_tags: dict[str, tuple[str, ...]]
    eval_templates: tuple[EvalTemplate, ...]

    @model_validator(mode="after")
    def integrity(self) -> Catalogue:
        if self.meta.get("authored") is not True:
            raise ValueError("this compiler accepts authored catalogues, not unverified measured claims")
        if tuple(self.meta.get("columns", {}).get("activity", ())) != ACTIVITY_COLUMNS:
            raise ValueError("activity column declaration does not match the supported schema")
        if not self.industry_overlays or not self.regional_variants:
            raise ValueError("catalogue needs at least one industry and region")
        functions = set(self.function_families)
        for name, rules in self.operating_models.items():
            counts = Counter(f for members in rules.values() for f in members)
            if set(counts) != functions or any(v != 1 for v in counts.values()):
                raise ValueError(f"operating model {name}: every function must have exactly one owner rule")
        for kind, prior in self.channel_priors.items():
            if not prior or set(prior) - set(self.channel_types):
                raise ValueError(f"unknown or empty channel prior: {kind}")
        if len({t.id for t in self.eval_templates}) != len(self.eval_templates):
            raise ValueError("duplicate evaluation template id")
        for code, industry in self.industry_crosswalk.items():
            if industry not in self.industry_overlays:
                raise ValueError(f"crosswalk {code}: unknown industry {industry}")
        for industry, overlay in self.industry_overlays.items():
            seen: set[str] = set()
            for stream in {**self.value_streams, **overlay.specific}.values():
                for activity in stream.activities:
                    if activity.id in seen:
                        raise ValueError(f"duplicate activity id {industry}:{activity.id}")
                    seen.add(activity.id)
                    if activity.function not in functions:
                        raise ValueError(f"{activity.id}: unknown function {activity.function}")
                    if activity.type not in self.channel_priors:
                        raise ValueError(f"{activity.id}: missing channel prior")
                    if set(activity.tags) - set(self.variant_tags):
                        raise ValueError(f"{activity.id}: unknown variant tags")
        return self

    @property
    def fingerprint(self) -> str:
        body = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class Unit(Model):
    name: Nonempty
    archetype: Nonempty
    # None inherits the company footprint. Explicit scopes stop Plant Penang
    # appearing in every other country merely because the group operates there.
    countries: tuple[str, ...] | None = Field(default=None, min_length=1)


class CompanyProcessSpec(Model):
    name: Nonempty
    industry: Nonempty
    operating_model: Nonempty
    countries: tuple[str, ...] = Field(min_length=1)
    bus: tuple[Unit, ...] = Field(min_length=1)
    landscape: dict[str, Nonempty] = Field(default_factory=dict)
    seed: int = 8128
    streams: tuple[str, ...] | None = Field(default=None, min_length=1)
    # Owner overrides are explicit resolutions, not undocumented fallback rules.
    owner_overrides: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_keys(self) -> CompanyProcessSpec:
        if len(set(self.countries)) != len(self.countries):
            raise ValueError("duplicate company countries")
        if len({bu.name for bu in self.bus}) != len(self.bus):
            raise ValueError("duplicate business-unit names")
        if self.streams is not None and len(set(self.streams)) != len(self.streams):
            raise ValueError("duplicate requested streams")
        for unit in self.bus:
            if unit.countries is not None:
                if len(set(unit.countries)) != len(unit.countries):
                    raise ValueError(f"duplicate countries for {unit.name}")
                if set(unit.countries) - set(self.countries):
                    raise ValueError(f"{unit.name}: country scope outside company footprint")
        for function, names in self.owner_overrides.items():
            if not names or len(set(names)) != len(names):
                raise ValueError(f"{function}: owner override must contain distinct units")
            if set(names) - {bu.name for bu in self.bus}:
                raise ValueError(f"{function}: owner override names an unknown unit")
        return self


class Diagnostic(Model):
    code: str
    severity: Literal["warning", "error"]
    location: str
    message: str


class ActivityInstance(Model):
    id: str
    activity_id: str
    industry: str
    stream: str
    stream_name: str
    stream_kind: Literal["backbone", "overlay"]
    core: bool
    ordinal: int
    activity: str
    apqc_hint: str
    apqc_verified: Literal[False] = False
    evidence: Literal["authored_prior"] = "authored_prior"
    function: str
    owner_kind: OwnerKind
    owner_bu: str
    owner_binding: Literal["rule", "override", "fallback"]
    bu_archetype: str
    country: str
    sor_class: str
    sor_product: str
    sor_schema_class: str | None
    sor_binding: Literal["bound", "aliased", "unregistered_product", "unresolved_schema"]
    # These are distinct namespaces. Knowing Salesforce objects does not prove
    # that a particular process uses all of them.
    process_objects: tuple[str, ...]
    sor_objects: dict[str, dict[str, str]]
    type: ActivityKind
    channel_probabilities: dict[str, Probability]
    channels: tuple[str, ...]
    control: str
    control_evaluable: Literal[False] = False
    exception: str
    tags: tuple[str, ...]
    variant: dict[str, str | list[str]]
    regional_evidence: Literal["authored_unverified"] = "authored_unverified"
    calibration_requested: tuple[str, ...]
    calibration_applied: tuple[str, ...] = Field(default=(), max_length=0)
    eval_templates: tuple[str, ...]


class CoverageCell(Model):
    industry: str
    stream: str
    status: Literal["authored_backbone", "authored_overlay", "missing"]
    core: bool
    activities: int
    activity_instances: int
    calibration_requested: tuple[str, ...]
    calibration_applied: tuple[str, ...] = Field(default=(), max_length=0)


class Compilation(Model):
    schema_version: Literal["1"] = "1"
    company: CompanyProcessSpec
    catalogue_sha256: str
    catalogue_json: str
    selection: Literal["all", "core", "explicit"]
    activities: tuple[ActivityInstance, ...]
    coverage: tuple[CoverageCell, ...]
    diagnostics: tuple[Diagnostic, ...]
    templates: tuple[EvalTemplate, ...]
    source_note: str

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "company": self.company.name,
            "industry": self.company.industry,
            "distinct_activities": len({a.activity_id for a in self.activities}),
            "activity_instances": len(self.activities),
            "streams": len({a.stream for a in self.activities}),
            "missing_streams": [c.stream for c in self.coverage if c.status == "missing"],
            "candidate_template_pairs": sum(len(a.eval_templates) for a in self.activities),
            "executable_evals": 0,
            "calibrated_streams": sum(bool(c.calibration_applied) for c in self.coverage),
            "diagnostics": len(self.diagnostics),
        }

    def raise_for_errors(self) -> None:
        errors = [f"{d.code} at {d.location}: {d.message}" for d in self.diagnostics if d.severity == "error"]
        if errors:
            raise ValueError("process catalogue is incomplete:\n" + "\n".join(errors))
