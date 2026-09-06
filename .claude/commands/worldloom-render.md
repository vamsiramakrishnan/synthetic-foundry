---
description: Render a Worldloom corpus to files and validate that every document agrees
tags: [worldloom, rendering, validation]
---

Render and validate the corpus at $ARGUMENTS (default `./corpus`).

```bash
worldloom render <CORPUS> -f xlsx -f docx -f markdown -f jira -f confluence -f servicenow
worldloom validate <CORPUS>
```

`-f docx` is easy to forget and easy to miss the absence of: the corpus renders and
validates fine without it, because Markdown covers every artifact type Word does.
Include it whenever the user wants the narrative artifacts (the CFO memo, the
incident RCA, the executive summary) in the shape they actually arrive in at a
real company. Only the six document-shaped artifact types render as `.docx`; the
workbook and Confluence pages don't, and asking for those in that format is not an
error, just nothing extra to render.

Validation must pass. It prints the number of checks it ran (reconciliation,
referential integrity, the org graph, temporal ordering, lore, access), and a
failure is a defect in the corpus, not a warning to note and move past.

Then show the user what they have. Surface these:

- The workbook carries real formulas: totals are `=SUM(...)`, and a hidden
  reconciliation sheet checks the summed units against what the fact ledger states.
- Documents written at different times disagree by design, and the labelled
  imperfections record which disagreements are intended.
- `worldloom inspect <CORPUS> --evals` lists the evaluation cases: questions with
  ground-truth answers, citations, distractors, and temporal cut-offs.

For what each format carries and why the render order is XLSX first, read
`references/rendering.md`.
