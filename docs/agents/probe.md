---
title: Physics by probe
description: Derive the numeric ranges by Socratic drill-down instead of typing thirty-seven of them.
read-when: The corpus must be a specific kind of organisation and the engine's default physics is not it.
tags: [probe, physics, parameters, trading-year, accountability]
---

# Deriving the physics, optionally

A pack supplies *values*: this unit's share, that category's name. The ranges
every figure is drawn from belong to the engine. Four literals decide how long
an organisation takes to find the cause of an outage, so every Worldloom
incident ever generated has resolved at one tempo, whatever the pack said the
company was.

The same is true of a company's trading year. One twelve-month index, a 21%
December, is applied to every world the retail engine builds, and since `base`
may only be `retail` or `banking`, that is every industry pack that is not
literally a deposit-taking bank. The general insurer shipped in
`examples/packs/` therefore wrote a premium book that peaked at Christmas.
`worldloom pack profiles` lists the trading years a pack may pick by name
(`flat` is the right answer for any business whose revenue is a book rather than
a till), or a pack may supply twelve months of its own, which must average one.

And a corpus had no way to say who answers for a number. Budgets attach to
business units, variances are reported and never judged, and the engine's one
ownership fact resolves to "unassigned", so *who was accountable for the unit
that missed* had no answer anywhere. Lore can now say so:

```json
{"kind": "accountability", "target": "gm_md/financial.revenue.variance",
 "effect": "The MD answers for revenue against budget", "magnitude": 3.0}
```

`target` is `role_key/fact_kind` and `magnitude` is the tolerance band in per
cent. It mints a fact whose **subject is a person**, the first in the project,
carrying the measure they are judged on and how far it may move before anyone
asks. `worldloom pack targets` lists it alongside every other consulted target.

## The probe loop

`worldloom pack params` prints the numeric ranges, now that they have names, and
`worldloom build --physics` overrides them. But a list of thirty-seven ranges to
fill in is the wrong instrument: they are not independent, and "retailer" or
"insurer" is a label, not a structure. So derive them instead, by descending the
organisation:

```
organisation → reporting → roles → objectives → measures
```

A layer is a *kind* of question, and a level is settled before the one under it
opens. How the business divides, then how it hangs together, then which titles
that implies, then what those titles are accountable for; only at the bottom
do numbers bind to the engine.

```bash
worldloom probe open -p "A field-services business, 900 people, four regions."
worldloom probe next probe.json                     # the question, its layer, its bounds
#                                                     you answer it
worldloom probe accept probe.json --from answer.json
worldloom probe show probe.json                     # the graph as it stands
worldloom probe worlds probe.json -n 5              # what your answers committed to
worldloom probe resolve probe.json -o physics.json  # the ranges it settled on
worldloom build --seed 8128 --physics physics.json --out ./corpus
```

`probe next` exits 3 when nothing is left to ask, so a loop can tell "finished"
from "failed" without parsing prose. The physics ride the corpus recipe, so a
probed corpus replays byte-for-byte with no probe file on hand.

The shape of an answer matters as much as its content. You may **narrow** a
question and never widen it; the bounds you are given are what earlier answers
established. If the
quantity is not primitive, do not pick a number: say so, and raise what it
follows from as sub-questions, each with a stated relation. Span of control is
not a number you know about a business; it is what the work's standardisation
and the supervision it needs produce.

**Link across layers.** Headcount, span and reporting levels are three numbers
with two degrees of freedom. A `link` states that, and the graph enforces it on
every answer that follows, in *both* directions, so a measure discovered at the
bottom can make a structure asserted at the top untenable.

The refusals are computed, not listed. Every relation is invertible, so the
whole graph is narrowed to arc consistency after each answer; if a range
empties, the answer is refused naming the chain that broke. Nobody wrote down
which combinations are illegal; they fall out of the relations you supplied.

Two things at the end. `probe worlds` first: a settled probe describes a *space*
of worlds, and this returns the ones furthest apart in it, deterministically. If
they all look the same you have over-constrained it; if they look incoherent a
link is missing. And a leaf that binds to no terminal parameter is **reported,
not dropped**: a quantity this world needed and the engine cannot read, which
is the only honest argument for adding one.

`source` records where a range came from. Sector statistics and published
benchmarks are priors and are welcome; with web search, use one rather than
your recollection of one. A named company's own figures are not: this corpus is
fictional and has to stay that way.

Over MCP the same surface is the tools (`probe_open`, `probe_next`,
`probe_answer`, `probe_worlds`, `probe_resolve`), so a session holds the loop
itself rather than being called once per question.
