---
title: Structural Diversity
description: Judge whether a batch is structurally varied or one document photocopied, and move that number
read-when: Plans are compiled and the question is batch sameness (shapes, entropy, quotas, near-duplicates)
tags: [diversity, fingerprints, entropy, quotas, near-duplicates]
---

# Diversity

You are here because the corpus is built and compiled (plans exist, sections
are resolved, `ArtifactIR`s are real) and the question is neither "does it
agree with itself" (`worldloom validate`) nor "is it hard to retrieve from"
(`worldloom evaluate`) but "does it look like one document photocopied with
different numbers." This stage answers that.

```bash
worldloom diversity ./corpus
worldloom diversity ./corpus -v
worldloom diversity ./corpus --check-quotas
```

`-v`/`--verbose` adds the per-artifact-type breakdown *and* the actual distinct
shapes within each type: not just how many there are, but the component
sequence each one is. `--check-quotas` runs the declared `Quotas` thresholds
from `compiler/diversity.py` and exits non-zero if any of them fail. The CLI
name mirrors that module's own `check()` function, which it calls directly,
the same way `docs --check` names the thing it checks. Put it in CI: the
corpus is supposed to get *more* varied as generation improves, never less,
and this is the assertion that a change did not quietly walk it backwards.

## The one thing to internalise first

**Diversity is a property of the batch, not of any one artifact.** A single
`Composition` cannot be "diverse" or "repetitive"; those words only mean
anything once there is something to compare it against. Twelve CFO memos with
identical outlines are not twelve defects; they are one defect, visible only
once you look at all twelve side by side. Every measure this stage reports
(entropy, family share, repetition runs, distinct-shape counts) is computed
over the whole set of fingerprints at once, never per artifact, for that
reason. If you find yourself asking "is this artifact diverse", that is
the wrong question; ask whether the *batch it belongs to* is.

## What a fingerprint is

A `Fingerprint` (`compiler/diversity.py`) is a content-addressed summary of one
artifact's *structure*: its component sequence, per-component layout choice,
style genome, density bucket, and section count. Not its prose or
its facts, by design: two artifacts about completely different business units
collapse to the same fingerprint when they read the same way, which is the
property a structural check needs. It is asking "does this look like something
we already produced", not "is this the same document".

`Fingerprint.digest()` is a stable key for that exact shape, built through
`ids.content_key`: SHA-256 over the fields, not Python's builtin `hash()`.
This matters for the same reason it matters everywhere else in this repo:
`hash()` is salted per process, so two runs of the same batch in two different
interpreters would compute *different* digests for identical shapes even
though every individual fingerprint compared equal within either run. Every
test would still pass, because nothing inside one process would ever notice,
and then CI's byte-for-byte replay check would fail on a diff it cannot
explain: the "passes locally, fails in CI" defect determinism exists to
rule out everywhere else in the codebase. `content_key` is content-addressed
instead: the same shape, hashed in any process, on any run, produces the same
digest.

## What the entropy measure is actually over

`DiversityReport.ngram_entropy_bits` is Shannon entropy over the batch's pooled
component-sequence **bigrams**: adjacent pairs, not bare component
frequency. That width was chosen for a reason: a unigram measure (counting
how often each component appears, full stop) cannot tell `(position, evidence,
decision)` apart from `(decision, position, evidence)`. Both sequences use the
same three components the same number of times, so a frequency count over
components alone sees no difference between an artifact that argues normally
and one that opens with its own conclusion. Bigrams are the smallest window
that sees *adjacency*, which component follows which, and adjacency is
the thing "the same outline every time" repeats. A batch of
artifacts that all read `position → evidence → decision` has low bigram
entropy even if every individual component appears with healthy variety on its
own; that gap is the symptom this measure exists to catch.

## What each quota means

`Quotas` (`compiler/diversity.py`) declares four thresholds, checked by
`check()`, which returns every violation rather than raising on the first,
the same contract as `grammar.check`. Defaults, and why each one exists:

- **`min_unique_ratio`** (default 0.35): `distinct_digests / count`. Below the
  floor means fewer than roughly a third of the batch has a shape not already
  seen elsewhere in it.
- **`max_single_family_share`** (default 0.20): the largest fraction of all
  components, pooled across the batch, contributed by any one component
  *family* (the text before a component id's first `.`, e.g.
  `finance.variance_table` → `finance`). Above the ceiling means one family,
  often `core`, the most general-purpose one, is doing most of the batch's
  work, which reads as sameness even when the exact digests differ.
