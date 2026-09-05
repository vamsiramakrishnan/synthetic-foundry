# Reference execution and world forks

Status: design contract.

## Why

Static world predicates prove that evidence exists. They do not prove that an agent task can be executed.

A benchmark row should enter the evaluation set only after a reference implementation can complete the task against an isolated fork of the candidate world.

## Execution states

```text
UNPROVEN
PROVEN_EXECUTABLE
PROVEN_UNSAT
INVALID
```

`PROVEN_EXECUTABLE` means the reference executor completed the declared task DAG and every oracle assertion passed.

`PROVEN_UNSAT` means the world is internally valid but cannot satisfy the task as designed.

`INVALID` means the eval or world violates a contract before execution.

## Fork contract

Each eval executes against the same initial accepted world state.

```text
W0
 +-- fork A -> task A -> trace A -> discard
 +-- fork B -> task B -> trace B -> discard
 `-- fork C -> task C -> trace C -> discard
```

A fork must isolate writes. Evaluation A cannot create, close, assign, or edit an object that changes the starting state of evaluation B.

The first implementation may use an in-memory copy because Worldloom worlds are deterministic data structures. External connector fixtures can later map this semantic contract to snapshots or resettable namespaces.

## Trace

Reference execution should produce a typed trace rather than prose.

```python
class ExecutionStep(Model):
    step_id: str
    operation: str
    input_ids: tuple[str, ...]
    output_ids: tuple[str, ...]
    effect_ids: tuple[str, ...]

class ExecutionProof(Model):
    eval_instance_id: str
    candidate_seed: int
    status: ProofStatus
    steps: tuple[ExecutionStep, ...]
    assertion_results: tuple[AssertionResult, ...]
```

The trace should contain IDs and effects sufficient to reproduce the proof. It should not depend on an LLM explanation.

## Reads and writes

Read steps prove that the required evidence is reachable under the persona's access policy.

Write steps prove both preconditions and effects. For example, a `create` eval should verify that the target does not already exist where uniqueness is part of the task, execute the creation in the fork, and assert the created record's fields and links.

## Branches and parallelism

The reference executor follows the abstract task DAG, not the natural-language realization.

Ordering, branching, fan-out, and fan-in are therefore testable properties. Independent steps may execute in either valid topological order; assertions should encode only ordering that the DAG actually requires.

## Frozen clock

Execution uses candidate world time. Relative predicates and write timestamps must not read the machine clock.

A fork inherits the candidate clock. Time advances only through an explicit simulated-time operation.

## Failure reporting

A failed proof should identify the smallest useful boundary:

```text
step=resolve-approved-forecast
operation=search
reason=no accessible record satisfies predicate
```

or:

```text
assertion=created-change-links-incident
expected=INC-42
observed=()
```

This feedback is useful to the demand/tactic planner. It must not silently mutate the eval or lower the assertion.

## Relationship to candidate validation

Candidate validation and reference execution are separate gates.

```text
world requirements pass
        |
        v
oracle binds
        |
        v
reference execution
```

A world can satisfy every static requirement and still produce an unexecutable eval because of access, ordering, write preconditions, or an incorrect task DAG. Keeping the gates separate makes that defect visible.
