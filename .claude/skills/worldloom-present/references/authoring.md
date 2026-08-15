# Authoring a profile: overrides, what the lint refuses, the Python cascade, and what replays.

## The document

`assets/profile.json` is a complete starter. The override block is the reason
this is a document and not four flags:

```json
"overrides": { "incident_rca": { "appendix": "append" } }
```

A knowledge article wants no citations on the page and the RCA sitting beside
it in the same corpus is read by an engineer who needs them. Without overrides
the only way to say that is two corpora.

## What the lint refuses

Every finding at once, as sentences to act on:

- A knob set to a value outside its vocabulary — the finding names the value
  and the allowed set. A *misspelled knob* (`appendx`) is refused by name too,
  but earlier and alone, at parse: the seed forbids unknown fields, so a typo
  can never be a silent no-op.
- An override on a doctype the corpus does not mint (checked when `--corpus`
  is given, which is why you pass it) — a rule that silently does nothing is
  the failure mode a typo produces.
- Any `scaled` setting whose rescaled figures cannot round-trip to the ledger
  figure exactly. The comparison is exact, never within-epsilon: a tolerance
  would be the lint deciding how much of a figure a reader may lose.
- A name already registered with different settings — a corpus that asked for
  that name before must still get what it asked for.

## In Python

```python
from worldloom import presentation

profile = presentation.accept("profile.json", doctypes=corpus_doctypes)   # load → lint → refuse-or-register
world = world.extend(recipe=recipe.with_presentation(world.recipe, profile))
world.render("docx", "pdf")
```

## What replays

The profile is written onto the **recipe**, by value and never by name — the
same seam `locale` rides, and for the same three reasons: the recipe is the
only singular document a corpus has, so two artifacts cannot disagree; it
survives the round trip to disk; and it replays. By value rather than by name
because a name is a reference into a registry a later checkout may have
changed, and a rebuild that resolved `"house"` against somebody's edited
profile would produce different documents and report success.
