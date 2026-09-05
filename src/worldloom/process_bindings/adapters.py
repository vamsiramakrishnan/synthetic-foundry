"""Use compiled process structure through existing lexicon, brief and tool contracts."""
from __future__ import annotations

import json
from collections.abc import Iterator
from string import Formatter
from typing import Any, Literal

from ..cascade import Brief
from ..connector_data import (
    ConnectorCapability,
    ConnectorDataset,
    ConnectorRecord,
    ConnectorVerb,
)
from ..ids import content_key
from ..lexicon import EvidenceClass, LexiconRecord
from ..models import Model
from ..predicates import Predicate
from ..rng import Rng
from ..tool_surface import ToolSurface
from .models import ActivityBinding, CompiledCatalogue


class ProcessDemand(Model):
    id: str
    binding_id: str
    compilation_digest: str
    template_id: str
    request: str
    status: Literal["bound_structural", "requires_runtime", "binding_unresolved"]
    unresolved_slots: tuple[str, ...]
    answer_from: str
    # Only structural ownership has an oracle here. Counts of other templates
    # are authoring demand counts, not executed or even runnable evaluations.
    expected_json: str | None = None


def dataset(compiled: CompiledCatalogue) -> ConnectorDataset:
    """A read-only structural register. Not Jira incidents or simulated case history."""
    return ConnectorDataset(
        capabilities=[ConnectorCapability(connector="process_catalogue", entity="activity_binding",
            verbs=(ConnectorVerb.SEARCH, ConnectorVerb.READ), stable_id_field="external_id")],
        records=[ConnectorRecord(id=row.id, connector="process_catalogue", entity="activity_binding",
            external_id=row.id, title=row.activity,
            fields={**row.model_dump(mode="json"), "variant": row.variant,
                    "compilation_digest": compiled.digest}) for row in compiled.rows])


def tool_surface(compiled: CompiledCatalogue) -> ToolSurface:
    return ToolSurface(dataset(compiled))


def lexicon_records(compiled: CompiledCatalogue) -> tuple[LexiconRecord, ...]:
    """One activity concept, not one concept per BU/country Cartesian expansion.

    APQC hints never become canonical IDs. Two authored activities can share a
    hint without becoming synonyms for each other.
    """
    unique = {row.activity_id: row for row in compiled.rows}
    count = max(len(unique), 1)
    return tuple(LexiconRecord(
        id=f"{row.source}:{compiled.industry}:activity:{activity_id}", type="activity", label=row.activity,
        canonical=f"{row.source}:{compiled.industry}:activity:{activity_id}",
        industry=compiled.industry, weight=1 / count, source=row.source, license=row.license,
        evidence=EvidenceClass.AUTHORED_PRIOR,
        description=f"{row.stream_name}; APQC hint {row.apqc} is unverified.")
        for activity_id, row in sorted(unique.items()))


def sample_channels(row: ActivityBinding, *, seed: int) -> tuple[str, ...]:
    """Independent presence priors, not a normalized categorical distribution."""
    rng = Rng(seed).derive(f"process-channel/{row.id}")
    return tuple(p.channel for p in sorted(row.channel_priors, key=lambda p: p.channel)
                 if rng.derive(p.channel).chance(p.probability))


def authoring_brief(compiled: CompiledCatalogue, *, stream: str) -> Brief:
    rows = compiled.select(stream=stream)
    if not rows:
        raise ValueError(f"stream has no compiled definition: {stream}")
    return Brief(stage="steps", asks=(
        "Author executable process steps and role slots using these activity bindings. "
        "Use Worldloom's process.accept/resolve validation. Control descriptions are not executable "
        "predicates; APQC hints are not validated IDs; calibration targets are not measurements. "
        "Do not invent missing schemas, policy thresholds or statistical calibration."),
        context={"company":compiled.company, "industry":compiled.industry,
                 "compilation_digest":compiled.digest, "stream":stream,
                 "activities":[row.model_dump(mode="json") for row in rows],
                 "findings":[f.model_dump(mode="json") for f in compiled.findings
                             if f.subject in {stream, *(r.activity_id for r in rows)} or f.code == "authored_source"],
                 "evidence":"authored_prior"})


def demands(compiled: CompiledCatalogue) -> Iterator[ProcessDemand]:
    templates = json.loads(compiled.template_definitions_json)
    for row in compiled.rows:
        slots = {"activity":row.activity, "bu":row.owner_bu, "country":row.country,
                 "function":row.function, "system":row.sor_product, "control":row.control,
                 "exception":row.exception}
        for template in templates:
            required = {field for _, field, _, _ in Formatter().parse(template["text"]) if field}
            unknown = tuple(sorted(required - set(slots)))
            # str.format_map is deliberately not used on source-supplied field
            # expressions: only exact known placeholders are substituted.
            request = template["text"]
            for key, value in slots.items():
                request = request.replace("{" + key + "}", value)
            structural = template["id"] == "ownership" and not unknown
            good_binding = row.owner_resolution == "exact" and row.binding_status == "bound"
            expected: dict[str, Any] | None = None
            if structural and good_binding:
                expected = {"owner_bu":row.owner_bu, "function":row.function,
                            "sor_product":row.sor_product, "country":row.country}
            yield ProcessDemand(
                id="PCD-" + content_key(compiled.digest, row.id, template["id"])[:24].upper(),
                binding_id=row.id, compilation_digest=compiled.digest, template_id=template["id"],
                request=request, status=("bound_structural" if expected is not None else
                                        "binding_unresolved" if structural else "requires_runtime"),
                unresolved_slots=unknown, answer_from=template["answer_from"],
                expected_json=json.dumps(expected, sort_keys=True) if expected is not None else None)


def verify_ownership(compiled: CompiledCatalogue, demand: ProcessDemand) -> bool:
    """Execute the shared search predicate and compare to the structural oracle."""
    if demand.compilation_digest != compiled.digest or demand.status != "bound_structural":
        return False
    # Derive the oracle again, rather than trusting mutable/caller-authored
    # expected_json or a copied success marker.
    rows = compiled.select(id=demand.binding_id)
    if len(rows) != 1:
        return False
    row = rows[0]
    if demand.template_id != "ownership" or row.owner_resolution != "exact" or row.binding_status != "bound":
        return False
    expected = {"owner_bu":row.owner_bu,"function":row.function,"sor_product":row.sor_product,"country":row.country}
    if demand.expected_json is None:
        return False
    try:
        if json.loads(demand.expected_json) != expected:
            return False
    except ValueError:
        return False
    found = tool_surface(compiled).fork().search("process_catalogue", "activity_binding",
        predicate=Predicate.equalities({"external_id":row.id,"compilation_digest":compiled.digest}, entity="activity_binding"))
    return len(found.records) == 1 and all(found.records[0].fields.get(k) == v for k, v in expected.items())
