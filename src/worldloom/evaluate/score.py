"""Scoring the baseline against the corpus's own evaluation set.

Every question type is scored on the thing that type is actually testing, and the
grading is objective in each case because the manifest records what it needs to
be:

``direct_lookup`` and friends
    Did retrieval surface a passage carrying the facts the answer rests on?
``temporal_state``
    An author writing at 09:30 could not cite a cause confirmed at 13:20. The
    baseline sees every document at once, so this is where a system with no
    notion of *when* a document was written gets caught.
``authority_resolution``
    Several documents carry the fact; only one is the record. Ranking by keyword
    overlap has no reason to prefer it.
``expected_abstention``
    The corpus does not contain the answer. Retrieving something confident is the
    failure, so the score is whether the retriever stayed quiet.

There is no model anywhere in this. A judge would put the thing under test inside
the measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..models import EvaluationType
from .bm25 import Bm25
from .index import Passage, passages

if TYPE_CHECKING:  # pragma: no cover
    from ..models import EvaluationCase
    from ..world import World

#: How many passages the baseline is allowed to return.
DEFAULT_K = 5

#: Below this BM25 score a retrieval counts as "nothing found". Calibrated from
#: the corpus rather than chosen: it is a fraction of the median top score across
#: answerable questions, so a corpus with longer documents does not silently
#: become a corpus that never abstains.
ABSTENTION_FRACTION = 0.35


@dataclass(frozen=True)
class Outcome:
    """How the baseline did on one question."""

    case_id: str
    evaluation_type: EvaluationType
    passed: bool
    detail: str


@dataclass
class Scorecard:
    """Per-type results, and the totals."""

    outcomes: list[Outcome] = field(default_factory=list)
    k: int = DEFAULT_K

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
        lines = [f"Baseline retrieval @{self.k}", "─" * 52]
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


def score(world: World, *, k: int = DEFAULT_K) -> Scorecard:
    """Run the baseline over every evaluation case in *world*."""
    pool = passages(world)
    if not pool:
        raise ValueError("nothing to retrieve from — render or compile the corpus first")

    index = Bm25([passage.text for passage in pool])
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

    card = Scorecard(k=k)
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
                best_rank = max(p.authority_rank for p in carrying)
                passed = found[0].authority_rank >= best_rank
                detail = f"top passage authority {found[0].authority.value}"

        else:
            passed = _covers(found, case)
            missing = sorted(set(case.expected_fact_ids) - {f for p in found for f in p.fact_ids})
            detail = "covered" if passed else f"missed {missing[:3]}"

        card.outcomes.append(Outcome(case.id, case.evaluation_type, passed, detail))

    return card
