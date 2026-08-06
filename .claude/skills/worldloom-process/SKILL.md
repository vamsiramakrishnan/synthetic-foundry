---
name: worldloom-process
description: Author a business process for a Worldloom company through a refusable cascade — seed it with a name, purpose, engine and owning LOB, propose its steps and the fact kinds they mint, declare its ordered role slots, and resolve it into an episode spec that installs, runs, and replays. Use when a company needs a recurring process (a close, a P2P cycle, an onboarding drive) that no shipped scenario models, or when asked who participates in a process and in what order.
---

# Authoring a process

A **process** is the recurring type, declared once — the month-end close, P2P,
a recruitment drive. One bounded run of it over a period is an **episode**
(`episodes.EpisodeSpec` is the spec; `AuthoredEpisode` is the run). This skill
authors a process through the same staged handshake as `/worldloom-lob`: seed →
briefs → refusable answers → resolved spec. Only the resolved spec replays; the
conversation is never recorded.

## The cascade

```python
from worldloom import process

seed = process.ProcessSeed(
    name="HrOnboarding",
    purpose="Every joiner is recorded, surveyed, and signed off.",
    engine="retail",
    lob="hr",                # the LOB whose responsibilities derive who participates
    period="month",
)
process.lint_seed(seed)      # advisory: unknown engine, unknown LOB
session = process.open(seed, facets={"listing": "listed"})   # facets ride every brief
```

**Stage 1 — steps and kinds.** `process.next_stage(session)` asks for the
steps (ordinary `episodes.EventSpec`s, in order) and the fact kinds they mint
(`episodes.FactKindSpec`s). The brief's `context` carries the engine, the
facets, and the owning LOB's roles and responsibilities — propose for *this*
company. The rule the stage enforces: a minted kind must be **registry-known
or declared with invariants**. A registry-known kind (`factkinds.names()`)
may leave `invariants` empty — `accept` fills them from the registry, so the
spec cannot drift from what the validators actually enforce. An unknown kind
must declare its own invariants or the answer is refused.

```python
session = process.accept(session, process.Answer(stage="steps", steps=[...], kinds=[...]))
```

**Stage 2 — slots.** The process declares its ordered role slots — its own
vocabulary (`preparer`, `challenger`, `approver`, or whatever this process
calls its seats), in the order the work moves. Do not name company role keys
here: slots are the process's vocabulary, the binding is the company's.
Propose `[]` if there is nothing to order.

```python
from worldloom.episodes import RoleSlotSpec
session = process.accept(session, process.Answer(stage="slots", slots=[
    RoleSlotSpec(slot="preparer", purpose="records the joiner"),
    RoleSlotSpec(slot="approver", purpose="signs the onboarding off"),
]))
```

**Resolve.** `spec = process.resolve(session)` derives the `EpisodeSpec`,
linted whole. Install and run it like any authored episode:

```python
from worldloom import episodes
episodes.install([spec])
world = world.run(episodes.AuthoredEpisode(episode=spec.name, period="2026-01"))
```

## Binding and participation

The company's half lives on the LOB: `lob.SlotBinding(process=..., slot=...,
role_key=...)` rows in `Lob.slot_bindings`. Lint them with
`lob.lint_bindings(my_lob, spec)` — an unbound **required** slot and a binding
to a role the LOB lacks are both refused.

Who is *in* a process is never a table — it is the join of the LOB's
responsibility edges against the kinds the process's steps mint (dot-prefix
semantics: answering for `financial.revenue` meets minting
`financial.revenue.actual`), plus the slot bindings:

```python
from worldloom import lob, sdk

lob.participation(my_lob, spec)         # tuple of Participant(role, slots, kinds, via)
lob.describe("hr")["participation"]     # per installed process, for installed LOBs

blueprint = sdk.retail().lob(my_lob, bind={"HrOnboarding": {"preparer": "recruiter",
                                                            "approver": "head_of_people"}})
blueprint.participation("HrOnboarding") # {lob_name: participants}, spec must be installed
```

## Determinism

Only the resolved spec replays: the recipe records `AuthoredEpisode(episode=
name, period=...)`, and a rebuild in a Python process that never installed the
spec fails loudly. The session, its briefs, and every refused answer are
working state. No draw, no clock, no set iteration anywhere in the cascade.
