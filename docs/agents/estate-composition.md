---
title: Estate composition
description: Grow a stock landscape with --estate, or author a vertical's estate through a refusable handshake.
read-when: The corpus needs a real service landscape, or a vertical's estate has no vocabulary yet.
tags: [estate, compose, topology, services, landscape]
---

# Composing the estate, optionally

A stock world runs four services on five systems, because nine is what the
episode names. `--estate small|medium|large` grows a real landscape around them
on the retail engine — layered, with placed chokepoints, and with the episode's
own services untouched so its causality is unchanged.

For a vertical whose vocabulary the engine does not have — banking's estate is
not called `click-collect-api`, and the insurer ships with no services at all —
you author it, and the graph is the grammar:

```bash
worldloom compose requests ./corpus -o estate.json    # what the company already runs
#                                                       you write the estate and its lore
worldloom compose accept ./corpus --from estate.json --model-id <your model>
worldloom topology ./corpus                           # read what you built
```

The request carries the company, its units, every existing service with what it
depends on, who may own something, the closed constraint vocabulary lore may
use, and the rules — so you can answer without reading the source. Propose
services and systems under keys of your own; the harness mints the ids.

The refusals are the point, and each is stated in the request before you write
anything: a dependency cycle through any number of hops, a dependency that
resolves to nothing, an owner who does not work here, a criticality tier the
graph contradicts, lore that constrains nothing, and an estate in which nothing
is a single point of failure. All violations come back at once, and nothing is
committed unless everything passes. Accepted compositions land in the generation
ledger, so a composed corpus replays with no provider reachable.
