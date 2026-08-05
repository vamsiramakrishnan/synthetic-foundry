"""Measuring a *mosaic*, not a corpus.

``mosaic.spread()`` reports that five worlds differ — distinct organisation
shapes, headcounts, estates, trading years. That is a claim about the
**enterprises**. The product claim is about the **dataset**: that five
deliberately-unlike companies make a better evaluation set than one company
seen five times. Nothing measured that, so this does.

Three readings, because "better dataset" is three different questions and they
have different answers:

``transfer()``
    Same evaluation kinds, different worlds. If a family scores 8/9 in world 1
    and 2/9 in world 5, the variety is genuinely stressing the retriever and a
    system tuned on one world does not carry to the next. If every world
    returns the same scorecard, the mosaic has added corpora but not
    *difficulty* — five draws from one distribution.

``overlap()``
    Are the questions different questions, or one template with different
    nouns? ``similarity.near_duplicate_pairs`` answers this exactly, run over
    question text with the whole mosaic in one pool so the pairs that matter —
    world *i* against world *j* — are in scope. This is the sharpest reading
    available and the one most likely to be unflattering, which is why it
    reports the raw pair count and the distinct-string count rather than a
    single index that could be read charitably.

``difficulty()``
    Is the hardness spread across the mosaic, or does one world carry it? A
    mosaic whose fifth world holds every failing case is a one-world benchmark
    with four warm-up corpora attached.

**Why the abstention floor is the transfer experiment.** Neither baseline is
"tuned" in the usual sense — BM25's ``K1``/``B`` are fixed and deliberately
untuned (see ``bm25.py``), and TF-IDF has no knobs. But ``score()`` does
calibrate exactly one quantity per corpus: the abstention floor, a fraction of
*that corpus's* median top score. That is the whole tunable surface, so
transplanting it is the whole transfer experiment, and it is a real one — a
floor fitted on a 30-person world with a large estate being applied to a
16-person world with none is precisely "does what I learned on world 1 hold on
world 5".

Deterministic throughout, for the same reason everything else here is: every
iteration is over a sorted key, and the only hashing is
``similarity``'s ``content_key``-derived kind.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import similarity
from ..models import EvaluationType
from ..stats import NEAR_DUPLICATE_THRESHOLD, SHINGLE_SIZE
from .bm25 import tokens
from .index import passages
from .score import (
    ABSTENTION_FRACTION,
    DEFAULT_K,
    DEFAULT_RETRIEVER,
    RETRIEVERS,
    Scorecard,
    score,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..models import EvaluationCase
    from ..world import World

#: The filename ``worldloom mosaic --out`` writes its plan to. Read when
#: present and ignored when absent: a directory of hand-built corpora is a
#: legitimate thing to measure, and the plan only supplies the one-line
#: summaries that make a report readable.
PLAN_FILE = "mosaic.json"


@dataclass(frozen=True)
class MosaicWorld:
    """One world of a mosaic, with the name it is known by on disk.

    The name is load-bearing rather than cosmetic: every finding below is
    "world 3 differs from world 5", so a reading that lost track of which
    directory a number came from would name no world to go and look at.
    """

    name: str
    world: World
    summary: str = ""
    """The variant's one-line shape, from ``mosaic.json`` — "22 people, spans
    of 5, 3 levels, …". Empty for a directory that carries no plan."""


