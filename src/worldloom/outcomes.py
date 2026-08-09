"""Choosing worlds by what came out of them, not by the parameters that went in.

``mosaic`` disperses in **parameter** space: it covers a hypercube of headcount,
span, depth, estate and physics with a Halton sequence and takes the *N*
furthest apart. That is a good algorithm pointed at a proxy. It has never once
looked at the corpora. Two configurations far apart in parameter space can
produce corpora that measure identically — a margin band that no figure in
either world happens to fall in, an estate size that changes nine nodes into
eleven — and two configurations close together can differ sharply, because a
single extra reporting level changes who signs what and therefore what the
evaluation generator can ask. The mosaic cannot tell, because it never asks.

This module runs the loop that a *dataset* needs rather than the one a
*parameter sweep* needs:

    generate candidates → measure the corpora → select on the measurements

Nothing here is new machinery. ``dispersion.farthest_first`` already implements
max-min selection and ``stats``, ``graphs`` and ``models`` already implement
every measurement. What was missing was pointing the first at the second: the
selection runs over a **measurement vector** — what the corpus turned out to
contain — instead of over the coordinates that were fed in.

**What is measured, and why only these.** Every reading below is available
from a *compiled* world: built, one or more episodes run, ``compile()`` called.
No narration, no rendering, no model call, no file written. That is a hard
constraint rather than a convenience — a selection loop that costs a narrated,
rendered corpus per candidate costs more than building the mosaic it is trying
to improve, and nobody would run it. The consequence is stated rather than
hidden: on an un-narrated corpus the prose-level readings (``passages``,
``duplicate_rate``) are readings of the *plan*, thin and mostly flat. The
readings that carry the signal are the ones that are already final before a
word is written — the organisation, the fact ledger, the dependency graph, and
above all the **evaluation questions**, which the evaluation generator mints at
episode time and which are the dataset's actual product.

**The Goodhart line, drawn in code.** Two objectives are available here and
they are not equally safe:

* Selecting for *spread and coverage* — the default, ``select()``. It has no
  model of what a good corpus is, only of what a varied set of corpora is. A
  set chosen this way cannot be overfit to anything, because nothing was fit.
* Selecting for *"hardest against retriever X"* — ``hardest()``. This is
  optimising a dataset against a specific weak retriever, and it works: it will
  reliably hand back the worlds BM25 does worst on. What it produces is a
  corpus shaped around BM25's blind spots, which is a benchmark for BM25 and
  not for retrieval. It is opt-in, it is never reachable from ``select()``, and
  it warns at the call.

``docs/sdk.md`` has said "outcome selection should be a filter or Pareto
decision, not an optimization loop against one baseline" in prose since the SDK
shipped. This is that sentence with a type signature.

**Determinism.** No clock, no ``random``, no UUID, and no ``set`` iteration
decides anything: every dict this module returns is built from a sorted key
list, the distance matrix is a nested tuple indexed by position, and
``farthest_first``'s tie-breaking (lowest index, strict ``>``) is the same one
the parameter mosaic relies on. The wall-clock cost of the loop is reported by
``tools/outcome_selection.py``, which is not library code, because a timing is
not a measurement of the corpus.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .dispersion import farthest_first
from .stats import NEAR_DUPLICATE_THRESHOLD, SHINGLE_SIZE

__all__ = [
    "QUESTION_WEIGHT",
    "Pool",
    "Reading",
    "distances",
    "hardest",
    "pool",
    "read",
    "report",
    "select",
    "shape_vector",
]

#: How much the questions weigh against everything else in the distance.
#:
#: One, meaning the question-overlap term is worth as much as the entire metric
#: block combined. That is deliberate and it is the one free parameter in this
#: module, so it is named rather than buried: the metric block is normalised to
#: a mean per-dimension distance in [0, 1] and the question term is a fraction
#: in [0, 1], so at 1.0 a pair of worlds that measure identically but ask
#: disjoint questions is exactly as far apart as a pair that asks the same
#: questions of structurally opposite companies.
#:
#: The justification is that the questions *are* the dataset. Everything else
#: measured here is a property of the corpus a question would be asked about;
#: two worlds whose evaluation sets are the same forty sentences are two
#: presentations of one benchmark however different their org charts.
QUESTION_WEIGHT = 1.0

# `NEAR_DUPLICATE_THRESHOLD` and `SHINGLE_SIZE` are imported from `stats` rather
# than restated here so that "near-duplicate" means in this module exactly what
# it means in `stats`, in `evaluate.across`, and to a retriever — the argument
# `similarity.shingles` makes one level down. A second threshold would let a
# selection call two questions distinct that the survey measuring the selection
# calls the same.


# ---------------------------------------------------------------------------
# One candidate, measured
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """What one candidate corpus turned out to contain.

    ``metrics`` is the vector selection runs over; ``questions`` and their
    shingles are held separately because question overlap is a *pairwise*
    property and cannot be folded into a per-candidate coordinate. A world's
    forty questions are not a number, and reducing them to one (a count, a
    vocabulary size) would throw away exactly the thing that distinguishes two
    worlds asking the same forty sentences from two worlds asking different
    ones.
    """

    name: str
    seed: int
    metrics: Mapping[str, float]
    questions: tuple[str, ...]
    shingles: tuple[frozenset[tuple[str, ...]], ...]
    """Token shingles per question, parallel to ``questions``."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "seed": self.seed,
            "questions": len(self.questions),
            "metrics": {key: self.metrics[key] for key in sorted(self.metrics)},
        }


