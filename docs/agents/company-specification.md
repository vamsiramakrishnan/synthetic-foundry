---
title: Company specification
description: Describe a company in one refusable document, size it by divisions, or author an industry pack.
read-when: A corpus must be a particular kind of business, or the industry is not retail or banking as shipped.
tags: [spec, archetypes, divisions, industry-packs, verticals]
---

# Saying what kind of company it is, in one document

Nine surfaces answer "what kind of company is this?" — an archetype key,
`--employees`, a `--facet`, `--locale`, `--estate`, a `--physics` file, a
`--pack`, a vocabulary qualifier, and revenue, which can only be said by
writing a pack. Each is documented in its own topic file and each is right;
between them they require you to know which of nine places each clause of a
sentence belongs to, and two interact in a way nobody predicts.

A **company specification** is that sentence as one document:

```bash
worldloom pack spec                        # the schema, and which registry each field draws on
worldloom pack spec --template             # a starter you can edit
worldloom build --spec company.json --seed 8128 --out ./corpus
```

```json
{
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

It is a **composer, not an engine**. Every field resolves into a seam that is
already load-bearing — `archetypes.get`, `vocabulary.spoken`, `facets.resolve`,
`parameters.with_overrides`, `roles.from_shape`, `locales.named`, `packs.Pack` —
so it adds no capability the flags lack. What it adds is that the pieces are
resolved *together*, and three things follow from that:

* **It refuses a description that contradicts itself, with the arithmetic.**
  "40bn of revenue across twelve employees" is refused naming both numbers and
  the registered shapes that bound them — the envelope is computed from the
  archetype registry (97,500 to 514,286 per head, widened by the factor the
  registry itself spans) rather than typed in, so registering a fifth archetype
  moves it. Premium margins in a fragmented market is refused by
  `facets.resolve`'s own empty-intersection arithmetic; an over-determined
  headcount/span/depth by `roles.from_shape`'s.
* **It reports what it cannot honour, rather than dropping it.** A trading year
  on an engine whose world builder has no `seasonality` field; a margin band on
  a vertical whose generators never draw from `retail.*`; a `geo` with no
  identity to carry its people and regions; a named rival, which nothing here
  mints an entity for. Same `unmet:` channel a facet's `wants` uses, and for
  the same reason.
* **It is never recorded.** A pack is embedded in the recipe verbatim, because
  the pack *is* how the world was made. A specification resolves to
  consequences and the recipe records *those*, exactly as `--facet` records
  consequences rather than facet names — so the corpus replays byte-for-byte
  after the facet registry, the archetype table or the locale presets move
  underneath it.

**A specification is not a pack, and the boundary is `company_name`.** A pack
is *identity*: a company's name, its divisions, their books, its voices, and
`pack_export` marks every one of those `PLACEHOLDER` because nothing derived
can honestly supply them. A specification is a *description* — true of a class
of businesses, naming no company at all. Supplying `identity.company_name` is
what lets a description compose *into* a pack, which is how a description names
the company at all — a `geo` reaches the people, the site regions and the head
office on its own, through `--locale`. Naming a `pack` instead uses it whole, and the
pack then wins over everything derived — the same precedence `Pack.regions`
already has over a locale's pool.

`--spec` refuses the flags it subsumes (`--archetype`, `--inspired-by`,
`--pack`, `--employees`, `--facet`, `--physics`, `--locale`, `--estate`) rather
than merging with them. `--seed`, `--periods`, `--incident`, `--messiness`,
`--timeline` and the formats are untouched: the specification says what the
company *is*, and those say what happens to it.

In Python the same surface is `sdk.described(document)`, which returns an
ordinary `Blueprint` — so a description can be crossed, swept and dispersed
like any other.

## How big the company is, which is not how many people it has

`organisation.divisions` is the field that makes a corpus bigger, and the
measurement says why. Raising `organisation.headcount` from 23 to 429 left
facts at 8,021, artifacts at 204 and evaluation cases at 596 — every one of
them unchanged, because 429 people were still managing the same three
divisions. The close fans out per division and per category, so the document
count follows the *structure*. Widening the same retailer from three divisions
to eight took facts from 604 to 990 and questions from 42 to 52 on the same
seed.

```json
{"archetype": "omnichannel_retailer",
 "organisation": {"headcount": 420, "span": 8, "levels": 6, "divisions": 8}}
```

A division arrives from `worldloom.divisions.POOLS`, keyed by industry, and it
is a real line of business rather than a relabelling — its own categories, its
own site formats, therefore its own row in every unit-level table, its own
close commentary and its own questions. Widening is additive: the archetype's
declared divisions keep their names, their categories and their *relative*
sizes, so 64/21/15 stays in that ratio however many arrive. Only the shares
renormalise, because a share is a fraction of group revenue and a fourth
division has to take something from somebody. Each addition is sized against
the company's *smallest* declared division and declines from there — equal
shares were the first rule and they gave Property a 12.5% share against
General Merchandise's 7.9%, an adjacent business outweighing the core it was
bolted onto.

It refuses rather than improvises in three places: narrowing below what the
archetype declares (that would silently remove every fact, document and
question a division owned), running out of pool (named with how many are
available, because a division called `Division 7` tells a reader the company is
synthetic without telling them anything else), and an industry with no pool at
all. `divisions.register` adds a pool for a fourth vertical.

The width rides the **archetype key** — `omnichannel_retailer+8div`, composing
with the vocabulary qualifier as `omnichannel_retailer+wholesale_club+8div` —
for the reason `vocabulary.spoken` qualified its own key: the key is the only
thing a recipe records about the shape, so a width carried anywhere else would
rebuild a three-division company from an eight-division corpus and report
success.

The same principle decides the other three verticals, and it is worth knowing
which way round it works before reaching for a flag. Structure only makes a
corpus bigger where something *reports* on the structure. Banking, insurance and
procurement each declared a full organisation that no fact named and no document
carried — 243 sites, 9 business units and 6 cost centres between them — so
widening any of them changed nothing, and their corpora were 52 to 62 facts
against retail's 588. Now that their estates carry facts, one period of banking
is 744 and three is 2,220.

`validate.reachability` is the reading that answers this for a corpus you have:
it reports declared entities that no compiled document says anything about, per
kind, and an entity kind it names is a knob that will not turn. It is not part
of `worldloom validate`, because what it reports is true and is not a statement
about coherence.

## An industry that is neither retail nor banking

For an industry that is neither retail nor banking as shipped, author an
**industry pack** — a JSON file carrying the company's shape, lore, and name,
run through one of the two engines. `worldloom pack template <engine>` starts
one, `worldloom pack targets <engine>` lists which lore is load-bearing,
`worldloom pack check` lints yours, and `worldloom build --pack pack.json`
builds it. The pack embeds in the corpus recipe, so a pack-built corpus
rebuilds byte-for-byte with no pack file on hand. Reference packs live in
`examples/packs/`.

The default build is the retail month-end close. `--archetype midsize_adi`
builds the banking vertical instead: a quarterly capital return that is
challenged by the second line, filed anyway under a lodgement norm, invalidated
by a reconciliation break the daily liquidity cadence catches, and corrected by
a *restatement* — a new lodgement that leaves the original on the record, which
is the one thing `revises` and `supersedes` both may not do. Same loop from
step 1b on; the retail-only flags (`--incident`, `--comparatives`, `--actors`)
are refused rather than ignored. `--periods` still applies — `N` consecutive
quarters, each one a `QuarterlyCapitalReturn` chained onto the last, stepping
three months at a time rather than retail's one.
