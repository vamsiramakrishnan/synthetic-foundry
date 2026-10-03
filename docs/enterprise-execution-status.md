# Enterprise execution: implementation and measured limits

This supersedes the unbuilt-status claims in
[the original design](plans/queryset-to-outcome.md). The comparison starts at
`2f79e5bdbd2aff1e5a19c890e29a454c783a761b`, using the untouched
`examples/retail-close` world and the first 400 interleaved exhaustive queries.
The measurement keeps planning, compilation, execution, assertions and evidence
validation separate. A compiler accepting a row is not evidence that its source
corpus answers the query.

## Measured population

| Gate | Original legacy population | Updated legacy population | Opt-in grammar population |
| --- | ---: | ---: | ---: |
| Planned queries | 400 | 400 | 400 |
| Compiled | 97 (24.25%) | 400 (100%) | 356 (89%) |
| Refused | 303 | 0 | 44 |
| Executed | 97 | 400 | 356 |
| Grade `ok` | 53 | 171 | 53 |
| Grade `behavior` | 23 | 229 | 303 |
| Grade `fail` | 21 | 0 | 0 |
| Runtime exceptions | 0 | 0 | 0 |
| Runs with tool errors | 44 | 229 | 293 |
| Evidence-validation findings | 0 (checks absent) | 200 | 212 |

The original refusals were unresolved connector vocabulary. The updated
legacy tool errors are the 229 explicitly designed failure outcomes. The
grammar's `behavior` category also includes ten valid conditional executions
without an error. Its 44 refusals are insufficient bound source records
(42 at `read-0`, two at `read-1`), not missing tools. All eight authored shapes
occur in the grammar population. The populations in this table differ because
shape expansion and compatibility happen before the limit, so its columns are
not a paired comparison of legacy and grammar difficulty. The paired
measurement below is, for the identities it selects.

## Paired comparison

`--paired` selects the limit's base identities first: the first rows of the
same fair exhaustive stream, so the legacy arm is exactly the default legacy
population at that limit (a test strips the key and compares the bytes).
Each identity then gets one grammar variant, built as the default `--dag-shape
'*'` expansion builds that row and shape; the shape is chosen among the
compatible ones by a content key of the identity. Both arms carry the legacy
query id as the `pair_key` dimension. An identity no shape admits stays in the
table as a grammar planning refusal. Each arm is materialised and graded
separately with the gates above, and compile or runtime refusals would be
reported per pair (none occurred here).

Measured at `30e3b953f3a27f0217c35caa694ed3b303baa9ce`, clean tree, untouched
`examples/retail-close`:

```bash
python tools/measure_enterprise_execution.py --paired --limit 400 --output paired.json
python tools/measure_enterprise_execution.py --paired --limit 100 --failure none --output paired-healthy.json
```

| Pair outcome | 400 identities, all failure kinds | 100 identities, `--failure none` |
| --- | ---: | ---: |
| Both `ok` | 65 | 85 |
| Legacy-only `ok` (grammar `behavior`) | 11 | 15 |
| Grammar-only `ok` | 0 | 0 |
| Neither `ok` (both `behavior`) | 204 | 0 |
| Refused in grammar arm (legacy `ok`) | 120 | 0 |
| Refused in legacy arm | 0 | 0 |
| Refused in both arms | 0 | 0 |

No row in either arm graded `fail` and none raised. All 120 refusals are at
planning: 70 `stale_source` and 50 `ambiguous_join` identities, the
perturbations the grammar refuses by design. Every disagreement between
executed arms is `ok` against `behavior`, not `ok` against `fail`: in the
400-identity run 9 are `conditional` and 2 `delete_chain`; in the healthy run
12 are `conditional` and 3 `delete_chain`. Every other shape agrees with legacy
on every executed pair. So on these identities the grammar is not measured as
harder in the sense of wrong answers; it changes which identities can be
attempted and how two shapes are graded.

Limits of this reading: one grammar shape per identity, so a shape's count is
how often the content key chose it among the compatible shapes, not its
difficulty over the whole space. The legacy arm at this revision (196 `ok`,
204 `behavior`, no evidence findings) differs from the "updated legacy" column
above, which was measured at an earlier revision; that table stays as the
record of its own revision. Raw reports with per-pair rows:
[enterprise-paired.json](measurements/enterprise-paired.json) and
[enterprise-paired-healthy.json](measurements/enterprise-paired-healthy.json).

Evidence validation now detects ungrounded placeholders and missing minimum
cardinality. These counts are findings, not distinct queries, measured at the
commit above. The hand-authored retail example does not supply every
operational source demanded by the full shipped registry. It is unchanged, and
the HTTP corpus loader correctly refuses an invalid corpus. Use a scenario with
matching evidence or supply operational projections.

