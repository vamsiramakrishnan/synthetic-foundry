---
title: Recursion
description: The proposer's own policy as an agent pack, how it reaches the harness, and the meta loop that revises it by the held-out gain it produces.
read-when: Read this when the proposer itself should get better, when a receipt's authoring rounds name a `proposer`, or when running `evalrun improve-proposer`.
tags: [worldloom, evalrun, improve, proposer, meta, recursion]
---

# Improving the improver

Read this when the proposer, not the agent, is what should get better, when
a receipt's authoring rounds carry a `proposer` identity, or before running
`evalrun improve-proposer`.

## The proposer's policy is an agent pack

The harness that writes the diffs runs under a pack of kind `agent`, the same
kind as the agent under test. `agent:proposer-baseline` ships and restates
what the proposer does today. Only four fields reach a proposer: `system`,
`planning`, `skills` and the `skills/` tree. The meta loop refuses a proposer
that sets `turn_rules`, `plan_rules`, `tools` or `max_turns`, because nothing
reads them on the interview seam and a change there would be scored as noise.

```bash
worldloom evalrun improve ./cases --agent-pack agent:baseline --exec 'python agent.py' \
  --proposer-exec 'python proposer.py' --proposer-pack agent:proposer-baseline \
  --holdout-corpus ./fresh-cases -o ./improve
```

With `--proposer-pack` every interview request carries an `agent` block
(`ref`, `digest`, `system`, `planning`, `skills`, and `skills_dir` with
`skill_index` for a skill tree). The bundled `--proposer-harness` adapters put
it ahead of the interview role, fenced by a nonce derived from the block, as
they do for an agent under test. Each authoring round in `rounds/NNN.json`
records `proposer: {ref, digest}`. Without the flag nothing changes, byte for
byte.

## The meta loop

```bash
worldloom evalrun improve-proposer --tasks tasks.json \
  --proposer-pack agent:proposer-baseline --proposer-exec 'python proposer.py' \
  --meta-rounds 2 --rounds 1 -o ./meta-run
```

`tasks.json` holds `tasks` (training) and `holdout_tasks` (meta-held-out),
each `{name, corpus, holdout_corpus, agent_pack, exec | harness}`, with paths
relative to the file. A held-out task may not share a case set with a
training task.

One meta round:

1. **Score.** For each training task, `improve` runs with the proposer under
   the champion policy. The task's score is the held-out mean delta of the
   agent champion it ends with over the one it started from, measured by
   running both on the task's held-out cases; 0 when nothing was promoted.
   Promotion rate and refused proposals are recorded beside it.
2. **Brief.** Each training task's inner rounds: decisions, reasons, refused
   findings, questions, and what earlier meta rounds tried. No held-out task
   is named.
3. **Propose.** The same harness, running under the policy it revises,
   returns a diff to the proposer pack (`evalrun.meta.message`).
4. **Gates.** The candidate must gain on the training tasks (mean delta at
   least the delta band, no task down by more than the band), and only then
   strictly on the held-out tasks.

## Reading a meta receipt (`meta/rounds/NNN.json`)

- `decision`: `promoted`, `rejected`, `no_failures`, `questions`, `refused`,
  `unchanged` or `proposer_error`, as in an inner receipt.
- `champion_train`, `candidate_train`, `champion_holdout`,
  `candidate_holdout`: per-task scores (`gain`, `promotions`,
  `promotion_rate`, `refusals`, and the inner rounds).
- `train`, `holdout`: the paired gates, with `task_deltas`. No `holdout`
  means training failed and the held-out tasks were never spent.
- `meta_proposer`: the policy the revising harness ran under; `diff`: the
  proposer diff, also written as `NNN.diff`.

## Rules

- The meta loop writes only under `<out>/meta`. It never edits a grader, a
  case set or an agent pack; every task's grader and case sets are pinned by
  digest and checked around every score.
- A promoted proposer lives in `<out>/meta/packs/agent/`. Use it by file with
  `evalrun improve --proposer-pack`, never by copying a rejected one forward.
