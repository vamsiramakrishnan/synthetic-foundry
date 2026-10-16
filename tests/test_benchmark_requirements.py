"""Declared evidence demands distinguish input work from generated outputs."""
from __future__ import annotations

import pytest

from worldloom.benchmarks.requirements import (
    BenchmarkRequirements,
    CoverageRequirement,
    measure_requirements,
    resolve_requirements,
)
from worldloom.evalrun.contract import (
    EvalCase,
    OutcomeContract,
    PlanContract,
    TrajectoryContract,
)
from worldloom.native_query_planning import NativeWorkloadPlan
from worldloom.native_tasks import (
    NativeAssertion,
    NativeCitation,
    NativeInput,
    NativeOutput,
    NativeTask,
)


def _case(task: NativeTask, *facts: str) -> EvalCase:
    return EvalCase(id=task.id, query="Inspect the native evidence.", plan=PlanContract(nodes=(), edges=()), trajectory=TrajectoryContract(),
        outcomes=OutcomeContract(), dimensions={"source_namespace": "test-company", "source_digest": "snapshot"},
        row={"native_task": task.model_dump(mode="json"), "expected_fact_ids": list(facts)})


def test_creation_does_not_claim_the_format_of_its_input_as_an_output() -> None:
    task = NativeTask(id="create-sheet", operation="create", inputs=(NativeInput(artifact_id="slides", format="pptx", path="slides.pptx"),),
        output=NativeOutput(artifact_id="sheet", format="xlsx", assertions=(NativeAssertion(id="result",
            target=NativeCitation(artifact_id="sheet", locator="sheet:1/A1"), expected="Revenue"),)))
    requirements = BenchmarkRequirements(cells=(
        CoverageRequirement(name="creates-slides", operation="create", format="pptx"),
        CoverageRequirement(name="creates-sheets", operation="create", format="xlsx"),
        CoverageRequirement(name="consumes-slides", operation="create", format="pptx", format_role="input"),
        CoverageRequirement(name="touches-slides", operation="create", format="pptx", format_role="any"),
    ))
    measured = {cell.name: cell for cell in measure_requirements((_case(task, "fact-a"),), requirements)}
    assert not measured["creates-slides"].satisfied and measured["creates-slides"].tasks == 0
    assert all(measured[name].satisfied for name in ("creates-sheets", "consumes-slides", "touches-slides"))


def test_cell_subsets_retain_full_pool_transitive_independence() -> None:
    def task(identifier: str, operation: str) -> NativeTask:
        source = NativeInput(artifact_id=identifier, format="docx", path=identifier + ".docx")
        if operation == "read":
            return NativeTask(id=identifier, operation="read", inputs=(source,), assertions=(NativeAssertion(id="read",
                target=NativeCitation(artifact_id=identifier, locator="paragraph:1")),))
        return NativeTask(id=identifier, operation="create", inputs=(source,), output=NativeOutput(artifact_id="output",
            format="docx", assertions=(NativeAssertion(id="write", expected="value",
                target=NativeCitation(artifact_id="output", locator="paragraph:1")),)))

    cases = (_case(task("read-a", "read"), "fact-a"), _case(task("read-b", "read"), "fact-b"),
        _case(task("join", "create"), "fact-a", "fact-b"))
    demand = BenchmarkRequirements(cells=(CoverageRequirement(name="read-support", operation="read", min_independent_units=2),))
    cell = measure_requirements(cases, demand)[0]
    assert cell.tasks == 2 and cell.independent_units == 1 and not cell.satisfied


def test_conflicting_requirement_names_are_rejected_and_minima_only_strengthen() -> None:
    plan = NativeWorkloadPlan(use_case_id="test", objective="Read documents.", formats=("docx",), operations=("read",),
        requirements=BenchmarkRequirements(cells=(CoverageRequirement(name="read-demand", operation="read", min_independent_units=3),)))
    stricter = resolve_requirements(plan, additional=BenchmarkRequirements(cells=(
        CoverageRequirement(name="read-demand", operation="read", min_independent_units=1),)))
    assert next(cell for cell in stricter.cells if cell.name == "read-demand").min_independent_units == 3
    with pytest.raises(ValueError, match="conflicting selectors"):
        resolve_requirements(plan, additional=BenchmarkRequirements(cells=(
            CoverageRequirement(name="read-demand", operation="analyze"),)))
