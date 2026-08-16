---
title: Fleet Coverage
description: Plan a fleet of corpora with covering arrays, and audit which combinations one never reached
read-when: The ask is several corpora — a mosaic, a sweep, a training set — rather than one
tags: [fleets, coverage, covering-arrays, mosaic, sweeps]
---

# Fleets: planning one, and auditing one you already built

Load this when the ask is *several* corpora — a mosaic, a determinism sweep, a
training set spanning industries — rather than one.

## The problem this solves

`worldloom mosaic` and `tools/sweep.py` both choose configurations, and neither
can tell you what it missed. A sampler knows where its points landed; it does
not know which combinations nobody reached. So "we built 240 corpora" sounds
like coverage and is not a coverage claim at all.

Measured on this repository's own determinism gate, at the seed and count its
workflow ships: **8 configurations covered 220 of 918 pairs — 24%.** Thirty
nightly seeds — 240 configurations, 480 builds — reached 41.4%. And one of the
holes had been structural for as long as the gate existed: it had **never once
compared two builds of a bank running more than one period**, which is exactly
where a carry-forward defect would live.

## The three commands

```bash
worldloom spaces                              # the axes, and how few rows cover them
worldloom spaces --cover -t 2 > plan.jsonl    # the plan, one JSON object per line
worldloom spaces --holes plan.jsonl           # score a fleet you already have
```

`--cover` builds nothing. It emits configurations; you run them.

## Why the row count is small

A covering array at strength *t* guarantees every *t*-way combination of axis
values appears in at least one row, and its size grows with the product of the
*t widest* axes rather than with the whole space.

For this repository's twelve axes — **3,732,480 configurations exhaustive** —
that is:

| strength | rows | what it guarantees |
| --- | --- | --- |
| t=1 | 6 | every value of every axis appears somewhere |
| t=2 | 39 | every *pair* of values appears somewhere |
| t=3 | 207 | every triple |

39 rows against an exact floor of 36: the two widest axes are both 6 wide and
each must take every value, so no pairwise fleet over this space can be shorter.

## How this differs from `mosaic` and from dispersion

Not in quality — in *guarantee*.

- `dispersion.halton` spreads points evenly through a continuous cube. Even
  spread is a good property and it is not coverage: a Halton fleet can be
  beautifully distributed and still never once pair a bank with three periods.
- `mosaic` varies each engine's own physics and produces genuinely different
  companies. It has no denominator, so it cannot report an omission.
- A covering array has a denominator and therefore a **stopping condition**.
  "Generate 200 corpora" is a budget; "cover every pair" is a target.

## Reading `--holes`

It prints the axes a fleet **never varied at all** before it lists the
combinations it missed. That ordering is deliberate: one unvaried axis is a
hundred holes with a single cause, and a list that does not say so reads as a
hundred separate failures.

Score a fleet against the axes it *can* reach when you want a fair number —
`BuildSpace.select` exists for that. A fleet that never touches five of twelve
axes scores badly for a reason that is true and uninformative: it is not that
its selection was poor, it is that those knobs have no front door in whatever
built it. Separating "chose badly" from "cannot reach" is the whole reading.

## When a hole is legitimate

Some are. A domain may cap its own built-in episode — insurance does, because
the half of its reserving that supersedes the first run's estimates is
unimplemented — and it says so on `domains.Domain.max_periods` rather than
raising from inside the scenario where no planner could see it.

The rule worth keeping: **every hole should have a declaration behind it.** A
hole with no declaration is an assumption in the planner, and that is precisely
how the multi-period bank gap hid for as long as it did.
