---
title: Grader and Agreement
description: The grader's identity and digest, why the loop pins it, what GraderDrift means, and measuring agreement with Eval Studio before trusting the rater.
read-when: Choosing a rater for a loop, the loop raised GraderDrift, or a comparison refuses two runs as differently graded.
tags: [worldloom, evalrun, grader, rater, agreement, eval-studio]
---

# The frozen grader and its agreement with Eval Studio

Read this before choosing a rater for a loop, after a `GraderDrift`, or when
`compare` refuses two runs as differently graded.

## Identity

The grader is the rater (by kind and name; an `exec:` command with secrets
redacted), the `rater.*` prompt texts in force, the rubrics and the grading
policy, reduced to one digest by `grader_identity(rater)`. Every run records
it in `run.json` as `grader`.

The loop pins the digest before round one and checks it before and after every
run. If it moves, `GraderDrift` is raised and the loop stops: numbers measured
by two graders cannot be compared, and a loop that could move its own
measuring stick would be measuring nothing. `evalrun compare` likewise refuses
to call anything an improvement across two graders (`grader_mismatch`).

Things that move the digest: a different `--rater`, a pack that overrides a
`rater.*` prompt or a rubric, a change to the grading policy keys. Fix the
cause and rerun; runs made under the old grader are not reused.

## Choosing a rater

- `grounded`: no model. Scores an answer by the golden's figures and
  identifiers and refuses (leaves unrated) the shapes a lexical check cannot
  judge. The safe default for a loop.
- `exec:<command>`: a judge over the `--exec` seam, given the Eval Studio prompt
  for the case's shape; it prints a score or a model reply.
- In Python, any object with a `name` and `__call__(case, answer)` returning
  `(score, error)`.

A failed judgement is an error on that case, excluded from the answer mean,
never a zero.

## Agreement with Eval Studio

Before a rater decides promotions, measure whether it agrees with the grader
the team already trusts. Each Studio row's own answer is rated again locally,
so only the grader differs:

```bash
worldloom evalrun agreement ./cases eval_results.csv --rater grounded -o ./agreement
```

```python
report = session.agreement("eval_results.csv", rater="grounded")
report.verdict, report.stats.kappa, report.stats.mae, report.worst[:5]
```

It reports mean absolute error, Pearson and Spearman correlation, the share
within the comparison band, Cohen's kappa of pass or fail at the pass mark,
per-shape slices and the worst disagreements, then a verdict against
`evalrun.agreement.min_kappa`, `max_mae` and `min_cases`. Judge-only shapes the
grounded rater abstains on are counted, not scored. Only the answer axis is
comparable: Eval Studio observes no tool call.

A rater that disagrees is a finding to report, not a prompt to tune until it
agrees on this set.
