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

## The corpus side is not optional

It is tempting to run step 3 against a customer's existing data store and skip
steps 1 and 2. That produces scores, and they mean nothing: the golden answers
come from a fact ledger describing a company that is not in the index. The
whole reason a synthetic corpus is worth generating is that every answer is
derived from a canonical fact, and that property survives only as far as the
documents do.
