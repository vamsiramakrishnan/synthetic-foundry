---
title: Specification Fields
description: Write each company-spec field against the seam it resolves into, and know what may go where.
read-when: Before writing company.json, or when unsure whether a field is a value, a range, or free text.
tags: [worldloom, company-spec, schema, registries, packs]
---

# Every field of a company specification, and the seam each resolves into.

`worldloom pack spec` prints this schema from the code; what follows is the
map, not a substitute for running it.

| field | what it says | the seam it resolves into |
|---|---|---|
| `industry` | prose | `archetypes.inspired_by`, the same table `--inspired-by` uses |
| `archetype` | a registered shape by key | `archetypes.get` |
| `engine` | which vertical runs the episode | `domains.by_name` |
| `vocabulary` | what the divisions are *called* | `vocabulary.spoken`, via the `base+dialect` key |
| `revenue` | annual revenue, in the archetype's currency unit | the builder's `annual_revenue`, which every money fact derives from |
| `employees` | the company's stated headcount | the builder's `employees`; see the caveat in refusals.md |
| `geo` | the jurisdiction | `locales.named`, plus a pack's geography |
| `facets` | what the company *is* | `facets.resolve` |
| `physics` | ranges the engine draws inside | `parameters.overrides_from` |
| `calendar` / `estate` | the trading year, the landscape size | `profiles.named`, the estate profiles |
| `policies` | standing documents the company *has* rather than produces: `core` or `full` | `worldloom.policies`. Without it, an assistant asked what the approval threshold is finds nothing, because the company has no written rules |
| `organisation` | headcount, span, levels, functions, and `divisions`, how many lines of business | `roles.from_shape` → `roles.review`; divisions via `worldloom.divisions`: the knob corpus size actually follows, because the close fans out per division, not per employee |
| `leadership` | roles the engine's table does not have | rows appended to that table, never substituted |
| `master_data` | reference tables to mint at build: counts for vendors, customers, skus | `generators/masterdata.py`, opt-in; the recipe records the counts and replay re-mints the rows |
| `identity` | company name, HQ, regions | `packs.Pack` |
| `pack` | an authored pack, used whole | `packs.load`, and it wins over everything |
| `rivals` | named competitors, as a **list** of names | reported as `unmet`, one per rival; see refusals.md. A bare string is iterated per character, so always pass a list |
| `about` | prose for whoever reads the document next | read by nobody |

## Values, ranges, and which you may write

*If the engine draws it, you may only narrow it. If the engine reads it, you
may only choose from what is registered.*

- **Values**: archetype, engine, vocabulary, geo, calendar, estate, revenue,
  employees, role rows, company name. Each is checked against the registry
  that owns them. An unknown one is refused, never defaulted, because a spec
  that asked for `germay` and silently got Australia builds a corpus with
  nothing in it to notice the drop by.
- **Ranges**, everything in `physics`, may name only parameters
  `worldloom pack params` lists. That closure is not fussiness: a generator
  asking for a parameter nobody registered raises part-way through an episode.
- **Open** (`industry`, `about`, a span's `source`) is free text read by
  nobody.

## Identity: the boundary is `company_name`

A **pack** is identity: a company's name, its divisions, their books, its
voices, embedded in the corpus recipe verbatim, because the pack *is* how the
world was made. `pack export` marks every identity field `PLACEHOLDER` because
nothing derived can honestly supply them.

A **specification** is a description. It names no company, and it is embedded
not at all: it resolves to consequences and the recipe records those, so the
corpus replays after the registries move underneath it.

They meet in one direction. Supplying `identity.company_name` composes a pack:
units and scale off the resolved archetype, geography off the locale, the name
off you. That composition is the only route a `geo` has to the build half.
Naming a `pack` instead uses it whole, and it wins over everything derived.
Naming both is refused.
