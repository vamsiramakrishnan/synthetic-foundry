#!/usr/bin/env python3
"""Measure executable enterprise coverage, exact export replay and case selection.

    python tools/measure_enterprise_qualification.py --out measurement.json

The finite pools are observations, not estimates of the entire enterprise space.
Company probes share the built-in query catalogue to expose support differences
without inventing industry-specific workflows. Native World artifacts are rendered
before qualification; no model calls or authored-prose quality claims are made.
Operational comparisons hold each simulator and query pool fixed and change only
the opt-in case binding. Exports are checked in temporary storage unless --exports
names a persistent empty directory. No external calls or additional dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from worldloom import BankingWorld, MonthEndClose, RetailWorld, company, domains, sdk
from worldloom.connector_eval_runtime import run_eval_row
from worldloom.enterprise_corpus import validate_corpus
from worldloom.enterprise_io import iter_queries, load_exported_corpus
from worldloom.enterprise_qualification import (
    QualificationProof,
    QualificationReport,
    digest,
)
from worldloom.enterprise_rows import compile_rows, runtime_records
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.enterprise_specs import CoverageProfile
from worldloom.synthesis import (
    IncidentRule,
    Simulator,
    banking,
    exception_episodes,
    operational_profile,
    retail,
    with_parameters,
)

ENGINES = ("retail", "banking", "insurance", "procurement")
GEOGRAPHIES = ("germany", "united_kingdom")
FORMATS = ("xlsx", "docx", "pptx", "pdf", "html", "markdown", "confluence", "jira", "servicenow")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _files(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)): _sha(path.read_bytes())
            for path in sorted(directory.rglob("*")) if path.is_file()}


def _require(condition: bool, message: str) -> None:
    # These are measurement gates, so Python's -O must not disable them.
    if not condition:
        raise AssertionError(message)


def _cases(corpus: Any) -> set[str]:
    records = {record.id: record for record in corpus.connector_data.records}
    return {str(case) for fixture in corpus.fixtures
            for identifiers in fixture.input_record_ids.values() for identifier in identifiers
            if (case := records[identifier].fields.get("case_id")) is not None}


def _coverage(report: Any) -> dict[str, Any]:
    return {
        "strength": report.strength,
        "required_interactions": report.required_interactions,
        "covered_interactions": report.covered_interactions,
        "hole_count": len(report.holes),
        "hole_examples": report.holes[:8],
    }


def _replay(result: Any, directory: Path) -> dict[str, Any]:
    result.export(directory)
    loaded = load_exported_corpus(directory)
    _require(loaded == result.corpus, "exported corpus changed on reload")
    _require(not validate_corpus(loaded), "reloaded corpus failed validation")
    rows = tuple(json.loads(line) for line in
                 (directory / "qualified-rows.jsonl").read_text(encoding="utf-8").splitlines())
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    pool = tuple(iter_queries(directory / "pool-queries.jsonl"))
    qualification = QualificationReport.model_validate_json(
        (directory / "qualification.json").read_text(encoding="utf-8"))
    exported_proofs = tuple(QualificationProof.model_validate_json(line) for line in
                            (directory / "proofs.jsonl").read_text(encoding="utf-8").splitlines())
    _require(digest(loaded) == manifest["corpus_digest"], "reloaded corpus digest mismatch")
    _require(digest(rows) == manifest["rows_digest"], "reloaded rows digest mismatch")
    _require(digest(loaded.connector_data) == result.connector_data_digest, "reloaded data digest mismatch")
    _require(digest(loaded.connector_data) == manifest["connector_data_digest"], "exported data manifest mismatch")
    _require(digest([query.model_dump(mode="json") for query in pool]) == manifest["pool_digest"],
             "reloaded pool digest mismatch")
    _require(digest(qualification) == manifest["qualification_digest"], "reloaded qualification digest mismatch")
    _require(digest([proof.model_dump(mode="json") for proof in exported_proofs]) == manifest["proofs_digest"],
             "reloaded proofs digest mismatch")
    runtime = runtime_records(loaded.connector_data.records)
    compiled = compile_rows(loaded.queries, loaded.fixtures, runtime)
    _require(not compiled.refusals, "selected corpus no longer compiles")
    _require(digest(compiled.rows) == digest(rows), "recompilation changed exported rows")
    proofs = {proof.query_id: proof for proof in exported_proofs}
    statuses: Counter[str] = Counter()
    spans_with_errors = 0
    for row in rows:
        executed = run_eval_row(row, runtime)
        _require(executed.grade.get("status") in {"ok", "behavior"}
                 and executed.grade.get("fails") == [], f"reloaded assertion failed: {row['id']}")
        proof = proofs[row["id"]]
        observed = {"grade": dict(executed.grade),
                    "spans": tuple(asdict(span) for span in executed.spans),
                    "behaviors": executed.behaviors,
                    "post_state": {key: dict(value) for key, value in executed.post_state.items()}}
        expected = {key: getattr(proof, key) for key in observed}
        _require(digest(observed) == digest(expected), f"reloaded execution changed: {row['id']}")
        statuses[str(executed.grade["status"])] += 1
        spans_with_errors += sum(span.error is not None for span in executed.spans)
    return {"corpus_equal": True, "recompiled_rows_equal": True,
            "pool_report_proof_digests_verified": True,
            "execution_proofs_equal": True, "assertion_passed": len(rows),
            "assertion_failed": 0, "grade_statuses": dict(sorted(statuses.items())),
            "tool_error_spans": spans_with_errors, "export_sha256": _files(directory)}


def _measure(harness: EnterpriseEvalHarness, *, pool: int, cap: int,
             directory: Path) -> dict[str, Any]:
    first = harness.qualify(pool_size=pool, max_selected=cap)
    replay = _replay(first, directory / "first")
    repeated = harness.qualify(pool_size=pool, max_selected=cap)
    repeated.export(directory / "repeat")
    _require(_files(directory / "first") == _files(directory / "repeat"),
             "repeated qualification changed export bytes")
    report = first.report
    refusals = Counter(f"{item.stage}:{item.code}" for item in report.refusals)
    refused_queries = {item.query_id for item in report.refusals}
    _require(report.eligible_count + len(refused_queries) == report.pool_count,
             "eligible and refused query counts do not partition the pool")
    native = [witness.model_dump(mode="json") for proof in first.proofs
              for witness in getattr(proof, "native_artifacts", ())]
    return {
        "pool_size": pool, "pool_count": report.pool_count,
        "pool_exhausted": report.pool_exhausted, "selection_cap": cap,
        "eligible": report.eligible_count, "selected": report.selected_count,
        "refused_queries": len(refused_queries), "refusal_findings": len(report.refusals),
        "refusal_distribution": dict(sorted(refusals.items())),
        "refusal_examples": [item.model_dump(mode="json") for item in report.refusals[:12]],
        "shared_findings": report.shared_findings,
        "requested_interactions": report.requested_interactions,
        "observed_achievable_interactions": report.eligible_coverage.covered_interactions,
        "eligible_coverage": _coverage(report.eligible_coverage),
        "selected_coverage": _coverage(report.selected_coverage),
        "requested_cases": report.requested_cases,
        "eligible_case_coverage": _coverage(report.eligible_case_coverage),
        "selected_case_coverage": _coverage(report.selected_case_coverage),
        "distinct_selected_cases": len(_cases(first.corpus)),
        "connector_records": len(first.corpus.connector_data.records),
        "selected_native_source_witnesses": len(native),
        "distinct_native_source_witnesses": len({digest(witness) for witness in native}),
        "pool_source_formats": dict(sorted(Counter(source.input_format for query in first.pool
                                                  for source in query.generation.source_requirements).items())),
        "selected_workflows": dict(sorted(Counter(query.workflow for query in first.corpus.queries).items())),
        "selected_shapes": dict(sorted(Counter(query.dimensions.get("dag_shape", "legacy")
                                               for query in first.corpus.queries).items())),
        "connector_data_digest": first.connector_data_digest,
        "proofs_digest": first.proofs_digest,
        "repeat_export_byte_equal": True,
        "reload": replay,
    }


def _company_probe(engine: str, geo: str, *, seed: int, pool: int, cap: int,
                   directory: Path) -> dict[str, Any]:
    specification = {"engine": engine, "geo": geo,
                     "identity": {"company_name": f"Qualification {engine.title()} {geo}"}}
    resolution = company.resolve(company.from_document(specification))
    observation: dict[str, Any] = {"engine": engine, "geography": geo,
                                   "company_specification": specification,
                                   "resolution": resolution.as_dict(),
                                   "query_profile": "enterprise-default", "seed": seed,
                                   "narration": "not authored; native structural evidence only"}
    if not resolution.ok:
        return {**observation, "status": "unsupported", "stage": "company_resolution"}
    world = sdk.from_resolution(resolution, seed=seed).build().world
    domain = domains.by_name(engine)
    if domain is None:
        raise AssertionError(f"unregistered engine {engine}")
    episode = (domain.single_episode("2026-03") if domain.single_episode is not None else
               MonthEndClose(period="2026-03", include_operational_incident=True))
    world = world.run(episode).compile()
    world.validate().raise_if_failed()
    # Use real format renderers; never manufacture file claims or source rows.
    world = world.render(*FORMATS)
    observation.update({"episode": type(episode).__name__, "period": "2026-03",
                        "artifacts": len(world.artifact_irs), "render_formats_requested": FORMATS,
                        "rendered_files_by_suffix": dict(sorted(Counter(Path(item.path).suffix
                                                                     for item in world._rendered).items())),
                        "rendered_bytes": sum(len(item.payload) for item in world._rendered)})
    harness = EnterpriseEvalHarness.from_world(world).with_profile(CoverageProfile(strengths=2))
    observation["qualification"] = _measure(harness, pool=pool, cap=cap, directory=directory)
    observation["status"] = "measured"
    return observation


def _operational_probe(vertical: str, shape: str, *, seed: int, count: int,
                       directory: Path) -> dict[str, Any]:
    if vertical == "retail":
        world = RetailWorld(seed=seed).build()
        program = with_parameters(retail(stores=2, products=3, ticks=12),
                                  {"initial_stock": 8, "target_stock": 15})
        rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    else:
        world = BankingWorld(seed=seed).build()
        program = banking(borrowers=8, ticks=8)
        rule = IncidentRule(table="loan", signal="arrears", title="Payment arrears")
    simulator = Simulator(program, seed=seed)
    scenario = operational_profile(vertical)
    scenario = scenario.model_copy(update={"coverage": scenario.coverage.model_copy(
        update={"strengths": 2, "failures": ("none",)})})
    harness = (EnterpriseEvalHarness.from_world(world).with_scenario(scenario)
               .with_operational_data(simulator, rule, include_world_records=False))
    if shape != "straight":
        harness = harness.with_dag_grammar(shape)
    baseline = _measure(harness, pool=count, cap=count, directory=directory / "default")
    bound = _measure(harness.with_operational_case_binding(), pool=count, cap=count,
                     directory=directory / "case-bound")
    return {"vertical": vertical, "shape": shape, "seed": seed,
            "simulator_recipe_digest": simulator.run_digest,
            "available_exception_cases": len(tuple(exception_episodes(simulator, rule))),
            "failures": ("none",), "pool_size": count, "selection_cap": count,
            "default_binding": baseline, "case_binding": bound,
            "status": "measured"}


def measure(*, seed: int, pool: int, cap: int, count: int, exports: Path) -> dict[str, Any]:
    companies = []
    operational = []
    errors = []
    for engine in ENGINES:
        for geo in GEOGRAPHIES:
            label = f"{engine}-{geo}"
            print(f"Measuring {label}", file=sys.stderr, flush=True)
            try:
                companies.append(_company_probe(engine, geo, seed=seed, pool=pool, cap=cap,
                                                 directory=exports / label))
            except Exception as error:
                errors.append({"probe": label, "error": type(error).__name__, "detail": str(error)})
    for vertical in ("retail", "banking"):
        for shape in ("straight", "map_read"):
            label = f"operational-{vertical}-{shape}"
            print(f"Measuring {label}", file=sys.stderr, flush=True)
            try:
                operational.append(_operational_probe(vertical, shape, seed=seed, count=count,
                                                      directory=exports / label))
            except Exception as error:
                errors.append({"probe": label, "error": type(error).__name__, "detail": str(error)})
    all_results = [item["qualification"] for item in companies if item["status"] == "measured"]
    all_results.extend(arm for item in operational for arm in (item["default_binding"], item["case_binding"]))
    refusals: Counter[str] = Counter()
    for result in all_results:
        refusals.update(result["refusal_distribution"])
    return {
        "schema": "worldloom.enterprise-qualification-measurement/v1",
        "parameters": {"seed": seed, "company_pool": pool, "company_cap": cap,
                       "strength": 2, "operational_pool_and_cap": count,
                       "engines": ENGINES, "geographies": GEOGRAPHIES},
        "scope": ["Finite interleaved query pools, not the whole declared space.",
                  "Four engine-backed company profiles share the built-in enterprise query catalogue.",
                  "Geographies use resolved identity packs; unmet resolution capabilities remain reported.",
                  "Native source file bytes are rendered, not inferred from requested formats.",
                  "Reference emulator assertions measure executable plumbing, not autonomous agent ability or semantic prose quality.",
                  "Observed achievable coverage is restricted to eligible rows in each measured pool.",
                  "Operational arms use failure=none and identical simulator configuration and pool budget.",
                  "Exact selected corpus exports and rerun proof comparisons include retained shared connector records."],
        "companies": companies, "operational": operational,
        "summary": {"company_probes_requested": len(ENGINES) * len(GEOGRAPHIES),
                    "company_probes_measured": sum(item["status"] == "measured" for item in companies),
                    "operational_comparisons_measured": len(operational),
                    "qualification_arms_measured": len(all_results),
                    "refusal_distribution": dict(sorted(refusals.items())),
                    "selected_assertions_passed": sum(result["reload"]["assertion_passed"] for result in all_results),
                    "measurement_error_count": len(errors)},
        "measurement_errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--exports", type=Path, help="Retain exact exports in an empty directory.")
    parser.add_argument("--seed", type=int, default=8128)
    parser.add_argument("--pool", type=int, default=128)
    parser.add_argument("--cap", type=int, default=64)
    parser.add_argument("--operational-count", type=int, default=24)
    args = parser.parse_args()
    if min(args.pool, args.cap, args.operational_count) < 1:
        parser.error("pool, cap and operational-count must be positive")
    if args.exports is not None and args.exports.exists() and any(args.exports.iterdir()):
        parser.error("--exports must name an empty directory")
    options = {"seed": args.seed, "pool": args.pool, "cap": args.cap, "count": args.operational_count}
    if args.exports is not None:
        result = measure(**options, exports=args.exports)
    else:
        with tempfile.TemporaryDirectory(prefix="worldloom-qualification-") as temporary:
            result = measure(**options, exports=Path(temporary))
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    result["source_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
    result["measurement_script_sha256"] = _sha(Path(__file__).read_bytes())
    tracked = subprocess.run(["git", "ls-files", "src", "pyproject.toml"], cwd=ROOT,
                             capture_output=True, text=True, check=True)
    result["source_files_sha256"] = {name: _sha((ROOT / name).read_bytes())
                                      for name in sorted(tracked.stdout.splitlines())}
    result["python_version"] = sys.version
    result["dependency_versions"] = {}
    for package in ("pydantic", "python-docx", "XlsxWriter", "python-pptx", "reportlab"):
        try:
            result["dependency_versions"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result["dependency_versions"][package] = None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result["summary"], sort_keys=True, indent=2))
    if result["measurement_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
