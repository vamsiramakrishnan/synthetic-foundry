---
title: Process Cascade Stages
description: Answer the steps and slots briefs field by field — seed, EventSpec, FactKindSpec, resolve.
read-when: Before answering the first process brief.
tags: [worldloom, process, cascade, episodes, fact-kinds]
---

# The process cascade, stage by stage

## Seed

`ProcessSeed` — four commitments and a cadence; everything structural is
proposed in stages where the lint can refuse it.

- `name`: `EpisodeSpec.name`'s shape, `^[A-Z][a-zA-Z0-9]*$` (`MonthEndClose`).
- `purpose`: one sentence — why the company runs this process.
- `engine`: a registered domain (`banking`, `insurance`, `procurement`, `retail`).
- `lob`: the owning LOB, whose responsibility edges derive who participates.
- `period`: `month`, `quarter`, or `year`.

`process.lint_seed(seed)` is advisory: an unknown engine and an unknown LOB
are findings, not exceptions — the cascade still runs with an unknown LOB, but
its briefs carry no roles or responsibilities and participation has nothing to
join. Author the LOB first (`/worldloom-lob`) or name a library one
(`finance`, `hr`, `procurement`). `process.open(seed, facets={...})` starts
the session; the facets ride every brief as context.

## Stage: steps and kinds

`process.next_stage(session)` asks for the steps (ordinary
`episodes.EventSpec`s, in order) and the fact kinds they mint
(`episodes.FactKindSpec`s). The brief's `context` carries the engine, the
facets, the period, and the owning LOB's roles and responsibilities — propose
for *this* company.

`EventSpec`: `kind` (`domain.event`, lowercase dotted), `when` (one of
`start`, `before_incident`, `incident`, `after_incident`, `end`), `summary`,
`fact_keys` (the kinds this event mints, in mint order), `detail`, plus
placement and causality fields. `FactKindSpec`: `kind`, `value_type` (one of
`money`, `measure`, `text`, `date`, `percent`), `unit`, `invariants`, and for
derived kinds `derive`, `parameter`, `cohort`.

The rule the stage enforces: a minted kind must be **registry-known or
declared with invariants**. Registry-known (`factkinds.names()`) may leave
`invariants` empty — `accept` fills them from the registry, so the spec cannot
drift from what the validators actually enforce. An unknown kind with no
invariants is refused: "a kind nothing validates may not enter a process
spec."

```python
session = process.accept(session,
                         process.Answer(stage="steps", steps=[...], kinds=[...]))
```

## Stage: slots

The process declares its ordered role slots — its own vocabulary (`preparer`,
`challenger`, `approver`, or whatever this process calls its seats), in the
order the work moves. Do not name company role keys here: slots are the
process's vocabulary, the binding is the company's (see
`references/participation.md`). Propose `[]` if there is nothing to order.

```python
from worldloom.episodes import RoleSlotSpec
session = process.accept(session, process.Answer(stage="slots", slots=[
    RoleSlotSpec(slot="preparer", purpose="records the joiner"),
    RoleSlotSpec(slot="approver", purpose="signs the onboarding off"),
]))
```

`RoleSlotSpec.required` defaults true — `lob.lint_bindings` refuses an unbound
required slot; an optional slot (an observer, a second challenger in larger
firms) may stay empty.

## Resolve, install, run

`spec = process.resolve(session)` derives the `EpisodeSpec`, linted whole.
Install and run it like any authored episode:

```python
from worldloom import episodes
episodes.install([spec])
world = world.run(episodes.AuthoredEpisode(episode=spec.name, period="2026-01"))
```

## Determinism

Only the resolved spec replays: the recipe records `AuthoredEpisode(episode=
name, period=...)`, and a rebuild in a Python process that never installed the
spec fails loudly. The session, its briefs, and every refused answer are
working state. No draw, no clock, no set iteration anywhere in the cascade.
