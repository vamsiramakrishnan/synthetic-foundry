---
name: worldloom-company
description: Describe a company once, in one document, instead of assembling it from nine flags — industry, geography, revenue, size, margins, listing, competition, leadership — and let the description be refused when it contradicts itself. Use when a corpus has to be a *particular* kind of business ("a listed mid-size German insurer, thin margins, fragmented market"), when you find yourself reaching for --facet and --locale and --physics and --pack in one command, or when asked whether Worldloom can express some attribute of a company.
---

# One document that says what kind of company this is

Nine surfaces answer that question. An archetype key says what the business
sells; `--employees` says how many people it has; `--facet` says whether it is
listed; `--locale` says which jurisdiction spells its figures; `--estate` says
how much technology it runs; `--physics` says what its margins are; `--pack`
says what it is called; a vocabulary qualifier says what its divisions are
called; and revenue can only be said by writing a pack.

Each is right on its own. Between them they ask you to know which of nine
places every clause of "a listed mid-size German insurer on thin margins in a
fragmented market" belongs to — and two of them interact in a way nobody
predicts: naming *any* facet settles *every* facet at its registry default, so
`--facet listing=listed` alone also asserts a flat trading year, replacing the
engine's 21% December.

```bash
worldloom pack spec                  # the schema, and which registry each field draws on
worldloom pack spec --template       # a starter, filled in rather than blank
worldloom build --spec company.json --seed 8128 --out ./corpus
```

## The document

```json
{
  "about": "A listed mid-size German general insurer in a fragmented broker market.",
  "industry": "General insurance",
  "geo": "germany",
  "facets": {"listing": "listed", "competition": "fragmented",
             "maturity": "legacy", "trading_pattern": "steady"},
  "organisation": {"headcount": 26, "span": 5, "levels": 3},
  "leadership": [{"key": "chief_underwriting",
                  "title": "Chief Underwriting Officer",
                  "function": "Executive", "reports_to": "ceo"}],
  "identity": {"company_name": "Rheinmark Versicherung",
               "headquarters": "Munich, Germany"}
}
```

| field | what it says | the seam it resolves into |
|---|---|---|
| `industry` | prose | `archetypes.inspired_by` — the same table `--inspired-by` uses |
| `archetype` | a registered shape by key | `archetypes.get` |
| `engine` | which vertical runs the episode | `domains.by_name` |
| `vocabulary` | what the divisions are *called* | `vocabulary.spoken`, via the `base+dialect` key |
| `revenue` | annual revenue, in the archetype's currency unit | the builder's `annual_revenue` |
| `employees` | the company's stated headcount | the builder's `employees` — read the caveat below |
| `geo` | the jurisdiction | `locales.named`, plus a pack's geography |
| `facets` | what the company *is* | `facets.resolve` |
| `physics` | ranges the engine draws inside | `parameters.overrides_from` |
| `calendar` / `estate` | the trading year, the landscape size | `profiles.named`, the estate profiles |
| `organisation` | headcount, span, levels, functions | `roles.from_shape` → `roles.review` |
| `leadership` | roles the engine's table does not have | rows appended to that table |
| `identity` | company name, HQ, regions | `packs.Pack` |
| `pack` | an authored pack, used whole | `packs.load` — and it wins over everything |

**It is a composer, not an engine.** Nothing above is a capability the flags
lack. What the document adds is that the pieces are resolved *together*.

## Values, ranges, and which you may write

*If the engine draws it, you may only narrow it. If the engine reads it, you
may only choose from what is registered.*

- **Values** — archetype, engine, vocabulary, geo, calendar, estate, revenue,
  employees, role rows, company name — are checked against the registry that
  owns them. An unknown one is refused, never defaulted, because a spec that
  asked for `germay` and silently got Australia builds a corpus with nothing in
  it to notice the drop by.
- **Ranges** — everything in `physics` — may name only parameters
  `worldloom pack params` lists. That closure is not fussiness: a generator
  asking for a parameter nobody registered raises part-way through an episode.
- **Open** — `industry`, `about`, a span's `source` — is free text read by
  nobody.

## What it refuses, and with what

