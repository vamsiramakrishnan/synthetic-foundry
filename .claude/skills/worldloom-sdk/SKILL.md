---
name: worldloom-sdk
description: Write Python against Worldloom instead of driving its CLI — compose blueprints, cross and disperse them, build many worlds in a loop, and filter on what came out. Use when a corpus request needs an arrangement no single command expresses: several organisation shapes crossed with several calendars, a sweep of one parameter, keeping only the worlds whose blast radius exceeds some number, or anything where the answer is a comprehension rather than a flag.
---

# Worldloom as a library

The CLI is a set of **fixed pipelines**. `worldloom mosaic -n 5` is one
arrangement of the machinery; `build` is another. Wanting a different one — five
organisation shapes crossed with three trading calendars, each run for six
periods, keeping only the ones whose dependency graph is deep enough to be worth
asking about — means a new flag, a new command, or a shell script gluing JSON
between processes.

You write Python. Use it.

```python
from worldloom import sdk
```

## Everything is a value until you say `build()`

A `Blueprint` describes a world that does not exist yet. Every method returns a
new one, so a half-configured blueprint is a perfectly good thing to hold:

```python
base = sdk.retail().org(levels=4).calendar("harvest")
field = [base.org(headcount=n, span=s) for n, s in ((18, 4), (31, 8), (25, 6))]
worlds = [b.build().episodes("2026-01", periods=3) for b in field]
```

`sdk.company(name)` is the registry-driven front door (`retail`, `banking`,
`insurance`, `procurement`, or anything installed). `sdk.retail()`,
`sdk.banking()`, and `sdk.insurance()` remain conveniences for existing callers.
Then:

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

`.describe()` returns what a blueprint says without building it. Use it to
decide whether forty worlds are worth the wait, before generating forty worlds.

## Three loop shapes, and one of them is the interesting one

```python
sdk.cross(base, calendar=["flat", "harvest"], estate=["small", "large"])   # 4
sdk.sweep(base, "calendar", ["flat", "harvest", "fiscal_year_end"])        # 3
sdk.dispersed(candidates, 8)                                              # the 8 least alike
```

**`dispersed` is the one people get wrong.** A cartesian product of six axes is
46,656 worlds and nobody wants those; they want the eight least alike. Taking
the *first* eight of a product gives you eight that differ only in the last
axis, because that is what a product's ordering does. `dispersed` is a
farthest-point traversal over normalised coordinates — the same algorithm
`mosaic` uses — so the eight actually cover the space.

Normalising matters and is done for you: headcount runs to forty and a margin
runs from 0.2 to 0.6, so unnormalised, headcount would decide entirely what
"unlike" means.

## Measure, then filter — that is the point of a loop

```python
rich = [
    w for w in (b.build() for b in field)
    if w.measure()["chokepoints"] >= 10 and w.ok
]
```

`Built.measure()` gives people, titles, facts, artifacts, evaluations, graph
nodes, chokepoints and longest chain. `Built.topology()` is the graph subset.
`Built.ok` is the coherence gate. `sdk.built(blueprints)` builds lazily, so a
loop that stops early does not mint the rest.

Then `.export(path)` or `.render("xlsx", "docx", out=path)`.

## Bridges to what already exists

```python
sdk.mosaic_of(5, engine="banking")     # a dispersed field, as blueprints
sdk.probe_of(session, 5)               # a model-derived space, as blueprints
```

Both return blueprints rather than worlds, so a mosaic's field can be further
constrained, filtered, or crossed with something else before anything is built.

## What this does not do

It relaxes **no invariant**. A blueprint still refuses a role table missing a
key the engine looks up by name, physics that would close the held-versus-central
gap the insurance vertical exists to pose, or an organisation whose headcount,
span and depth cannot all hold at once. The freedom here is in *arrangement*.
The constraints are what make an arrangement worth building — a loop that could
emit incoherent worlds would be a slower way to get noise.

If a blueprint is refused, read the error: they name the rule and usually the
arithmetic. Do not work around one by loosening a check.

## When to use the CLI instead

For a single world, one command, or a shell pipeline: `worldloom build`,
`worldloom mosaic`, `worldloom render`. The CLI is the right tool when the
arrangement is one the command already expresses. Reach for the SDK the moment
you find yourself wanting a loop, a filter, or a product.
