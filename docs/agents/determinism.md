---
title: Determinism in depth
description: Prove a corpus regenerates from its own record — replay, verify, migrate, and the schema-bump policy.
read-when: Proving byte-identity, carrying a corpus across schema versions, or bumping SCHEMA_VERSION.
tags: [determinism, replay, verify, migrate, schema]
---

# Determinism, in depth

A world regenerates byte-for-byte from its seed plus its generation ledger:

```bash
worldloom build --seed 8128 --incident --replay ./corpus -f markdown --out ./again
diff -r ./corpus ./again
```

The second command makes **no model call at all** — every request is served from
the ledger. CI enforces this on every push.

`worldloom verify ./corpus` is that contract as one verb: it rebuilds the
corpus from its own recipe and generation ledger into a temporary directory,
byte-compares every file, then validates — exit 0 means the directory on disk
is exactly what its own record regenerates, and coherent. It makes no model
call and never renders, so a corpus already rendered into files diverges at
its first rendered file by design; prove a rendering by replaying the build
with the same `-f` flags. A corpus with no recipe refuses (`no_recipe`)
rather than verifying vacuously, and a divergence names the first differing
path and whether it is missing, extra, or different (`verify_diverged`,
exit 1).

`worldloom migrate ./corpus --out ./upgraded` carries a corpus to the current
schema version — today an identity copy, because the version chain has no
steps yet. `corpus.SCHEMA_VERSION` may only be bumped together with a
migration step in `worldloom.migrate._STEPS`; the frozen fixture test in
`tests/test_migrate.py` fails on any PR that bumps without one. When bumping:
move `tests/fixtures/schema-current` to `schema-v{old}`, freeze a new current
fixture, and add a test migrating the old one.
