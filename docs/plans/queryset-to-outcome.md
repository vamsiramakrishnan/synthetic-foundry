# From a selection to a graded outcome

The ask, in the words it was asked in: generate a queryset by selecting
connectors, file formats and customisations like custom fields; use that
queryset to generate an expected trajectory; then create the data that
validates that trajectory and its final outcome, where the outcome could be an
answer, a resultset, a file we generate, an outcome such as updating an
existing system, or several of those at once.

This document is what that would take. Everything in the first section was
established by running the code, not by reading it, and the commands are in the
text so the numbers can be re-checked.

## What already holds

Most of the pipeline exists. Seven connectors are installed (confluence, drive,
email, jira, salesforce, servicenow, sharepoint) across four workflows
(change_assurance, customer_health, executive_digest, incident_review), and a
planned query already carries a natural-language request, its dimensions, its
generation requirements and an expected DAG:

```
read-0     read          servicenow  incident  depends_on: []
transform  reconcile     model       html      depends_on: [read-0]
write      upsert        confluence  page      depends_on: [transform]
verify     cross_system  confluence  page      depends_on: [write]
```

The selection vocabulary the ask names is already modelled as fields:

| Selecting | Field |
|---|---|
| connectors | `SourceRequirement.connector`, `MutationRequirement.connector` |
| file formats | `ArtifactRequirement.format`, `SourceRequirement.input_format`, `MutationRequirement.output_format` |
| custom fields | `SourceRequirement.required_fields` |

Two of the five outcome kinds are already expressible and already gradeable. A
file is declared by `ArtifactRequirement(format, sections, sheets, slides,
charts)` and checked by the `artifact_created` assertion. A system update is
declared by `MutationRequirement(preexisting_record, verify_after_write)` and
checked by `state_equals` and `deleted`, both of which read a post-state. Since
assertions are a list, several outcomes on one query already compose, so
"plural" needs nothing new once its members exist.

Under that sit `materialize_corpus`, `validate_corpus`,
`generate_connector_data`, the in-process `ConnectorEmulator`, `run_eval_row`,
and `grade_trace` with eighteen assertion kinds. None of this needs rebuilding.

## What stands in the way

Five things, in the order they block the ask rather than the order they are
easy.

### 1. The expected trajectory is a single fixed shape

`_plan` in `enterprise_queries.py:331` builds every DAG the same way: some
number of read nodes, then one transform, then one write, then one verify. Not
a default that can be overridden, and not one shape among several. It is the
only shape the planner can produce, so there is no branching, no conditional,
no `for_each`, no variation in depth or width, and no arguments on any node.
Each node is `{id, kind, connector, entity, depends_on}` and nothing more.

The 100k eval set this work is aimed at carries forty-two DAG shapes with
`for_each` and conditional nodes. The planner emits one. That gap is not a
missing feature on an existing grammar; there is no grammar, and writing one is
the largest piece of work here.

Node arguments are the same defect seen from a different side. A trajectory
that says "read a servicenow incident" and cannot say *which* incident cannot
distinguish an agent that found the right record from one that listed the table
and guessed.

### 2. Two of the five outcome kinds do not exist

An **answer** and a **resultset** have no requirement type to declare them and
no assertion kind to check them. Searching the whole connector and agent eval
path (`connector_trace`, `enterprise_corpus`, `enterprise_queries`,
`agent_evals`) for any notion of a final answer or returned records returns
nothing.

This is structural rather than an omission. This engine has two eval systems
that never meet: `EvaluationCase.expected_answer` grades answers, and belongs
to retrieval; `grade_trace` grades trajectories and side effects, and belongs to
agents. A trace is a list of tool calls, and a final natural-language answer is
not a tool call, so it falls between the two. A resultset falls in the same gap
for the same reason.

The consequence is worth stating plainly, because it is easy to miss while
looking at a green report: an agent can be graded as fully correct on its
trajectory while returning an answer nobody checked.

### 3. The unnarrowed queryset path does not return

**Corrected.** An earlier draft of this document said "the default queryset path
hangs" and stopped there. That overstated it: the hang is real but it is the
*unnarrowed* default only, and there are two routes that return promptly. A
reader of the first version would have concluded the step was unusable, which it
is not.

The hang: `plan_queries(world, limit=3)` on the golden corpus ran for over 109
seconds without yielding a query. With the default `strategy="covering"`,
`constrained_cover` consumes the entire candidate stream before anything is
yielded, and `limit` is applied afterwards (`enterprise_queries.py:363`), so it
bounds the output and not the work. Lowering `max_candidates` does not bound the
work either, because it is a safety valve that *raises* rather than a bound that
truncates. Its default of 10,000,000 is high enough that the refusal almost
never fires and the caller simply waits.

Both working routes were measured on `examples/retail-close`:

