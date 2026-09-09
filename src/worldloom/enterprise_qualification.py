"""Qualify a finite enterprise query pool before choosing its coverage.

Planning supplies obligations, not evidence. This adapter keeps the existing
materializer, validators, compiler, executor and covering algorithm authoritative,
and records the rows each seam refused. Selection keeps the exact shared records
and fixtures against which the admitted rows were executed.

Coverage of audience, content-action and legacy topology labels describes the
requested pool. It does not establish semantic answer accuracy, document layout
or macro reconciliation. Native input receipts attest bytes in the source World;
that original World is required to inspect them after an enterprise export.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import RootModel

from .connector_data import ConnectorDataset, ConnectorProjectionRegistry
from .connector_eval_runtime import run_eval_row
from .corpus import write_json, write_jsonl
from .enterprise_corpus import (
    EnterpriseCorpus,
    QueryFixture,
    materialize_corpus,
    operational_case_ids,
    validate_corpus,
)
from .enterprise_io import export_corpus, export_queries
from .enterprise_queries import (
    CoverageReport,
    PlannedEnterpriseQuery,
    _subsets,
    constrained_cover,
)
from .enterprise_rows import compile_rows, runtime_records
from .eval_shape_validation import ArtifactByteWitness, artifact_byte_witnesses
from .ids import content_key
from .models import Model
from .synthesis.connectors import OPERATIONAL_CASE_DIMENSIONS

if TYPE_CHECKING:
    from .world import World

QUALIFICATION_SCHEMA = "worldloom.enterprise-qualification/v1"
PROVENANCE_DIMENSIONS = OPERATIONAL_CASE_DIMENSIONS
Interaction = tuple[tuple[str, str], ...]
QueryBinder = Callable[[PlannedEnterpriseQuery, int], PlannedEnterpriseQuery]


def digest(value: Any) -> str:
    """Content identity shared by qualification proofs and their export."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return content_key(QUALIFICATION_SCHEMA, json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ))


class QualificationRefusal(Model):
    query_id: str
    stage: Literal["binding", "preflight", "materialization", "validation", "compilation", "execution"]
    code: str
    detail: str


class QualificationReport(Model):
    pool_size: int
    pool_count: int
    pool_exhausted: bool
    max_selected: int | None
    eligible_count: int
    selected_count: int
    requested_interactions: int
    eligible_coverage: CoverageReport
    selected_coverage: CoverageReport
    requested_cases: int
    eligible_case_coverage: CoverageReport
    selected_case_coverage: CoverageReport
    excluded_dimensions: tuple[str, ...] = tuple(sorted(PROVENANCE_DIMENSIONS))
    eligible_query_ids: tuple[str, ...] = ()
    selected_query_ids: tuple[str, ...] = ()
    refusals: tuple[QualificationRefusal, ...] = ()
    shared_findings: tuple[str, ...] = ()


class QualificationProof(Model):
    query_id: str
    query_digest: str
    fixture_digest: str
    connector_data_digest: str
    row_digest: str
    grade: dict[str, Any]
    spans: tuple[dict[str, Any], ...]
    behaviors: tuple[str, ...]
    post_state: dict[str, dict[str, Any]]
    native_artifacts: tuple[ArtifactByteWitness, ...] = ()


