"""Corpus statistics: what is actually in the corpus, measured, not graded.

Sibling to `evaluate` and `compiler.diversity`, and a different question again.
`evaluate` asks whether the corpus is hard to retrieve from; `diversity` asks
whether it looks like the same artifact repeated with different numbers; this
asks what is actually in it — how much text, how varied the vocabulary, how
much of it repeats itself, how densely prose cites the facts it rests on. None
of the three can stand in for either of the others: a corpus can be small,
lexically repetitive, and still score badly on the hard evaluation families
(see `evaluate`'s own note that a low score is the good result there), and
knowing that requires all three numbers side by side, not one.

**Report, don't grade.** No number in this module is compared against a
benchmark for "a real enterprise corpus" — there is no such published reference
anyone could audit, so a comparison against one would be exactly the kind of
unverifiable claim a corpus card should not make. The one legitimate comparison
is between two corpora this tool actually built, both fully inspectable —
`diff()`, wired to `worldloom stats --against`.

Deterministic and stably ordered throughout, the same discipline as
`compiler.diversity`: every count walks the corpus in an order the caller
already fixed (`world.artifacts`, `world.facts`, sorted dict keys at the point
of output), never through a `set` or an unsorted `Counter`, so `--json` can be
diffed in CI the way a rendered corpus already is.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import similarity
from .evaluate.bm25 import tokens
from .evaluate.index import Passage, document_texts, passages

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

#: Token-shingle size for the near-duplicate check. Long enough (5 tokens) that
#: two passages sharing a shingle share an actual phrase, not just the common
#: short words ("of the", "for the period") that would otherwise make every
#: passage look like a duplicate of every other one.
SHINGLE_SIZE = 5

#: Two passages count as near-duplicates once their shingle sets' Jaccard
#: similarity reaches this. High rather than "any overlap" — 0.8 is "the same
#: passage with a few numbers changed" (a generator stamping out one template
#: across periods), which is the failure mode this exists to catch. It is not
#: meant to flag two passages that merely discuss the same fact in different
#: words; those should overlap on some shingles and nowhere near this many.
NEAR_DUPLICATE_THRESHOLD = 0.8


@dataclass(frozen=True)
class Distribution:
    """min / median / p90 / max over a sample, plus the sample size.

    `n` travels with the numbers rather than being left for the caller to
    track separately: a distribution over one document and one over a hundred
    should not print identically, and a reader deciding how much to trust a p90
    needs to see the sample it came from.
    """

    minimum: float
    median: float
    p90: float
    maximum: float
    n: int

    @classmethod
    def of(cls, values: list[float]) -> Distribution:
        if not values:
            return cls(0.0, 0.0, 0.0, 0.0, 0)
        ordered = sorted(values)
        n = len(ordered)

        def percentile(fraction: float) -> float:
            # Nearest-rank, not linear interpolation: interpolating between two
            # observed document lengths manufactures a length no document
            # actually has, which reads as more precise than an eleven-document
            # sample supports. Nearest-rank always reports a value that is
            # really in the sample.
            index = min(n - 1, max(0, math.ceil(fraction * n) - 1))
            return ordered[index]

        return cls(minimum=ordered[0], median=percentile(0.5), p90=percentile(0.9), maximum=ordered[-1], n=n)

    def as_dict(self) -> dict[str, float | int]:
        return {"min": self.minimum, "median": self.median, "p90": self.p90, "max": self.maximum, "n": self.n}

    def __str__(self) -> str:
        if not self.n:
            return "n/a (no documents)"
        return f"min {self.minimum:g}  median {self.median:g}  p90 {self.p90:g}  max {self.maximum:g}  (n={self.n})"


def _shingles(text: str) -> frozenset[tuple[str, ...]]:
    """Token k-shingles of *text*, `SHINGLE_SIZE` tokens each.

    Built from the same tokenizer the retrievers use (`bm25.tokens` — lowercase,
    split on non-alphanumeric runs, no stemming), so "near-duplicate" means the
    same thing here as it does to the thing that would actually be confused by
    it: a retriever indexing this corpus.
    """
    return similarity.shingles(tokens(text), SHINGLE_SIZE)


def _near_duplicate_reading(
    pool: list[Passage],
) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, ...], ...]]:
    """``(pairs, groups)`` for *pool*, from one pass of the join.

    Both readings come from the same pair list because they are the same
    measurement asked two ways, and running the join twice to answer it twice
    would let the pair count and the group count disagree about a corpus if
    anything about the shingling ever became order-dependent.
    """
    pairs = similarity.near_duplicate_pairs(
        [_shingles(p.text) for p in pool], NEAR_DUPLICATE_THRESHOLD
    )
    return pairs, similarity.clusters(pairs, len(pool))


def near_duplicate_clusters(pool: list[Passage]) -> tuple[tuple[int, ...], ...]:
    """Groups of mutually near-duplicate passages, largest first.

    The finding behind the rate. `_near_duplicates` says a tenth of the pairs
    repeat; this says *which* passages they are, so an author can look at the
    eleven that are one template and fix the template rather than guess.
    """
    return _near_duplicate_reading(pool)[1]


def _near_duplicates(pool: list[Passage]) -> tuple[int, int]:
    """``(near-duplicate pairs, total pairs)`` among *pool*, by shingled Jaccard.

    Still the exact count — the same pairs a full pairwise scan returns, not a
    MinHash estimate of them — because the premise of this whole report is a
    number a skeptical reader can recompute by hand from the passage text. What
    changed is only how long getting it takes: `similarity.near_duplicate_pairs`
    reaches the same answer through a prefix-filtered similarity join instead of
    comparing all n(n-1)/2 pairs.

    That mattered more than it looked. The O(n^2) version defended itself on
    the grounds that no corpus this tool renders is big enough for the cost to
    bite — which was true of a 120-artifact close and is precisely what
    build-order §12's Gate 1 (10,000 artifacts, fifty million pairs) exists to
    stop being true. A diversity number that silently becomes uncomputable at
    the scale where diversity is most at risk is worse than no number.

    The *rate* built from this pair count is a different matter — see
    `Stats.near_duplicate_share` for why the pair count needs a companion once
    a corpus is large.
    """
    total_pairs = len(pool) * (len(pool) - 1) // 2
    return len(_near_duplicate_reading(pool)[0]), total_pairs


def _texts_and_citations(world: World) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Per-document text and per-document cited-fact-ids, from whatever the world has.

    The compiled path (`world.artifact_irs` present, which the CLI arranges by
    calling `world.compile()` when needed — every generated corpus has
    `artifact_intents` to compile) is preferred: `document_texts()` and
    `passages()` are the same substitution-and-table-flattening `evaluate`
    scores against, so a document's citation count here agrees with what a
    retriever could actually find.

    `examples/retail-close`, the hand-authored golden episode, has no
    `artifact_intents` at all — Gate A fixed the corpus contract by hand before
    the compiler pipeline existed, so there is nothing for `compile()` to run —
    and falls back to reading the rendered bytes straight off disk, with the
    manifest's `supporting_fact_ids` standing in for the citations `passages()`
    would otherwise compute. A binary rendering (xlsx, docx, pdf, pptx) in that
    fallback has no compiled IR and is not text on disk either, so it is
    skipped here (counted in `documents_by_type` regardless — that count comes
    from the manifest directly, not from this dict).
    """
    if world.artifact_irs:
        texts = document_texts(world)
        cited: dict[str, set[str]] = {doc_id: set() for doc_id in texts}
        for passage in passages(world):
            cited.setdefault(passage.artifact_id, set()).update(passage.fact_ids)
        return texts, cited

    if world.root is None:
        return {}, {}

    texts: dict[str, str] = {}
    cited = {}
    for entry in world.artifacts:
        if not entry.path:
            continue
        if not (entry.media_type.startswith("text/") or entry.media_type == "application/json"):
            continue
        try:
            texts[entry.id] = (world.root / entry.path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        cited[entry.id] = set(entry.supporting_fact_ids)
    return texts, cited


@dataclass(frozen=True)
class Stats:
    """Everything `worldloom stats` reports, computed once."""

    document_count: int
    documents_by_type: dict[str, int]
    word_lengths: Distribution
    token_lengths: Distribution
    vocabulary_size: int
    total_tokens: int
    type_token_ratio: float
    passage_count: int
    near_duplicate_threshold: float
    near_duplicate_pairs: int
    near_duplicate_total_pairs: int
    near_duplicate_rate: float
    near_duplicate_groups: int
    """How many distinct templates the corpus is repeating."""
    near_duplicate_grouped_passages: int
    """How many passages are inside one of those groups."""
    largest_near_duplicate_group: int
    """How many times the worst-repeated template is repeated."""
    facts_per_document: Distribution
    fact_density: Distribution
    """Facts cited per 100 tokens, per document — how densely prose cites the
    ledger, normalised so a long document does not automatically look like it
    cites more just for being long."""
    fact_count: int
    uncited_fact_count: int
    documents_per_fact: Distribution
    """Over facts cited at least once. A fact cited by zero documents is counted
    in `uncited_fact_count`, not folded into this distribution's minimum — a
    true minimum of 0 would say nothing about the facts that *are* used."""
    evals_by_type: dict[str, int]
    eval_count: int

    @property
    def near_duplicate_share(self) -> float:
        """The fraction of passages sitting inside a near-duplicate group.

        The reading to quote once a corpus is large, because
        `near_duplicate_rate` stops distinguishing anything there and the
        arithmetic says why. Take *K* templates each stamped out *m* times over
        *n = K·m* passages. The qualifying pairs are the within-template ones,
        ``K·m(m-1)/2``, against ``n(n-1)/2`` in total, so the rate is exactly
        ``(m-1)/(K·m-1)`` — which **saturates at 1/K**. Both denominators are
        quadratic in the repetition, and they cancel. At eight templates the
        rate reads 0.097 when each is copied four times and 0.124 when each is
        copied ninety-six times: the corpus got twenty-four times more
        repetitive and the number moved by under three points, because it never
        had anywhere to go. It reports how many templates a corpus repeats,
        and is almost blind to how hard it repeats them.

        Measured on this engine's own retail corpus, growing the history alone
        (1, 6, 12, 24, 48 and 96 periods): the rate reads 0.000, 0.005, 0.007,
        0.008, 0.007, 0.007 — flat, and flattest exactly where the repetition
        got worst — while the largest single duplicate family goes 0, 5, 11,
        23, 47, 95 and this share goes 0.00, 0.17, 0.27, 0.28, 0.37, 0.37. At
        96 periods one template covers ninety-five passages and the rate is
        indistinguishable from what it read when that template covered five.

        Both are kept rather than one replacing the other. The rate is still
        the honest answer to "how much of this corpus is redundant against the
        rest of it", which is the question a retriever asks; this is the answer
        to "how much of it is a photocopy", which is the question an author
        asks. `measure` below reports the second, cluster by cluster.
        """
        return (self.near_duplicate_grouped_passages / self.passage_count) if self.passage_count else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_count": self.document_count,
            "documents_by_type": self.documents_by_type,
            "word_length": self.word_lengths.as_dict(),
            "token_length": self.token_lengths.as_dict(),
            "vocabulary_size": self.vocabulary_size,
            "total_tokens": self.total_tokens,
            "type_token_ratio": self.type_token_ratio,
            "near_duplicate": {
                "shingle_size": SHINGLE_SIZE,
                "threshold": self.near_duplicate_threshold,
                "passages_compared": self.passage_count,
                "pairs": self.near_duplicate_pairs,
                "total_pairs": self.near_duplicate_total_pairs,
                "rate": self.near_duplicate_rate,
                "groups": self.near_duplicate_groups,
                "grouped_passages": self.near_duplicate_grouped_passages,
                "largest_group": self.largest_near_duplicate_group,
                "share": self.near_duplicate_share,
            },
            "facts_per_document": self.facts_per_document.as_dict(),
            "fact_density_per_100_tokens": self.fact_density.as_dict(),
            "fact_count": self.fact_count,
            "uncited_fact_count": self.uncited_fact_count,
            "documents_per_fact": self.documents_per_fact.as_dict(),
            "evals_by_type": self.evals_by_type,
            "eval_count": self.eval_count,
        }

    def __str__(self) -> str:
        width = 24
        lines = [f"Corpus statistics — {self.document_count} document(s)", "─" * 60, "  by type"]
        for kind, n in self.documents_by_type.items():
            lines.append(f"    {kind:<{width}} {n}")
        lines += ["─" * 60]
        lines.append(f"  {'words/document'.ljust(width)} {self.word_lengths}")
        lines.append(f"  {'tokens/document'.ljust(width)} {self.token_lengths}")
        lines.append(
            f"  {'vocabulary'.ljust(width)} {self.vocabulary_size} distinct / {self.total_tokens} total tokens"
            f", TTR {self.type_token_ratio:.3f}"
        )
        if self.near_duplicate_total_pairs:
            lines.append(
                f"  {'near-duplicates'.ljust(width)} {self.near_duplicate_pairs}/{self.near_duplicate_total_pairs}"
                f" passage pair(s) ≥{self.near_duplicate_threshold:.0%} shingled Jaccard"
                f" ({self.near_duplicate_rate:.1%})"
            )
            # Printed on its own line rather than folded into the one above,
            # because the two disagree on a large corpus and a reader has to see
            # both to notice. See `near_duplicate_share`.
            lines.append(
                f"  {'repeated passages'.ljust(width)} {self.near_duplicate_grouped_passages}/{self.passage_count}"
                f" ({self.near_duplicate_share:.1%}) in {self.near_duplicate_groups} group(s),"
                f" largest {self.largest_near_duplicate_group}"
            )
        else:
            lines.append(f"  {'near-duplicates'.ljust(width)} n/a (no compiled passages for this corpus)")
        lines.append(f"  {'facts/document'.ljust(width)} {self.facts_per_document}")
        lines.append(f"  {'fact density'.ljust(width)} {self.fact_density}  (cited facts per 100 tokens)")
        lines.append(
            f"  {'facts cited'.ljust(width)} {self.fact_count - self.uncited_fact_count}/{self.fact_count}"
            f" ({self.uncited_fact_count} never cited by a rendered document)"
        )
        lines.append(f"  {'documents/fact'.ljust(width)} {self.documents_per_fact}  (over cited facts only)")
        lines += ["─" * 60, "  eval cases by family"]
        for kind, n in self.evals_by_type.items():
            lines.append(f"    {kind:<{width}} {n}")
        lines.append(f"    {'total'.ljust(width)} {self.eval_count}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return str(self)


def compute(world: World) -> Stats:
    """Compute every statistic above for *world*.

    Raises the same way `evaluate.score` and `evaluate.passages` do when there
    is nothing to measure — a corpus that has never been compiled or rendered
    has no text to report on, and a silent empty report would look like a
    corpus with zero of everything rather than one that was never given a
    chance to have anything.
    """
    texts, fact_ids_by_document = _texts_and_citations(world)
    if not texts:
        raise ValueError("nothing to compute statistics from — render or compile the corpus first")

    # Document counts and types come from the manifest, not from `texts`: a
    # binary rendering with nothing decodable is still a document the corpus
    # ships, and hiding it here would make `documents_by_type` disagree with
    # `worldloom inspect`.
    documents_by_type = dict(sorted(Counter(entry.artifact_type for entry in world.artifacts).items()))

    token_lists = {doc_id: tokens(text) for doc_id, text in texts.items()}
    word_counts = [float(len(text.split())) for text in texts.values()]
    token_counts = [float(len(t)) for t in token_lists.values()]

    vocabulary: set[str] = set()
    total_tokens = 0
    for token_list in token_lists.values():
        vocabulary.update(token_list)
        total_tokens += len(token_list)
    type_token_ratio = (len(vocabulary) / total_tokens) if total_tokens else 0.0

    pool = passages(world) if world.artifact_irs else []
    # One join, both readings. Calling `_near_duplicates` and then
    # `near_duplicate_clusters` would shingle and join the whole pool twice for
    # two halves of one answer — which is the cost the join exists to avoid.
    near_pairs_found, near_groups = _near_duplicate_reading(pool)
    near_total = len(pool) * (len(pool) - 1) // 2

    facts_per_document: list[float] = []
    fact_density: list[float] = []
    documents_per_fact_counter: Counter[str] = Counter()
    for doc_id, fact_ids in fact_ids_by_document.items():
        facts_per_document.append(float(len(fact_ids)))
        token_n = len(token_lists.get(doc_id, ()))
        fact_density.append((len(fact_ids) / token_n * 100) if token_n else 0.0)
        for fact_id in fact_ids:
            documents_per_fact_counter[fact_id] += 1

    all_fact_ids = {fact.id for fact in world.facts}
    cited_fact_ids = set(documents_per_fact_counter)
    documents_per_fact_values = [
        float(documents_per_fact_counter[fact_id]) for fact_id in sorted(cited_fact_ids)
    ]

    evals_by_type = dict(sorted(Counter(case.evaluation_type.value for case in world.evaluations).items()))

    return Stats(
        document_count=len(world.artifacts),
        documents_by_type=documents_by_type,
        word_lengths=Distribution.of(word_counts),
        token_lengths=Distribution.of(token_counts),
        vocabulary_size=len(vocabulary),
        total_tokens=total_tokens,
        type_token_ratio=type_token_ratio,
        passage_count=len(pool),
        near_duplicate_threshold=NEAR_DUPLICATE_THRESHOLD,
        near_duplicate_pairs=len(near_pairs_found),
        near_duplicate_total_pairs=near_total,
        near_duplicate_rate=(len(near_pairs_found) / near_total) if near_total else 0.0,
        near_duplicate_groups=len(near_groups),
        near_duplicate_grouped_passages=sum(len(group) for group in near_groups),
        largest_near_duplicate_group=max((len(group) for group in near_groups), default=0),
        facts_per_document=Distribution.of(facts_per_document),
        fact_density=Distribution.of(fact_density),
        fact_count=len(all_fact_ids),
        uncited_fact_count=len(all_fact_ids - cited_fact_ids),
        documents_per_fact=Distribution.of(documents_per_fact_values),
        evals_by_type=evals_by_type,
        eval_count=len(world.evaluations),
    )


def diff(a: Stats, b: Stats, *, a_label: str = "a", b_label: str = "b") -> str:
    """A metric-by-metric side-by-side of two corpora's statistics.

    The one comparison this module makes: never against a fabricated "real
    enterprise corpus" figure, always between two corpora this tool actually
    built and either party could open and recount by hand.
    """
    rows: list[tuple[str, object, object]] = [
        ("documents", a.document_count, b.document_count),
        ("words/document (median)", a.word_lengths.median, b.word_lengths.median),
        ("tokens/document (median)", a.token_lengths.median, b.token_lengths.median),
        ("vocabulary size", a.vocabulary_size, b.vocabulary_size),
        ("type-token ratio", round(a.type_token_ratio, 4), round(b.type_token_ratio, 4)),
        ("near-duplicate rate", round(a.near_duplicate_rate, 4), round(b.near_duplicate_rate, 4)),
        # The row that actually moves when a corpus gets more repetitive; the
        # rate above barely does. See `Stats.near_duplicate_share`.
        ("repeated passage share", round(a.near_duplicate_share, 4), round(b.near_duplicate_share, 4)),
        ("largest duplicate group", a.largest_near_duplicate_group, b.largest_near_duplicate_group),
        ("fact density (median, /100 tok)", round(a.fact_density.median, 2), round(b.fact_density.median, 2)),
        ("facts cited", a.fact_count - a.uncited_fact_count, b.fact_count - b.uncited_fact_count),
        ("eval cases", a.eval_count, b.eval_count),
    ]
    width = max(len(label) for label, _, _ in rows)
    lines = [f"  {'metric'.ljust(width)}  {a_label:>16}  {b_label:>16}", "─" * (width + 38)]
    for label, a_value, b_value in rows:
        lines.append(f"  {label.ljust(width)}  {str(a_value):>16}  {str(b_value):>16}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The repetition measurement, as one reading
# ---------------------------------------------------------------------------
#
# Formerly the "measure" step of `worldloom refine`, a rewrite loop this
# repository deleted: the loop was built and gated against `DeterministicProvider`
# template prose, and a five-world proof run on real model prose measured its
# target — repeated passages — at zero in every world (0/46, 0/50, 0/52, 0/46,
# 0/43). The repetition it fought was an artifact of the deterministic fake, not
# of any real writer. The *measurement* survives the loop because it answers a
# question independent of it — "what does this corpus repeat, right now?" — and
# `worldloom diversity` and the `measure_corpus` MCP tool both report it.


@dataclass(frozen=True)
class Measurement:
    """What the corpus repeats, right now."""

    passages: int
    duplicate_pairs: int
    clusters: tuple[tuple[int, ...], ...]
    """Groups of mutually near-duplicate passages, by index into ``pool``."""
    pool: tuple[Passage, ...]
    artifacts: int
    distinct_shapes: int
    shape_collisions: tuple[tuple[str, tuple[int, ...]], ...]
    uncomposable: tuple[tuple[str, str, str, str], ...] = ()
    """``(intent_id, artifact_type, code, detail)`` for artifacts whose plan the
    compiler cannot satisfy, and which therefore have no shape to fingerprint.

    Carried rather than raised. `artifacts` and `distinct_shapes` are counts over
    what *could* be fingerprinted, so a corpus with unsatisfiable plans would
    otherwise report a shape census that quietly covered a subset without either
    reading saying so. Empty on a corpus with no such artifact, which is every
    corpus this repository ships except one built with ``--distractors``."""

    @property
    def duplicate_rate(self) -> float:
        """Duplicate pairs as a fraction of all pairs."""
        total = self.passages * (self.passages - 1) // 2
        return self.duplicate_pairs / total if total else 0.0

    @property
    def repeated_passages(self) -> int:
        """How many passages sit in some duplicate cluster — the number a
        reader cares about. A pair count squares with cluster size and so
        overstates a single eleven-way repeat as fifty-five problems."""
        return sum(len(group) for group in self.clusters)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passages": self.passages,
            "duplicate_pairs": self.duplicate_pairs,
            "duplicate_rate": round(self.duplicate_rate, 6),
            "repeated_passages": self.repeated_passages,
            "clusters": [
                {
                    "size": len(group),
                    "artifacts": sorted({self.pool[i].artifact_id for i in group}),
                    "excerpt": self.pool[group[0]].text[:160],
                }
                for group in self.clusters
            ],
            "artifacts": self.artifacts,
            "distinct_shapes": self.distinct_shapes,
            "shape_collisions": [
                {"digest": digest, "count": len(members)}
                for digest, members in self.shape_collisions
            ],
            "uncomposable": [
                {"artifact_id": intent_id, "artifact_type": artifact_type,
                 "code": code, "detail": detail}
                for intent_id, artifact_type, code, detail in self.uncomposable
            ],
        }

    def __str__(self) -> str:
        line = (
            f"Repetition — {self.repeated_passages} of {self.passages} passage(s) "
            f"in {len(self.clusters)} duplicate group(s); "
            f"{self.distinct_shapes} distinct shape(s) across {self.artifacts} artifact(s)"
        )
        if self.uncomposable:
            # Appended to the same line rather than left to `as_dict`: the shape
            # census above is over `self.artifacts`, and a reader who is not told
            # the denominator excludes something will read it as the whole corpus.
            line += f" ({len(self.uncomposable)} more have no composable shape)"
        return line


def measure(world: World) -> Measurement:
    """Prose repetition and structural repetition together, in one reading.

    Together because they are different failures with different fixes: twenty
    distinct shapes can still say the same sentences inside all of them, and one
    shape used twenty times can carry twenty genuinely different arguments. A
    reading that reported only one of them would declare victory over the other.
    """
    from .compiler import diversity as diversity_module

    pool = tuple(passages(world))
    pairs, groups = _near_duplicate_reading(list(pool))

    shapes = census(world)
    collisions = diversity_module.collisions(list(shapes.fingerprints))
    distinct = len({fp.digest() for fp in shapes.fingerprints})

    return Measurement(
        passages=len(pool),
        duplicate_pairs=len(pairs),
        clusters=groups,
        pool=pool,
        artifacts=len(shapes.fingerprints),
        distinct_shapes=distinct,
        shape_collisions=collisions,
        uncomposable=shapes.uncomposable,
    )


@dataclass(frozen=True)
class ShapeCensus:
    """Every artifact's structural shape, and every artifact that has none.

    The two lists are the point. A shape census that reported only the shapes it
    found would be a census over a silently-chosen subset, and the number a
    reader takes from it — "eight distinct shapes across thirty-five artifacts"
    — would be wrong in the denominator rather than merely incomplete.
    """

    fingerprints: tuple[Any, ...]
    """``compiler.diversity.Fingerprint`` rows. Typed loosely so this module
    keeps its compiler imports inside the functions that need them."""
    artifact_ids: tuple[str, ...]
    """Parallel to ``fingerprints``. Kept beside them rather than recovered by
    re-walking the IR, because `diversity.collisions` returns *positions* and a
    position is only useful if it can be turned back into the artifact an author
    has to open."""
    uncomposable: tuple[tuple[str, str, str, str], ...]
    """``(artifact_id, artifact_type, code, detail)``, in corpus order."""


def census(world: World) -> ShapeCensus:
    """Structural fingerprints for every compilable artifact, and what refused.

    Anything neither the workbook nor the document renderer claims is a record
    projection rather than a component composition and has no shape to
    fingerprint — the same split ``worldloom diversity`` draws.

    Public, and `cli.py`'s `diversity` calls it, where the CLI used to hold a
    separate copy of this walk on the stated principle that a library must not
    depend on its own front end. That principle is intact — the dependency still
    runs one way — but the duplication was not free: every reader of the census
    has to agree on which artifacts are in it, and additionally on how an
    unsatisfiable plan is *counted*. Two copies of that were how one command
    could crash on a corpus while another reported on it.

    Returns the failures rather than raising them; see `compose.try_compose` for
    why a survey is the caller shape that needs it.
    """
    from .compiler import diversity as diversity_module
    from .compiler.compose import Composition, plan_from_ir, try_compose
    from .render.docx import HANDLES as DOCX_TYPES
    from .render.xlsx import HANDLES as XLSX_TYPES

    out: list[Any] = []
    ids: list[str] = []
    refused: list[tuple[str, str, str, str]] = []
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        # A workbook composes with fmt="xlsx" — its lineage sheet is xlsx-only,
        # so composing it as "docx" refuses on a component that does not fit.
        # Every other handled type composes with fmt="docx". Anything neither
        # renderer claims (a Jira, Confluence, or ServiceNow bundle) is a record
        # projection rather than a component composition (see
        # `docs/artifact-compiler.md` §9.5) and has no shape to fingerprint —
        # the same split `tests/test_diversity.py`'s own regression fixture
        # draws. Not counted as `uncomposable` either: it is not a defect, it is
        # a kind of artifact this census has nothing to say about.
        if intent.artifact_type in XLSX_TYPES:
            fmt = "xlsx"
        elif intent.artifact_type in DOCX_TYPES:
            fmt = "docx"
        else:
            continue
        plan = plan_from_ir(
            ir, artifact_type=intent.artifact_type, size_class=intent.size_profile
        )
        composed = try_compose(plan, fmt=fmt)
        if isinstance(composed, Composition):
            out.append(diversity_module.fingerprint(composed))
            ids.append(ir.id)
        else:
            # `ir.id`, not `composed.intent_id`: the plan's `intent_id` is the
            # intent's, and a caller told an artifact is unfingerprintable needs
            # the id it can go and open. They coincide today and are not required
            # to.
            refused.append((ir.id, intent.artifact_type, composed.code, composed.detail))
    return ShapeCensus(tuple(out), tuple(ids), tuple(refused))


__all__ = [
    "Distribution",
    "Measurement",
    "ShapeCensus",
    "Stats",
    "census",
    "compute",
    "diff",
    "measure",
    "SHINGLE_SIZE",
    "NEAR_DUPLICATE_THRESHOLD",
]
