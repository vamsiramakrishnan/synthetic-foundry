"""Company-specific planning; deliberately not an event-log simulator."""
from __future__ import annotations

import gzip
import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from ..ids import content_key
from ..rng import Rng
from .models import (
    ActivityInstance,
    Catalogue,
    CompanyProcessSpec,
    Compilation,
    CoverageCell,
    Diagnostic,
    OwnerKind,
    Unit,
)


def _resource(name: str) -> dict[str, Any]:
    value = json.loads(gzip.decompress(files("worldloom").joinpath("_data", "processes", name).read_bytes()))
    if not isinstance(value, dict):
        raise ValueError(f"{name}: expected an object")
    return value


def load_catalogue(path: str | Path | None = None) -> Catalogue:
    """Read the bundled authored catalogue or a replacement; never fetch a URL."""
    if path is None:
        return Catalogue.model_validate(_resource("catalogue.json.gz"))
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return Catalogue.model_validate_json(raw)


def default_company(industry: str, *, seed: int = 8128) -> CompanyProcessSpec:
    defaults = _resource("defaults.json.gz")
    if industry not in defaults["orgs"]:
        raise ValueError(f"unknown default industry {industry!r}")
    return CompanyProcessSpec.model_validate({
        "name": f"default-{industry}", "industry": industry, "seed": seed, **defaults["orgs"][industry],
    })


def _owners(kind: OwnerKind, units: tuple[Unit, ...]) -> tuple[tuple[Unit, ...], bool]:
    if kind == "BU":
        preferred = tuple(b for b in units if b.archetype in (
            "product_line", "geography", "customer_segment", "channel", "legal_entity",
        ))
        return (preferred, False) if preferred else (units, True)
    wanted = "shared_service_centre" if kind == "shared_service" else "group_function"
    preferred = tuple(b for b in units if b.archetype == wanted)
    if preferred:
        return preferred, False
    fallback = tuple(b for b in units if b.archetype == "group_function") if kind == "shared_service" else ()
    # Input order is meaningful only for this documented legacy fallback. It is
    # not a hidden random draw, and every affected row says "fallback".
    return fallback or units[:1], True


