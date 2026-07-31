# Evaluating

You are here because the corpus is built, narrated and rendered, and the
question is no longer "does it agree with itself" (that's `worldloom validate`)
but "is it actually hard to retrieve from." This stage answers that.

```bash
worldloom evaluate ./corpus
worldloom evaluate ./corpus -v
worldloom evaluate ./corpus -k 3
worldloom evals export ./corpus -o evals.jsonl
```

`-v`/`--verbose` prints every case with pass/fail and a one-line detail.
`-k` changes how many passages the baseline retriever is allowed to return
(default 5) — lowering it makes every question type harder, which is a way to
sanity-check that a family isn't passing only because it's allowed to return
half the corpus. `worldloom evals export` writes the evaluation set as JSONL,
one case per line, sorted keys — the format to hand to an external retrieval
system you want to score against this same answer key.

## What's being measured, and what isn't

This scores **retrieval**, not generation. There is no judge model anywhere in
`src/worldloom/evaluate/` — deliberately, because a judge model would put the
thing under test inside the measurement itself, and the score would stop being
reproducible. Every case is graded by an objective, mechanical check against the
manifest: did the retrieved passages between them carry the fact IDs the
question needs (`_covers` in `score.py`), was the top hit written before the
question's `temporal_cutoff`, did the top hit come from a passage whose
authority rank matches or beats the best available source. The manifest — which
artifact carries which fact, when it was written (`created_at`), with what
authority — is the answer key, built once by `src/worldloom/evaluate/index.py`
turning each rendered artifact section into a `Passage` that carries its fact
IDs, authority, and timestamp. Nothing about "did this read well" is scored
here; that's the narration stage's job, enforced by `claims.py` instead.

## The baseline

`src/worldloom/evaluate/bm25.py` is BM25 in well under a hundred lines, no
dependency, unweighted, untuned (`K1`/`B` are textbook defaults — "a tuned
baseline is no longer a floor", per its own docstring). It has no notion of
time, no notion of authority, no notion of provenance — it ranks purely on
keyword overlap across every document in the corpus at once, as if they'd all
been written simultaneously and were all equally to be trusted. It exists to be
beaten. More precisely, it exists to **fail** in a specific, informative way:
every question family this baseline gets wrong is a family the corpus is
successfully making hard, and every family it gets right is either genuinely
easy (single-fact lookup) or a sign the corpus isn't posing the question it
thinks it's posing.

## The question families

From `src/worldloom/generators/evaluation.py` — each `_Taxonomy` method builds
one or more `EvaluationType`s. For each, ask what capability a retriever needs
that plain keyword overlap doesn't have:

- **`direct_lookup`** (`direct_lookup()`) — one fact, one document, e.g. "what was
  group revenue for the period." No comparison, no time sensitivity. The floor:
  a competent baseline should pass these, and if it doesn't, something is
  actually broken.
- **`numerical_comparison`** (`numerical_comparison()`) — several facts that have
  to be read together: which of four units carried the largest adverse
  variance, whether category revenues sum to the divisional total. Answerable
  from the corpus, but not from any single page — needs the passages that carry
  every compared value, not just the one with the most keyword overlap.
- **`causal_multi_hop`** (`incident()`) — failure → cause → consequence chains,
  e.g. "why was the close delayed" needs the feed failure, the confirmed cause,
  *and* the resulting delay strung together, and the harder ones ("what allowed
  the failure to reach production undetected") need the classification and the
  ownership gap read jointly, facts that live in different sentences of the RCA.
- **`temporal_state`** (`incident()`) — "what was believed to be the cause at
  time T" where T sits inside a fact's validity window, before it was
  superseded. Demands knowing *when* each candidate passage was written, not
  just what it says — the correction is almost always the better keyword match,
  and it's the wrong answer for the question actually asked.
- **`authority_resolution`** (`incident()`, `across_episodes()`) — several
  documents state the same thing, only one is the current record. E.g. a stale
  triage page still carrying the ruled-out hypothesis versus the confirmed RCA,
  or an old close calendar versus the one currently in force. Demands ranking
  by which source is authoritative, not by which reads most confidently.
- **`citation_required`** (`incident()`) — the answer has to be paired with
  *where* it's recorded, not just stated. "Who owns the mapping table? Nobody —
  and where does that show?" An unsupported right answer is indistinguishable
  from a lucky guess.
- **`cross_artifact`** (`incident()`) — the correct answer requires facts that
  live in different documents of different types read together, e.g. which of
  two open remediation tickets addresses the actual control failure versus only
  detection, which needs the RCA's classification and the ticket text both.
- **`expected_abstention`** (`abstentions()`) — plausible-sounding questions the
  corpus does not answer at all: prior-period causes, people's compensation,
  suppliers, competitors, net promoter score. The right answer is silence. A
  keyword baseline can't produce silence — it always returns its best-overlap
  document with some confidence, so this family is where "confidently wrong" is
  the only way to fail.
- **`across_episodes`** (`across_episodes()`) questions aren't a distinct
  `EvaluationType` of their own — they're `causal_multi_hop`,
  `numerical_comparison` and `authority_resolution` cases that can only exist
  once a corpus has more than one period: recurrence ("did the earlier response
  prevent this happening again"), counting incidents across periods, or which
  of several superseded close calendars is the one in force now. They only
  appear when the world was built with `--periods` greater than one.

## Reading the scorecard

The printed table is per-type pass/total with a bar. The headline read: **a
baseline that scores well on `direct_lookup` and `numerical_comparison` while
scoring badly on `temporal_state`, `expected_abstention`, and
`causal_multi_hop` is the corpus working as designed.** That's not a caveat on
the result, that's the result.

State the inverted intuition plainly, because it reads backwards the first
time: **a rising baseline score is bad news**, not good news — unless someone
deliberately improved the retriever (a different index, added time-awareness,
added authority weighting), a rising score on the hard types means the corpus
got easier, not that anything got better. This is exactly why CI asserts the
hard types stay hard (see `tests/test_evaluate.py` —
`test_the_baseline_fails_on_knowing_when`,
`test_the_baseline_never_abstains_confidently`, and friends): a regression
here means a change accidentally made superseded facts distinguishable by
keyword alone, or added enough text overlap that abstention questions started
scoring, or some other way the corpus quietly stopped being hard.

## A measurement trap already caught

An early version of the scorer filtered retrieved passages down to those that
existed as of the question's `temporal_cutoff`, *before* grading `temporal_state`
cases. That reads as reasonable — "only look at what the author could have
known" — and it was exactly wrong: filtering by the cutoff **is** the
capability under test. Handing the baseline a pre-filtered pool measures a
temporal-aware retriever that doesn't exist in this repository, and the score
came back perfect, which felt like success and meant the opposite — the test
had stopped testing anything. `score.py` now grades the top hit **unfiltered**
(see the comment at `EvaluationType.TEMPORAL_STATE` in `score.py`): the plain
BM25 index sees every document at once, ranks purely on overlap, and is graded
on whether the passage it actually returned predates the cutoff and carries the
fact. Graded that way it scores zero, correctly. `tests/test_evaluate.py`
(`test_a_temporally_aware_retriever_can_answer_what_the_baseline_cannot`) proves
the gap is fair rather than impossible, by rerunning the same question against
a second index that *is* pre-filtered and confirming that one gets it right —
so the corpus isn't unanswerable, the baseline is just the wrong tool for it.
If you ever touch the scorer, keep grading on the unfiltered top hit; filtering
before grading is the specific mistake to not reintroduce.

## Abstention goes stale

The abstention questions in `abstentions()` are hand-picked against things the
generator deliberately never models at all — people costs, suppliers,
competitors, any period but the current run, forward-looking questions. That
has a shelf life: `abstentions()`'s own docstring notes that "how many stores
does the food division operate" was a valid abstention case right up until a
store estate generator was added, at which point the answer was suddenly
sitting in the workbook and the question silently stopped being unanswerable.
`worldloom validate` checks the mechanical half of this — `abstention_requires_sources`
fails if an abstention case ever picks up `required_artifact_ids` (an
abstention case that names a source is no longer really an abstention case) —
but it can't know that a *new* generator made an old question answerable in
prose it doesn't parse. If you add a generator that models something the
existing abstention list presumes doesn't exist, check that list by hand.
