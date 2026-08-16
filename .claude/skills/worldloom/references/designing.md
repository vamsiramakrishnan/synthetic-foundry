---
title: Designing a Corpus
description: Turn a loose corpus ask into defensible choices — decide, author, build, measure, iterate, deliver
read-when: The ask is open-ended ("a hard RAG corpus for insurance") rather than a named stage or a seed
tags: [design, elicitation, packs, measurement, corpus-card]
---

# Designing a corpus

Loaded by `/worldloom-design`, when the ask is not "build seed 8128" but
something looser — "I need a hard corpus for testing RAG on insurance
documents," "give me agent-eval data for a bank," "a demo dataset for a
grocer." Every primitive this stage composes already exists; what is missing
without this file is the *judgment* connecting an ask to the right
combination of them. The shape of the work is decide → author (if authoring)
→ build → measure → iterate → deliver.

Worldloom is not one generator with flags — it is a deterministic engine with
five places where you, the agent, are meant to intervene, and a measurement
loop that tells you whether your choices worked:

| Surface | You author | When to use it | Command |
| --- | --- | --- | --- |
| **Pack** | The world itself: company shape, product mix, estate, lore, name | The user's industry is not retail or banking-as-shipped, or they described a specific kind of company | `worldloom build --pack you-wrote-this.json` |
| **Build knobs** | Scale and history: seed, periods, comparatives, incident, archetype | Always — these decide what the corpus can ask | `worldloom build ...` |
| **Plan** | Each document's structure | The batch must not read as one document photocopied; run `worldloom diversity` to see whether it does | `worldloom plan requests/accept` |
| **Narrate** | Every sentence of prose | The corpus should read like people wrote it; the deterministic provider is the fallback, not the goal | `worldloom narrate requests/accept` |
| **Act** | Every decision an employee takes | The user cares about who-knew-what, tool-mediated authority, or agent-behaviour evaluation | `worldloom build --actors agent` + `worldloom act` |

`worldloom status <corpus>` always names the stage and the next command.
Resume from that, never from memory.

## Elicit, don't interrogate

A loose ask already answers most of what changes the build. Read it for these
five before asking the user anything:

| Question | What it decides | Usually inferable from |
| --- | --- | --- |
| What industry / company shape? | stock archetype vs. `--inspired-by` vs. authoring a pack | the domain named in the ask ("insurance", "a bank") |
| What is the corpus *for*? | retrieval eval → lean on `worldloom evaluate`; agent eval → `--actors agent` and `worldloom act`; demo data → `--narrate`, skip measurement rigor | "testing RAG", "agent", "demo", "show a customer" |
| Which hardness families matter? | whether `--incident` is worth forcing, whether `--periods > 1` is worth the cost | "hard", "adversarial", "temporal", "trap" language vs. "just needs data" |
| What scale, and over how many periods? | `--archetype`/`--pack` size, `--periods`, `--comparatives` | headcount or "over time" / "recurring" language, or absence of either (default to something modest) |
| What prose bar? | deterministic (`--narrate`) vs. an agent-written narrate loop | "realistic", "reads like a real memo" vs. "just needs facts", or unstated (default to agent-written — it's the harder bar and the one worth defending) |

Ask only what the text genuinely leaves open — a request that already says
"hard RAG eval corpus for a mid-size insurer, three months of closes, needs
to read like real documents" answers all five and should not be interrogated
further. Silence on a dimension is a default, not a blocker: pick the
reasonable one, say what you picked and why in the corpus card, and move.

## Decide the engine: archetype, `--inspired-by`, or a pack

Three ways to get a company shape, in order of cost:

1. **A stock archetype** (`worldloom archetypes`). Reach for this whenever
   the industry doesn't matter to what's being tested — a demo, a RAG eval
   that only needs *an* enterprise's documents, an agent-eval scaffold. Free,
   and already proven coherent.
2. **`--inspired-by "a large Australian grocer"`.** A shape lookup, not a new
   engine — it resolves to one of the same archetypes. Reach for it when the
   ask names a real business only to communicate scale and category mix, not
   when it names an *industry* the archetypes don't model at all. No figure
   or fact about the real business is used either way — this is a phrase
   resolving to a shape, never a data fetch.
3. **Author a pack** (next section). Reach for this when the industry itself
   is the point — anything where the vocabulary, the systems, and the failure
   modes need to sound like that industry rather than retail's or banking's.
   Real authoring work; do not reach for it when a stock archetype would
   answer the ask just as well.

Orthogonal to all three, the pack's (or archetype's) `base` decides the
episode physics: `retail` gives a month-end close with an optional
data-quality incident; `banking` gives a quarterly filing challenged before
lodgement and corrected by restatement. Choose `banking` when the user needs
contested authority or immutable-record semantics; `retail` for operational
incident texture, multi-period history, and org change.

