---
title: Building a World
description: Choose the build surface that owns each decision — seed, archetype, spec, facets, pack, periods, scale
read-when: About to run worldloom build and deciding which flags state the request completely
tags: [build, seeds, archetypes, packs, periods, determinism]
---

# Building a world

You are about to run `worldloom build`. This reference explains which build
surface owns each decision. Load `references/commands.md` only when exact option
spelling is needed.

## Seed, recipe, and determinism

```bash
worldloom build --seed 8128 --out ./corpus
```

The seed is the source of deterministic draws, not the complete corpus identity.
Every flag that changes the company, physics, schedule, evidence density, or
output is also an input. The recipe records resolved consequences and scenario
steps so the corpus can rebuild itself.

Same seed plus same resolved configuration plus same generation ledger under the
same Worldloom version produces the same corpus. A different seed changes names,
figures, and seeded event choices; it does not guarantee a different organization
shape. Use `mosaic` when the goal is multiple unlike companies.

## Choose the right company surface

Use the least powerful surface that states the request completely.

### An archetype or real-world shape

```bash
worldloom archetypes
worldloom build --archetype australian_grocery --out ./corpus
worldloom build --inspired-by "a large Australian grocer" --out ./corpus
```

An archetype is company shape without company data. `--inspired-by` resolves a
description to a registered shape and performs no external lookup. All names,
people, systems, events, and figures remain fictional and seed-derived.

The archetype also determines which registered domain owns the build. The four
shipped verticals are retail, banking, insurance, and procurement.

### A company specification

```bash
worldloom pack spec --template > company.json
worldloom build --spec company.json --seed 8128 --out ./corpus
```

Use a specification when one sentence spans industry, geography, workforce,
revenue, facets, leadership, and identity. Resolution checks those claims
together. `--spec` refuses the flags it subsumes instead of choosing precedence
between two accounts of one company.

### Facets

```bash
worldloom pack facets
worldloom build \
  --facet listing=listed \
  --facet maturity=legacy \
  --facet trading_pattern=christmas_peak \
  --out ./corpus
```

A facet is an operational claim, not a label. It can add roles, lore, physics,
calendar, and estate consequences. Naming any facet settles every facet at its
registry default, so state a non-default trading pattern explicitly. Inconsistent
claims are refused with the conflicting ranges or exclusions.

### Pack and physics

```bash
worldloom pack template retail > company-pack.json
worldloom pack targets retail
worldloom pack check company-pack.json
worldloom build --pack company-pack.json --out ./corpus
```

A pack supplies a particular company's identity, units, lore, voices, geography,
and optional document types while reusing an engine's episode. A physics file
changes registered parameter ranges. Use a new vertical only when the causal
episode, documents, invariants, and benchmark are genuinely different.

## Workforce scale

```bash
worldloom build --employees 80000 --out ./corpus
```

`--employees` is authoritative aggregate workforce. The named roster is a bounded
decision-making graph: authors, owners, approvers, actors, and reporting lines.
Worldloom does not mint one `Employee` object per payroll row.

The separation is load-bearing, not cosmetic. Explicit workforce scale changes
sampled incident, departure, and reorganization density logarithmically. It never
permits active named employees to exceed aggregate headcount; sampling, scenario
review, direct hires, and corpus validation all enforce that invariant.

## Periods and vertical scope

```bash
worldloom build --seed 8128 --periods 6 --out ./corpus
```

For retail, `--periods` runs consecutive monthly closes. Multiple points permit
recurrence, supersession, trend, historical state, and evaluation families a
single episode cannot express.

Banking, insurance, and procurement are currently single-episode CLI verticals.
Their period/carry-forward behavior is not generalized through the `build` loop,
so `--periods` greater than one is refused. Do not work around the refusal by
assuming retail's cadence applies.

`--comparatives` is a different axis: it adds prior financial actuals behind the
first close without creating full episodes for those months. Pair it with
`--trend` when the series needs a deterministic direction rather than a flat
seasonal level.

```bash
worldloom build \
  --comparatives 23 \
  --trend 0.004 \
  --periods 6 \
  --out ./corpus
```

## Eventful history

`--periods` repeats the episode against one evolving world. `--timeline` decides
what changes between those periods.

```bash
worldloom build \
  --periods 12 \
  --timeline turbulent \
  --out ./history
```

