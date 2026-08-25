# Agent workflow evaluations

The existing evals.jsonl measures retrieval. Enterprise agents also change
state: they update risk registers, create incident reviews, refresh steering
packs, and write identifiers back to business systems. Those cases need a DAG
and a side-effect contract rather than a single expected answer.

The worldloom.agent_evals module compiles customer-natural requests and hidden
MCP plans from a world's facts, artifacts, identities, and reporting period.

Python usage:

    from worldloom import World
    from worldloom.agent_evals import WorkflowSeed, export_agent_evals

    world = World.load("./corpus")
    export_agent_evals(
        world,
        "./corpus/agent-evals.jsonl",
        WorkflowSeed(
            workflows=("incident_review", "risk_register", "customer_health"),
            destinations=("sharepoint", "drive", "confluence"),
            max_cases=100,
        ),
    )

Each row contains the customer request, persona, typed MCP DAG, source
artifacts, canonical acceptance facts, mutation target, idempotency rule, and
post-write assertions.

## Multiplication boundary

The expansion is:

    business workflow
      x world facts and entities
      x destination
      x create or update
      x DAG topology
      x verification policy

The request names the cohort, time window, reconciliation rule, deliverable,
and destination. Formats appear only when a person would name the artifact.
Entity representations and MCP tool names stay in the hidden execution plan.

## Invariants

- Every case is grounded in facts reachable from a world artifact.
- Every write is restricted to the synthetic namespace.
- Every write carries an idempotency key derived from the case ID.
- Every mutation has a dependent verification read.
- Ambiguous joins are rejected rather than guessed.
- Delete workflows are excluded until tombstone and recovery assertions exist.

The initial API writes agent-evals.jsonl alongside a corpus without changing
World serialisation. A later schema change can make it an optional World ledger
after connector projection manifests and trajectory validation land.
