---
title: The refine loop that is not here
description: Explain why narration is open-loop, and measure repetition instead of rewriting it.
read-when: Tempted to close a rewrite loop over the corpus, or reaching for the MCP measurement tools.
tags: [refine, narration, diversity, mcp, deleted-code]
---

# The refine loop that is deliberately not here

Narration is open-loop: every section gets one request and one attempt, and
nothing afterwards looks at what the corpus became. This repository once closed
that loop — a `worldloom refine` command, MCP rewrite tools, a skill, and a
`Stop` hook — rewriting whichever sections a similarity join said were
near-duplicates of each other. It was deleted, and a future reader deserves the
reason rather than just the absence.

The loop was built and gated against `DeterministicProvider`, the template
writer CI uses, whose one-sentence-per-fact prose genuinely does repeat: three
closes from one template put tens of passages into near-duplicate groups. On
real model prose the problem it fought does not exist. A five-world proof run
measured the loop's target — passages sitting in a near-duplicate group — at
**zero in every world** (0/46, 0/50, 0/52, 0/46, 0/43). A writer that varies by
nature never gave the loop anything to do; the repetition was an artifact of
the deterministic fake, and no real writer reproduces it. The loop's headless
driver and API adapters were also the only code violating the first line of
`AGENTS.md`, and they went with it.

The *measurement* survives the loop, because "what does this corpus repeat?" is
worth asking of any corpus whoever narrated it — not least as the check that
the finding above stays true:

```bash
worldloom diversity ./corpus --near-duplicates   # the groups, named
worldloom stats ./corpus                         # the same reading among the rest
```

**`worldloom mcp`** serves the read-only tools over stdio — `measure_corpus`,
`corpus_topology`, `corpus_series`, `validate_corpus`, and the probe tools —
and `.mcp.json` wires them into Claude Code, so a session can ask those
questions repeatedly, as data, without leaving the loop it is actually running:
writing prose through `narrate requests` / `narrate accept`. No tool writes a
corpus; every corpus write path stays behind the handshakes.
