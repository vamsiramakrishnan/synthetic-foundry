"""Explain workload coverage and the evidence budget behind native experiments.

Reference qualification establishes solvability. It does not establish source
independence, balanced coverage, or evidence of an improved target. Reports use
the same validated cases and transitive lineage as the qualification vault.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..evalrun.qualification import (
    QualificationPolicy,
    SplitAudit,
    audit_splits,
    evidence_components,
    qualification_tranches,
)
from ..models import Model
from ..native_eval_bridge import native_task_cases
from ..native_query_planning import NativeWorkloadFinding
from ..providers import digest
from .requirements import (
    BenchmarkRequirements,
    RequirementCoverage,
    measure_requirements,
    requirement_deficits,
    resolve_requirements,
    task_formats,
)

if TYPE_CHECKING:
    from ..evalrun.contract import EvalCase
    from ..native_corpus import NativeCorpusResult
    from ..native_query_planning import NativeWorkload
    from ..world import World
    from .core import BenchmarkSplitRole


@dataclass(frozen=True)
class NativeAssessmentSource:
    """Canonical inputs needed to revalidate a separate held-out package."""

    world: World
    rendered: Mapping[str, NativeCorpusResult]
    workload: NativeWorkload
    namespace: str
    split_role: BenchmarkSplitRole = "unspecified"


class BenchmarkFinding(Model):
    code: str
    detail: str
    remediation: str
    blocks: tuple[Literal["execution", "coverage", "promotion"], ...] = ()


class BenchmarkCoverage(Model):
    """Task counts are descriptive; correlated tasks never buy more units."""

    name: str
    requested: bool
    tasks: int
    independent_units: int | None


class BenchmarkAssessment(Model):
    """Preflight only: ``promotion_ready`` means ready to run the experiment.

    A ready report neither promotes a candidate nor estimates its performance.
    Execution readiness applies to the delivered tasks; coverage completeness
    separately records whether the requested operations and formats were met.
    ``task_limit`` is a ceiling, never an invented minimum task requirement.
    Independence assumes the target receives only each task's declared inputs.
    """

    schema_version: Literal["worldloom.benchmark-assessment/v1"] = "worldloom.benchmark-assessment/v1"
    workload_digest: str
    namespace: str
    tasks: int
    task_limit: int
    reference_qualified: int | None
    independent_units: int | None
    used_sources: int
    used_canonical_facts: int
    operations: tuple[BenchmarkCoverage, ...]
    formats: tuple[BenchmarkCoverage, ...]
    capabilities: tuple[BenchmarkCoverage, ...]
    execution_ready: bool
    coverage_complete: bool
    promotion_ready: bool
    qualification_policy: QualificationPolicy | None = None
    required_heldout_units: int | None = None
    repeats: int | None = None
    split_audit: SplitAudit | None = None
    unassigned_tasks: int | None = None
    heldout_reference_qualified: int | None = None
    heldout_coverage_complete: bool | None = None
    findings: tuple[BenchmarkFinding, ...]
    planner_findings: tuple[NativeWorkloadFinding, ...] = ()
    requirements: BenchmarkRequirements = BenchmarkRequirements()
    required_coverage: tuple[RequirementCoverage, ...] = ()
    heldout_required_coverage: tuple[RequirementCoverage, ...] = ()
    tranche_required_coverage: tuple[tuple[RequirementCoverage, ...], ...] = ()


def assess_native_benchmark(
    world: World, rendered: Mapping[str, NativeCorpusResult], workload: NativeWorkload, *,
    namespace: str, qualification_policy: QualificationPolicy | None = None,
    training_task_ids: Sequence[str] | None = None, heldout_task_ids: Sequence[str] | None = None,
    repeats: int | None = None, heldout: NativeAssessmentSource | None = None,
    requirements: BenchmarkRequirements | None = None,
    split_role: BenchmarkSplitRole = "unspecified",
) -> BenchmarkAssessment:
    """Revalidate source bytes and contracts before counting independent units.

    A supplied split is audited exactly as ``QualificationVault.open`` audits
    it. The held-out budget is ``trials * min_units`` and repeat support comes
    from that policy; no arbitrary quality threshold is introduced here.
    """
    findings: list[BenchmarkFinding] = []

    def add(code: str, detail: str, remediation: str, *blocks: Literal["execution", "coverage", "promotion"]) -> None:
        findings.append(BenchmarkFinding(code=code, detail=detail, remediation=remediation, blocks=blocks))

    # Inspection must not certify a sealed allocation that the improvement
    # entry point rejects before invoking any target or proposer.
    if split_role == "heldout" or (heldout is not None and heldout.split_role == "training"):
        add("benchmark_split_role_conflict",
            "Benchmark split roles prohibit using held-out evidence as training or training evidence as held-out.",
            "Use the designated training and held-out packages in their sealed roles.", "promotion")

    tasks = tuple(sorted(workload.tasks, key=lambda task: task.id))
    cases: tuple[EvalCase, ...] = ()
    components: dict[str, str] | None = None
    qualified: int | None = None
    heldout_qualified: int | None = None
    heldout_coverage_complete: bool | None = None
    external_held: tuple[EvalCase, ...] = ()
    held: tuple[EvalCase, ...] = ()
    train: tuple[EvalCase, ...] = ()
    held_requirements = BenchmarkRequirements()
    required_coverage: tuple[RequirementCoverage, ...] = ()
    held_coverage: tuple[RequirementCoverage, ...] = ()
    tranche_coverage: tuple[tuple[RequirementCoverage, ...], ...] = ()
    try:
        effective_requirements = resolve_requirements(workload.plan, additional=requirements)
        held_requirements = resolve_requirements(workload.plan, *(() if heldout is None else (heldout.workload.plan,)),
            additional=requirements)
    except ValueError as error:
        effective_requirements = BenchmarkRequirements()
        add("coverage_requirements_invalid", str(error), "Give each distinct required cell a distinct name.",
            "coverage", "promotion")
    if heldout is not None:
        # The held-out package has its own declared coverage. Enough units
        # cannot qualify an experiment whose requested work is absent there.
        heldout_coverage_complete = True
        held_operations = {task.operation for task in heldout.workload.tasks}
        held_formats = {format for task in heldout.workload.tasks for format in task_formats(task)}
        for dimension, requested, delivered in (("operation", heldout.workload.plan.operations, held_operations),
                ("format", heldout.workload.plan.formats, held_formats)):
            held_missing = sorted(set(requested) - delivered)
            if held_missing:
                heldout_coverage_complete = False
                add(f"heldout_requested_{dimension}_missing",
                    f"Held-out tasks do not cover requested {dimension}s: {', '.join(held_missing)}.",
                    "Build the missing held-out work or explicitly revise its declared plan before selecting an experiment.",
                    "promotion")
        if heldout.namespace != namespace:
            add("heldout_origin_mismatch", "Training and held-out packages declare different source origins.",
                "Use the same stable company/world origin across source snapshots and format variants.", "promotion")
        try:
            external_held = native_task_cases(heldout.workload.tasks, heldout.rendered,
                namespace=heldout.namespace, world=heldout.world)
            heldout_qualified = len(external_held)
        except (ValueError, KeyError) as error:
            heldout_coverage_complete = False
            add("heldout_contract_invalid", str(error),
                "Rebuild the held-out package from accepted source bytes and canonical provenance.", "promotion")
        if training_task_ids is not None or heldout_task_ids is not None:
            add("qualification_split_conflict", "A separate held-out package and internal task assignments were both supplied.",
                "Use either two complete packages or explicit assignments within one package.", "promotion")
    if not tasks:
        add("empty_workload", "No tasks were delivered.",
            "Add supported source evidence and rebuild the workload.", "execution", "promotion")
    else:
        try:
            cases = native_task_cases(tasks, rendered, namespace=namespace, world=world)
            qualified = len(cases)
        except (ValueError, KeyError) as error:
            add("native_contract_invalid", str(error),
                "Rebuild from accepted source bytes and canonical provenance; do not edit private receipts.",
                "execution", "promotion")
        if cases:
            try:
                components = evidence_components(cases, unit_dimension=(
                    qualification_policy.unit_dimension if qualification_policy is not None else None))
            except ValueError as error:
                add("independence_unavailable", str(error),
                    "Choose a unit dimension present in every validated case, or use canonical evidence components.",
                    "promotion")
    if qualified is not None and qualified != workload.reference_qualified:
        add("qualification_count_stale", "Stored reference qualification count differs from revalidated tasks.",
            "Rebuild the workload metadata from its contracts.")

    operation_counts = Counter(task.operation for task in tasks)
    formats_by_task = {task.id: task_formats(task) for task in tasks}

    def count(name: str, requested: bool, selected: Sequence[str]) -> BenchmarkCoverage:
        return BenchmarkCoverage(name=name, requested=requested, tasks=len(selected), independent_units=(
            len({components[task_id] for task_id in selected}) if components is not None else None))

    operations = tuple(count(operation, operation in workload.plan.operations,
        [task.id for task in tasks if task.operation == operation])
        for operation in sorted(set(workload.plan.operations) | set(operation_counts)))
    delivered_formats = {format for formats in formats_by_task.values() for format in formats}
    formats = tuple(count(format, format in workload.plan.formats,
        [task.id for task in tasks if format in formats_by_task[task.id]])
        for format in sorted(set(workload.plan.formats) | delivered_formats))
    capabilities = tuple(count(f"{operation}:{format}", any(cell.operation == operation and cell.format == format
            and cell.format_role == "operation" for cell in effective_requirements.cells),
        [task.id for task in tasks if task.operation == operation and format in formats_by_task[task.id]])
        for operation in sorted(workload.plan.operations) for format in sorted(workload.plan.formats))
    for dimension, coverage in (("operation", operations), ("format", formats)):
        missing = [entry.name for entry in coverage if entry.requested and not entry.tasks]
        if missing:
            add(f"requested_{dimension}_missing", f"No tasks cover requested {dimension}s: {', '.join(missing)}.",
                f"Add source evidence supporting those {dimension}s, increase a truncating task limit, or explicitly revise the plan.",
                "coverage", "promotion")
    absent_cells = [entry.name for entry in capabilities if not entry.tasks]
    if absent_cells:
        add("operation_format_gaps", "Descriptive operation/format combinations without tasks: " + ", ".join(absent_cells) + ".",
            "Declare explicit required cells before claiming coverage of every operation/format combination.")
    present_counts = [entry.tasks for entry in operations if entry.requested]
    if present_counts and len(set(present_counts)) > 1:
        add("operation_counts_uneven", "Requested operations have unequal delivered task counts.",
            "Use the per-operation counts when comparing results; generate missing evidence before expanding weak categories.")
    if workload.truncated:
        add("task_limit_reached", f"Candidate selection was truncated at the task ceiling of {workload.plan.max_tasks}.",
            "Increase max_tasks if omitted candidates cover required operations or formats.")
    independent_units = len(set(components.values())) if components is not None else None
    if independent_units is not None and independent_units < len(tasks):
        add("shared_evidence", f"{len(tasks)} tasks reduce to {independent_units} evidence components.",
            "Place disjoint canonical sections and facts in separate task input files; paraphrases, extra assertions, and format copies do not add units.")

    audit = None
    unassigned = None
    required_units = None
    if qualification_policy is None:
        add("qualification_policy_missing", "No promotion experiment policy was supplied.",
            "Supply QualificationPolicy before selecting the held-out pool or running candidates.", "promotion")
    else:
        required_units = qualification_policy.trials * qualification_policy.min_units
        if repeats is None or repeats < qualification_policy.min_repeats:
            add("repeat_budget_insufficient", f"The policy requires at least {qualification_policy.min_repeats} paired repeats; supplied {repeats}.",
                "Predeclare enough fresh paired runs for each baseline and candidate.", "promotion")
        if heldout is not None and external_held and components is not None:
            try:
                audit = audit_splits(cases, external_held, unit_dimension=qualification_policy.unit_dimension)
                unassigned = 0
            except ValueError as error:
                add("heldout_independence_unavailable", str(error),
                    "Use a unit dimension present in every held-out case, or use canonical evidence components.", "promotion")
        elif heldout is None and (training_task_ids is None or heldout_task_ids is None):
            add("qualification_split_missing", "Explicit training and held-out task assignments were not supplied.",
                "Partition whole evidence components, then reassess both assignments together.", "promotion")
            if independent_units is not None and independent_units < required_units + 1:
                add("evidence_budget_insufficient", f"The workload has {independent_units} units; {required_units} held-out units plus a disjoint training unit are needed.",
                    "Generate more disjoint evidence; reducing task duplication cannot create new units.", "promotion")
        elif heldout is None and components is not None and training_task_ids is not None and heldout_task_ids is not None:
            train_ids, held_ids = tuple(training_task_ids), tuple(heldout_task_ids)
            known = {task.id for task in tasks}
            if (not train_ids or not held_ids or len(set(train_ids)) != len(train_ids)
                    or len(set(held_ids)) != len(held_ids) or not set(train_ids + held_ids) <= known):
                add("qualification_split_invalid", "Both splits require nonempty, distinct, known task IDs within each split.",
                    "Select task IDs from this workload and keep each split free of duplicates.", "promotion")
            else:
                by_id = {case.id: case for case in cases}
                train = tuple(by_id[task_id] for task_id in sorted(train_ids))
                held = tuple(by_id[task_id] for task_id in sorted(held_ids))
                audit = audit_splits(train, held, unit_dimension=qualification_policy.unit_dimension)
                unassigned = len(known - set(train_ids) - set(held_ids))
        if audit is not None:
            if not audit.isolated:
                add("qualification_split_leakage", f"Training and held-out tasks share {audit.overlapping_units} evidence components.",
                    "Move every connected source family to one split; renaming files or tasks does not isolate evidence.", "promotion")
            if audit.heldout_units < required_units:
                add("heldout_units_insufficient", f"The policy needs {required_units} held-out units ({qualification_policy.trials} trials x {qualification_policy.min_units}); found {audit.heldout_units}.",
                    "Expand the disjoint held-out pool or explicitly revise the policy before trials begin.", "promotion")
    if components is not None:
        training_cases = train or cases
        required_coverage = measure_requirements(training_cases, effective_requirements, components=components)
        deficits = requirement_deficits(required_coverage)
        if deficits:
            add("required_cell_units_insufficient", "; ".join(deficits),
                "Generate independent canonical evidence for each named required cell; more questions or format copies cannot supply it.",
                "coverage", "promotion")
    elif effective_requirements.cells:
        add("required_cell_support_unavailable", "Required cell support cannot be measured without validated independent evidence.",
            "Repair the source contracts or the independent-unit dimension before claiming required coverage.",
            "coverage", "promotion")
    held_cases = external_held or held
    if qualification_policy is not None and held_cases:
        try:
            held_components = evidence_components(held_cases, unit_dimension=qualification_policy.unit_dimension)
            heldout_coverage_complete = heldout_coverage_complete is not False
            held_coverage = measure_requirements(held_cases, held_requirements, components=held_components,
                min_units=qualification_policy.min_units, multiplier=qualification_policy.trials)
            deficits = requirement_deficits(held_coverage)
            if deficits:
                heldout_coverage_complete = False
                add("heldout_required_cell_units_insufficient", "; ".join(deficits),
                    "Expand each named cell with disjoint evidence sufficient for every fresh held-out trial.", "promotion")
            tranches = qualification_tranches(held_cases, policy=qualification_policy)
            by_id = {case.id: case for case in held_cases}
            tranche_coverage = tuple(measure_requirements(tuple(by_id[case_id] for case_id in tranche),
                held_requirements, components=held_components, min_units=qualification_policy.min_units)
                for tranche in tranches)
            for index, measured in enumerate(tranche_coverage, start=1):
                deficits = requirement_deficits(measured)
                if deficits:
                    heldout_coverage_complete = False
                    add("heldout_tranche_cell_units_insufficient", f"Fresh tranche {index}: " + "; ".join(deficits),
                        "Add independent source families that cover the required work in every deterministic fresh tranche.", "promotion")
        except ValueError as error:
            heldout_coverage_complete = False
            add("heldout_requirement_support_unavailable", str(error),
                "Supply enough validated independent evidence to measure all fresh cohorts.", "promotion")
    source_ids = sorted({item.artifact_id for task in tasks for item in task.inputs})
    source_facts = {fact_id for source_id in source_ids if source_id in rendered
        for entry in rendered[source_id].manifest.evidence for fact_id in entry.fact_ids}
    return BenchmarkAssessment(workload_digest=digest(workload.model_dump(mode="json")), namespace=namespace,
        tasks=len(tasks), task_limit=workload.plan.max_tasks, reference_qualified=qualified,
        independent_units=independent_units, used_sources=len(source_ids), used_canonical_facts=len(source_facts),
        operations=operations, formats=formats, capabilities=capabilities,
        execution_ready=not any("execution" in finding.blocks for finding in findings),
        coverage_complete=not any("coverage" in finding.blocks for finding in findings),
        promotion_ready=not any("promotion" in finding.blocks for finding in findings),
        qualification_policy=qualification_policy, required_heldout_units=required_units, repeats=repeats,
        split_audit=audit, unassigned_tasks=unassigned, heldout_reference_qualified=heldout_qualified,
        heldout_coverage_complete=heldout_coverage_complete,
        requirements=effective_requirements, required_coverage=required_coverage,
        heldout_required_coverage=held_coverage, tranche_required_coverage=tranche_coverage,
        findings=tuple(sorted(findings, key=lambda finding: (finding.code, finding.detail))),
        planner_findings=tuple(sorted(workload.findings, key=lambda finding: (
            finding.code, finding.artifact_id or "", finding.operation or "", finding.detail))))


__all__ = ["BenchmarkAssessment", "BenchmarkCoverage", "BenchmarkFinding", "NativeAssessmentSource", "assess_native_benchmark"]
