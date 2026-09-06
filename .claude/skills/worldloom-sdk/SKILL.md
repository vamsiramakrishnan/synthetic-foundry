---
name: worldloom-sdk
description: Write Python against Worldloom instead of driving its CLI: compose blueprints, cross and disperse them, build many worlds in a loop, and filter on what came out. Use when a corpus request needs an arrangement no single command expresses: several organisation shapes crossed with several calendars, a sweep of one parameter, keeping only the worlds whose blast radius exceeds some number, or anything where the answer is a comprehension rather than a flag.
tags: [worldloom, sdk, python, blueprints, sweeps]
---

# Worldloom as a library

The CLI is a set of **fixed pipelines**. `worldloom mosaic -n 5` is one
arrangement of the machinery; `build` is another. Wanting a different one: five
organisation shapes crossed with three trading calendars, keeping only the ones
whose dependency graph is deep enough to be worth asking about, means a new
flag, a new command, or a shell script gluing JSON between processes.

You write Python. Use it.

## The happy path

```python
from worldloom import sdk

base = sdk.retail().org(levels=4).calendar("harvest")
field = [base.org(headcount=n, span=s) for n, s in ((18, 4), (31, 8), (25, 6))]
rich = [
    w for w in (b.build() for b in field)
    if w.measure()["chokepoints"] >= 10 and w.ok
]
rich[0].export(out_path)          # or .render("xlsx", "docx", out=out_path)
```

A `Blueprint` describes a world that does not exist yet. Every method returns a
new one, so a half-configured blueprint is a perfectly good thing to hold.
`sdk.company(name)` is the registry-driven front door (`retail`, `banking`,
`insurance`, `procurement`, or anything installed). `.describe()` says what a
blueprint means without building it: decide whether forty worlds are worth the
wait before generating forty worlds.

## Fields of worlds

```python
sdk.cross(base, calendar=["flat", "harvest"], estate=["small", "large"])   # 4
sdk.sweep(base, "calendar", ["flat", "harvest", "fiscal_year_end"])        # 3
sdk.dispersed(candidates, 8)       # the 8 least alike, the interesting one
```

`sdk.built(blueprints)` builds lazily, so a loop that stops early does not mint
the rest. `sdk.mosaic_of(n, engine=...)` and `sdk.probe_of(session, n)` return
*blueprints*, not worlds, so an existing field can be constrained further
before anything is built.

## No invariant is relaxed

A blueprint still refuses everything the engine refuses: an organisation whose
headcount, span and depth cannot all hold at once, physics that would tune away
the question a vertical exists to pose. The freedom here is in *arrangement*; a
loop that could emit incoherent worlds would be a slower way to get noise. A
refusal names the rule and usually the arithmetic. Fix the input; never work
around a check.

## When to use the CLI instead

One world, one command, or a shell pipeline: `worldloom build`,
`worldloom mosaic`, `worldloom render`. Reach for the SDK the moment you want a
loop, a filter, or a product.

## Read next

- `references/blueprint.md`: every builder method and what it sets; load when
  composing a blueprint beyond seed/org/calendar.
- `references/loops.md`: cross, sweep, dispersed (and why `dispersed` is the
  one people get wrong), measuring and filtering `Built` worlds, the mosaic and
  probe bridges.
- `references/corpus-loop.md`: the built world asked about itself:
  `built.search` (BM25 self-retrieval), `built.mutated`/`built.twin`
  (recipe patches and measured counterfactuals), `sdk.as_fleet` into
  `fleet.qualify`, access gating and `evolve` from Python.
