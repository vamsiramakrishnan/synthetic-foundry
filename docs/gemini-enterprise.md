# Running a corpus against Gemini Enterprise

[Gemini Enterprise Eval Studio][studio] is a client-side Angular application
that calls a Gemini Enterprise instance and grades what comes back. This guide
is the loop that puts a Worldloom corpus underneath it.

[studio]: https://github.com/GoogleCloudPlatform/gemini-enterprise-eval-studio

## What each side owns

Eval Studio owns **reaching the product**, which is the part worth not
rebuilding: Workforce Identity Federation, Google Identity, OIDC and SAML,
token refresh, the `streamAssist` call, and latency telemetry (TTFT, TTFA,
TTLT) measured against a real endpoint. Nothing here replaces any of it.

Worldloom owns the two ends Eval Studio leaves open.

| | Eval Studio | Worldloom |
|---|---|---|
| Fill the index the assistant searches | selects existing data stores; no ingestion at all | `gemini-enterprise datastore` |
| Ask questions with checkable answers | reads a `query,golden` CSV you supply | `gemini-enterprise cases` |
| Call the product, time it | yes | not its job |
| Grade the final answer | one LLM judge, one instruction per run | rubric per grading shape |
| Grade the trace | **no**, see below | `connector_trace`, with no wire to reach it |

## The loop

```bash
# 1. A corpus, rendered, with a drive laid out over it.
worldloom build --seed 8128 --incident --out ./corpus
worldloom render ./corpus -f markdown
worldloom workspace ./corpus -o ./drive --noise lived_in

# 2. The drive into Cloud Storage, then into a data store.
gcloud storage cp -r ./drive/* gs://your-bucket/drive/
worldloom gemini-enterprise datastore ./corpus ./drive \
  --uri-prefix gs://your-bucket/drive -o ./documents.jsonl
# then `documents:import` that file into the data store Eval Studio will search

# 3. The evaluation set as uploadable shards.
worldloom gemini-enterprise cases ./corpus -o ./shards

# 4. Run each shard in Eval Studio, then read the results back.
worldloom gemini-enterprise score ./corpus ./results/*.csv
```

Step 3 writes one CSV per `EvaluationType` plus a `manifest.json`. **Paste that
shard's `auto_rater_instruction` into Eval Studio's auto-rater field before
uploading that shard.** This is the step it is tempting to skip, and skipping it
is what makes the numbers wrong rather than merely coarse. See below.

## Three things that go wrong quietly

**One rubric across the whole set grades abstention backwards.** Eval Studio's
default instruction asks for semantic similarity between the fetched answer and
the golden one. An `expected_abstention` case has a golden answer that says the
corpus holds nothing, and the behaviour under test is a refusal. Under
similarity scoring, a model that invents a confident, fluent, wrong answer is
scored against that refusal and earns whatever the fluency earns, while saying
"I cannot answer that" is scored as though it were a failed attempt. Same shape
of error for `temporal_state` (a superseded reading reads as similar and is
wrong) and `citation_required` (an uncited answer reads as similar and is the
failure). `worldloom.gemini_enterprise.RUBRICS` is one instruction per shape.

**An upload past a hundred rows is truncated, not rejected.** Eval Studio's CSV
reader is `results.data.slice(0, 100)`. Row 101 onward is not sent, and the run
reports a clean pass over a set it never saw. `cases` shards at that cap by
default; `score` reports the cases with no result row, which is where a
truncation shows up if one happens anyway.

**A grader failure looks exactly like a wrong answer.** Eval Studio returns
`score: 0` both when the model was wrong and when its own auto-rater call
failed, separated only by a populated `scoreError`. `score` counts those and
excludes them from every mean rather than averaging a rate limit in as poor
model performance.

## What this cannot tell you

**Nothing about the trace.** Eval Studio's stream parser keeps
`answer.replies[].groundedContent.content.text` and discards everything else,
so nothing about how an answer was reached reaches a grader. Every score this
loop produces is a judgement about a final answer, and a corpus whose value is
partly in *how* an answer was reached is only partly exercised by it.

That is worth separating into the half that could be fixed and the half that
could not, because "capture the trace" sounds like one job.

The API carries more than Eval Studio reads. `StreamAssistResponse` also has
`invocationTools` (the tool names invoked), `invokedSkills`, and
`textGroundingMetadata`: per-segment byte offsets, `groundingScore`, and
references carrying `documentMetadata.document` and `.uri`. That last one is
the document id `datastore` mints, so a citation could be checked against the
corpus exactly rather than by reading the prose for a source name.

The API carries tool *arguments* and tool *results* nowhere. Checked across all
973 schemas of the v1 discovery document (revision 20260831): no schema has an
arguments-like property, and `invokedSkills` entries are `{name, displayName}`
only. So an assertion about what a tool was called with is not reachable
through this surface at any amount of effort.

Two consequences worth stating plainly. A `citation_required` case can only be
graded on whether the response *text* names its source, not on whether a
citation was attached. And a permission failure is visible only if the wrong
document's content surfaces in the answer. The ACLs go into the store and are
enforced there, but an assistant that reads a document it should not and does
not quote it looks identical to one that never opened it.

Closing that gap means capturing the parts of the `streamAssist` stream Eval
Studio drops, which is a change to Eval Studio rather than to this engine.

## Comparing with a local run

`worldloom evalrun import-studio ./cases eval_results.csv -o ./runs/studio`
brings a results CSV in as a run on the answer axis only, joined on query
text, so it can sit next to a local three-axis run in `worldloom evalrun
compare`. The summary reports plan and trajectory as unobserved rather than
as zeros. See [eval execution](eval-execution.md).

