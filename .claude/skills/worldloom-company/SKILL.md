---
name: worldloom-company
description: Describe a company once, in one document, instead of assembling it from nine flags — industry, geography, revenue, size, margins, listing, competition, leadership — and let the description be refused when it contradicts itself. Use when a corpus has to be a *particular* kind of business ("a listed mid-size German insurer, thin margins, fragmented market"), when you find yourself reaching for --facet and --locale and --physics and --pack in one command, or when asked whether Worldloom can express some attribute of a company.
---

# One document that says what kind of company this is

Nine surfaces answer that question — an archetype key, `--employees`, `--facet`,
`--locale`, `--estate`, `--physics`, `--pack`, a vocabulary qualifier, and
revenue only by writing a pack. Each is right on its own. Between them they ask
you to know which of nine places every clause of "a listed mid-size German
insurer on thin margins in a fragmented market" belongs to — and two interact in
a way nobody predicts: naming *any* facet settles *every* facet at its registry
default, so `--facet listing=listed` alone also asserts a flat trading year,
replacing the engine's 21% December.

The specification is **a composer, not an engine**. Nothing it does is a
capability the flags lack. What it adds is that the pieces are resolved
*together* — and refused together when they contradict.

## The loop

```bash
worldloom pack spec                  # the schema, and which registry each field draws on
worldloom pack spec --template       # a starter, filled in rather than blank
# write company.json — assets/company.json is that starter
worldloom build --spec company.json --seed 8128 --out ./corpus
```

A refused build names every conflict at once, not the first, and each names the
arithmetic. Fix the specific clause; do not delete the claim that was refused.

## When not to use it

For one world with one unusual attribute the flag is shorter and clearer:
`worldloom build --facet maturity=legacy` says one thing and says it well.
Reach for a specification when three or more surfaces are involved, when the
description has to be handed to somebody else to read, or when you want it
refused before it becomes a corpus.

For deriving *ranges* you cannot argue from a label — how long this organisation
takes to find the cause of an outage — use `worldloom probe`
(`.claude/skills/worldloom-probe/SKILL.md`) and paste its resolved physics into
the specification's `physics` block. A probe argues the numbers; a
specification says what kind of company holds them.

## Read next

- `references/spec-fields.md` — every field, the seam it resolves into, what
  you may write where, and the identity/pack boundary. Load before writing the
  document.
- `references/refusals.md` — what is refused with what arithmetic, and what is
  reported as `unmet` rather than dropped. Load when a build refuses, or an
  `unmet:` line surprises you.
- `references/python.md` — `sdk.described` and `company.resolve`. Load when
  driving this from Python or reading what a description committed to.
