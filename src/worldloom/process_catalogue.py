"""Industry process structure as deterministic, evidence-labelled data.

The process catalogue is the bridge between a company shape and the operational
objects that should exist in its corpus. It does not generate prose. It binds
value-stream activities to business units, countries, systems of record,
channels, controls, exceptions, and eval-demand templates.

The bundled catalogue is authored from public reference material. Its ``apqc``
values are deliberately marked ``authored_hint`` until the actual licensed PCF
workbooks are ingested. Treating a plausible identifier as a verified taxonomy
edge would be worse than having no identifier at all.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from enum import StrEnum
from importlib.resources import files
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

_DATA_DIR = ("_data", "process-catalogue")
_ACTIVITY_COLUMNS = (
    "id",
    "name",
    "apqc",
    "function",
    "sor_class",
    "type",
    "control",
    "exception",
    "tags",
)


class APQCEvidence(StrEnum):
    """Strength of the APQC relationship carried on an activity."""

    AUTHORED_HINT = "authored_hint"
    VERIFIED = "verified"


class CoverageStatus(StrEnum):
    """How an industry/value-stream cell is grounded."""

    BACKBONE = "backbone"
    OVERLAY = "overlay"
    CORPUS_CALIBRATED = "corpus_calibrated"


class BusinessUnit(BaseModel):
    """A business unit that can own work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    archetype: str = Field(min_length=1)


class CompanyProcessSpec(BaseModel):
    """Inputs that turn the generic catalogue into one company's process estate."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    name: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    operating_model: str = Field(min_length=1)
    countries: tuple[str, ...] = Field(min_length=1)
    business_units: tuple[BusinessUnit, ...] = Field(
        validation_alias=AliasChoices("business_units", "bus"),
        serialization_alias="bus",
        min_length=1,
    )
    landscape: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_units_and_countries(self) -> CompanyProcessSpec:
        unit_names = [unit.name for unit in self.business_units]
        if len(unit_names) != len(set(unit_names)):
            raise ValueError("business unit names must be unique")
        if len(self.countries) != len(set(self.countries)):
            raise ValueError("countries must be unique")
        return self


class ProcessInstance(BaseModel):
    """One activity after company, owner, region and system binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    activity_id: str
    stream: str
    stream_name: str
    activity: str
    apqc: str
    function: str
    owner_kind: str
    owner_bu: str
    bu_archetype: str
    country: str
    sor_class: str
    sor_product: str
    sor_objects: tuple[str, ...] = ()
    type: str
    channels: tuple[str, ...] = ()
    channels_optional: tuple[str, ...] = ()
    control: str
    exception: str
    variant: dict[str, Any] = Field(default_factory=dict)
    eval_templates: tuple[str, ...] = ()
    calibration_sources: tuple[str, ...] = ()
    coverage_status: CoverageStatus = CoverageStatus.BACKBONE
    apqc_evidence: APQCEvidence = APQCEvidence.AUTHORED_HINT

    def source_record(self) -> dict[str, Any]:
        """Return the exact shape emitted by the supplied reference compiler."""
        return self.model_dump(
            mode="json",
            exclude={
                "calibration_sources",
                "coverage_status",
                "apqc_evidence",
            },
        )


class CoverageCell(BaseModel):
    """Coverage for one industry/value-stream pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    industry: str
    stream: str
    status: CoverageStatus
    activities: int = Field(ge=0)


class CompilationSummary(BaseModel):
    """Compact shape of a process compilation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company: str
    industry: str
    operating_model: str
    business_units: int
    countries: int
    distinct_activities: int
    activity_instances: int
    streams: int
    eval_demands: int
    unbound_systems: tuple[str, ...] = ()