## Measuring the grader against Eval Studio

A local run is only worth comparing with an Eval Studio run if the two
graders agree on what a good answer is. `worldloom evalrun agreement`
measures that, and nothing else:

```bash
worldloom evalrun agreement ./cases eval_results.csv -o ./runs/agreement
worldloom evalrun agreement ./cases eval_results.csv --rater "exec:python3 judge.py" --rater-timeout 60 --json
```

**What is comparable.** Only the answer axis. Eval Studio sees a query, the
answer it fetched and the golden, and never a tool call, so it has no plan
or trajectory grade to agree with. Even on the answer axis, `evalrun compare`
between an imported Studio run and a local run compares the local blended
outcome score (state diff, grounding and answer together) with Studio's
answer score, which are different quantities, and two different answers rated
by two different graders confound the agent with the grader. The agreement
command removes both confounds: it takes the `fetched` text of every Studio
row and rates that same text with the local rater (`--rater grounded`, the
default, or `exec:<command>` for a model judge over the exec seam). Whatever
differs is the graders.

**What is left out, and counted.** A Studio row with a `scoreError` or an
`Error:` answer, a row the local rater could not rate, a case with no
answer contract, and a Studio row whose query matches no case
(`unknown_cases`, counted at import rather than dropped) are excluded and
counted under `excluded`. Cases whose shape the grounded rater declines by
design (causal chains, authority resolution, citation required) have a
Studio score and no local one; they are reported under `abstained` with
Studio's mean, so the reader sees how much of the set the local grader cannot
vouch for. Only the grounded rater abstains: a model or exec judge that
returns no score on such a shape failed, and is counted as a local error, so
those cases join the comparison when a judge rates them. A case Studio graded
twice (two rows with one query) is refused with its id rather than counted
twice; keep one row per query.

**How to read it.** Every statistic is over the rated pairs, overall and per
shape:

- *MAE* is the mean absolute difference on the 0 to 1 scale: how far apart
  the two numbers are on a typical case.
- *Pearson* and *Spearman* say whether the graders order answers the same
  way; Spearman uses average ranks, because rater scores tie constantly.
- *Within band* is the share of cases whose two scores differ by no more
  than `evalrun.delta_band`, the band inside which `compare` calls a change
  stable.
- *Kappa* is Cohen's kappa of the pass/fail call at `evalrun.answer_pass_score`
  (0.8 unless a pack moves it), with the confusion counts beside it. It
  corrects the raw agreement rate for the agreement two graders would reach
  by chance, which matters when most answers pass or most fail.
- `worst` lists the cases the two disagree on most: read those before
  trusting any summary number.

A statistic that is undefined on the data is `null` with its reason under
`undefined` (fewer than two pairs, one side giving every case the same score,
both sides putting every case in one class), never a number that looks like
a measurement.

**The verdict and its thresholds.** Three policy values in
`policy:default` decide `agrees`, `disagrees` or `insufficient`:

| Policy | Default | Why |
|---|---|---|
| `evalrun.agreement.min_cases` | 30 | Below about thirty pairs the uncertainty on kappa is wider than the gap between "moderate" and "substantial", so no verdict is drawn. A single Eval Studio shard holds up to a hundred rows. |
| `evalrun.agreement.min_kappa` | 0.6 | The conventional floor for substantial agreement on a binary call (Landis and Koch's scale). Below it the local pass rate and Studio's are not measuring the same thing. |
| `evalrun.agreement.max_mae` | 0.1 | Equal to `evalrun.delta_band`. If the graders differ by more than the band on a typical case, grader noise alone can turn a stable case into an improvement or a regression. |

Both bars must hold for `agrees`; missing either is `disagrees`; too few
pairs, or a kappa that is undefined, is `insufficient`. A pack may move any
of them, and the report records the values in force.

**The grader is frozen by digest.** `evalrun.grader.grader_identity(rater)`
names what graded a run: the rater and its kind (for an exec judge, its
command with anything credential-shaped redacted: secret-named assignments
and flags, header values such as `Authorization: Bearer ...` and
`x-api-key: ...`, secret query parameters, and values with a known token
prefix such as `sk-`, `ghp_`, `AKIA` or `xox`; for a model judge, the model
`model_rater(complete, model=...)` names, which is required so two judge
models are two graders), a digest of the `rater.*`
judge texts in force, a digest of the per-shape rubrics, the grading policy
values in force (`evalrun.answer_pass_score`, `evalrun.delta_band`), and a
grading code version, all under one `digest`. The agreement report carries it
under `local`; a run that carries it in `run.json` (`grader`) is compared by
`evalrun compare` only against runs graded under the same digest, and two
runs graded under different digests get `grader_mismatch: true` and the
verdict `incomparable` on every case, with the deltas still reported. A loop
that improves an agent pins the digest once and calls
`evalrun.grader.check_frozen(pinned, rater)` (or wraps a round in `frozen`)
before each round, so it can never improve by moving its own measuring stick.
When the Studio run's auto-rater instruction is known, pass it with
`--studio-instruction` so the report records which instruction the other
side used.

## The corpus side is not optional

It is tempting to run step 3 against a customer's existing data store and skip
steps 1 and 2. That produces scores, and they mean nothing: the golden answers
come from a fact ledger describing a company that is not in the index. The
whole reason a synthetic corpus is worth generating is that every answer is
derived from a canonical fact, and that property survives only as far as the
documents do.
