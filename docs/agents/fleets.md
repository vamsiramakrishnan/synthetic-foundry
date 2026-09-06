---
title: Fleets
description: Build many distinct companies by planning with spaces, sampling with mosaic, admitting with fleet, and evolving.
read-when: Building many companies at once, or asked for a fleet, a dataset, or a covering plan.
tags: [mosaic, spaces, fleet, evolve, coverage]
---

# Many companies at once

Varying the seed does not give you several enterprises. A seed decides names,
figures, and which month the incident lands in; it does not decide headcount,
span of control, reporting depth, trading calendar, or how fast an organisation
finds the cause of an outage. Five seeds produce **one company with different
names on the same twenty-three people**: a fine corpus and a poor dataset,
because a model evaluated against it has seen one enterprise five times.

```bash
worldloom mosaic --describe                       # what varies, building nothing
worldloom mosaic -n 5                             # the plan, still building nothing
worldloom mosaic -n 5 --incident --out ./mosaic
worldloom mosaic -e banking -n 5 --out ./banks    # or insurance
```

Each engine varies its own physics, because the parameters are its own: a
retailer's margin erosion and incident tempo, a bank's capital headroom and how
badly its filed risk-weighted assets understate the truth, an insurer's tail
length and how bad the news the actuary has to deliver is. Only the retail
engine varies a trading year, because `finance.generate` is the one generator
that reads one. Estate size is an axis for all three, so a mosaic of banks spans
9 to 101 nodes and the corpus can be asked what has a blast radius.

## Planning a fleet rather than sampling one

`mosaic` and the determinism gate both *choose* configurations, and neither can
say what it missed: a sampler knows where its points landed and not which
combinations nobody reached. `spaces` gives that answer:

```bash
worldloom spaces                                  # every axis, and how few rows cover it
worldloom spaces --cover -t 2 > plan.jsonl        # the planned fleet, building nothing
worldloom spaces --holes plan.jsonl               # what a fleet you already built missed
```

Thirteen axes, **11,197,440 configurations exhaustive, 39 rows to cover every
pair**, because a covering array grows with the two widest axes rather than
with the space (adding the three-level `access` axis tripled the space and
changed the row count not at all). That is a different guarantee from `mosaic`'s: dispersion
spreads points evenly through a cube and can still never once pair a bank with
three periods, which is what it had never done.

`--holes` is the reading to run against a fleet you already have. It
reports the axes a fleet *never varied at all* before it lists the combinations
it missed, because one unvaried axis is a hundred holes with a single cause, and
a list that does not say so reads as a hundred separate failures.

## The four commands are one loop

They close on each other, and the closing is what makes them useful:

```bash
worldloom spaces --cover -t 2 > plan.jsonl    # what should exist
worldloom build --outline-synthesis 600 ...   # make one of them
worldloom diversity ./corpus --effective      # is what came out actually varied
worldloom spaces --holes fleet.jsonl          # what still does not exist
```

Plan, build, measure, then ask what is missing and plan again against the
answer. What makes it a loop rather than a pipeline is that both readings report
a **denominator**: `--effective` prices a shape used ten times differently from
one used once, and `--holes` divides by the combinations that exist rather than
the ones you happened to try. "We built two hundred corpora" becomes "we covered
41% of the pairs and never varied six of the thirteen axes at all", which is a
sentence you can act on.

Both readings are *readings* and neither may be fed back into a build. A
generator that branched on an effective-diversity score would make a corpus's
bytes depend on which BLAS the machine linked; a fleet planner may consume
`--holes`, but the world builder may not.

## Admitting a fleet, rather than shipping whatever was generated

Every reading above measures and none of them rules: a fleet is generated,
measured six ways, and then all of it ships. `fleet` composes the readings
into a verdict and a keep list:

```bash
worldloom fleet qualify ./mosaic --purpose challenge   # measure, verdict; exit 1 if not qualified
worldloom fleet curate ./mosaic --purpose challenge    # champions per niche, rejects, empty niches
```

`qualify` checks that every member coheres (`validate`), rebuilds from its own
recipe and ledger into the same fact ledger and artifact plan, and holds the
floors its purpose requires: a challenge fleet must mint questions and must
not contain the same world twice; a counterfactual fleet must share one
archetype, so a difference in outcome attributes to the varied input rather
than to being a different company. The record also reports the fleet's
pairwise coverage of the configuration space, the axes it never varied, the
reachable-spine share, the questions restated across worlds, and effective
diversity, that last clearly labelled non-gating, for the BLAS reason above.

`curate` keeps one champion per niche of a small behaviour grid (deterministic
integer features of the measured corpora, never an eigendecomposition), lists
every reject with the champion that displaced it and why, and writes
`fleet-manifest.json`, byte-for-byte stable, whose empty niches are the next
generation's worklist. A curator is downstream of generation: nothing it emits
feeds back into a build.

There is no `naturalistic` purpose. Qualifying a fleet as resembling real
enterprise populations needs reference data this repository does not have, so
that purpose is refused naming the data it would take; offering it would
convert "we don't claim realism" into a fake claim.

## Evolving a fleet, generation by generation

`evolve` closes the loop `spaces`, `mosaic` and `fleet` leave open. It runs
propose → build → measure → select → vary as one command:

```bash
worldloom evolve --generations 3 --population 6 --seed 8128 --purpose challenge --out ./evolved
```

Generation zero is a dispersed sample of the axes above; each generation's
champions come from `fleet curate`, and each child differs from its parent
champion in one axis, chosen by a seeded ordering with every stepped-over
candidate recorded beside its refusal. Same seed, same run, byte-for-byte,
manifests included, and a rerun resumes rather than rebuilds. Axes the loop
cannot drive are excluded with the reason printed, not skipped silently, and
`naturalistic` is refused here for the same reason it is refused above. Not a token is spent until you choose a champion to narrate.

Each world lands in `./mosaic/world-NN/` with its own recipe, so any one of them
rebuilds alone. `mosaic.json` records the plan. Measured on five worlds: five
distinct organisation shapes, five distinct title sets, mean title overlap 0.72
against 1.00 for five plain seeds, and every world validates clean.

Candidates are covered with a low-discrepancy sequence rather than drawn at
random, because random points clump and a clump is a company shape the tool
never produces. They are filtered to what can actually be built (headcount,
span and depth are three numbers with two degrees of freedom, so the
over-determined combinations are discarded rather than rounded into feasibility)
and then the furthest apart are chosen by farthest-point traversal. That last
step earns its cost: measured at 2.5× the minimum separation of simply taking
the first five candidates.

Deterministic throughout. World *N* uses `seed + N - 1`, so a mosaic's third
world is reproducible without building the first two, and a smaller mosaic is a
prefix of a larger one.

## From a premise, end to end

`--probe` takes the axes from a settled probe instead of the engine's defaults:

```bash
worldloom probe open -p "A specialty apparel retailer, 180 stores."
# ... answer its questions ...
worldloom mosaic --probe probe.json -n 5 --out ./apparel
```

The probe decides **what varies and between which bounds**; the algorithm still
decides **which N**. That division is why the flag exists: a model is good at
arguing that a business of this kind runs margins in that band and bad at
picking five points that cover a seven-dimensional space; a farthest-point
traversal is the reverse, and neither is asked to do the other's job.

Every parameter the probe bound becomes an axis over the interval it argued for,
and no world's range ever escapes that envelope. Axes the probe said nothing
about keep their defaults, so a probe that reasoned about margin and ignored
reporting depth still gets five different reporting depths. A probe that bound
nothing at all is refused rather than quietly falling back, because it would
report success for work that reached no engine.