def compile_company(
    spec: CompanyProcessSpec | dict[str, Any],
    catalogue: Catalogue | None = None,
    *,
    core_only: bool = False,
    strict: bool = False,
    max_instances: int = 100_000,
) -> Compilation:
    """Bind authored activities to units, countries, systems and channel draws.

    Default stream selection reproduces the supplied all-universal policy.
    ``strict`` refuses missing core streams and unresolved product/schema binds.
    A corpus name in ``calibrate`` remains a request, never a calibrated claim.
    """
    cat = Catalogue.model_validate((catalogue if catalogue is not None else load_catalogue()).model_dump(mode="json"))
    company: CompanyProcessSpec = CompanyProcessSpec.model_validate(
        spec.model_dump(mode="json") if isinstance(spec, CompanyProcessSpec) else spec
    )
    if max_instances < 1:
        raise ValueError("max_instances must be positive")
    if company.industry not in cat.industry_overlays:
        raise ValueError(f"unknown industry {company.industry!r}")
    if company.operating_model not in cat.operating_models:
        raise ValueError(f"unknown operating model {company.operating_model!r}")
    if set(company.countries) - set(cat.regional_variants):
        raise ValueError("unknown country in company footprint")
    if any(b.archetype not in cat.bu_archetypes for b in company.bus):
        raise ValueError("unknown business-unit archetype")
    if set(company.owner_overrides) - set(cat.function_families):
        raise ValueError("owner override references unknown function")
    if core_only and company.streams is not None:
        raise ValueError("choose explicit streams or core_only, not both")

    overlay = cat.industry_overlays[company.industry]
    streams = {**cat.value_streams, **overlay.specific}
    if company.streams is not None:
        if set(company.streams) - set(streams):
            raise ValueError("unknown explicit stream; cross-industry borrowing is not implicit")
        selected = sorted(company.streams)
    elif core_only:
        selected = sorted(set(overlay.core_streams))
    else:
        selected = sorted(set(streams) | set(overlay.core_streams))
    defaults = _resource("defaults.json.gz")
    landscape = {**defaults["landscape"], **company.landscape}
    rules = cat.operating_models[company.operating_model]
    kinds: dict[str, OwnerKind] = {f: k for k, functions in rules.items() for f in functions}
    rows: list[ActivityInstance] = []
    coverage: list[CoverageCell] = []
    findings: dict[tuple[str, str], Diagnostic] = {}
    rng = Rng(company.seed).derive("process-catalogue/channels/v1")

    def report(code: str, location: str, message: str, *, error: bool = False) -> None:
        findings[(code, location)] = Diagnostic(
            code=code, location=location, message=message, severity="error" if error else "warning",
        )

    for sid in selected:
        core = sid in overlay.core_streams
        if sid not in streams:
            report("missing_core_stream", sid, "The overlay names this stream but supplies no definition.", error=True)
            coverage.append(CoverageCell(industry=company.industry, stream=sid, status="missing", core=core,
                                         activities=0, activity_instances=0, calibration_requested=()))
            continue
        stream = streams[sid]
        stream_kind: Literal["overlay", "backbone"] = "overlay" if sid in overlay.specific else "backbone"
        start_count = len(rows)
        for ordinal, activity in enumerate(stream.activities):
            kind = kinds[activity.function]
            product = landscape.get(activity.sor_class, "unbound")
            schema_class = activity.sor_class if activity.sor_class in cat.sor_classes else None
            aliased = activity.sor_class == "Minutes" and schema_class is None
            if aliased:
                schema_class = "Wiki"
                report("explicit_schema_alias", activity.id, "Minutes uses the Wiki product schema; original class is retained.")
            products = cat.sor_classes.get(schema_class or "", {}).get("products", {})
            binding: Any = "aliased" if aliased else "bound"
            if schema_class is None:
                binding = "unresolved_schema"
                report("unresolved_system_schema", activity.id, f"No schema for {activity.sor_class}; product {product!r} is unverified.", error=True)
            elif product not in products:
                binding = "unregistered_product"
                report("unregistered_product", activity.id, f"{product!r} is not registered for {schema_class}.", error=True)
            objects = products.get(product, {})
            if schema_class is not None and product in products and not objects:
                report("missing_object_schema", activity.id, f"{product} has no declared object metadata.")
            prior = dict(sorted(cat.channel_priors[activity.type].items()))
            for country in sorted(company.countries):
                available = tuple(b for b in company.bus if b.countries is None or country in b.countries)
                override = company.owner_overrides.get(activity.function)
                if override is not None:
                    owners = tuple(b for b in available if b.name in override)
                    fallback = False
                else:
                    owners, fallback = _owners(kind, available)
                if not owners:
                    report("unbound_owner", f"{activity.id}/{country}", "No eligible owner in this country.", error=True)
                if fallback:
                    report("owner_fallback", f"{activity.id}/{country}", f"No {kind} owner; fallback to {[b.name for b in owners]}.")
                regional = cat.regional_variants[country]
                keys = sorted({key for tag in activity.tags for key in cat.variant_tags[tag]})
                variant = {key: regional[key] for key in keys if key in regional}
                for bu in sorted(owners, key=lambda b: b.name):
                    if len(rows) >= max_instances:
                        raise ValueError(f"activity instance budget exceeded ({max_instances}); narrow countries, units or streams")
                    identity = json.dumps([company.name, company.industry, sid, activity.id, bu.name, country], ensure_ascii=False)
                    identifier = "PROC-" + content_key("process-instance/v1", identity).upper()
                    channels = tuple(c for c, p in prior.items() if rng.derive(identifier).derive(c).chance(p))
                    rows.append(ActivityInstance(
                        id=identifier, activity_id=activity.id, industry=company.industry,
                        stream=sid, stream_name=stream.name, stream_kind=stream_kind, core=core, ordinal=ordinal,
                        activity=activity.name, apqc_hint=activity.apqc, function=activity.function,
                        owner_kind=kind, owner_bu=bu.name, owner_binding="override" if override is not None else "fallback" if fallback else "rule",
                        bu_archetype=bu.archetype, country=country, sor_class=activity.sor_class,
                        sor_product=product, sor_schema_class=schema_class, sor_binding=binding,
                        process_objects=stream.objects, sor_objects=objects, type=activity.type,
                        channel_probabilities=prior, channels=channels, control=activity.control,
                        exception=activity.exception, tags=activity.tags, variant=variant,
                        calibration_requested=tuple(sorted(set(stream.calibrate))),
                        eval_templates=tuple(t.id for t in cat.eval_templates),
                    ))
        coverage.append(CoverageCell(
            industry=company.industry, stream=sid, status="authored_overlay" if stream_kind == "overlay" else "authored_backbone", core=core,
            activities=len(stream.activities), activity_instances=len(rows) - start_count,
            calibration_requested=tuple(sorted(set(stream.calibrate))),
        ))
    result = Compilation(
        company=company.model_copy(update={"landscape": landscape}), catalogue_sha256=cat.fingerprint,
        catalogue_json=json.dumps(cat.model_dump(mode="json"), sort_keys=True, ensure_ascii=False),
        selection="explicit" if company.streams is not None else "core" if core_only else "all",
        activities=tuple(rows), coverage=tuple(coverage),
        diagnostics=tuple(findings[k] for k in sorted(findings)), templates=cat.eval_templates,
        source_note=str(cat.meta.get("note", "")),
    )
    if strict:
        result.raise_for_errors()
    return result


