---
title: Twins and mutation
description: Attribute every delta to one recorded value with a twin, or mutate recipes without building.
read-when: Asked what one parameter caused, or fanning out structural candidates before building any.
tags: [twin, mutate, counterfactual, recipes, causality]
---

# One recorded value, one measured delta

Two seeds differ everywhere at once, so comparing them attributes nothing. A
**counterfactual twin** rebuilds the same recipe with exactly one recorded value
replaced — the physics endpoint, a step's `trend_pct`, the whole trading year —
so every row that differs between the two worlds differs *because of that value*:

```bash
worldloom twin ./corpus --set physics/retail.margin.erosion/high=0.06 --json
worldloom twin ./corpus --set steps/0/trend_pct=0.008 --out ./counterfactual
```

The delta manifest names the changed facts, documents and evaluation cases with
the unchanged counts beside them, measured at the corpus's own jsonl
representation rather than predicted. Paths are slash-separated because physics
names are themselves dotted. An intervention that changes *how many* things
exist (a policy level, an incident switched off) reshuffles sequentially-minted
ids and is **refused with the cause** — exit code 3 — because a diff across
reshuffled ids would label unrelated changes as caused. A zero-change manifest
is a finding, not a failure: a widened integer range can be absorbed by
rejection sampling and the twin honestly reports that the parameter reached
nothing. `worldloom.twins` in Python returns both worlds and the manifest.

# Many mutations, no build

A twin buys its causal claim with two builds. A fan-out harness planning dozens
of structural candidates cannot afford that per candidate, so `mutate` is the
build-free half of the same machinery: N interventions in, a mutated *recipe*
out, and no world on either side — mutate, measure cheaply, build only winners.

```bash
worldloom mutate ./corpus --set steps/0/trend_pct=0.008 --out mutant.json
worldloom mutate mutant.json --set steps/0/period=2026-04 --out mutant-2.json
```

Same path grammar as `twin`, same refusals, same exit taxonomy — with the
build-time measurement traded for a static classification where the missing
build forces the trade. An unrecorded path is an error (exit 2). A path that
decides what *exists* rather than what is true about it — a policy level, an
incident flag, a headcount — is refused (exit 3), because rebuilding it would
reshuffle sequentially-minted ids and break the alignment every delta depends
on; route that candidate through `twin`, which can afford to measure. And two
`--set` values for one path are refused naming it: a fan-out harness that
sends two values for one gene has a bug, and last write winning would hide it
until a build exposed it. The output is an ordinary recipe — rebuildable,
twin-able, and accepted back as input for a further round. In Python the same
surface is `worldloom.twins.mutated`.