def load(directory: str | Path) -> tuple[MosaicWorld, ...]:
    """Every corpus under *directory*, in directory-name order.

    A subdirectory is a corpus if it has a ``world.json``; anything else is
    skipped rather than raising, because ``worldloom mosaic --out`` also writes
    ``mosaic.json`` beside the worlds and a future sibling file should not
    break this.

    Ordered by name, not by filesystem order, because ``world-05`` must be the
    fifth world in every report on every machine.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"{root} is not a directory of worlds")

    plan: dict[str, str] = {}
    plan_path = root / PLAN_FILE
    if plan_path.is_file():
        document = json.loads(plan_path.read_text(encoding="utf-8"))
        for entry in document.get("worlds", []):
            index = entry.get("index")
            if index is None:
                continue
            parts = [
                f"{entry.get('headcount')} people",
                f"spans of {entry.get('span')}",
                f"{entry.get('levels')} levels",
                f"{entry.get('estate') or 'no'} estate",
            ]
            plan[f"world-{int(index):02d}"] = ", ".join(parts)

    from ..world import World as _World

    found: list[MosaicWorld] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not (child / "world.json").is_file():
            continue
        world = _World.load(child)
        # Compiled here rather than at every call site: `passages()` reads
        # `artifact_irs`, and a mosaic written by `worldloom mosaic` has them
        # already — but a corpus exported before rendering does not, and the
        # three readings below would each have to know that.
        if not world.artifact_irs:
            world = world.compile()
        found.append(MosaicWorld(child.name, world, plan.get(child.name, "")))

    if len(found) < 2:
        raise ValueError(
            f"{root} holds {len(found)} corpus/corpora — a cross-corpus reading"
            " needs at least two. Build one with `worldloom mosaic -n 5 --out`."
        )
    return tuple(found)


# ---------------------------------------------------------------------------
# 1. Transfer: same question kinds, different worlds
# ---------------------------------------------------------------------------


def _calibrate(index: Any, cases: Sequence[EvaluationCase]) -> float:
    """This corpus's abstention floor — ``score()``'s calibration, extracted.

    Deliberately a copy of the six lines inside `score()` rather than a
    refactor of them: `score()` computes the floor for the corpus it is
    scoring and has no reason to accept a foreign one, and changing its
    signature to take one would put a cross-corpus concept into the
    single-corpus scorer. The duplication is six lines and
    ``tests/test_across.py`` pins the two against each other, which is the
    cheaper of the two ways to keep them honest.
    """
    tops: list[float] = []
    for case in cases:
        if case.expects_abstention:
            continue
        ranked = index.rank(case.question, limit=1)
        if ranked:
            tops.append(ranked[0][1])
    tops.sort()
    median = tops[len(tops) // 2] if tops else 0.0
    return median * ABSTENTION_FRACTION


@dataclass(frozen=True)
class Transfer:
    """How one retriever did across every world of a mosaic."""

    retriever: str
    k: int
    cards: dict[str, Scorecard]
    by_family: dict[EvaluationType, dict[str, tuple[int, int]]]
    """``{family: {world: (passed, total)}}`` — the reading question 1 asks
    for, held at family granularity because an overall score that holds steady
    can still be two families moving in opposite directions."""
    floors: dict[str, float]
    """Each world's calibrated abstention floor."""
    floor_flips: dict[str, dict[str, int]]
    """``{fitted_on: {applied_to: cases whose verdict changed}}``. The diagonal
    is zero by construction and is kept in the table anyway, because a matrix
    with a hole in it reads as a missing measurement rather than as a
    tautology."""

    @property
    def worlds(self) -> tuple[str, ...]:
        return tuple(sorted(self.cards))

    @property
    def identical(self) -> bool:
        """Whether every world returned the same per-case verdicts.

        The strong form of "the mosaic added no difficulty", and the one worth
        testing: two worlds can reach the same 20/42 while failing different
        cases, which would still be variety. This says they did not.
        """
        first = self.worlds[0]
        reference = {(o.case_id, o.passed) for o in self.cards[first].outcomes}
        return all(
            {(o.case_id, o.passed) for o in self.cards[name].outcomes} == reference
            for name in self.worlds[1:]
        )

    def spread(self) -> dict[EvaluationType, float]:
        """Per family, the gap between the best and worst world's pass rate.

        Zero everywhere means a retriever that works on world 1 works exactly
        as well on world 5 — the variety is not stressing it at all.
        """
        out: dict[EvaluationType, float] = {}
        for family, scores in self.by_family.items():
            rates = [passed / total for passed, total in scores.values() if total]
            out[family] = round(max(rates) - min(rates), 4) if rates else 0.0
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "retriever": self.retriever,
            "k": self.k,
            "identical_verdicts": self.identical,
            "worlds": {
                name: {"passed": card.passed, "total": len(card)}
                for name, card in sorted(self.cards.items())
            },
            "by_family": {
                family.value: {
                    "worlds": {n: {"passed": p, "total": t} for n, (p, t) in sorted(scores.items())},
                    "spread": self.spread()[family],
                }
                for family, scores in sorted(self.by_family.items(), key=lambda i: i[0].value)
            },
            "abstention_floor": {
                "fitted": {name: round(value, 4) for name, value in sorted(self.floors.items())},
                "flips": {a: dict(sorted(row.items())) for a, row in sorted(self.floor_flips.items())},
            },
        }


