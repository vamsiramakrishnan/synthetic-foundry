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
| `citations` | `inline` | `appendix` | `appendix` |
| `layout` | `plain` | `designed` | `designed` |
| `deck` | `ledger` | `presenter` | `presenter` |
| `notes` | `provenance` | `talk` | `talk` |
| `slide_budget` | `unbounded` | `board` | `board` |

`audit` is byte-for-byte what every corpus rendered before this layer existed
got, and what a corpus that names no profile gets under `legacy` and
`enterprise/v1`. It is not a legacy setting: it is the right profile for a
corpus whose reader is a validator. A corpus built under `enterprise/v2` (the
default for new builds) that names no profile is presented under `reader`.

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
- **`citations`**: where a long document's per-section provenance goes.
  `inline` follows every numbered section with a "Figures cited" table (a
  "Key figures" table under the summary), one row per fact id, captioned
  "Source: Fact ledger". `appendix` takes every one of those rows into a single
  "Sources of figures" appendix (section, measure, subject, value, fact id),
  keeps the lineage appendix, moves the workbook schedules behind the paper
  as an appendix, and writes the cited fact ids into the file itself: Word
  and PowerPoint custom properties and the PDF information dictionary
  (`WorldloomFacts`, `WorldloomProvenance`, `WorldloomReference`,
  `WorldloomProfile`). `artifact_text.extract` reports them as
  `extra["properties"]`, so a grader or a connector's `get_file` still sees
  every id and no page prints one.
- **`layout`**: `plain` is the shipped layout. `designed` gives a long
  document a real cover (classification band, title block, a summary box
  carrying the document's own opening paragraphs, an "In this paper" list, a
  distribution list and a reference block), a two-column document-control
  grid, headings and captions kept with what follows them, tables of up to
  fourteen rows kept whole and rows that never break, widow and orphan
  control on body text, and sections that run on rather than each opening a
  page. Word and PDF both.
- **`deck`**: `ledger` builds a deck from the pack the way a validator reads
  it: every schedule as a Title Only table slide. `presenter` builds the deck
  somebody gives: titles that are the slide's point (written from the facts
  it shows), bullets that are the section's argument (one per move), a Two
  Content slide pairing an argument with the chart it rests on, a chart under
  a takeaway title, and tables in the appendix unless the table is the point.
- **`notes`**: what a presenter deck's speaker notes say. `talk` is what the
  presenter says, from the notes moves (`point`, `evidence`, `transition`) in
  the rhetoric catalogue and the prompts pack's `render.deck.notes.*` texts;
  `provenance` names the document each slide was drawn from. No fact id
  appears in either. A `ledger` deck's notes always list its ledger entries,
  which is what that deck is for.
- **`slide_budget`**: how many slides a deck may run to: `unbounded` (the
  renderer's own stop, sixty), `board` (twenty-four) or `briefing` (fourteen).
  The closing slide is reserved; the appendix takes what the budget leaves.
