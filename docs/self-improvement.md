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
  largest remainders deciding the last rows. The plan always has exactly
  `total` rows: when the funded strata could not hold it under the
  `max_share` cap (two strata capped at five and a total of eleven), the cap
  is raised to the even share rather than planning fewer rows than asked.
  A `total` under `min_per_cluster` is refused, since not even one stratum
  can be funded at its floor.
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

A policy's skills can be real files: a tree under `skills/` in the layout
coding harnesses use (`skills/<name>/SKILL.md`, `references/`, `scripts/`).
The loop improves an agent by generating and diffing that code. The whole
policy is presented as a tree (`policy.json` plus `skills/`), a revision is a
unified diff against it, and the tree is the only place generated code may
live: reading a tree back refuses any other path.

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
   (`evalrun.improve.message`) with the champion as the draft, handed over as
   a tree (`draft_tree`), and is asked (`evalrun.improve.rule.diff`) for a
   minimal unified diff against it, with any code only under `skills/`. A
   diff that does not apply, or a result the lint refuses, comes back as
   findings until its proposal lints clean;
4. the candidate runs the same training cases. It passes the training gate
   when the mean delta is at least the delta band, no axis falls by more than
   the band, and it errors on no case the champion was graded on;
5. the candidate is ablated hunk by hunk (below), and the reduced candidate
   is judged by the training gate again;
6. only then do both run the held-out cases. The candidate must gain there
   (`evalrun.improve.min_holdout_delta`, strictly), under the same axis and
   error rules;
7. a candidate that clears both gates becomes the champion.

**Ablation.** A candidate that passes the training gate is taken apart. For
each hunk of its diff against the champion, up to
`evalrun.improve.ablation_max_hunks` (default 8), the candidate without that
hunk is rebuilt, linted and run on the training cases. When removing the hunk
costs less than `evalrun.improve.ablation_tolerance` of mean score (the
shipped 0.05 is half the shipped delta band), the hunk is dropped. Hunks are
tried in order against the candidate as it stands after the earlier drops,
so two hunks that only work together are not both lost, and the last hunk
left is never dropped, since without it the candidate is the champion. A
hunk whose removal leaves a patch that does not apply or does not lint is
kept. The reduced candidate goes to the holdout only if it still passes the
training gate; otherwise the proposed one does. Ablation is on unless
`evalrun.improve.ablate` is false. Each trial is an ordinary run, pinned to
the same grader and cached by its policy's digest.

**Value gate.** With `--value` (SDK `value=True`), every gate also computes
the delta weighted by each case's value at stake (see Value and
representativeness below) and requires it to clear the same bar as the plain
mean, so a candidate cannot win on cheap cases by losing a costly one. The
receipt records it as `value_delta`. `--concurrency N` runs every one of the
loop's runs N cases at a time, and `--no-ablate` skips ablation.

The held-out cases are a separate corpus when `--holdout-corpus` is given,
which is the stronger test: a policy that learned this company rather than the
task fails on another. Otherwise a share of the corpus
(`evalrun.improve.holdout_share`) is held back by a stable hash of each case
id, and a case that declares its split (`test`, `holdout`, `validation`) keeps
it. A training case that declares a held-out split never trains, whichever
way the holdout is chosen: with `--holdout-corpus` it is dropped, and
`improve.json` counts it as `held_out_dropped`. Every run on the held-out
cases is written with `"split": "holdout"` in its `run.json`, so trace export
recognises it after it leaves the loop. The proposer sees the training brief
only; no held-out case id or result reaches it.

The proposer and the agent under test run in a fresh empty working directory
when either is a bundled harness (`--harness`, `--proposer-harness`): with no
tools where the harness allows it, or in codex's read-only sandbox pointed
there with `--cd`. The
loop's output directory, with its runs and held-out results, is never that
directory. A working directory is not a jail: a codex child with shell access
could still read an absolute path it guessed, so keep the corpus and the
output directory where no child needs to look.