Since then the planner plans only against the world's groundable inventory, and
`strict_sources` is the default for materialization: a case the source corpus
cannot answer is refused with `missing_source` or `insufficient_sources`,
naming the connector, entity, counts and query, instead of being built.
`enterprise-evals build` reports it as the `sources_insufficient` refusal.
Re-measured on `examples/retail-close` with `plan_queries(strategy="exhaustive",
limit=400)` and the default registry and profile, the first 400
grounded queries materialize with zero evidence-validation findings under
either setting; with `ground=False`, the first 400 are refused at
`email:thread`, which the world never projects. `strict_sources=False` remains
as an explicit opt-out in `materialize_corpus` and `EnterpriseEvalHarness`. It
no longer mints filler records, so a short source pool is refused there too, as
the `ungroundable_source` tripwire.

For a positive end-to-end evidence check,
`tests/test_enterprise_operational_execution.py` builds actual retail inventory
and banking loan histories. It exercises 24 queries per industry for each of
legacy, `map_read`, `conditional`, `write_chain` and `delete_chain` (240
total), validates evidence, exports and reloads, compiles and executes every
row. The 192 grammar queries also run through CLI simulation. The 48 legacy runs additionally
achieve complete observation coverage through the semantic trace scorer.

## Implemented contracts

| Design item | Result |
| --- | --- |
| Target state | Authored legal transitions or explicit destination targets reach writes and fixture-anchored post-state assertions. Wrong targets, wrong records and missing post-state fail. |
| Vocabulary | Email definition, patch normalization, explicit preexistence-based upsert, concrete file aliases, required create payloads and returned-ID readback. |
| Failure injection | Shared emulator overlays target the correct connector and record; exact `failure_at` checks the error, persisted effects and stopped descendants. Partial writes persist before reporting failure. |
| Simulation taxonomy | Completion, designed write failure, earlier stop and runtime exception retain their distinct findings. Assertion grades and weighted scores remain separate. |
| Evidence validation | Empty placeholders fail. Operational histories have independently named, content-addressed observations and checked local integrity. |
| Coverage | Fixtures pin exact selected facts and observations. Successful source reads earn coverage; missing pins earn no provenance credit and invented IDs are penalized. |
| DAG grammar | Versioned typed nodes, arguments, result references, conditions, maps, bounds, eight authored shapes and an independent execution-contract grader. |
| Required fields | Definitions reach generated records, the user request, native read predicates and field-use assertions; invalid existing values are refused. |
| Connector service | Optional MCP StreamableHTTP, isolated run state, authenticated principals, bounded tools and calls, native result capture, trace retrieval and grading. |
| Cleanup and sizing | Dead enterprise CLI and field-manifest modules removed; predicates live on connector definitions. Public legacy query planning is deprecated with its schema preserved. Scenario-aware sizing reports an exact count or witnessed lower bound. |

The external service observes the tools and record identities itself; callers
cannot submit node labels, assertions or a fabricated post-state. Actual HTTP
tests cover the nine shapes, both conditional paths, mapped reads and writes,
pagination, response refusal, run isolation and authentication. Both execution
paths use the connector emulator and assertion dispatcher.

Contracts and examples: [state and fields](enterprise-evaluation-contracts.md),
[DAG grammar](enterprise-dag-grammar.md),
[connector serving](connector-serving.md), and
[CLI and SDK](enterprise-agent-evals.md).

## Reproduce

```bash
python tools/measure_enterprise_execution.py --output measurement.json
python tools/measure_enterprise_execution.py --dag-shape '*' --output grammar-measurement.json
python tools/measure_enterprise_execution.py --failure none --output healthy-measurement.json
python tools/measure_enterprise_execution.py --paired --limit 400 --output paired-measurement.json
pytest -q tests/test_enterprise_operational_execution.py tests/test_enterprise_dag.py tests/test_connector_serving.py tests/test_enterprise_replay.py
```

Committed raw reports are in [measurements](measurements/). Each records the
source revision, dirty-tree flag, parameters, denominators, refusal reasons,
grades, validation examples and failure slices. The baseline dirty flag records
the uncommitted measurement script; runtime source was at the stated baseline.
Use exhaustive mode for a bounded prefix: covering mode scans candidates
before applying its output limit.

## Explicit limits

- Eight shapes are implemented. The external 42-shape catalogue was not
  supplied; completeness against it is unmeasured.
- Ambiguous joins and stale sources are data perturbations, with no checked
  clarification or authoritative-replacement policy. The grammar refuses
  these combinations; legacy completion does not prove those policies.
- Operational observations prove local history and provenance integrity.
  They do not prove an unavailable synthesis ledger was replayed or that
  operational totals reconcile with the World's macro facts.
- Fact coverage checks deterministic grounding. It does not grade the truth
  or quality of final prose, and pure DAG result transforms are not an LLM.
- The service is a single-worker evaluation endpoint. Runs are in memory by
  default; `--run-store PATH` journals them to an fsynced append-only JSONL
  file and replays them on restart (`docs/connector-serving.md`). Public TLS,
  OAuth integration, multi-worker routing (shared run state across processes)
  and a live Gemini Enterprise deployment have not been implemented or tested.
- Generation changes are documented in `CHANGELOG.md`. Reproducibility holds
  for repeated execution of this generation, not byte identity with the old
  enterprise query and fixture schema. Existing exports need rematerialization
  to acquire evidence pins.
