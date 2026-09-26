# Trace export: graded runs as training data

`worldloom evalrun export` turns a graded run directory into JSONL a trainer
reads: supervised demonstrations, preference pairs, or reward records. It
grades nothing and re-derives no score. Every record is a reading of the run
ledger (`run.json`, `results.jsonl`) against the corpus the run was over, so a
record says exactly what the ledger says.

```bash
worldloom evalrun run ./cases -o ./runs/reference
worldloom evalrun run ./cases -o ./runs/mine --exec "python3 my_agent.py"
worldloom evalrun export ./runs/reference --corpus ./cases --format sft -o sft.jsonl
worldloom evalrun export ./runs/reference --corpus ./cases --format pairs --against ./runs/mine -o pairs.jsonl
worldloom evalrun export ./runs/mine --corpus ./cases --format rewards -o rewards.jsonl
```

The library entry points are in `worldloom.evalrun.export`: `sft_records`,
`preference_pairs`, `reward_records` and `write_records`.

## Why the corpus is required

The ledger holds the request, not the persona that asked it, and a split
lives on the case, not on the result. The export also checks that the run
was over this corpus: the run's `case_set` digest must match the cases it
holds (a run cut short with `--limit` still matches) or the whole set. A run
read against the wrong corpus is refused, because its personas and splits
would be someone else's.

## SFT demonstrations (`--format sft`)

One chat transcript per case, rebuilt in the order the service recorded it:

1. `system`: the agent pack's `system` text when `run.json` names an agent
   pack that still resolves to the recorded digest, then the turn rules in
   force (`evalrun.turn.rule.*`). A pack that does not resolve, or resolves
   to different content, is left out: a demonstration under a system prompt
   the agent never saw teaches the wrong conditional.
2. `user`: the query, with the persona when the case has one.
3. Per span, by ordinal: an `assistant` message carrying one `tool_calls`
   entry (the tool and the arguments the service recorded) and a `tool`
   message with the result, or `{"error": {code, kind, message}}` for a
   failed call.
4. Each question at the position it was asked: its `index` is the number of
   spans recorded before it, so it goes in front of the next span, as an
   `assistant` message (the question) and a `user` message (the reply).
5. Each refused call as a tool call and a `tool` message carrying the
   serving error. The service records a refusal's tool, argument names and
   error, not its argument values or its position. Argument names are kept
   with null values, and a refusal without an `index` is placed after the
   last span. `metadata.order` labels every turn (`call:s1`, `ask:q1`,
   `refused:1`, `answer`) so a reader can see where each came from.
6. The final `assistant` answer.

A case qualifies when it is graded, scores at least `--min-score`, and
passed; `--include-failed` drops the pass requirement. Tool results longer
than the policy `evalrun.export.max_result_chars` (4000) are cut with a
marker that says how much was removed; `--max-result-chars` overrides it.
The CLI also attaches each case's tool catalog, as the run advertised it,
under `tools`.

```json
{"schema": "worldloom.trace-export.sft/v1", "id": "...", "messages": [...], "tools": [...],
 "metadata": {"case_id": "...", "case_set": "...", "agent": "...", "agent_pack": null, "grader": null,
              "scores": {"overall": 1.0, "plan": 1.0, "trajectory": 1.0, "outcomes": 1.0},
              "observed": ["plan", "trajectory", "outcomes"], "passed": true,
              "dimensions": {...}, "split": "train", "shape": null, "order": ["call:s1", "answer"]}}
```

## Preference pairs (`--format pairs --against RUN_DIR`)

Two runs of one case set, joined on case id. For each case both runs graded
on the same axes, the run with the higher overall score is `chosen` when it
leads by at least `--margin` (default: the policy `evalrun.delta_band`, the
band `evalrun compare` calls stable, so a pair never teaches a difference the
comparison would not report). The order of the two run directories does not
matter.

Refused rather than paired: two runs over different case sets (a pair must
share its prompt), two runs whose `grader` digests differ (their scores are
not on one scale; one side unrecorded is allowed), and a run paired with
itself. Errored cases are skipped.

```json
{"schema": "worldloom.trace-export.pair/v1", "id": "...",
 "prompt": [{"role": "system", ...}, {"role": "user", ...}],
 "chosen": [...], "rejected": [...], "margin": 0.6167,
 "axes": {"plan": 0.75, "trajectory": 0.6, "outcomes": 0.5},
 "metadata": {"case_id": "...", "case_set": "...", "grader": null,
              "chosen": {"agent": "...", "agent_pack": null, "scores": {...}, "passed": true},
              "rejected": {...}, "dimensions": {...}, "split": "train", "shape": null}}
```

The prompt carries the turn rules only: the two runs may have run under
different agent packs, and each side's pack digest is in the metadata.

## Reward records (`--format rewards`)

One record per graded case. `reward` is the overall score and `axes` the
per-axis scores (null for an axis the run did not observe). `verifiable`
holds only what the service observed and a deterministic rule decided:

| Part | Fields |
| --- | --- |
| `plan` | score, node recall and precision, edge recall, missing verifies, extra writes, unattributed calls |
| `trajectory` | score, exact / in-order / any-order match, precision, recall, calls, refused calls, budget and retry storm, safety finding count and laws, designed failures honoured and expected, questions honoured and expected, question findings |
| `outcomes` | the outcome score with the rated answer taken out, the state-diff ratio (share of expected records that ended as expected), structured met and expected, collateral count, grounding |
| `reward` | the overall score recomputed from the three parts above |

`model_rated` holds the answer score and answer error, the one term a
rater (possibly a model) produced. When no answer was rated,
`verifiable.reward` equals `reward` exactly. A trainer that wants a reward
no model influenced reads `verifiable.reward`; a run that executed nothing
(an Eval Studio import) has none.

## The holdout guard

A case set built by the dataset compiler carries a split (`train`,
`validation`, `test`) in its dimensions or on its row. Promotion is decided
on the test split, and a model trained on it has seen the exam, so every
later promotion decision over it is void. The export therefore:

- keeps `train` (and any case that carries no split) by default, and prints
  how many cases of each other split it withheld and why;
- keeps other splits when named with `--split` (repeatable), such as
  `--split validation`;
- refuses `--split test` or `--split holdout` unless `--include-holdout` is
  given, and `--include-holdout` alone exports every split.

A case set without splits has nothing to guard, and every case is eligible.

## Determinism

Records are ordered by case id; `write_records` sorts keys and pins `\n`
newlines. The same run and corpus export to the same bytes.
