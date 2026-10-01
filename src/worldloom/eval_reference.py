"""Reference execution proofs for eval-first campaigns.

A candidate that satisfies static world requirements is not automatically an
executable benchmark. This module runs the abstract task DAG against an isolated
World branch and scores the instance's derived assertions over a typed trace.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from .eval_design import EvalStepSpec
from .eval_instances import EvalAssertion, EvalInstance
from .models import Model

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


class ProofStatus(StrEnum):
    UNPROVEN = "unproven"
    PROVEN_EXECUTABLE = "proven_executable"
    PROVEN_UNSAT = "proven_unsat"
    INVALID = "invalid"


class ExecutionStep(Model):
    step_id: str
    operation: str
    input_ids: tuple[str, ...] = ()
    output_ids: tuple[str, ...] = ()
    effect_ids: tuple[str, ...] = ()


class AssertionResult(Model):
    assertion_index: int
    assertion_type: str
    passed: bool
    detail: str = ""


class ExecutionProof(Model):
    eval_instance_id: str
    candidate_seed: int
    status: ProofStatus
    steps: tuple[ExecutionStep, ...] = ()
    assertion_results: tuple[AssertionResult, ...] = ()
    failure: str = ""


StepExecutor = Callable[["World", EvalStepSpec, EvalInstance], tuple["World", ExecutionStep]]


def _world_ids(world: World) -> set[str]:
    ids = set(world.facts.ids()) | set(world.events.ids()) | set(world.artifact_intents.ids())
    ids |= {policy.id for policy in world.access_policies}
    return ids


def _assertion_result(
    index: int,
    assertion: EvalAssertion,
    trace: Sequence[ExecutionStep],
    instance: EvalInstance,
    world: World,
) -> AssertionResult:
    positions = {step.step_id: position for position, step in enumerate(trace)}
    by_step = {step.step_id: step for step in trace}
    passed = False
    detail = ""

    if assertion.type == "dag_acyclic":
        passed = len(positions) == len(trace)
    elif assertion.type == "order":
        passed = (
            assertion.before in positions
            and assertion.after in positions
            and positions[assertion.before] < positions[assertion.after]
        )
    elif assertion.type == "capability_invoked":
        step = by_step.get(assertion.step_id or "")
        declaration = next((item for item in instance.steps if item.id == assertion.step_id), None)
        expected_operation = assertion.operation or assertion.capability
        operation_ok = bool(
            step and (expected_operation is None or step.operation == expected_operation)
        )
        # Scoped IDs constrain which evidence came back; an empty binding
        # does not waive the operation's need to return evidence. In
        # particular, connectorless custom executors cannot prove a read or
        # computation by reporting only its name. Writes instead prove their
        # observed effects through side_effect_occurred.
        requires_output = declaration is not None and declaration.effect in {"read", "transform", "verify"}
        evidence_ok = bool(
            step and (not requires_output or step.output_ids)
            and set(assertion.evidence_ids) <= set(step.output_ids)
        )
        passed = operation_ok and evidence_ok
    elif assertion.type == "side_effect_occurred":
        step = by_step.get(assertion.step_id or "")
        passed = bool(step and step.effect_ids)
    elif assertion.type == "verification_performed":
        step = by_step.get(assertion.step_id or "")
        # Merely naming a verification is not a readback. The executor must
        # return observed evidence, including effects of writes this step
        # depends on when they occur on the same connector.
        declarations = {item.id: item for item in instance.steps}
        declaration = declarations.get(assertion.step_id or "")
        observed_effects: set[str] = set()
        pending = list(declaration.depends_on) if declaration is not None else []
        visited: set[str] = set()
        while pending:
            ancestor = pending.pop()
            if ancestor in visited:
                continue
            visited.add(ancestor)
            parent = declarations.get(ancestor)
            if parent is not None:
                pending.extend(parent.depends_on)
                if declaration is not None and parent.connector == declaration.connector:
                    executed = by_step.get(ancestor)
                    if executed is not None:
                        observed_effects.update(executed.effect_ids)
        passed = bool(step and step.output_ids and observed_effects <= set(step.output_ids))
    elif assertion.type == "world_requirement_satisfied":
        evidence = set(assertion.evidence_ids)
        oracle_evidence = set(instance.oracle.evidence_by_requirement.get(assertion.requirement_id or "", ()))
        passed = bool(evidence) and evidence <= oracle_evidence
    elif assertion.type == "evidence_grounded":
        passed = set(assertion.evidence_ids) <= _world_ids(world)
    else:  # pragma: no cover - EvalAssertion is a closed Literal vocabulary
        detail = "unknown assertion type"

    if not passed and not detail:
        detail = assertion.model_dump_json()
    return AssertionResult(
        assertion_index=index,
        assertion_type=assertion.type,
        passed=passed,
        detail=detail,
    )


def execute_reference(
    instance: EvalInstance,
    world: World,
    executor: StepExecutor,
) -> ExecutionProof:
    """Execute one eval against an isolated branch of *world*.

    ``World`` is immutable, so the caller's object is the snapshot. The executor
    may return derived World values after writes; those values remain local to
    this proof and cannot affect a later eval.
    """

    if world.seed != instance.candidate_seed:
        return ExecutionProof(
            eval_instance_id=instance.id,
            candidate_seed=instance.candidate_seed,
            status=ProofStatus.INVALID,
            failure=f"world seed {world.seed!r} does not match instance seed {instance.candidate_seed}",
        )

    current = world
    trace: list[ExecutionStep] = []
    try:
        for step in instance.steps:
            current, executed = executor(current, step, instance)
            if executed.step_id != step.id:
                raise ValueError(f"executor returned step {executed.step_id!r} for {step.id!r}")
            trace.append(executed)
    except Exception as error:  # executor boundary: failure becomes proof data
        return ExecutionProof(
            eval_instance_id=instance.id,
            candidate_seed=instance.candidate_seed,
            status=ProofStatus.PROVEN_UNSAT,
            steps=tuple(trace),
            failure=f"{type(error).__name__}: {error}",
        )

    results = tuple(
        _assertion_result(index, assertion, trace, instance, current)
        for index, assertion in enumerate(instance.assertions)
    )
    failed = tuple(result for result in results if not result.passed)
    return ExecutionProof(
        eval_instance_id=instance.id,
        candidate_seed=instance.candidate_seed,
        status=ProofStatus.PROVEN_EXECUTABLE if not failed else ProofStatus.PROVEN_UNSAT,
        steps=tuple(trace),
        assertion_results=results,
        failure="" if not failed else f"{len(failed)} assertion(s) failed",
    )


def execute_isolated(
    instances: Sequence[EvalInstance],
    world: World,
    executor: StepExecutor,
) -> tuple[ExecutionProof, ...]:
    """Execute every instance from the same immutable starting world."""

    return tuple(execute_reference(instance, world, executor) for instance in instances)


__all__ = [
    "AssertionResult",
    "ExecutionProof",
    "ExecutionStep",
    "ProofStatus",
    "StepExecutor",
    "execute_isolated",
    "execute_reference",
]
