"""The run ledger: write it, summarize it, compare two of them, import Eval Studio's.

Eval Studio exports one CSV per run and computes nothing over it: no mean,
no pass rate, no slice, and a comparison that joins two exports on the exact
query string and reports a per-row delta. This module is the aggregation
layer it does not have, over the three-axis results ``runner`` produces.

Two rules carry over from ``gemini_enterprise.results`` because they were
right there and are right here. A result with an ``error`` is counted and
excluded from every mean: a crashed agent or a rate-limited rater is not a
zero. And a comparison is keyed on case id, never on query text, because two
cases may ask the same words of different fixtures; Eval Studio's own CSV
carries only the text, so its results are joined back to cases by text
*once*, at import, where a duplicate is refused rather than guessed.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pydantic import ConfigDict, Field

from ..corpus import write_json
from ..models import Model
from .contract import EvalCase
from .grading import CaseScore
from .runner import RUN_SCHEMA, CaseResult, Latency, RunReport, case_set_digest

#: Eval Studio's delta bands, from `compare-evals.component.ts`: a change
#: inside ±0.10 is stable, outside is an improvement or a regression.
DELTA_BAND = 0.10


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


class AxisMeans(Model):
    """Per-axis means over the rows that observed the axis; absent when none did."""

    plan: float | None
    trajectory: float | None
    outcomes: float | None
    overall: float


def _axis_mean(scores: Sequence[CaseScore], axis: str) -> float | None:
    observed = [getattr(score, axis).score for score in scores if axis in score.observed]
    return _mean(observed) if observed else None


class RunSlice(Model):
    key: str
    cases: int
    graded: int
    errors: int
    passed: int
    pass_rate: float
    means: AxisMeans


class RunSummary(Model):
    schema_version: str = Field(default="worldloom.eval-run-summary/v1", alias="schema")
    agent: str
    case_set: str
    cases: int
    graded: int
    errors: int
    passed: int
    pass_rate: float
    means: AxisMeans
    #: Trajectory vocabulary, as rates over the graded cases that observed a
    #: trajectory; absent when none did (a plan-only run, a Studio import).
    exact_match_rate: float | None
    in_order_match_rate: float | None
    any_order_match_rate: float | None
    mean_calls: float | None
    error_codes: dict[str, int]
    safety_findings: dict[str, int]
    #: Question laws broken across the graded cases, and the questions asked
    #: against the points the set required.
    question_findings: dict[str, int] = Field(default_factory=dict)
    questions_asked: int = 0
    questions_expected: int = 0
    questions_honoured: int = 0
    assertion_status: dict[str, int]
    #: Structured outcome expectations met over all expected, across cases.
    structured_met: int
    structured_expected: int
    collateral_cases: int
    #: Answer-axis rows a rater actually judged, and how many it refused.
    answers_rated: int
    answers_unrated: int
    #: Latency means over timed rows only; absent when no clock ran.
    timed: int
    mean_ttlt: float | None = None
    by_shape: tuple[RunSlice, ...]
    by_connector: tuple[RunSlice, ...]
    by_failure: tuple[RunSlice, ...]

    model_config = ConfigDict(populate_by_name=True)


def _slice(key: str, rows: Sequence[CaseResult]) -> RunSlice:
    graded = [row for row in rows if row.graded]
    scores = [row.score for row in graded if row.score is not None]
    return RunSlice(
        key=key, cases=len(rows), graded=len(graded), errors=len(rows) - len(graded),
        passed=sum(1 for score in scores if score.passed),
        pass_rate=_mean([1.0 if score.passed else 0.0 for score in scores]),
        means=AxisMeans(
            plan=_axis_mean(scores, "plan"), trajectory=_axis_mean(scores, "trajectory"),
            outcomes=_axis_mean(scores, "outcomes"), overall=_mean([score.score for score in scores]),
        ),
    )


def summarize(report: RunReport) -> RunSummary:
    rows = list(report.results)
    graded = [row for row in rows if row.graded]
    scores = [row.score for row in graded if row.score is not None]
    codes: Counter[str] = Counter()
    laws: Counter[str] = Counter()
    question_laws: Counter[str] = Counter()
    questions_asked = questions_expected = questions_honoured = 0
    statuses: Counter[str] = Counter()
    met = expected = collateral = rated = unrated = 0
    for score in scores:
        codes.update(score.trajectory.error_codes)
        laws.update(finding.law for finding in score.trajectory.safety)
        question_laws.update(finding.law for finding in score.trajectory.question_findings)
        questions_asked += score.trajectory.questions_asked
        questions_expected += score.trajectory.questions_expected
        questions_honoured += score.trajectory.questions_honoured
        statuses[score.assertion_status] += 1
        met += score.outcomes.structured_met
        expected += score.outcomes.structured_expected
        collateral += bool(score.outcomes.collateral)
        rated += score.outcomes.answer_score is not None
        unrated += score.outcomes.answer_error is not None
    timed = [row.latency.ttlt for row in rows if row.latency is not None]
    executed = [score for score in scores if "trajectory" in score.observed]
    walked = [row for row in graded if row.score is not None and "trajectory" in row.score.observed]
    by_connector: dict[str, list[CaseResult]] = defaultdict(list)
    for row in rows:
        for connector in sorted({str(span.get("tool", "")).split(".")[0] for span in row.spans} or {"none"}):
            by_connector[connector].append(row)
    by_shape: dict[str, list[CaseResult]] = defaultdict(list)
    by_failure: dict[str, list[CaseResult]] = defaultdict(list)
    for row in rows:
        by_shape[row.shape or "legacy"].append(row)
        by_failure[row.dimensions.get("failure", "none")].append(row)
    return RunSummary(
        agent=report.agent, case_set=report.case_set, cases=len(rows), graded=len(graded),
        errors=len(rows) - len(graded), passed=sum(1 for score in scores if score.passed),
        pass_rate=_mean([1.0 if score.passed else 0.0 for score in scores]),
        means=_slice("all", rows).means,
        exact_match_rate=_mean([1.0 if score.trajectory.exact_match else 0.0 for score in executed]) if executed else None,
        in_order_match_rate=_mean([1.0 if score.trajectory.in_order_match else 0.0 for score in executed]) if executed else None,
        any_order_match_rate=_mean([1.0 if score.trajectory.any_order_match else 0.0 for score in executed]) if executed else None,
        mean_calls=_mean([float(row.calls) for row in walked]) if walked else None,
        error_codes=dict(sorted(codes.items())), safety_findings=dict(sorted(laws.items())),
        question_findings=dict(sorted(question_laws.items())), questions_asked=questions_asked,
        questions_expected=questions_expected, questions_honoured=questions_honoured,
        assertion_status=dict(sorted(statuses.items())),
        structured_met=met, structured_expected=expected, collateral_cases=collateral,
        answers_rated=rated, answers_unrated=unrated,
        timed=len(timed), mean_ttlt=_mean(timed) if timed else None,
        by_shape=tuple(_slice(key, by_shape[key]) for key in sorted(by_shape)),
        by_connector=tuple(_slice(key, by_connector[key]) for key in sorted(by_connector)),
        by_failure=tuple(_slice(key, by_failure[key]) for key in sorted(by_failure)),
    )


# -- ledger -------------------------------------------------------------------


def _result_line(result: CaseResult) -> str:
    return json.dumps(result.model_dump(mode="json"), sort_keys=True, default=str) + "\n"


def append_result(directory: Path, result: CaseResult) -> None:
    """One graded case onto ``results.jsonl`` as it lands.

    A run over a slow agent can take longer than the wall clock it is given.
    Written only at the end, a killed run leaves nothing; written as each
    case completes, it leaves every case that finished. ``write_run`` then
    rewrites the same lines in the same order, so a run that completes is
    byte-identical whether or not it checkpointed.
    """

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "results.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_result_line(result))


def write_run(directory: Path, report: RunReport) -> RunSummary:
    """``run.json`` (identity), ``results.jsonl`` (one case per line), ``summary.json``."""

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "results.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for result in report.results:
            handle.write(_result_line(result))
    summary = summarize(report)
    write_json(directory / "run.json", {"schema": RUN_SCHEMA, "agent": report.agent, "principal": report.principal,
                                        "case_set": report.case_set, "cases": len(report.results)})
    write_json(directory / "summary.json", summary.model_dump(mode="json", by_alias=True))
    return summary


def read_run(directory: Path) -> RunReport:
    header = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    if header.get("schema") != RUN_SCHEMA:
        raise ValueError(f"{directory}: not an eval run ({header.get('schema')!r})")
    results = []
    with (directory / "results.jsonl").open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    results.append(CaseResult.model_validate_json(line))
                except ValueError as error:
                    raise ValueError(f"{directory / 'results.jsonl'}:{number}: invalid result") from error
    return RunReport(agent=str(header["agent"]), principal=str(header.get("principal", "agent")),
                     case_set=str(header["case_set"]), results=tuple(results))


# -- comparison ---------------------------------------------------------------


class CaseDelta(Model):
    case_id: str
    baseline: float | None
    recent: float | None
    delta: float | None
    #: Which axes moved by more than the band, signed.
    axes: dict[str, float]
    verdict: str


class Comparison(Model):
    schema_version: str = Field(default="worldloom.eval-run-comparison/v1", alias="schema")
    baseline_agent: str
    recent_agent: str
    same_case_set: bool
    compared: int
    only_baseline: tuple[str, ...]
    only_recent: tuple[str, ...]
    improvements: tuple[str, ...]
    regressions: tuple[str, ...]
    stable: int
    #: Cases graded on one side and errored on the other: a change in
    #: reliability, reported separately from a change in score.
    newly_errored: tuple[str, ...]
    newly_graded: tuple[str, ...]
    mean_delta: float
    axis_deltas: AxisMeans
    deltas: tuple[CaseDelta, ...]

    model_config = ConfigDict(populate_by_name=True)


def compare(baseline: RunReport, recent: RunReport) -> Comparison:
    """Per-case deltas by case id, with Eval Studio's ±0.10 bands, plus what it lacks."""

    left = {row.case_id: row for row in baseline.results}
    right = {row.case_id: row for row in recent.results}
    shared = sorted(set(left) & set(right))
    deltas: list[CaseDelta] = []
    improvements: list[str] = []
    regressions: list[str] = []
    newly_errored: list[str] = []
    newly_graded: list[str] = []
    stable = 0
    axis_totals: dict[str, list[float]] = defaultdict(list)
    for case_id in shared:
        a, b = left[case_id], right[case_id]
        if a.graded and not b.graded:
            newly_errored.append(case_id)
        elif b.graded and not a.graded:
            newly_graded.append(case_id)
        if not (a.graded and b.graded) or a.score is None or b.score is None:
            deltas.append(CaseDelta(case_id=case_id, baseline=a.score.score if a.score else None,
                                    recent=b.score.score if b.score else None, delta=None, axes={}, verdict="ungraded"))
            continue
        # An axis only one side observed has no delta: a plan-only run
        # against an executed one compares on the plan axis and nowhere else,
        # and its overall delta is the mean over the axes both observed. Two
        # runs with no axis in common have no delta at all.
        axes = {
            axis: round(getattr(b.score, axis).score - getattr(a.score, axis).score, 4)
            for axis in ("plan", "trajectory", "outcomes")
            if axis in a.score.observed and axis in b.score.observed
        }
        for axis, value in axes.items():
            axis_totals[axis].append(value)
        if not axes:
            deltas.append(CaseDelta(case_id=case_id, baseline=a.score.score, recent=b.score.score, delta=None,
                                    axes={}, verdict="unobserved"))
            continue
        same_axes = set(a.score.observed) == set(b.score.observed)
        delta = round(b.score.score - a.score.score, 4) if same_axes else _mean(list(axes.values()))
        if delta > DELTA_BAND:
            verdict = "improvement"
            improvements.append(case_id)
        elif delta < -DELTA_BAND:
            verdict = "regression"
            regressions.append(case_id)
        else:
            verdict = "stable"
            stable += 1
        deltas.append(CaseDelta(case_id=case_id, baseline=a.score.score, recent=b.score.score, delta=delta,
                                axes={axis: value for axis, value in axes.items() if abs(value) > DELTA_BAND},
                                verdict=verdict))
    graded_deltas = [item.delta for item in deltas if item.delta is not None]
    return Comparison(
        baseline_agent=baseline.agent, recent_agent=recent.agent,
        same_case_set=baseline.case_set == recent.case_set, compared=len(shared),
        only_baseline=tuple(sorted(set(left) - set(right))), only_recent=tuple(sorted(set(right) - set(left))),
        improvements=tuple(improvements), regressions=tuple(regressions), stable=stable,
        newly_errored=tuple(newly_errored), newly_graded=tuple(newly_graded),
        mean_delta=_mean(graded_deltas),
        axis_deltas=AxisMeans(plan=_mean(axis_totals["plan"]) if axis_totals["plan"] else None,
                              trajectory=_mean(axis_totals["trajectory"]) if axis_totals["trajectory"] else None,
                              outcomes=_mean(axis_totals["outcomes"]) if axis_totals["outcomes"] else None,
                              overall=_mean(graded_deltas)),
        deltas=tuple(deltas),
    )