- a narrowed `ScenarioProfile` (three connectors, one workflow, two failure
  modes) covers 5,120 candidates to 79 queries in **0.88 seconds**, and two runs
  produce byte-identical output;
- `strategy="exhaustive", limit=N` is lazy, and returns in **0.5 seconds**.

So what is actually missing is not a working path but a way to find one:
`enterprise-evals space`, the command for sizing a selection before committing
to it, takes no `--profile`, so it can only size the unnarrowed space. Neither
route is in the skill documentation.

### 4. Custom fields do not reach the covering planner

**Corrected.** An earlier draft said "custom fields are a hook nothing reads",
which was too broad and would have caused someone to rebuild working machinery.
Custom fields *do* work, on the other track: a field added through
`ConnectorDefinition.with_fields` and passed to `run_eval_row(definitions=...)`
propagates end to end, and that was verified by execution.

What is true is narrower. `SourceRequirement.required_fields` is declared in
`enterprise_specs.py:50`, defaults to `()`, and nothing in the *covering
planner's* path reads it: it reaches neither fixture generation, nor the query
text, nor the DAG, nor grading. Every planned row carries
`"required_fields": []`.

So the two halves of the engine disagree about custom fields rather than lacking
them. The working machinery lives at `eval_design.RecordShapeRequirement.custom_fields`
into `eval_shape.shape_connector_definitions` into
`connector_fields.synthesize_custom_fields`, and its entry point
`bind_eval_connectors` has no caller in `src/`. The work is connecting the
planner to it, not building it.

A declared field with no consumer is still worse than an absent one, because it
reads as support. That part of the original finding stands.

### 5. The planned trajectory could not be executed at all (fixed)

**Added after the first draft, which missed it entirely, and since fixed.**

The first version of this document treated "does the loop run end to end?" as an
open question. It did not. `worldloom enterprise-evals simulate` on a corpus this
repository plans and validates reported `completed: 0` of 12: every query stopped
at its first node. Three defects held it there, one per module, each invisible to
the others and none caught by any unit test, because no test invoked an
`enterprise-evals` command at all.

- `_target_id` (`connectors/enterprise.py`) chose the target record by fixture
  field rather than by the connector and entity the node addresses, so every
  source read was handed `destination_record_id`, the record the *write* would
  target, and 404'd.
- The `simulate` command manufactured a `ToolBinding` per DAG triple. Since
  `RunnerConfig.resolve` consults bindings before the connector definition, a
  synthesised `sharepoint.readback` beat the definition lookup that normalises
  `readback` and `cross_system` to `read`, and every verify node died on
  `KeyError`.
- `_op_get` (`connector_emulator.py`) resolved entity aliases in the requested
  position only, so a record stored under the alias `file` was invisible to the
  `docx` tool that should have read it. Separately, `_concrete_entity` was
  resolved eagerly for every operation although only `create` and `transition`
  use it, so a read of a multi-member alias such as `jira/issue` refused before
  it could do anything.

Fixed, measured cumulatively on the same twelve-query corpus: 0 of 12, then 3,
then 6, then **12 of 12 at mean DAG score 0.777**. None of it is a Generation
change; no generated byte moves. `tests/test_enterprise_evals_pipeline.py` now
runs plan, build, validate and simulate through the CLI and asserts the exact
count, because an assertion of `completed > 0` would have passed with two of the
three defects still in place.

### 6. Nothing serves the connectors to an external agent

`ConnectorEmulator` is in-process. There is no HTTP surface anywhere in `src/`,
and `worldloom mcp` speaks stdio and exposes corpus introspection rather than
connector tools. So a trajectory can be graded when Worldloom itself drives the
emulator, and cannot be graded when the thing under test is a product that has
to reach the connectors over a wire.

This does not block generating the eval set. It blocks pointing the eval set at
anything real, which is eventually the point.

## What it would take

Sizes are engineering estimates for someone fluent in this codebase, and the
ordering is by what unblocks the most downstream rather than by ease.

| # | Workstream | Size | Unblocks |
|---|---|---|---|
| ~~0~~ | ~~Make the planned trajectory executable~~ | **done** | The loop runs: 12 of 12, mean 0.777 |
| A | Queryset ergonomics | S, ~1 day | Sizing a selection before committing to it |
| B | Outcome grading: a producer, not a vocabulary | M, ~1 week | Three of five outcome kinds becoming five |
| C | Custom fields reach the covering planner | M, ~1 week | The "customisations" half of selection |
| D | DAG grammar and node arguments | L, ~3 to 5 weeks | Trajectory variety; the 42 shapes |
| E | A served connector estate | M to L, ~2 to 4 weeks | Grading a real product rather than a simulation |

### A. Queryset ergonomics

Two routes already return promptly, so this is no longer about making one work.
Give `enterprise-evals space` a `--profile` so a narrowed selection can be sized
before it is committed to, which is the actual missing step, and document both
routes in the skill. Optionally give `constrained_cover` a bound so `limit`
stops the covering pass rather than trimming its output.

