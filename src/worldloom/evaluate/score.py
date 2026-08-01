"""Scoring a retriever against the corpus's own evaluation set.

Every question type is scored on the thing that type is actually testing, and the
grading is objective in each case because the manifest records what it needs to
be:

``direct_lookup`` and friends
    Did retrieval surface a passage carrying the facts the answer rests on?
``temporal_state``
    An author writing at 09:30 could not cite a cause confirmed at 13:20. A
    retriever that sees every document at once, with no notion of *when* a
    document was written, gets caught here.
``authority_resolution``
    Several documents carry the fact; only one is the record. Ranking by keyword
    overlap has no reason to prefer it.
``expected_abstention``
    The corpus does not contain the answer. Retrieving something confident is the
    failure, so the score is whether the retriever stayed quiet.

There is no model anywhere in this. A judge would put the thing under test inside
the measurement.

Two ranking families run through the same grading code (`RETRIEVERS`): BM25, the
original baseline, and TF-IDF cosine, a genuinely different family (see
`tfidf.py`'s module docstring for the actual axes of difference). The grading
above never asks which retriever produced the passages it is looking at — same
`_covers`, same authority and temporal checks either way — which is what makes a
family that both retrievers fail *structurally* hard rather than hard for one
heuristic's particular blind spot. `compare()` is that reading, made explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from ..models import EvaluationType
from .bm25 import Bm25
from .index import Passage, passages
from .tfidf import TfIdf

if TYPE_CHECKING:  # pragma: no cover
    from ..models import EvaluationCase
    from ..world import World

#: How many passages a retriever is allowed to return.
DEFAULT_K = 5

#: Below this fraction of the median top score a retrieval counts as "nothing
#: found". Calibrated from the corpus rather than chosen: a fraction of the
#: median top score across answerable questions, so a corpus with longer
#: documents does not silently become a corpus that never abstains. Recomputed
#: per retriever (see `score()`) because BM25's scores are unbounded and TF-IDF
#: cosine's are bounded to [0, 1] — the two scales are not comparable, only each
#: retriever's own distribution against itself is.
ABSTENTION_FRACTION = 0.35


class Retriever(Protocol):
    """What `score()` needs from a ranking family — `Bm25` and `TfIdf` both satisfy
    this without declaring it, which is the point: adding a third retriever means
    writing a class with this shape, not touching the scorer."""

    def __init__(self, documents: list[str]) -> None: ...

    def rank(self, query: str, *, limit: int) -> list[tuple[int, float]]: ...


#: Every ranking family `score()` and the CLI know how to run. Registering a new
#: retriever here is the entire integration surface — `score()`, the CLI's
#: `--retriever` choices, and `compare()` all read this rather than naming a
#: retriever class directly.
RETRIEVERS: dict[str, type[Retriever]] = {"bm25": Bm25, "tfidf": TfIdf}

#: Default kept as the original baseline, not "both": every existing caller
#: (`score(corpus)` with no retriever argument, `worldloom evaluate` with no
#: flag, the CI step that asserts the hard families stay hard) has to see
#: exactly the numbers it always has. Run `--retriever both` explicitly for the
#: credibility reading — see `evaluating.md`.
DEFAULT_RETRIEVER = "bm25"


@dataclass(frozen=True)
class Outcome:
    """How a retriever did on one question."""

    case_id: str
    evaluation_type: EvaluationType
    passed: bool
    detail: str


@dataclass
class Scorecard:
    """Per-type results, and the totals, for one retriever's run."""

    outcomes: list[Outcome] = field(default_factory=list)
    k: int = DEFAULT_K
    retriever: str = DEFAULT_RETRIEVER
    """Which entry of `RETRIEVERS` produced these outcomes. Carried on the
    dataclass rather than left implicit so a `Scorecard` printed or serialised on
    its own still says which ranking family it is reporting on."""

    def by_type(self) -> dict[EvaluationType, tuple[int, int]]:
        """``{type: (passed, total)}``."""
        tally: dict[EvaluationType, list[int]] = {}
        for outcome in self.outcomes:
            entry = tally.setdefault(outcome.evaluation_type, [0, 0])
            entry[0] += int(outcome.passed)
            entry[1] += 1
        return {kind: (passed, total) for kind, (passed, total) in tally.items()}

    @property
    def passed(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.passed)

    def __len__(self) -> int:
        return len(self.outcomes)

    def __str__(self) -> str:
        label = "Baseline" if self.retriever == "bm25" else self.retriever.upper()
        lines = [f"{label} retrieval @{self.k}", "─" * 52]
        for kind, (passed, total) in sorted(self.by_type().items(), key=lambda i: i[0].value):
            bar = "█" * round(10 * passed / total) if total else ""
            lines.append(f"  {kind.value:<24} {passed:>2}/{total:<3} {bar}")
        lines += ["─" * 52, f"  {'overall':<24} {self.passed:>2}/{len(self):<3}"]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return str(self)


