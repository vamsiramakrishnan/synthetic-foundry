"""Evaluation-case mechanics, shared by every vertical's taxonomy.

Extracted from the retail taxonomy and the banking families once both existed
— the same after-two rule as ``org_builder``. What repeats is mechanism: how a
case is minted, how an abstention is phrased, how a value is written the way a
reader would write it, and the gate every family must end with. What does not
repeat — which questions are worth asking, and why each is hard — stays in the
domain's own module, because that is the judgement a vertical exists to make.

The reachability gate is the one invariant that must never fork: a case whose
expected facts no planned artifact carries is unanswerable, and both the
retail and banking taxonomies must refuse it identically, in exact agreement
with ``validate.py``'s ``unreachable_answer`` check.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ..ids import Minter
from ..models import ArtifactIntent, CanonicalFact, EvaluationCase, EvaluationType


def fmt(fact: CanonicalFact) -> str:
    """A fact's value as a reader would write it."""
    if fact.value is not None:
        amount = fact.value.amount
        rendered = f"{int(amount):,}" if float(amount).is_integer() else f"{amount:,.2f}"
        return f"{rendered} {fact.value.unit}"
    return fact.text_value or ""


def adverse(fact: CanonicalFact) -> str:
    """A variance as a reader states it: magnitude and direction, not a sign.

    An expected answer is graded against a system's prose, so "7,200 below
    budget" is a fairer target than "-7200".
    """
    if fact.value is None:
        return fact.text_value or ""
    amount = fact.value.amount
    magnitude = f"{abs(int(amount)):,}" if float(amount).is_integer() else f"{abs(amount):,.2f}"
    return f"{magnitude} {fact.value.unit} {'below' if amount < 0 else 'above'} budget"


class CaseBuilder:
    """Mints evaluation cases in order, so ``EVAL`` ids stay append-only."""

    def __init__(self, minter: Minter) -> None:
        self.minter = minter
        self.cases: list[EvaluationCase] = []

    def case(
        self,
        question: str,
        kind: EvaluationType,
        answer: str,
        facts: list[str],
        *,
        cutoff: datetime | None = None,
        difficulty: str = "medium",
        reasoning: str = "",
        sources: list[str | None] | None = None,
        distractors: list[str | None] | None = None,
    ) -> None:
        self.cases.append(
            EvaluationCase(
                id=self.minter.next("EVAL"),
                question=question,
                evaluation_type=kind,
                expected_answer=answer,
                expected_fact_ids=facts,
                required_artifact_ids=[a for a in (sources or []) if a],
                distractor_artifact_ids=[a for a in (distractors or []) if a],
                temporal_cutoff=cutoff,
                difficulty=difficulty,  # type: ignore[arg-type]
                reasoning=reasoning,
            )
        )

    def abstain(self, question: str, reasoning: str) -> None:
        self.cases.append(
            EvaluationCase(
                id=self.minter.next("EVAL"),
                question=question,
                evaluation_type=EvaluationType.EXPECTED_ABSTENTION,
                expected_answer="Not present in the corpus.",
                expects_abstention=True,
                difficulty="hard",
                reasoning=reasoning,
            )
        )


def reachable_fact_ids(*intent_sets: Iterable[ArtifactIntent]) -> frozenset[str]:
    """Every fact id some planned artifact actually requires.

    Mirrors ``validate.py``'s ``unreachable_answer`` check exactly —
    deliberately, not approximately, because the two have to agree.
    """
    ids: set[str] = set()
    for intents in intent_sets:
        for intent in intents:
            ids.update(intent.required_fact_ids)
    return frozenset(ids)


def answerable(
    cases: Iterable[EvaluationCase], reachable: frozenset[str]
) -> tuple[EvaluationCase, ...]:
    """The cases whose every expected fact some artifact carries.

    The last pass of the rule each family is supposed to apply for itself: a
    dropped case here is a question that would have been generated and then
    refused by the validator — catching it before minting means it is never in
    the corpus at all.
    """
    return tuple(
        case
        for case in cases
        if case.expects_abstention or set(case.expected_fact_ids) <= reachable
    )