Read the refusal. Each one names the arithmetic, and none of them is a matter
of taste.

```
revenue/employees: implausible_productivity — 40,000,000 thousands of revenue
across 12 employee(s) is 3,333,333,333 per head. The shapes this engine knows
run 18,510 to 2,712,000 per head — that is the omnichannel_retailer and the
midsize_general_insurer extremes, each widened by the factor the registry
itself spans. No company is both of the numbers you gave.
```

The envelope is **computed from the archetype registry**, not typed in: four
registered shapes state a revenue and a headcount at the same time and nothing
else in the project does (`parameters.DEFAULTS` has no opinion —
`generators/finance` never consults headcount). Register a fifth archetype and
the envelope moves on its own.

The other refusals are composed rather than restated:

- `facets.resolve` on an empty intersection — *a mutual runs 16-26% margin and
  a premium brand 48-62%, and no company is both.*
- `roles.from_shape` on headcount, span and depth — three numbers with two
  degrees of freedom.
- `roles.review` on the finished table — a missing spine key, a reporting
  cycle, a role with no title.
- `organisation.headcount > employees` — a corpus cannot name more people than
  the company employs.

Every conflict comes back at once, not the first one.

## What it reports rather than dropping

`unmet:` lines are the honest half, the same channel a facet's `wants` uses.
They are evidence, not warnings:

- **A trading year on an engine that has no field for one.** Only
  `RetailWorld` carries `seasonality`. Asked of the registered class, so a
  fourth vertical answers for itself.
- **A margin band on a vertical that never draws from it.** `retail.margin.*`
  is retail's; an insurer's economics have their own names.
- **A `geo` with no identity to carry it.** A locale has two halves. The figure
  grammar rides the recipe always. The people, the site regions and the head
  office reach `organisation.generate` through a pack's
  `name_pools`/`regions`/`headquarters` — so a description that names Germany
  and no company gets German digits and Australian staff, and is told so.
- **A named rival.** Nothing here mints an entity for a company that is not
  this one, and lore asserting one would constrain no consulted target. Say
  what the market *does* to pricing with `facets: {"competition": …}`, which is
  load-bearing.

## Identity: the boundary is `company_name`

A **pack** is identity — a company's name, its divisions, their books, its
voices — embedded in the corpus recipe verbatim, because the pack *is* how the
world was made. `pack_export` marks every identity field `PLACEHOLDER` because
nothing derived can honestly supply them.

A **specification** is a description. It names no company, and it is embedded
not at all: it resolves to consequences and the recipe records those, so the
corpus replays after the registries move underneath it.

They meet in one direction. Supplying `identity.company_name` composes a pack —
units and scale off the resolved archetype, geography off the locale, the name
off you — and that composition is the only route a `geo` has to the build half.
Naming a `pack` instead uses it whole, and it wins over everything derived.
Naming both is refused.

## In Python

```python
from worldloom import sdk, company

blueprint = sdk.described({"industry": "general insurance", "geo": "germany",
                           "facets": {"listing": "listed"}})
built = blueprint.build().episodes("2026-03")

resolution = company.resolve(company.from_document("company.json"))
resolution.ok, resolution.unmet, resolution.as_dict()
```

`sdk.described` returns an ordinary `Blueprint`, which is the point: cross it,
sweep it, disperse it, filter on what came out. `company.resolve` is the same
resolution with its `unmet` list intact when you want to read what a
description committed to and the engine did not honour.

## When not to use it

For one world with one unusual attribute, the flag is shorter and clearer:
`worldloom build --facet maturity=legacy` says one thing and says it well.
Reach for a specification when you are describing a *company* rather than
setting a knob — when three or more of the nine surfaces are involved, when the
answer has to be handed to somebody else to read, or when you want the
description refused before it becomes a corpus.

For deriving *ranges* you cannot argue from a label — how long this
organisation takes to find the cause of an outage — use `worldloom probe`
(`.claude/skills/worldloom-probe/SKILL.md`) and paste its resolved physics into
the specification's `physics` block. The two compose: a probe argues the
numbers, a specification says what kind of company holds them.
