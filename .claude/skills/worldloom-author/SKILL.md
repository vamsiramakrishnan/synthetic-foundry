---
name: worldloom-author
description: Author a whole Worldloom company from the top, covering what it is, its lines of business, its processes, and its paperwork, and run it into a narrated, validated corpus by driving one loop at every layer: propose, be refused with findings, revise, until accepted. Use when the ask is a complete authored world rather than one layer of it, when unsure which layer skill a change belongs to, or when asked how the authoring layers fit together.
tags: [worldloom, authoring, cascade, refusal-loop, routing]
---

# Authoring a world, top to bottom

Every authorable layer in this repository is the same machine, and this skill
is the map of the stack that machine builds. The loop is stated once in
`src/worldloom/cascade.py` and runs everywhere:

```
seed → Session → Brief (context + constraints) → propose → lint →
refuse-with-findings → revise → accept → resolve → install → replay
```

**Every stage is propose → refuse → revise.** A refusal is data, not failure.
It carries every finding at once, each naming what you proposed, the rule it
broke, and what to do instead. Nothing is committed on a refusal, so revision
starts from the same state your proposal was judged against. Fix those
specific things, resubmit, loop until accepted. Never work around a refusal by
editing the corpus, loosening a check, or answering a different question.
`narrate accept` rejecting your prose is this same loop over sentences.

## Route to the layer: load the skill, do not duplicate it

| # | Stage | What you author | Skill |
| --- | --- | --- | --- |
| 1 | **Company** | What the business *is*: industry, geo, facets, locale, organisation shape, as one refusable document | `/worldloom-company` |
| 2 | **Physics** | The numbers behind the company, by Socratic drill-down, refused by arc consistency | `/worldloom-probe` |
| 3 | **LOBs** | Roles, responsibility edges (the cohesion primitive), slot bindings | `/worldloom-lob` |
| 4 | **Processes** | Steps, the fact kinds they mint, ordered role slots, resolving to an `EpisodeSpec` | `/worldloom-process` |
| 5 | **Doctypes** | Paperwork no archetype ships, linted against what the compiler assumes | `/worldloom-doctypes` |
| 6 | **Run** | Install the specs, build, run periods; arrangements the CLI lacks are Python | `/worldloom-sdk` |
| 7 | **Narrate** | The prose, source-blind, refused when it contradicts the facts | `/worldloom-narrate` |
| 8 | **Validate / evaluate** | Render, check every document agrees, score | `/worldloom-render`, `/worldloom-evaluate` |

Before any of this: an industry the engines do not model at all (a hospital, an
airline) is `/worldloom-vertical`, and a loose ask (no seed, no shape chosen)
is `/worldloom-design`.

Order matters the way it does inside one cascade: a later stage's brief carries
what earlier stages accepted. Author the LOB before its process.
Participation is the *join* of responsibility edges against the kinds the
process's steps mint, never a table.

Check where a corpus stands with `worldloom status ./corpus`; before any
commit, `pytest -q` and `worldloom validate retail-close` must pass.

## Read next

- `references/constraints.md`: the four harness constraints no layer may
  relax; load before authoring any stage.
- `references/loop.md`: driving a cascade from Python, covering the verbs,
  Session semantics, what a refusal costs, and resume.
