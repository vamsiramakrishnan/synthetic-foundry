# Rendering a world

You are about to run `worldloom render`, on a corpus that is already narrated.
This is what each format is for and what it carries — not the procedure,
which is in `SKILL.md`.

```bash
worldloom formats
worldloom render ./corpus -f xlsx -f docx -f markdown -f jira -f confluence -f servicenow
```

`worldloom formats` lists what this installation actually has registered —
`xlsx` and `docx` are optional extras (`pip install -e ".[xlsx,docx]"`); the
rest need nothing extra. Trust that list over this file if they disagree,
because it comes straight from `render.available()`.

## The IR is the contract

Every renderer reads one thing: the artifact's `ArtifactIR`, produced once by
the narrative compiler. No renderer touches the world, the fact ledger, or
another renderer's output — this is what guarantees two formats of the same
artifact agree, because they are two projections of the one resolved
structure rather than two independent descriptions of it.

The consequence worth understanding before you add or debug a format:
**formulas and charts are declared in the IR, not invented by a renderer.**
A table cell that should sum its rows carries `FormulaKind.SUM` and the row
keys to sum; a chart carries `ChartKind` and which rows and columns it plots.
A renderer's whole job is deciding how to *spell* a declared computation —
`=SUM(C4:C6)` in Excel, a shaded row and a bar figure in Word, a plain number
in Markdown — never whether to compute one. This is why a workbook's totals
are live formulas rather than baked-in numbers, and why adding a new format
to this list can change how a document looks but can never change what it
*says*: it has no path to a fact or a figure that bypasses what the IR
already resolved.

## The formats

**`xlsx`** (`src/worldloom/render/xlsx.py`) — the finance workbook, and the
only format where numerical coherence is externally checkable without this
tool: open the file, and the sheet recomputes its own totals. A total is
`=SUM(...)`, a variance is `=D4-C4`, a margin is `=IF(denom=0,0,num/denom)`
— never a pasted value, so if a fact changes and a total does not move, the
sheet itself shows it. Charts draw from a hidden **Chart Data** sheet made of
cross-sheet formula references, not copied numbers, for the same reason: a
chart that quietly disagreed with the table it plots would be worse than no
chart. Named ranges (`GroupRevenueActual` and siblings) are stamped onto the
P&L's summary row so a consumer can address the headline figures without
knowing which row they landed on.

**`docx`** (`src/worldloom/render/docx.py`) — the narrative artifacts as Word
documents: the shape enterprise prose actually arrives in, which a
Markdown-only corpus cannot exercise. It carries what a memo or RCA needs
that Markdown does not: A4 page setup with real margins, a running header
naming the company and document, a footer with live `PAGE`/`NUMPAGES` fields,
a `TOC` field on documents with enough sections to need one — all fields, not
typed text, because a page count or contents list that was *written* goes
stale the moment a section is added and this corpus is regenerated
constantly. Tables shade subtotal rows and right-align figures; a negative
is parenthesised and coloured red, with the colour as the second signal so
the document still reads correctly printed in black and white. Charts have
no native equivalent here — python-docx has no DrawingML chart API — so they
are drawn as proportional block-character bars from the same cells the table
above shows, deterministic and needing nothing installed.

**`markdown`** — the fallback that keeps every artifact readable regardless
of what else is installed, and the cheapest to diff. Any IR renders here,
including one still awaiting narration (it says so, rather than shipping
placeholder prose).

**`jira`**, **`confluence`**, **`servicenow`** (`src/worldloom/render/bundles.py`)
— portable bundles: a JSON header plus JSONL, not a live API call, so they
can be diffed, reproduced byte for byte, and tested with no credentials
against whatever system a reader actually has. These are record sets rather
than documents — they render from the world's facts and events directly,
not through an `ArtifactIR` — because what they add over a document is
*workflow*: ServiceNow's incident carries a `work_notes` sequence with the
full triage timeline including the hypothesis that was later ruled out, not
a single "root cause" field; Jira raises two issues rather than one for an
incident's remediation, because "close the detection gap" and "fix the
ownership failure that let it happen" are different questions a corpus
should be able to pose separately; Confluence renders each page's body
through the Markdown renderer and adds the thing Markdown has no notion of —
page hierarchy — and marks a page `stale` when a fact it depends on has since
been superseded, with a comment explaining why it was left as written rather
than corrected. That staleness is deliberate: a reader (or an agent under
evaluation) has to notice it, not have it silently fixed.

