from dataclasses import replace

from worldloom.eval_candidates import generate_candidates
from worldloom.eval_design import EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement
from worldloom.eval_instances import bind_eval_instance
from worldloom.eval_reference import ExecutionStep, ProofStatus, execute_isolated, execute_reference
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _build(plan):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03"))


def _instance(*, write: bool = False):  # type: ignore[no-untyped-def]
    step = EvalStepSpec(
        id="act" if write else "find",
        capability="create_issue" if write else "find_evidence",
        operation="create" if write else "find",
        effect="write" if write else "read",
    )
    spec = EvalSpec(
        id="EVALSPEC-REFERENCE-WRITE" if write else "EVALSPEC-REFERENCE-READ",
        capability=step.capability,
        persona="controller",
        request_template="Execute the task.",
        steps=(step,),
        requirements=(WorldRequirement(id="facts", kind=RequirementKind.FACT),),
        candidate_count=1,
    )
    candidate = generate_candidates(spec, _build, count=1)[0]
    return candidate.world, bind_eval_instance(spec, candidate)


def test_reference_execution_proves_read_task() -> None:
    world, instance = _instance()

    def executor(current, step, bound):  # type: ignore[no-untyped-def]
        return current, ExecutionStep(
            step_id=step.id,
            operation=step.operation or step.capability,
            output_ids=bound.oracle.fact_ids,
        )

    proof = execute_reference(instance, world, executor)

    assert proof.status == ProofStatus.PROVEN_EXECUTABLE
    assert proof.steps[0].output_ids
    assert all(result.passed for result in proof.assertion_results)


def test_write_task_requires_observed_effect() -> None:
    world, instance = _instance(write=True)

    def no_effect(current, step, bound):  # type: ignore[no-untyped-def]
        return current, ExecutionStep(step_id=step.id, operation="create")

    proof = execute_reference(instance, world, no_effect)

    assert proof.status == ProofStatus.PROVEN_UNSAT
    assert any(result.assertion_type == "side_effect_occurred" and not result.passed for result in proof.assertion_results)


def test_each_eval_starts_from_same_world_snapshot() -> None:
    world, instance = _instance()
    seen_periods = []

    def executor(current, step, bound):  # type: ignore[no-untyped-def]
        seen_periods.append(current.period)
        changed = replace(current, period="2099-12")
        return changed, ExecutionStep(
            step_id=step.id,
            operation=step.operation or step.capability,
            output_ids=bound.oracle.fact_ids,
        )

    proofs = execute_isolated((instance, instance), world, executor)

    assert [proof.status for proof in proofs] == [
        ProofStatus.PROVEN_EXECUTABLE,
        ProofStatus.PROVEN_EXECUTABLE,
    ]
    assert seen_periods == [world.period, world.period]
    assert world.period != "2099-12"


def test_reference_execution_rejects_wrong_world_seed() -> None:
    world, instance = _instance()
    wrong = replace(world, seed=(world.seed or 0) + 1)

    proof = execute_reference(
        instance,
        wrong,
        lambda current, step, bound: (
            current,
            ExecutionStep(step_id=step.id, operation=step.operation or step.capability),
        ),
    )

    assert proof.status == ProofStatus.INVALID
    assert "does not match" in proof.failure
