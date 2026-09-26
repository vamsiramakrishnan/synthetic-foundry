---
title: Training Data from the Loop
description: Export a loop's runs as SFT transcripts, preference pairs or reward records, and the holdout guard that keeps promotion meaningful.
read-when: Turning runs into fine-tuning or reward data, or asked to include held-out cases in an export.
tags: [worldloom, evalrun, export, sft, preferences, rewards, holdout]
---

# Training data: exporting what the loop ran

Read this when turning runs into fine-tuning or reward data, or when anyone
asks to include held-out cases in an export.

The runs a loop leaves are training data. Three formats:

| Format | From | Record |
| --- | --- | --- |
| `sft` | one run | A chat transcript per case that passed (or scored at least `--min-score` with `--include-failed`), rebuilt from the ledger in recorded order: calls, results, questions and replies, refused calls as tool errors, the answer |
| `pairs` | two runs of one case set | Chosen and rejected continuations of one prompt where the lead is at least the margin (default `evalrun.delta_band`); refuses runs graded differently |
| `rewards` | one run | Overall reward and per-axis scores, with the `verifiable` parts (what the service observed) kept apart from the `model_rated` answer score |

```bash
worldloom evalrun export ./improve/runs/baseline-r1@0123456789ab/train --corpus ./cases --format sft -o sft.jsonl
worldloom evalrun export ./runs/champion --corpus ./cases --format pairs --against ./runs/baseline -o pairs.jsonl
worldloom evalrun export ./runs/champion --corpus ./cases --format rewards -o rewards.jsonl
```

```python
session.export("champion", "sft", out="sft.jsonl")          # with each case's tool catalog
session.export("champion", "pairs", against="baseline")
session.export("champion", "rewards", splits=("train", "validation"))
```

## The holdout guard

Promotion is decided on held-out cases. A model trained on them has seen the
exam, and every later promotion over them is void. So an export:

- keeps `train`, and any case with no split, by default, and says how many of
  each other split it withheld;
- keeps another split only when named (`--split validation`);
- refuses `test` or `holdout` unless `--include-holdout` (`include_holdout=True`)
  is given, which is only for a set that will never be used to promote.

In the loop, the held-out cases are the holdout corpus or the held-back share;
export from `runs/*/train` only. Never feed `runs/*/holdout` back into
training, and never export a curriculum's `test` split.

Records are ordered by case id with sorted keys, so the same run exports to the
same bytes. Details: `docs/trace-export.md`.