A round stops early when the champion passes every training case (escalate
the curriculum instead), when the proposer asks questions (the operator
answers them), when no proposal lints clean within
`evalrun.improve.authoring_rounds`, when the proposal restates the champion,
or when the proposer fails (`proposer_error`: its process exited non-zero,
timed out or answered with something that is not JSON; the receipt keeps the
error and the loop stops). A reply that is JSON but not the interview's
shape is refused with a finding per field, like any other refusal. If the
grader moves mid-loop the command refuses with `grader_drift`. Every round writes `rounds/NNN.json` with the champion, the
candidate, the grader digest, the brief's digest, the clusters, the authoring
rounds and both gates. A round with a candidate also stores the candidate's
unified diff against the champion (`diff`, and its hunk count in
`diff_hunks`), written beside the receipt as `rounds/NNN.diff`, and, when it
was ablated, `ablation`: the proposed candidate and its diff, the tolerance,
and each hunk with its file, header, decision (`kept`, `dropped` or
`untested`) and measured contribution. The diff is that of the candidate that
went to the holdout, so after ablation it holds only the hunks that carried
the gain, and that candidate is what `packs/agent/` holds under the round's
name. Runs already on disk for the same policy, agent, case set and grader
are reused, so an interrupted loop resumes without paying twice; the agent is
compared by its fingerprint (for `--exec` or `--harness`, the command and the
policy), so a run another agent made under the same pack is run again.
Accepted candidates are stored under `packs/agent/`, so any of them can be
named with `--agent-pack` afterwards.

Round numbers run across every loop into one output directory: a second loop
continues from the last receipt in `rounds/`, so it never overwrites an
earlier loop's receipts, and its candidates are named after their rounds
(`baseline-r3`, with the stem taken from the champion's name less any round
suffix). A name that a receipt or the current champion already refers to, or
that a pack outside the loop's own `packs/` holds, is never overwritten: that
round's candidate takes a suffixed name (`baseline-r3-1f2e3d4c`) instead, so
an earlier loop's champion always resolves by its pinned digest. The loop writes nothing outside its
output directory and that pack root: a candidate's skill tree is
materialised under `skills-cache/` there, not in the user's cache.

## Recursion: improving the improver

The improve loop revises the agent's policy, but the proposer that writes
each diff used to run under fixed instructions. Now it runs under a policy
too, held in the same kind of pack as the agent it improves: an `agent`
pack, so the lint, the tree codec, the diff interview and the content
address all apply unchanged. `agent:proposer-baseline` ships and restates
today's proposer. A proposer reads four of the pack's fields (`system`,
`planning`, `skills` and the `skills/` tree); the meta loop refuses a
proposer that sets the others, since nothing on the interview seam reads
them.

```bash
worldloom evalrun improve ./corpus --agent-pack agent:baseline --harness codex \
  --proposer-harness codex --proposer-pack agent:proposer-baseline \
  --holdout-corpus ./fresh-seed-corpus -o ./improve
```

Under `--proposer-pack` each interview request carries an `agent` block for
the proposer, the same block an evalrun turn carries, and its id covers the
policy's digest. The bundled adapters put the standing instruction and the
skill index ahead of the interview role, inside the fence whose nonce is a
digest of that block. Each authoring round in a receipt records the
proposer's `ref` and `digest`. Without the flag the request, the prompt and
the receipt are byte-identical to before.

The meta loop improves that pack:

```bash
worldloom evalrun improve-proposer --tasks tasks.json \
  --proposer-pack agent:proposer-baseline --proposer-harness codex \
  --meta-rounds 2 --rounds 1 -o ./meta-run
```

`tasks.json` lists training `tasks` and meta-held-out `holdout_tasks`, each
naming a `corpus`, a `holdout_corpus`, an `agent_pack` and the agent's `exec`
or `harness`. A proposer policy is scored by the held-out gain it produces:
for each task `improve` runs with the proposer under that policy, and the
task's score is the mean held-out delta of the agent champion the loop ended
with over the one it started from, measured by running both on the task's
held-out cases (0 when nothing was promoted). The proposer's score is the
mean over tasks; its promotion rate and refused proposals are recorded
beside it and decide nothing.

Each meta round scores the proposer champion on the training tasks, turns
their inner rounds into a brief (rejections and their reasons, refused lint
findings, questions asked, earlier meta rounds), and asks a meta-proposer
for a diff to the proposer pack through the pack interview
(`evalrun.meta.message`). By default the meta-proposer is the same harness
running under the current proposer champion: the improver revises itself.
The candidate is scored on the same training tasks, compared task by task
(`compare_scores`: the mean delta must reach the delta band and no task may
fall by more than the band), and only then on the meta-held-out tasks,
which no brief ever names, where it must gain strictly. Receipts are
written to `meta/rounds/NNN.json` with the proposer diff beside them, and
candidates to `meta/packs/agent/`.

