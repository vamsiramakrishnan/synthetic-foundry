---
title: Presentation Knobs
description: Choose among audit, reader and filing, and know what every knob value does to the page.
read-when: Before choosing or authoring a presentation profile.
tags: [worldloom, presentation, profiles, knobs, pdf]
---

# The shipped profiles and what every knob value does.

`worldloom present describe` prints this table from the code; this is the why
behind each knob.

| | `audit` | `reader` | `filing` |
|---|---|---|---|
| `appendix` | `append` | `omit` | `sidecar` |
| `provenance` | `footer` | `properties` | `properties` |
| `magnitudes` | `ledger` | `scaled` | `scaled` |
| `table_fit` | `fixed` | `measured` | `measured` |

`audit` is the default and is byte-for-byte what every corpus rendered before
this layer existed got. It is not a legacy setting: it is the right profile
for a corpus whose reader is a validator.

What the knobs do:

- **`appendix`**: what becomes of a section the IR flagged `hidden` (the
  supporting-facts tables). `append` prints it with a note saying it is not
  part of the readable surface; `omit` drops it from the document; `sidecar`
  drops it and writes `<artifact>.citations.md` beside the document instead.
- **`provenance`**: where the author's voice and persona go. `footer` puts
  them in the document; `properties` writes them to the file's own metadata
  (Word and PowerPoint category, where a tool can read them and a reader cannot
  see them); `omit` drops them from the file entirely. Markdown has no metadata
  container, so `properties` and `omit` are the same there.
- **`magnitudes`**: `ledger` spells a money figure exactly as the fact states
  it (`AUD 5,372,800 thousands`); `scaled` promotes it to the largest magnitude
  that is still *exact* (`AUD 5,372.8m`). Never a rounding: a figure with no
  shorter exact spelling keeps the ledger wording.
- **`table_fit`**: `fixed` divides a PDF table's frame evenly; `measured`
  sizes each column to its widest unbreakable token and shrinks the type if
  even that will not fit. On the shipped fact table `fixed` produces 112
  mid-token line breaks (`system_of_recor`/`d`, a timestamp split as
  `2026-04-07T16:4`/`0:00+00:00`), and `measured` produces none.
