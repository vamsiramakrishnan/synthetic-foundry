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
- Delete workflows are excluded from this legacy planner. The DAG grammar's
  `delete_chain` shape plans them, graded on the record being gone and its
  readback failing; see [eval execution](eval-execution.md).

The initial API writes agent-evals.jsonl alongside a corpus without changing
World serialisation. A later schema change can make it an optional World ledger
after connector projection manifests and trajectory validation land.

## Connector projections and verbs

The worldloom.connector_data module projects the same world events, facts,
people, systems, services, and artifacts into coherent Jira issues, ServiceNow
incidents and changes, and email threads. Stable cross-system keys make joins
testable rather than guessed.

Connector verbs describe state access: search, list, read, create, update,
patch, upsert, delete, comment, attach, link, unlink, draft, send, reply, and
forward. Content verbs describe
reasoning over retrieved content: summarize, extract, classify, compare,
reconcile, transform, generate, render, and convert. An email summary is therefore an email.read node
followed by content.extract and content.summarize nodes.

Generate and create are not synonyms. Generate produces content. Create
persists a new entity. Update retains entity identity. Patch changes named
fields or ranges. Upsert requires a stable key. Modify is rejected as a
canonical protocol verb and normalised to update for stored records or
transform for in-memory content.

## Query-first generation

Use `worldloom.enterprise_queries.plan_queries` to plan executable workflows,
then `worldloom.enterprise_corpus.materialize_corpus` to bind their source and
destination records. Each query carries `generation` requirements and an
`expected_dag`. The planner admits only combinations allowed by its connector
and workflow registry.

    from worldloom import World
    from worldloom.enterprise_queries import plan_queries
    from worldloom.enterprise_corpus import materialize_corpus, validate_corpus

    world = World.load("./corpus")
    queries, coverage = plan_queries(world, strategy="exhaustive", limit=100)
    generated = materialize_corpus(world, queries, strict_sources=True)
    assert not validate_corpus(generated)

Exhaustive mode streams a deterministic prefix when `limit` is set. Covering
mode walks the valid candidate stream and stops when the requested interactions
are covered or the selection limit is reached. `CoverageReport.complete`,
`exact` and `truncated` distinguish a proved cover from a bounded prefix. Use a
narrowed `ScenarioProfile` to control the declared space. Size the selection before planning:

```bash
worldloom enterprise-evals space --profile examples/enterprise-evals/omnichannel-retailer.json --max-candidates 100000
worldloom enterprise-evals plan ./corpus queries.jsonl --profile examples/enterprise-evals/omnichannel-retailer.json --exhaustive --limit 100
```

`space` uses the profile's candidate ceiling unless `--max-candidates` overrides
it. `exhaustive: true` means the count is exact. Otherwise `at_least` is the
number of witnessed candidates, including one beyond the ceiling; it is a
lower bound, not a coverage claim. Unknown connectors and selections admitting
no workflow are refused by the same validation used by `plan` and `build`.

## Migration from the removed flat planner

`worldloom.query_planning` has been removed. Use the canonical enterprise SDK;
there is no import shim or conversion of old fixture IDs. Rebuild and validate
corpora because the query schema, IDs and generated bytes differ.

```python
from worldloom import World
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.enterprise_specs import CoverageProfile

harness = (EnterpriseEvalHarness.from_world(World.load("./corpus"))
    .with_profile(CoverageProfile(strengths=1, connector_counts=(1, 2, 3, 4, 6)))
    .require_sources().take(100))
queries, coverage = harness.plan()
corpus, coverage = harness.build()
# Use harness.exhaustive() for a bounded deterministic exhaustive prefix.
```

| Removed contract | Canonical contract |
|---|---|
| `plan_query_set(...)` | `EnterpriseEvalHarness.plan()` returns queries and coverage |
| `build_query_driven_corpus(...)` | `EnterpriseEvalHarness.build()` returns corpus and coverage |
| `QueryDrivenCorpus.plan` | `EnterpriseCorpus.queries` |
| `query.sources` | `query.generation.source_requirements` |
| `query.mutation` | `query.generation.mutation` |
| `fixture.output_record_id` | `fixture.destination_record_id` |
| Connector-only fixture keys | `connector:entity` keys in `input_record_ids` |
| `content_verb` | `content_action` in the declared workflow and query dimensions |
| Topology labels | `with_dag_grammar(...)` with executable catalogue shapes |
| Unconstrained `query_space_size()` | Valid-space counts and explicit coverage reports |

Source cardinalities 1, 2, 3, 4 and 6 remain supported when an authored
`WorkflowSpec` supplies those source roles and the world actually grounds them.
A profile does not invent missing connector evidence. `risk_register` and
`steering_pack` can be authored as additional workflows; they are no longer
fixed entries in a second planner. Native output mappings name a real entity
and format: records, HTML pages or emails, DOCX documents, XLSX workbooks and
PPTX presentations. Ambiguous connector aliases still need a concrete write
type; for example, creating a Jira issue requires its issue type.

The removed planner's `checksum`, `map_reduce` and `chart` values were labels;
it never executed those semantics or rendered a chart. They are not preserved
as capability claims. The executable catalogue offers `read_chain`, `fan_in`,
`fan_out`, `diamond` and `map_read`, with actual result bindings and readback
checks. Connector workflows remain complementary to
[native file benchmarks](native-benchmark-workflow.md): stateful connector
permissions, mutations and trace grading have their own execution contract.
