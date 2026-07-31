---
description: Build a Worldloom corpus from a seed and report what it contains
---

Build a synthetic enterprise corpus. Arguments: $ARGUMENTS (a seed, and optionally
a period like 2026-03; default to seed 8128 and period 2026-03 if not given).

```bash
worldloom build --seed <SEED> --period <PERIOD> --incident --out ./corpus
```

Two flags change the shape of what gets built, and are worth asking about rather
than defaulting silently:

- `--archetype <NAME>` picks the company shape (`worldloom archetypes` lists
  them — a mid-size omnichannel retailer or a large Australian supermarket
  group today). Or use `--inspired-by "a large Australian grocer"` and let the
  phrase resolve to an archetype; either way no real data about the business is
  used, only its shape.
- `--periods N` runs N consecutive closes from `--period` onward instead of
  one. This is the only way to get recurrence, superseded documents, and the
  evaluation questions a single close can't pose — reach for it whenever the
  user's request implies "over time" or "across a few months."

Then show the user the summary table and tell them what is *not* there yet: the
artifacts are planned and their tables resolved, but the prose is not written. Point
them at `/worldloom-narrate` to write it.

Omit `--incident` if the user wants the seed and the world's lore to decide whether
the operational incident happens — that is the more interesting behaviour, since it
makes a 2026 close go wrong because of a decision recorded in 2024.

For scale, comparatives, or replay, see `references/building.md`.
