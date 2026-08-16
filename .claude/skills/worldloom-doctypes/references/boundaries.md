---
title: Authored/Coded Boundary
description: Know where a JSON type stops being enough, and why authored types travel in the pack.
read-when: Before promising a workbook, a new role, or a new audience from a pack-authored type.
tags: [worldloom, doctypes, compilers, determinism, packs]
---

# What still needs Python, and why the pack is the only carrier

## What still needs Python

A **compiler**. Among the core types, five have one — `finance_workbook`,
`capital_return` and `reserve_triangle_workbook` declare formulas over a
resolved table; `meeting_minutes` and `email_thread` build one message per
moment (the verticals and policy suites register more) — and no outline stands
in for that. If the document you want is a workbook whose totals have to
recompute, it is a domain module, not a pack.

Also Python-side, and worth knowing before you promise any of it: a new **fact
kind** (a section can only cite what a generator produced), a new **role**
(`filing.author_role` is looked up in the engine's role table), and a new
**access policy** (an audience nothing maps falls to the narrowest one).

## Determinism

Authored types travel **in the pack**, and the pack is embedded verbatim in
the corpus recipe — so a corpus carrying an authored type rebuilds with the
type, in any process, with no file on hand. There is no search path and no
plugin directory, deliberately: `register_artifact_types` calls that "a
determinism bug wearing a plugin's clothes".

Two names are refused rather than merely linted, because their consequence
lands on *somebody else's* corpus: a key some module already declares, and a
key `documents.reserved_types()` holds — a name a scenario mints without
declaring, where there is no registered value for the seam to disagree with.
