"""Factor a source catalogue by company scope, with explicit evidence gaps."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from ..ids import content_key
from .models import (
    Activity,
    ActivityBinding,
    BindingStatus,
    BusinessUnit,
    ChannelPrior,
    CompanySpec,
    CompiledCatalogue,
    CoverageCell,
    Finding,
    OwnerKind,
    OwnerResolution,
    StreamKind,
)

COLS = ("id", "name", "apqc", "function", "sor_class", "type", "control", "exception", "tags")
BU_ARCHETYPES = {"product_line", "geography", "customer_segment", "channel", "legal_entity"}
SOURCE = "user-process-catalogue-0.1"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def resource(name: str) -> Any:
    if name not in {"catalogue.json", "defaults.json", "bindings-provenance.json"}:
        raise ValueError(f"unknown catalogue resource: {name}")
    return json.loads(files("worldloom").joinpath("_data", "process-catalogue", name).read_text(encoding="utf-8"))


def load_catalogue(path: Path | None = None) -> dict[str, Any]:
    value = resource("catalogue.json") if path is None else json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("catalogue must be an object")
    if tuple(value.get("meta", {}).get("columns", {}).get("activity", ())) != COLS:
        raise ValueError("unsupported activity columns")
    required = {"function_families", "operating_models", "sor_classes", "value_streams",
                "industry_overlays", "regional_variants", "variant_tags", "channel_priors", "eval_templates"}
    if required - set(value):
        raise ValueError(f"missing catalogue sections: {sorted(required - set(value))}")
    return value


def default_company(industry: str, *, name: str | None = None) -> CompanySpec:
    orgs = resource("defaults.json")["DEFAULT_ORGS"]
    if industry not in orgs:
        raise ValueError(f"unknown industry {industry!r}; choose from {sorted(orgs)}")
    return CompanySpec(name=name or f"default-{industry}", industry=industry, **orgs[industry])


def _owners(kind: OwnerKind, bus: tuple[BusinessUnit, ...]) -> tuple[tuple[BusinessUnit, ...], OwnerResolution]:
    # Preserve the source compiler's fallbacks, but never call them exact ownership.
    if kind == "BU":
        exact = tuple(b for b in bus if b.archetype in BU_ARCHETYPES)
    elif kind == "shared_service":
        exact = tuple(b for b in bus if b.archetype == "shared_service_centre")
    else:
        exact = tuple(b for b in bus if b.archetype == "group_function")
    if exact:
        return exact, "ambiguous" if kind != "BU" and len(exact) > 1 else "exact"
    if kind == "BU":
        return bus, "fallback"
    if kind == "shared_service":
        group = tuple(b for b in bus if b.archetype == "group_function")
        if group:
            return group, "fallback"
    return bus[:1], "fallback"


def compile_company(spec: CompanySpec | Mapping[str, Any], *, catalogue: dict[str, Any] | None = None,
                    core_only: bool = False, strict: bool = False, max_instances: int = 100_000) -> CompiledCatalogue:
    if not isinstance(spec, CompanySpec):
        spec = CompanySpec.model_validate(dict(spec))
    if isinstance(max_instances, bool) or not isinstance(max_instances, int) or max_instances < 1:
        raise ValueError("max_instances must be a positive integer")
    # Private snapshots prevent caller-owned dictionaries from mutating a compilation.
    cat = json.loads(canonical(catalogue if catalogue is not None else load_catalogue()))
    if tuple(cat["meta"]["columns"]["activity"]) != COLS:
        raise ValueError("unsupported activity columns")
    if spec.industry not in cat["industry_overlays"]:
        raise ValueError(f"unknown industry: {spec.industry}")
    unknown_countries = set(spec.countries) - set(cat["regional_variants"])
    if unknown_countries:
        raise ValueError(f"unknown countries: {sorted(unknown_countries)}")
    defaults = resource("defaults.json")["DEFAULT_LANDSCAPE"]
    unknown_landscape = set(spec.landscape) - set(defaults) - set(cat["sor_classes"])
    if unknown_landscape:
        raise ValueError(f"unknown landscape classes: {sorted(unknown_landscape)}")
    landscape = {**defaults, **spec.landscape}
    overlay = cat["industry_overlays"][spec.industry]
    streams: dict[str, tuple[dict[str, Any], StreamKind]] = {key: (value, "universal") for key, value in cat["value_streams"].items()}
    streams.update({key: (value, "industry_specific") for key, value in overlay["specific"].items()})
    core = set(overlay["core_streams"])
    rules = cat["operating_models"][spec.operating_model]
    owners_by_function: dict[str, OwnerKind] = {}
    for kind, functions in rules.items():
        if kind not in {"BU", "shared_service", "group_function"}:
            raise ValueError(f"unknown owner kind: {kind}")
        for function in functions:
            if function not in cat["function_families"] or function in owners_by_function:
                raise ValueError(f"unknown or multiply owned function: {function}")
            owners_by_function[function] = kind
    template_ids = tuple(sorted(t["id"] for t in cat["eval_templates"]))
    if len(set(template_ids)) != len(template_ids):
        raise ValueError("duplicate eval template id")
    findings: list[Finding] = [Finding(code="authored_source", severity="warning", subject=SOURCE,
        message="APQC hints, channel priors, controls, vendor and regional claims are authored and unverified; license is NOASSERTION.")]
    coverage: list[CoverageCell] = []
    rows: list[ActivityBinding] = []
    seen: set[str] = set()
    for missing in sorted(core - set(streams)):
        findings.append(Finding(code="missing_core_stream", severity="error", subject=missing,
                                message="The industry names this core stream but supplies no definition."))
        coverage.append(CoverageCell(industry=spec.industry, stream=missing, status="missing_definition",
                                     activities=0, activity_instances=0, core=True))
    for sid, (stream, kind) in sorted(streams.items()):
        is_core = sid in core or kind == "industry_specific"
        if core_only and not is_core:
            continue
        targets = tuple(sorted(stream.get("calibrate", ())))
        if targets:
            findings.append(Finding(code="calibration_unresolved", severity="warning", subject=sid,
                message=f"Requested sources {list(targets)} are not fitted priors or proof of calibration."))
        before = len(rows)
        for raw in stream["activities"]:
            if len(raw) != len(COLS):
                raise ValueError(f"{sid}: activity requires {len(COLS)} columns, got {len(raw)}")
            activity = Activity.model_validate(dict(zip(COLS, raw, strict=True)))
            if activity.id in seen:
                raise ValueError(f"duplicate activity id: {activity.id}")
            seen.add(activity.id)
            if activity.function not in owners_by_function:
                raise ValueError(f"{activity.id}: function has no ownership rule: {activity.function}")
            if set(activity.tags) - set(cat["variant_tags"]):
                raise ValueError(f"{activity.id}: unknown variant tags")
            owner_kind = owners_by_function[activity.function]
            owners, resolution = _owners(owner_kind, spec.bus)
            if resolution != "exact":
                findings.append(Finding(code=f"owner_{resolution}", severity="warning" if resolution == "fallback" else "error",
                    subject=activity.id, message=f"{activity.function}: source rule resolves to {resolution} owners."))
            product = landscape.get(activity.sor_class, "unbound")
            products = cat["sor_classes"].get(activity.sor_class, {}).get("products", {})
            objects = tuple(sorted(products.get(product, {})))
            status: BindingStatus = ("unknown_class" if activity.sor_class not in cat["sor_classes"] else
                      "unknown_product" if product not in products else "bound" if objects else "objects_unspecified")
            if status != "bound":
                findings.append(Finding(code=f"sor_{status}", severity="warning" if status == "objects_unspecified" else "error",
                    subject=activity.id, message=f"{activity.sor_class}/{product}: {status}; no object schema was invented."))
            priors = tuple(ChannelPrior(channel=c, probability=p) for c, p in sorted(cat["channel_priors"][activity.type].items()))
            for owner in owners:
                for country in sorted(owner.countries or spec.countries):
                    if len(rows) >= max_instances:
                        raise ValueError(f"activity instance budget exceeded: {max_instances}")
                    rv = cat["regional_variants"][country]
                    variant = {key: rv[key] for tag in activity.tags for key in cat["variant_tags"][tag] if key in rv}
                    rows.append(ActivityBinding(
                        id="PCA-" + content_key("process-catalogue/v1", spec.name, spec.industry, sid, activity.id, owner.name, country)[:24].upper(),
                        company=spec.name, industry=spec.industry, activity_id=activity.id,
                        stream=sid, stream_name=stream["name"], activity=activity.name, apqc=activity.apqc,
                        function=activity.function, owner_kind=owner_kind, owner_bu=owner.name,
                        bu_archetype=owner.archetype, country=country, owner_resolution=resolution,
                        sor_class=activity.sor_class, sor_product=product, sor_objects=objects, binding_status=status,
                        type=activity.type, channels=tuple(p.channel for p in priors if p.probability >= 0.5),
                        channels_optional=tuple(p.channel for p in priors if 0 < p.probability < 0.5),
                        channel_priors=priors, control=activity.control, exception=activity.exception,
                        variant_json=canonical(variant), eval_templates=template_ids, calibration_targets=targets,
                        core=is_core, kind=kind, source=SOURCE))
        coverage.append(CoverageCell(industry=spec.industry, stream=sid,
            status="overlay" if kind == "industry_specific" else "backbone",
            activities=len(stream["activities"]), activity_instances=len(rows) - before, core=is_core,
            calibration_targets=targets, calibration_status="unresolved" if targets else "not_requested"))
    source_digest = fingerprint(cat)
    scope = spec.model_dump(mode="json")
    scope["countries"] = sorted(scope["countries"])
    for bu in scope["bus"]:
        bu["countries"] = sorted(bu["countries"])
    ordered_rows = tuple(sorted(rows, key=lambda r: (r.stream, r.activity_id, r.owner_bu, r.country)))
    compilation = CompiledCatalogue(company=spec.name, industry=spec.industry, core_only=core_only,
        digest=fingerprint({"version":1,"catalogue":source_digest,"spec":scope,"core_only":core_only,"rows":[r.model_dump(mode="json") for r in ordered_rows]}),
        catalogue_digest=source_digest, spec_json=canonical(scope), rows=ordered_rows,
        coverage=tuple(sorted(coverage, key=lambda c: c.stream)),
        findings=tuple(sorted(findings, key=lambda f: (f.code, f.subject, f.message))),
        template_definitions_json=canonical(sorted(cat["eval_templates"], key=lambda t: t["id"])),
        licenses_json=canonical({"source":SOURCE,"catalogue_digest":source_digest,"evidence":"authored_prior",
            "license":"NOASSERTION","attribution":resource("bindings-provenance.json")["attribution"]}))
    if strict:
        compilation.require_ready()
    return compilation