# -- Eval Studio ---------------------------------------------------------------

#: Eval Studio's `ResultRow`, verbatim column names.
STUDIO_COLUMNS = ("query", "golden", "fetched", "ttft", "ttfa", "ttlt", "score", "scoreError")


def to_studio_rows(report: RunReport, cases: Mapping[str, EvalCase] | None = None) -> tuple[dict[str, str], ...]:
    """The run as rows Eval Studio's Compare tab reads. Lossy: one score, no axes."""

    rows = []
    for result in report.results:
        case = (cases or {}).get(result.case_id)
        golden = case.outcomes.answer.golden if case is not None and case.outcomes.answer is not None else ""
        score = result.score.score if result.score is not None else 0.0
        rows.append({
            "query": result.query, "golden": golden, "fetched": result.answer,
            "ttft": str(result.latency.ttft or 0) if result.latency else "0",
            "ttfa": str(result.latency.ttfa or 0) if result.latency else "0",
            "ttlt": str(result.latency.ttlt) if result.latency else "0",
            "score": f"{score:.4f}", "scoreError": result.error or "",
        })
    return tuple(rows)


def write_studio_csv(path: Path, rows: Iterable[Mapping[str, str]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STUDIO_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in STUDIO_COLUMNS})
            count += 1
    return count


