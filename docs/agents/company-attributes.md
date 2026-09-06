---
title: Company attributes
description: Claim one attribute at a time (facets, messiness, locale, timeline) and keep a derived world.
read-when: Reaching for --facet, --messiness, --locale, --timeline, or keeping a mosaic or probe result.
tags: [facets, messiness, locale, timeline, pack-export]
---

# Saying what kind of company it is, one attribute at a time

The four flags below are the difference between "a corpus" and "the corpus you
were asked for". Each is a no-op when omitted, so every corpus already built is
byte-identical, and each rides the recipe, so a corpus built with them rebuilds
itself with none of them on the command line.

```bash
worldloom pack facets                      # the dimensions, and what each value commits to
worldloom pack messiness                   # how well the archive is kept
worldloom pack locales                     # jurisdictions, and which half of one a build reaches
worldloom pack landscapes                  # what an estate is called, per vertical

worldloom build --facet listing=listed --facet maturity=legacy --seed 8128 --out ./corpus
worldloom build --locale germany --messiness lived_in --seed 8128 --out ./corpus
worldloom build --periods 12 --timeline turbulent --seed 8128 --out ./corpus
```

## `--facet`

**`--facet`** says what the company *is* rather than what it has. A `Pack` is a
closed schema of twenty fields, each threaded by hand into a generator, so
"listed" could only ever have been a boolean nothing read. A facet is instead a
claim that emits **consequences into vocabularies that already exist**:
parameter ranges, lore, roles, a trading year, an estate size. So `listed`
mints an audit committee chair and a head of investor relations, raises
status-report density, and puts the audit committee in the filing approval
chain. Know two consequences of that before you use it:

* Naming *any* facet settles *every* facet at its registry default. That is what
  makes claims composable, and it means `--facet listing=listed` alone also
  asserts `trading_pattern=steady`, a flat year replacing the engine's 21%
  December. Say `--facet trading_pattern=christmas_peak` to keep it.
* Contradictory claims are refused naming both, with the arithmetic where there
  is any: a mutual runs 16-26% margin and a premium brand 48-62%, and no company
  is both. `worldloom pack facets` prints every exclusion before you hit one.

The recipe records the **consequences**, never the facet names, and that is the
stronger of the two: consequences replay this world byte-for-byte after the
registry moves under it, where a stored `listing=listed` would replay whatever
`listed` came to mean later while reporting success. What a facet implies and
nothing implements (an analyst consensus, a regulator with a pricing
determination) is printed as `unmet:` rather than dropped, the same evidence a
probe's unbound leaf is.

Facet **lore** is not in that category. `world.extend_lore` mints it into the
domain's own lore before the organisation is generated, because lore is an
*input*: it dates the business units, attaches persona traits, and decides how
much status reporting a close produces. The recipe records the **claims** it was
minted from, under `lore_claims`, rather than the finished commitments, whose
ids and dates belong to the world they landed in. So a faceted corpus rebuilds
into itself.

## `--messiness`

**`--messiness`** grades how well the archive is kept: `pristine`, `well_run`,
`lived_in`, `neglected`. Every corpus so far has been almost perfectly kept, and
only half of that was ever a promise anything depended on: *no document may
contradict the ledger*, which does not change. That every document is also
current, correctly quoted, and owned by somebody still employed was never
promised and is not realistic. What keeps this a corpus rather than noise is
that **every imperfection is recorded**: a reader holding only the corpus can
establish mechanically that the stale page is stale and what the current
position is. Three kinds ship: a document that missed a correction it
postdates, two live documents disagreeing with a ledger that says which is
right, and an author who has left with nobody named in their place. Counts are
a budget, not a quota: a
small world has fewer corrections to be stale about and the pass takes what it
can support.

## `--locale`

**`--locale`** puts the corpus somewhere. It reaches the *figure grammar*,
corpus-wide, so the DOCX, the Markdown, the PPTX and the retrieval index all
spell one number one way: `1.234,50` and `-1.234` in Germany, where before
every corpus printed `1,234.50` and `(1,234)` whatever its pack said. And it
reaches the *build*: the region labels in every site name, the pools the people
are drawn from, the headquarters city, the currency and the fiscal year. Claim
Frankfurt and you get Katharina Kirchgässner in Berlin at `Supermarket BW 001`.
A pack's own `name_pools`, `regions` and `headquarters` still win over the
locale's, the same precedence `Pack.regions` has always had.

The **working week** arrives too. August 2026 ends on a Monday, and four
working days later is Friday the 4th in Sydney and Sunday the 6th in Manama,
because the Gulf week runs Sunday to Thursday and has already spent its
weekend. The retail close, the bank's LCR observations and the insurer's
reserving dates all step on the corpus's own calendar.

## `--timeline`

**`--timeline`** replaces repetition with a history. `--periods 6` runs six
closes signed by the same twenty-three people, drawn from the same distribution:
one month photocopied. A density (`quiet`, `steady`, `turbulent`) schedules
incidents and org changes across those periods instead, so a controller who
departs in period 2 means periods 3-6 are signed by their successor, an incident
in period 3 and not period 4 makes "which month went wrong" answerable, and a
reorganisation moves who reports to whom *inside one corpus*.

```
worldloom build --periods 12 --timeline turbulent
  → 2026-03 MonthEndClose, Reorganisation · 2026-06 MonthEndClose, Departure
    · 2026-10 MonthEndClose, Departure · 2026-12 MonthEndClose, Reorganisation …
```

It is a flag rather than a command, and the reason is the recipe. Every scenario
a timeline can hold already records itself through its own `with_step`, so a
sampled history rebuilds from the steps it wrote, with no new recipe verb and
nothing added. A `worldloom timeline` command applied to a built corpus would be a
second build path whose steps the recipe already describes, which is two
accounts of one history. So: `--periods` says how many, `--timeline` says what
happens between them.

Three refusals, each stated rather than silently absorbed. The schedule states
incidents in *both* directions once it schedules any, so `--incident` and a
non-`quiet` density cannot both decide. `--actors` is refused, because an
episode resumed from the ledger is driven one decision at a time and a history
is decided before the first one is taken. And the single-episode verticals are
refused, because their scenario takes no incident flag at all: a scheduled
incident would be dropped on the floor and the corpus would be `--periods N`
wearing a history's name. Hires are not sampled either: a new post's title is a
business decision, and a sampler inventing one would write the least plausible
sentence in the corpus.

## Keeping a derived world

`mosaic` and `probe` both answer "what kind of company is this?" and neither
answer survives the command that produced it. `worldloom pack export` turns one
into an artifact that travels:

```bash
worldloom pack export ./kept --world 3 -n 5        # a mosaic world, kept
worldloom pack export ./kept --probe probe.json    # a settled probe's physics, kept
worldloom pack check ./kept/pack.json
worldloom build --pack ./kept/pack.json --physics ./kept/physics.json --out ./corpus
```

What comes out is a **bundle, not a pack**. A pack is texture: a name, units,
books, lore, voices. A variant and a probe are physics and shape. So it writes
`pack.json` plus the sidecars a pack is not allowed to hold (`physics.json` for
`build --physics`, `shape.json` for the org table and estate that have no pack
field at all), rather than widening `Pack` with a physics block and giving a
build two ways to say one thing. Identity fields come out `TODO`-marked and
`pack check` names every one: neither a Halton coordinate nor an interval graph
knows what the company is called, and a name invented there would be signed with
your own.
