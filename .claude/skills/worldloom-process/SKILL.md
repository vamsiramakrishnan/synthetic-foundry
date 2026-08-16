---
name: worldloom-process
description: Author a business process for a Worldloom company through a refusable cascade — seed it with a name, purpose, engine and owning LOB, propose its steps and the fact kinds they mint, declare its ordered role slots, and resolve it into an episode spec that installs, runs, and replays. Use when a company needs a recurring process (a close, a P2P cycle, an onboarding drive) that no shipped scenario models, or when asked who participates in a process and in what order.
tags: [worldloom, process, episodes, cascade, cohorts]
---

# Authoring a process

A **process** is the recurring type, declared once — the month-end close, P2P,
a recruitment drive. One bounded run of it over a period is an **episode**
(`episodes.EpisodeSpec` is the spec; `AuthoredEpisode` is the run). The cascade
is the same staged handshake as `/worldloom-lob`: seed → briefs → refusable
answers → resolved spec. Only the resolved spec replays; the conversation is
never recorded.

## The loop

```python
from worldloom import process, episodes

seed = process.ProcessSeed(
    name="HrOnboarding",            # EpisodeSpec.name's shape: CamelCase
    purpose="Every joiner is recorded, surveyed, and signed off.",
    engine="retail",
    lob="hr",        # the LOB whose responsibilities derive who participates
    period="month",
)
process.lint_seed(seed)             # advisory: unknown engine, unknown LOB
session = process.open(seed, facets={"listing": "listed"})  # facets ride every brief

brief = process.next_stage(session)     # stage "steps": brief.asks, brief.context
session = process.accept(session, process.Answer(stage="steps",
                                                 steps=[...], kinds=[...]))
session = process.accept(session, process.Answer(stage="slots", slots=[...]))
spec = process.resolve(session)         # an EpisodeSpec, linted whole

episodes.install([spec])
world = world.run(episodes.AuthoredEpisode(episode=spec.name, period="2026-01"))
```

A refused `accept` raises `ValueError` with findings; fix that finding and
answer again. The steps stage enforces one rule: a minted kind must be
**registry-known or declared with invariants**. A registry-known kind
(`factkinds.names()`) may leave `invariants` empty — `accept` fills them from
the registry, so the spec cannot drift from what the validators enforce. An
unknown kind must declare its own invariants or the answer is refused. Slots
are the process's own vocabulary (`preparer`, `approver`), never company role
keys; propose `[]` if there is nothing to order.

`assets/process-seed.json` is a seed to copy; `process.load_seed` reads a
path, JSON text, or dict.

## Read next

- `references/cascade.md` — both stages in field detail (spec enums included),
  resolve, determinism. Load before answering the first brief.
- `references/cohorts.md` — when the numbers are a grid (loss triangle,
  vintage book): origin axes, `allocation_of` / `prior_in_cohort`,
  `rolls-up-to`, and the refusals. Load only for cohort-gridded kinds.
- `references/participation.md` — the company's half: slot bindings on the
  LOB, and participation derived rather than stored. Load when seating roles
  or asking who is in a process.
