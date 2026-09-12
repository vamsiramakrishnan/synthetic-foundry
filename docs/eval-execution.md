# Eval execution: querying, iteration, outcomes

`worldloom evalrun` runs an agent against a compiled case set and grades three
axes. It is the loop Gemini Enterprise Eval Studio has and Worldloom did not,
with the grading a fact-derived corpus can support and Eval Studio cannot.

```bash
worldloom enterprise-evals build ./corpus ./cases --exhaustive --limit 200 --dag-shape '*'
worldloom evalrun cases ./cases                     # what the set can grade, per axis
worldloom evalrun run ./cases -o ./runs/reference   # the executable ceiling
worldloom evalrun run ./cases -o ./runs/mine --agent scripted:trajectories.json
worldloom evalrun compare ./runs/reference ./runs/mine
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
| **trajectory** (iteration) | How the agent got through it | `TrajectoryContract`: call budget, designed failures and what they block, retry tolerance | exact / in-order / any-order match, precision, recall, retry storm, budget, failures honoured, Anvil's safety laws |
| **outcomes** | What is true afterwards | `OutcomeContract`: records to create, update, delete; the artifact and the facts it rests on; the answer and its rubric | a state diff (created, updated, deleted, collateral), artifact grounding, a rated answer |

The compiled row stays beside the contract, unchanged, and `grade_trace` still
decides its assertions. The axes are a reading of the row; they cannot
disagree with it about what a call was for.

**Outcomes are a diff, not a claim.** The service snapshots every connector's
records after `begin` and again after the agent returns. Created is in the
second and not the first; deleted is the reverse; updated is the same record
with different fields. A write to the wrong record is *collateral*, reported
by fid, never credit. A case whose designed failure blocks a write expects
that write *not* to happen, and a record that appears anyway is the agent
writing past a refusal. A delete is graded the same way an update is: the
record is gone from the post-state, and the trajectory shows the agent read
it first.

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

## Driving it from another harness

Three transports, each carrying only what the agent may know:

| Transport | Command | When |
| --- | --- | --- |
| Executable, one subprocess per turn | `evalrun run ./cases --exec "<command>"` | The agent must act on what a tool returned. The child reads a `worldloom.evalrun-turn/v1` document (query, tools, transcript) and prints one call or the final answer. Stateless between turns. |
| Requests and responses files | `evalrun requests ./cases -o requests.json`, then `evalrun run ./cases --agent scripted:responses.json` | A fixed trajectory: a regression set, a hand-authored baseline, a harness that cannot be called back. Replay cannot see a call's result. |
| MCP | `enterprise-evals serve ./cases`, then `evalrun import-served ./cases scores.jsonl` | An agent that speaks MCP, Gemini Enterprise included. It calls `eval_score` before `eval_end` and keeps each document; those are complete three-axis results graded by the serving service, and `import-served` collects them into a comparable run. |

The same surface is reachable as MCP tools of `worldloom mcp`
(`evalrun_cases`, `evalrun_run`, `evalrun_summarize`, `evalrun_compare`), as
the `evalrun` entry of `worldloom seams --json` (schemas, axes, laws,
commands), and from Python through `EvalSession`. The exact documents are in
the `worldloom-evalrun` skill's `references/protocol.md`.

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
   and the trajectory grader requires the read before it.
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

- **No planner grades yet.** The plan axis grades the DAG the agent
  *executed*, attributed by the service, and `planned_dag` only against that.
  A planner that emits a DAG without executing it has no wire to reach a
  grade. The shape catalogue is eight shapes; the external forty-two-shape
  target is not in this repository.
- **Delete cases are hand-authored.** The retail and banking scenario
  profiles plan no delete workflow, so `evalrun cases` reports `deletes: 0`
  for a built corpus. Planning deletes is a Generation change to
  `enterprise_queries` and is deliberately not made here.
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
