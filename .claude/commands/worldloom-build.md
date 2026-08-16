---
description: Build a Worldloom corpus from a seed and report what it contains
tags: [worldloom, build, seeds]
---

Build a synthetic enterprise corpus. Arguments: $ARGUMENTS (a seed, and optionally
a period like 2026-03; default to seed 8128 and period 2026-03 if not given).

```bash
worldloom build --seed <SEED> --period <PERIOD> --incident --out ./corpus
```

The high-impact choices are worth asking about rather than defaulting silently:

- `--archetype <NAME>` picks a registered company shape; `worldloom archetypes`
  is authoritative. `--inspired-by` borrows shape only and performs no lookup.
  Use `--spec` when the request also states geography, facets, leadership,
  revenue, or identity.
- `--periods N` adds recurrence and historical questions on the retail path.
  Add `--timeline quiet|steady|turbulent` when people, incidents, workforce, or
  estate should change between periods. Banking, insurance, and procurement are
  single-episode CLI verticals and refuse a multi-period build.
- `--employees` is aggregate workforce, not named-roster cardinality.
  `--headcount-end` and the four structural `--*-end` flags define exact final
  anchors for a multi-period retail history.
- `--eval-density`, `--distractors`, and `--messiness` control evidence volume,
  false friends, and recorded archive imperfection independently.

Then show the user the summary table and tell them what is *not* there yet: the
artifacts are planned and their tables resolved, but the prose is not written. Point
them at `/worldloom-narrate` to write it.

Omit `--incident` if the user wants the seed and the world's lore to decide whether
the operational incident happens — that is the more interesting behaviour, since it
makes a 2026 close go wrong because of a decision recorded in 2024.

For scale, trajectories, company surfaces, comparatives, locale, estate, or
replay, see `references/building.md`. For sharded multi-company generation, see
`docs/enterprise-corpus.md`.
