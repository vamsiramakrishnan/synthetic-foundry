# Fields, dispersion, and measuring what came out

Load this when arranging many worlds: products, sweeps, dispersed selection,
and the measure-then-filter loop that justifies building any of them.

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
`Built.search`, `Built.mutated` and `Built.twin` close the loop on a built
world — see `references/corpus-loop.md`.
`Built.ok` is the coherence gate. `sdk.built(blueprints)` builds lazily, so a
loop that stops early does not mint the rest.

Then `.export(path)` or `.render("xlsx", "docx", out=path)`, and
`.episodes(start, periods=n)` to run the episode over periods.

## Bridges to what already exists

```python
sdk.mosaic_of(5, engine="banking")     # a dispersed field, as blueprints
sdk.probe_of(session, 5)               # a model-derived space, as blueprints
```

Both return blueprints rather than worlds, so a mosaic's field can be further
constrained, filtered, or crossed with something else before anything is built.
