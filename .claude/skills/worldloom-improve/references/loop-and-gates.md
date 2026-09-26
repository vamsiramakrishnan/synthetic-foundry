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

## Where the held-out cases come from

- **A separate corpus** (`--holdout-corpus`, or `holdout=` a second
  `EvalSession`): cases from fresh seeds. The stronger test, because a policy
  that learned this company rather than the task fails on another.
- **A stable share** (`--holdout-share`, default `evalrun.improve.holdout_share`,
  0.25): each case lands by a hash of its id, the same side in every round. A
  case that declares its split (`test`, `holdout`, `validation`) keeps it.

Training and held-out case ids must not overlap; the loop refuses otherwise.

## Output directory

```text
improve/
  improve.json                 the ImproveReport: initial, champion, rounds, promotions
  rounds/001.json ...          one RoundReceipt per round
  runs/<pack>@<digest12>/train|holdout/   ordinary run directories
  packs/agent/<stem>-rN.json   every accepted proposal, usable as --agent-pack
```

**Resume.** A run on disk for the same pack digest, case set digest and grader
digest is read instead of paid for again, so rerunning an interrupted loop
into the same `-o` continues it. Changing the rater or the cases starts those
runs over.

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

**Value gate.** With `--value` (SDK `value=True`) every gate also computes the
delta weighted by each case's value at stake (`evalrun value` explains the
weights) and requires it to clear the same bar as the plain mean. A candidate
that wins many cheap cases by losing one costly case is refused, and the
receipt's `value_delta` says by how much.

The low-level function is `worldloom.evalrun.improve.improve(champion, cases,
run=, agent_for=, exchange=, out=, ...)`; the session builds those callables
and calls it unchanged.
