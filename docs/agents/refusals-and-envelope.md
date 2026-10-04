---
title: Refusals and the envelope
description: Understand why the plan-vs-compiled checks exist, and parse refusals as JSON instead of prose.
read-when: A validation rule looks excessive, or a caller must parse CLI refusals mechanically.
tags: [validate, refusals, json-output, exit-codes]
---

# Why the sharpest checks exist

Validation compares each intent's required facts with the facts present in
that intent's compiled artifact. It also checks empty referenced cells and
missing compiled documents. Comparing only the union of facts across the
corpus would allow one document to conceal another document's omission.

These checks were added after an incorrect reporting-period lookup produced
empty workbook cells that passed reconciliation. Retain per-artifact checks
when adding a format or changing compilation; an empty value is not evidence
that the requested fact was rendered.

# Machine-readable refusals

Refusals are also machine-readable. With `WORLDLOOM_OUTPUT=json` in the
environment, every CLI refusal prints one line of JSON to stderr,
`{"refusal": "<code>", "message": ..., "fix": ..., "data": {...}}`, with the
same exit code the prose form uses (2 for a caller error, 3 for a measured
refusal). The codes are stable, snake_case, and registered in `cli._REFUSALS`;
parse the code, not the message.

Without the variable, the refusal prints as prose: the message, then, when the
next action is known, a dim line under it such as `  fix: worldloom archetypes`.
`fix` (in both forms) is the refusal site's own remedy when it names one, and
otherwise the code's entry in `cli._REFUSAL_FIXES`: a real command for the
commonest codes with one generic next step (an unknown name gets the command
that lists the known ones, an unloadable corpus gets `worldloom build`, a
missing extra gets `worldloom doctor`). Codes whose remedy depends on the
input, such as `cannot_combine` or `unreadable_document`, carry no default, and
their `fix` is `null` unless the site supplies one.
