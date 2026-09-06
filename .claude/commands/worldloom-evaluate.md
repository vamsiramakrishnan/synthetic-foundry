---
description: Score the corpus against the built-in baseline retrievers, and report what it contains
tags: [worldloom, evaluation, retrieval]
---

Score the corpus at $ARGUMENTS (default `./corpus`) against its own evaluation set.

```bash
worldloom evaluate <CORPUS> --retriever both
worldloom stats <CORPUS>
```

`evaluate` indexes the corpus with a mediocre retriever by design (naive
chunking, no reranking, no notion of authority or time) and scores it against the
questions `worldloom build` generated alongside the facts. Every answer and
citation is ground truth from the fact ledger, not another model's opinion, so the
score is checking the corpus, not the retriever's taste. `--retriever` picks
which ranking family: `bm25` (default), `tfidf` (vector-space cosine, a
genuinely different ranking family from BM25's probabilistic one), or `both`.
`both` makes the stronger claim, because a family low under **both** is hard for a
structural reason, not for one heuristic's particular blind spot. Read the
per-family agreement table `both` prints; a family the two retrievers split on
is a finding about the corpus, not something to average away.

**A rising score is bad news unless someone set out to improve the retriever.**
Neither retriever has a concept of `knows_as_of`, supersession, or authority, so
both should do fine on direct lookup and badly on temporal state, authority
resolution, and expected abstention. If a change to the corpus makes those
harder categories score *better*, the corpus got easier, not the retriever
smarter: the questions that were supposed to require reasoning about time or
trust started being answerable by keyword match instead. Investigate the diff
to the corpus, not the retriever, when that happens.

Use `-v`/`--verbose` to see every question and its result rather than the
aggregate, and `-k <N>` to change how many passages a retriever may return before
answering.

To hand the evaluation set to an external system instead of scoring the baseline:

```bash
worldloom evals export <CORPUS> -o evals.jsonl
```

`worldloom stats` is `evaluate`'s sibling for a different question. It does not
ask "is this hard to retrieve from" but "what does it actually contain": document
counts, length distributions, vocabulary, near-duplicate rate, fact-citation
density and graph, eval-case counts. No fabricated "real enterprise corpus"
benchmark appears anywhere in it. Report, don't grade; `--against <corpus>`
diffs two real corpora if there is a second one worth comparing to.

Report the per-type breakdown to the user, not just the aggregate. A single
overall number hides the direct-lookup-vs-temporal split that makes the
result legible. For what each evaluation type is testing, how to read a
scorecard, the two-retriever agreement reading, and what `stats` reports, see
`references/evaluating.md`.