- **`max_repetition_run`** (default 2): the longest run of *consecutive*
  identical shapes, in the order the batch was given. Order-sensitive because
  three identical memos back to back is a worse reading experience
  than the same three shapes spread through a hundred-artifact batch, and a
  distinct-shape count alone cannot tell those two situations apart.
- **`min_entropy_bits`** (default 2.2): the bigram entropy floor described
  above. Catches a batch that technically clears the unique-ratio floor (every
  digest looks different on paper) while still reusing the same adjacent
  component pairs so heavily that a reader would notice the pattern.

An empty batch trivially clears all four. There is nothing yet to be
repetitive or concentrated about, the same stance `grammar.check` takes toward
an artifact type with no grammar entry declared.

## The honest baseline

A 12-period industry corpus of 120 artifacts carried **11 distinct section
shapes** in total, with the `core` component family alone holding **78%** of
all component usage, against the 20% ceiling above. That is the number this
stage exists to move, and it is stated here because it is the reason the
command exists at all: a metric nobody surfaces is a metric nobody notices
regress, and this one had already regressed once before anyone had a command
to see it with.

Do not expect that exact shape from a build you run today. The component
registry this measures against is under active development (new components
and roles change what a composition can settle on), so the honest way to know
the *current* number is to ask the corpus, not this document:

```bash
worldloom diversity ./corpus -v
```

or, for the pinned regression floor this repository holds itself to,
`tests/test_diversity.py`'s `test_regression_the_measured_problem_has_a_floor_to_raise`.
Both read the number off whatever the registry produces right now, which is
the only version of that number that is ever going to be true.

## Reading the report

The printed table is the same shape every stage in this repo uses for a
number a person reads on a terminal (`evaluate.Scorecard`, `world.Summary`):
count and distinct-shape headline, then entropy, max family share with its
name and a bar, then the longest repetition run. With `-v`, a per-artifact-type
section follows naming every distinct shape actually seen (the real component
sequence, not just how many there were), so an agent deciding whether a
regression matters can see *what* repeated, not only that something did.

**A rising distinct-shape count and a falling max-family-share are the good
result**, the mirror image of `evaluate`'s inverted intuition: there, a
*rising* baseline score is bad news because the corpus got easier; here, a
*falling* diversity number is bad news because the corpus got more monotonous.
Neither number should move on its own. A change to how many artifacts a
corpus produces, or which types, will shift the count; only a change to the
component registry, the composer, or a diversity mechanism wired
into generation should shift the *shape*.

## Prose sameness, which is a different failure

`worldloom diversity ./corpus --near-duplicates` groups passages whose *text*
is near-identical and names the artifacts they came from. A batch can carry
twenty distinct structural shapes and still say the same sentences inside all
of them, and the fingerprint has no way to see that. It reads component
sequences only, so that two memos about entirely different business
units do not look different merely for having different numbers in them.

The grouping is exact rather than sampled: `similarity.near_duplicate_pairs`
runs a prefix-filtered similarity join, which returns the same pairs a
full pairwise scan would and misses none, so the clusters are auditable by
hand. It is also the only version of the number that survives Gate 1's scale.
Ten thousand artifacts is fifty million pairs, and the pairwise scan it
replaced would have made the diversity claim uncheckable on the corpora
whose diversity is most at risk.

The report names the group size and the artifacts in it. Three artifacts
sharing a passage across three periods is a template stamped per period; that
is one template to fix, not three documents.

## Selecting, not only auditing

Two functions in `compiler/diversity.py`, and they solve different halves:

- `select(candidates, k=..., seed=...)` picks the *k* structural alternatives
  for **one** artifact that are most unlike each other. Right for offering a
  model a varied menu; silent about the batch. Run independently for a hundred
  artifacts it hands every one of them the same first pick, which is how a
  corpus reaches 120 artifacts and 11 shapes.
- `assign(candidates_per_artifact, committed=...)` picks one shape per artifact
  **across** the batch, each one chosen to be furthest from everything already
  spent, including shapes an earlier period already used, via `committed`, so
  a corpus built one period at a time does not restart the dispersion each time.

`collisions(fingerprints)` is the audit half of the same question: which
artifacts actually share a shape, rather than how many shapes there were.