Then decide history. One period cannot pose recurrence, supersession, or
who-signed-this-before-the-handover questions. `--periods 3` gives recurring
incidents and superseded calendars; `--comparatives 11` gives a trend. The
Python API adds `Hire`/`Departure`/`Reorganisation` between closes when the
user needs authorship to change hands mid-corpus.

## Authoring a pack, as the agent

You are the author here, the same way you are the author of prose in
`narrate`. The loop:

```bash
worldloom pack template retail > pack.json    # or: banking
worldloom pack targets retail                 # what you may move, and what each target changes
worldloom pack texts retail --json            # every surface string you may re-voice, with its default
# edit pack.json
worldloom pack check pack.json --json
# fix findings; repeat until clean
```

Start from the template or the shipped references in `examples/packs/` (an
insurer on the retail engine, a mutual bank on the banking one). Then:

- **Shape**: units with income shares that sum to 1; categories per unit with
  shares that sum to 1 and margins that are the *industry's* (the roll-up
  discipline will hold whatever you write, so what you write is the realism).
  Zero-revenue-weight site formats are for locations that hold work but book
  nothing — warehouses, operations centres.
- **Lore is the lever.** `pack targets` is the contract: a lore `constrains`
  entry aimed at one of its listed targets changes generation — incident
  likelihood, artifact density, event tagging, persona behaviour
  (`<role>/<trait>`). Aimed anywhere else it is carried and citable but
  changes nothing; check the targets before writing lore, not after
  `pack check` reports a commitment inert. Write lore as *causes with dates*:
  "the 2023 migration carried mappings over by hand" is a decision the
  corpus's own timeline will witness and its incident will cite.
- **Texture: brands, voices, and the episode's own narration.**
  `system_brands` renames the engine's systems for your industry (slots from
  `worldloom pack targets` — the insurer example turns the merchandising
  master into "Policy and Claims Register"); `voices` re-voices any role's
  prose (`{"cfo": {"voice": ..., "phrases": [...]}}`, role keys from the same
  command); and `episode_text` re-voices the episode's surface — every event
  sentence and prose fact, keyed by `worldloom pack texts`. An override may
  use any subset of its default's `{placeholders}` and nothing else, and it
  re-voices the sentence, never the underlying causality — what fails, when,
  what supersedes what, what gets filed stays the engine's.
  `evaluation_text` re-voices the benchmark the same way — every question
  and authored answer, keyed in the same `worldloom pack texts` output — so
  a re-voiced episode's own evaluation set stops asking about "merchandise
  category" in a world that no longer has one.
- **Locale: name pools and headquarters/regions.** A pack-less corpus is
  Australian by default — the engine's own given/family name pools, its
  headquarters draw, and its site-region abbreviations (NSW, VIC, ...) all
  come from `generators/names.py`/`generators/hierarchy.py`. `name_pools`
  (`{"given": [...], "family": [...]}`) replaces either or both halves of the
  person-name pools; `pack check` flags a pool too small for the archetype's
  headcount before a build silently recycles a name onto two people.
  `headquarters` is a single string (the company has one, not a pool of
  candidates); `regions` replaces the labels the site estate cycles through.
  Leave any of the three unset and that piece stays the engine's default —
  setting only `name_pools` and leaving `headquarters` empty is legal and
  common for a pack whose story does not hinge on where the head office sits.
- **Re-voice in consistent pairs, not isolated fields.** A pack's `lore`,
  `system_brands`, `voices`, and `episode_text` all have to agree with each
  other and with the `company_name`/`industry` you set at the top — an
  insurer whose ERP is still branded like a retail POS validates and still
  doesn't read as an insurer. The same discipline covers locale: a
  `headquarters` in one country reads oddly beside `name_pools` built for
  another. Set the identity fields first, then work outward through brands →
  voices → episode text. Override `episode_text` in story pairs: a fact and
  the event that recorded it tell one story (the insurer example re-voices
  the hypothesis fact and both its events together).
- **Fiction only.** Never a real company, brand, or regulator — in the
  identity fields, the lore, or anywhere a narrated document could end up
  stating it as fact. Shape and scale may resemble an industry; no figure,
  person, or fact may resemble a company.

`pack check --json` is the loop's compiler: keep editing and re-checking
until findings are empty; do not build from a pack with findings outstanding.
The pack embeds in the corpus recipe, so the corpus rebuilds without the
file.

## Build, then measure — never assert hardness

```bash
worldloom build --seed 8128 --pack pack.json --incident --out ./corpus
worldloom evaluate ./corpus --retriever both --json   # two ranking families, side by side
worldloom diversity ./corpus -v                       # structural sameness fingerprints
worldloom stats ./corpus --json                       # what's actually in it
```

