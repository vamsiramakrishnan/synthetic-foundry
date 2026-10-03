"""Project byte-verified native measures into the existing connector evaluator.

The representation is extracted content. This adapter proves which source
bytes support a connector value; it does not claim the target downloaded or
parsed a binary file, or that an attached generated image is qualified truth.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from ..connector_data import ConnectorRecord
from ..ids import content_key
from ..models import Authority, CanonicalFact, Model
from ..native_corpus import NativeCorpusResult
from ..native_query_evidence import SourceEvidenceIndex
from ..native_query_planning import NativeFormat, NativeWorkloadPlan, _inventory
from ..native_tasks import MAX_FILE_BYTES

if TYPE_CHECKING:
    from ..world import World

_VERSION: Literal["worldloom.native-connector-sources/v1"] = "worldloom.native-connector-sources/v1"
_RESERVED = frozenset({
    "id", "name", "title", "content", "representation", "measure_kind", "unit",
    "source_sha256", "source_format", "source_size_bytes", "source_locator", "source_family",
    "fact_ids", "event_ids", "source_artifact_ids", "total", "source_count", "evidence",
})


class NativeConnectorProjection(Model):
    """One explicitly selected measure; no prefix matching or implicit totals.

    Values retain their declared unit. Authority comes from the authored file
    by default; a caller can explicitly project the selected fact's authority.
    Scope includes measure and unit so two projections cannot silently mix
    financial units or line measures in one reconciliation cohort.
    """

    measure_kind: str = Field(min_length=1, max_length=250)
    unit: str = Field(min_length=1, max_length=80)
    connector: str = Field(default="sharepoint", min_length=1)
    format: NativeFormat = "xlsx"
    scope: Literal["company", "subject"] = "company"
    authority_source: Literal["artifact", "fact"] = "artifact"
    value_field: str = Field(default="amount", pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    scope_field: str = Field(default="scope", pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    period_field: str = Field(default="period", pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    authority_field: str = Field(default="authority", pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    max_files: int = Field(default=1024, ge=1, le=4096, strict=True)
    max_content_bytes: int = Field(default=8 * 1024 * 1024, ge=1, le=64 * 1024 * 1024, strict=True)

    @model_validator(mode="after")
    def _distinct_fields(self) -> NativeConnectorProjection:
        fields = (self.value_field, self.scope_field, self.period_field, self.authority_field)
        if len(set(fields)) != len(fields) or set(fields) & _RESERVED:
            raise ValueError("projection fields must be distinct and cannot shadow native provenance or output fields")
        return self


class NativeConnectorBinding(Model):
    """Private qualification metadata; do not hand this record to a target."""

    record_id: str
    artifact_id: str
    source_sha256: str
    locator: str
    selected_fact_id: str
    fact_ids: tuple[str, ...]
    source_artifact_ids: tuple[str, ...]
    family_id: str


class NativeConnectorSources(Model):
    schema_version: Literal["worldloom.native-connector-sources/v1"] = _VERSION
    representation: Literal["extracted_content"] = "extracted_content"
    config: NativeConnectorProjection
    records: tuple[ConnectorRecord, ...]
    bindings: tuple[NativeConnectorBinding, ...]
    deduplicated_artifact_ids: tuple[str, ...] = ()
    excluded_formats: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Projection:
    native: NativeCorpusResult
    fact: CanonicalFact
    locator: str
    value: Decimal
    units: dict[str, str]
    fact_ids: tuple[str, ...]
    source_artifact_ids: tuple[str, ...]
    scope: str
    authority: str


def _families(candidates: Sequence[_Projection], company_id: str) -> dict[str, str]:
    """Keep every connected canonical ancestry component in one split family."""
    parents = list(range(len(candidates)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    seen: dict[str, int] = {}
    for index, candidate in enumerate(candidates):
        for fact_id in candidate.fact_ids:
            if fact_id in seen:
                parents[root(index)] = root(seen[fact_id])
            else:
                seen[fact_id] = index
    groups: dict[int, set[str]] = {}
    for index, candidate in enumerate(candidates):
        groups.setdefault(root(index), set()).update(candidate.fact_ids)
    return {
        candidate.native.manifest.artifact_id: content_key(_VERSION, "family", company_id, *sorted(groups[root(index)]))
        for index, candidate in enumerate(candidates)
    }


def project_native_sources(
    world: World,
    rendered: Sequence[NativeCorpusResult],
    config: NativeConnectorProjection,
) -> NativeConnectorSources:
    """Expose one unambiguous byte-qualified canonical measure per source file.

    Matching is exact on kind and unit. Same-fact replicas are deduplicated
    within an authority cohort; overlapping derived values are refused rather
    than counted as independent contributions. Historical files retain their
    actual artifact authority. Explicitly superseded numeric facts are refused.
    """
    config = NativeConnectorProjection.model_validate(config.model_dump(mode="json"))
    materialized = tuple(rendered)
    if not materialized or len(materialized) > config.max_files:
        raise ValueError("native projection requires a nonempty source set within max_files")
    if len({item.manifest.artifact_id for item in materialized}) != len(materialized):
        raise ValueError("native projection artifact IDs must be unique")
    selected = tuple(sorted((item for item in materialized if item.manifest.format == config.format),
                            key=lambda item: item.manifest.artifact_id))
    if not selected:
        raise ValueError(f"native projection has no {config.format} sources")
    if any(len(item.payload) > MAX_FILE_BYTES for item in selected):
        raise ValueError("native projection source exceeds the native file byte budget")
    # The same byte/provenance/IR validators used by native task planning own
    # this admission boundary; checking a supplied digest alone is insufficient.
    sources, _, numeric, _ = _inventory(world, {item.manifest.artifact_id: item for item in selected},
        NativeWorkloadPlan(use_case_id="native-connector-projection", objective="Validate native connector source values.",
                           formats=(config.format,), operations=("read",), max_tasks=1))
    source_by_id = {source.input.artifact_id: source for source in sources}
    index = SourceEvidenceIndex(world)
    names = world.entity_names()
    superseded = {fact.supersedes for fact in world.facts if fact.supersedes is not None}
    candidates: list[_Projection] = []
    for native in selected:
        artifact_id = native.manifest.artifact_id
        source = source_by_id[artifact_id]
        matching = [index.facts[fact_id] for fact_id in sorted(source.fact_ids)
                    if index.facts[fact_id].kind == config.measure_kind]
        if not matching:
            raise ValueError(f"native source {artifact_id} has no grounded measure {config.measure_kind!r}")
        if any(fact.value is None or fact.value.unit != config.unit for fact in matching):
            raise ValueError(f"native source {artifact_id} measure has the wrong unit; expected {config.unit!r}")
        if len(matching) != 1:
            raise ValueError(f"native source {artifact_id} has ambiguous matching canonical values")
        fact = matching[0]
        if fact.id in superseded or fact.valid_to is not None or fact.tx_to is not None:
            raise ValueError(f"native source {artifact_id} selects a superseded or expired numeric fact")
        if not fact.period:
            raise ValueError(f"native source {artifact_id} measure has no reporting period")
        eligible = [(item.ref.locator, item.value) for item in numeric
                    if item.source.input.artifact_id == artifact_id and item.fact.id == fact.id]
        # XLSX totals are authored formulas, not numeric text. The shared
        # inventory already verified their native expressions, dependency
        # locators and canonical arithmetic graph. Expose that proved result,
        # never an unchecked workbook cached value or a fact merely in closure.
        for entry in native.manifest.evidence:
            if entry.table_key is None or entry.row_key is None or entry.column_key is None:
                continue
            table = index.artifacts[entry.source_artifact_id].sections[entry.section_index].table
            assert table is not None
            cell = next(row for row in table.rows if row.key == entry.row_key).cells[entry.column_key]
            if cell.fact_id == fact.id and isinstance(entry.value, (int, float)):
                eligible.append((entry.locator, Decimal(str(entry.value))))
        eligible.sort(key=lambda item: item[0])
        if not eligible:
            raise ValueError(f"native source {artifact_id} matching measure lacks a byte-qualified numeric value")
        value = eligible[0][1]
        if not value.is_finite() or any(item[1] != value for item in eligible):
            raise ValueError(f"native source {artifact_id} has inconsistent matching native values")
        provenance = tuple(sorted({item.source_artifact_id for item in native.manifest.evidence}))
        if config.authority_source == "fact":
            authority = fact.authority.value
        else:
            authorities = {index.artifacts[identifier].metadata.get("authority") for identifier in provenance}
            if len(authorities) != 1 or None in authorities:
                raise ValueError(f"native source {artifact_id} requires one declared authored artifact authority")
            declared = next(iter(authorities))
            assert declared is not None
            authority = Authority(declared).value
        subject = world.company.name if config.scope == "company" else names.get(fact.subject)
        if not subject:
            raise ValueError(f"native source {artifact_id} has no named business subject")
        scope = f"{subject} | {config.measure_kind} [{config.unit}]"
        candidates.append(_Projection(native, fact, eligible[0][0], value, dict(source.units),
                                      tuple(sorted(source.lineage)), provenance, scope, authority))
    families = _families(candidates, world.company.id)
    records: list[ConnectorRecord] = []
    bindings: list[NativeConnectorBinding] = []
    omitted: list[str] = []
    seen: dict[tuple[str, str, str], list[tuple[str, frozenset[str]]]] = {}
    for candidate in candidates:
        native, fact = candidate.native, candidate.fact
        assert fact.period is not None
        key = candidate.scope, fact.period, candidate.authority
        lineage = frozenset(index.fact_closure((fact.id,)))
        previous = seen.setdefault(key, [])
        if any(identifier == fact.id for identifier, _ in previous):
            omitted.append(native.manifest.artifact_id)
            continue
        if any(lineage.intersection(other) for _, other in previous):
            raise ValueError("native source values share canonical ancestry; they cannot be summed as independent contributions")
        previous.append((fact.id, lineage))
        content = "\n".join(text for _, text in sorted(candidate.units.items()) if text)
        if len(content.encode("utf-8")) > config.max_content_bytes:
            raise ValueError("native extracted content exceeds max_content_bytes; it cannot be silently truncated")
        record_id = "native-source-" + content_key(_VERSION, config.model_dump(mode="json"),
            native.manifest.artifact_id, native.manifest.sha256, fact.id)
        family = families[native.manifest.artifact_id]
        # Keep the canonical numeric JSON type expected by connector schemas;
        # values retain the world's units rather than being called minor units.
        amount: int | float = int(candidate.value) if candidate.value == candidate.value.to_integral_value() else float(candidate.value)
        if Decimal(str(amount)) != candidate.value:
            raise ValueError("native amount cannot round-trip through the connector numeric JSON representation")
        fields: dict[str, Any] = {
            "name": native.manifest.artifact_id + "." + native.manifest.format,
            "title": index.artifacts[candidate.source_artifact_ids[0]].title,
            "content": content, config.value_field: amount, config.scope_field: candidate.scope,
            config.period_field: fact.period, config.authority_field: candidate.authority,
            "measure_kind": config.measure_kind, "unit": config.unit, "representation": "extracted_content",
            "source_sha256": native.manifest.sha256, "source_format": native.manifest.format,
            "source_size_bytes": native.manifest.file_size_bytes, "source_locator": candidate.locator,
            "source_family": family,
        }
        records.append(ConnectorRecord(
            id=record_id, external_id=record_id, connector=config.connector, entity=native.manifest.format,
            title=fields["title"], fields=fields, fact_ids=list(candidate.fact_ids),
            event_ids=sorted({event for identifier in candidate.fact_ids
                              if (event := index.facts[identifier].event_id) is not None}),
            source_artifact_ids=list(candidate.source_artifact_ids),
        ))
        bindings.append(NativeConnectorBinding(
            record_id=record_id, artifact_id=native.manifest.artifact_id, source_sha256=native.manifest.sha256,
            locator=candidate.locator, selected_fact_id=fact.id, fact_ids=candidate.fact_ids,
            source_artifact_ids=candidate.source_artifact_ids, family_id=family,
        ))
    return NativeConnectorSources(config=config, records=tuple(records), bindings=tuple(bindings),
        deduplicated_artifact_ids=tuple(omitted),
        excluded_formats=tuple(sorted(item.manifest.artifact_id for item in materialized if item.manifest.format != config.format)))


__all__ = ["NativeConnectorProjection", "NativeConnectorBinding", "NativeConnectorSources", "project_native_sources"]