def shape_vector(world: Any) -> dict[str, Any]:
    """The organisation, the ledger and the dependency graph, as eight numbers.

    Public and shared with ``sdk.Built.measure``, which is where these eight
    were first written down and which now delegates here. One definition
    rather than two: a loop that filters on ``measure()["chokepoints"]`` and a
    loop that selects on the same quantity have to agree about what a
    chokepoint is, and two copies of this walk were how they could stop
    agreeing.

    Needs no compilation — a freshly built world with no episode run answers
    every one of these, which is what lets ``sdk.built()`` filter before paying
    for an episode.
    """
    from . import graphs

    people = [p for p in world.people if p.left is None]
    dependency = graphs.dependency_graph(world)
    return {
        "people": len(people),
        "titles": len({p.title for p in people}),
        "facts": len(world.facts),
        "artifacts": len(world.artifact_intents),
        "evaluations": len(world.evaluations),
        "nodes": dependency.number_of_nodes(),
        "chokepoints": len(graphs.chokepoints(dependency)),
        "longest_chain": len(graphs.longest_chain(dependency)),
    }


def _mix(values: Sequence[str], keys: Sequence[str], prefix: str) -> dict[str, float]:
    """Shares of *values* over a fixed, sorted *keys* list.

    Shares rather than counts, and over a **fixed** key list rather than over
    whichever keys this world happens to use. Both matter. Counts would make
    every mix coordinate a restatement of ``evaluations``, so a world with
    twice as many cases would read as far from every other world in eight
    dimensions at once for one reason. A per-world key list would give two
    candidates vectors of different lengths, which is the failure
    ``sdk._vectors`` documents one module over.
    """
    total = len(values) or 1
    tally = {key: 0 for key in keys}
    for value in values:
        if value in tally:
            tally[value] += 1
    return {f"{prefix}{key}": tally[key] / total for key in keys}


def _difficulty_keys() -> tuple[str, ...]:
    # Fixed rather than read off the corpus, for `_mix`'s second reason. These
    # are the three `generators.evaluation` labels; a fourth would show up as a
    # dimension nothing moves in rather than as a crash.
    return ("easy", "hard", "medium")