def _seconds(row: Mapping[str, str], column: str) -> float | None:
    try:
        parsed = float(row.get(column) or 0.0)
    except ValueError:
        return None
    return parsed or None


def import_served(path: Path, cases: Iterable[EvalCase], *, agent: str = "served") -> RunReport:
    """Case results an external agent collected from `eval_score`, as a run.

    One `eval_score` document per line. Each is a complete `CaseResult`
    graded by the service that served the run, so nothing is re-graded here:
    the ledger records what the service observed. A result whose case id is
    not in the case set is refused, because a ledger attributed to the wrong
    set compares against the wrong ceiling; a case with no result is an
    `not_attempted` error row, never a pass.
    """

    listed = list(cases)
    known = {case.id: case for case in listed}
    collected: dict[str, CaseResult] = {}
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                result = CaseResult.model_validate_json(line)
            except ValueError as error:
                raise ValueError(f"{path}:{number}: not an eval_score result") from error
            if result.case_id not in known:
                raise ValueError(f"{path}:{number}: case {result.case_id!r} is not in this case set")
            if result.case_id in collected:
                raise ValueError(f"{path}:{number}: case {result.case_id!r} appears twice; keep one result per case")
            collected[result.case_id] = result.model_copy(update={"agent": agent})
    results = tuple(
        collected.get(case.id) or CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions,
                                             shape=case.plan.shape, agent=agent, status="error",
                                             error="not_attempted: no eval_score result for this case")
        for case in listed
    )
    return RunReport(agent=agent, principal="served", case_set=case_set_digest(listed), results=results)


