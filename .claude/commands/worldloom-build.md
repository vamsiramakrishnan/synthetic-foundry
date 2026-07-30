---
description: Build a Worldloom corpus from a seed and report what it contains
---

Build a synthetic enterprise corpus. Arguments: $ARGUMENTS (a seed, and optionally
a period like 2026-03; default to seed 8128 and period 2026-03 if not given).

```bash
worldloom build --seed <SEED> --period <PERIOD> --incident --out ./corpus
```

Then show the user the summary table and tell them what is *not* there yet: the
artifacts are planned and their tables resolved, but the prose is not written. Point
them at `/worldloom-narrate` to write it.

Omit `--incident` if the user wants the seed and the world's lore to decide whether
the operational incident happens — that is the more interesting behaviour, since it
makes a 2026 close go wrong because of a decision recorded in 2024.
