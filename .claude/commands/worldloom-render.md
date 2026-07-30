---
description: Render a Worldloom corpus to files and validate that every document agrees
---

Render and validate the corpus at $ARGUMENTS (default `./corpus`).

```bash
worldloom render <CORPUS> -f xlsx -f markdown -f jira -f confluence -f servicenow
worldloom validate <CORPUS>
```

Validation must pass — it runs over a thousand checks covering reconciliation,
referential integrity, the org graph, temporal ordering, lore, and access. A failure
is a defect in the corpus, not a warning to note and move past.

Then show the user what they have. Worth surfacing:

- The workbook carries real formulas: totals are `=SUM(...)`, and a hidden
  reconciliation sheet checks the summed units against what the fact ledger states.
- Documents written at different times disagree *on purpose*, and the labelled
  imperfections record which disagreements are deliberate.
- `worldloom inspect <CORPUS> --evals` lists the evaluation cases: questions with
  ground-truth answers, citations, distractors, and temporal cut-offs.