@dataclass(frozen=True)
class EnterpriseQualification:
    corpus: EnterpriseCorpus
    pool: tuple[PlannedEnterpriseQuery, ...]
    rows: tuple[dict[str, Any], ...]
    proofs: tuple[QualificationProof, ...]
    report: QualificationReport
    connector_data_digest: str
    proofs_digest: str
    pool_digest: str
    qualification_digest: str

    def export(self, directory: str | Path, *, overwrite: bool = False) -> Path:
        """Persist exact qualified fixtures, rows, traces and input identities.

        Native artifact receipts retain their checked byte digests. The original
        World holds those source files; the enterprise export does not copy them.
        """
        if digest(self.corpus.connector_data) != self.connector_data_digest:
            raise ValueError("qualified connector data changed after execution")
        if digest([proof.model_dump(mode="json") for proof in self.proofs]) != self.proofs_digest:
            raise ValueError("qualified proofs changed after execution")
        if digest([query.model_dump(mode="json") for query in self.pool]) != self.pool_digest:
            raise ValueError("qualification pool changed after execution")
        if digest(self.report) != self.qualification_digest:
            raise ValueError("qualification report changed after execution")
        queries = {query.id: query for query in self.corpus.queries}
        fixtures = {fixture.query_id: fixture for fixture in self.corpus.fixtures}
        rows = {str(row["id"]): row for row in self.rows}
        if (set(queries) != set(fixtures) or set(queries) != set(rows)
                or set(queries) != {proof.query_id for proof in self.proofs}
                or len(queries) != len(self.corpus.queries)
                or len(fixtures) != len(self.corpus.fixtures)
                or len(rows) != len(self.rows) or len(queries) != len(self.proofs)):
            raise ValueError("qualified queries, fixtures, rows and proofs disagree")
        for proof in self.proofs:
            if (proof.connector_data_digest != self.connector_data_digest
                    or proof.query_digest != digest(queries[proof.query_id])
                    or proof.fixture_digest != digest(fixtures[proof.query_id])
                    or proof.row_digest != digest(rows[proof.query_id])):
                raise ValueError(f"qualified inputs for {proof.query_id} changed after execution")
        root = Path(directory)
        if root.exists() and any(root.iterdir()):
            if not overwrite:
                raise FileExistsError(f"qualification destination is not empty: {root}")
            try:
                manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
            if manifest.get("qualification_schema") != QUALIFICATION_SCHEMA:
                raise FileExistsError(f"{root} is not an enterprise qualification; refusing to overwrite it")
            shutil.rmtree(root)
        export_corpus(self.corpus, root)
        write_json(root / "qualification.json", self.report.model_dump(mode="json"))
        export_queries(self.pool, root / "pool-queries.jsonl")
        write_jsonl(root / "qualified-rows.jsonl", [RootModel[dict[str, Any]](row) for row in self.rows])
        write_jsonl(root / "proofs.jsonl", [proof for proof in self.proofs])
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        manifest.update({
            "qualification_schema": QUALIFICATION_SCHEMA,
            "qualification": "qualification.json",
            "pool": "pool-queries.jsonl",
            "rows": "qualified-rows.jsonl",
            "proofs": "proofs.jsonl",
            "connector_data_digest": self.connector_data_digest,
            "corpus_digest": digest(self.corpus),
            "pool_digest": self.pool_digest,
            "qualification_digest": self.qualification_digest,
            "rows_digest": digest(self.rows),
            "proofs_digest": self.proofs_digest,
        })
        write_json(root / "manifest.json", manifest)
        return root


def _dimensions(query: PlannedEnterpriseQuery) -> dict[str, str]:
    return {key: value for key, value in query.dimensions.items() if key not in PROVENANCE_DIMENSIONS}


def _interactions(queries: Sequence[PlannedEnterpriseQuery], strength: int) -> set[Interaction]:
    return {interaction for query in queries for interaction in _subsets(_dimensions(query), strength)}


def _coverage(required: set[Interaction], observed: set[Interaction], *, strength: int,
              candidates: int, selected: int) -> CoverageReport:
    return CoverageReport(strength=strength, candidates=candidates, selected=selected,
                          required_interactions=len(required), covered_interactions=len(required & observed),
                          holes=tuple(sorted(required - observed)))


def _declared_cases(query: PlannedEnterpriseQuery) -> set[str]:
    if (PROVENANCE_DIMENSIONS & query.dimensions.keys()
            and "operational_case_binding" not in query.dimensions):
        raise ValueError("operational case metadata requires operational_case_binding")
    return set(operational_case_ids(query))