The meta loop changes the proposer pack and nothing else. Every task's
grader and case sets are pinned by digest before the first score and
checked around each one, the inner loops write only under `meta/tasks/`,
and a held-out task may not share a case set with a training task. From
Python, `evalrun.meta.improve_proposer(pack, tasks=..., holdout_tasks=...,
proposer=..., out=...)` runs the same loop, passing any other keyword to
every inner `improve` call, and `EvalSession.improver(...,
proposer_pack=...)` runs an ordinary loop under a promoted proposer.

## Trace export

The runs the loop leaves are training data. `worldloom evalrun export` turns a
run into SFT transcripts, two runs into preference pairs, and any run into
reward records whose verifiable parts are kept apart from the model-rated
answer score. It refuses held-out cases unless asked, because a model trained
on them can no longer be judged on them. See [Trace export](trace-export.md).

## Corner cases from the world's events

The curriculum makes a case harder by its DAG shape or by a designed failure
drawn at random, which makes it hard without making it representative: nothing
in the world said that write should be refused or that record was out of date.
A built world already holds the events that make real work hard, projected into
the records an agent reads (one Jira issue per event, a ServiceNow record per
incident or change). `worldloom.evalrun.corners` turns such an event into a case
whose difficulty is the event, expressed through the grading that already
exists (`reads_contain`, `state_equals`, `failure_at`, `question_required`,
the as-of), with no new executor.

| Template | Events it rests on | Activity | Where the difficulty comes from |
| --- | --- | --- | --- |
| `confirmed_cause` | `root_cause_confirmed`, superseding a `hypothesis_recorded` cause (`ops.cause`) | `i2r.09` Post-incident review | The hypothesis record is older and also names a cause. It is the true stale source: linking it fails the state post-condition. |
| `restated_figure` | `return_restated` (banking), `reserves_strengthened` (insurance), superseding figures on the record | `r2c.06` Regulatory filing, `r2r.02` Post accruals | Two records hold the figures. The as-of decides which: one variant asks for the original, one for the current, one names neither and requires the agent to ask. |
| `escalated_exception` | `exception_escalated` after a failed `match_run` (`p2p.exception_status`) | `p2p.10` Resolve invoice exception | The escalation took the exception out of the buyer's authority, so the buyer's clearing write is refused (`failure_at`, `denied`). The refusal is the world's delegation, not a draw. |
| `approver_handover` | `person_departed` (and `leadership_changed` where the outgoing holder carried work) | `h2r.09` Offboard, `r2r.08` Prepare management pack | The item's history names the outgoing holder; the current one is only in the handover record, so resolving the approver is a real lookup. |

A template that finds no event of its kind yields nothing: an event the world
does not contain is never invented. An occurrence it cannot use (a leadership
change whose outgoing leader carried no work item) is counted as unmatched,
with the reason. Every case carries `dimensions` naming `corner` (the
template), `event`, `evidence` (the event ids it cites, also the row's
`expected_evidence_ids`, with the superseded and superseding facts in
`expected_fact_ids`), `activity`, `workflow`, `value_stream`, `pcf_id`,
`as_of`, `failure` and `question`, so an autopsy slices by them like any
other dimension.

**Solvability.** Every generated case is run by the reference agent through
`run_cases` with its full expected outcome, answer included: a case with an
answer contract is graded by a rater during the proof (`prove(...,
rater=...)`, `corner_cases(..., rater=...)`, `evalrun corners --rater`). The
default is the grounded rater wherever the shape allows it; on a judge-only
shape, or a golden with no figure to check, the answer is left to the other
axes, and a model judge given as the rater grades it. A case the reference
cannot solve is dropped and the reason recorded; `corners.json` reports
generated, solvable, dropped and unmatched per template, and the rater the
proof used. Over seeds 1 to 10 of the four seeded
worlds (`seeded_world`), every generated case was solvable: 20
`confirmed_cause`, 60 `restated_figure`, 10 `escalated_exception` and 10
`approver_handover`, with 10 leadership changes unmatched.

**Frontier search.** `frontier(cases_or_generator, champion, *, reference_agent,
budget, seeds, holdout_ids, holdout_seeds)` keeps the cases the reference
solves and the champion fails. A generator (`corner_generator(engine)`) is
called once per seed in order; a fixed case set is offered in a seeded,
content-addressed order. It stops when `budget` champion runs are spent and
reports per template how many cases were offered, solved by the reference, run
by the champion and left on the frontier. It never touches the holdout: a seed
in `holdout_seeds` or a case id in `holdout_ids` is refused with
`HoldoutOverlap`, not skipped, because a search that looked at the held-out
cases has already learned from them. The same inputs give the same report.