def import_studio_results(path: Path, cases: Iterable[EvalCase], *, agent: str = "eval-studio") -> RunReport:
    """Eval Studio's results CSV as a run: the answer axis only, joined on query text.

    Eval Studio drops every column it was given except ``query`` and
    ``golden`` and never observes a tool call, so an imported row carries an
    answer score, its three latencies, and nothing about plan or trajectory.
    The report says so: plan and trajectory grades are absent, the overall
    score is the answer score alone, and a duplicate query text refuses.
    """

    from .grading import (
        CaseScore,
        unobserved_outcomes,
        unobserved_plan,
        unobserved_trajectory,
    )

    listed = list(cases)
    by_query: dict[str, EvalCase] = {}
    for listed_case in listed:
        if listed_case.query in by_query:
            raise ValueError(f"two cases ask {listed_case.query[:60]!r}; Eval Studio results cannot be attributed")
        by_query[listed_case.query] = listed_case
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    results: list[CaseResult] = []
    for row in rows:
        query = (row.get("query") or "").strip()
        case = by_query.get(query)
        if case is None:
            continue
        error = (row.get("scoreError") or "").strip() or None
        fetched = row.get("fetched") or row.get("response") or ""
        if fetched.startswith("Error:"):
            error = error or fetched
        try:
            value = float(row.get("score") or 0.0)
        except ValueError:
            error = error or f"unparseable score {row.get('score')!r}"
            value = 0.0

        ttlt = _seconds(row, "ttlt")
        latency = Latency(ttft=_seconds(row, "ttft"), ttfa=_seconds(row, "ttfa"), ttlt=ttlt) if ttlt else None
        if error is not None:
            results.append(CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions,
                                      shape=case.plan.shape, agent=agent, status="error", error=error,
                                      answer=fetched, latency=latency))
            continue
        value = max(0.0, min(1.0, value))
        outcomes = unobserved_outcomes(value)
        score = CaseScore(plan=unobserved_plan(), trajectory=unobserved_trajectory(), outcomes=outcomes,
                          assertion_status="unobserved", assertion_fails=(), observed=("outcomes",),
                          score=value, passed=outcomes.passed)
        results.append(CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions, shape=case.plan.shape,
                                  agent=agent, status="graded", score=score, answer=fetched, latency=latency,
                                  notes=("answer axis only: Eval Studio observes no tool call",)))
    return RunReport(agent=agent, principal="eval-studio", case_set=case_set_digest(listed), results=tuple(results))


__all__ = [
    "DELTA_BAND",
    "STUDIO_COLUMNS",
    "AxisMeans",
    "CaseDelta",
    "Comparison",
    "RunSlice",
    "RunSummary",
    "append_result",
    "compare",
    "import_served",
    "import_studio_results",
    "read_run",
    "summarize",
    "to_studio_rows",
    "write_run",
    "write_studio_csv",
]
