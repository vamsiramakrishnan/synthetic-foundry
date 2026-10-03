---
title: Failures and Curriculum
description: Autopsy finding keys and lift, the brief a proposer reads, targeted curricula of fresh cases, and escalation of saturated slices.
read-when: Interpreting a brief, the loop stopped with no_failures, or the next round needs new cases aimed at a failure.
tags: [worldloom, evalrun, autopsy, curriculum, escalation]
---

# Failures, the brief, and the next round's cases

Read this when interpreting a brief, when the loop stopped `no_failures`, or
when the next round needs fresh cases aimed at what still fails.

## Autopsy

```bash
worldloom evalrun autopsy ./improve/runs/baseline@0123456789ab/train --out autopsy.json
```

```python
run = Path("./improve/runs/baseline@0123456789ab/train")   # or a session label, or a RunReport
found = session.autopsy(run)          # clusters, lifts, exemplars
print(session.brief(run))             # the text a proposer receives
```

Each failing case is named by closed, low-cardinality finding keys that never
carry an id or free text, so clusters compare across case sets:

| Family | Keys |
| --- | --- |
| Trajectory | `trajectory.safety:<law>`, `trajectory.question:<law>`, `trajectory.failure_leaked`, `trajectory.failure_not_reached`, `trajectory.budget_exceeded`, `trajectory.retry_storm`, `trajectory.refused_call` |
| Plan | `plan.missing:<read/write/verify>`, `plan.extra_write`, `plan.order` |
| Outcomes | `outcomes.unmet:<create/update/delete>`, `outcomes.collateral`, `outcomes.ungrounded`, `outcomes.answer_below_threshold`, `outcomes.answer_unrated`, and on source-policy cases `outcomes.clarification_missing`, `outcomes.stale_source_used`, `outcomes.authoritative_source_missing` |
| Stages | `query.missed_evidence`, `query.overfetch`, `query.missing_filter`, `query.wrong_window`, `query.malformed`, `query.wrong_scope`, `query.zero_result`, `query.error`, `plan.node_missing:<kind>`, `plan.node_extra:<kind>`, `plan.node_misordered`, `output.field_mismatch`, `output.wrong_format`, `output.missing_section`, `output.ungrounded_fact` |
| Other | `error:<code>`, `assertion.fail`, `run.errored`, `unclassified` (a gap: report it) |

A cluster reports its case count, share of failing cases (shares can sum past
one), and where it concentrates as **lift**: a value's share of the cluster
over its share of the whole run. Lift above one is where the failure is more
common than the case set explains. The full table is in
`docs/self-improvement.md`.

## Curriculum

Fresh cases for the next round, aimed at the clusters, under a seed derived
from the base seed and the round (never the base seed: the cases that exposed
a failure are never the ones used to fix it), with a `test` split held back:

```bash
worldloom evalrun curriculum ./runs/baseline --plan base-plan.json --out round-2.json --round 2 --holdout-share 0.25
worldloom evals dataset compile round-2.json --out ./round-2
```

```python
plan = session.curriculum("baseline", "base-plan.json", round=2, holdout_share=0.25)
plan.targets, plan.unmappable      # strata, and every cluster no filter could express, with the reason
```

Unmappable clusters are listed, never dropped: `run.errored` describes the run
rather than the agent, and some failure kinds have no DAG shape that admits
them. Report them.

## Escalation

When the champion passes everything in a slice, that slice teaches nothing.
`escalate` puts a 95% Wilson interval on each `dag_shape x failure` and `shape`
slice and calls it saturated only when the whole interval lies above the
target band (default 0.3 to 0.8). For each it proposes heavier shapes, a
designed failure not yet tried there, and the cases to retire.

```bash
worldloom evalrun curriculum ./runs/round-3 --plan base-plan.json --out round-4.json --round 4 --history ./runs/round-1 --history ./runs/round-2
```

```python
session.escalate("round-1", "round-2", "round-3")   # pooled
```

A loop that stopped `no_failures` is the signal to escalate, compile the new
plan, and start the next loop on the harder cases with the current champion.

## Trace-level brief

When the autopsy says `error:validation_error` and nothing more, a proposer
writes advice about retrying. Show it the connectors' own messages instead:

```bash
worldloom evalrun run ./cases --agent reference -o ./runs/reference
worldloom evalrun improve ./cases --agent-pack agent:baseline --harness codex \
  --proposer-harness codex --holdout-corpus ./fresh-cases \
  --brief traces --reference-run ./runs/reference -o ./improve
```

With `--holdout-corpus`, every case of `./cases` trains, so a reference run
over all of it is admissible. Without one, a share of `./cases` is held out
and a reference run over all of it is refused: run the reference agent on
the training share only, or give a separate holdout.

```python
loop = session.improver(agent=..., proposer=..., out="./improve", brief="traces",
                        reference_run="./runs/reference")
```

Below the summary the brief then carries, in priority order:

1. **Error catalogue.** Each tool, error code and message pattern (ids,
   quoted values and numbers masked, so twenty values of one mistake are one
   group), most frequent first (weighted by case value when the loop has
   values), with one raw message, a few failing arguments, and accepted
   calls of the same tool from this run and from the reference run.
   Refusals (`unknown_arguments`) appear with their argument names.
2. **Tool contracts.** The declared parameters (`?` optional), required
   create fields, query language, searchable fields and enumerated values
   of every tool in the catalogue.
3. **Trajectories.** One failing case per top cluster, turn by turn, with
   the reference agent's calls on the same case beside it: record ids
   masked, write payloads as field names, no answer.

Items that do not fit the interview message are dropped whole, lowest
priority first, and the brief says how many. `summary` (the default, policy
`evalrun.improve.brief`) is the brief byte for byte as before.

The reference run must cover training cases only. One marked held out, over
the held-out set, or holding any held-out case is refused before a run is
paid for; never point `--reference-run` at a `holdout` run directory.