```bash
worldloom evalrun corners ./corpus --out ./corners --templates confirmed_cause,restated_figure --limit 50
worldloom evalrun run ./corners -o ./runs/corners-reference
worldloom evalrun frontier ./corners --champion-harness claude --agent-pack agent:baseline --budget 40 --out ./frontier --holdout ./held-out --seed 1
worldloom evalrun run ./frontier -o ./runs/frontier-candidate --harness claude --agent-pack agent:baseline
```

`evalrun corners` reads a world corpus (`worldloom build --out`) and writes a
case set (`evalrun-cases.jsonl`, `records.jsonl`, `corners.json`) that
`evalrun run` takes. `evalrun frontier` reads a case set, runs the champion
given by `--champion-exec` or `--champion-harness` under `--agent-pack`, and
writes the frontier as a case set with `frontier.json` beside it; frontier
batches from several worlds go one case set per directory, named for the
seed or the world, with the batch index appended when two would share a
name, so no batch overwrites another. `--holdout`
takes a case set directory, a cases JSONL file or a file of ids;
`--holdout-id` and `--holdout-seed` name them one at a time.

**The honest limit.** These events are the simulated company's. The templates
make a case representative of the flows this world models (a close with its
incident, a filed and restated return, a reserving round, a purchase-to-pay
cycle, a departure), and the process catalogue ties each to a real activity.
Whether the mix of corners matches the mix a real enterprise meets, and so
whether a frontier gain lands the value it suggests, needs an empirical
reference: traces or incident logs from real work to weight the templates
against. Until then the frontier says where an agent fails on flows that are
real in kind, not how often a business would meet them.

## Value and representativeness

A pass rate counts a courtesy email and a deleted goods receipt the same, and
a curriculum that chases the most frequent failure can drift into slices the
company rarely runs. Two measurements correct for that. Both are computed at
report time from the cases and the records they run over: no case row, no
case-set digest and no default output changes, and `summarize`, `autopsy`
and `curriculum` print exactly what they printed before unless given values
or a reference.

```bash
worldloom evalrun value ./runs/baseline --corpus ./cases
worldloom evalrun value ./runs/baseline --corpus ./programme --mix activity --json --out value.json
```

### What a case is worth

`value_of(case, records, catalogue=None)` in `worldloom.evalrun.value`
returns a `CaseValue` with a `basis`: one line per input it read or found
missing, naming the record ids and fields.

- **At stake.** The money on the records the expected DAG reads or writes
  (node fixtures, `expected_reads`, `reads_contain`, outcome fixtures, the
  artifact's required records, `expected_record_ids`). Per record: the first
  field in `evalrun.value.money_fields`, else a quantity field times a unit
  price field, else the same money field summed over an operational record's
  observation `history`. Records in different currencies are never added:
  the largest single-currency total is kept and the others are named. A case
  whose records carry no money has `at_stake: null`. Nothing is estimated,
  and a record a create will make carries no money, because it does not
  exist yet.
- **Frequency.** How often the company does the case's activity, per
  period. The activity is the `activity_id` the touched records carry (the
  system-of-record projection writes one on every record), else the row's
  own. The volume is the compiled catalogue's (bindings x record kinds x
  `sor.records_per_period`) when one is passed, else the activity's records
  over the periods they span, else, for an operational case with no
  activity, the exception episodes the simulation raised on its source.
  Every one of these is the simulated company's volume, an authored prior.
  The first two are per period; the episode count is over the simulation's
  whole horizon, so a case records its `frequency_unit` (`period` or
  `horizon`) and is only ever compared with frequencies in the same unit.
- **Error cost.** A multiplier by operation class, the case's costliest
  expected outcome (`read` when it writes nothing), times a factor when it
  carries a designed failure.
- **Weight.** `at-stake factor x frequency factor x error cost`. Each factor
  is the part divided by the set's median of that part, so a typical case
  is 1.0, clamped to `[1/max_factor, max_factor]`. Medians are taken within
  one currency and one frequency unit: a case's money is relative to the
  median of its own currency, never to a median that mixes yen and dollars.
  A missing part is 1.0,
  the typical case: a case with no money is neither favoured nor ignored,
  and its basis says so. `value_table(cases, records)` weighs a whole set
  against its own medians; `value_of` alone can only compare a case with
  itself.