def _dimension_contract(query: PlannedEnterpriseQuery) -> tuple[QualificationRefusal, ...]:
    """Coverage labels for concrete inputs and mutations must name their contract."""
    sources = query.generation.source_requirements
    mutation = query.generation.mutation
    expected = {
        "workflow": query.workflow,
        "source_set": "+".join(source.connector for source in sources),
        "source_entities": "+".join(f"{source.connector}:{source.entity}" for source in sources),
        "input_formats": "+".join(source.input_format for source in sources),
        "destination": mutation.connector, "destination_entity": mutation.entity,
        "operation": mutation.operation, "output_format": mutation.output_format,
        "failure": "+".join(query.generation.state_overrides) or "none",
    }
    return tuple(QualificationRefusal(
        query_id=query.id, stage="preflight", code="dimension_contract_mismatch",
        detail=f"dimension {key} declares {query.dimensions[key]!r}; generation requires {value!r}",
    ) for key, value in sorted(expected.items()) if key in query.dimensions and query.dimensions[key] != value)


def _observed_cases(fixture: QueryFixture, data: ConnectorDataset) -> set[str]:
    by_id = {record.id: record for record in data.records}
    return {
        str(case)
        for ids in fixture.input_record_ids.values() for record_id in ids
        if (record := by_id.get(record_id)) is not None
        and (case := record.fields.get("case_id")) is not None
    }


def _source_evidence(query: PlannedEnterpriseQuery, fixture: QueryFixture,
                     data: ConnectorDataset, known_facts: set[str],
                     witnesses: dict[tuple[str, str], ArtifactByteWitness],
                     ) -> tuple[tuple[QualificationRefusal, ...], tuple[ArtifactByteWitness, ...]]:
    """An entity alias cannot attest a concrete input format.

    Materialization deliberately keeps its legacy alias selection. Qualification
    checks the actual records it selected and their linked native artifacts.
    Planned ``file`` rows with no bytes cannot prove a PDF or workbook exists;
    these checks make no claim about pages, charts or semantic file content.
    """
    by_id = {record.id: record for record in data.records}
    formats = {"docx", "xlsx", "pptx", "pdf", "html", "markdown", "csv", "text"}
    findings: list[QualificationRefusal] = []
    checked: dict[tuple[str, str], ArtifactByteWitness] = {}
    for source in query.generation.source_requirements:
        key = f"{source.connector}:{source.entity}"
        for record_id in fixture.input_record_ids.get(key, ()):
            record = by_id.get(record_id)
            if record is None:
                continue  # The corpus validator owns dangling evidence.
            unknown = set(record.fact_ids) - known_facts
            if unknown:
                findings.append(QualificationRefusal(
                    query_id=query.id, stage="validation", code="source_fact_unknown",
                    detail=f"source {key} record {record_id} cites facts absent from the World: {sorted(unknown)}",
                ))
            if source.input_format == "record":
                continue
            observed = {str(record.fields["format"])} if record.fields.get("format") else set()
            if record.entity in formats:
                observed.add(record.entity)
            if observed and observed != {source.input_format}:
                findings.append(QualificationRefusal(
                    query_id=query.id, stage="validation",
                    code="source_format_mismatch",
                    detail=f"source {key} record {record_id} requires {source.input_format}; observed formats {sorted(observed)}",
                ))
                continue
            suffix = ".md" if source.input_format == "markdown" else f".{source.input_format}"
            artifacts = record.source_artifact_ids
            if not artifacts or any((witness := witnesses.get((artifact_id, suffix))) is None or witness.size_bytes == 0 for artifact_id in artifacts):
                findings.append(QualificationRefusal(
                    query_id=query.id, stage="validation", code="source_format_unsupported",
                    detail=f"source {key} record {record_id} has no complete native {source.input_format} payload witness for its linked World artifacts",
                ))
            else:
                checked.update({(artifact_id, suffix): witnesses[artifact_id, suffix] for artifact_id in artifacts})
    return tuple(findings), tuple(checked[key] for key in sorted(checked))