class ProcessCompilation(BaseModel):
    """A deterministic compiled process estate and its coverage report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: CompanyProcessSpec
    rows: tuple[ProcessInstance, ...]
    coverage: tuple[CoverageCell, ...]
    summary: CompilationSummary

    def select(
        self,
        *,
        stream: str | None = None,
        activity_id: str | None = None,
        owner_bu: str | None = None,
        country: str | None = None,
        sor_class: str | None = None,
        calibration_source: str | None = None,
    ) -> tuple[ProcessInstance, ...]:
        """Filter the process estate without changing source ordering."""
        return tuple(
            row
            for row in self.rows
            if (stream is None or row.stream == stream)
            and (activity_id is None or row.activity_id == activity_id)
            and (owner_bu is None or row.owner_bu == owner_bu)
            and (country is None or row.country == country)
            and (sor_class is None or row.sor_class == sor_class)
            and (
                calibration_source is None
                or calibration_source in row.calibration_sources
            )
        )

    def demand_seeds(self) -> Iterator[dict[str, Any]]:
        """Yield grounded eval-demand seeds without fabricating unbound slots."""
        templates = _catalogue()["eval_templates"]
        by_id = {template["id"]: template for template in templates}
        for row in self.rows:
            for template_id in row.eval_templates:
                template = by_id[template_id]
                yield {
                    "template_id": template_id,
                    "template": template["text"],
                    "answer_from": template["answer_from"],
                    "difficulty_features": tuple(template["difficulty_features"]),
                    "activity_id": row.activity_id,
                    "activity": row.activity,
                    "stream": row.stream,
                    "owner_bu": row.owner_bu,
                    "country": row.country,
                    "sor_class": row.sor_class,
                    "sor_product": row.sor_product,
                    "sor_objects": row.sor_objects,
                    "channels": row.channels,
                    "control": row.control,
                    "exception": row.exception,
                }


def _resource(*parts: str) -> Any:
    resource = files("worldloom")
    for part in (*_DATA_DIR, *parts):
        resource = resource.joinpath(part)
    return resource


def _catalogue() -> dict[str, Any]:
    payload = json.loads(_resource("catalogue.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("process catalogue must be a JSON object")
    return payload


def catalogue() -> dict[str, Any]:
    """Return a detached copy of the bundled source catalogue."""
    return json.loads(json.dumps(_catalogue()))


def industries() -> tuple[str, ...]:
    """Industries with explicit overlays, in catalogue order."""
    return tuple(_catalogue()["industry_overlays"])


def coverage_matrix() -> tuple[CoverageCell, ...]:
    """Load the supplied all-industry coverage matrix."""
    text = _resource("coverage.csv").read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return tuple(
        CoverageCell(
            industry=row["industry"],
            stream=row["stream"],
            status=CoverageStatus(row["status"]),
            activities=int(row["activities"]),
        )
        for row in reader
    )


def _default_specs() -> dict[str, CompanyProcessSpec]:
    raw: dict[str, dict[str, Any]] = {
        "banking": {"operating_model": "federated", "countries": ["SG", "IN", "HK"], "bus": [{"name": "Consumer Banking", "archetype": "customer_segment"}, {"name": "Institutional Banking", "archetype": "customer_segment"}, {"name": "Wealth", "archetype": "product_line"}, {"name": "Group Finance", "archetype": "group_function"}, {"name": "Global Business Services", "archetype": "shared_service_centre"}]},
        "insurance": {"operating_model": "centralised", "countries": ["AU", "NZ", "SG"], "bus": [{"name": "Personal Lines", "archetype": "product_line"}, {"name": "Commercial Lines", "archetype": "product_line"}, {"name": "Claims", "archetype": "shared_service_centre"}, {"name": "Group Finance", "archetype": "group_function"}]},
        "retail": {"operating_model": "centralised", "countries": ["AU", "NZ"], "bus": [{"name": "Supermarkets", "archetype": "product_line"}, {"name": "Online", "archetype": "channel"}, {"name": "Supply Chain", "archetype": "shared_service_centre"}, {"name": "Group Finance", "archetype": "group_function"}]},
        "consumer_products": {"operating_model": "federated", "countries": ["ID", "TH", "VN", "MY"], "bus": [{"name": "Beverages", "archetype": "product_line"}, {"name": "Snacks", "archetype": "product_line"}, {"name": "APAC Shared Services", "archetype": "shared_service_centre"}]},
        "telecom": {"operating_model": "federated", "countries": ["IN"], "bus": [{"name": "Consumer Mobile", "archetype": "customer_segment"}, {"name": "Enterprise", "archetype": "customer_segment"}, {"name": "Network", "archetype": "shared_service_centre"}, {"name": "Group Finance", "archetype": "group_function"}]},
        "utilities": {"operating_model": "centralised", "countries": ["AU"], "bus": [{"name": "Distribution", "archetype": "product_line"}, {"name": "Retail Energy", "archetype": "customer_segment"}, {"name": "Corporate", "archetype": "group_function"}]},
        "life_sciences": {"operating_model": "federated", "countries": ["SG", "JP", "AU"], "bus": [{"name": "Pharma", "archetype": "product_line"}, {"name": "Devices", "archetype": "product_line"}, {"name": "Global Business Services", "archetype": "shared_service_centre"}]},
        "logistics": {"operating_model": "decentralised", "countries": ["SG", "HK", "MY", "ID"], "bus": [{"name": "Freight Forwarding", "archetype": "product_line"}, {"name": "Contract Logistics", "archetype": "product_line"}, {"name": "Singapore", "archetype": "legal_entity"}]},
        "healthcare": {"operating_model": "centralised", "countries": ["SG"], "bus": [{"name": "Acute Hospitals", "archetype": "product_line"}, {"name": "Primary Care", "archetype": "product_line"}, {"name": "Corporate Services", "archetype": "shared_service_centre"}]},
        "manufacturing": {"operating_model": "decentralised", "countries": ["TW", "CN", "MY"], "bus": [{"name": "Plant Taoyuan", "archetype": "legal_entity"}, {"name": "Plant Penang", "archetype": "legal_entity"}, {"name": "Group", "archetype": "group_function"}]},
        "public_sector": {"operating_model": "centralised", "countries": ["SG"], "bus": [{"name": "Ministry", "archetype": "group_function"}, {"name": "Statutory Board A", "archetype": "legal_entity"}, {"name": "Whole-of-Government Platforms", "archetype": "shared_service_centre"}]},
        "technology_saas": {"operating_model": "decentralised", "countries": ["SG", "AU", "IN", "JP"], "bus": [{"name": "Product & Engineering", "archetype": "group_function"}, {"name": "Customer Success", "archetype": "customer_segment"}, {"name": "APAC Sales", "archetype": "geography"}]},
    }
    return {
        industry: CompanyProcessSpec(
            name=f"default-{industry}",
            industry=industry,
            **spec,
        )
        for industry, spec in raw.items()
    }


def default_spec(industry: str) -> CompanyProcessSpec:
    """Return the validated reference company for one industry."""
    specs = _default_specs()
    try:
        return specs[industry]
    except KeyError as exc:
        raise KeyError(
            f"unknown process industry {industry!r}; known: {tuple(specs)}"
        ) from exc


def _streams_for(cat: Mapping[str, Any], industry: str) -> dict[str, dict[str, Any]]:
    try:
        overlay = cat["industry_overlays"][industry]
    except KeyError as exc:
        raise KeyError(
            f"unknown process industry {industry!r}; known: {tuple(cat['industry_overlays'])}"
        ) from exc

    streams: dict[str, dict[str, Any]] = {}
    for stream_id, stream in cat["value_streams"].items():
        streams[stream_id] = {
            "name": stream["name"],
            "kind": "universal",
            "core": stream_id in overlay["core_streams"],
            "activities": stream["activities"],
            "calibrate": tuple(stream.get("calibrate", ())),
        }
    for stream_id, stream in overlay["specific"].items():
        streams[stream_id] = {
            "name": stream["name"],
            "kind": "industry_specific",
            "core": True,
            "activities": stream["activities"],
            "calibrate": tuple(stream.get("calibrate", ())),
        }
    return streams


def _owner_kind(cat: Mapping[str, Any], model: str, function: str) -> str:
    try:
        rules = cat["operating_models"][model]
    except KeyError as exc:
        raise KeyError(
            f"unknown operating model {model!r}; known: {tuple(cat['operating_models'])}"
        ) from exc
    for kind, families in rules.items():
        if function in families:
            return kind
    return "group_function"


def _bind_owner(kind: str, units: tuple[BusinessUnit, ...]) -> tuple[BusinessUnit, ...]:
    if kind == "BU":
        resolved = tuple(
            unit
            for unit in units
            if unit.archetype
            in {"product_line", "geography", "customer_segment", "channel", "legal_entity"}
        )
        return resolved or units
    if kind == "shared_service":
        resolved = tuple(
            unit for unit in units if unit.archetype == "shared_service_centre"
        )
        if resolved:
            return resolved
        resolved = tuple(unit for unit in units if unit.archetype == "group_function")
        return resolved or units[:1]
    resolved = tuple(unit for unit in units if unit.archetype == "group_function")
    return resolved or units[:1]


def compile_company(spec: CompanyProcessSpec | Mapping[str, Any]) -> ProcessCompilation:
    """Compile one company against the bundled process catalogue."""
    if not isinstance(spec, CompanyProcessSpec):
        spec = CompanyProcessSpec.model_validate(spec)

    cat = _catalogue()
    streams = _streams_for(cat, spec.industry)
    landscape = dict(_default_landscape())
    landscape.update(spec.landscape)

    rows: list[ProcessInstance] = []
    coverage_counts: Counter[tuple[str, str, CoverageStatus]] = Counter()

    for stream_id, stream in streams.items():
        status = (
            CoverageStatus.CORPUS_CALIBRATED
            if stream["calibrate"]
            else (
                CoverageStatus.OVERLAY
                if stream["kind"] == "industry_specific"
                else CoverageStatus.BACKBONE
            )
        )
        for raw_activity in stream["activities"]:
            activity = dict(zip(_ACTIVITY_COLUMNS, raw_activity, strict=True))
            kind = _owner_kind(cat, spec.operating_model, activity["function"])
            owners = _bind_owner(kind, spec.business_units)
            product = landscape.get(activity["sor_class"], "unbound")
            objects = tuple(
                cat["sor_classes"]
                .get(activity["sor_class"], {})
                .get("products", {})
                .get(product, {})
                .keys()
            )
            try:
                channel_prior = cat["channel_priors"][activity["type"]]
            except KeyError as exc:
                raise KeyError(
                    f"activity {activity['id']!r} uses unknown channel type "
                    f"{activity['type']!r}"
                ) from exc

            for owner in owners:
                for country in spec.countries:
                    regional = cat["regional_variants"].get(country, {})
                    variant: dict[str, Any] = {}
                    for tag in activity["tags"]:
                        for key in cat["variant_tags"].get(tag, ()):
                            if key in regional:
                                variant[key] = regional[key]
                    rows.append(
                        ProcessInstance(
                            activity_id=activity["id"],
                            stream=stream_id,
                            stream_name=stream["name"],
                            activity=activity["name"],
                            apqc=activity["apqc"],
                            function=activity["function"],
                            owner_kind=kind,
                            owner_bu=owner.name,
                            bu_archetype=owner.archetype,
                            country=country,
                            sor_class=activity["sor_class"],
                            sor_product=product,
                            sor_objects=objects,
                            type=activity["type"],
                            channels=tuple(
                                channel
                                for channel, probability in channel_prior.items()
                                if probability >= 0.5
                            ),
                            channels_optional=tuple(
                                channel
                                for channel, probability in channel_prior.items()
                                if 0 < probability < 0.5
                            ),
                            control=activity["control"],
                            exception=activity["exception"],
                            variant=variant,
                            eval_templates=tuple(
                                template["id"] for template in cat["eval_templates"]
                            ),
                            calibration_sources=tuple(stream["calibrate"]),
                            coverage_status=status,
                        )
                    )
            coverage_counts[(spec.industry, stream_id, status)] += 1

    coverage = tuple(
        CoverageCell(
            industry=industry,
            stream=stream,
            status=status,
            activities=count,
        )
        for (industry, stream, status), count in coverage_counts.items()
    )
    unbound = tuple(
        sorted({row.sor_class for row in rows if row.sor_product == "unbound"})
    )
    summary = CompilationSummary(
        company=spec.name,
        industry=spec.industry,
        operating_model=spec.operating_model,
        business_units=len(spec.business_units),
        countries=len(spec.countries),
        distinct_activities=len({row.activity_id for row in rows}),
        activity_instances=len(rows),
        streams=len({row.stream for row in rows}),
        eval_demands=sum(len(row.eval_templates) for row in rows),
        unbound_systems=unbound,
    )
    return ProcessCompilation(
        spec=spec,
        rows=tuple(rows),
        coverage=coverage,
        summary=summary,
    )


def load_default(industry: str) -> ProcessCompilation:
    """Load the supplied precompiled default and enrich it from the catalogue."""
    spec = default_spec(industry)
    cat = _catalogue()
    streams = _streams_for(cat, industry)
    coverage_by_stream = {
        cell.stream: cell.status
        for cell in coverage_matrix()
        if cell.industry == industry
    }

    archive = _resource("defaults.zip")
    with archive.open("rb") as handle:
        with zipfile.ZipFile(io.BytesIO(handle.read())) as bundle:
            member = f"default-{industry}.jsonl"
            try:
                payload = bundle.read(member).decode("utf-8")
            except KeyError as exc:
                raise KeyError(
                    f"precompiled default missing {industry!r}"
                ) from exc

    rows: list[ProcessInstance] = []
    for line in payload.splitlines():
        if not line:
            continue
        raw = json.loads(line)
        stream_id = raw["stream"]
        rows.append(
            ProcessInstance.model_validate(
                {
                    **raw,
                    "calibration_sources": streams[stream_id]["calibrate"],
                    "coverage_status": coverage_by_stream[stream_id],
                }
            )
        )
    live = compile_company(spec)
    return ProcessCompilation(
        spec=spec,
        rows=tuple(rows),
        coverage=live.coverage,
        summary=live.summary,
    )


def verify_defaults() -> dict[str, Any]:
    """Prove the source compiler and bundled precompiled defaults still agree."""
    mismatches: list[str] = []
    totals: Counter[str] = Counter()
    for industry in industries():
        live = compile_company(default_spec(industry))
        archived = load_default(industry)
        live_source = tuple(row.source_record() for row in live.rows)
        archived_source = tuple(row.source_record() for row in archived.rows)
        if live_source != archived_source:
            mismatches.append(industry)
        totals["industries"] += 1
        totals["instances"] += len(live.rows)
        totals["eval_demands"] += live.summary.eval_demands

    supplied = {
        (cell.industry, cell.stream): (cell.status, cell.activities)
        for cell in coverage_matrix()
    }
    recomputed = {
        (cell.industry, cell.stream): (cell.status, cell.activities)
        for industry in industries()
        for cell in compile_company(default_spec(industry)).coverage
    }
    coverage_mismatch = supplied != recomputed
    return {
        **dict(totals),
        "coverage_cells": len(supplied),
        "mismatched_industries": tuple(mismatches),
        "coverage_mismatch": coverage_mismatch,
        "ok": not mismatches and not coverage_mismatch,
    }


def _default_landscape() -> dict[str, str]:
    return {
        "ERP-SD": "SAP S/4HANA",
        "ERP-MM": "SAP S/4HANA",
        "ERP-FI": "SAP S/4HANA",
        "CRM": "Salesforce",
        "CPQ": "Salesforce CPQ",
        "ITSM": "ServiceNow",
        "HRIS": "Workday",
        "Payroll": "ADP",
        "P2P-suite": "Coupa",
        "WMS": "Manhattan Active WM",
        "TMS": "SAP TM",
        "PLM": "PTC Windchill",
        "MES": "Siemens Opcenter",
        "EPM": "Anaplan",
        "Consolidation": "OneStream",
        "e-invoicing": "PEPPOL access point",
        "Treasury": "Kyriba",
        "DMS": "SharePoint",
        "Wiki": "Confluence",
        "Email": "Exchange Online",
        "Chat": "Microsoft Teams",
        "BI": "Power BI",
        "CoreBanking": "Temenos T24",
        "PolicyAdmin": "Guidewire PolicyCenter",
        "Claims": "Guidewire ClaimCenter",
        "TelcoBilling": "Amdocs",
        "EMR": "Epic",
        "ADMS": "GE ADMS",
        "Minutes": "Confluence",
        "portal": "PEPPOL access point",
    }


def iter_all_defaults() -> Iterable[ProcessCompilation]:
    """Yield all 12 reference-company compilations in catalogue order."""
    for industry in industries():
        yield load_default(industry)
