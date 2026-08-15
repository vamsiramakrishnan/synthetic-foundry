---
name: worldloom-present
description: Decide who a Worldloom corpus's documents are for, and author a presentation profile through a refusable lint — whether the supporting-fact appendix prints, where the author's voice goes, how a money figure is spelled, and how a PDF table sizes its columns. Use when a corpus's documents will be read by a person rather than checked by a validator, when a demo or a filing pack needs the traceability scaffolding off the page, or when asked why a rendered memo looks like a machine wrote it.
---

# Presenting a corpus

Every artifact here is two things at once. It is a **traceability record** —
which facts a passage cites, at what authority, in whose voice it was asked
for. And it is a **document** — something a person opens. The renderers were
written for the first reading, so left alone the second one leaks: a CFO
variance memo renders to five PDF pages of which four are a fact table, and its
last line is the generation brief printed inside the artifact it briefed.
Neither reading is more correct, which is why this is a decision you make and
not a default somebody picked.

## The one rule

**A profile decides how a value is shown. It may never change the value.**

That is enforced, not asked for: `magnitudes: scaled` is refused unless every
rescaled figure multiplies back to the ledger figure exactly. And nothing a
profile omits is *lost* — `artifact-ir.jsonl` keeps every section, every
`fact_ids` list and every voice under every profile. So omitting is safe, and
the lint that matters is about arithmetic.

## Start here

```bash
worldloom present describe                  # every profile and knob, rendering nothing
worldloom render ./corpus -f docx -f pdf --profile reader
```

Three profiles ship — `audit` (everything on the page; the default, and the
right profile when the reader is a validator), `reader` (appendix and voice
off the page), `filing` (citations in a sidecar file). Re-rendering an
existing corpus under a second profile needs **no rebuild** — unlike `locale`,
a profile decides nothing about the world.

## Authoring your own

Use the cascade when none of the three fits — most often because one doctype
needs different treatment from the rest.

```bash
worldloom present brief ./corpus -o brief.json    # knobs, vocabularies, this corpus's doctypes
# write profile.json — assets/profile.json is a starter
worldloom present lint profile.json --corpus ./corpus
```

`lint` returns **every** finding, not the first — fixing one knob per round
trip is a turn paid per rule you could not see.

## Read next

- `references/knobs.md` — the shipped profiles' settings and what every knob
  value does. Load before choosing or authoring a profile.
- `references/authoring.md` — overrides, what the lint refuses, the Python
  cascade, and why a profile replays by value. Load when writing profile.json.
- `references/checking.md` — reading the rendered file instead of trusting the
  flag. Load after the first render under a new profile.
