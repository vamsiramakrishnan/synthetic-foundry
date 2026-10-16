"""Measure declared cells using whole canonical evidence components."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ..evalrun.qualification import evidence_components
from ..models import Model
from ..native_requirements import (
    BenchmarkRequirements,
    CoverageDimension,
    CoverageRequirement,
)
from ..native_tasks import NativeTask

if TYPE_CHECKING:
    from ..evalrun.contract import EvalCase
    from ..native_query_planning import NativeWorkloadPlan


class RequirementCoverage(Model):
    name: str
    requirement: CoverageRequirement
    tasks: int
    independent_units: int | None
    required_units: int
    satisfied: bool


def task_formats(task: NativeTask, *, role: str = "operation") -> frozenset[str]:
    """Read/analyze formats are inputs; update/create formats are outputs."""
    selected_role = ("input" if task.operation in ("read", "analyze") else "output") if role == "operation" else role
    formats = {item.format for item in task.inputs} if selected_role in ("input", "any") else set()
    if selected_role in ("output", "any") and task.output is not None:
        formats.add(task.output.format)
    return frozenset(formats)


def resolve_requirements(*plans: NativeWorkloadPlan,
                         additional: BenchmarkRequirements | None = None) -> BenchmarkRequirements:
    """Declared axes remain required; explicit intersections add hard demands."""
    cells: dict[str, CoverageRequirement] = {}
    requested = [CoverageRequirement(name="operation:" + operation, operation=operation)
        for operation in sorted({operation for plan in plans for operation in plan.operations})]
    requested.extend(CoverageRequirement(name="format:" + format, format=format)
        for format in sorted({format for plan in plans for format in plan.formats}))
    requested.extend(cell for plan in plans if plan.requirements is not None for cell in plan.requirements.cells)
    if additional is not None:
        requested.extend(additional.cells)
    for cell in requested:
        previous = cells.get(cell.name)
        if previous is not None:
            if previous.model_copy(update={"min_independent_units": cell.min_independent_units}) != cell:
                raise ValueError("coverage requirement name has conflicting selectors: " + cell.name)
            cell = cell.model_copy(update={"min_independent_units": max(previous.min_independent_units, cell.min_independent_units)})
        cells[cell.name] = cell
    return BenchmarkRequirements(cells=tuple(cells[name] for name in sorted(cells)))


def _matches(task: NativeTask, dimensions: Mapping[str, str], requirement: CoverageRequirement) -> bool:
    return ((requirement.operation is None or task.operation == requirement.operation)
        and (requirement.format is None or requirement.format in task_formats(task, role=requirement.format_role))
        and (requirement.calculation is None or any(assertion.calculation is not None
            and assertion.calculation.operation == requirement.calculation for assertion in task.assertions))
        and (requirement.scope is None or (len(task.inputs) > 1) == (requirement.scope == "cross_artifact"))
        and all(dimensions.get(item.name) == item.value for item in requirement.dimensions))


def measure_requirements(cases: Sequence[EvalCase], requirements: BenchmarkRequirements, *,
                         unit_dimension: str | None = None, min_units: int = 1,
                         multiplier: int = 1,
                         components: Mapping[str, str] | None = None) -> tuple[RequirementCoverage, ...]:
    """Count cells within the full validated pool's transitive evidence closure.

    Never recompute independence from a filtered capability subset: another
    case may connect two apparently separate members of that subset.
    """
    units = evidence_components(cases, unit_dimension=unit_dimension) if components is None else components
    tasks = [(case, NativeTask.model_validate(case.row["native_task"])) for case in cases]
    coverage = []
    for cell in requirements.cells:
        selected = [case.id for case, task in tasks if _matches(task, case.dimensions, cell)]
        independent = len({units[case_id] for case_id in selected})
        required = max(cell.min_independent_units, min_units) * multiplier
        coverage.append(RequirementCoverage(name=cell.name, requirement=cell, tasks=len(selected),
            independent_units=independent, required_units=required, satisfied=independent >= required))
    return tuple(coverage)


def requirement_deficits(coverage: Sequence[RequirementCoverage]) -> tuple[str, ...]:
    return tuple(f"{cell.name}: requires {cell.required_units} independent units; found {cell.independent_units}"
        for cell in coverage if not cell.satisfied)


__all__ = ["BenchmarkRequirements", "CoverageDimension", "CoverageRequirement", "RequirementCoverage",
    "measure_requirements", "requirement_deficits", "resolve_requirements", "task_formats"]