def authoring_context(compilation: Compilation, stream: str, *, max_instances: int = 1000) -> dict[str, Any]:
    """Bounded stream-specific context for the existing process authoring cascade.

    This exposes intent, not an invented linear execution trace. Controls remain
    text until a harness proposes evaluable guards and the existing lint accepts.
    """
    rows = [r for r in compilation.activities if r.stream == stream]
    if not rows:
        raise ValueError(f"stream {stream!r} has no bound activity instances")
    if max_instances < 1 or len(rows) > max_instances:
        raise ValueError("authoring context budget exceeded; narrow the company spec before opening a session")
    groups: dict[str, list[ActivityInstance]] = {}
    for row in rows:
        groups.setdefault(row.activity_id, []).append(row)
    activities = []
    for _, group in sorted(groups.items(), key=lambda item: (item[1][0].ordinal, item[0])):
        exemplar = group[0]
        activities.append({
            "activity_id": exemplar.activity_id, "name": exemplar.activity,
            "apqc_hint": exemplar.apqc_hint, "apqc_verified": False,
            "function": exemplar.function, "type": exemplar.type,
            "control": exemplar.control, "control_evaluable": False, "exception": exemplar.exception,
            "process_objects": exemplar.process_objects,
            "bindings": [{"instance_id": r.id, "owner": r.owner_bu, "owner_binding": r.owner_binding,
                          "country": r.country, "sor_class": r.sor_class, "sor_product": r.sor_product,
                          "sor_binding": r.sor_binding, "sor_objects": r.sor_objects,
                          "channels": r.channels, "channel_probabilities": r.channel_probabilities,
                          "regional_variants": r.variant, "regional_evidence": r.regional_evidence}
                         for r in group],
            "calibration_requested": exemplar.calibration_requested, "calibration_applied": (),
        })
    return {
        "company": compilation.company.name, "industry": compilation.company.industry,
        "operating_model": compilation.company.operating_model, "stream": stream,
        "catalogue_sha256": compilation.catalogue_sha256, "evidence": "authored_prior",
        "activities": activities, "eval_templates": [t.model_dump(mode="json") for t in compilation.templates],
        "boundaries": [
            "Activity order is an authored outline, not an observed transition graph.",
            "Corpus names request calibration; no calibration has been applied.",
            "Regional labels and APQC hints are unverified source text, not legal or taxonomy validation.",
            "Templates are authoring demands, not executable evaluations with reference proofs.",
        ],
    }
