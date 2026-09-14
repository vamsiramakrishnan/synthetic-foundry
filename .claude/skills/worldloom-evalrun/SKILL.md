---
name: worldloom-evalrun
description: "Run an agent against a Worldloom enterprise case set and grade three axes separately: the plan it formed (which connector DAG), the trajectory it took (order, budget, designed failures, safety laws) and the outcomes it left (records created, updated and deleted as a state diff; artifact grounding; a rated answer). Use when asked to evaluate an agent, a model or a harness on enterprise workflows, to compare two agents or two versions, to be the agent under test yourself, or to bring Gemini Enterprise Eval Studio results alongside a local run. Not for retrieval scoring: that is `worldloom evaluate`."
metadata: {tags: [worldloom, evalrun, agents, trajectory, outcomes, mcp, eval-studio]}
---

# Worldloom eval execution

Evaluation here is not retrieval. A case is a request over several business
systems; the agent forms a plan, works through it, and leaves state behind.
`worldloom evalrun` grades those three things separately and reports each.
Read `docs/eval-execution.md` for the contracts; this skill is the procedure.

## The loop

```bash
worldloom enterprise-evals build ./corpus ./cases --exhaustive --limit 200 --dag-shape '*'
worldloom evalrun cases ./cases                     # 1. what the set can grade
worldloom evalrun run ./cases -o ./runs/reference   # 2. the executable ceiling
worldloom evalrun run ./cases -o ./runs/mine --exec "python3 my_agent.py"   # 3. the agent under test
worldloom evalrun compare ./runs/reference ./runs/mine                       # 4. what moved, per axis
worldloom evalrun plan ./cases -o ./runs/planner --exec "python3 my_planner.py"  # 5. querying alone
worldloom enterprise-evals housekeeping ./corpus ./hk --kind drive --records 300   # a hero use case: organise my drive
```

1. **Read the coverage before running anything.** `cases` prints counts per
   axis and names every zero (`gap: no case grades deletes`). A set that
   grades no updates cannot show an agent updates correctly; say so in the
   report rather than reading a pass rate as complete. Deletes are planned
   only by `--dag-shape delete_chain` on a destination whose connector serves
   a delete (SharePoint and Drive files); email drafts never report one.
2. **Run the reference first.** It walks every expected DAG through the same
   tool surface an external agent gets. Its pass rate is the ceiling of the
   set, not a claim about any model. A reference case that fails is a finding
   about the case; report it, do not grade an agent against it.
3. **Run the agent under test.** Three transports; pick by what the agent can do:
   - `--exec "<command>"`: the agent as an executable, one subprocess per
     **turn**. It reads a turn document on stdin (query, tools, transcript so
     far) and prints one call or the final answer. This is the interactive
     path and the one to use when you are the agent yourself: write a small
     script and be honest in it. Contract in `references/protocol.md`.
   - `--agent scripted:responses.json`: replay a responses document written
     against `worldloom evalrun requests ./cases -o requests.json`. Replay
     cannot see a call's result, so it suits fixed trajectories, not an agent
     that must find an id before acting on it.
   - MCP: `worldloom enterprise-evals serve` exposes the same tools over
     StreamableHTTP for an agent that speaks MCP. Have it call `eval_score`
     before `eval_end` and keep each document, then
     `worldloom evalrun import-served ./cases scores.jsonl -o ./runs/served`
     collects them into a run comparable with a local one.
4. **Compare by case id, never by eye.** `compare` reports improvements and
   regressions under ±0.10 bands, which axis moved, and cases graded on one
   side and errored on the other as reliability changes, not score changes.
5. **Measure querying alone when execution muddies it.** `plan` hands the
   planner the request and the tool catalog and grades only the DAG it
   states; nothing runs. `--exec` (one subprocess per case, a plan document
   on stdin), `--agent scripted:plans.json` (written against `requests
   --for plan`), or `--agent reference` for the ceiling. Its trajectory and
   outcome axes are unobserved, and `compare` against an executed run
   reports the plan axis only.

