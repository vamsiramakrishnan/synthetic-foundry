# Eval execution: querying, iteration, outcomes

`worldloom evalrun` runs an agent against a compiled case set and grades three
axes. It is the loop Gemini Enterprise Eval Studio has and Worldloom did not,
with the grading a fact-derived corpus can support and Eval Studio cannot.

```bash
worldloom enterprise-evals build ./corpus ./cases --exhaustive --limit 200
worldloom evalrun prove ./cases                     # every case solvable? first failing node and why
worldloom evalrun cases ./cases                     # what the set can grade, per axis
worldloom evalrun run ./cases -o ./runs/reference   # the executable ceiling
worldloom evalrun run ./cases -o ./runs/mine --agent scripted:trajectories.json
worldloom evalrun compare ./runs/reference ./runs/mine
worldloom evalrun plan ./cases -o ./runs/planner --exec "python3 my_planner.py"   # querying alone
worldloom evalrun import-studio ./cases eval_results.csv -o ./runs/studio
worldloom evalrun agreement ./cases eval_results.csv -o ./runs/agreement   # does the local grader agree with Studio's?
worldloom evalrun summarize ./runs/mine --json
```

## The three axes

Retrieval evaluation asks whether the right passage came back. An enterprise
agent is not graded on that. Given a request, it forms a plan over several
systems, works through it, and leaves state behind. Those are three different
questions, and a single pass/fail over a trace answers none of them
separately. Every case carries a contract per axis (`worldloom.evalrun.EvalCase`)
and every run reports a grade per axis (`CaseScore`).

| Axis | Question | Contract | Grade |
| --- | --- | --- | --- |
| **plan** (querying) | Given the request, which connector DAG should exist | `PlanContract`: nodes, edges, shape, which nodes read, write, verify | node recall and precision, edge recall, missing verifies, writes outside the plan |
| **trajectory** (iteration) | How the agent got through it | `TrajectoryContract`: call budget, designed failures and what they block, retry tolerance, the questions the request requires before the agent may act | exact / in-order / any-order match, precision, recall, retry storm, budget, failures honoured, questions honoured, Anvil's safety laws and the four question laws |
| **outcomes** | What is true afterwards | `OutcomeContract`: records to create, update, delete (by fid, for a mapped write); the artifact and the facts it rests on; the answer and its rubric | a state diff (created, updated, deleted, collateral), the share of a mapped write's records that landed, artifact grounding, a rated answer |

The compiled row stays beside the contract, unchanged, and `grade_trace` still
decides its assertions. The axes are a reading of the row; they cannot
disagree with it about what a call was for.

**A question is a turn.** The turn protocol has three replies: a call, a
question, an answer. An agent asks through `ToolSurface.ask` (the `ask`
reply of the turn document, the `eval_ask` tool over MCP, an `["ask", {...}]`
entry in a responses document); the service records the question beside the
spans, at the position it was asked, answers it from the case's own
`QuestionPoint`s and never says whether it was expected. A row declares the
questions its request requires (`question_required`: the reason, the tokens
the question must mention, the user's reply, the nodes that may not run
first) and `confirm_before` on a delete derives one per destructive write.
The trajectory grade counts the points honoured under four laws,
`acted_without_asking`, `asked_too_late`, `ignored_the_answer` and
`asked_without_need`, as one more term beside the designed failures; a case
that requires no question and gets none scores exactly as before. The
reference agent asks what the row requires, so the ceiling still passes.

**A refused call is still an attempt.** A call the surface does not admit
(an unknown tool, an undeclared argument, a limit) never reaches a connector,
so no span exists for it; the service records it as a refusal instead, the
ledger carries it beside the spans, and the trajectory axis counts it against
precision and the budget and withholds its pass. An agent that probes the
surface a dozen times before finding the right call is not the trajectory an
agent that did not probe took, and the plan axis, which reads only what
reached a connector, still says the same plan was executed.

**Outcomes are a diff, not a claim.** The service snapshots every connector's
records after `begin` and again after the agent returns. Created is in the
second and not the first; deleted is the reverse; updated is the same record
with different fields. A write to the wrong record is *collateral*, reported
by fid, never credit. A case whose designed failure blocks a write expects
that write *not* to happen, and a record that appears anyway is the agent
writing past a refusal. A mapped write (a `for_each` node) is one expectation and one
record per item; every record it produced belongs to it, none is collateral.
A delete is graded the same way an update is: the
record is gone from the post-state, and the trajectory shows the agent read
it first. A record the run created and then deleted is in neither snapshot;
the spans the service recorded show the write that made it and the delete
that removed it, and both expectations are met on that record, with the
artifact grounded on the write the service saw.

**Deletes are planned, not hand-authored, and they are the default.**
`delete_chain` adds a `delete` and a final readback to every case whose
destination connector serves a delete: write, read back, delete that exact
returned record, read it back expecting `not_found`. The row states the
expected error as a designed failure, so an agent that skips the last readback
has not honoured it, and the `deleted` assertion names the write that created
the record. SharePoint and Drive files serve `delete_file`, which the specs
had declared and the definitions did not. A build with no `--dag-shape` now
plans it. `--dag-shape none` plans the single-write trajectory instead.

**Unstructured outcomes rest on records.** Every grammar write binds the
collected evidence into the record it creates. The artifact contract names
the source records the fixture pinned; grounding is the share of them that
the produced artifact cites or the created record carries. Legacy rows do not
bind evidence into the write, so their cases carry no artifact contract, and
`evalrun cases` says so instead of scoring a requirement nothing could meet.

## The stages inside the axes: query, plan, output

