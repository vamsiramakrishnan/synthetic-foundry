---
title: Campaigns
description: The outer loop over stages of fresh cases, how a stage decides the next one, the held-out seal, the cross-stage ledger, and resuming.
read-when: The improve loop stopped with no_failures or plateaued and the agent should keep improving, or the owner asks how much a policy improved on cases it never saw.
tags: [worldloom, evalrun, improve, campaign, curriculum, escalation, holdout]
---

# Campaigns: stages of fresh cases until nothing harder is left

Read this when an improve loop stopped with `no_failures` or stopped
promoting, when the next round needs cases that are both fresh and harder,
or when someone asks how much the policy improved over where it started.

## One command

```bash
worldloom evalrun campaign ./cases --agent-pack agent:baseline --harness codex \
  --proposer-harness codex --plan base-plan.json --stages 4 --seed 11 -o ./campaign
```

`./cases` is run by the champion first; its failures decide stage 1.
`--plan` is the base `DatasetPlan` every stage compiles from under seeds
the campaign derives and never reuses. `--rounds`, `--rater`,
`--concurrency` and `--value` mean what they mean for `evalrun improve`.
`--json` prints `campaign.json`.

## How a stage decides the next one

1. Saturated (`no_failures`) or plateaued (`evalrun.campaign.patience`
   rounds without a promotion): **escalate**. `escalate` reads the
   champion's training run and proposes harder shapes and designed
   failures beside each slice it has mastered.
2. Still failing: **target**. `design_curriculum` over the champion's
   autopsy, value-weighted with `--value`, with a representative share.
3. `questions` or `proposer_error`: stop. Answer or fix, then run the same
   command again.

It also stops on the stage budget, the case budget (`--max-cases`),
`no_new_cases` and `nothing_harder`. A small stage can saturate without a
slice whose Wilson interval clears the band; then `nothing_harder` says to
spend more cases per stage, not that the agent is finished.

## Reading `campaign.json`

- `stopped`, `reasons`: why it ended, in words.
- `stages[]`: `mode`, `description`, `seeds`, `train_case_set`,
  `held_case_set`, `improve` (rounds, decisions, promotions, champion
  before and after), `status` and `status_reason`.
- `ledger[]`: per stage, the **original** champion and the **current** one
  on that stage's held-out cases (`passed`, `pass_rate`, `mean`) and
  `mean_delta`, `pass_rate_delta`. This is the answer to "how much did it
  improve": measured every stage, on cases neither side trained on.

## From Python

```python
from worldloom.evalrun import EvalSession

session = EvalSession.open("./cases")
loop = session.campaign(agent=session.harness("codex"), proposer=session.proposer("codex"),
                        builder="base-plan.json", out="./campaign", seed=11, rounds=3)
report = loop.run("agent:baseline", stages=4)
for entry in report.ledger:
    print(entry.stage, entry.original.pass_rate, entry.current.pass_rate, entry.mean_delta)
best = loop.champion(report)
```

`builder` also takes any `StageBuilder`: a callable from a `StageRequest`
to `(train_cases, held_cases, records_train, records_held, description)`
that raises `StageExhausted` or `NothingHarder` with its reason.
`CornerStageBuilder(engine="retail")` builds stages from event-grounded
corner cases and escalates by searching the frontier.

## Rules that are never broken

- **Held-out cases never train.** A stage whose training set holds an
  earlier held-out case (by id, request and row), or whose held-out set
  holds a trained case, is refused (`held_out_overlap`, `refused.json`).
  Never work around it by renaming cases: fix the builder.
- **Seeds are the campaign's.** Do not hand a builder seeds of your own; the
  stage records the ones it derived, and a resumed campaign checks them.
- **A completed stage is final.** Rerunning reads `stage.json` back. To
  change a finished stage, start a new directory.
