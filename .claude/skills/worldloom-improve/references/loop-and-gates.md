---
title: Loop and Gates
description: One improvement round step by step, the training and held-out gates, where the held-out cases come from, resume, and every knob.
read-when: Reading a rejected or surprising receipt, choosing a holdout, or changing a loop setting.
tags: [worldloom, evalrun, improve, gates, holdout, resume]
---

# The loop and its two gates

Read this when a receipt surprises you, before choosing where the held-out
cases come from, or before changing any loop setting.

## One round

1. The champion runs the training cases. The run lands in
   `runs/<pack>@<digest12>/train/`.
2. `autopsy` clusters its failures and `render_brief` writes the brief. With
   no failures the round ends `no_failures` and the loop stops.
3. The proposer receives the brief through the pack interview (prompt
   `evalrun.improve.message`) with the champion as the draft. It is refused
   with findings until the proposal lints clean, up to
   `evalrun.improve.authoring_rounds` exchanges. Questions end the loop
   (`questions`); no clean proposal ends the round (`refused`); a proposal
   equal to the champion ends it (`unchanged`).
4. The candidate runs the same training cases and is judged (training gate).
5. Only if it passes do both run the held-out cases (held-out gate).
6. Passing both makes the candidate the champion: `promoted`.

## The gates

Both compare champion to candidate case by case (`evalrun compare` semantics)
and fail with every reason listed:

| Rule | Training gate | Held-out gate |
| --- | --- | --- |
| Mean delta | at least the delta band (`evalrun.delta_band`, 0.1) | strictly above `evalrun.improve.min_holdout_delta` (0.0) |
| Any axis (plan, trajectory, outcomes) | may not fall by more than the band | same |
| Newly errored cases | none | none |
| Same grader, same case set, at least one case compared | required | required |

A candidate that wins training and loses the holdout learned the cases, not
the behaviour. That is the gate working; do not loosen it to promote.

**Over repeats** (`--repeats K`, K above 1) each case is reduced to its mean
score on each side and the gates judge a paired bootstrap interval of the
per-case differences instead of one delta:

| Rule over repeats | Training gate | Held-out gate |
| --- | --- | --- |
| Mean delta | at least the band, and the interval's lower bound at least `evalrun.improve.min_train_ci` (0.0) | the interval's lower bound strictly above `evalrun.improve.min_holdout_delta` |
| Value-weighted delta (`--value`) | same rule | same rule |
| Any axis | fails only when its interval's upper bound is below minus the band | same |
| Newly errored | errored in most candidate repeats and in no champion repeat | same |

The gate then carries `repeats`, `ci_low`, `ci_high`, `stderr`, `t_low`,
`t_high`, `confidence`, `method`, `axis_intervals`, `value_interval`,
`noise_floor_champion` and `noise_floor_candidate`. A lower bound at or below
zero on training means the gain is not distinguishable from run-to-run
noise: that is a rejection to believe, not one to rerun until it passes.

## Where the held-out cases come from

- **A separate corpus** (`--holdout-corpus`, or `holdout=` a second
  `EvalSession`): cases from fresh seeds. The stronger test, because a policy
  that learned this company rather than the task fails on another.
- **A stable share** (`--holdout-share`, default `evalrun.improve.holdout_share`,
  0.25): each case lands by a hash of its id, the same side in every round. A
  case that declares its split (`test`, `holdout`, `validation`) keeps it.

Training and held-out case ids must not overlap; the loop refuses otherwise.
A training case that declares a held-out split never trains: beside a
separate holdout it is dropped and counted in `improve.json` as
`held_out_dropped`. Held-out runs carry `"split": "holdout"` in `run.json`,
so export refuses them after they leave the loop.

## Output directory

```text
improve/
  improve.json                 the ImproveReport: initial, champion, rounds, promotions
  rounds/001.json ...          one RoundReceipt per round
  runs/<pack>@<digest12>/train|holdout/   ordinary run directories
  runs/<pack>@<digest12>/train|holdout/rep-<i>/   one per repeat, when --repeats is above 1
  packs/agent/<stem>-rN.json   every accepted proposal, usable as --agent-pack
```

**Numbering.** Rounds are numbered across every loop into one `-o`: a second
loop continues after the last receipt, so earlier receipts and candidates are
never overwritten. A name a receipt or the champion already uses, or that a
pack outside `packs/` holds, gets a suffix instead (`baseline-r3-1f2e3d4c`).

**Resume.** A run on disk for the same pack digest, agent fingerprint, case
set digest and grader digest is read instead of paid for again, so rerunning
an interrupted loop into the same `-o` continues it. Changing the rater, the
cases or the agent (another `--exec` command or `--harness`) starts those
runs over. With repeats, each `rep-<i>` is cached on its own, so a resumed
loop reruns only the repeats it lost.

## Knobs

| CLI | SDK (`session.improver(...)` or `loop.run`) | Default |
| --- | --- | --- |
| `--rounds` | `loop.run(champion, rounds=)` | `evalrun.improve.rounds` (3) |
| `--holdout-share` | `holdout_share=` | `evalrun.improve.holdout_share` |
| `--holdout-corpus` | `holdout=` | none |
| `--rater` | `rater=` | none (answers unrated) |
| none | `min_train_delta=`, `min_holdout_delta=`, `max_axis_regression=` | the policies above |
| none | `authoring_rounds=` | `evalrun.improve.authoring_rounds` (4) |
| `--concurrency` | `concurrency=` | `evalrun.concurrency` |
| `--value` | `value=True` | off: gates judge the plain mean only |
| `--no-ablate` | `ablate=False` | `evalrun.improve.ablate` (on) |
| `--repeats` | `repeats=` | `evalrun.improve.repeats` (1: one run a side, the single-run rules) |
| none | `improve(confidence=)` | `evalrun.improve.confidence` (0.95) |
| none | `improve(resamples=)` | `evalrun.improve.bootstrap_resamples` (2000) |
| none | `improve(min_train_ci=)` | `evalrun.improve.min_train_ci` (0.0) |
| `evalrun noise` | `noise.noise(runs)` | power `evalrun.improve.power` (0.8) |

**Sizing repeats.** Run the champion two or three times and read
`worldloom evalrun noise RUN_DIR... [--cases N] [--repeats K]`: it reports the
pooled run-to-run standard deviation and the minimum detectable effect for N
cases at K repeats a side. Pick K so that effect is below the delta band;
otherwise a real band-sized gain and a lucky draw look the same.

**Value gate.** With `--value` (SDK `value=True`) every gate also computes the
delta weighted by each case's value at stake (`evalrun value` explains the
weights) and requires it to clear the same bar as the plain mean. A candidate
that wins many cheap cases by losing one costly case is refused, and the
receipt's `value_delta` says by how much.

The low-level function is `worldloom.evalrun.improve.improve(champion, cases,
run=, agent_for=, exchange=, out=, ...)`; the session builds those callables
and calls it unchanged.