def transfer(
    worlds: Sequence[MosaicWorld],
    *,
    retriever: str = DEFAULT_RETRIEVER,
    k: int = DEFAULT_K,
) -> Transfer:
    """Score *retriever* on every world, and transplant each world's calibration.

    Two things come back and they answer different halves of "does it
    transfer": the per-family scores say whether the *corpora* differ in
    difficulty, and ``floor_flips`` says whether the one calibrated quantity
    fitted on world *i* still holds on world *j*.
    """
    if retriever not in RETRIEVERS:
        raise ValueError(f"unknown retriever {retriever!r} — choose from {sorted(RETRIEVERS)}")

    cards = {entry.name: score(entry.world, k=k, retriever=retriever) for entry in worlds}

    by_family: dict[EvaluationType, dict[str, tuple[int, int]]] = {}
    for name in sorted(cards):
        for family, tally in cards[name].by_type().items():
            by_family.setdefault(family, {})[name] = tally

    # The transplant. Only abstention cases can move: the floor is the only
    # per-corpus calibration in `score()`, and it is consulted on no other
    # branch — so re-grading the rest under a foreign floor would be running
    # the same comparison twice and reporting it as evidence.
    floors: dict[str, float] = {}
    bests: dict[str, list[tuple[str, float]]] = {}
    for entry in worlds:
        pool = passages(entry.world)
        if not pool:
            raise ValueError(f"{entry.name}: nothing to retrieve from — render or compile it first")
        index = RETRIEVERS[retriever]([passage.text for passage in pool])
        cases = list(entry.world.evaluations)
        floors[entry.name] = _calibrate(index, cases)
        bests[entry.name] = [
            (case.id, ranked[0][1] if (ranked := index.rank(case.question, limit=1)) else 0.0)
            for case in cases
            if case.expects_abstention
        ]

    flips: dict[str, dict[str, int]] = {}
    for fitted_on in sorted(floors):
        row: dict[str, int] = {}
        for applied_to in sorted(floors):
            own, foreign = floors[applied_to], floors[fitted_on]
            row[applied_to] = sum(
                1 for _, best in bests[applied_to] if (best < own) != (best < foreign)
            )
        flips[fitted_on] = row

    return Transfer(retriever, k, cards, by_family, floors, flips)


# ---------------------------------------------------------------------------
# 2. Overlap: are these different questions?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Overlap:
    """How much of the mosaic's evaluation set is the same question restated.

    Every field is a count rather than an index, on purpose. "Question
    diversity 0.2" invites a reader to decide 0.2 is fine; "210 questions, 42
    distinct" does not.
    """

    threshold: float
    shingle_size: int
    questions: int
    distinct_questions: int
    distinct_with_answers: int
    """Distinct ``(question, expected answer)`` pairs. The charitable reading of
    a repeated question is that the same words asked of a different company are
    a different item because the answer differs — this is that reading,
    measured. Where it equals ``distinct_questions`` the repetition is total."""
    identical_in_every_world: int
    """Question strings present, byte-for-byte, in all of the worlds."""
    cross_world_pairs: int
    cross_world_pairs_possible: int
    groups: tuple[tuple[str, ...], ...]
    """Near-duplicate groups that span more than one world, as world names —
    the finding, where the pair count is the metric. Sorted, largest first."""
    questions_in_a_cross_world_group: int

    @property
    def redundancy(self) -> float:
        """Fraction of questions that are a restatement of another world's."""
        if not self.questions:
            return 0.0
        return round(1 - self.distinct_questions / self.questions, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "shingle_size": self.shingle_size,
            "questions": self.questions,
            "distinct_questions": self.distinct_questions,
            "distinct_with_answers": self.distinct_with_answers,
            "identical_in_every_world": self.identical_in_every_world,
            "redundancy": self.redundancy,
            "cross_world_pairs": self.cross_world_pairs,
            "cross_world_pairs_possible": self.cross_world_pairs_possible,
            "questions_in_a_cross_world_group": self.questions_in_a_cross_world_group,
            "cross_world_groups": len(self.groups),
        }


