---
name: worldloom-lob
description: Author a Worldloom line of business through a refusable cascade — declare its roles, responsibilities, lore, and process-slot bindings so participation, access, and accountability can be derived rather than maintained separately. Use when a company needs an organizational capability such as finance, procurement, HR, or underwriting that must participate in authored processes.
tags: [worldloom, lob, roles, cascade, participation]
---

# Authoring Lines of Business

A Line of Business (LOB) declares the roles, responsibilities, and lore of an
organizational unit — finance, procurement, HR, underwriting. From those
declarations the engine derives authorship hints, access policies, and
accountability facts. It is authored through a refusable cascade: the engine
briefs you, you answer, and an incoherent answer is refused with findings
rather than silently building a broken world.

## The loop

```python
from worldloom import lob

seed = lob.LobSeed(name="finance", title="Finance",
                   purpose="Financial management, reporting, and close-out.",
                   engine="retail")
lob.lint_seed(seed)               # [] or findings — e.g. an unregistered engine
session = lob.open(seed)

brief = lob.next_stage(session)   # brief.stage, brief.asks, brief.context
session = lob.accept(session, answer)   # stage "roles", then "responsibilities"
lob_spec = lob.resolve(session, artifact_filings=[...],
                       episode_contributions=[...])
```

A refused `accept` raises `ValueError` carrying the findings. Fix the specific
finding and answer again; do not loosen the answer around it.
`examples/finance-lob.md` is this loop worked end to end — a finance LOB from
seed to built world, with the two refusals to expect first.

`assets/lob-seed.json` is a seed to copy; `lob.load_seed` reads a path, JSON
text, or dict.

## Read next

- `examples/finance-lob.md` — the complete exchange: every answer spelled out,
  through resolve and into a built world.
- `references/cascade.md` — every stage's fields and the refusal taxonomy.
  Load before answering a brief.
- `references/integration.md` — the shipped finance/procurement/HR library,
  blueprints and slot bindings, install/describe, determinism. Load when
  building with a finished LOB.