def qualify_queries(
    world: World,
    queries: Sequence[PlannedEnterpriseQuery],
    *,
    pool_size: int,
    pool_exhausted: bool,
    strength: int = 2,
    max_selected: int | None = None,
    projections: ConnectorProjectionRegistry | None = None,
    binder: QueryBinder | None = None,
) -> EnterpriseQualification:
    """Qualify a bounded pool, then cover eligible semantics and actual cases.

    Case representatives use the existing one-way cover; semantic interactions
    use the requested strength. Their union follows pool order. An explicit
    output cap may leave either kind of hole, which is recomputed and reported.
    """
    if pool_size < 1 or len(queries) > pool_size:
        raise ValueError("qualification requires a positive pool_size bounding every input query")
    if max_selected is not None and max_selected < 1:
        raise ValueError("max_selected must be positive")
    if strength < 1 or any(len(_dimensions(query)) < strength for query in queries):
        raise ValueError("coverage strength must fit every query's semantic dimensions")
    if len({query.id for query in queries}) != len(queries):
        raise ValueError("qualification pool contains duplicate query ids")
    world.validate().raise_if_failed()
    refusals: list[QualificationRefusal] = []
    pool: list[PlannedEnterpriseQuery] = []
    survivors: list[PlannedEnterpriseQuery] = []
    requested_cases: set[str] = set()

    def refuse(query_id: str, stage: Any, error: Exception) -> None:
        finding = getattr(error, "finding", None)
        refusals.append(QualificationRefusal(
            query_id=query_id, stage=stage,
            code=getattr(finding, "code", type(error).__name__), detail=str(error),
        ))

    for ordinal, original in enumerate(queries):
        query = original
        if binder is not None:
            try:
                query = binder(original, ordinal)
            except ValueError as error:
                pool.append(original)
                refuse(original.id, "binding", error)
                continue
        pool.append(query)
        contract_findings = _dimension_contract(query)
        if contract_findings:
            refusals.extend(contract_findings)
            continue
        try:
            requested_cases.update(_declared_cases(query))
            preflight = materialize_corpus(world, (query,), projections=projections, strict_sources=True)
        except (ValueError, KeyError) as error:
            refuse(query.id, "preflight", error)
            continue
        requested_cases.update(_observed_cases(preflight.fixtures[0], preflight.connector_data))
        survivors.append(query)

    if len({query.id for query in pool}) != len(pool):
        raise ValueError("binding produced duplicate qualified query ids")
    try:
        batch = materialize_corpus(world, survivors, projections=projections, strict_sources=True)
    except (ValueError, KeyError) as error:
        for query in survivors:
            refuse(query.id, "materialization", error)
        batch = EnterpriseCorpus(queries=(), fixtures=(), connector_data=ConnectorDataset(capabilities=[], records=[]))
    shared_findings = validate_corpus(batch.model_copy(update={"queries": (), "fixtures": ()}))
    data_digest = digest(batch.connector_data)
    known_facts = set(world.facts.ids())
    witnesses = artifact_byte_witnesses(world) if any(
        source.input_format != "record" for query in batch.queries
        for source in query.generation.source_requirements
    ) else {}
    records = runtime_records(batch.connector_data.records)
    fixtures = {fixture.query_id: fixture for fixture in batch.fixtures}
    eligible: list[PlannedEnterpriseQuery] = []
    rows_by_id: dict[str, dict[str, Any]] = {}
    proofs_by_id: dict[str, QualificationProof] = {}
    cases_by_id: dict[str, set[str]] = {}
    for query in batch.queries:
        fixture = fixtures[query.id]
        view = batch.model_copy(update={"queries": (query,), "fixtures": (fixture,)})
        findings = validate_corpus(view)
        if findings:
            refusals.extend(QualificationRefusal(query_id=query.id, stage="validation",
                            code="invalid_corpus", detail=detail) for detail in findings)
            continue
        evidence_findings, native_artifacts = _source_evidence(query, fixture, batch.connector_data, known_facts, witnesses)
        if evidence_findings:
            refusals.extend(evidence_findings)
            continue
        try:
            compiled = compile_rows((query,), (fixture,), records)
        except (ValueError, KeyError) as error:
            refuse(query.id, "compilation", error)
            continue
        if compiled.refusals:
            for refusal in compiled.refusals:
                refuse(query.id, "compilation", refusal)
            continue
        row = compiled.rows[0]
        try:
            result = run_eval_row(row, records)
        except Exception as error:  # executor boundary: a failed row must remain visible in the finite pool
            refuse(query.id, "execution", error)
            continue
        if result.grade.get("status") not in {"ok", "behavior"} or result.grade.get("fails") != []:
            refusals.append(QualificationRefusal(query_id=query.id, stage="execution",
                            code="assertions_failed", detail=json.dumps(dict(result.grade), sort_keys=True)))
            continue
        eligible.append(query)
        rows_by_id[query.id] = row
        cases_by_id[query.id] = _observed_cases(fixture, batch.connector_data)
        proofs_by_id[query.id] = QualificationProof(
            query_id=query.id, query_digest=digest(query), fixture_digest=digest(fixture),
            connector_data_digest=data_digest, row_digest=digest(row), grade=dict(result.grade),
            spans=tuple(asdict(span) for span in result.spans), behaviors=result.behaviors,
            post_state={key: dict(value) for key, value in result.post_state.items()},
            native_artifacts=native_artifacts,
        )

    semantic_rows = [_dimensions(query) for query in eligible]
    semantic_cover, _ = constrained_cover(semantic_rows, strength)
    first_by_dimensions: dict[tuple[tuple[str, str], ...], str] = {}
    for query, dimensions in zip(eligible, semantic_rows, strict=True):
        first_by_dimensions.setdefault(tuple(sorted(dimensions.items())), query.id)
    selected_ids = {first_by_dimensions[tuple(sorted(row.items()))] for row in semantic_cover}
    first_by_case: dict[str, str] = {}
    case_rows: list[dict[str, str]] = []
    for query in eligible:
        for case in sorted(cases_by_id[query.id]):
            first_by_case.setdefault(case, query.id)
            case_rows.append({"case_id": case})
    case_cover, _ = constrained_cover(case_rows, 1)
    selected_ids.update(first_by_case[row["case_id"]] for row in case_cover)
    selected = tuple(query for query in eligible if query.id in selected_ids)
    if max_selected is not None:
        selected = selected[:max_selected]
    requested = _interactions(pool, strength)
    eligible_interactions = _interactions(eligible, strength)
    selected_interactions = _interactions(selected, strength)
    required_case_interactions: set[Interaction] = {(("case_id", case),) for case in requested_cases}
    eligible_cases: set[Interaction] = {(("case_id", case),) for query in eligible for case in cases_by_id[query.id]}
    selected_cases: set[Interaction] = {(("case_id", case),) for query in selected for case in cases_by_id[query.id]}
    report = QualificationReport(
        pool_size=pool_size, pool_count=len(pool), pool_exhausted=pool_exhausted,
        max_selected=max_selected, eligible_count=len(eligible), selected_count=len(selected),
        requested_interactions=len(requested), requested_cases=len(requested_cases),
        eligible_coverage=_coverage(requested, eligible_interactions, strength=strength, candidates=len(pool), selected=len(eligible)),
        selected_coverage=_coverage(requested, selected_interactions, strength=strength, candidates=len(eligible), selected=len(selected)),
        eligible_case_coverage=_coverage(required_case_interactions, eligible_cases, strength=1, candidates=len(pool), selected=len(eligible)),
        selected_case_coverage=_coverage(required_case_interactions, selected_cases, strength=1, candidates=len(eligible), selected=len(selected)),
        eligible_query_ids=tuple(query.id for query in eligible),
        selected_query_ids=tuple(query.id for query in selected), refusals=tuple(refusals),
        shared_findings=shared_findings,
    )
    proofs = tuple(proofs_by_id[query.id] for query in selected)
    return EnterpriseQualification(
        corpus=batch.model_copy(update={"queries": selected, "fixtures": tuple(fixtures[query.id] for query in selected)}),
        pool=tuple(pool), rows=tuple(rows_by_id[query.id] for query in selected),
        proofs=proofs, report=report, connector_data_digest=data_digest,
        proofs_digest=digest([proof.model_dump(mode="json") for proof in proofs]),
        pool_digest=digest([query.model_dump(mode="json") for query in pool]),
        qualification_digest=digest(report),
    )


__all__ = [
    "EnterpriseQualification", "PROVENANCE_DIMENSIONS", "QUALIFICATION_SCHEMA",
    "QualificationProof", "QualificationRefusal", "QualificationReport", "digest", "qualify_queries",
]
