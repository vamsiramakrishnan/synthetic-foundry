# Test the harness with controlled retrieval

Worldloom can hold retrieval behavior fixed while measuring an agent's queries,
operations and recovery. A sufficient query returns the matching, permitted
source records. An insufficient query receives a declared empty, partial or
stale response. Those responses contain actual corpus records; the evaluator
does not manufacture an answer when the agent asks the wrong question.

This is an explicit evaluation mode. The ordinary connector query engine and
retrieval benchmarks remain available for testing vendor syntax and search.
Controlled mode tests a typed query contract, not ranking quality.

## Query contract and observations

`RetrievalContract` declares the connector, search operation, entity and required
scope, period and authority predicates. `ResponsePolicy` declares insufficient
responses. `RetrievalFault` can schedule transient transport failures. Explicit
`QueryAlias` values allow equivalent business labels without fuzzy matching.

The public tool schema advertises `Predicate` filters and their operators.
It does not expose the private expected predicates, source IDs or receipts.
For example, an agent can submit:

```json
{
  "entity": "xlsx",
  "predicate": {
    "entity": "xlsx",
    "where": [
      {"field": "business_unit", "op": "eq", "value": "APAC"},
      {"field": "period", "op": "eq", "value": "2026-01"},
      {"field": "status", "op": "eq", "value": "approved"}
    ]
  }
}
```

The engine checks predicate implication and evaluates the query over the
connector's ACL-filtered pool. Merely selecting a fixture's correct record does
not prove the declared scope: `period != 2024` cannot establish `period = 2026`.
Conflicting entity selectors refuse. Native query strings receive an explicit
`unsupported_query` response with the typed alternative; arbitrary KQL, JQL,
full-text search and semantic paraphrase equivalence are not promised here.

Every controlled call leaves evaluator-owned receipts. They identify the query,
source records, returned payload digests, page position, delivery status and
semantic progress. An oversized response that was never delivered cannot count
as evidence. Its failed attempt still counts toward the session's history.
Target-authored tool claims cannot create a receipt.

The evaluator distinguishes:

| Observed behavior | Treatment |
| --- | --- |
| Sufficient first query | Passes without requiring a preliminary mistake |
| Insufficient query followed by a sufficient refinement | Recovery is measured |
| Unchanged insufficient query repeated | No progress; cannot satisfy recovery |
| Valid next page of the same query | Pagination progress |
| Transient failure followed by a successful retry | Valid retry, separately identified |
| Unsupported query followed by the documented typed form | Interface recovery |
| Correct prose with no required source reads or mutation | Does not satisfy the operation/DAG contract |

Receipt delivery establishes what reached the harness. It does not prove
comprehension. Answer and post-state grading remain separate.

## Generate a DAG queryset

`HarnessDagConfig` selects actual source cohorts by connector, entity, numeric
field, scope, period and authority. The generator compiles each cohort into the
existing `EnterpriseDag` and `EvalCase` contracts:

1. Search for all eligible sources, paging when required.
2. Read the records discovered in those results.
3. Sum the declared numeric measure using bounded, exact arithmetic.
4. Create or update a report using the observed values and source IDs.
5. Read back the result and verify the required fields.

Search returns metadata in these generated cases; the numeric values require
source reads. An update must preserve unrelated fields. Source, computation
and write dependencies are executable result bindings. Insufficient attempts
are bounded trajectory work; they are not mandatory nodes in a memorized plan.

```python
from worldloom.connector_data import ConnectorRecord
from worldloom.enterprise_rows import runtime_records
from worldloom.evalrun import (
    HarnessDagConfig, HarnessDagReference, build_harness_dags,
    run_cases, service_for,
)

# records are existing ConnectorRecord objects with real evidence links.
config = HarnessDagConfig(
    cases=12,
    source_connector="sharepoint",
    source_entity="xlsx",
    value_field="amount_minor",
    scope_field="business_unit",
    period_field="period",
    authority_field="status",
    authority_value="approved",
    operations=("create", "update"),
    response_modes=("empty", "partial", "stale"),
    max_calls=128,
)
suite = build_harness_dags(records, config)
suite.write("./cases")
service = service_for(suite.cases, runtime_records(suite.records))
report = run_cases(service, suite.cases, HarnessDagReference(suite.tasks, refine=True))
```

The public reference receives the user task and tools, not the private cases,
gold values or discovered IDs. `refine=True` exercises insufficient-result
recovery; the default reference starts with a sufficient query. These workers
prove implementation behavior, not live-model gains.

The same configuration is available from the CLI:

```bash
worldloom enterprise-evals harness-dags ./records.jsonl --config ./harness-dags.json --out ./cases
worldloom evalrun prove ./cases
worldloom evalrun run ./cases --agent reference -o ./runs/reference
```

`cases` is a selection ceiling. The report exposes candidate count and skipped
cohorts. Missing numeric evidence, insufficient sources, absent stale records
or an impossible call budget produce findings or refuse construction; no
placeholder rows are added to repair the benchmark. The generator uses the
supplied source records. It does not claim every existing world's default
connector projection already contains the requested business fields.

Keep the full case-set directory evaluator-side. Its `public-tasks.jsonl` is a
separate target view. `evalrun` serves controlled cases through their typed
surface while ordinary cases retain their configured connector surface.
External Anvil serving cannot supply these evaluator-owned receipts and is
explicitly refused for controlled cases.

## Connect real native files to the queryset

`project_native_sources` verifies generated DOCX/PPTX/XLSX bytes and their
provenance, then projects one explicitly selected numeric measure and unit into
connector records. The default chooses XLSX, preserving artifact authority,
source hashes, locators and evidence ancestry. It refuses ambiguous values and
overlapping aggregates. Format copies are deduplicated; working and approved
documents remain distinguishable members of their original source family.

```python
from worldloom.benchmarks import NativeConnectorProjection, project_native_sources
from worldloom.evalrun import HarnessDagConfig, build_harness_dags

# world and rendered come from build_native_scenarios and its render() method.
projection = project_native_sources(world, tuple(rendered.values()), NativeConnectorProjection(
    measure_kind="native.supplier_reconciliation.total.actual",
    unit=world.company.currency,
))
suite = build_harness_dags(projection.records, HarnessDagConfig(
    cases=6, value_field="amount", scope_field="scope",
    authority_field="authority", authority_value="approved_report",
))
```

The projection declares `representation="extracted_content"`. The target reads
verified content through its connector; this does not demonstrate that it
downloaded and parsed the binary itself. Private projection bindings and native
manifests stay evaluator-side. A generated infographic does not acquire
qualified evidence status through this adapter.

The runnable [native evidence pilot](../examples/harness-evidence/README.md)
builds two independent source episodes, renders the files, verifies replay,
executes both public-reference strategies and checks two adversarial controls.
Its six DAG variants form one evaluation family, not six independent samples.

## Independence and the remaining boundary

Operation variants and response-policy variants of one cohort share a family.
They do not buy additional independent support. Use the existing split audit
and held-out qualification before treating a measured change as improvement.

These cases evaluate connector record/extracted-content operations. Native
binary ingestion, image comprehension, upstream ranking, and empirical corpus
realism require their own evidence and must not be inferred from a passing DAG.
