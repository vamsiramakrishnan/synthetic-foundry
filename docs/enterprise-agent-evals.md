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
from worldloom.enterprise_specs import ScenarioProfile
from worldloom.world import World

world = World.load("retail-close")
profile = ScenarioProfile.model_validate_json(
    Path("examples/enterprise-evals/financial-services.json").read_text()
)
corpus, coverage = (
    EnterpriseEvalHarness.from_world(world)
    .with_scenario(profile)
    .take(500)
    .build()
)

assert coverage is None or coverage.complete
```

Use `.exhaustive().take(n)` for deterministic shards/smoke sets. The exhaustive iterator does not allocate the entire space. Covering mode emits a proof report containing required interactions, covered interactions, and holes.

The planner plans only rows the world can ground. For each source a workflow
names it counts the records the world offers that carry a fact or a pinned
observation, and a source with fewer than its role's minimum is left out of
the candidate space. The report's `ungroundable_sources` names those sources.
A world that grounds no row of any selected workflow is refused as
`ungroundable_world`. `space` has no world and counts the whole space.

## CLI

```console
worldloom enterprise-evals space
worldloom enterprise-evals plan dist/retail-close queries.jsonl --strength 2
worldloom enterprise-evals plan dist/retail-close shard.jsonl --exhaustive --limit 10000
worldloom enterprise-evals build dist/retail-close dist/enterprise-evals --exhaustive --limit 500 --render-limit 50 --profile examples/enterprise-evals/omnichannel-retailer.json
worldloom enterprise-evals validate dist/enterprise-evals
worldloom enterprise-evals simulate dist/enterprise-evals --limit 500
worldloom enterprise-evals score query.json trace.json --fixture fixture.json
```

## Query and fixture contract

Every query includes grounded customer language, dimensions, generation requirements, and an ordered semantic DAG. Materialization generates only records demanded by the plan. Failure dimensions mutate fixture state: stale versions, duplicate join candidates, missing IDs, denied principals, partial writes, and ETag conflicts.

The scorer measures required semantic calls, dependency order, write verification, provenance, and idempotency. MCP-specific tool names stay in the runner adapter so one corpus can test different MCP implementations.

`ConnectorProjectionRegistry` is the extension point for company-specific or custom connectors. `RunnerConfig` binds semantic DAG nodes to concrete MCP tool names. `execute_query` checkpoints after every node, stops on failed writes, and resumes safely from deterministic query and node IDs.

`render_corpus_artifacts` produces real XLSX, DOCX, PPTX, and PDF files. XLSX output contains structured evidence, chart data, a native chart, and provenance; PPTX output includes native charts and source slides. Optional imports preserve the package's bare-install contract.

`ConnectorSimulator` is an executable in-memory MCP target for harness tests. It applies fixture permissions, stale versions, missing identifiers, ambiguous joins, partial writes, version conflicts, idempotent writes, and dependency-based readback instead of merely carrying failure labels.

## Running an agent and grading three axes

`worldloom evalrun run dist/enterprise-evals -o ./runs/reference` executes an
agent over the compiled rows through the same tool surface `serve` exposes and
grades plan, trajectory and outcomes separately, with the assertion grade
beside them. See [eval execution](eval-execution.md).

## External connector agents

`worldloom enterprise-evals serve dist/enterprise-evals --check` validates the
connector server configuration. Remove `--check` to serve StreamableHTTP at
`http://127.0.0.1:8000/mcp`. Each external agent run has isolated fixture state,
captured connector spans and the same assertion grader as local execution.
See [connector serving](connector-serving.md) for the SDK, per-principal bearer
authentication, limits, trace retrieval and Gemini Enterprise setup.
The fixture pins the exact facts in the selected input records. `score --fixture`
measures their coverage from successful source reads and penalizes invented IDs.
Without a fixture, provenance is unverified and scores zero. Older exports without
`expected_fact_ids` must be materialized again before validation. Selection now
honors `SourceRequirement.minimum`; both reference runtimes read every selected
record instead of silently obligating three records and reading one.

Operational projections use a separate `SYNOBS:` observation namespace. Their
recipe and program digests, scope, record identities, consecutive history and
values are checked and pinned in `expected_evidence_ids`. This verifies local
history integrity. It does not replay an unavailable synthesis ledger or prove
that operational totals reconcile with the World's financial facts. A placeholder
with neither fact evidence nor valid operational observations fails validation;
`strict_sources` remains opt-in.

Simulation reports each query's finding and one of `completed`,
`blocked_at_designed_write`, `stopped_before_failure_point`, or `raised`.
Permission and version failures target the intended destination; missing stable
IDs stop at the source. A partial write applies the mutation, then returns 207,
with its writes and post-state preserved for reconciliation. Compiled rows declare
an exact `failure_at` assertion and block dependent nodes while independent
branches remain executable. Changing the failure kind, writing another target,
or continuing a blocked descendant fails the grade. Ambiguous joins and stale
sources remain data perturbations; they do not yet prove that an agent resolved
ambiguity or selected an authoritative replacement.

For typed DAGs, simulation executes the grammar and reports `assertion_grade`
per query, plus `assertion_passed` and `assertion_failed` totals. Its `dag_score`
is null. `average_dag_score` averages only the legacy weighted scores and is
null when no legacy rows ran; it never treats an assertion pass as a numeric
weighted score. See [the DAG grammar](enterprise-dag-grammar.md) and the
[implementation measurements](enterprise-execution-status.md).