Each axis folds a stage into one number, and the number hides what an
evaluation of an agent usually asks: were the searches good, was the plan the
right DAG node by node, is the output right. Three stage grades answer those
as breakdowns attached to the axis they refine. None of them moves an axis
score, a pass, or a verdict; they say *which stage* moved inside an axis.

| Stage | Attached to | Graded against | Finding keys |
| --- | --- | --- | --- |
| **query** (per search or list call) | `TrajectoryGrade.queries` | the gold evidence of the plan node the call served (`expected_reads`, else the fixture) | `query.missed_evidence`, `query.overfetch`, `query.missing_filter`, `query.wrong_window`, `query.malformed`, `query.wrong_scope`, `query.zero_result`, `query.error` |
| **plan nodes** | `PlanGrade.nodes` | the gold DAG, matched by `(connector, operation kind, target entity)` | `plan.node_missing:<kind>`, `plan.node_extra:<kind>`, `plan.node_misordered` |
| **output** | `OutcomeGrade.output` | field values the gold binds, the requested format and sections, the evidence records | `output.field_mismatch`, `output.wrong_format`, `output.missing_section`, `output.ungrounded_fact` |

**Queries are graded by what came back, never by their text.** A call is
assigned to the node it served (the service's attribution, else the search
node on the same connector and entity); per node the grade reads evidence
recall, precision and over-fetch (records returned per record needed, graded
only when the node's gold list is exhaustive), pages pulled against the
fewest that hold the evidence, and the share of its calls with no structural
fault. The structural checks read the arguments the emulator recorded: the
entity the call scoped (`wrong_scope`), a refusal as malformed for its
language (`malformed`), and each window clause, evaluated on the gold
records and against the connector's as-of clock (`wrong_window`: it cuts
evidence, or starts after the clock). A native query is read back through
the emulator's own parser. The fields a call filtered on are recorded, and a
field the gold node constrains that an over-broad call left out is named
(`missing_filter`), but filter choice alone never costs score: two queries
that return the same records in the same pages with no fault score the same.
A node with a designed failure, or blocked by one, is not graded for evidence.

**Plan nodes** compare the agent's declared DAG (`planned_dag`, or the stated
plan of `evalrun plan`) or, when it declared none, the DAG its trajectory
implies, with the gold DAG: node precision and recall, missing and extra
nodes, and dependency accuracy (a node that consumes another's output must
come after it; nodes with no path between them may run in any order). The
existing plan score is unchanged beside it.

**Output** checks each written record for the values the gold fixes: a
state target, an evidence list or count bound from the plan's reads, a
literal the request itself states. For a produced document it checks the
format (media type, name or content), the required sections of the planned
artifact, and grounding: every figure of two or more digits and every record
identifier in the answer and artifacts must trace to an evidence record, the
request, or the evidence count. With no document text, format and sections
are unobserved rather than failed. The rated answer is graded as before.

