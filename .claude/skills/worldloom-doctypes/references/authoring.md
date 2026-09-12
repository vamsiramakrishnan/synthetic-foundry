---
title: Authored Type Schema
description: Write an artifact_types entry field by field, and the lore that makes the company file it.
read-when: Before writing an authored type's JSON into a pack.
tags: [worldloom, doctypes, packs, schema, lore]
---

# Writing an authored type, field by field

## What is authorable

| Table | Shape | Authorable |
| --- | --- | --- |
| `_STANDING` | `(Authority, Lifecycle)` | yes |
| `_LAG` | a `timedelta`, always whole minutes | yes |
| `_OUTLINES` | a tuple of `SectionPlan`, four strings each | yes |
| `_COMPILERS` | a function | **no** |

The type goes in the pack, under `artifact_types`. Copy
`assets/artifact-type.json`: a complete entry with `key`, `authority`,
`lifecycle`, `lag` (`{"days":…, "hours":…, "minutes":…}`, three integers, not
a duration string, so two packs cannot disagree about what `P1DT15H` means),
`word: true`, `sections`, and `filing`.

## The five fields that decide whether the document is any good

- **`sections[].kinds`** are fact-kind *prefixes*, and they are what the
  section is handed. A prefix nothing produces resolves to no facts, the
  section is dropped, and the document compiles into a hidden appendix and
  nothing else. It does not fail. Start from
  `doctypes.describe("cfo_variance_memo")` rather than guessing.
- **`sections[].scope`** filters on a fact's *subject*: `group` for company
  subjects, `unit` for business units, `any` otherwise. Only the financial
  generators state one figure per company and another per unit, so `close.` or
  `ops.` facts scoped to `unit` resolve to nothing.
- **`sections[].purpose`** is the field that decides whether the prose argues
  or lists. "Write the drivers section, here are four metrics" gets four
  correct sentences. Say what the section has to *establish*, and for whom.
- **`filing.audience`** decides who may **open** the document, not who
  receives it. It resolves through `world._policy_for`, and an audience
  nothing maps falls to the world's narrowest policy: if that excludes the
  author, the corpus fails `author_cannot_see_own_artifact`. Name the receiver
  in the purposes.
- **`filing.size`** names how long the document may be: `small`, `medium`,
  `long` or `xlong` (`worldloom.sizing.PRESETS`, each a component cap the
  composer enforces and a word brief every section's writer is given). When
  no preset fits, declare **`filing.budget`** outright,
  `{"components": 60, "words": 450}`, and it wins over the word. The budget
  rides the planned intent, so a process that only loads the corpus narrates
  and renders to it without the pack. The lint refuses a budget smaller than
  the outline's required sections, since the composer never drops one.
- **`lag`** is how long after its newest cited fact the document is written.
  Keep it at or under a day and fifteen hours: `scenarios._period_boundary`
  places a departure eight business days after period end and chose eight
  against the slowest artifact any episode plans. A later lag puts an author's
  departure before their signature, silently, and only in some months.

## Then make the company file it

Declaring a type does not produce one. What produces one is lore, in the same
`artifact_density` vocabulary a facet uses. Copy `assets/filing-lore.json`:

```json
{"kind": "artifact_density", "target": "filing/franchisee_trading_statement",
 "effect": "The network is sent a statement of the month every period",
 "magnitude": 1.0}
```

That constraint sits inside a `norm` lore entry whose `assertion` states the
obligation. The type is the company's *vocabulary*; the lore is its *claim
about who it answers to*. Magnitudes sum across commitments, so a negative one
suppresses. That is how a founder-led company loses its minutes.