def read(world: Any, *, name: str = "", seed: int = 0) -> Reading:
    """Measure one compiled corpus.

    *world* must have had at least one episode run and ``compile()`` called —
    ``pool()`` arranges both. It need not have been narrated or rendered, and
    deliberately is not: see the module docstring for what that costs in
    signal and buys in wall-clock.
    """
    from . import similarity, stats
    from .evaluate.bm25 import tokens
    from .models import EvaluationType

    metrics: dict[str, float] = {
        key: float(value) for key, value in shape_vector(world).items()
    }

    # `stats.measure` and `stats.compute` are the two instruments this
    # repository already owns for "what is in this corpus". Both are called
    # because they answer different halves — repetition and structure from the
    # first, lexical texture and citation density from the second — and neither
    # is a projection of the other.
    repetition = stats.measure(world)
    metrics["passages"] = float(repetition.passages)
    metrics["distinct_shapes"] = float(repetition.distinct_shapes)
    metrics["duplicate_rate"] = float(repetition.duplicate_rate)
    metrics["repeated_passage_share"] = (
        repetition.repeated_passages / repetition.passages if repetition.passages else 0.0
    )

    texture = stats.compute(world)
    metrics["vocabulary"] = float(texture.vocabulary_size)
    metrics["type_token_ratio"] = float(texture.type_token_ratio)
    metrics["tokens_median"] = float(texture.token_lengths.median)
    metrics["fact_density_median"] = float(texture.fact_density.median)
    metrics["cited_fact_share"] = (
        (texture.fact_count - texture.uncited_fact_count) / texture.fact_count
        if texture.fact_count else 0.0
    )

    cases = list(world.evaluations)
    # The evaluation *mix*, not the per-family pass rate. A pass rate needs a
    # retriever, and a retriever in the default objective is the Goodhart
    # failure this module exists to keep out of it — `evaluate.across`'s family
    # spread is reported beside a selection, never used to make one.
    metrics.update(_mix(
        [case.evaluation_type.value for case in cases],
        sorted(family.value for family in EvaluationType),
        "family:",
    ))
    metrics.update(_mix(
        [case.difficulty for case in cases], _difficulty_keys(), "difficulty:",
    ))

    questions = tuple(case.question for case in cases)
    return Reading(
        name=name,
        seed=seed,
        metrics={key: metrics[key] for key in sorted(metrics)},
        questions=questions,
        shingles=tuple(
            similarity.shingles(tokens(question), SHINGLE_SIZE) for question in questions
        ),
    )


# ---------------------------------------------------------------------------
# A pool of candidates, measured
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pool:
    """Every candidate, measured, with the worlds that produced the readings.

    The worlds are kept rather than discarded because a caller who selects a
    subset has already paid to build it — handing back indices into a list of
    descriptions and making them build again would double the cost of the loop
    and, worse, would only be *sound* if the rebuild were byte-identical, which
    is a property to rely on rather than to require.
    """

    readings: tuple[Reading, ...]
    worlds: tuple[Any, ...]
    sources: tuple[Any, ...]
    """Whatever was measured — ``sdk.Blueprint`` or ``mosaic.Variant`` — in the
    same order. This module never inspects them; it carries them so the caller
    gets its own vocabulary back."""

    def __len__(self) -> int:
        return len(self.readings)

    def select(self, count: int, *, question_weight: float = QUESTION_WEIGHT) -> tuple[int, ...]:
        """The *count* candidates least like each other, by measurement."""
        return select(self.readings, count, question_weight=question_weight)

    def hardest(self, count: int, *, retriever: str = "bm25", k: int = 5) -> tuple[int, ...]:
        """The *count* candidates one baseline retriever does worst on. **Opt-in.**

        .. warning::

           This is the unsafe objective, and it is unsafe in a way that looks
           like success. Selecting the worlds a specific retriever fails most
           produces a set shaped around *that retriever's* blind spots: BM25 is
           a bag of words with no stemming and fixed, deliberately untuned
           ``K1``/``B`` (see ``evaluate/bm25.py``), so "hard for BM25" mostly
           means "phrased with vocabulary that does not overlap the passage".
           A dataset selected this way will show a large, real, reproducible
           gap between BM25 and anything better — and that gap is a measurement
           of BM25, not of the corpus. Fit a second retriever on it and the
           advantage does not transfer, because nothing about the selection was
           ever about retrieval difficulty in general.

           ``select()`` cannot reach this. It is a separate method, it takes
           the retriever's name as a required-by-default argument so the caller
           has to name what they are overfitting to, and it emits a
           ``UserWarning`` at the call. Use it to *investigate* a retriever, and
           report a corpus chosen this way as what it is.

        Requires scoring every candidate, which the default objective does not.
        """
        warnings.warn(
            f"outcomes.hardest() selects against a single retriever ({retriever!r})."
            " The resulting set is a benchmark for that retriever's blind spots"
            " rather than a more diverse dataset; outcomes.select() is the safe"
            " objective. See outcomes.Pool.hardest's docstring.",
            UserWarning,
            stacklevel=2,
        )
        return hardest(self.worlds, count, retriever=retriever, k=k)