def _covers(found: list[Passage], case: EvaluationCase) -> bool:
    """Whether the retrieved passages between them carry every expected fact."""
    carried: set[str] = set()
    for passage in found:
        carried |= passage.fact_ids
    return set(case.expected_fact_ids) <= carried


def score(world: World, *, k: int = DEFAULT_K, retriever: str = DEFAULT_RETRIEVER) -> Scorecard:
    """Run *retriever* over every evaluation case in *world*.

    ``retriever`` names an entry of `RETRIEVERS`. The grading logic below never
    branches on which one was chosen — every check reads `found`/`pool`, which
    are retriever-shaped but not retriever-*specific* — so a passing test suite
    for one retriever is a passing test suite for the grading, and the only thing
    that changes between `score(world)` (BM25, the default, unchanged from
    before this function took a `retriever` argument) and `score(world,
    retriever="tfidf")` is which class built `index`.
    """
    try:
        index_cls = RETRIEVERS[retriever]
    except KeyError:
        raise ValueError(f"unknown retriever {retriever!r} — choose from {sorted(RETRIEVERS)}") from None

    pool = passages(world)
    if not pool:
        raise ValueError("nothing to retrieve from — render or compile the corpus first")

    index = index_cls([passage.text for passage in pool])
    cases = list(world.evaluations)

    # Calibrate the abstention threshold on the answerable questions, so it
    # reflects this corpus rather than a number chosen in advance.
    tops = []
    for case in cases:
        if case.expects_abstention:
            continue
        ranked = index.rank(case.question, limit=1)
        if ranked:
            tops.append(ranked[0][1])
    tops.sort()
    median = tops[len(tops) // 2] if tops else 0.0
    floor = median * ABSTENTION_FRACTION

    card = Scorecard(k=k, retriever=retriever)
    for case in cases:
        ranked = index.rank(case.question, limit=k)
        found = [pool[position] for position, _ in ranked]
        best = ranked[0][1] if ranked else 0.0

        if case.expects_abstention:
            passed = best < floor
            detail = f"top score {best:.2f} against a floor of {floor:.2f}"

        elif case.evaluation_type is EvaluationType.TEMPORAL_STATE and case.temporal_cutoff:
            # Scored on the top answer *unfiltered*. Filtering by the cut-off
            # before grading would hand the baseline the one capability this
            # question type exists to test — it would be measuring a temporal
            # retriever that does not exist, and the corpus would look easy
            # because the scorer was doing the work.
            top = found[0] if found else None
            passed = (
                top is not None
                and top.created_at <= case.temporal_cutoff
                and _covers([top], case)
            )
            if top is None:
                detail = "retrieved nothing"
            elif top.created_at > case.temporal_cutoff:
                detail = (
                    f"top hit was written {top.created_at.isoformat()},"
                    f" after the cut-off {case.temporal_cutoff.isoformat()}"
                )
            else:
                detail = "top hit predates the cut-off and carries the fact"

        elif case.evaluation_type is EvaluationType.AUTHORITY_RESOLUTION:
            carrying = [p for p in pool if set(case.expected_fact_ids) & p.fact_ids]
            if not carrying or not found:
                passed, detail = False, "no passage carries the expected fact"
            else:
                # Both halves are required. Rank alone passed a retriever whose
                # top hit was the *wrong* document at the right authority —
                # invisible while every corpus discriminated by rank, exposed
                # the moment the banking vertical put two lodgements at
                # SYSTEM_OF_RECORD on purpose: surfacing the superseded filing
                # scored as authority resolution while carrying none of the
                # answer. Resolving authority means surfacing the document the
                # answer actually rests on, at the standing the answer needs.
                best_rank = max(p.authority_rank for p in carrying)
                top = found[0]
                answers = bool(set(case.expected_fact_ids) & top.fact_ids)
                passed = top.authority_rank >= best_rank and answers
                detail = (
                    f"top passage authority {top.authority.value}"
                    + ("" if answers else ", and it carries none of the expected facts")
                )

        else:
            passed = _covers(found, case)
            missing = sorted(set(case.expected_fact_ids) - {f for p in found for f in p.fact_ids})
            detail = "covered" if passed else f"missed {missing[:3]}"

        card.outcomes.append(Outcome(case.id, case.evaluation_type, passed, detail))

    return card


# ---------------------------------------------------------------------------
# The credibility reading: two ranking families, compared per family
# ---------------------------------------------------------------------------

#: A family is reported as a "disagreement" once at least this fraction of its
#: cases are ones the retrievers split on — one passed, the other failed. Set
#: to a full third rather than "any split at all" because families run as small
#: as two or three cases (see `test_every_question_shape_is_represented`), and
#: two independent heuristics differing on a single case out of three is not yet
#: a pattern. A third means at least two cases have to split before a family of
#: six is flagged, which is where a difference stops looking like noise.
DISAGREEMENT_FRACTION = 1 / 3

Finding = Literal["consistently hard", "consistently easy", "disagreement"]


@dataclass(frozen=True)
class FamilyAgreement:
    """How two (or more) ranking families did on one question type, compared.

    The reading this exists to support: a family every retriever fails is
    *structurally* hard — nothing about swapping the ranking heuristic fixes it,
    so the corpus, not the baseline, is what is making it hard. A family the
    retrievers split on is not evidence about hardness at all; it is evidence
    that one heuristic happens to exploit (or miss) something incidental about
    how that family's questions or passages are worded, which is a finding
    about the corpus worth naming on its own — see `evaluating.md`.
    """

    evaluation_type: EvaluationType
    scores: dict[str, tuple[int, int]]
    """``{retriever: (passed, total)}`` for this family, one entry per retriever
    compared."""
    disagreements: int
    """Cases in this family where the retrievers did not all agree pass/fail."""
    total: int
    finding: Finding


def compare(cards: dict[str, Scorecard]) -> list[FamilyAgreement]:
    """Per-family agreement across the retrievers in *cards*.

    Compared *per case*, not by nearest aggregate pass rate: two retrievers can
    land on the same 3-of-6 for a family while failing entirely different three
    cases, which an aggregate-only comparison would read as "they agree" when
    they manifestly do not. Requires every card in *cards* to have scored the
    same evaluation set — true whenever they all came from one `world`, which is
    the only way the CLI ever builds this dict.
    """
    names = sorted(cards)
    if not names:
        return []

    # Any card enumerates the same cases in the same order (`score()` always
    # walks `list(world.evaluations)`), so the first is as good a source of
    # "which cases belong to which family, in what order" as any other.
    outcomes_by_case = {name: {o.case_id: o for o in cards[name].outcomes} for name in names}
    families: dict[EvaluationType, list[str]] = {}
    for outcome in cards[names[0]].outcomes:
        families.setdefault(outcome.evaluation_type, []).append(outcome.case_id)

    findings = []
    for kind in sorted(families, key=lambda k: k.value):
        case_ids = families[kind]
        disagreements = sum(
            1
            for case_id in case_ids
            if len({outcomes_by_case[name][case_id].passed for name in names}) > 1
        )
        total = len(case_ids)
        scores = {name: cards[name].by_type().get(kind, (0, 0)) for name in names}
        case_total = sum(t for _, t in scores.values())
        rate = (sum(p for p, _ in scores.values()) / case_total) if case_total else 0.0

        if total and disagreements / total >= DISAGREEMENT_FRACTION:
            finding: Finding = "disagreement"
        elif rate < 0.5:
            finding = "consistently hard"
        else:
            finding = "consistently easy"
        findings.append(FamilyAgreement(kind, scores, disagreements, total, finding))
    return findings


def render_agreement(findings: list[FamilyAgreement]) -> str:
    """The comparison table for the terminal — `str(Scorecard)`'s sibling.

    A family printed as "disagreement" is a prompt to go read `evaluating.md`'s
    credibility section and the two retrievers' actual outcomes for that family,
    not a number to shrug at.
    """
    if not findings:
        return "(nothing to compare)"
    names = sorted(findings[0].scores)
    label = {"consistently hard": "hard for both", "consistently easy": "easy for both", "disagreement": "DISAGREEMENT"}
    width = max(len(f.evaluation_type.value) for f in findings)
    lines = [f"Agreement — {' vs '.join(n.upper() for n in names)}", "─" * (width + 46)]
    for finding in findings:
        cells = "  ".join(f"{name} {p:>2}/{t:<2}" for name, (p, t) in finding.scores.items())
        lines.append(f"  {finding.evaluation_type.value.ljust(width)}  {cells}  {label[finding.finding]}")
    return "\n".join(lines)