def overlap(
    worlds: Sequence[MosaicWorld],
    *,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    shingle_size: int = SHINGLE_SIZE,
) -> Overlap:
    """The near-duplicate join, run over question text across the whole mosaic.

    One pool, not one per world: an intra-corpus duplicate is `stats.py`'s
    question and a different failure, and pooling is the only way a pair from
    world 1 and world 5 is a candidate at all.

    The tokenizer and shingle size are the corpus-level ones
    (``stats.SHINGLE_SIZE``, ``evaluate.bm25.tokens``) for the reason
    ``similarity.shingles`` states: "near-duplicate" only means something if it
    means the same thing here as it does to the retriever that would be
    confused by the duplication. One caveat worth stating rather than burying —
    a five-token shingle over a ten-token question is a coarse instrument, and
    it will *under*-report two questions that share a template but differ in a
    noun near the middle, since every shingle spans that noun. So
    ``cross_world_pairs`` is a floor on the repetition, never a ceiling, and
    ``distinct_questions`` is the reading that cannot be argued with.
    """
    rows: list[tuple[str, str, str]] = [
        (entry.name, case.question, case.expected_answer or "")
        for entry in worlds
        for case in entry.world.evaluations
    ]
    if not rows:
        raise ValueError("no evaluation cases in any of these worlds")

    sets = [similarity.shingles(tokens(question), shingle_size) for _, question, _ in rows]
    pairs = similarity.near_duplicate_pairs(sets, threshold)
    cross = tuple((i, j) for i, j in pairs if rows[i][0] != rows[j][0])
    possible = sum(
        1
        for i in range(len(rows))
        for j in range(i + 1, len(rows))
        if rows[i][0] != rows[j][0]
    )

    groups = similarity.clusters(pairs, len(rows))
    spanning = tuple(
        group for group in groups if len({rows[i][0] for i in group}) > 1
    )
    inside = len({index for group in spanning for index in group})

    per_world = [
        {question for name, question, _ in rows if name == world_name}
        for world_name in sorted({row[0] for row in rows})
    ]
    everywhere = len(set.intersection(*per_world)) if per_world else 0

    return Overlap(
        threshold=threshold,
        shingle_size=shingle_size,
        questions=len(rows),
        distinct_questions=len({question for _, question, _ in rows}),
        distinct_with_answers=len({(question, answer) for _, question, answer in rows}),
        identical_in_every_world=everywhere,
        cross_world_pairs=len(cross),
        cross_world_pairs_possible=possible,
        groups=tuple(
            tuple(sorted(rows[i][0] for i in group)) for group in spanning
        ),
        questions_in_a_cross_world_group=inside,
    )


# ---------------------------------------------------------------------------
# 3. Difficulty: is it spread, or does one world carry it?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Difficulty:
    """Where the mosaic's hardness actually sits."""

    declared: dict[str, dict[str, int]]
    """``{world: {easy|medium|hard: count}}`` — what the generator labelled."""
    failures: dict[str, int]
    """Cases each world's corpus defeated the baseline on. The *measured*
    hardness, as against the declared kind above: a label is an intention and a
    failing retriever is an outcome, and a mosaic can have the first uniform
    while the second is not."""
    retriever: str

    @property
    def concentration(self) -> float:
        """The share of the mosaic's failures carried by its hardest world.

        Compare against ``1 / len(worlds)``: at that value hardness is spread
        perfectly evenly, at 1.0 a single world is the entire benchmark.
        """
        total = sum(self.failures.values())
        if not total:
            return 0.0
        return round(max(self.failures.values()) / total, 4)

    @property
    def even_share(self) -> float:
        return round(1 / len(self.failures), 4) if self.failures else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "retriever": self.retriever,
            "declared": {name: dict(sorted(mix.items())) for name, mix in sorted(self.declared.items())},
            "failures": dict(sorted(self.failures.items())),
            "concentration": self.concentration,
            "even_share": self.even_share,
        }


def difficulty(
    worlds: Sequence[MosaicWorld],
    *,
    retriever: str = DEFAULT_RETRIEVER,
    k: int = DEFAULT_K,
) -> Difficulty:
    """Declared difficulty mix and measured failure count, per world."""
    declared: dict[str, dict[str, int]] = {}
    failures: dict[str, int] = {}
    for entry in worlds:
        mix: dict[str, int] = {}
        for case in entry.world.evaluations:
            mix[case.difficulty] = mix.get(case.difficulty, 0) + 1
        declared[entry.name] = mix
        card = score(entry.world, k=k, retriever=retriever)
        failures[entry.name] = len(card) - card.passed
    return Difficulty(declared, failures, retriever)


# ---------------------------------------------------------------------------
# The three readings together
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Survey:
    """All three readings of one mosaic, and the sentence they add up to."""

    worlds: tuple[MosaicWorld, ...]
    transfers: dict[str, Transfer]
    overlap: Overlap
    difficulty: Difficulty

    @property
    def verdict(self) -> str:
        """What the numbers say about the product claim, in one line.

        Stated by the measurement rather than by whoever reads it, because the
        flattering reading of a mosaic ("five distinct organisation shapes")
        is already printed by `mosaic.spread()` and is about the companies.
        This is the one about the dataset.
        """
        stressed = any(
            rate > 0.0
            for reading in self.transfers.values()
            for rate in reading.spread().values()
        )
        repeated = self.overlap.redundancy
        if repeated >= 0.5 and not stressed:
            return (
                f"the variety is in the facts, not in the questions —"
                f" {self.overlap.questions} questions reduce to"
                f" {self.overlap.distinct_questions} distinct, and every world"
                f" returns the same verdicts"
            )
        if repeated >= 0.5:
            return (
                f"the questions repeat ({self.overlap.distinct_questions} distinct of"
                f" {self.overlap.questions}) but the worlds answer them with"
                f" different difficulty"
            )
        if not stressed:
            return "the questions differ but no world is harder than any other"
        return "the questions differ and the worlds differ in difficulty"

    def as_dict(self) -> dict[str, Any]:
        return {
            "worlds": [
                {"name": entry.name, "summary": entry.summary,
                 "cases": len(entry.world.evaluations)}
                for entry in self.worlds
            ],
            "transfer": {name: reading.as_dict() for name, reading in sorted(self.transfers.items())},
            "overlap": self.overlap.as_dict(),
            "difficulty": self.difficulty.as_dict(),
            "verdict": self.verdict,
        }

    def __str__(self) -> str:
        return render(self)

    def __repr__(self) -> str:
        return render(self)


