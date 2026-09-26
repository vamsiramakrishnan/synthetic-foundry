# Self-improvement: from a run's failures to the next round

An eval run says how often an agent failed. Improving the agent needs three
more things: what kind of failure dominates, where it concentrates, and fresh
cases of that kind the agent has never seen, with some of them held back to
judge the change. This page describes the loop Worldloom supports for that,
and the parts of it that exist today: the autopsy, the targeted curriculum
and difficulty escalation. Sections marked as placeholders are owned by work
still landing.

Nothing in the loop re-grades a case or asks a model for a verdict. Every
finding is read from the three-axis grade `evalrun run` already wrote, and
every new case comes from the dataset compiler under its own admission rules.

## The loop

```text
baseline run ──> autopsy ──> proposal ──> train comparison ──> holdout ──> promotion
     ^                          |                                             |
     |                          +── curriculum (fresh cases, new seed)        |
     +─────────────── escalation when a slice is saturated <──────────────────+
```

1. **Baseline.** Run the current agent over a case set and keep the run
   directory (`worldloom evalrun run`).
2. **Autopsy.** Cluster the failing cases by finding key and read the brief
   (`worldloom evalrun autopsy`). The brief is the instruction an improving
   harness receives.
3. **Proposal.** The improver changes the agent: a prompt, a policy pack, a
   tool-use rule. The autopsy tells it what to fix and forbids nothing else;
   the next two steps decide whether the change was an improvement.
4. **Train comparison.** Compile the curriculum the autopsy implies
   (`worldloom evalrun curriculum`, then `worldloom evals dataset compile`),
   run both agents over its `train` split and compare them case by case
   (`worldloom evalrun compare`).
5. **Holdout.** Run both agents over the curriculum's `test` split, which no
   one tuned against. A change that improves train and not holdout learned
   the cases, not the behaviour.
6. **Promotion.** Promote the change only when the holdout comparison shows
   no regression beyond the delta band. The promoted agent's run is the next
   round's baseline; when it saturates a slice, escalate.

```bash
worldloom evalrun run ./cases -o ./runs/baseline --agent scripted:trajectories.json
worldloom evalrun autopsy ./runs/baseline --out ./runs/baseline/autopsy.json
worldloom evalrun curriculum ./runs/baseline --plan base-plan.json --out round-1.json --round 1
worldloom evals dataset compile round-1.json --out ./round-1
worldloom evalrun compare ./runs/baseline ./runs/candidate
```

## Autopsy keys

`finding_keys(result)` in `worldloom.evalrun.autopsy` names each thing a case
failed on. Keys are a closed, low-cardinality vocabulary built from the
grader's own: they never carry a case id, a record id or free text, so two
runs over different case sets produce clusters that can be compared.

| Key | Meaning |
| --- | --- |
| `trajectory.safety:<law>` | One of the safety laws: `duplicate_write`, `unsafe_retry`, `destructive_without_read` |
| `trajectory.question:<law>` | One of the question laws: `acted_without_asking`, `asked_too_late`, `ignored_the_answer`, `asked_without_need` |
| `trajectory.failure_leaked` | A designed failure was met, then worked around or retried unchanged |
| `trajectory.failure_not_reached` | The run stopped before the node where the designed failure waits |
| `trajectory.budget_exceeded` | More calls than the case allows |
| `trajectory.retry_storm` | The same call with the same arguments past the cap |
| `trajectory.refused_call` | The tool surface refused a call (unknown tool, undeclared argument) |
| `plan.missing:<kind>` | A planned node never ran; kind is `read`, `write` or `verify` |
| `plan.extra_write` | A successful write outside the plan's write nodes |
| `plan.order` | Every node ran but a dependency ran late |
| `outcomes.unmet:<kind>` | An expected `create`, `update` or `delete` did not hold |
| `outcomes.collateral` | Records changed that no expectation covers |
| `outcomes.ungrounded` | The artifact does not carry the evidence it must rest on |
| `outcomes.answer_below_threshold` | The rated answer scored under `evalrun.answer_pass_score` |
| `outcomes.answer_unrated` | The rater could not judge the answer |
| `error:<code>` | An error code from the closed sixteen-code taxonomy, reported only when the run hit more errors than the designed failures it honoured |
| `assertion.fail` | The row's own assertion verdict failed and no other key explains it |
| `run.errored` | The agent raised or the case could not be graded |
| `unclassified` | The case failed and no key explains it; report it, it is a gap |