`value_summary(report, cases, records)` reads a run by weight: the
value-weighted pass rate and mean score beside the plain ones, money at stake
passed, failed and errored, the costliest failing cases, and a breakdown per
activity (or `workflow:<name>` when a case maps to none). Errored cases are
not zeros, as in `summarize`. `value_weighted_delta(comparison, values)` is
the weighted twin of a comparison's `mean_delta`, over the same cases, for a
loop that should gate on value; it refuses two runs graded differently.

`autopsy(report, values=table)` adds each cluster's weight, its share of the
failing value and its money, and `order="value"` ranks clusters by weight.
`design_curriculum(..., values=table)` makes each stratum's claim its failure
share times its relative value (the cluster's mean case weight over the
failing cases' mean), which is the cluster's share of the failing value;
uniform values leave the plan unchanged.

| Key | Default | Why |
| --- | --- | --- |
| `evalrun.value.money_fields` | `amount, total_amount, total, net_amount, revenue, due, cost` | The monetary fields the shipped connectors and simulators write, most specific first: `amount` is the system-of-record field, `revenue` and `due` the retail and banking simulators' flow per observation. `cost` comes last because it is the smaller side of a margin. |
| `evalrun.value.quantity_fields` / `unit_price_fields` | `quantity, qty, units` / `unit_price, unit_cost, price` | The fallback when a record carries a line rather than a total. |
| `evalrun.value.error_cost` | read 1, update 2, create 3, delete 5 | A wrong read costs a wrong answer and rework. A wrong update corrupts a record whose history still holds the old value. A wrong create puts a record into the world that others act on (a duplicate order, a spurious payment request) and must be found before it can be undone. A wrong delete destroys the evidence a correction needs, so it costs most. |
| `evalrun.value.designed_failure_factor` | 1.5 | A case that meets a designed failure is one where the system is already misbehaving, and a mistake there compounds (a write past a refusal, a retry that doubles a payment). Half again, not double, because the operation class already prices the write. |
| `evalrun.value.max_factor` | 100 | Money is heavy-tailed. A hundredfold case counts a hundredfold, but one outlier cannot become the whole score. |
| `evalrun.value.top` | 10 | Failing cases listed by `evalrun value`. |
| `evalrun.curriculum.representative_share` | 0.5 | Half of a curriculum's rows keep measuring the work the company does, so a round cannot improve the tail by regressing the body unnoticed; half is also enough rows for a pass rate with a usable interval on each side. |
| `evalrun.curriculum.max_mix_tvd` | 0.3 | At least 70% of a plan's probability mass sits where the reference puts it. With the default share the tail may still concentrate hard on failures, but not so hard that the plan stops resembling the company. |

### A realistic mix

`mix_report(cases, reference=..., records=...)` reports the case set's shares
over activity, workflow and operation and, given a `ReferenceMix`, the total
variation distance to it (half the L1 distance between the two share maps)
with the most over- and under-represented slices. `reference_mix(records,
dimension="activity")` counts the company's records per activity (also
`stream`, `lob`, `pcf_id`, `function`); `reference_from_catalogue(compiled)`
derives the same mix from the compiled bindings, and also offers
`activity_type`. `check_mix(cases_or_plan, reference, max_tvd)` is the guard:
exact over compiled cases, predicted over a plan from the value each stratum
pins (a stratum that pins none is assumed to follow the reference).

`design_curriculum(..., reference=mix)` keeps `representative_share` of the
rows drawn to match the reference (one stratum per reference value when the
dimension is a dataset predicate, otherwise spread over the base strata,
whose own draw is the company's mix) and puts only the rest on failure
targets. When the targets pin slices far from the reference, the
representative share is raised until the whole plan is within
`max_mix_tvd`; a reference that leaves fewer rows than `min_per_cluster` for
the targets is refused. The check is returned as the curriculum's `mix`.
Representative strata carry the key `mix:representative`, and
`mix_scores(report, curriculum, strata=...)` scores a run over the
curriculum's cases on those rows and on the failure-targeted tail apart, so a
gain on the tail that costs the body is visible.

"Representative" here is relative to the company's own simulated operations:
record and binding volumes derived from the process catalogue and the
operational simulators, which are authored priors. Until an empirical
reference population exists (empirical source acquisition is listed as unmet
in [Implementation status](implementation-status.md)), a representative
curriculum is representative of the simulated company, not of any real one.
The operational simulators also run one workflow per vertical today, so their
workflow mix is a single slice; the process-binding volumes are the reference
with more than one value.
