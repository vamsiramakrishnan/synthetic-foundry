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

### When the process's numbers are a grid, not a series

Most kinds mint one fact per period. Some businesses do not work that way: a loss
triangle, a loan book by vintage, warranty by manufacture quarter, retention by
hiring cohort. Each is a grid of **origin cohort × observation date**, where a
cell needs both coordinates to mean anything — *what we thought the 2025-Q1
accident quarter would cost, as at the March 2026 valuation*.

Declare the origin axis on the episode and put kinds on it:

```python
from worldloom.episodes import CohortSpec, FactKindSpec, Invariant

CohortSpec(name="accident_quarter", count=4, spacing_months=3, lag_months=3)
# episodes.cohort_periods("2026-03", axis)
#   -> ("2025-03", "2025-06", "2025-09", "2025-12")
```

`count` cohorts, `spacing_months` apart, the newest sitting `lag_months` before
the observing period — a cohort that has not finished developing has nothing
anyone could have observed, so a grid including it would state a figure nobody
held.

A kind naming that axis mints **one fact per cohort per run**, and each fact's
`period` is its **cohort's** period, not the run's. That is the whole design:
the observation lives in `valid_from` and the supersession chain, so "the same
cohort, one observation earlier" is an ordinary period-scoped lookup rather than
a convention, and nothing was added to `CanonicalFact` — an optional `cohort`
field would serialise as `"cohort": null` into every fact line of every corpus
ever built and fail the byte-identity gate estate-wide.

```python
FactKindSpec(
    kind="reserves.ultimate", value_type="money", unit="AUD_millions",
    cohort="accident_quarter",
    derive="allocation_of(reserves.central_estimate_total)",
    parameter="reserves.cohort.ultimate",     # one weight draw per cohort
    invariants=[Invariant(kind="holds-at"),
                Invariant(kind="rolls-up-to",
                          operands=["reserves.central_estimate_total"])],
)
```

Two derivations, both cohort-only (the lint refuses either without a `cohort`):

- **`allocation_of(K)`** — K's amount split across the cells by largest
  remainder, so the grid reconciles to its parent by construction rather than by
  luck. Equal weights unless the kind declares a `parameter`, which draws one
  weight per cell on a stream named for the cohort. Never draw per cell and sum:
  the total would be nobody's stated total.
- **`prior_in_cohort(K)`** — what K held for *this same cohort* at the previous
  observation. The diagonal step, and the one thing `prior(K)` cannot express:
  `prior(K)` walks the period axis, and a cohort's period does not move. Zero at
  a cohort's first appearance, same rule and reason as `prior(K)`.

And one invariant, **`rolls-up-to`**, declared on the cohort kind naming its
parent — not `sums-to`, which decomposes one period across *subjects*; this
decomposes one subject across *cohort periods*, and a check looking on the wrong
axis passes vacuously.

Three refusals to expect: a cohort kind must be `period-keyed` (an absent cell
makes the roll-up unanswerable — you cannot tell a cohort that reported nothing
from one nobody asked about); it may not also be a `series_days` series (both
claim the fact's `period`); and a kind whose invariants exceed what
`factkinds` registers for it is refused, so a registered kind gaining a roll-up
needs the registry line first.

**One thing the vocabulary does not have:** per-cell arithmetic between two
grids. The seven scalar derivations still work, but a grid asked for as a scalar
is its *roll-up* — so `minus(gridA, gridB)` states the book-level difference in
every cell, which validates clean and describes nothing. Read a movement off the
graph instead: a cohort's cells across observations are a supersession pair, and
`benchmark.py` already asks about it.

**The cascade has no cohort stage yet.** `process.resolve` builds the spec from
steps, kinds and slots, so an axis is attached after and re-linted by hand —
`episodes.lint` is where a cohort kind with no axis is caught:

```python
spec = process.resolve(session)
spec = spec.model_copy(update={"cohorts": [CohortSpec(
    name="accident_quarter", count=4, spacing_months=3, lag_months=3)]})
findings = episodes.lint([spec])     # model_copy(update=…) does not re-validate
assert not findings, findings
```

`docs/episode-grammar.md` works the reserving triangle end to end — four accident
quarters, the grid sliding a quarter between valuations, and the traps.

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
