# Designing a corpus

Read this before building anything for a user who asked for "a corpus" rather
than a specific command. Worldloom is not one generator with flags — it is a
deterministic engine with five places where you, the agent, are meant to
intervene, and a measurement loop that tells you whether your choices worked.
Your job is to pick the interventions the user's need actually requires and
skip the rest.

## The five intervention surfaces

| Surface | You author | When to use it | Command |
| --- | --- | --- | --- |
| **Pack** | The world itself: company shape, product mix, estate, lore, name | The user's industry is not retail or banking-as-shipped, or they described a specific kind of company | `worldloom build --pack you-wrote-this.json` |
| **Build knobs** | Scale and history: seed, periods, comparatives, incident, archetype | Always — these decide what the corpus can ask | `worldloom build ...` |
| **Plan** | Each document's structure | The batch must not read as one document photocopied; run `worldloom diversity` to see whether it does | `worldloom plan requests/accept` |
| **Narrate** | Every sentence of prose | The corpus should read like people wrote it; the deterministic provider is the fallback, not the goal | `worldloom narrate requests/accept` |
| **Act** | Every decision an employee takes | The user cares about who-knew-what, tool-mediated authority, or agent-behaviour evaluation | `worldloom build --actors agent` + `worldloom act` |

`worldloom status <corpus>` always names the stage and the next command.
Resume from that, never from memory.

## From a user's ask to a build

**1. Industry.** Retail-shaped or banking-shaped businesses use the stock
archetypes (`worldloom archetypes`). Anything else — an insurer, a logistics
firm, a mutual — is a pack you author (next section). The `base` you choose
decides the episode physics: `retail` gives a month-end close with an
optional data-quality incident; `banking` gives a quarterly filing challenged
before lodgement and corrected by restatement. Choose `banking` when the user
needs contested authority or immutable-record semantics; `retail` for
operational incident texture, multi-period history, and org change.

**2. History.** One period cannot pose recurrence, supersession, or
who-signed-this-before-the-handover questions. `--periods 3` gives recurring
incidents and superseded calendars; `--comparatives 11` gives a trend. The
Python API adds `Hire`/`Departure`/`Reorganisation` between closes when the
user needs authorship to change hands mid-corpus.

**3. Hardness.** Decide which evaluation families matter to the user, then
pick the structures that generate them — see the loop below. Do not promise
hardness you have not measured.

**4. Prose.** If the corpus will be read by humans or judged on realism,
write the prose yourself through `narrate` (rejection is the harness working;
fix the named violation and resubmit). If it only needs coherence for
pipeline testing, `--narrate` (deterministic) is honest and free.

## Authoring a pack

Start from `worldloom pack template <engine>` or the shipped references in
`examples/packs/` (an insurer on the retail engine, a mutual bank on the
banking one). Then:

- **Shape**: units with income shares that sum to 1; categories per unit with
  shares that sum to 1 and margins that are the *industry's* (the roll-up
  discipline will hold whatever you write, so what you write is the realism).
  Zero-revenue-weight site formats are for locations that hold work but book
  nothing — warehouses, operations centres.
- **Lore is the lever.** The engine consults specific targets —
  `worldloom pack targets <engine>` lists them with what each changes.
  A commitment aimed at a consulted target changes generation: incident
  likelihood, artifact density, event tagging, persona behaviour
  (`<role>/<trait>`). Aimed anywhere else it is carried and citable but
  changes nothing — `worldloom pack check` names every inert commitment.
  Write lore as *causes with dates*: "the 2023 migration carried mappings
  over by hand" is a decision the corpus's own timeline will witness and its
  incident will cite.
- **Texture: brands, voices, and the episode's own narration.**
  `system_brands` renames the engine's systems for your industry (slots from
  `worldloom pack targets` — the insurer example turns the merchandising
  master into "Policy and Claims Register"); `voices` re-voices any role's
  prose (`{"cfo": {"voice": ..., "phrases": [...]}}`, role keys from the
  same command); and `episode_text` re-voices the episode's surface — every
  event sentence and prose fact, keyed by `worldloom pack texts <engine>`
  (`--json` for the full key → default table). An override may use any
  subset of its default's `{placeholders}` and nothing else. Override in
  consistent *pairs*: a fact and the event that recorded it tell one story
  (the insurer example re-voices the hypothesis fact and both its events
  together). Know the boundary: the narration is yours, but the *causality*
  — what fails, when, what supersedes what, what gets filed — is the
  engine's; a template cannot change what happens, only how the record
  says it.
- **Fiction only.** Name the company anything you invent; never a real
  organisation, regulator, or standard. Shape and scale may resemble an
  industry; no figure, person, or fact may resemble a company.
- **Check, then build**: `worldloom pack check pack.json --json`, fix
  findings, `worldloom build --pack pack.json ...`. The pack embeds in the
  corpus recipe, so the corpus rebuilds without the file.

## The measurement loop — never assert hardness, measure it

```
worldloom build ... --narrate -f markdown --out ./corpus
worldloom evaluate ./corpus          # baseline retriever scorecard
worldloom diversity ./corpus         # structural sameness fingerprints
```

Read the scorecard the right way round: **a low score on the hard families is
the good result.** `direct_lookup` at ceiling proves answerability;
`authority_resolution` and `temporal_state` well below it prove hardness. If
a hard family scores high, the corpus is not testing anything there — change
what the corpus *generates*, never the questions, and rebuild:

| Weak family | What to change |
| --- | --- |
| `temporal_state` too easy | More periods (supersession), or the banking engine (as-filed vs restated), or actors (observation lags) |
| `authority_resolution` too easy | The banking engine — its two lodgements tie at system-of-record, so rank cannot resolve them |
| `cross_artifact` too easy | Fan-out is your friend: minutes and threads split pairings across documents |
| Everything too easy | The corpus is too small for the questions; add periods and an incident |
| `expected_abstention` passing | The threshold calibrates per corpus; if the baseline abstains, the questions overlap the corpus too little — usually fine |

If `diversity` reports few distinct shapes, run the plan handshake and
propose different structures per document — that is what it is for.

## Intervening mid-generation

Everything pauses and resumes. `--actors agent` exports a corpus that waits;
`worldloom act requests` hands you one employee's decision with only what
that employee could see — decide from the decision document alone, never by
reading the corpus's fact files, or every information-asymmetry property
quietly dies. `narrate accept` commits nothing unless everything passes, so
you can iterate freely. A corpus is never in a half-state you must remember:
`worldloom status` reconstructs where you are.

## What to tell the user

Report what was measured, not what was intended: the scorecard by family,
the diversity shape count, the validation check count, and the seed +
pack/recipe that regenerate it all byte-for-byte. A corpus whose hardness
you cannot show is a corpus you have not finished.