Only axes the score observed contribute, so a plan-only run yields plan keys
and an Eval Studio import yields answer keys. A missing node's kind comes from
the case contract when `autopsy(report, cases=...)` is given the cases, and
otherwise from the node id, which the DAG grammar names by role (`read-0`,
`fetch-0`, `write`, `verify-write`, `target-write`, `delete`).

`autopsy(report, top=12)` groups failing cases by key. Per cluster it reports
the case count, the share of failing cases (shares sum past one, because a case
can fail on several findings), counts per dimension value (`failure`,
`dag_shape`, `shape`, `connector`, `workflow`, `operation`, `destination`), the
values the cluster concentrates in, and one or two exemplar cases with a
clipped query and at most four clipped evidence lines. Clusters are ordered by
count, then key; exemplars by case id. The same run always yields the same
autopsy, byte for byte.

Concentration is **lift**: the value's share of the cluster divided by its
share of the whole run. If every failure is `partial_write` and six of ten
cases are, the lift is 1/0.6, about 1.67. A cluster's raw composition would
only repeat the case set's composition back; lift says where the failure is
more common than the case set explains. Values with lift above one are listed,
strongest first.

`render_brief(autopsy)` writes the plain-text brief: the headline counts, then
per cluster its key, share, meaning, concentrations and examples. It is the
text an improving harness is handed, and it ends by telling the improver not
to special-case the example ids.

## Curriculum

`design_curriculum(autopsy, base_plan, *, round, total, min_per_cluster,
max_share, holdout_share)` in `worldloom.evalrun.curriculum` writes a new
`DatasetPlan` of fresh cases aimed at the clusters; `targeted_plan` returns
the plan alone.

- **Mapping.** Each cluster maps onto dataset `where` predicates. `failure`
  and `dag_shape` are taken when their modal value holds a majority of the
  cluster. Other dimensions (`operation`, `workflow`, `destination`,
  `destination_entity`, `output_format`) are taken only when they also
  concentrate, so a value every case shares is left to the base stratum. A
  designed-failure key always asks for its most common designed failure.
  Clusters that map onto the same predicates share one stratum.
- **Unmappable clusters are reported.** A cluster whose cases carry no
  dataset dimensions, with no majority value, asking for a failure kind the
  DAG grammar admits no shape under (`ambiguous_join`, `stale_source`), that
  describes the run rather than the agent (`run.errored`), that no base
  stratum admits, or that the budget cannot fund, is listed in `unmappable`
  with its reason. The CLI prints each one.