Inside Studio the same run is a job: `worldloom studio evalrun PROJECT_ID`
grades the reference agent on the project's own dataset and `--agent harness`
grades the connected harness; the Evaluations page shows the axes per case.
`summarize ./runs/mine --json` recomputes a summary from the ledger; `import-studio ./cases eval_results.csv -o ./runs/studio` brings Eval Studio's CSV in as an answer-axis-only run.

**Rating answers.** `--rater grounded` needs no model and refuses the
shapes a lexical check cannot judge. `--rater exec:"python3 judge.py"` runs
a judge over the same seam as `--exec`: the child gets the Eval Studio
prompt for the case's shape and prints `{"score": 0.85}` or
`{"text": "<model reply>"}`. A judge that fails is a rating error on that
case, excluded from the answer mean, never a zero.

**Hero use cases.** `enterprise-evals housekeeping WORLD OUT --kind
drive|inbox|chats [--connector ...] [--records N] [--mess] [--stale]
[--duplicates]` builds a corpus that needs tidying and the cases that grade
the tidying: a folder tree, a mailbox or a channel list in the company's own
words, with a stated share misfiled, mislabelled, stale or duplicated. Each
case is one rule the request states and one group of records; the search is
bound to the rule's predicate and every record is graded by fid, so the
outcome score is the share that landed. Run it through the same loop; the
count is the point, so say how many records the corpus held and how many
the agent left behind.

## Reading a result

- A case has `plan`, `trajectory` and `outcomes` grades, each with a score
  in `[0, 1]` and `passed`, plus `assertion_status` from `grade_trace`. A case
  passes only when all four hold.
- An **error row** means the agent raised, exited non-zero, or broke the turn
  contract. It is excluded from every mean and carries the stderr tail.
  Never read it as a zero, and never fix it by editing the grader.
- `outcomes.collateral` lists records the run changed that no expectation
  covers. A write to the wrong record is collateral, not credit.
- `trajectory.refused_calls` counts calls the surface did not admit (an
  unknown tool, an undeclared argument, a limit). No connector saw them, so
  they are not spans, but they cost precision and the trajectory pass.
- `trajectory.safety` names Anvil's laws broken: `duplicate_write`,
  `unsafe_retry`, `destructive_without_read`. A delete without a prior read
  of the record fails the trajectory even when the record is gone.
- A designed failure (`failures_expected`) is honoured when the agent met the
  error at the node and wrote nothing on the nodes it blocks. Writing past a
  refusal is what those cases exist to catch.

## From Python

```python
from worldloom.evalrun import EvalSession, ExecAgent, ExecPlanner

session = EvalSession.from_export("./cases")
print(session.coverage().deletes)          # 0 means no case grades a delete
session.reference()                        # label "reference"
session.run(ExecAgent("python3 my_agent.py"), label="mine")
print(session.compare("reference", "mine").regressions)
session.write("mine", "./runs/mine")
session.plan(ExecPlanner("python3 my_planner.py"), label="planner")   # plan axis only
```

Any object with `.name` and `.run(task, tools) -> AgentResponse` is an agent;
`tools.call("<connector.tool>", **arguments)` is the whole surface.

## Rules

- **Ask when the request leaves something open.** The turn document's third
  reply is `{"ask": {"question": ..., "about": [...]}}`; the reply comes back
  in the transcript. Ask before acting on the point in doubt, act on what the
  reply says, and do not ask when nothing is unclear: `acted_without_asking`,
  `asked_too_late`, `ignored_the_answer` and `asked_without_need` are each a
  trajectory finding. `evalrun cases` reports how many cases require a
  question (`questions_expected`); a zero means the set never checks it.

- The agent never sees the expected DAG, fixture ids or assertions, and
  cannot submit its own trace. Do not add a channel that lets it.
- Runs are byte-reproducible; `--timed` is the only thing that reads a clock,
  and it is off by default. Compare runs on the same `case_set` digest.
- Grading is derived from spans and snapshots the service recorded. The
  answer axis is the only judged one; the built-in `--rater grounded` refuses
  shapes a lexical check cannot honestly grade rather than scoring them.
- A failing reference case, a refused row, a zero in the coverage: report
  each as a finding. Widening the grader to pass is the failure mode this
  layer exists to make visible.
- Changing a grader means extending `tests/test_evalrun_mutations.py`: weaken
  the control you touched on purpose and show the grade drops on its axis.
