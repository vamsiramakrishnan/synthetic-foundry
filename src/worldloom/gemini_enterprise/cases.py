"""Evaluation cases as the CSV Eval Studio reads, one rubric per grading shape.

Eval Studio's input is `query` and `golden`, and its grader is a single
`autoRaterInstruction` applied to every row of a run. Both of those are the
whole of the contract, and the second one is where a naive export goes wrong.

The default instruction asks for semantic similarity between the fetched answer
and the golden one. That is a defensible grader for a lookup and a bad one for
half of what this engine generates. `EXPECTED_ABSTENTION` is the clearest case:
its golden answer is a sentence saying the corpus holds nothing, and the
behaviour under test is a refusal. Under similarity scoring, a model that
invents a confident, fluent, wrong answer is scored against a refusal and gets
whatever partial credit the fluency earns, while the one thing the case exists
to reward -- saying "I cannot answer that" -- is scored as though it were an
attempt. The rubric has to know which shape it is grading.

So a set does not export as one CSV. It exports as one CSV per
`EvaluationType`, each with the rubric that shape claims, and the manifest says
which instruction to paste into which run. That also happens to be the natural
way to live within the hundred-row truncation, which is the other thing a naive
export gets wrong: `csv.service.ts` reads `results.data.slice(0, 100)`, so
rows one hundred and one onward are not rejected, they are not sent, and the
run reports a clean pass over a set it never saw.

The rubrics are written as *prefixes*. Eval Studio appends the query, the
fetched response, the golden response and a fixed trailer asking for a float
between 0.0 and 1.0, so an instruction here must set up that trailer and must
not contradict it by asking for a verdict, a letter, or a percentage.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..models import EvaluationCase, EvaluationType

#: How Eval Studio truncates an uploaded CSV, in `csv.service.ts`. Not a
#: preference and not configurable from the UI: rows past this one are dropped
#: silently at parse time, so a shard larger than this is a shard that lies
#: about what it tested.
ROW_LIMIT = 100

#: The two columns Eval Studio reads, then what it ignores. `CSVRow` is typed
#: `{query, golden, [key: string]: string}`, so the extra columns ride along
#: harmlessly -- and are dropped again on the way out, because `processRow`
#: builds its `ResultRow` from scratch. They are here for the human who opens
#: the file; `results.score` recovers them by joining on the query text.
COLUMNS: tuple[str, ...] = (
    "query",
    "golden",
    "case_id",
    "evaluation_type",
    "difficulty",
    "expects_abstention",
)

_SCALE = (
    "Answer with a single float between 0.0 and 1.0, where 1.0 is a fully"
    " correct response and 0.0 is a wrong one."
)

#: One auto-rater instruction per grading shape.
#:
#: Each says what *this* shape counts as correct, because the thing that
#: distinguishes these cases is not how similar the prose is. Two answers can
#: be near-identical and one of them wrong, and the difference is always
#: structural: a superseded reading, a number off by a factor, the right value
#: from the wrong authority, a fluent answer where a refusal was the point.
RUBRICS: dict[EvaluationType, str] = {
    EvaluationType.DIRECT_LOOKUP: (
        "You are grading a factual lookup against a system of record. The"
        " golden response contains a specific value. Score on whether the"
        " fetched response states that same value, with the same units and"
        " period. Wording may differ freely. A fluent answer carrying a"
        " different number is wrong, not partially right: score it 0.0."
        f" {_SCALE}"
    ),
    EvaluationType.CROSS_ARTIFACT: (
        "You are grading an answer that had to combine information from more"
        " than one document. The golden response contains several elements."
        " Score the fraction of those elements the fetched response states"
        " correctly. An answer that gets one element right and omits the rest"
        " has done the lookup and not the join, and should score low rather"
        " than half."
        f" {_SCALE}"
    ),
    EvaluationType.NUMERICAL_COMPARISON: (
        "You are grading a comparison between quantities. Both the direction"
        " of the comparison and the magnitude must match the golden response."
        " An answer with the right direction and a wrong magnitude scores at"
        " most 0.5; an answer with the wrong direction scores 0.0 however"
        " close the numbers are."
        f" {_SCALE}"
    ),
    EvaluationType.CAUSAL_MULTI_HOP: (
        "You are grading a causal explanation. The golden response names a"
        " chain: a cause, its effect, and the link between them. Score on"
        " whether the fetched response reaches the same conclusion *by the"
        " same chain*. A correct conclusion reached by a different or unstated"
        " mechanism scores at most 0.4, because the case tests the reasoning"
        " and not the guess."
        f" {_SCALE}"
    ),
    EvaluationType.TEMPORAL_STATE: (
        "You are grading a question about the state of things at a particular"
        " moment. The golden response describes the state as of that moment."
        " A later or superseded reading is wrong even when it is the current"
        " truth, and even when the corpus contains a document saying it:"
        " score that 0.0. Score 1.0 only for the state as of the asked-about"
        " time."
        f" {_SCALE}"
    ),
    EvaluationType.AUTHORITY_RESOLUTION: (
        "You are grading an answer where two sources disagree and one of them"
        " governs. The golden response carries the authoritative answer. Score"
        " 1.0 only when the fetched response gives that answer. An answer"
        " that reports the non-authoritative source's version, or that reports"
        " both without resolving them, scores 0.0: the case is the resolution,"
        " not the retrieval."
        f" {_SCALE}"
    ),
    EvaluationType.EXPECTED_ABSTENTION: (
        "You are grading whether a system correctly refused to answer. The"
        " corpus does not contain the information asked for, and the golden"
        " response says so. Score 1.0 when the fetched response declines,"
        " says it cannot find the information, or states that the corpus does"
        " not contain it. Score 0.0 for ANY substantive answer to the"
        " question, however plausible, fluent, or superficially similar to the"
        " golden response it is. Do not reward an attempt for being"
        " well-written. Confidence in the absence of evidence is the exact"
        " failure this case tests."
        f" {_SCALE}"
    ),
    EvaluationType.CITATION_REQUIRED: (
        "You are grading whether an answer names its source. Score 1.0 only"
        " when the fetched response is correct AND identifies the document,"
        " report or system it came from. A correct answer citing nothing"
        " scores at most 0.3. Judge only what the response text says: an"
        " attached citation the text does not mention cannot be seen here."
        f" {_SCALE}"
    ),
}


@dataclass(frozen=True)
class Shard:
    """One uploadable CSV: the rows, and the rubric to grade them with."""

    evaluation_type: EvaluationType
    part: int
    """1-based, because a shape with more than `ROW_LIMIT` cases splits."""
    parts: int
    rows: tuple[dict[str, str], ...]
    rubric: str

    @property
    def name(self) -> str:
        """The file stem, stable and sortable."""
        if self.parts == 1:
            return str(self.evaluation_type.value)
        return f"{self.evaluation_type.value}-{self.part:02d}"

    def csv(self) -> str:
        """This shard as CSV text.

        Written through `csv.writer` with the line terminator pinned to `\\n`:
        the module default is `\\r\\n`, and `.gitattributes` pins LF everywhere
        because byte-identity fixtures depend on it.
        """
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        return buffer.getvalue()


def rows(cases: Iterable[EvaluationCase]) -> tuple[dict[str, str], ...]:
    """Every case as a CSV row, sorted by id.

    A case with no `expected_answer` is skipped rather than exported with an
    empty golden: Eval Studio treats a falsy golden as "do not score" and
    returns 0, which is indistinguishable in the results from a model that
    answered and got it wrong. Silently converting a missing ground truth into
    a zero score is the kind of clean-looking number this repository exists to
    refuse.
    """
    out: list[dict[str, str]] = []
    for case in sorted(cases, key=lambda c: c.id):
        if not case.expected_answer:
            continue
        out.append(
            {
                "query": case.question,
                "golden": case.expected_answer,
                "case_id": case.id,
                "evaluation_type": str(case.evaluation_type.value),
                "difficulty": case.difficulty,
                "expects_abstention": "true" if case.expects_abstention else "false",
            }
        )
    return tuple(out)


def shards(
    cases: Iterable[EvaluationCase], *, limit: int = ROW_LIMIT
) -> tuple[Shard, ...]:
    """The set split into uploadable runs: one grading shape each, capped at *limit*.

    Sorted by shape then part, so two exports of one corpus produce the same
    files in the same order.
    """
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    by_shape: dict[str, list[dict[str, str]]] = {}
    for row in rows(cases):
        by_shape.setdefault(row["evaluation_type"], []).append(row)

    out: list[Shard] = []
    for shape_value in sorted(by_shape):
        shape = EvaluationType(shape_value)
        held: Sequence[dict[str, str]] = by_shape[shape_value]
        chunks = [held[i : i + limit] for i in range(0, len(held), limit)]
        for index, chunk in enumerate(chunks, start=1):
            out.append(
                Shard(
                    evaluation_type=shape,
                    part=index,
                    parts=len(chunks),
                    rows=tuple(chunk),
                    rubric=RUBRICS[shape],
                )
            )
    return tuple(out)


__all__ = ["COLUMNS", "ROW_LIMIT", "RUBRICS", "Shard", "rows", "shards"]
