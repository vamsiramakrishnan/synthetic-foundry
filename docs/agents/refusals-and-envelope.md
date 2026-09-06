---
title: Refusals and the envelope
description: Understand why the plan-vs-compiled checks exist, and parse refusals as JSON instead of prose.
read-when: A validation rule looks excessive, or a caller must parse CLI refusals mechanically.
tags: [validate, refusals, json-output, exit-codes]
---

# Why the sharpest checks exist

The last three rules `worldloom validate` enforces (a fact a document was asked
to carry and does not carry, a table cell that names a fact and states nothing,
fewer compiled documents than the plan asked for) are one rule looked at from
three sides, and they exist because the worst defect this project has had passed
everything above them. A workbook that looked its figures up at the wrong month
rendered with *every cell empty* and validated clean, because a reconciliation
check compares a cell against a fact and two absent numbers agree. So the plan
is now compared against the compiled document, per document rather than over the
union of all of them: an intent's `required_fact_ids` against its own
`ArtifactIR.fact_ids()`. It found four more of the same shape on its first run
across the four verticals.

# Machine-readable refusals

Refusals are also machine-readable. With `WORLDLOOM_OUTPUT=json` in the
environment, every CLI refusal prints one line of JSON to stderr,
`{"refusal": "<code>", "message": ..., "fix": ..., "data": {...}}`, with the
same exit code the prose form uses (2 for a caller error, 3 for a measured
refusal). The codes are stable, snake_case, and registered in `cli._REFUSALS`;
parse the code, not the message. Without the variable, output is unchanged.
