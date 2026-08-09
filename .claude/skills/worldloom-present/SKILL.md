---
name: worldloom-present
description: Decide who a Worldloom corpus's documents are for, and author a presentation profile through a refusable lint — whether the supporting-fact appendix prints, where the author's voice goes, how a money figure is spelled, and how a PDF table sizes its columns. Use when a corpus's documents will be read by a person rather than checked by a validator, when a demo or a filing pack needs the traceability scaffolding off the page, or when asked why a rendered memo looks like a machine wrote it.
---

# Presenting a corpus

Every artifact here is two things at once. It is a **traceability record** —
which facts a passage cites, at what authority, valid from when, in whose voice
it was asked for. And it is a **document** — something a person opens. The
renderers were written for the first reading, so left alone the second one
leaks: a CFO variance memo renders to five PDF pages of which four are a fact
table, and its last line is the generation brief (`Author voice: precise,
procedural, cautious.`) printed inside the artifact it briefed.

Neither reading is more correct, which is why this is a decision you make and
not a default somebody picked. An evaluation corpus wants every citation on the
page. A demo wants none of it. A filing pack wants them in a separate file.

## The one rule

**A profile decides how a value is shown. It may never change the value.**

That is enforced, not asked for: `magnitudes: scaled` is refused unless every
rescaled figure multiplies back to the ledger figure exactly. And nothing a
profile omits is *lost* — `artifact-ir.jsonl` keeps every section, every
`fact_ids` list and every voice under every profile. A reader profile declines
to print them; it does not decline to record them. So omitting is safe, and the
lint that matters is about arithmetic.

## Start here

```bash
worldloom present describe                  # every profile and knob, rendering nothing
worldloom render ./corpus -f docx -f pdf --profile reader
```

Three profiles ship:

| | `audit` | `reader` | `filing` |
|---|---|---|---|
| `appendix` | `append` | `omit` | `sidecar` |
| `provenance` | `footer` | `properties` | `properties` |
| `magnitudes` | `ledger` | `scaled` | `scaled` |
| `table_fit` | `fixed` | `measured` | `measured` |

`audit` is the default and is byte-for-byte what every corpus rendered before
this layer existed got. It is not a legacy setting — it is the right profile
for a corpus whose reader is a validator.

What the knobs do:

- **`appendix`** — what becomes of a section the IR flagged `hidden` (the
  supporting-facts tables). `append` prints it with a note saying it is not
  part of the readable surface; `omit` drops it from the document; `sidecar`
  drops it and writes `<artifact>.citations.md` beside the document instead.
- **`provenance`** — where the author's voice and persona go. `footer` puts
  them in the document; `properties` writes them to the file's own metadata
  (Word and PowerPoint category, where a tool can read them and a reader cannot
  see them); `omit` drops them from the file entirely. Markdown has no metadata
  container, so `properties` and `omit` are the same there.
- **`magnitudes`** — `ledger` spells a money figure exactly as the fact states
  it (`AUD 5,372,800 thousands`); `scaled` promotes it to the largest magnitude
  that is still *exact* (`AUD 5,372.8m`). Never a rounding: a figure with no
  shorter exact spelling keeps the ledger wording.
- **`table_fit`** — `fixed` divides a PDF table's frame evenly; `measured`
  sizes each column to its widest unbreakable token and shrinks the type if
  even that will not fit. On the shipped fact table `fixed` produces 112
  mid-token line breaks — `system_of_recor`/`d`, a timestamp split as
  `2026-04-07T16:4`/`0:00+00:00` — and `measured` produces none.

## Authoring your own

Use the cascade when none of the three fits — most often because one doctype in
the corpus needs different treatment from the rest.

```bash
worldloom present brief ./corpus -o brief.json    # knobs, vocabularies, this corpus's doctypes
# write profile.json
worldloom present lint profile.json --corpus ./corpus
```

```json
{
  "name": "house",
  "appendix": "omit",
  "provenance": "properties",
  "magnitudes": "scaled",
  "table_fit": "measured",
  "about": "What we hand to a customer. Citations recorded, never printed.",
  "overrides": {
    "incident_rca": { "appendix": "append" }
  }
}
```

The override is the reason this is a document and not four flags: a knowledge
article wants no citations on the page and the RCA sitting beside it in the
same corpus is read by an engineer who needs them. Without overrides the only
way to say that is two corpora.

`lint` returns **every** finding, not the first — fixing one knob per round trip
is a turn paid per rule you could not see. It refuses an unknown knob by name
(`appendx` is a finding, never a silent no-op), an override on a doctype the
corpus does not mint, and any scaling that cannot round-trip.

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

Re-rendering an existing corpus under a second profile needs **no rebuild** and
is a supported thing to do — unlike `locale`, a profile decides nothing about
the world. Same facts, same prose, same IR, different presentation.

## Checking your work

Read the file, do not trust the flag:

```bash
worldloom render ./corpus -f pdf --profile reader
python -c "from pypdf import PdfReader; print(len(PdfReader('corpus/artifacts/art-0003-cfo-variance-memo.pdf').pages))"
```

Two things worth checking by eye, because a lint cannot:

1. **Does a figure read like a memo?** `AUD 5,372.8m` does; `AUD 5,372,800
   thousands` does not. If prose still reads the second way under a `scaled`
   profile, the figure has no shorter exact spelling and the ledger wording is
   the honest answer.
2. **Does anything in the document address its own generator?** Phrases like
   "not part of the readable surface" or "resolved before prose" are the
   harness talking to itself. Under `reader` they should be gone; if one
   survives, it is in a section the IR did not flag `hidden`, which is a defect
   in the artifact type rather than in the profile.
