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

The worldloom.query_planning module inverts the pipeline:

    declare query space
      -> select exhaustive or t-way covering plan
      -> derive record and mutation requirements
      -> generate connector projections
      -> bind exact records to each query
      -> inject conflict or failure state
      -> emit the executable evaluation case

The declared space varies workflow, source connector set, write target and
verb, output kind, content verb, DAG topology, failure mode, and verification
policy. Source connector sets include one, two, three, four, and six inputs.
The destination adds another connector hop.

Exhaustive mode materialises the full Cartesian product. Covering mode uses
WorldLoom's existing deterministic covering-array engine. At strength two,
every pair of dimension values occurs at least once. At strength three, every
triple occurs. The plan therefore has an explicit denominator and holes can be
measured rather than inferred from random samples.

    from worldloom import World
    from worldloom.query_planning import build_query_driven_corpus

    world = World.load("./corpus")
    generated = build_query_driven_corpus(
        world,
        strategy="covering",
        strength=2,
    )

Every planned query carries RecordRequirement and MutationRequirement objects.
Generation then creates only the connectors the plan requires and binds stable
record IDs to each input. Create operations receive an empty destination.
Update, patch, upsert, and reply operations receive an existing destination
record. Failure families add ambiguous joins, missing identifiers, permission
denials, partial writes, stale sources, or version conflicts.