The stages surface in `summarize` (`stages`), in `compare` (`stage_deltas`,
per case `stages`), in the autopsy (their keys cluster beside the axis keys
on failing cases) and in the trace brief (a section of searches that fell
short, with what they sent and how much of the step's evidence came back).
Policies `evalrun.grade.queries`, `evalrun.grade.plan_nodes` and
`evalrun.grade.output` switch each stage (on by default), and
`evalrun.grade.overfetch_ratio` (2.0) is the over-fetch threshold. When any
stage is on, the grader identity carries a `stages` part (its version, the
stages on, the threshold), so the grader digest of a new run differs from an
older one; `compare` judges the three axes on the digest without that part,
so older ledgers still compare, and reports stage deltas only between runs
graded by the same stage grader. With every stage off, the ledger, summary and
digest are byte-identical to what they were before stages existed.

## Solvability and pins

A grade means something only when full marks were possible. A pilot's call
errors were mostly valid vendor queries the emulator's old predicate parser
refused (SOQL `ORDER BY ... LIMIT`, ServiceNow `ORDERBY`, JQL `OR`), so part of
what it measured was the emulator. Two things close that: the vendor query
evaluator is the default engine (policy `connectors.query.engine`, `native`;
`predicate` still selects the historical parser), and every case set is proved
solvable before an agent is graded on it.

```bash
worldloom evalrun prove ./cases                   # one verdict per case, first failing node and why
worldloom evalrun prove ./cases --json --record   # the report as JSON; proof.json written beside the cases
worldloom evalrun prove ./cases --connectors anvil --contract jira=./contracts/jira   # also served through Anvil
```

**What the proof checks.** Each case's gold DAG is replayed through the
connector emulator under the vendor engine, through the tool surface an agent
gets (`evalrun.proof.prove_cases`; `EvalSession.prove()`):

| Check | Fails when |
| --- | --- |
| `query.parse`, `query.field` | the node's gold query, or its structured predicate compiled into the connector's language, does not parse in the vendor grammar or names a field the vendor does not have; the reason is the vendor's own error |
| `query.evidence` | that vendor query, run by the evaluator, does not return the node's evidence. An identity lookup is restated on the vendor's identity (the Jira key, the Salesforce Id, the ServiceNow number); Drive `q`, KQL and Slack search have no identity clause, so an identity lookup there is not checked in vendor form |
| `read.error`, `read.evidence` | a gold read fails, or does not retrieve its evidence (`expected_reads`, `reads_contain`, else its fixture) |
| `write.error`, `write.state` | a gold write fails (a target that does not exist), or does not leave the expected state diff |
| `node.unexecuted` | the reference could not execute the node (an unbound argument, a blocked parent) |
| `trajectory.safety` | the gold trajectory itself breaks a safety law |
| `axis.*`, `stage.*`, `assertions` | the reference does not score 1.0 on plan, trajectory or outcomes, or on a stage it is graded on (queries, plan nodes, output), or the row's assertions fail |
| `anvil.unmapped`, `anvil.divergence` | with `--connectors anvil`: a gold call has no modelled contract operation, or Anvil served it differently from the emulator |

A case that fails any check is unsolvable. The verdict names the first failing
node in gold order and why; `prove` exits 1 when any case is unsolvable. Under
`--connectors anvil` without Node and an Anvil CLI the Anvil half is reported
as skipped, never as passed, and the in-process verdict stands.

**Writers refuse unsolvable sets.** `enterprise-evals build`, `evalrun
corners` and the case-set writer (`corners.write_case_set`) prove the cases
before anything is written. The default is to refuse, naming each case's first
failing node (refusal `cases_unsolvable`); `enterprise-evals build
--drop-unsolvable` (and `write_case_set(..., drop_unsolvable=True)`) writes the
solvable cases instead and lists every dropped case, with its node and reason,
under `dropped` in `proof.json`. Corner cases were always drawn only where the
reference solves them; they now use the same proof, so a dropped corner case
names its node too. Refusal is the default because a writer that quietly
shipped an unsolvable case hands every agent a zero it did not earn.

**Pins.** `proof.json` records what the proof rests on, as digests
(`evalrun.proof.environment_pins`):

| Pin | What it names |
| --- | --- |
| `corpus` | the records and the case rows |
| `connectors.<name>` | each connector definition the cases use |
| `query_engine`, `query_data` | the engine, and the vendor field names and error bodies it reads (`_data/connectors/_query.json`) |
| `grader` | the grading code, grading policy and stage graders (`grader_identity`, without a rater) |
| `serving` | `emulator`, or under Anvil the contract digests, any exposure profiles the serving carries, the provider mapping digests and the Anvil version |

`evalrun run` computes the live pins before any agent runs. Equal pins: the
recorded proof stands. Any difference makes the proof stale: the cases the run
takes (all of them, or its `--limit` or `--shard`) are proved again under the engine the run will use (deterministic, seconds for a
few hundred cases) and the run is refused (`proof_stale_unsolvable`) when a
case the record proved solvable no longer is, naming the pins that moved and
the first failing node. A set with no proof record (every set written before
this) is proved at the start of the run and runs with a warning, never a
refusal. The run records `pins` in `run.json`: the live pins plus `proof`,
the recorded proof's digest when the pins match it, `reproved:<digest>` when
they moved and the run's cases proved again, `unrecorded` for a set with no
record; `--resume` and `evalrun merge` refuse a
ledger under other pins, and `evalrun compare` treats two runs under different
pins as it treats two runs under different graders: deltas are reported, no
case is judged, and `pins_mismatch` names what moved.

**Measured.** `enterprise-evals build <world> ./cases --exhaustive --limit 200
--dag-shape '*'` over the worlds of `--seed 8128 --incident` and `--seed 4242
--incident`, with no profile and with each of the four shipped profiles
(`examples/enterprise-evals/*.json`), proves every case solvable: 0 of 1,000
per seed. Before the generators were fixed it was 116 of 1,000 per seed (the
two seeds plan the same shapes), every one the gold plan's or its grader's
doing, none any agent's:

| Cause | Unsolvable per seed, before | After | Fix |
| --- | --- | --- | --- |
| a reply to a message the gold plan never read (`trajectory.safety`, `destructive_without_read`) | 44 | 0 | the planner reads the target of every write the law holds, asking the grader's own classification (`OperationSafety.reads_first`) |
| the same replies, behind that: a body of raw JSON where the case requires a document's sections (`stage.output`, `output.missing_section`) | (44, masked) | 0 | a message's body is an `outline` of the required sections over the evidence |
| a send flagged for not reading the message it creates (`destructive_without_read`) | 21 | 0 | the law holds a call to read the record it names by `id`; a send names none |
| a diamond whose write counts each record twice (`stage.output`, `evidence_count`) | 51 (and 3 masked behind a send) | 0 | the diamond joins its two views on the record, one entry per record |

Corner cases over the same seeds (`seeded_world` for each engine): 0 of 10
drafted per seed dropped, from 6: every `restated_figure` case's answer stated
the lodged and current figures, which no record an agent can read carries
(`output.ungrounded_fact`); it now states the cited issue and what the issue
says. Industry programmes (the first 100 record-request cases of banking,
retail and healthcare): 0 of 300, from 22, all `output.ungrounded_fact`: a
list or queue answer stated how many records tripped or were open (`14 open of
18`), arithmetic no record carries; it now names those records and states only
how many were read. Refusal stays the default for any set that does not prove.

**Every search tool states its query language.** The tool catalog an agent
gets (`tools[*].query` in the turn document, and the MCP tool description)
carries, for each search tool, the vendor language its `query` is read in, a
grammar summary, two or three examples in that vendor's syntax, the field
names the connector knows, and the free-text form where the real product has
one: ServiceNow `123TEXTQUERY321=`, Jira and Confluence `text ~`, Drive
`fullText contains`, KQL bare terms, OData `$search`, Slack bare terms. SOQL
has none, so it says to use `LIKE` with `%` wildcards. A tool whose language
the evaluator does not read (GraphQL, Rovo, the system of record) says to pass
a structured `predicate`. The words are data (`_data/connectors/_query_docs.json`)
and every example is executed by the tests.

## Plans as data flow

A plan is a DAG of calls, and a DAG's edges are dependencies. Matching nodes
and then reading edges off "ran first" grades a trace as a sequence: two
reads that happened to run one after the other look like a chain, and a write
that names an id it never saw looks downstream of the search that would have
found it, as long as the search ran earlier. The plan stage therefore also
derives the **executed DAG from data flow** (`evalrun.lineage`) and grades it
edge by edge against the gold DAG. It is attached as `PlanGrade.nodes.dag`,
with its own score and findings; the plan axis, the node breakdown beside it
and every other number are unchanged, byte for byte.

**Lineage.** Call B depends on call A when a value A returned reappears in
B's arguments. The rules, in order:

- *Produced values* come only from a call that succeeded, and only from what
  the agent saw: the response the surface returned, or for a run served by
  Anvil the vendor response Anvil answered with (the replay's own result is
  not what the agent read). Every scalar that passes the distinctiveness rule
  counts, and so does every identifier-shaped token inside a longer string. A
  record the call returned or wrote is also produced under its fid, ident and
  external id, the handles the in-process surface resolves.
- *Consumed values* are every scalar in the request (for Anvil, the path,
  query string and body the agent sent), identifier tokens inside strings,
  the literal values of a native query (JQL, SOQL, an encoded query, OData,
  CQL, KQL, Drive and Slack search) read by the shared evaluator in
  `worldloom.connectors.query`, and the records a get, update or delete
  resolved.
- *Distinctiveness*: booleans and nulls never link; a number links when its
  integer part has five or more digits; a string links when it is an email
  address, or has a digit and three or more characters (an all-digit string
  needs five), or has no digit and sixteen or more characters. ISO dates and
  timestamps never link. A value carried by more than half the items of a
  list of three or more (a status, an assignee, a project key) is a shared
  attribute and does not link.
- *Stated values*: a value the case's request states is the user's, not a
  call's, and links nothing.
- *Several producers*: the link goes to the most recent earlier producer; the
  others are kept as alternatives. An ambiguous link honours a gold edge when
  the gold producer is the chosen call or an alternative.
- *Pagination*: a call that repeats the last call to the same tool with the
  same non-paging arguments and asks for a later page depends on it.
- *Unsourced*: a record handle the agent used that no earlier call produced
  and the request did not state is counted as unsourced (guessed or
  hardcoded), never linked.

The run's ledger carries the result in each span's `consumed_from` when the
plan stage is on; with it off, the spans keep what the service recorded.

**The executed DAG against the gold DAG.** Executed nodes are the implied
nodes (one per attributed plan node, one per unattributed tool and entity),
matched to gold as the node breakdown matches them. Gold edges come from the
case's generation: a consumer that binds a producer's output
(`bindings` such as `fields.evidence`, `id` from `$.steps.<node>`, a
`for_each`), transforms compressed out, is a **data** edge; one whose
condition reads it is a **control** edge; the rest (a `read_chain`'s listed
order) are **order** edges. A row without bindings still has a data edge
where the consumer acts on the producer's record (the same fixture, or the
readback of a write). `PlanGrade.nodes.dag` reports:

