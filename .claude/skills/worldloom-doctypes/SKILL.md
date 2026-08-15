---
name: worldloom-doctypes
description: Give a company a document type the engine does not have — authored as JSON in its pack, planned by its own lore, rendered to Word, and linted against what the compiler actually assumes. Use when a corpus needs paperwork no archetype ships (a franchisee statement, a levy return, a covenant certificate), when asked whether Worldloom can produce some particular document, or when a pack's lore asks for a filing nothing plans.
---

# A document type, authored rather than written in Python

An artifact type is registered into four tables, and three are pure data:
`_STANDING` (`(Authority, Lifecycle)`), `_LAG` (a `timedelta`, always whole
minutes), `_OUTLINES` (a tuple of `SectionPlan` — four strings each). Only
`_COMPILERS` is a function. So a pack can give a company paperwork of its own:
an `artifact_types` entry declares the type, and a lore commitment makes the
company file it. Declaring without the lore produces a type that is carried,
renderable, and inert.

```bash
worldloom pack check ./pack.json                      # lint it before you build it
worldloom build --pack ./pack.json --seed 8128 -f docx -o ./corpus
```

Reference: `examples/artifact-types/` — the thirty core types ported to the
schema (`core.json`), a pack that authors one and builds
(`franchise-network.json`), and one that fires every lint rule
(`franchise-network-broken.json`). Skeletons to copy:
`assets/artifact-type.json` (one complete type, for the pack's
`artifact_types` list) and `assets/filing-lore.json` (the lore entry that
files it).

Five fields decide whether the document is any good:

- `sections[].kinds` — fact-kind *prefixes*; a prefix nothing produces drops
  the section silently rather than failing.
- `sections[].scope` — `group` / `unit` / `any`, filtering on a fact's
  *subject*; only financial generators state per-unit figures.
- `sections[].purpose` — say what the section must *establish*, and for whom,
  or the prose lists instead of argues.
- `filing.audience` — who may **open** the document, not who receives it.
- `lag` — how long after its newest cited fact it is written; keep it at or
  under a day and fifteen hours.

Read the lint before building: only two findings are refused at install
(`is reserved`, `already declared by a module`); the other fifteen **compile**,
into documents that are quietly wrong.

## Read next

- `references/authoring.md` — every schema field, the why of the five above,
  and the lore that makes the company file the type. Load before writing the
  JSON.
- `references/lint.md` — the findings and what each one costs. Load when
  `pack check` reports anything.
- `references/boundaries.md` — what still needs Python (compilers, fact
  kinds, roles, access policies) and why authored types travel in the pack.
  Load before promising a workbook, a new role, or a new audience.
