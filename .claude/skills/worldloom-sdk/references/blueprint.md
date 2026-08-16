---
title: Blueprint Methods
description: Compose a Blueprint beyond seed, org and calendar — every builder method and what it sets.
read-when: Composing a blueprint beyond seed, org and calendar.
tags: [worldloom, sdk, blueprints, python, refusals]
---

# Blueprint composition — every builder method and what it sets

Everything is a value until you say `build()`: each method returns a new `Blueprint`, and
`.describe()` returns what one says — engine, seed, shape, calendar, physics,
facets — without building it.

`sdk.company(name)` is the registry-driven front door (`retail`, `banking`,
`insurance`, `procurement`, or anything installed). `sdk.retail()`,
`sdk.banking()`, and `sdk.insurance()` remain conveniences for existing callers.

| method | what it sets |
|---|---|
| `.seeded(n)` | the world seed |
| `.org(headcount=, span=, levels=, functions=)` | the organisation's shape — partial, so `.org(span=8)` leaves the rest |
| `.calendar(name)` | trading year (`flat`, `harvest`, `fiscal_year_end`, `southern_summer`, `retail_christmas`) |
| `.estate(size, vocabulary=)` | technology landscape: `small`/`medium`/`large` |
| `.physics(retail_margin_erosion=(0.10, 0.15))` | any registry range; underscores stand for dots |
| `.staff(n)` | the company's stated headcount, which is not the same claim as how many people the corpus names |
| `.revenue(n)` | annual revenue in the archetype's own currency unit |
| `.located(locale)` | the jurisdiction and corpus-wide figure grammar |
| `.facets(listing="listed", maturity="legacy")` | operational company claims and their implemented consequences |
| `.master_data(vendors=, customers=, skus=)` | deterministic relational reference tables |
| `.pack(source)` | authored identity, shape, lore, voices and geography |
| `.lob(spec, bind=...)` | an authored line of business and process-slot bindings |
| `.archetype(key)` | a specific archetype rather than the domain's default |

Bad names are refused at the call, not at build: an unknown calendar or locale
raises immediately with the known set in the message, so a field of forty
blueprints cannot get thirty-nine worlds deep before discovering a typo.

Refusals at `build()` are the engine's own — a role table missing a key the
engine looks up by name, physics that would close the held-versus-central gap
the insurance vertical exists to pose, an organisation whose headcount, span
and depth cannot all hold at once. Read the error: it names the rule and
usually the arithmetic. Do not work around one by loosening a check.