def pool(
    blueprints: Sequence[Any],
    *,
    start: str = "2026-03",
    periods: int = 1,
    incident: bool | None = None,
    names: Sequence[str] | None = None,
) -> Pool:
    """Build, run and measure every candidate. The expensive half of the loop.

    *blueprints* are ``sdk.Blueprint``s. Each is built, run for *periods*
    episodes from *start*, and compiled — and nothing else. No narration, no
    render, no export, no file written.

    Builds eagerly rather than lazily, unlike ``sdk.built()``: a max-min
    selection is a property of the whole field and cannot be decided from a
    prefix, so there is no early exit to preserve.
    """
    labels = (tuple(names) if names is not None
              else tuple(f"candidate-{index + 1:02d}" for index in range(len(blueprints))))
    if len(labels) != len(blueprints):
        raise ValueError(
            f"{len(labels)} name(s) for {len(blueprints)} candidate(s) — a reading"
            " that cannot be named is a reading nobody can go and look at"
        )

    readings: list[Reading] = []
    worlds: list[Any] = []
    for label, blueprint in zip(labels, blueprints, strict=True):
        world = blueprint.build().episodes(
            start, periods=periods, incident=incident,
        ).world.compile()
        worlds.append(world)
        readings.append(read(world, name=label, seed=getattr(blueprint, "seed", 0)))
    return Pool(tuple(readings), tuple(worlds), tuple(blueprints))


# ---------------------------------------------------------------------------
# Distance over measurements, and selection on it
# ---------------------------------------------------------------------------


def _normalised(readings: Sequence[Reading]) -> tuple[tuple[float, ...], ...]:
    """Each metric scaled to [0, 1] across the pool.

    The same argument ``mosaic`` makes about parameter coordinates, one level
    down and with more force: ``facts`` runs to several hundred and
    ``type_token_ratio`` runs from 0.2 to 0.4, so unnormalised the fact count
    would decide entirely what "unlike" means and every selected set would
    differ in corpus size and in nothing else.

    A metric that is constant across the pool collapses to zero everywhere
    rather than to a half or a NaN — it carries no information about which
    candidates differ, and a constant column that contributed a fixed amount to
    every pair would dilute the columns that do.
    """
    if not readings:
        return ()
    keys = sorted(readings[0].metrics)
    for reading in readings[1:]:
        if sorted(reading.metrics) != keys:
            raise ValueError(
                "these readings do not share a metric vocabulary, so no two of"
                " them can be compared; they were probably measured by"
                " different versions of `read`"
            )
    columns = [[float(reading.metrics[key]) for reading in readings] for key in keys]
    bounds = [(min(column), max(column)) for column in columns]
    return tuple(
        tuple(
            0.0 if high == low else (float(reading.metrics[key]) - low) / (high - low)
            for key, (low, high) in zip(keys, bounds, strict=True)
        )
        for reading in readings
    )


def _jaccard(left: frozenset[tuple[str, ...]], right: frozenset[tuple[str, ...]]) -> float:
    if not left and not right:
        return 1.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def _question_distance(left: Reading, right: Reading, threshold: float) -> float:
    """One minus the share of either world's questions the other one restates.

    Symmetric by construction — the numerator counts matched questions on both
    sides and the denominator is both question counts — because a distance that
    depended on argument order would make ``farthest_first`` return a different
    set depending on which candidate happened to survive the feasibility filter
    first.

    Coverage rather than a pair count. ``evaluate.across`` reports the raw
    cross-world pair count because that is the finding a reader has to see; as
    a *distance* it is the wrong shape, since two worlds sharing one template
    twenty times over score the same as twenty worlds sharing it once, and the
    pair count against all possible pairs is near zero for every pair of worlds
    that ever existed.
    """
    if not left.shingles and not right.shingles:
        return 0.0
    matched_left = sum(
        1 for a in left.shingles
        if any(_jaccard(a, b) >= threshold for b in right.shingles)
    )
    matched_right = sum(
        1 for b in right.shingles
        if any(_jaccard(a, b) >= threshold for a in left.shingles)
    )
    total = len(left.shingles) + len(right.shingles)
    return 1.0 - (matched_left + matched_right) / total if total else 0.0