`quiet`, `steady`, and `turbulent` control sampled incident and organization-event
density. A departure changes later authorship because the role points to a real
successor. A reorganization changes reporting and unit leadership. Every accepted
scenario records its own recipe step; there is no second timeline serialization
that can drift from the events it produced.

A non-quiet timeline states incident presence per period, so it cannot be combined
with a forced `--incident` decision. Actor resumption is sequential and cannot be
combined with a precomputed timeline.

## Workforce trajectory

```bash
worldloom build \
  --employees 80000 \
  --headcount-end 92000 \
  --periods 6 \
  --timeline steady \
  --out ./growing-enterprise
```

`--headcount-end` creates exact aggregate workforce anchors. Intermediate values
are deterministically interpolated. Each movement emits headcount and signed-delta
facts plus a personnel notice.

The endpoint requires a multi-period retail build. A target may grow or contract,
but it may not fall below the active named roster.

## Structural estate trajectory

```bash
worldloom build \
  --periods 6 \
  --timeline steady \
  --estate large \
  --business-units-end 8 \
  --sites-end 240 \
  --systems-end 24 \
  --services-end 60 \
  --out ./changing-estate
```

The initial active counts come from the built world. Each endpoint is independent.
Growth appends deterministic entities. Contraction closes lifecycle windows and
retains the rows for historical artifacts and as-of queries. Dependency-safe,
role-safe, and category-safe floors are enforced.

Structural endpoints use the same multi-period retail timeline path and cannot be
combined with an actor episode.

## Technology estate

```bash
worldloom build --estate large --out ./corpus
```

Without `--estate`, retail contains only the systems and services required by the
episode. A named estate expands the graph around those causal nodes so blast
radius, chokepoints, and dependency depth become meaningful.

For a vertical whose vocabulary is not shipped, use the compose handshake after
build:

```bash
worldloom compose requests ./corpus -o estate.json
worldloom compose accept ./corpus --from estate.json --model-id architect-v1
```

The graph review refuses missing dependencies, cycles, impossible owners,
unsupported criticality, inert lore, and a topology with no meaningful single
point of failure.

## Locale

```bash
worldloom pack locales
worldloom build --locale germany --out ./corpus
```

Locale reaches corpus-wide figure grammar and, where the engine/pack exposes the
seam, names, regions, headquarters, currency, fiscal year, and working calendar.
A pack's explicit company identity wins over locale defaults. Locale is recorded
on the recipe so replay preserves both values and spelling.

## Evidence density and controlled mess

```bash
worldloom build \
  --eval-density high \
  --distractors 40 \
  --messiness lived_in \
  --out ./corpus
```

These controls answer different questions:

- `--eval-density` lets large dimensions and multiple periods create more
  supported questions and source artifacts;
- `--distractors` adds provenance-true drafts, personal copies, and routine
  notices that answer no evaluation case;
- `--messiness` adds recorded stale, conflicting, and orphaned archive state.

Messiness never relaxes canonical coherence. Every imperfection is labelled so a
reader holding only the corpus can establish what is wrong and which fact is
current.

## Narration and rendering

`build --narrate` uses the deterministic provider: complete, offline, replayable,
and intended for tests or inspection.

```bash
worldloom build --seed 8128 --narrate --out ./corpus
worldloom render ./corpus -f xlsx -f docx -f pptx -f pdf -f markdown
```

For production language, omit `--narrate` and drive `narrate requests` / `narrate
accept` with a coding agent. Canonical state and artifact scopes are identical in
both modes.

## Replay

```bash
worldloom build \
  --seed 8128 \
  --incident \
  --replay ./corpus \
  -f xlsx -f markdown \
  --out ./again
```

Replay rebuilds deterministic state and serves accepted generative calls from the
source corpus's generation ledger. It should make no provider call. Compare the
entire file set and bytes; comparing only `world.json` misses renderer and ledger
drift.

## Resume and inspect

```bash
worldloom status ./corpus
worldloom inspect ./corpus
worldloom inspect ./corpus --facts
worldloom inspect ./corpus --events
worldloom inspect ./corpus --artifacts
worldloom inspect ./corpus --evals
worldloom inspect ./corpus --lore
```

Start an interrupted or handed-off corpus with `status`, which reports the stage
and exact next command. Use `inspect` to read collections before writing an
explicit scenario or interpreting a validation result. Nothing in canonical state
is hidden.

For multi-company sharding, checkpoints, and operational scale gates, read
`docs/enterprise-corpus.md`.
