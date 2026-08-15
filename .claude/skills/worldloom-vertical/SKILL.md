---
name: worldloom-vertical
description: Author a whole new industry vertical for Worldloom — its own episode, documents, checks and benchmark — through the registration seams, without editing core. Use when a corpus needs a business this repository does not model (a hospital, a manufacturer, an airline), when an industry pack cannot express what the episode actually is, or when asked what adding a fourth engine to this codebase would cost.
---

# Authoring a vertical

A **pack** re-voices an existing engine: new names, new units, new lore, same
episode. A **vertical** is a new episode — a different thing happening, with
its own fact kinds, its own documents, its own invariants and its own
benchmark. If the answer to "what happens in this corpus?" is not a month-end
close, a capital return, a reserving valuation or a purchase cycle, you are
authoring a vertical.

Do not start here. Read `.claude/skills/worldloom/references/extending.md`
first for the generation boundary, and `docs/build-order.md` §7a for why the
seams exist. This skill is the *cost*, measured, and the order of work.

## What it actually costs

Measured on the verticals added since the first, excluding tests: insurance
(quarterly reserving) was 7 files, 2,823 lines; procure-to-pay (purchase
cycle) 7 files plus 124 lines of archetype, 3,630 lines. The shape is stable,
and that is the useful part: **seven files, and the same seven every time** —
the domain module, the scenario, the documents, and four generators (org,
figures, episode, evaluation). Plus one archetype in
`src/worldloom/archetypes.py` (data only) and one import line in
`src/worldloom/__init__.py`. Budget a day, and expect the episode design —
*what happens, and what disagrees with what* — to be most of it.

## The workflow

1. Decide what disagrees with what. If nothing in your industry can be
   current and contested at once, you have a pack, not a vertical — stop.
2. Work the nine steps in `references/order-of-work.md`, in order: archetype,
   org, figures, episode, documents, checks, benchmark, tests.
3. Register through the four seams in `references/seams.md` — a `Domain`,
   a recipe step, artifact types, a check group — and nothing else.
4. Prove it: `pytest -q`, `worldloom validate retail-close`, the byte-diff
   and replay protocol in `references/traps.md`.

## Read next

- `references/seams.md` — the four registries, the CLI surface a `Domain`
  buys, and the closed tables a vertical must *not* widen. Load before
  writing any code.
- `references/order-of-work.md` — the nine steps, each with the defect it
  prevents. Load when starting the build.
- `references/traps.md` — multi-period reuse, draw order, intent ordering,
  and the done protocol (byte-diff of existing corpora, replay proof). Load
  before the first multi-period run and again before calling it done.
- A registered vertical is immediately a Python front door —
  `sdk.engine("hospital")` joins every loop in `/worldloom-sdk`.
