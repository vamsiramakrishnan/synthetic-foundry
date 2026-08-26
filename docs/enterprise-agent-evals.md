# Enterprise agent evaluation harness

WorldLoom can generate realistic customer requests, connector state, expected MCP DAGs, and trajectory scores from one deterministic enterprise world.

## Decision boundary

| Concern | Authored data | Harness code |
|---|---|---|
| Industry and company vocabulary | World seed and pack | Seed loading and validation |
| Connector entities, IDs, formats, operations | `ConnectorSpec` | Connector projection adapter |
| Business use cases and customer language | `WorkflowSpec` | Constraint evaluation and rendering |
| Event-to-record semantics | `ProcessSpec` | Deterministic projection engine |
| Desired interaction strength and failures | `CoverageProfile` | Covering/exhaustive planner |
| MCP server tool names and authentication | Runner configuration | Semantic-node-to-tool adapter |
| Correct execution | Expected DAG and fixture state | Trace capture and scorer |

Company names, process vocabulary, source authority, prompt wording, entity choices, format choices, and allowed routes are not planner constants. They live in specs. Code owns reusable algorithms: validation, constrained coverage, deterministic IDs, projections, failure mutation, serialization, and scoring.

## Python SDK

```python
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.world import World

world = World.load("retail-close")
corpus, coverage = (
    EnterpriseEvalHarness.from_world(world)
    .take(500)
    .build()
)

assert coverage is None or coverage.complete
```

Use `.exhaustive().take(n)` for deterministic shards/smoke sets. The exhaustive iterator does not allocate the entire space. Covering mode emits a proof report containing required interactions, covered interactions, and holes.

## CLI

```console
worldloom enterprise-evals space
worldloom enterprise-evals plan dist/retail-close queries.jsonl --strength 2
worldloom enterprise-evals plan dist/retail-close shard.jsonl --exhaustive --limit 10000
worldloom enterprise-evals validate corpus.json
```

## Query and fixture contract

Every query includes grounded customer language, dimensions, generation requirements, and an ordered semantic DAG. Materialization generates only records demanded by the plan. Failure dimensions mutate fixture state: stale versions, duplicate join candidates, missing IDs, denied principals, partial writes, and ETag conflicts.

The scorer measures required semantic calls, dependency order, write verification, provenance, and idempotency. MCP-specific tool names stay in the runner adapter so one corpus can test different MCP implementations.
