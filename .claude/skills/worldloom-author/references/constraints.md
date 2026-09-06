---
title: Harness Constraints
description: Hold every authoring stage to the four harness constraints no layer may relax.
read-when: Before authoring any stage of any layer's cascade.
tags: [worldloom, authoring, determinism, fact-kinds, narration]
---

# The constraints every authoring stage must respect

These are the harness's, not any one layer's, and no layer may relax them;
each layer skill assumes them.

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