| Field | Meaning | Finding |
| --- | --- | --- |
| `edge_recall` | gold data edges the run carried | |
| `edge_precision` | lineage edges between matched nodes that a gold edge or gold ancestry accounts for | |
| `missing` | a consumer ran without the producer's output: it guessed or hardcoded the value | `plan.edge_missing` |
| `spurious` | a consumer used the output of a node the gold DAG says it does not depend on | `plan.edge_spurious` |
| `wrong_source` | `(consumer, gold producer, actual producer)`: consumed, but from another node | `plan.wrong_source` |
| `wrong_branch` | a conditional branch the data the run read did not select was executed anyway | `plan.wrong_branch` |
| `parallelisable`, `serialised` | independent reads (no path either way in gold or in the run), and those run one after the other | `plan.serialised` (efficiency, not an error) |
| `executed` | the DAG itself: nodes, edges (how each was carried, a few of the values, alternatives), depth, steps | |

Which branch the data selected is decided from the results the reads
returned; a write carrying the untaken branch's literal arguments is on the
wrong branch whatever node attribution by shape gave it. Calls an agent
issued together (an `sdk-program`'s threads, which the shim records as
overlapping) are one step and never `serialised`.

**Declared against executed.** When the agent declares a plan (`planned_dag`
in its answer, or the plan read off an `sdk-program`'s source), the node
breakdown grades the declared DAG as before and `dag.declared` reports the
divergence: `declared_not_executed`, `executed_not_declared`,
`edges_dropped` (declared dependencies the calls did not carry),
`edges_added` (data flow the plan did not declare), the declared DAG's own
edge precision and recall against gold, and `agreement` (mean of node and
edge agreement; 1.0 means the agent did what it said). `summarize` reports
`stages.plan_dag`, `edge_precision`, `edge_recall`, `declared_cases` and
`declared_agreement`.

**The `sdk-program` harness mode.** A coding harness plans by writing a
program. `evalrun run --exec "<cmd>" --harness-mode sdk-program` asks the
child once per case for one: a `worldloom.evalrun-program/v1` document on
stdin carries the request, the tool catalog, a generated client module
(`worldloom_client`, one method per tool) and the endpoint variable
(`WORLDLOOM_TOOL_URL`, or the `anvil` block under `--connectors anvil`), and
the child replies `{"program": "<python source>"}`, optionally with a
`planned_dag`. Worldloom runs the program in a subprocess under
`--program-timeout` against the run's serving path (a local HTTP shim over
the run's own tool surface, or Anvil), grades the calls it made with every
axis, stage and lineage, and keeps the program on the ledger line
(`program`: source, digest, exit status, output tails, the declared DAG and
where it came from). Without a stated plan, the declared DAG is read off the
source with Python's `ast`: tool calls in source order, each depending on the
calls whose results reach its arguments through variables. A program that
exits non-zero or times out is an error row that still carries its program.
The default harness mode stays the turn protocol.

## The agent seam

An agent under test receives an `AgentTask` (the request, the persona, the
principal) and a `ToolSurface`: the run's tools with their parameters and
safety annotations, and `call`. It never sees the expected DAG, the fixture
ids, or the assertions, and it cannot submit its own trace. This is the rule
`ConnectorEvaluationService` enforces over MCP, kept for an in-process agent.

Three agents ship. `ReferenceAgent` walks each expected DAG through that
surface, so a case is proven executable through the tools an external agent
would use rather than through a private runtime; its run is the ceiling every
other agent is compared against. `ScriptedAgent` replays a trajectory, which
is how a test states one exactly. `CallableAgent` wraps a Python callable,
which is how a harness plugs in a model. An agent that raises is a result
with an `error`, counted and excluded from every mean, never a zero.

Latency is recorded only under `--timed`. Without it a run reads no clock,
and two runs of one agent over one case set write identical ledgers.

## Plan-only grading

`evalrun run` grades the DAG the agent executed, so its plan axis measures
querying and execution together. `evalrun plan` measures querying alone: the
planner receives what an agent receives (the request and the tool catalog
with its safety annotations) and returns a DAG of tool calls, nothing runs,
and the stated DAG is graded with `grade_plan`'s formula: node recall and
precision by tool name (a planner cannot know the case's node ids), edge
recall as reachability through the planned `depends_on` with the expected
DAG's transforms compressed out, missing verifies, writes outside the plan.
A designed failure is a runtime discovery and does not shrink the expected
plan; both branches of a conditional shape are expected.

Three planners: `reference` restates each expected DAG and is the ceiling,
`--exec "<command>"` runs a command once per case with a
`worldloom.evalrun-plan/v1` document on stdin, and `--agent
scripted:plans.json` replays a `worldloom.evalrun-plans/v1` file written
against `evalrun requests ./cases --for plan`. A plan-only run's trajectory
and outcome axes are unobserved: the summary reports no mean for them and
`compare` reports no delta on them, so a plan-only run and an executed run of
the same case set compare on the plan axis and nowhere else: a case's overall
delta is then the mean over the axes both runs observed, two runs with no axis
in common have no delta and no verdict, and the summary's trajectory rates
(exact, in-order, any-order, mean calls) are absent rather than zero where no
trajectory was observed.

## Driving it from another harness

Transports, each carrying only what the agent may know. An installed `codex`
or `claude` needs none of them spelled out: `--harness` is the adapter this
package ships, using that harness's own login.

| Transport | Command | When |
| --- | --- | --- |
| An installed coding harness | `evalrun run ./cases --harness codex`, `--harness claude` | A real second number against the reference ceiling, with no adapter to write. Shorthand for the bundled `--exec` child, which speaks the same turn document and tells the harness it is the agent under test. `evalrun plan --harness` grades its planning alone. |
| Executable, one subprocess per turn | `evalrun run ./cases --exec "<command>"` | The agent must act on what a tool returned. The child reads a `worldloom.evalrun-turn/v2` document (query, tools, transcript) and prints one call, one question to the user, or the final answer. Stateless between turns. |
| Requests and responses files | `evalrun requests ./cases -o requests.json`, then `evalrun run ./cases --agent scripted:responses.json` | A fixed trajectory: a regression set, a hand-authored baseline, a harness that cannot be called back. Replay cannot see a call's result. |
| MCP | `enterprise-evals serve ./cases`, then `evalrun import-served ./cases scores.jsonl` | An agent that speaks MCP, Gemini Enterprise included. It calls `eval_score` before `eval_end` and keeps each document; those are complete three-axis results graded by the serving service, and `import-served` collects them into a comparable run. |
| Planner, one subprocess per case | `evalrun plan ./cases --exec "<command>"`, or `evalrun requests ./cases --for plan` then `evalrun plan ./cases --agent scripted:plans.json` | The plan axis alone. The child reads a `worldloom.evalrun-plan/v1` document (query, tools) and prints the DAG it would run; nothing executes. |
| Studio | `worldloom studio evalrun PROJECT_ID [--agent harness --harness-command "<command>"] [--mode plan]`, or the console's **Evaluations** page | The same run as a durable Studio job on the revision's own dataset, with lineage attached and per-axis results in the console. See [Studio](studio.md#grade-agents-on-the-connector-cases). |

The same surface is reachable as MCP tools of `worldloom mcp`
(`evalrun_cases`, `evalrun_run`, `evalrun_plan`, `evalrun_summarize`,
`evalrun_compare`), as
the `evalrun` entry of `worldloom seams --json` (schemas, axes, laws,
commands), and from Python through `EvalSession`. The exact documents are in
the `worldloom-evalrun` skill's `references/protocol.md`.

## Hero use cases: organise my drive, my inbox, my chats

The tasks people actually hand an agent are reorganisations: file the
quarter's documents, clear the inbox, archive the dead channels. A
reorganisation is hundreds of small, checkable moves whose whole point is the
count, and no planned query could pose one: every row wrote one record.
`worldloom enterprise-evals housekeeping` builds both halves of such an
evaluation from a world:

```bash
worldloom enterprise-evals housekeeping ./corpus ./hk --kind drive --connector drive --records 300 --mess 0.35 --stale 0.15 --duplicates 0.1
worldloom evalrun cases ./hk
worldloom evalrun run ./hk -o ./runs/reference
worldloom evalrun run ./hk -o ./runs/mine --exec "python3 my_agent.py"
```

| Kind | Connectors | The corpus | The rules |
| --- | --- | --- | --- |
| `drive` | drive, sharepoint, onedrive | a folder per business unit and reporting period, plus Archive; files named for the artifact, period and unit | every unit's files for a period belong in that folder; files past the last three periods belong in Archive; a copy named `(1)` is deleted |
| `inbox` | email, outlook | a mailbox of subject-tagged messages (`[Invoice]`, `[Approval]`, ...) and conversation; Outlook adds mail folders | tagged messages are filed under their category (a folder, or a `folder` field on the native connector); old unread conversation is marked read |
| `chats` | slack, teams | a channel per unit and purpose with a last-activity date | a channel silent since the cut-off is archived |

The corpus is in the world's own words (its units, periods and people) and
nothing on a record says where it should be: the rule is in the request and
the ground truth is in the row. A stated share of items is misfiled,
mislabelled, stale or duplicated (`--mess`, `--stale`, `--duplicates`), and
the count is a flag (`--records`, up to five thousand).

Each case is one rule and one group of records that share a destination,
in the executable DAG grammar: a search bound to the rule's own predicate
(`SourceRequirement.bind = "predicate"`, so an agent that reads the rule can
search by it, paged at the tool's page size), a mapped write per record (a
`move`, an update, a transition, a delete) and a mapped readback. The row
carries a `per_record_state` assertion listing every record and the fields
it must end with, and the outcome grade is the fraction that did
(`OutcomeMatch.ratio`): three hundred files with one left behind score
0.997 on that expectation, not 0. The reference agent passes every case on
every connector; the plan and trajectory axes grade a reorganisation exactly
as they grade any other row.

## What Eval Studio contributed, and what it could not

[Gemini Enterprise Eval Studio][studio] is an Angular client that calls
`streamAssist` and grades the answer with one model prompt. Reading it
(`19d235c`) settles what was worth adapting:

- **The judge prompt.** `judge_prompt` reproduces its auto-rater prompt byte
  for byte, indentation included, and `parse_score` is its salvage parser:
  strip fences, strip a `Score:` prefix, strip the scale words so "between
  0.0 and 1.0" is not read as the score, take the last number. Two
  deliberate differences: the result is clamped (Eval Studio returns 5 when
  a rater says 5, then averages it) and "no number" is an error, not a zero.
- **Latency vocabulary.** `ttft`, `ttfa`, `ttlt` in seconds, from
  `ResultRow`, so a timed local run and an imported Studio run share fields.
- **Error separation.** A row with `scoreError` is excluded from every mean.
- **Comparison bands.** ±0.10 is stable; beyond it is an improvement or a
  regression. `evalrun compare` adds what its Compare tab lacks: the join is
  on case id rather than query text, each axis reports its own delta, and a
  case graded on one side and errored on the other is a reliability change,
  not a score change.
- **Its results, imported.** `evalrun import-studio` brings a results CSV in
  as a run on the answer axis only, joined on query text once, refusing when
  two cases ask the same words. The summary reports plan and trajectory as
  unobserved because Eval Studio's parser keeps
  `groundedContent.content.text` and drops everything else.
- **A check on the local grader.** `evalrun agreement` rates each Studio
  row's own answer again with the local rater and reports how far the two
  graders agree (kappa, mean absolute error, correlations, per shape). The
  grader is named by a digest (`evalrun.grader.grader_identity`), and
  `evalrun compare` calls two runs graded under different digests
  `incomparable` rather than judging them. See [Measuring the grader against
  Eval Studio](gemini-enterprise.md#measuring-the-grader-against-eval-studio).

What it could not contribute is the rest: it observes no tool call, caps an
upload at a hundred rows by truncation, computes no mean, and applies one
similarity rubric to every row of a run. `gemini_enterprise` already argued
why that rubric grades an abstention backwards; `rubric_for` reuses its
per-shape instructions for a model rater.

## What Anvil contributed

[Anvil][anvil] classifies every operation once in its IR and projects the
classification onto every surface. `worldloom.evalrun.safety` ports the
vocabulary onto `ConnectorToolDefinition`: `EffectKind` (read or mutation,
nothing between, unknown is a mutation), `RiskLevel`, `IdempotencyMode`,
`RetryBasis`, and the closed sixteen-code `ErrorCode` taxonomy that every
span error maps onto. `tool_annotations` yields the same `readOnlyHint`,
`destructiveHint` and `idempotentHint` Anvil advertises, and the service's
`tool_catalog` carries them, so what a tool says about itself and what a
trace is held to come from one classification.

Three of Anvil's laws are trajectory findings: `duplicate_write` (a
non-idempotent mutation issued twice with the same arguments after it
succeeded), `unsafe_retry` (retried after a non-transient error with no
idempotency basis) and `destructive_without_read` (a destructive call on the
record it names by `id`, a delete, a reply or a forward, that no earlier call
in the run read; a send names no record, so it has nothing to read). The gold
plan reads that record first, by the same classification. Anvil's judge-only rule holds for the answer
axis: `GroundedRater` refuses the causal and authority shapes rather than
scoring them lexically.

Anvil's other habit is the mutation battery: weaken one control on purpose
and prove the check notices. `tests/test_evalrun_mutations.py` takes a
passing reference trajectory, removes or adds exactly one thing an agent
could plausibly do wrong (skip the readback, write twice, add an unplanned
write, hammer a read, write past a failed read, retry a refused call, update
the wrong record, update before reading, delete blind, skip the readback
after a delete, keep the record, do nothing, reverse a stated plan's edges)
and asserts that the score drops and the right axis names the loss. Writing
it found two gaps the graders now close: a write the service could not
attribute to any node leaked past a designed failure without costing the
"honoured" count, and an unchanged retry of a refused call counted as
honouring the refusal because every shipped create carries an idempotency
key that makes the retry *safe* under Anvil's law. Safe is not honoured. The
battery also states what a keyed create absorbs: an identical repeat is one
record and no law broken, though the repeated call is still off the plan.

## The gaps this closes, and the ones it names

Before this layer the repository had the parts and not the loop. These are
the findings, with where each was:

1. **No run.** `eval_execution` proved a design executable through a private
   emulator; `enterprise-evals simulate` executed rows through a private
   runtime; `connectors.serving` graded an external agent's trace. Nothing
   took *an agent* and *a case set* and produced a comparable ledger. Now
   `run_cases` does, with error separation, order-stable results, and a
   content-addressed `case_set` so two runs know whether they are comparable.
2. **One verdict, no axis.** `grade_trace` returns `ok`, `behavior` or
   `fail` and a list of named fails. Two agents on the same case had no
   distance between them, and a model change could not be attributed to
   planning, execution or effect. The three grades are that distance.
3. **Outcomes graded from the call, not the state.** `artifact_created`
   checked for a non-errored span; nothing diffed connector state, so a write
   to the wrong record, a second record created by a retry, or a delete were
   invisible unless a specific assertion named them. The diff sees all of them.
4. **Delete was excluded.** `agent_evals` excluded delete workflows "until
   tombstone and recovery assertions exist"; the emulator could delete and
   `grade_trace` could check `deleted`, but no case contract carried one.
   `StructuredOutcome(kind="delete")` does, the reference walker issues it,
   and the trajectory grader requires the read before it. The planner then
   still planned none: no destination connector served a delete, though the
   specs declared one on SharePoint and Drive files. `delete_chain` and
   `delete_file` close that, and `evalrun cases` on such a build reports the
   deletes it can grade.
7. **Querying could not be measured apart from execution.** The plan axis
   graded the executed DAG, so a planner that emits a DAG without acting had
   no wire to a grade. `evalrun plan` is that wire, with the same formula,
   and a plan-only run's other axes are unobserved rather than zero.
8. **Studio could build the cases and not grade an agent on them.** Its
   Foundry trials observed a target agent for one pass/fail per trial, and
   its console had no job that ran `evalrun` and no page that showed which
   axis moved. The `evalrun` job grades the reference agent or the connected
   harness on the revision's dataset, durably and authenticated, and the
   Evaluations page reads the ledger per case.
5. **The served surface could not attribute an email source.** The service
   demanded an `entity` argument on every search and create to attribute a
   call to its node, and refused the same argument as undeclared for tools
   that do not take one (email's `search_threads`). Every grammar case with
   an email source was unattributable through the surface it was served on.
   Found by running the reference agent through that surface; fixed in
   `ConnectorEvaluationService`.
6. **The interview did not ask.** The Studio interview asked for systems,
   volumes and outcomes without saying evaluation is not retrieval. Its
   instructions now name the three axes and ask which write operations each
   use case's outcomes contain.

Named and not closed here:

- **The shape catalogue is nine shapes.** The external forty-two-shape
  target is not in this repository.
- **Every shape is planned by default.** `map_read` and `conditional` raise a
  source's `minimum` to two, and the materializer used to top a source pool up
  to exactly one record, so rows under those shapes materialized and then
  refused to compile. It now tops a pool up to the largest minimum any planned
  row asks of it, and all nine shapes ground. Deleting a preexisting fixture
  record is compiled (the `deleted` assertion then names the fixture) but no
  shipped profile plans an update-then-delete.
- **A planned DAG is graded by tool name.** `evalrun plan` cannot tell two
  calls of one tool apart by their arguments, so a planner that names the
  right tools in the right order passes the plan axis whatever it would have
  bound; the executed run is where bindings are graded.
- **The answer axis needs a model for half its shapes.** `GroundedRater`
  grades lookups, comparisons and abstentions. For the rest, `--rater
  exec:"<command>"` runs a judge over the `--exec` seam: the child receives
  a `worldloom.evalrun-rating/v1` document (the Eval Studio prompt for the
  case's shape, its parts) and prints a score or the model's text; a child
  that fails is a rating error on that case, not a zero. `model_rater` is
  the same seam for a Python callable. This package never calls a model.
- **Scale is bounded by the corpus, not the runner.** A run over ten
  thousand cases is a loop; the records under them come from the scenario's
  operational program, and a hundred thousand queries over sixty-eight
  records is a hundred thousand readings of the same evidence. The
  [100k plan](plans/evalset-100k.md) owns that.

## Running at scale

An improvement loop wants many attempts per round, and an agent that waits on
a model spends most of each case waiting. Four things let a run use the time.
None of them changes what a run writes: a concurrent, resumed or sharded run
of a deterministic agent leaves the same bytes as one process running the
whole set in order.

```bash
worldloom evalrun run ./cases -o ./runs/mine --exec "python3 my_agent.py" --concurrency 8
worldloom evalrun run ./cases -o ./runs/mine --exec "python3 my_agent.py" --concurrency 8 --resume
worldloom evalrun run ./cases -o ./runs/shard-1 --exec "python3 my_agent.py" --shard 1/4
worldloom evalrun merge ./runs/mine ./runs/shard-1 ./runs/shard-2 ./runs/shard-3 ./runs/shard-4
```

**Concurrency.** `--concurrency N` runs N cases at once on a thread pool, each
still one run on its own fork of the connector state. Its default is the
policy `evalrun.concurrency` (1), so a pack can raise it for every run in a
project. Results are appended to `results.jsonl` as they land, in completion
order, and the finished ledger is rewritten in case order, so the concurrency
never shows in the output. From Python it is `run_cases(...,
concurrency=N)`. Build the service with `service_for(cases, records,
concurrency=N)`, which raises the run limits (`connectors.serving.max_runs`,
`max_runs_per_principal`) to admit N runs under one principal; a service you
build yourself keeps its limits, and a concurrency they cannot admit is
refused (`ConcurrencyRefused`, a `ServingError`) before any case starts rather than turning into error rows whose
number depends on thread timing. Workers run in a copy of the caller's
context, so the packs in force are the same in every thread. The agent must
tolerate being called from several threads at once: the shipped agents do,
and an `--exec` agent is one subprocess per turn, so it does by construction.

Inside the service, begin and end (the run registry, the ordinal, the lazily
built connector bases) take the service lock, and every call, trace, snapshot
and grade takes the lock of its own run. Calls on different runs proceed in
parallel; the calls of one run stay strictly ordered, which is what its
trace records.

**Durability and resume.** Each appended line is flushed and synced before
the next case starts, and `run.json` is written at the start, marked
`partial`, so a killed run leaves an identified ledger. A process killed in
the middle of an append leaves a last line with no newline and only part of
its JSON; reading the ledger drops that line with a note (it is the case that
did not finish) and refuses any other line that does not parse, because that
is corruption rather than a crash. `--resume` keeps the ledger in `--out` when
its `run.json` names the same agent, principal, case set, agent pack,
grader, agent identity and split (and the same shard), grades only the cases
it lacks, and appends them; a ledger for a different run is refused with each
differing field named. The agent identity is the agent's fingerprint (for an
`--exec` or `--harness` agent, its whole command), so `--harness codex` and
`--harness claude`, which share a name, never resume or merge into one run.
Without `--resume` the directory is started over, as it always was.

Until the last case lands, the ledger is not the run, and nothing reads it
as one: `summarize`, `compare`, `autopsy`, `curriculum`, `export` and `value`
refuse a directory whose `run.json` is still `partial` as `run_partial`,
naming how many of the planned cases finished, and so do `read_run`, the MCP
tools and `EvalSession.report` (a `PartialRun`, a `ValueError`). Finish it
with `--resume`; `read_run(directory, allow_partial=True)` reads the finished
cases when a caller wants exactly those. The finished ledger is written file
by file to a synced sibling and renamed into place, `run.json` last, so a kill
while it is written leaves either the previous bytes or the new ones, and a
ledger still marked `partial` until the header is replaced. A `run.json` torn
by an older writer is refused as torn rather than as a different run.
Studio's evaluation job resumes the same way, at case granularity, and runs
the cases of each batch at the policy's concurrency.

**Shards.** `--shard i/n` (1-based) runs the cases whose id hashes to shard
i of n. The partition is by a stable hash of the case id, never by position,
so every machine computes the same one whatever order it listed the cases
in. The shard directory is an ordinary run over its own cases plus a
`shard.json` naming the index, the count, the whole set's digest and its case
order. `evalrun merge OUT SHARD_DIR...` joins them into one run in case
order, byte-identical to the single-process run, and refuses shards that
differ in agent, principal, agent pack, grader, agent identity, split, case set or count, a shard
given twice, a case two shards graded, an unfinished shard (finish it with
`--resume`), and a missing one. Shards combine with `--concurrency` and
`--resume`.

**Served MCP.** `worldloom enterprise-evals serve` keeps its runs in the
memory of the process that began them, so one server is one worker. To serve
more, start several processes, give each its own `--worker-id` (worker `w3`
mints run ids `w3-run-1`, `w3-run-2`, ...), and route every call for a run id
to the process whose prefix it carries. Run state is never shared between
processes; a call that reaches the wrong one is refused as an unknown run.
Its `--max-runs` and `--max-calls` default to the serving policy.

## Python

```python
from worldloom.enterprise_io import load_exported_corpus
from worldloom.evalrun import ReferenceAgent, cases_from_corpus, compare, run_cases, service_for, write_run

corpus = load_exported_corpus("./cases")
cases = cases_from_corpus(corpus)
service = service_for(cases, corpus.connector_data.records)
ceiling = run_cases(service, cases, ReferenceAgent(cases))
mine = run_cases(service, cases, my_agent)          # any object with .name and .run(task, tools)
print(compare(ceiling, mine).regressions)
write_run("./runs/mine", mine)
```

A `CallableAgent` receives `(task, tools)` and returns an `AgentResponse`
with the answer, any `ProducedArtifact`s (name, text, and the record ids it
cites), and optionally the DAG it planned and its first-token latencies.

The proof is one call, and its report carries the pins:

```python
from worldloom.evalrun import prove_cases

proof = prove_cases(cases, corpus.connector_data.records)   # or EvalSession.open("./cases").prove()
for item in proof.unsolvable_cases():
    print(item.case_id, item.failure.node, item.failure.check, item.failure.reason)
```

[studio]: https://github.com/GoogleCloudPlatform/gemini-enterprise-eval-studio
[anvil]: https://github.com/vamsiramakrishnan/anvil

## A case set without a corpus

`worldloom evalrun run` and `EvalSession.from_export` also take a case set:
a directory holding `evalrun-cases.jsonl` (one `EvalCase` per line) beside
`records.jsonl` (the `ConnectorRecord`s the cases run over). `worldloom
industry programme INDUSTRY OUT` writes one for a programme's record
requests (see [Industry X](industry-programme.md)); `evalrun.contract.
read_case_set` reads it and `is_case_set` tells the two apart. A case set
without records is refused, because a case whose plan searches records it
cannot be served is not runnable.
