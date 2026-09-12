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
    generated = materialize_corpus(world, queries)
    assert not validate_corpus(generated)

Exhaustive mode streams a deterministic prefix when `limit` is set. Covering
mode examines the entire selected space before applying `limit`; use a
narrowed `ScenarioProfile` for that path. Size the selection before planning:

```bash
worldloom enterprise-evals space --profile examples/enterprise-evals/omnichannel-retailer.json --max-candidates 100000
worldloom enterprise-evals plan ./corpus queries.jsonl --profile examples/enterprise-evals/omnichannel-retailer.json --exhaustive --limit 100
```

`space` uses the profile's candidate ceiling unless `--max-candidates` overrides
it. `exhaustive: true` means the count is exact. Otherwise `at_least` is the
number of witnessed candidates, including one beyond the ceiling; it is a
lower bound, not a coverage claim. Unknown connectors and selections admitting
no workflow are refused by the same validation used by `plan` and `build`.

The former `worldloom.query_planning` API is deprecated. It remains available
for callers of its published nine-axis schema and emits a deprecation warning.
Migration is explicit: `QueryDrivenCorpus.plan` becomes `EnterpriseCorpus.queries`,
`query.sources` becomes `query.generation.source_requirements`, `query.mutation`
becomes `query.generation.mutation`, and `fixture.output_record_id` becomes
`fixture.destination_record_id`. Rebuild and revalidate when migrating; the
planners produce different schemas and generation bytes. New integrations must
use the executable planner above.