- **Sizing.** Each stratum gets at least `min_per_cluster` rows and at most
  `max_share` of `total` (which defaults to the base plan's row count). In
  between, rows are shared by the cluster's share of the failures, with
  largest remainders deciding the last rows.
- **Sources.** Each stratum copies the closest base stratum's source, adds
  the predicates, narrows `dag_shapes` to the asked shape and the coverage
  profile's failures to the asked failure, so the compiler plans only what
  it will keep.
- **Seed.** The seed is derived from the base seed and the round by content
  address. It is never the base seed, and a round is never another round:
  the cases that exposed a failure are never the cases used to fix it.
- **Splits.** The plan's split weights become `train` and `test`, with `test`
  at `holdout_share`. The compiler keeps shared evidence in one split, so the
  held-out cases share no evidence with the training cases.

```bash
worldloom evalrun curriculum ./runs/baseline --plan base-plan.json --out round-2.json --round 2 --total 200 --min-per-cluster 8 --holdout-share 0.25
```

## Escalation

An agent that passes everything in a slice learns nothing more there. The
function `escalate(history, *, target_band=(0.3, 0.8))` reads one or more
runs (or `CalibrationObservation`s whose conditions name `dag_shape`,
`failure` or `shape`), puts a 95% Wilson interval on the pass rate of every
`dag_shape x failure` slice and every `shape` slice, using the
`DifficultyCalibrator` estimator, and treats a slice as saturated only when
its whole interval lies above the band. Twenty passes out of twenty is not
enough on its own; thirty is.

For each saturated slice it proposes:

- **Harder shapes.** The shape catalogue is ordered by `dag_metrics` over one
  fixed probe request, with load `nodes + depth + width + conditional +
  for_each`: `fan_in` and `read_chain` are the lightest, `conditional` the
  heaviest. The proposal is the next shapes strictly heavier than the
  saturated one, under the same failure.
- **A designed failure.** On a slice with no designed failure, a failure kind
  the grammar admits that has not saturated at that shape too, kinds never
  tried there first.
- **Retirement.** The cases in the slice that passed in every run that
  observed them. They no longer separate a good agent from a better one.

`slice_stats(history)` exposes every slice with its status (`saturated`,
`too_hard`, `in_band`, `undetermined`), so a too-hard slice is visible without
being escalated. Proposals are `where` predicates; feed them to a dataset plan
as strata. Pass earlier runs with `--history` on `worldloom evalrun curriculum`
to pool rounds; the command prints saturated slices after the strata.

## Agent packs

What the loop changes is the policy of the agent under test, held as an
`agent` pack: a standing instruction, overlays on the shipped turn and plan
rules, advice per tool, planning guidance and named skills. A pack is
content-addressed, so two runs under the same policy name the same digest, and
a run records the pack's reference and digest in `run.json`. The rules that
define the reply grammar are locked: a policy that could restate them would be
a protocol variant, and its failures would look like the agent's. See
[Packs](packs.md#agent-packs) for the schema and the lint.

## Grader freeze and agreement

The grader has an identity: the rater, the `rater.*` prompt texts in force,
the rubrics and the grading policy, reduced to one digest. The loop pins it
before the first round and checks it around every run; if it moves, the loop
stops with `GraderDrift` rather than compare two numbers measured differently.
`evalrun compare` refuses to call anything an improvement when two runs name
different graders. Whether the pinned grader agrees with Eval Studio's is
measured separately, with `worldloom evalrun agreement` (see
[Gemini Enterprise](gemini-enterprise.md)).

## Running at scale

Each round runs two agents over the training cases and, when the candidate
passes, two more over the held-out cases, so the loop is as fast as a run.
`evalrun run --concurrency N` keeps N cases in flight on one per-run-locked
service, with the ledger in case order either way; `--shard i/n` splits one
set across processes or machines and `evalrun merge` joins them byte-for-byte;
`--resume` picks up a killed run. The policy key `evalrun.concurrency` sets
the default for the CLI and Studio. See
[Eval execution](eval-execution.md#running-at-scale).

## Improve loop

```bash
worldloom evalrun improve ./corpus --agent-pack agent:baseline \
  --harness claude --proposer-harness claude \
  --holdout-corpus ./fresh-seed-corpus --rounds 3 -o ./improve
```

Each round:

1. the champion runs the training cases (`runs/<pack>@<digest>/train`);
2. `autopsy` clusters its failures and renders the brief;
3. the proposer receives the brief through the pack interview
   (`evalrun.improve.message`) with the champion as the draft, and is refused
   with findings until its proposal lints clean;
4. the candidate runs the same training cases. It passes the training gate
   when the mean delta is at least the delta band, no axis falls by more than
   the band, and it errors on no case the champion was graded on;
5. only then do both run the held-out cases. The candidate must gain there
   (`evalrun.improve.min_holdout_delta`, strictly), under the same axis and
   error rules;
6. a candidate that clears both gates becomes the champion.

The held-out cases are a separate corpus when `--holdout-corpus` is given,
which is the stronger test: a policy that learned this company rather than the
task fails on another. Otherwise a share of the corpus
(`evalrun.improve.holdout_share`) is held back by a stable hash of each case
id, and a case that declares its split (`test`, `holdout`, `validation`) keeps
it. The proposer sees the training brief only; no held-out case id or result
reaches it.

A round stops early when the champion passes every training case (escalate
the curriculum instead), when the proposer asks questions (the operator
answers them), when no proposal lints clean within
`evalrun.improve.authoring_rounds`, or when the proposal restates the
champion. Every round writes `rounds/NNN.json` with the champion, the
candidate, the grader digest, the brief's digest, the clusters, the authoring
rounds and both gates. Runs already on disk for the same policy, case set and
grader are reused, so an interrupted loop resumes without paying twice.
Accepted candidates are stored under `packs/agent/`, so any of them can be
named with `--agent-pack` afterwards.

## Trace export

The runs the loop leaves are training data. `worldloom evalrun export` turns a
run into SFT transcripts, two runs into preference pairs, and any run into
reward records whose verifiable parts are kept apart from the model-rated
answer score. It refuses held-out cases unless asked, because a model trained
on them can no longer be judged on them. See [Trace export](trace-export.md).
