---
description: Turn a loose corpus ask into a decided, authored, built, measured, and delivered Worldloom corpus
tags: [worldloom, design, measurement]
---

Design a corpus for the ask in $ARGUMENTS. Unlike the individual steps, you are
not handed a seed and a shape. You decide them, and you show your work. This
command drives the whole loop end to end: decide → author (if authoring) →
build → measure → iterate → write prose → deliver. For the reasoning behind
each judgment call below, read `references/designing.md`. This file is the
short version; that one is the one you check when a call is close.

## 1. Elicit, don't interrogate

A loose ask usually already answers most of what changes the build: industry,
what the corpus is *for* (retrieval eval, agent eval, demo data), which
hardness families matter, scale and how many periods, and whether the prose
needs to read as real or only needs to exist. Read the ask for these before
asking the user anything. Ask only what it genuinely leaves open. A request
that already says "hard RAG eval for a mid-size insurer, three months of
closes, needs to read like real documents" answers everything and should not
be interrogated further. An unstated dimension is a default to pick and state
in the corpus card at the end, not a blocker.

## 2. Decide the engine: archetype, `--inspired-by`, or a pack

```bash
worldloom archetypes
```

Three options, in order of cost. Reach for the cheapest one that actually
answers the ask:

- **A stock archetype** when the industry itself doesn't matter to what's
  being tested (a demo, a generic RAG eval, an agent-eval scaffold).
- **`--inspired-by "a large Australian grocer"`** when a real business is
  named only to communicate scale and category mix, and it resolves to a
  shape one of the archetypes already has. This is a phrase-to-shape lookup,
  never a data fetch: no figure or fact about the real business is used.
- **Author a pack** when the industry is the point: insurance, banking
  beyond `midsize_adi`, or anything where the vocabulary, systems, and
  failure modes need to sound like that industry, not retail's.

### If authoring a pack, author it as the agent

```bash
worldloom pack template <retail|banking> > pack.json
worldloom pack targets <retail|banking>
worldloom pack texts <retail|banking> --json
# edit pack.json
worldloom pack check pack.json --json
# fix findings; repeat until clean
```

`pack targets` names what a lore commitment can actually move. Check it
before writing lore, not after `pack check` reports it inert. `pack texts`
lists every surface string (`episode_text`) you may re-voice; an override may
use any subset of its default's `{placeholders}` and no others, and it
changes the wording, never the underlying causality. **Re-voice `lore`,
`system_brands`, per-role `voices`, and `episode_text` as a consistent set**,
not field by field. An insurer whose ERP is still branded like a retail POS
validates and still doesn't read as an insurer. Iterate `pack check` to a
clean run before building; do not ship a pack with lint findings outstanding.

**Never a real company, brand, or regulator**, in the pack's identity
fields, its lore, or anywhere a narrated document could end up stating it as
fact.

## 3. Build, then measure

```bash
worldloom build --seed <SEED> --pack pack.json --incident --periods <N> --out ./corpus
# or, for a stock shape:
worldloom build --seed <SEED> --archetype <NAME> --incident --periods <N> --out ./corpus
worldloom evaluate ./corpus --retriever both --json
worldloom diversity ./corpus -v
worldloom stats ./corpus --json
worldloom status ./corpus --json
```

**Read the scorecard the right way round.** Retrievers that score well on
`direct_lookup` and `numerical_comparison` while scoring badly on
`temporal_state`, `expected_abstention`, `authority_resolution`, and
`causal_multi_hop` is the corpus *working*; a high score on the hard
families is the bad result. `--retriever both` makes the claim stronger, not
just louder: BM25 and TF-IDF cosine are different ranking families, so a
family low under **both** is hard because of the corpus, not because of one
keyword heuristic's blind spot. A family they *disagree* on (see the
agreement table `both` prints) is itself a finding to report, not a number
to average away. `diversity` reads the other way: a high unique-shape ratio, a
low max family share, short repetition runs are the good result. `stats` has
no "good" direction. It reports document counts, length, vocabulary,
near-duplication, and fact-citation density as facts, never against a
fabricated "real enterprise corpus" number. Don't change anything if the
first two already read this way; that's a finished corpus, not one that needs
another pass.

**Iterate by changing what the corpus generates, never the questions, the
scorer, or a validator.** `references/designing.md` carries the full
weak-family table; the shape of it: a hard family with zero cases usually
means the build ran without `--incident` or with only one period
(`--periods` gives recurrence and across-episode questions; `--comparatives`
alone does not); a hard family that scores too well usually means two
competing passages read too similarly and need re-voicing, or an
`expected_abstention` question got quietly answerable because a pack models
something the abstention list assumed didn't exist; low diversity usually
means the default outline was never overridden, so run `worldloom plan
requests` / `worldloom plan accept` and use `recent_headings` before
narrating. If a weak family doesn't fit any of these, say so in the corpus
card rather than iterating a number into looking better than what's true.

## 4. Prose: pick the bar, and say which

`--narrate` (deterministic, template sentences) is correct for a smoke test
or data nobody reads closely. The moment the ask wants documents that read
like a real controller or service desk wrote them, run the narrate loop
yourself:

```bash
worldloom narrate requests ./corpus -o requests.json
# write responses.json under the rules in references/writing-prose.md
worldloom narrate accept ./corpus --from responses.json --model-id <your model>
```

Expect rejection on the first pass. Fix what's named, resubmit; see
`/worldloom-narrate` and `references/writing-prose.md`.

If the ask is agent-eval data specifically (records of what an employee
*did*, not what a controller wrote about the month), build with `--actors
agent` and drive the decision loop instead of, or alongside, narrate:

```bash
worldloom act requests ./corpus -o decisions.json
# decide, one employee at a time, under what that employee could actually see
worldloom act accept ./corpus --from decisions.json --model-id <your model>
worldloom actors ./corpus
```

## 5. Render, validate, deliver

```bash
worldloom render ./corpus -f xlsx -f docx -f markdown -f jira -f confluence -f servicenow
worldloom validate ./corpus
```

Report the corpus card, not a directory listing:

- **Seed and recipe**: the exact `worldloom build` invocation, including
  `--pack <path>` or `--archetype <name>`, so it doubles as the rebuild
  command.
- **What was authored, and why**: the pack's industry decision and the two
  or three lore commitments the corpus's behaviour rests on, or why a stock
  archetype was enough.
- **Validation**: the check count from `worldloom validate`, pass or fail.
- **Scorecard by family, both retrievers**: `evaluate --retriever both`'s
  per-type breakdown for BM25 and TF-IDF cosine, read the right way round,
  stated plainly, with any family the two disagree on named as a finding.
- **Diversity shape**: `diversity`'s headline numbers and what changed to
  get there.
- **Corpus statistics**: `stats`'s headline numbers, reported as facts about
  the corpus, never against a fabricated reference figure.
- **What was chosen and why**: one line per elicitation answer, so the ask
  visibly got read rather than defaulted past.

## Never do these

- **Never a real company, brand, or regulator**, anywhere in a pack,
  archetype description, or narrated document.
- **Never respond to a rejection or a weak score by loosening a check,
  editing the corpus, or hand-picking what to report.** Rejection is the
  harness working; a weak family is a measurement doing its job. The fix is
  always upstream, in what generates the corpus.
- **Never call a corpus delivered without having run `worldloom evaluate`
  and `worldloom diversity` at least once.**

For the full decision guide (the elicitation table, the pack-authoring
contract in detail, the weak-family iteration table, and the corpus-card
format), read `references/designing.md`.
