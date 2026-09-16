# Eval execution: querying, iteration, outcomes

`worldloom evalrun` runs an agent against a compiled case set and grades three
axes. It is the loop Gemini Enterprise Eval Studio has and Worldloom did not,
with the grading a fact-derived corpus can support and Eval Studio cannot.

```bash
worldloom enterprise-evals build ./corpus ./cases --exhaustive --limit 200
worldloom evalrun cases ./cases                     # what the set can grade, per axis
worldloom evalrun run ./cases -o ./runs/reference   # the executable ceiling
worldloom evalrun run ./cases -o ./runs/mine --agent scripted:trajectories.json
worldloom evalrun compare ./runs/reference ./runs/mine
worldloom evalrun plan ./cases -o ./runs/planner --exec "python3 my_planner.py"   # querying alone
worldloom evalrun import-studio ./cases eval_results.csv -o ./runs/studio
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
plans it: 120 cases from `retail-close` grade 11 deletes. `--dag-shape none`
plans the single-write trajectory instead.

**Unstructured outcomes rest on records.** Every grammar write binds the
collected evidence into the record it creates. The artifact contract names
the source records the fixture pinned; grounding is the share of them that
the produced artifact cites or the created record carries. Legacy rows do not
bind evidence into the write, so their cases carry no artifact contract, and
`evalrun cases` says so instead of scoring a requirement nothing could meet.

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
idempotency basis) and `destructive_without_read` (a delete on a record no
earlier call in the run read). Anvil's judge-only rule holds for the answer
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
- **Two shapes are opt-in.** `map_read` and `conditional` raise a source's
  `minimum` above what the row declared, so a world holding one record where
  the row wanted one plans a case that materializes and then refuses to
  compile. A build with no `--dag-shape` plans the other seven. Deleting a
  preexisting fixture record is compiled (the `deleted` assertion then names
  the fixture) but no shipped profile plans an update-then-delete.
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