## Who the documents are for

Every artifact here is two things at once: a **traceability record** (which
facts a passage cites, at what authority, in whose voice it was asked for) and
a **document** (something a person opens). Left alone, the renderers serve the
first and the second leaks — a CFO variance memo renders to five PDF pages of
which four are a fact table, and its last line is the generation brief printed
inside the artifact it briefed.

Which reading a corpus is for is a decision, not a default:

```bash
worldloom present describe
worldloom render ./corpus -f docx -f pdf --profile reader
```

| | `audit` | `reader` | `filing` |
|---|---|---|---|
| supporting-fact appendix | printed | omitted | sibling `.citations.md` |
| author voice and persona | in the document | file metadata | file metadata |
| money figures | `AUD 5,372,800 thousands` | `AUD 5,372.8m` | `AUD 5,372.8m` |
| PDF table columns | even split | measured, type shrinks to fit |  measured |

`audit` is the default and is byte-for-byte what shipped before profiles
existed — the right profile when the reader is a validator. **Nothing a profile
omits is lost**: every section, `fact_ids` list and voice stays in
`artifact-ir.jsonl` under every profile, so omitting withholds from the page and
never from the corpus.

Authoring one, when none of the three fits — usually because one doctype needs
different treatment from the rest:

```bash
worldloom present brief ./corpus -o brief.json
worldloom present lint profile.json --corpus ./corpus
```

The lint returns every finding at once, refuses a misspelled knob by name
rather than ignoring it, and refuses any figure scaling that cannot multiply
back to the ledger value exactly — a profile decides how a value is *shown* and
may never change it. `/worldloom-present` drives the whole thing.

The chosen profile is written onto the corpus's **recipe**, by value, so the
files and the record of how they were made cannot disagree and a `--replay`
reproduces this rendering. Re-rendering an existing corpus under a second
profile needs no rebuild: unlike a locale, a profile decides nothing about the
world.

## Determinism in Office formats

`openpyxl`, `python-docx`, and `python-pptx` all stamp wall-clock timestamps
into the zip entries and core properties of the files they write — a defect
that has nothing to do with document content and everything to do with
breaking this project's central claim, that a corpus regenerates
byte-for-byte from its seed and ledger. `src/worldloom/render/ooxml.py::normalise()`
fixes every zip entry to a constant epoch and rewrites `dcterms:created` /
`dcterms:modified` to a timestamp derived from the world rather than the
clock. **Any new Office-family renderer (pptx, for instance) must call it** —
there is no other place this correction happens, and skipping it silently
reintroduces the defect for that one format while every other format still
looks clean.

This was measured, not assumed. `openpyxl` overwrites `dcterms:modified`
with `now()` from inside `save()`, after anything set on `workbook.properties`,
so it cannot be fixed by setting properties first; `python-docx` leaves core
properties alone but seeds them from its template, which claims a document
was created in 2013 unless told otherwise. Worth stating plainly because it
is the kind of bug that hides: the zip-timestamp half of this was found by
CI, not locally — two runs of the replay check happened to land on either
side of a second boundary, so the files differed, while every local run for
weeks beforehand had shared a second by luck and passed unnoticed.

## Validation after render

```bash
worldloom validate ./corpus
```

Beyond the checks that run on any corpus (referential, graph, financial,
temporal, lore — see `AGENTS.md`), rendering adds its own surface to check:

- **Rendered files exist and match the manifest** (`referential` /
  `missing_file`) — a manifest entry naming a path is only valid if that
  file is actually there; an empty path is fine and means "compiled, not
  rendered in this format set."
- **A chart cannot double-count** (`artifact` / `chart_double_counts`) — a
  chart that plots a total *and* the rows that sum into it draws the same
  money twice while looking entirely correct. This is answerable from the
  IR alone: a `SUM` cell names its own children as operands, so plotting a
  subtotal on its own is fine (a trend of divisions is exactly that) but
  plotting it alongside its parts is not.
- **Every number in a document traces to a fact** — the same referential
  check that catches any dangling reference elsewhere in the corpus applies
  here: a rendered figure that did not come from a resolved `{{fact:...}}`
  reference has nowhere legitimate to have come from.

Run it after every render, not just after narration — a rendering bug (a
misdrawn chart, a stale manifest path) is exactly as much a defect as a bad
fact, and this is the only step positioned to catch it.
