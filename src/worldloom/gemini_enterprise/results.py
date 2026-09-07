"""Eval Studio's results, rejoined to the structure its CSV could not carry.

Eval Studio exports one row per query: the fetched answer, three latencies, and
a score. What it does not export is anything it was given beyond `query` and
`golden` -- `processRow` builds its `ResultRow` from scratch, so the case id,
the grading shape and the difficulty that went up with the upload do not come
back down. A results file on its own is therefore a mean and nothing else, and
a mean over a set deliberately built from eight different grading shapes is the
one number least worth having.

So the join is on the query text, which is what survives the round trip. That
is sound exactly as long as no two cases ask the same question, and `score`
refuses rather than guesses when two do: attributing a result to the wrong case
would corrupt the slice silently, and a silently wrong slice is worse than no
slice.

One number is read with care. Eval Studio returns `score: 0` both when the
model was wrong and when the auto-rater call itself failed, and distinguishes
them only by a populated `scoreError`. Averaging those together reports a rate
limit on the grader as a model failure. Rows with an error are counted and
excluded from every mean, and `Scorecard.errors` says how many, because a
benchmark that reports its own outages as the system's poor performance is
worse than one that reports nothing.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..models import EvaluationCase


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


@dataclass(frozen=True)
class Slice:
    """A cohort of results, and what it scored."""

    key: str
    cases: int
    scored: int
    """Rows whose score is a judgement rather than a grader failure.
    `mean_score` is over these, not over `cases`."""
    timed: int
    """Rows whose assist call completed and was timed. The latency means are
    over these, and they are a different subset from `scored`: a grader that
    rate-limited still timed the call it graded, and a call that failed
    outright was still scored (as zero, correctly)."""
    mean_score: float
    mean_ttfa: float
    """Mean seconds to the first answer token. Eval Studio's genuine addition:
    latency against a real endpoint is not something this engine can derive."""
    mean_ttlt: float


def _numbers(rows: Sequence[Mapping[str, str]], column: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        try:
            out.append(float(row.get(column) or 0.0))
        except ValueError:
            # A malformed cell is dropped from the mean rather than read as
            # zero; a results file hand-edited in a spreadsheet is the
            # ordinary way this happens.
            continue
    return out


def _slice(key: str, rows: Sequence[Mapping[str, str]]) -> Slice:
    # Two different subsets, because two different things fail. A populated
    # `scoreError` means the auto-rater call failed, and its `score: 0` is not
    # a judgement -- but the assist call it was grading ran and was timed, so
    # dropping the row from the latency means throws away a real measurement.
    # An assist call that failed outright is the other way round: `processRow`
    # returns all three timings as zero from its catch block, so averaging
    # those in reports the product as faster than it is, while its zero score
    # is a correct judgement about a run that produced no answer.
    scored = [row for row in rows if not (row.get("scoreError") or "").strip()]
    timed = [row for row in rows if _numbers([row], "ttlt") not in ([], [0.0])]

    return Slice(
        key=key,
        cases=len(rows),
        scored=len(scored),
        timed=len(timed),
        mean_score=_mean(_numbers(scored, "score")),
        mean_ttfa=_mean(_numbers(timed, "ttfa")),
        mean_ttlt=_mean(_numbers(timed, "ttlt")),
    )


@dataclass(frozen=True)
class Scorecard:
    """What a run scored, sliced by what the corpus knows about each case."""

    overall: Slice
    by_type: tuple[Slice, ...]
    by_difficulty: tuple[Slice, ...]
    errors: tuple[str, ...] = ()
    """Grader failures, one sentence each, excluded from every mean above."""
    unmatched: tuple[str, ...] = ()
    """Result queries no case in the set asks. A results file from a different
    corpus, or an edited CSV."""
    missing: tuple[str, ...] = ()
    """Case ids with no result row. The hundred-row truncation shows up here:
    a shard uploaded whole and silently cut leaves its tail in this list."""


def read_results(path: str | Path) -> tuple[dict[str, str], ...]:
    """Eval Studio's exported results CSV, as rows."""
    text = Path(path).read_text(encoding="utf-8")
    return tuple(dict(row) for row in csv.DictReader(text.splitlines()))


def score(
    cases: Iterable[EvaluationCase], results: Iterable[Mapping[str, str]]
) -> Scorecard:
    """Join *results* back to *cases* and slice the scores.

    Raises `ValueError` when two cases ask the same question, because the join
    key is the question and there would be no way to say which case a row
    belongs to.
    """
    held = list(cases)
    by_question: dict[str, EvaluationCase] = {}
    for case in sorted(held, key=lambda c: c.id):
        if case.question in by_question:
            raise ValueError(
                f"cases {by_question[case.question].id!r} and {case.id!r} ask"
                " the same question, so an Eval Studio result cannot be"
                " attributed to either: its output carries no case id and the"
                " query text is the only join key that survives the run"
            )
        by_question[case.question] = case

    rows = list(results)
    matched: list[tuple[EvaluationCase, Mapping[str, str]]] = []
    unmatched: list[str] = []
    for row in rows:
        found = by_question.get(row.get("query", ""))
        if found is None:
            unmatched.append(row.get("query", ""))
        else:
            matched.append((found, row))

    seen = {case.id for case, _ in matched}
    missing = sorted(case.id for case in held if case.id not in seen and case.expected_answer)

    errors = tuple(
        f"{case.id!r} was not graded: {(row.get('scoreError') or '').strip()}"
        for case, row in sorted(matched, key=lambda pair: pair[0].id)
        if (row.get("scoreError") or "").strip()
    )

    def grouped(attribute: str) -> tuple[Slice, ...]:
        buckets: dict[str, list[Mapping[str, str]]] = {}
        for case, row in matched:
            value = getattr(case, attribute)
            key = str(getattr(value, "value", value))
            buckets.setdefault(key, []).append(row)
        return tuple(_slice(key, buckets[key]) for key in sorted(buckets))

    return Scorecard(
        overall=_slice("overall", [row for _, row in matched]),
        by_type=grouped("evaluation_type"),
        by_difficulty=grouped("difficulty"),
        errors=errors,
        unmatched=tuple(sorted(unmatched)),
        missing=tuple(missing),
    )


__all__ = ["Scorecard", "Slice", "read_results", "score"]
