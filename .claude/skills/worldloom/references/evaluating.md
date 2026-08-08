# Evaluating

You are here because the corpus is built, narrated and rendered, and the
question is no longer "does it agree with itself" (that's `worldloom validate`)
but "is it actually hard to retrieve from." This stage answers that.

```bash
worldloom evaluate ./corpus
worldloom evaluate ./corpus -v
worldloom evaluate ./corpus -k 3
worldloom evaluate ./corpus --retriever both
worldloom evaluate ./corpus --retriever all --vectors ./corpus/vectors.json
worldloom evals export ./corpus -o evals.jsonl
worldloom stats ./corpus
```

`-v`/`--verbose` prints every case with pass/fail and a one-line detail.
`-k` changes how many passages a retriever is allowed to return (default 5) —
lowering it makes every question type harder, which is a way to sanity-check
that a family isn't passing only because it's allowed to return half the
corpus. `--retriever` picks which ranking family scores the corpus — `bm25`
(the default, unchanged), `tfidf`, `embedding`, `both` (the two lexical
baselines) or `all`; see below. `worldloom evals
export` writes the evaluation set as JSONL, one case per line, sorted keys —
the format to hand to an external retrieval system you want to score against
this same answer key. `worldloom stats` is `evaluate`'s sibling for a different
question — not "is this corpus hard to retrieve from" but "what does it
actually contain" — see the section at the end of this file.

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

## The baselines

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

`src/worldloom/evaluate/tfidf.py` is the second one: TF-IDF cosine, a genuinely
different ranking family, not a second copy of the first with different
constants. BM25 is probabilistic-relevance (term frequency *saturates* inside a
formula tuned to approximate "probability this document is relevant", length
normalised as a ratio to the corpus's average document length). TF-IDF cosine
is vector-space (term frequency is log-*damped*, not saturating — a different
nonlinearity — length normalised by each document's own Euclidean vector norm,
and the score is an angle between two vectors rather than a sum of per-term
relevance). Both are equally blind to time, authority, and provenance; where
they differ is *which* keyword patterns each one happens to reward, which is
exactly the axis the credibility reading below depends on. Tokenisation is
shared (`tfidf.py` imports `bm25.tokens` rather than redefining it) so a
disagreement between the two is never just the two retrievers having chunked
the text differently.

## The credibility reading: run both

A hardness claim resting on one retriever proves less than it looks like it
proves — a family that BM25 fails might just be a family keyword-overlap
scoring happens to handle badly, with nothing structural about the corpus
behind it. `worldloom evaluate ./corpus --retriever both` runs BM25 and TF-IDF
cosine side by side and reports, per family, one of three readings:

- **consistently hard** — both retrievers fail it. This is the good result:
  neither probabilistic nor vector-space keyword ranking can shortcut the
  question, so whatever is making it hard is a property of the corpus, not an
  artifact of one heuristic's blind spot.
- **consistently easy** — both pass it. Fine for `direct_lookup` and similar
  floor families; a warning sign anywhere else (see the reading in "Reading
  the scorecard" above).
- **disagreement** — the two retrievers split on enough cases in that family
  (a third or more; see `DISAGREEMENT_FRACTION` in `score.py`) that they are
  not measuring the same thing. This is not evidence about hardness at all —
  it is evidence that one heuristic happens to exploit (or miss) something
  incidental about how that family's questions or passages are worded. Read
  it as a finding about the corpus worth naming in a corpus card, not as a
  number to average into the other two categories.

`compare()` computes this per case, not from matching aggregate pass rates —
two retrievers passing the same 3-of-6 for a family while failing entirely
different three cases would look identical on an aggregate-only comparison and
is exactly the kind of disagreement this exists to catch.

## The reading `both` could not give you: lexical against semantic

BM25 and TF-IDF are two ranking families and **one idea** — relevance is word
overlap. So "both fail it" is weaker evidence than it looks, and it conflates
two opposite findings: a family that is genuinely hard, and a family that is
merely *worded* in a way that misleads term matching and that any deployed
retrieval stack walks straight past. Every difficulty number this project
published before `src/worldloom/evaluate/embedding.py` existed rested on that
conflation.

`worldloom evaluate ./corpus --retriever all` adds a dense retriever and prints
a second table, per family:

- **`genuinely hard`** — the lexical *and* the semantic side both fail. Nothing
  about swapping ranking functions addresses it. This is the result worth
  having.
- **`lexical trap`** — the keyword baselines fail and the semantic retriever
  solves it. **The family was never difficulty**, whatever the BM25 column
  said, and a corpus card that keeps counting it is overstating itself. Say so
  plainly; that is a finding about the corpus, not a failure of the
  measurement.
- **`semantic blind spot`** — the rarer inverse. Usually an exact token (an
  identifier, a code, a figure) that a dense vector smooths away.
- **`solved by everything`** — the floor families, as expected.

Two cautions when reading it. A family can move *partway*: the measured
retail-close corpora put `authority_resolution` at 0/30 lexical and 8/30
semantic — still failing, so still hard, but the gap says part of what BM25 was
failing on was vocabulary rather than authority. And a dense retriever can pass
a case **for the wrong reason**: on the five-world mosaic the static-embedding
pin passes `temporal_state` five times out of fifteen — always the same question
— by preferring a short triage page whose text is dominated by the word the
question uses, with no notion of *when* anything was written. A pass is not
evidence of a capability; read `-v` and check what was actually returned.

## The dense retriever, and why its vectors are pinned

`src/worldloom/evaluate/embedding.py` is the third family. It is **optional**
(`pip install "worldloom[embeddings]"`) and **absent-friendly** — without the
extra, `--retriever all` skips it with a message and still reports the lexical
pair, and `--retriever embedding` says what to install and exits nonzero. It
never crashes and it never silently scores nothing.

The determinism problem it has to solve is real and is unlike anything else
here. Every other number in this repository replays from a seed and a ledger; an
embedding retriever's ranking depends on weights that live elsewhere, are
mutable under a name, and are loaded by a stack whose floating-point behaviour
depends on thread count and BLAS. So:

- **Pinned.** A `ModelPin` carries a model id *and a commit revision*, and the
  revision is what gets fetched. A pin that says `main` is not a pin.
- **Cached.** Every vector — passages *and* questions — is written to a sidecar
  keyed by `content_key(model, revision, scheme, text)`. Point `--vectors` at
  the corpus and commit the file: the measurement then replays on a machine with
  no model, no GPU and no extra installed. This is the generation ledger's idea
  applied to a retriever.
- **Quantised.** Cached vectors are L2-normalised `int8` and scoring is an
  integer dot product. That is the determinism argument, not a space saving:
  integer addition is exact and order-independent, so the cosine is bit-identical
  on any machine holding the same cache.

Two pins ship. `potion-retrieval-32m` (static embeddings — a vector per token,
mean-pooled, no torch) is the default; `all-minilm-l6-v2` is a real transformer
encoder and needs `pip install sentence-transformers`. Running both matters:
"a cheap semantic model failed this" and "no semantic retriever passes this" are
different claims. `tools/measure_retrievers.py` runs every retriever over a
corpus or a whole mosaic and prints both tables.

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
  the only way to fail. Measured against dense retrieval it gets *harder*, not
  easier: a dense model scores almost every passage positively, so its top
  scores sit in a narrow high band and even a floor calibrated on that band is
  cleared by questions the corpus cannot answer. 0 of 96 across a five-world
  mosaic, against BM25's 3.
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

And one caveat that only became sayable once a non-lexical retriever ran: a
*low* keyword score is not by itself difficulty. It is difficulty only if the
semantic column is low too — see "lexical against semantic" above. A corpus card
quoting BM25 alone is quoting the weakest of the three readings available.

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

## `worldloom stats`: what's in the corpus, not how hard it is

`evaluate` and `stats` (`src/worldloom/stats.py`) answer different questions and
neither substitutes for the other. `worldloom stats ./corpus` reports document
counts by type, per-document word/token length (min/median/p90/max), vocabulary
size and type-token ratio, a shingled-Jaccard near-duplicate rate over passages
(`SHINGLE_SIZE` tokens per shingle, `NEAR_DUPLICATE_THRESHOLD` similarity —
both named constants in `stats.py`, not magic numbers), fact-reference density
per document, the citation graph (facts per document, documents per fact, and
how many facts nothing cites at all), and eval-case counts per family.

**No fabricated reference numbers.** Nothing here is compared against a figure
for "a real enterprise corpus" — there is no such published, auditable
reference, so a comparison against one would be exactly the kind of
unverifiable claim this whole effort exists to stop making. Report, don't
grade. The one legitimate comparison this module makes is `worldloom stats
./corpus --against ./other-corpus`, between two corpora that both actually
exist and can both be opened and recounted by hand.

`examples/retail-close` (the hand-authored golden episode) has no
`artifact_intents` to compile — it predates the compiler pipeline entirely —
so `stats` falls back to reading the rendered files straight off disk for it,
with the manifest's `supporting_fact_ids` standing in for the citations
`passages()` would otherwise compute, and reports near-duplicates as "n/a" (no
compiled passages exist to shingle). Every generated corpus uses the compiled
path and gets the full report, near-duplicates included.

## The shape behind the numbers

`worldloom series ./corpus` decomposes a period-keyed fact series into trend,
season, and residual, and names the periods the first two do not explain.
Multiplicative throughout, so a residual reads as a percentage of normal —
`1.08` is "eight per cent above what the trend and the season predicted".

Outliers are scored on **median absolute deviation**, not a z-score, and the
reason is worth carrying: an outlier inflates the standard deviation it would
be measured against, so several of them mask each other and the detector fails
hardest exactly when there is most to find. The decomposition refits once with
the first pass's outliers replaced by what the first pass expected, so a single
spike cannot tilt the trend that every other month is then judged against.

Read it as a corpus check. An incident month *should* sit outside the pattern;
if it does not, the corpus is asserting a disruption its own figures do not
show. And a decomposition is only meaningful on a history that has one: build
with `--comparatives 23 --trend 0.004` for two years with a direction in them.
Without `--trend` the level is flat by construction, every seasonally-adjusted
month looks like every other, and no question about direction has an answer in
the data.

## The estate as a graph

`worldloom topology ./corpus` reads what depends on what. Services are ranked
by **blast radius** — how much falls over transitively when one does — and
separately by **gates**, how much has no second path to what it serves. Those
are genuinely different: a well-replicated shared platform has a large blast
radius and gates nothing, while a small unloved mapping job can gate the whole
close.

The ranking is derived from the graph rather than declared, so it can disagree
with an archetype's hand-set `criticality_tier`, and that disagreement is a
finding. So is a dependency chain of zero hops: it means the service catalogue
is a flat list of unrelated names rather than a system, and no multi-hop
question about the estate has an answer.

`validate` reads the same graphs, and fails a cycle through any number of hops,
a forked supersession chain (two facts replacing one, which leaves "what is
current" ambiguous), and a provenance loop that uses a different relationship
on each edge. None of those were reachable by the single-edge walks that
preceded them.
