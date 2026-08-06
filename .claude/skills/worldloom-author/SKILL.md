---
name: worldloom-author
description: Author a whole Worldloom company from the top — what it is, its lines of business, its processes, its paperwork — and run it into a narrated, validated corpus, by driving one loop at every layer: propose, be refused with findings, revise, until accepted. Use when the ask is a complete authored world rather than one layer of it, when unsure which layer skill a change belongs to, or when asked how the authoring layers fit together.
---

# Authoring a world, top to bottom

Every authorable layer in this repository is the same machine, and this skill
is the map of the stack that machine builds. The loop — stated once in
`src/worldloom/cascade.py`, run everywhere:

```
seed → Session → Brief (context + constraints) → propose → lint →
refuse-with-findings → revise → accept → resolve → install → replay
```

**The atomic pattern: every stage is propose → refuse → revise.** A refusal is
data, not failure — it carries every finding at once, each naming what you
proposed, the rule it broke, and what to do instead. Nothing is committed on a
refusal, so revision starts from exactly the state your proposal was judged
against. Read the findings, fix those specific things, resubmit. Loop until
accepted. Do not work around a refusal by editing the corpus, loosening a
check, or answering a different question — the refusal is the harness working,
and `narrate accept` rejecting your prose is this same loop over sentences.

## The stages, top down

Each stage has its own skill; this one only says what each layer decides and
what it hands the next. Do not duplicate their content — load them.

| # | Stage | What you author | Skill |
| --- | --- | --- | --- |
| 1 | **Company** | What the business *is*: industry, geo, facets, locale, organisation shape — one refusable document | `/worldloom-company` |
| 2 | **Physics** | The numbers behind the company, derived by Socratic drill-down (organisation → reporting → roles → objectives → measures), refused by arc consistency | `/worldloom-probe` |
| 3 | **LOBs** | Lines of business: roles, responsibility edges (the cohesion primitive), slot bindings into processes | `/worldloom-lob` |
| 4 | **Processes** | The recurring work: steps, the fact kinds they mint, ordered role slots — resolving to an `EpisodeSpec` | `/worldloom-process` |
| 5 | **Doctypes** | The paperwork no archetype ships: standing, lag, outline, filing — linted against what the compiler assumes | `/worldloom-doctypes` |
| 6 | **Run** | Episodes over periods — install the specs, build the world, run each period; arrangements the CLI lacks are Python | `/worldloom-sdk` |
| 7 | **Narrate** | The prose, source-blind: everything you may use is in `requests.json`, and `narrate accept` refuses what contradicts the facts | `/worldloom-narrate` |
| 8 | **Validate / evaluate** | Render, check every document agrees, score against the baseline | `/worldloom-render`, `/worldloom-evaluate` |

Order matters the way it does inside one cascade: a later stage's brief
carries what earlier stages accepted. A process's briefs carry the owning
LOB's roles and responsibilities, so author the LOB first; participation is
the *join* of responsibility edges against the kinds the process's steps mint,
never a table. Where the ask is loose — no seed, no shape chosen —
`/worldloom-design` decides what to build before any of this authors it.

## The constraints every stage must respect

These are the harness's, not any one layer's, and no layer may relax them:

- **Registry-known kinds, or declared invariants.** A step may only mint a
  fact kind that `worldloom.factkinds.names()` knows — or one you declare
  with its own invariants, so the validator can police it. A kind nothing
  validates never enters a spec; a responsibility edge naming a kind nothing
  generates is refused as an edge that can never fire.
- **The doctypes lint is the boundary for paperwork.** An authored type that
  cites kinds nothing produces *compiles* — into a document that is carried,
  cited, and says nothing — so `worldloom.doctypes.lint` findings are read
  and fixed, not shipped.
- **The byte-replay promise.** Only the *resolved* artifact ever replays —
  the spec, the pack, the recipe, the ledger. The conversation (sessions,
  briefs, refused answers) is working state and is never recorded or
  replayed. Nothing you author may introduce a clock, `random`, a UUID, or
  set-iteration order; a rebuilt corpus must match byte-for-byte, and CI
  checks it does.
- **Source-blindness at narration.** The brief is the boundary at every
  stage: if a fact, role, or bound is not in the brief, the answer may not
  use it. Narration is the strictest case — three writers who never opened
  `src/` narrated 115 sections; that is the contract, not a stunt.

## Working the loop

```python
from worldloom import lob, process   # every cascade has the same verbs

session = lob.open(seed)             # or process.open(seed, facets=...)
brief = lob.next_stage(session)      # stage, asks, context — answer from this alone
try:
    session = lob.accept(session, answer)
except ValueError as refusal:        # findings: what, which rule, what to do
    ...                              # revise that specific thing; session unchanged
spec = lob.resolve(session)          # only this rides the pack/recipe
```

A `Session` is a frozen value of accepted stages: refusals cost nothing, and a
session resumes by replaying its accepted answers through `open`/`accept`.
Check where a corpus stands with `worldloom status ./corpus`; before any
commit, `pytest -q` and `worldloom validate retail-close` must pass.