def survey(
    directory_or_worlds: str | Path | Sequence[MosaicWorld],
    *,
    retrievers: Sequence[str] = (DEFAULT_RETRIEVER,),
    k: int = DEFAULT_K,
) -> Survey:
    """Every reading, over a mosaic directory or an already-loaded one."""
    worlds = (
        load(directory_or_worlds)
        if isinstance(directory_or_worlds, (str, Path))
        else tuple(directory_or_worlds)
    )
    return Survey(
        worlds=worlds,
        transfers={name: transfer(worlds, retriever=name, k=k) for name in sorted(set(retrievers))},
        overlap=overlap(worlds),
        difficulty=difficulty(worlds, retriever=sorted(set(retrievers))[0], k=k),
    )


def render(reading: Survey) -> str:
    """The survey as terminal text — `Scorecard.__str__`'s cross-corpus sibling."""
    names = [entry.name for entry in reading.worlds]
    width = max(len(family.value) for family in EvaluationType)
    lines = [f"Across {len(names)} world(s)", "─" * (width + 12 * len(names) + 6)]

    for retriever in sorted(reading.transfers):
        moved = reading.transfers[retriever]
        header = "  ".join(name.removeprefix("world-").rjust(5) for name in names)
        lines.append(f"  {retriever.upper().ljust(width)}  {header}   [@{moved.k}]")
        for family, scores in sorted(moved.by_family.items(), key=lambda i: i[0].value):
            cells = "  ".join(
                f"{scores.get(name, (0, 0))[0]}/{scores.get(name, (0, 0))[1]}".rjust(5)
                for name in names
            )
            flag = "" if moved.spread()[family] else "  ← no spread"
            lines.append(f"  {family.value.ljust(width)}  {cells}{flag}")
        totals = "  ".join(f"{moved.cards[n].passed}/{len(moved.cards[n])}".rjust(5) for n in names)
        lines.append(f"  {'overall'.ljust(width)}  {totals}")
        lines.append(
            f"  identical verdicts in every world: {moved.identical}"
            f"   floor transplants that changed a verdict:"
            f" {sum(sum(row.values()) for row in moved.floor_flips.values())}"
        )
        lines.append("")

    over = reading.overlap
    lines += [
        f"Questions — near-duplicate join at ≥{over.threshold:.0%} shingled Jaccard",
        f"  {over.questions} question(s) across the mosaic, {over.distinct_questions} distinct"
        f" ({over.redundancy:.0%} restatement)",
        f"  {over.distinct_with_answers} distinct (question, answer) pair(s)",
        f"  {over.identical_in_every_world} question(s) appear byte-identical in every world",
        f"  {over.cross_world_pairs}/{over.cross_world_pairs_possible} cross-world pair(s) are"
        f" near-duplicates, in {len(over.groups)} group(s)",
        f"  {over.questions_in_a_cross_world_group}/{over.questions} question(s) sit in a"
        f" cross-world duplicate group",
        "",
        f"Difficulty — {reading.difficulty.retriever}",
    ]
    for name in names:
        mix = reading.difficulty.declared.get(name, {})
        declared = " ".join(f"{kind} {mix.get(kind, 0)}" for kind in ("easy", "medium", "hard"))
        lines.append(f"  {name.ljust(width)}  {declared}   failed {reading.difficulty.failures[name]}")
    lines.append(
        f"  hardest world carries {reading.difficulty.concentration:.0%} of the failures"
        f" (even split would be {reading.difficulty.even_share:.0%})"
    )
    lines += ["", f"Verdict: {reading.verdict}"]
    return "\n".join(lines)


__all__ = [
    "Difficulty",
    "MosaicWorld",
    "Overlap",
    "Survey",
    "Transfer",
    "difficulty",
    "load",
    "overlap",
    "render",
    "survey",
    "transfer",
]
