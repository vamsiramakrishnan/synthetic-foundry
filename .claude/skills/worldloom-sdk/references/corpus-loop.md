---
title: Corpus Loop
description: Ask a built world about itself: search, mutate, twin, fleet hand-off, access gating, evolve.
read-when: Closing the loop on a built world with retrieval, counterfactuals, or fleet qualification.
tags: [worldloom, sdk, retrieval, twins, fleet]
---

# The corpus loop: search, mutate, twin, fleet, from Python

Every door here reaches the same machinery its CLI command does: never a
second implementation that can drift. That sameness is pinned by
`tests/test_sdk_doors.py`.

## Ask a corpus what it already says

```python
hits = built.search("operational incident stock loss", limit=3)
hits[0]["passage_id"], hits[0]["score"], hits[0]["fact_ids"]
```

The same passage index and BM25 ranking `evaluate` scores retrievers with, so
what a loop retrieves is what the benchmark's baseline will see. Refusals
match `worldloom search`: an empty query, an empty index, a cutoff before the
world began. `as_of="2026-03-31"` searches only what existed then: the
narration contract's temporal cutoff applied to retrieval. Zero-score hits are
never returned.

## Mutate the recipe, rebuild in memory

```python
mutant = built.mutated({"steps/0/trend_pct": 0.008})
```

`twins.mutated` then `recipe.rebuild`, no disk. The mapping's insertion order
is the application order. Every twin refusal survives: an unrecorded path
raises `TwinError`; an existence-deciding path (`employees`, `policies`,
`estate`…) raises `MutationRefused`; measure those with `twin` instead.
`.blueprint` on the mutant is the ancestor's: the recipe records
what was made and is what was patched, while the blueprint tells a fan-out
loop where the mutant came from.

## Measure a counterfactual

```python
result = built.twin("steps/0/trend_pct", 0.008)
result.manifest.changed_fact_ids     # what moved
result.manifest.unchanged_counts     # the denominator that makes it a claim
```

Both sides rebuilt from the record, never from the in-memory world, for
`twins.twin`'s stated reason. A cardinality-changing intervention is a
measurement whose result is `manifest.refused`, not an exception.

## Hand a loop's worlds to the admission controller

```python
from worldloom import fleet

root = sdk.as_fleet(narrated_builts, "./flotilla")
verdict = fleet.qualify(root, "challenge")     # or fleet.curate(root, ...)
```

`as_fleet` writes the `world-NN/` layout `fleet` admits and stops there:
qualification's verdict belongs to `fleet`, and fusing export with judgment
would grow a second door into the one controller. Members need narration
first (`world.narrate(DeterministicProvider())`): an un-narrated corpus has
no readable surface, and the challenge floors say so.

## The rest of the loop

- **Access gating**: `built.run(scenarios.AccessProfile(level="strict"))`:
  the `--access` knob is an ordinary scenario, so `run()` is already its door.
- **Generations**: `from worldloom import evolve`. `evolve.evolve(...)` is a
  Python API in its own right (the CLI command is a thin wrapper over it);
  it builds through the `worldloom` executable, so its members
  carry CLI-recorded recipes.