def distances(
    readings: Sequence[Reading],
    *,
    question_weight: float = QUESTION_WEIGHT,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> tuple[tuple[float, ...], ...]:
    """The full pairwise distance matrix, computed once.

    Materialised rather than recomputed inside ``farthest_first``'s callback:
    the traversal asks for ``count × n`` distances and the question term is the
    expensive one (a shingled join between two evaluation sets), so a callback
    would compute most pairs twice and some not at all. A matrix over thirty
    candidates is 435 pairs and a few hundred kilobytes.

    Each entry is ``mean per-metric distance + question_weight × question
    distance``, both halves in [0, 1]. L1 over the metric block, mean rather
    than sum, for ``dispersion.manhattan``'s reason and one more: the block's
    width depends on how many evaluation families the registry has, and a
    distance that grew when somebody registered a ninth family would silently
    reweight the questions against everything else.
    """
    if question_weight < 0:
        raise ValueError(f"question_weight must be non-negative, got {question_weight}")
    vectors = _normalised(readings)
    n = len(readings)
    width = len(vectors[0]) if vectors and vectors[0] else 1

    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            metric = sum(abs(a - b) for a, b in zip(vectors[i], vectors[j], strict=True)) / width
            asked = _question_distance(readings[i], readings[j], threshold)
            value = metric + question_weight * asked
            matrix[i][j] = matrix[j][i] = value
    return tuple(tuple(row) for row in matrix)


def select(
    readings: Sequence[Reading],
    count: int,
    *,
    question_weight: float = QUESTION_WEIGHT,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> tuple[int, ...]:
    """The *count* readings least like each other, as indices in selection order.

    The safe objective, and the default everywhere. It maximises *spread* over
    the measurement vector — the same max-min traversal ``mosaic`` runs, with
    the coordinates replaced by what the corpora turned out to contain. Nothing
    is being fit, so there is nothing to overfit: a set chosen for spread is
    not a set chosen to defeat anything.

    ``farthest_first`` starts from index 0, so candidate order decides the
    first pick and nothing else. That is the same tie-break the parameter
    mosaic lives with and it is deterministic, which is the property that
    matters here.
    """
    matrix = distances(readings, question_weight=question_weight, threshold=threshold)
    return farthest_first(
        list(range(len(readings))), lambda i, j: matrix[i][j], count,
    )


def hardest(
    worlds: Sequence[Any], count: int, *, retriever: str = "bm25", k: int = 5,
) -> tuple[int, ...]:
    """The *count* worlds *retriever* fails most cases on. **Opt-in and unsafe.**

    .. warning::

       Read ``Pool.hardest``'s warning before using this. It selects a dataset
       against one weak baseline, which produces a benchmark for that baseline
       rather than a more diverse corpus, and it is kept out of ``select()``
       for that reason rather than by oversight.

    Ties resolve to the lower index, so the result is deterministic.
    """
    from .evaluate.score import score

    if count > len(worlds):
        raise ValueError(f"cannot select {count} candidate(s) from {len(worlds)}")
    cards = [score(world, k=k, retriever=retriever) for world in worlds]
    # Sorted on `(-failures, index)` ascending rather than on failures
    # descending, so a tie between two worlds resolves to the lower index in
    # both halves of the key at once — `reverse=True` on a plain failure count
    # would reverse the index tie-break as well, and the selection would depend
    # on pool order in a way nothing documents.
    ranked = sorted(
        range(len(worlds)), key=lambda i: (-(len(cards[i]) - cards[i].passed), i),
    )
    return tuple(ranked[:count])


# ---------------------------------------------------------------------------
# Reporting a selection, so it can be compared with one made another way
# ---------------------------------------------------------------------------


def report(
    readings: Sequence[Reading],
    chosen: Sequence[int],
    *,
    question_weight: float = QUESTION_WEIGHT,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> dict[str, Any]:
    """How spread out a chosen subset actually is, on the measurements.

    Deliberately callable on a subset this module did not choose: the whole
    point of the exercise is to hold an outcome-selected set and a
    parameter-dispersed set of the same size against the same ruler, and a
    report that only worked on its own output would be a report nobody could
    check.
    """
    picked = [readings[at] for at in chosen]
    matrix = distances(picked, question_weight=question_weight, threshold=threshold)
    pairs = [matrix[i][j] for i in range(len(picked)) for j in range(i + 1, len(picked))]
    keys = sorted(picked[0].metrics) if picked else []
    return {
        "worlds": len(picked),
        "names": [reading.name for reading in picked],
        "closest_pair": round(min(pairs), 4) if pairs else 0.0,
        "mean_pair": round(sum(pairs) / len(pairs), 4) if pairs else 0.0,
        "distinct_questions": len({q for reading in picked for q in reading.questions}),
        "questions": sum(len(reading.questions) for reading in picked),
        "metric_ranges": {
            key: round(
                max(r.metrics[key] for r in picked) - min(r.metrics[key] for r in picked), 4,
            )
            for key in keys
        },
    }
