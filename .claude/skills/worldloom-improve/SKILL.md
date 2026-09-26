---
name: worldloom-improve
description: "Improve an agent or harness policy against a Worldloom enterprise case set: run the champion, cluster its failures, have a proposer revise the `agent` pack, and keep the revision only when it wins on the training cases and then on held-out cases it never saw, under a grader frozen by digest. Use when asked to make an agent better on enterprise workflows, to tune its policy, standing instruction, tool advice or skills, to compare and promote a candidate policy, to target the next round's cases at its failures, or to export the loop's runs as training data. For a single evaluation or comparison without changing the agent, use worldloom-evalrun."
metadata: {tags: [worldloom, evalrun, improve, self-improvement, agent-packs, holdout, promotion]}
---

# Improving an agent, one receipted round at a time

The loop changes one thing, the agent's policy (an `agent` pack), and keeps a
change only when it wins where it was not tuned. Every round leaves a receipt.
`docs/self-improvement.md` is the design; this is the procedure.

## One command

```bash
worldloom evalrun improve ./cases --agent-pack agent:baseline --harness codex \
  --proposer-harness codex --holdout-corpus ./fresh-cases --rounds 3 -o ./improve
```

`--exec`/`--proposer-exec` take any adapter instead. `--holdout-corpus` should
come from fresh seeds; without it a stable share of cases is held back by id.

## From Python

```python
from worldloom.evalrun import EvalSession

session = EvalSession.open("./cases")
loop = session.improver(agent=session.harness("codex"), proposer=session.proposer("codex"),
                        holdout=EvalSession.open("./fresh-cases"), rater="grounded",
                        concurrency=8, out="./improve")
report = loop.run("agent:baseline", rounds=3)
best = loop.champion(report)                    # the winning pack, pinned by digest
for receipt in report.rounds:
    print(receipt.round, receipt.decision, receipt.reasons[:1])
```

`agent` and `proposer` also take any callable (a pack to an agent; an
interview request to a reply), which is how a test drives the loop offline.

## Reading a round receipt (`rounds/NNN.json`)

- `decision`: `promoted`, `rejected` (a gate failed), or why no candidate was
  judged: `no_failures`, `questions`, `refused` (no proposal linted clean),
  `unchanged` (the proposal restated the champion), `proposer_error` (the
  proposer's process failed, timed out or answered with something that is
  not JSON; `reasons` holds its error).
- `reasons`: every reason, in words. A rejection names the gate and the rule.
- `failing`, `clusters`, `brief_digest`: what the proposer was shown;
  `champion`, `candidate`, `grader`: identities by digest.
- `train`, `holdout`: the two gates (`passed`, `mean_delta`, `axis_deltas`,
  `regressions`, `newly_errored`). No `holdout` means training already failed,
  so the held-out cases were never spent on that candidate.

## Why a loop stops before its rounds run out

1. `no_failures`: the champion passes every training case. Escalate the
   curriculum; more rounds here teach nothing.
2. `questions`: the proposer asked something only the operator can answer.
   Answer it and run again; paid-for runs are reused.
3. `proposer_error`: the proposing harness did not answer. Fix its install,
   login or timeout and run again; paid-for runs are reused.
4. `GraderDrift` (raised; the CLI refuses with `grader_drift`): the grader's
   digest moved mid-loop. Nothing after it is comparable; find what changed
   the rater, prompts or policy.

## Rules that are never broken

- **The grader is frozen.** Pin one rater for the whole loop. Never change a
  `rater.*` prompt, a rubric or the grading policy to make a candidate pass.
- **Never tune on the holdout.** The proposer sees the training brief only. Do
  not paste held-out ids, results or failures into a proposal, and do not
  export held-out cases as training data.
- **Generated content lives only in the agent pack.** A proposal changes the
  pack's policy and its skills tree, nothing else: no edits to `src/`, the
  grader, the cases or the connector fixtures.
- **Promotion only through both gates.** A candidate is the champion only when
  its receipt says `promoted`. Never copy a rejected candidate's pack forward
  by hand, and never lower the delta band to let one through.

## Read next

- `references/loop-and-gates.md`: a round step by step, both gates, holdout, resume, knobs.
- `references/agent-packs.md`: the policy, locked rules, the skills tree and diffs against it.
- `references/failures-and-curriculum.md`: autopsy keys, the brief, curricula, escalation.
- `references/grader-and-agreement.md`: grader identity, drift, agreement with Eval Studio.
- `references/scale.md`: concurrency, shards, merge and resume for the runs a loop pays for.
- `references/training-data.md`: exporting runs as SFT, pairs or rewards; the holdout guard.
- `references/recursion.md`: the proposer's own policy pack and `evalrun improve-proposer`, which improves the improver.