Not a Generation change if any new bound defaults to the current behaviour,
which it should.

A mistyped connector name no longer produces an empty corpus at exit 0:
`apply_scenario_profile` now refuses, naming every unknown connector and
workflow at once, and refuses a selection that admits no workflow. That was the
worst failure this surface had, because the build succeeded and the eval set
tested nothing.

### B. Answer and resultset outcomes

Two new requirement types beside `MutationRequirement` and
`ArtifactRequirement`, declaring what the answer must assert and which records
the resultset must contain, with the answer's ground truth coming from the fact
ledger the way `EvaluationCase.expected_answer` already does. Then the two
assertion kinds that check them.

The model changes are small. The real work is that `grade_trace` grades a
trace, and neither an answer nor a resultset is in the trace, so the runtime
has to carry the agent's final output alongside its spans. That means a
decision: widen `grade_trace` to accept a final output, or add an outcome
grader that composes with it. The second keeps trace grading honest about what
it is, and is the recommendation.

This is the piece to build first after A, because it is self-contained, it
composes with the file and system-update outcomes that already work, and it
completes the sentence "validate the final outcome".

### C. Custom fields end to end

Make `required_fields` reach its four consumers: fixture generation must emit
records carrying the field, the rendered request must mention it, the read node
must filter on it, and an assertion must be able to require that it was used.
Add the authoring surface so a custom field can be declared per connector
entity, through `ConnectorFieldDefinition`, which already has the vocabulary.

A Generation change, because fixtures that carry a new field are different
bytes. Needs a CHANGELOG entry under its own heading.

### D. DAG grammar and node arguments

The large one. A grammar that can express the shapes the target set uses,
including `for_each` over a resultset and a conditional branch on a prior
node's result, plus arguments bound to each node so a trajectory says which
record it expects to be read. Then a generator that produces shapes from the
grammar, a validator that refuses an unexecutable one, an emulator path that
can execute each, and assertions per shape.

Feature 1 of `docs/plans/evalset-100k.md` is this work, and its estimate there
was also L. Nothing since has made it smaller.

Strongly a Generation change.

### E. A served connector estate

An HTTP or MCP transport in front of `ConnectorEmulator` so an external agent
can call the synthetic company's tools. For Gemini Enterprise specifically the
target is its `REMOTE_MCP` connector type, which requires StreamableHTTP (SSE
is not supported) and a TLS certificate from a publicly trusted CA, with a
recommended ceiling of 100 enabled actions.

Independent of A through D and can run in parallel with them.

## The smallest slice that proves the whole thing

Do not start with D. Start with a single path that goes end to end, so the
seams are exercised before they are widened:

1. One connector pair, servicenow to confluence, which already plans and
   already has an artifact and a mutation requirement.
2. Planning through `strategy="exhaustive", limit=N`, which returns in half a
   second today.
3. The existing four-stage DAG, unchanged.
4. `materialize_corpus` and `validate_corpus`, unchanged.
5. One new outcome kind, the resultset, declared and graded.
6. Executed through `run_eval_row` and graded, with the run reachable from a
   CLI command rather than from Python only.

That is workstream A plus half of B, it is a few days rather than a few weeks,
and it turns every later workstream into a widening of something that works
instead of a bet on something that does not exist yet.

## What was not established, and now is

The first draft listed three open questions. All three have since been answered
by running the code, and two of the answers changed this document.

- **Does `run_eval_row` execute end to end?** No, and neither did the `simulate`
  command above it: 0 of 12. Now 12 of 12; see finding 5.
- **What test coverage do these paths carry?** None. No test invoked any
  `enterprise-evals` command, and `score_trace` had no test at all. That is why
  three defects in three modules could ship together: every unit passed, and
  nothing checked that the units reached each other.
  `tests/test_enterprise_evals_pipeline.py` is the first test to run the loop.
- **Does `materialize_corpus` prove the fixtures satisfy the query?** Partly.
  `validate_corpus` checks source requirements against `input_record_ids` and
  refuses dangling records, so satisfaction is checked rather than assumed. What
  is not checked is the *shape* of what it produces: records carry placeholder
  values, and injected failure modes are recorded without being enforced.

## Still open

- Whether the reference artifact a query declares matches its own
  `ArtifactRequirement`. It is real bytes of the right format, but its shape was
  reported as not matching the requirement that asked for it, and as
  non-deterministic. That gates the file outcome in B.
- Three modules appear dead: `query_planning.py` is a second planner with no
  `expected_dag` and no caller, `enterprise_cli.py` has zero importers, and
  `field_manifests.py` has zero importers. Deleting them is a separate,
  low-risk change and should be confirmed before it is made, not assumed from a
  grep.
