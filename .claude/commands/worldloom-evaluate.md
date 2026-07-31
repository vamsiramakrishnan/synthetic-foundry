---
description: Score the corpus against the built-in baseline retriever
---

Score the corpus at $ARGUMENTS (default `./corpus`) against its own evaluation set.

```bash
worldloom evaluate <CORPUS>
```

This indexes the corpus with a deliberately mediocre baseline retriever — naive
chunking, no reranking, no notion of authority or time — and scores it against the
questions `worldloom build` generated alongside the facts. Every answer and
citation is ground truth from the fact ledger, not another model's opinion, so the
score is checking the corpus, not the baseline's taste.

**A rising score is bad news unless someone deliberately improved the retriever.**
The baseline has no concept of `knows_as_of`, supersession, or authority, so it
should do fine on direct lookup and badly on temporal state, authority resolution,
and expected abstention. If a change to the corpus makes those harder categories
score *better*, the corpus got easier, not the retriever smarter — the questions
that were supposed to require reasoning about time or trust started being
answerable by keyword match instead. Investigate the diff to the corpus, not the
retriever, when that happens.

Use `-v`/`--verbose` to see every question and its result rather than the
aggregate, and `-k <N>` to change how many passages the baseline may return before
answering.

To hand the evaluation set to an external system instead of scoring the baseline:

```bash
worldloom evals export <CORPUS> -o evals.jsonl
```

Report the per-type breakdown to the user, not just the aggregate — a single
overall number hides exactly the direct-lookup-vs-temporal split that makes the
result legible. For what each evaluation type is testing and how to read a
scorecard, see `references/evaluating.md`.
