# Executable enterprise DAGs

Enterprise planning uses `enterprise-dag@1`. Each generated node has
arguments, explicit result references, dependencies, and optional result-based
conditions or bounded iteration. These values drive execution and grading.

Planning with no `--dag-shape` plans every shape in the catalogue, so a
default case set grades a delete, a mapped read and a conditional branch.

`map_read` fetches every search hit and `conditional` needs a witness for both
branches, so both raise a source's `minimum` to two. The materializer tops a
source pool up to the largest minimum any planned row asks of it, which is what
makes those two groundable; it used to stop at one, and rows under them
materialized and then refused to compile.

```bash
# The default: every groundable shape, deletes included.
worldloom enterprise-evals plan examples/retail-close queries.jsonl --exhaustive --limit 100

# The whole catalogue, on a corpus with enough evidence for the two that need it.
worldloom enterprise-evals plan examples/retail-close queries.jsonl --exhaustive --limit 100 --dag-shape '*'
worldloom enterprise-evals build examples/retail-close ./enterprise-corpus --exhaustive --limit 100 --dag-shape map_read --dag-shape conditional

# The single-write trajectory the grammar produced before shapes existed.
worldloom enterprise-evals build examples/retail-close ./enterprise-corpus --exhaustive --limit 100 --dag-shape none
```

A mapped source requires at least two records. The materializer supplies them
unless the row filters its sources by a predicate or the corpus is built
`strict_sources`, in which case a filler record would meet the count and not
the claim, and the refusal names the connector, the entity, how many records
are present and how many the row needs. All source reads
are bound to fixture identities. A search intersects those identities with the
authored field predicates. It does not search an unrelated connector pool.

The SDK uses the same planner:

```python
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.enterprise_dag import shape_coverage

harness = (
    EnterpriseEvalHarness.from_world(world)
    .exhaustive()
    .with_dag_grammar("map_read", "conditional", "write_chain")
    .take(100)
)
corpus, coverage = harness.build()
print(shape_coverage(corpus.queries))
```

The versioned catalogue contains eight implemented shapes. This is not a claim
of coverage of the 42 shapes described in the external target dataset; that
catalogue is not present in this repository.

| Shape | Executed behavior |
| --- | --- |
| `fan_in` | Read each source, collect evidence, write one result, read it back. |
| `read_chain` | Read two or more sources in dependency order, then collect, write, verify. |
| `map_read` | Search each source, fetch each returned record within its bound, join, write, verify. |
| `diamond` | Independently project identifiers and titles, join the projections, write, verify. |
| `deep_chain` | Read, collect, project, deduplicate, write, verify. |
| `conditional` | Inspect the first search result count, execute one of two complementary writes, verify the selected write. |
| `fan_out` | Create two independently named outputs from shared evidence and verify both. |
| `write_chain` | Write, read back, update that exact returned record, read back again. |
| `delete_chain` | Write, read back, delete that exact returned record, read it back expecting `not_found`. |

Shape compatibility is a constraint. `read_chain` requires multiple sources;
`fan_out` requires an operation that creates records; `write_chain` and
`delete_chain` require a destination whose connector definition serves an
update or a delete for the entity (SharePoint and Drive files do; email
drafts do not). A planned delete compiles to a `deleted` assertion naming the
write that created the record and a `failure_at` expecting `not_found` on
the final readback, so the record being gone and the readback failing are
both graded rather than excused. Shape selection takes
place before covering and sharding, so coverage includes the shape dimension
and interleaved shards reconstruct the same global sequence. Conditional
campaigns deterministically request one- or two-record witnesses so both
branches can occur. `shape_coverage` reports what was actually planned.

## Author a graph

`EnterpriseDag`, `EnterpriseDagNode`, `ResultReference`, `ResultCondition`, and
`ResultIteration` in `worldloom.enterprise_dag` are public frozen models. The
catalogue is a set of examples of these models, not the grammar's boundary.
Serialized nodes can be supplied as a planned query's `expected_dag`, with
`dimensions["dag_grammar"] = "enterprise-dag@1"`.

A reference names a prior node, a field path, and a selection mode:

```python
ResultReference(node="search", path=("id",), select="item")
ResultReference(node="readback", path=("payload", "file", "mimeType"))
ResultReference(node="collect", select="count")
```

`first` requires a nonempty result; `all` returns the whole selected sequence;
`count` returns its size; `item` is valid only inside a map over that node.
Binding names use dotted argument paths such as `fields.evidence_count`.
Conditions compare a reference using `eq`, `ne`, `gt`, `gte`, `lt`, or `lte`.
They inspect returned values, never a preselected branch flag. Local transforms
are `collect`, `project`, and stable `unique`. They do not claim to generate
prose or to invoke a model.

The compiler refuses unknown tools, invalid entity/operation combinations,
duplicate node identifiers, cyclic or unresolved dependencies, references to
non-ancestors, missing source records, missing known source-result fields, and
invalid iteration bindings. Runtime preflight checks the tool contracts again.
Graphs contain at most 128 nodes; maps at most 1,000 items per node; searches at
most 1,000 returned items; execution at most 10,000 connector calls and 10,000
items per local transform. Smaller per-row budgets are supported. Bounds are
checked before allocating a transform's combined resultset.

## Execute and grade

`enterprise_rows.compile_row` emits the same tool/edge wire format used by
`connector_eval_runtime.run_eval_row`. The grammar evaluator owns only control
flow and result binding. All connector calls go through `ConnectorEmulator`,
which owns native tools, queries, paging, ACLs, state transitions, and failures.
Local transforms execute as pure functions and add no invented tool spans.
Their connector ancestry remains attached to downstream calls.

The compiler emits `execution_contract`. The existing `grade_trace` dispatcher
checks it independently of runtime branch messages. It verifies:

- Exact source record coverage, tool and entity admission, dependency order,
  argument bindings, map counts and record identities.
- The selected branch, including refusal of a call on the unselected branch.
- Writes to the declared fixture, actual created entity, and final field values.
- Unexpected tool calls, duplicate span identities, and a write hidden under a
  local transform's node identifier.

Grammar execution records native response receipts with
`connector_results.record_connector_result(span, result)`. An external tool
recorder uses the same helper after a successful tool call. The helper copies
the returned payload into a `ConnectorResultSpan`; legacy spans keep their
existing shape. These receipts let a later condition or write refer to the
value that was actually returned, including a readback before another update.
Source receipts are checked against the fixture's bound native snapshots.

Permission denial, missing stable identifiers, version conflicts, and partial
writes use the shared `failure_at` contract. Only the declared error at the
declared node satisfies a designed failure. Descendants must stop; independent
branches remain executable. The grammar refuses `ambiguous_join` and
`stale_source`, whose behavioral policies have not been implemented here.