**Read the scorecard the right way round.** Retrievers that score well on
`direct_lookup` and `numerical_comparison` while scoring badly on
`temporal_state`, `expected_abstention`, `authority_resolution`, and
`causal_multi_hop` is the corpus *working* — a high score on the hard
families means the corpus isn't posing the question it thinks it's posing.
`--retriever both` is the stronger form of that claim: BM25 and TF-IDF cosine
are different ranking families (probabilistic versus vector-space — see
`references/evaluating.md`), so a family low under **both** is hard because of
the corpus, not because of which keyword heuristic happened to be asked. Where
the two *disagree* on a family (a third or more of its cases split — see
`compare()` in `evaluate/score.py`), that disagreement is itself a finding
about the corpus, worth a line in the corpus card, not something to average
into a single number. `diversity` reads the other way: high unique-shape
ratio, low max family share, short repetition runs are the good result there.
`stats` reads neither direction — it has no "good" result, only an honest one:
document counts, length distributions, vocabulary, near-duplicate rate, and
the citation graph, with no fabricated "real enterprise corpus" figure to
compare against (report, don't grade; `--against` diffs two real corpora when
there is a second one worth comparing to). Read all three before deciding
anything needs to change; a corpus that already reads this way is done, not in
need of another pass.

**Iterate by changing what the corpus generates — never the questions, the
scorer, or a validator.** Every row below is a generation-side lever, not an
edit to the evaluation code:

| Symptom | What to change |
| --- | --- |
| the incident families (`causal_multi_hop`, `temporal_state`, `authority_resolution`, `citation_required`) show zero cases | build with `--incident` — these families come from the incident chain |
| `numerical_comparison` has few or no cases | a larger archetype, or a pack with more units and categories to compare |
| recurrence and superseded-calendar questions never appear | `--periods` above one; `--comparatives` alone backfills a trend, it does not give recurrence |
| `temporal_state` too easy | more periods (supersession), the banking engine (as-filed vs restated), or actors (observation lags) |
| `authority_resolution` too easy | the banking engine — its two lodgements tie at system-of-record, so rank cannot resolve them; or re-voice the competing `episode_text` pair so the family is hard because of *when* and *who*, not because the prose undersells the wrong answer |
| `cross_artifact` too easy | fan-out is your friend: minutes and threads split pairings across documents |
| `expected_abstention` scores *well* | a generator now models something the abstention list assumed didn't exist — a real finding to flag, not something a build flag fixes |
| `diversity` reports few distinct shapes | structure came from the default outline; run the plan handshake and propose different structures per document |
| everything too easy | the corpus is too small for the questions; add periods and an incident |

If a family is weak and none of these apply, that is a real finding about the
corpus — say so in the corpus card rather than iterating a number into
looking better than what's true.

## Prose: pick the bar deliberately

`--narrate` fills every section with the built-in deterministic provider — no
model, template sentences, one per fact, always the same shape. Correct for a
smoke test or data nobody reads closely. The moment the ask includes anything
like "realistic" or "reads like a real memo", that bar is wrong — run the
narrate loop yourself (rejection on the first pass is the harness working;
fix the named violation and resubmit — see `references/writing-prose.md`).

## Intervening mid-generation

Everything pauses and resumes. `--actors agent` exports a corpus that waits;
`worldloom act requests` hands you one employee's decision with only what
that employee could see — decide from the decision document alone, never by
reading the corpus's fact files, or every information-asymmetry property
quietly dies. `narrate accept` commits nothing unless everything passes, so
you can iterate freely. A corpus is never in a half-state you must remember:
`worldloom status` reconstructs where you are.

## Deliver: the corpus card

Report what was measured, not what was intended — in this shape, not a
directory listing:

- **Seed and recipe** — the exact `worldloom build` invocation, including
  `--pack <path>` or `--archetype <name>`, so it is the literal rebuild
  command.
- **What was authored, and why** — the pack's industry decision and its two
  or three load-bearing lore commitments, or why a stock archetype was
  enough.
- **Validation** — the check count from `worldloom validate`, pass or fail.
- **Scorecard by family, both retrievers** — `evaluate --retriever both`'s
  per-type breakdown for BM25 and TF-IDF cosine, with the right-way-round
  reading stated plainly (which low scores are good news) and the agreement
  reading named for any family the two retrievers split on.
- **Diversity shape** — `diversity`'s headline numbers, plus whatever changed
  to get there.
- **Corpus statistics** — `stats`'s headline numbers (document count and
  length, vocabulary, near-duplicate rate, fact-citation density), reported as
  facts about the corpus, not graded against anything.
- **What was chosen and why** — the answers to the elicitation table, one
  line each, so a reader can see the ask was actually read rather than
  defaulted past.

A corpus whose hardness you cannot show is a corpus you have not finished.

## Never do these

- **Never a real company, brand, or regulator**, anywhere a pack, archetype
  description, or narrated document could carry one.
- **Never respond to a rejection or a weak score by loosening a check,
  editing the corpus, or hand-picking what to report.** Rejection and a weak
  family are the harness and the measurement working; the fix is always
  upstream, in what generates the corpus.
- **Never call a corpus delivered without having run `worldloom evaluate`
  and `worldloom diversity` at least once** — a corpus that validates but was
  never measured is coherent and unproven, not designed.
