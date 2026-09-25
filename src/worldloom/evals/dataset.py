"""Compile declared dataset quotas into qualified, isolated, replayable rows.

The scheduler asks existing builders for worlds. Qualification remains the
independent evidence/execution boundary. Only admitted rows consume quotas;
rejected repetition becomes feedback for the next bounded generation request.
Each committed batch owns its exact World, fixtures and proofs on disk, so
resuming or exporting cannot accidentally rebuild the evidence that was tested.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import shutil
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import Executor, ProcessPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from fractions import Fraction
from itertools import islice
from pathlib import Path
from typing import Any, Protocol

from .. import packkit
from ..corpus import write_json
from ..enterprise_io import load_exported_corpus
from ..enterprise_qualification import QualificationProof, qualify_queries
from ..enterprise_queries import PlannedEnterpriseQuery, plan_queries
from ..enterprise_sdk import EnterpriseEvalHarness
from ..providers import digest
from .dataset_contract import DatasetEntry, DatasetPlan, DatasetReport, DatasetRequest
from .dataset_identity import (
    assign_splits,
    evidence_identity,
    program_identity,
    request_identity,
)


class DatasetRefused(ValueError):
    pass


@dataclass(frozen=True)
class DatasetBuild:
    harness: EnterpriseEvalHarness
    metadata: dict[str, Any]
    query_transform: Callable[[PlannedEnterpriseQuery], PlannedEnterpriseQuery] | None = None


class DatasetBuilder(Protocol):
    id: str

    def __call__(self, request: DatasetRequest) -> DatasetBuild: ...


class CompanyDatasetBuilder:
    """The same company resolution, episode SDK and operational projections."""

    id = "worldloom-dataset-source/v1"

    def __call__(self, request: DatasetRequest) -> DatasetBuild:
        from .. import company, sdk
        from ..synthesis import Simulator

        source = request.source
        resolution = company.resolve(company.from_document(source.company))
        resolution.raise_for_conflicts()
        unmet = sorted(set(resolution.unmet) - set(source.acknowledged_unmet))
        if unmet:
            raise DatasetRefused("company_unmet: " + "; ".join(unmet))
        built = sdk.from_resolution(resolution, seed=request.seed).build()
        if source.period is not None:
            built = built.episodes(source.period, periods=source.periods)
        harness = EnterpriseEvalHarness.from_world(built.world).with_scenario(source.scenario)
        if source.simulation is not None and source.incident_rule is not None:
            harness = harness.with_operational_data(
                Simulator(source.simulation, seed=request.seed), source.incident_rule,
                include_world_records=False,
            ).with_operational_case_binding()
        return DatasetBuild(harness, {"company_spec": source.company, "unmet": list(resolution.unmet),
                                      "acknowledged_unmet": list(source.acknowledged_unmet)})


def _read(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key {key}")
            out[key] = value
        return out

    def invalid(value: str) -> None:
        raise ValueError(f"nonfinite JSON value {value}")

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=invalid)


def _files(root: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise DatasetRefused("dataset checkpoints cannot contain symlinks")
        if path.is_file() and path not in {root / "receipt.json", root / "manifest.json"}:
            with path.open("rb") as handle:
                found[path.relative_to(root).as_posix()] = hashlib.file_digest(handle, "sha256").hexdigest()
    return found


def _discard_pending(root: Path, request: DatasetRequest) -> Path:
    staging = root.with_name(root.name + ".pending")
    if staging.exists():
        if _read(staging / "request.json") != request.model_dump(mode="json"):
            raise DatasetRefused("unfinished batch belongs to a different generation request")
        shutil.rmtree(staging)
    return staging


def _commit_batch(root: Path, request: DatasetRequest, builder: DatasetBuilder, *, company_root: Path | None = None) -> None:
    staging = _discard_pending(root, request)
    staging.mkdir(parents=True)
    write_json(staging / "request.json", request.model_dump(mode="json"))
    try:
        # Pydantic's frozen shell does not freeze nested dictionaries. Never
        # let a proposing adapter mutate the plan or subsequent request state
        # through a shared company/configuration object.
        built = builder(request.model_copy(deep=True))
        # External authors may change source generation, never the fixed
        # selector, planning budget or admission rules in the request.
        harness = built.harness.with_scenario(request.source.scenario)
        source = request.source
        # World-free, like `EnterpriseEvalHarness.qualify`: every query in the
        # pool is executed under `strict_sources` below and refused by name in
        # the batch's own ledger, so the pool does not depend on the inventory.
        planned, _ = plan_queries(harness.world, registry=harness.registry, profile=harness.profile,
                                  strategy="exhaustive", dag_shapes=source.dag_shapes, ground=False)
        bounded = islice(planned, source.planning_budget)
        seen: set[str] = set()
        pool_list = []
        inspected = equivalent = 0
        for query in bounded:
            inspected += 1
            if built.query_transform is not None:
                query = built.query_transform(query)
            if not all(query.dimensions.get(k) == v for k, v in source.where.items()):
                continue
            task = program_identity(query)
            wording = request_identity(query.query, company_name=harness.world.company.name)
            if task in request.saturated_tasks or wording in request.saturated_requests:
                continue
            key = digest([task, wording, query.generation.model_dump(mode="json")])
            if key in seen:
                equivalent += 1
                continue
            seen.add(key)
            pool_list.append(query)
            if company_root is None and len(pool_list) == source.pool_size:
                break
        if company_root is not None and pool_list:
            start = (request.ordinal * source.pool_size) % len(pool_list)
            pool_list = (pool_list[start:] + pool_list[:start])[:source.pool_size]
        pool = tuple(pool_list)
        if not pool:
            raise DatasetRefused("no_matching_plans: no query met the cell contract within its planning budget")
        harness.world.export(staging / "world")
        if company_root is not None and _files(staging / "world") != _files(company_root / "world"):
            raise ValueError("company builder changed the canonical world; create a new revision")
        binder = harness._case_binder(pool)
        if company_root is not None and binder is not None:
            original_binder = binder

            def advance_case(query: Any, ordinal: int) -> Any:
                return original_binder(query, ordinal + request.ordinal * source.pool_size)

            binder = advance_case
        qualified = qualify_queries(harness.world, pool, pool_size=source.pool_size, pool_exhausted=False,
                                    projections=harness.projections, binder=binder)
        qualified.export(staging / "qualified")
        write_json(staging / "source.json", built.metadata)
        write_json(staging / "outcome.json", {"refusals": [r.code for r in qualified.report.refusals],
                                             "planned_candidates": inspected, "equivalent_plans_removed": equivalent})
    except DatasetRefused as error:
        write_json(staging / "outcome.json", {"refusals": [str(error).split(":", 1)[0]], "detail": str(error)})
    write_json(staging / "receipt.json", {"request_digest": digest(request.model_dump(mode="json")), "files": _files(staging)})
    staging.rename(root)


def _load_batch(root: Path, request: DatasetRequest, index: int) -> tuple[list[DatasetEntry], list[str]]:
    receipt = _read(root / "receipt.json")
    if (receipt.get("request_digest") != digest(request.model_dump(mode="json"))
            or _read(root / "request.json") != request.model_dump(mode="json")
            or receipt.get("files") != _files(root)):
        raise DatasetRefused(f"batch {index} changed after checkpoint")
    findings = list(_read(root / "outcome.json")["refusals"])
    if not (root / "qualified").exists():
        return [], findings
    from ..world import World

    corpus = load_exported_corpus(root / "qualified")
    world = World.load(root / "world")
    company_id = digest(world.company.model_dump(mode="json"))
    fixtures = {f.query_id: f for f in corpus.fixtures}
    proofs = {p.query_id: p for p in (QualificationProof.model_validate_json(line) for line in
              (root / "qualified" / "proofs.jsonl").read_text(encoding="utf-8").splitlines())}
    entries: list[DatasetEntry] = []
    for query in corpus.queries:
        fixture, proof = fixtures[query.id], proofs[query.id]
        if proof.grade.get("fails") or proof.grade.get("status") not in {"ok", "behavior"}:
            raise DatasetRefused("dataset contains a nonpassing qualification proof")
        evidence = evidence_identity(fixture, company_id)
        if not evidence:
            findings.append("no_evidence")
            continue
        entries.append(DatasetEntry(
            id=digest([request.plan_digest, index, query.id]), query_id=query.id, batch=index,
            stratum=request.stratum, task_id=program_identity(query),
            case_id=digest(evidence), evidence=evidence, company_id=company_id,
            request_id=request_identity(query.query, company_name=world.company.name),
            proof_digest=digest(proof.model_dump(mode="json")), query=query.query,
            dimensions={k: query.dimensions[k] for k in ("workflow", "source_set", "operation", "failure", "dag_shape", "output_format")},
        ))
    return entries, findings


#: The builder and packs a commit worker was started with. Set once per
#: worker process by `_start_worker`; the compiling process never reads it.
_WORKER: tuple[DatasetBuilder, dict[str, dict[str, Any]], tuple[str, ...]] | None = None


def _start_worker(builder: bytes, packs: dict[str, dict[str, Any]], roots: tuple[str, ...] = ()) -> None:
    global _WORKER
    _WORKER = (pickle.loads(builder), packs, roots)


def _commit_in_worker(root: Path, request: DatasetRequest, company_root: Path | None) -> None:
    # Context variables do not cross a process boundary: the packs in force
    # where the plan was compiled are reinstated from their recorded bodies,
    # and the pack roots searched there are searched here, so a pack that is
    # visible without being in force (a workspace's uploaded connector) is
    # visible to every worker and the output never depends on how many ran.
    assert _WORKER is not None, "commit worker was not started"
    builder, packs, roots = _WORKER
    with packkit.use(roots=roots), packkit.use_recorded(packs):
        _commit_batch(root, request, builder, company_root=company_root)


def dataset_workers(workers: int | None = None) -> int:
    """How many processes commit a wave: the argument, the environment, then policy.

    A runtime choice, never a plan field: it changes how long a compile
    takes, not one byte of what it writes.
    """
    if workers is None:
        configured = os.environ.get("WORLDLOOM_DATASET_WORKERS", "").strip()
        workers = int(configured) if configured else int(packkit.policy("dataset.workers"))
    if workers < 1:
        raise ValueError("dataset workers must be positive")
    return workers


class _Committers:
    """One single-process executor per worker, so a stratum can stay where it is warm.

    A builder caches what it derives per source (a company builder's
    operational harness costs many times one batch to build), and each worker
    holds its own cache. A wave's commits go to distinct workers first and,
    among those, to one that has already served the stratum. Placement only
    decides where the time goes: every commit is a function of its request.
    """

    def __init__(self, slots: list[Executor]) -> None:
        self.slots = slots
        self.warm: list[set[str]] = [set() for _ in slots]

    def commit(self, missing: list[tuple[Path, DatasetRequest]], company_root: Path | None) -> None:
        load = [0] * len(self.slots)
        commits = []
        for destination, request in missing:
            slot = min(range(len(self.slots)), key=lambda i: (load[i], request.stratum not in self.warm[i], i))
            load[slot] += 1
            self.warm[slot].add(request.stratum)
            commits.append(self.slots[slot].submit(_commit_in_worker, destination, request, company_root))
        for commit in commits:
            commit.result()


@contextmanager
def _committer(builder: DatasetBuilder, workers: int) -> Iterator[_Committers | None]:
    """Spawn-started worker processes for a wave's commits, or none when serial.

    Spawn, not fork, on every platform: a forked child inherits whatever
    threads and caches the parent holds, and Windows has no fork at all.
    `_commit_batch` is CPU-bound Python, so threads would not overlap it.
    """
    if workers == 1:
        yield None
        return
    import multiprocessing

    try:
        shipped = pickle.dumps(builder)
    except Exception as error:
        raise DatasetRefused(f"builder cannot cross a process boundary ({error}); compile with one worker") from error
    from ..packkit.active import roots as pack_roots

    context, packs = multiprocessing.get_context("spawn"), packkit.recorded()
    with ExitStack() as stack:
        yield _Committers([stack.enter_context(ProcessPoolExecutor(
            max_workers=1, mp_context=context, initializer=_start_worker, initargs=(shipped, packs, pack_roots())))
            for _ in range(workers)])


@dataclass(frozen=True)
class DatasetRun:
    directory: Path
    report: DatasetReport

    def raise_if_incomplete(self) -> None:
        if not self.report.complete:
            raise DatasetRefused("dataset_incomplete: " + "; ".join(self.report.findings))


def compile_dataset(
    plan: DatasetPlan, out: str | Path, *, builder: DatasetBuilder | None = None,
    batch_limit: int | None = None, replay_only: bool = False, workers: int | None = None,
) -> DatasetRun:
    """Generate, independently qualify, admit, checkpoint, split and export.

    ``batch_limit`` pauses after this many total batches, without changing the
    plan. Calling again resumes. A completed checkpoint performs no builder or
    executor calls. Single-writer directory; committed batches are immutable.

    Batches are scheduled in waves of ``plan.batch_wave`` requests drawn from
    one admission state. ``workers`` processes commit a wave's missing batches
    concurrently (`dataset_workers` resolves the default); admission then
    reads them in batch order, so the directory is the same for any count.
    """
    from .company_dataset import CompanyDatasetPlan, load_dataset_plan, prepare_company

    plan = load_dataset_plan(plan.model_dump(mode="json"))
    json.dumps(plan.model_dump(mode="json"), allow_nan=False)
    if builder is not None and builder.id != plan.builder_id and not replay_only:
        raise DatasetRefused("builder identity does not match the dataset plan")
    if batch_limit is not None and batch_limit < 1:
        raise ValueError("batch_limit must be positive")
    root = Path(out)
    plan_key = digest(plan.model_dump(mode="json"))
    if root.exists() and any(root.iterdir()):
        if _read(root / "plan.json") != plan.model_dump(mode="json"):
            raise DatasetRefused("dataset plan changed; use a new output directory")
    else:
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / "plan.json", plan.model_dump(mode="json"))
    company_root = None
    if isinstance(plan, CompanyDatasetPlan):
        builder = prepare_company(root, plan, builder, replay_only=replay_only)
        company_root = root / "company"
    else:
        builder = builder or CompanyDatasetBuilder()
    if builder.id != plan.builder_id and not replay_only:
        raise DatasetRefused("builder identity does not match the dataset plan")
    (root / "batches").mkdir(exist_ok=True)
    remaining = {s.id: s.count for s in plan.strata}
    strata = {s.id: s for s in plan.strata}
    attempts: Counter[str] = Counter()
    refusals: Counter[str] = Counter()
    tasks: Counter[str] = Counter()
    cases: Counter[str] = Counter()
    requests: Counter[str] = Counter()
    entries: list[DatasetEntry] = []
    company_keys: set[str] = set()
    exact: set[str] = set()
    budget = min(plan.max_batches, batch_limit or plan.max_batches)
    batches = 0
    planning: Counter[str] = Counter()
    wave_size = plan.batch_wave
    with _committer(builder, 1 if replay_only else min(dataset_workers(workers), wave_size)) as committer:
        # A wave's boundaries are fixed by the plan (every `batch_wave`
        # indices) and cut only by the budget, so a paused run's prefix of a
        # wave is exactly the prefix the uninterrupted run issued.
        for first in range(0, budget, wave_size):
            if not any(remaining.values()):
                break
            # Every request in a wave reads the admission state at the wave's
            # start. Attempts claimed within the wave spread it across strata
            # by the serial tie-break; a wave of one is the serial schedule.
            claimed: Counter[str] = Counter()
            wave: list[tuple[int, DatasetRequest]] = []
            for index in range(first, min(first + wave_size, budget)):
                cell = min((s for s in plan.strata if remaining[s.id]), key=lambda s: (
                    attempts[s.id] + claimed[s.id], -Fraction(remaining[s.id], s.count), s.id))
                ordinal = attempts[cell.id] + claimed[cell.id]
                claimed[cell.id] += 1
                wave.append((index, DatasetRequest(
                    plan_digest=plan_key, stratum=cell.id, ordinal=ordinal,
                    seed=int(digest([plan.seed, cell.id, ordinal])[:8], 16),
                    remaining=remaining[cell.id], source=cell.source, refusals=dict(sorted(refusals.items())),
                    saturated_tasks=tuple(sorted(k for k, v in tasks.items() if v >= plan.max_per_task)[:32]),
                    saturated_requests=tuple(sorted(k for k, v in requests.items() if v >= plan.max_per_request)[:32]),
                )))
            missing = [(root / "batches" / f"{index:08d}", request) for index, request in wave
                       if not (root / "batches" / f"{index:08d}").exists()]
            if missing and replay_only:
                raise DatasetRefused(f"replay requires committed batch {int(missing[0][0].name)}")
            if committer is None:
                for destination, request in missing:
                    _commit_batch(destination, request, builder, company_root=company_root)
            else:
                # Each commit stages under its own `<index>.pending` and renames
                # into place, so a run killed mid-wave resumes from whichever
                # of the wave's batches reached their receipts.
                committer.commit(missing, company_root)
            for index, request in wave:
                cell = strata[request.stratum]
                destination = root / "batches" / f"{index:08d}"
                pool, findings = _load_batch(destination, request, index)
                if company_root is not None and (destination / "world").exists():
                    if _files(destination / "world") != _files(company_root / "world"):
                        raise DatasetRefused("batch evidence belongs to a different company revision")
                # Recovery can encounter a copied/stale staging directory beside a
                # committed batch. Its identity must agree before discarding it, and
                # the committed receipt is verified first. Never replace good evidence
                # with an unfinished retry or accept a staging directory as a receipt.
                _discard_pending(destination, request)
                outcome = _read(destination / "outcome.json")
                planning.update({key: outcome.get(key, 0) for key in ("planned_candidates", "equivalent_plans_removed")})
                refusals.update(findings)
                # Prefer underrepresented programs and language before case variety.
                # Re-rank a bounded batch after each admission, not the whole dataset.
                while pool and remaining[cell.id]:
                    candidate = min(pool, key=lambda e: (tasks[e.task_id], requests[e.request_id], cases[e.case_id], e.id))
                    pool.remove(candidate)
                    if isinstance(plan, CompanyDatasetPlan) and plan.split_assignments and digest([candidate.stratum, candidate.query_id]) not in plan.split_assignments:
                        refusals["outside_sealed_case_set"] += 1
                        continue
                    key = digest([candidate.task_id, candidate.case_id, candidate.request_id])
                    reason = (
                        "duplicate_variant" if key in exact else
                        "task_cap" if tasks[candidate.task_id] >= plan.max_per_task else
                        "case_cap" if cases[candidate.case_id] >= plan.max_per_case else
                        "request_cap" if requests[candidate.request_id] >= plan.max_per_request else ""
                    )
                    if reason:
                        refusals[reason] += 1
                        continue
                    slots_after = sum(remaining.values()) - 1
                    if slots_after < plan.minimum_tasks - len(tasks) - int(candidate.task_id not in tasks):
                        refusals["task_minimum_reserve"] += 1
                        continue
                    if slots_after < plan.minimum_companies - len(company_keys) - int(candidate.company_id not in company_keys):
                        refusals["company_minimum_reserve"] += 1
                        continue
                    if slots_after == 0:
                        _, counts, _, _ = assign_splits([*entries, candidate], plan)
                        if any(not count for count in counts.values()):
                            refusals["split_isolation"] += 1
                            continue
                    entries.append(candidate)
                    company_keys.add(candidate.company_id)
                    exact.add(key)
                    tasks[candidate.task_id] += 1
                    cases[candidate.case_id] += 1
                    requests[candidate.request_id] += 1
                    remaining[cell.id] -= 1
                attempts[cell.id] += 1
                batches += 1
                # A small durable progress document makes interruption actionable.
                write_json(root / "progress.json", {"plan_digest": plan_key, "batches": batches,
                                                   "accepted": len(entries), "remaining": remaining})

    committed = sorted(p for p in (root / "batches").iterdir() if p.is_dir() and not p.name.endswith(".pending"))
    if len(committed) > batches:
        raise DatasetRefused("checkpoint has a batch outside the deterministic schedule or requested resume prefix")
    assignment, split_counts, groups, largest = assign_splits(entries, plan)
    companies = len({e.company_id for e in entries})
    problems = [f"quota:{key}:{value}" for key, value in sorted(remaining.items()) if value]
    if len(tasks) < plan.minimum_tasks:
        problems.append(f"tasks:{len(tasks)}<{plan.minimum_tasks}")
    if companies < plan.minimum_companies:
        problems.append(f"companies:{companies}<{plan.minimum_companies}")
    problems.extend(f"empty_split:{key}" for key, value in split_counts.items() if not value)
    report = DatasetReport(
        target=sum(s.count for s in strata.values()), accepted=len(entries), batches=batches,
        complete=not problems, remaining=remaining, refusals=dict(sorted(refusals.items())),
        tasks=len(tasks), cases=len(cases), requests=len(requests), companies=companies,
        split_counts=split_counts, split_groups=groups, largest_split_group=largest, findings=tuple(problems),
        planned_candidates=planning["planned_candidates"], equivalent_plans_removed=planning["equivalent_plans_removed"],
        facets={key: dict(sorted(Counter(e.dimensions[key] for e in entries).items()))
                for key in ("workflow", "source_set", "operation", "failure", "dag_shape", "output_format")},
    )
    write_json(root / "report.json", report.model_dump(mode="json"))
    # An incomplete run exposes review candidates but cannot look like a
    # published benchmark to a consumer opening the conventional filename.
    for name in ("queryset.jsonl", "candidates.jsonl", "agent-requests.jsonl"):
        (root / name).unlink(missing_ok=True)
    output = root / ("queryset.jsonl" if report.complete else "candidates.jsonl")
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            value = {**entry.model_dump(mode="json"), "split": assignment[entry.id],
                     "qualification": f"batches/{entry.batch:08d}/qualified"}
            if isinstance(plan, CompanyDatasetPlan):
                value["lineage"] = plan.lineage.get(entry.stratum, {})
            handle.write(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n")
    if report.complete:
        with (root / "agent-requests.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for entry in entries:
                handle.write(json.dumps({"id": entry.id, "query": entry.query, "split": assignment[entry.id]}, sort_keys=True) + "\n")
    write_json(root / "manifest.json", {"schema": plan.schema_version, "plan_digest": plan_key,
                                       "complete": report.complete, "files": _files(root)})
    return DatasetRun(root, report)


def verify_dataset(out: str | Path) -> DatasetReport:
    """Verify the published content inventory, including every batch receipt."""
    root = Path(out)
    manifest = _read(root / "manifest.json")
    from .company_dataset import load_dataset_plan

    plan = load_dataset_plan(_read(root / "plan.json"))
    report = DatasetReport.model_validate(_read(root / "report.json"))
    if (manifest.get("schema") != plan.schema_version
            or manifest.get("plan_digest") != digest(plan.model_dump(mode="json"))
            or manifest.get("complete") != report.complete or manifest.get("files") != _files(root)):
        raise DatasetRefused("dataset manifest or files changed after export")
    return report


__all__ = ["CompanyDatasetBuilder", "DatasetBuild", "DatasetBuilder", "DatasetRefused", "DatasetRun", "compile_dataset", "verify_dataset"]
