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
import os
import warnings
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from .. import packkit
from ..ids import content_key
from ..models import Model
from .contract import EvalCase
from .grading import CaseScore
from .runner import RUN_SCHEMA, CaseResult, Latency, RunReport, case_set_digest


def delta_band() -> float:
    """The band inside which a change is stable: the policy ``evalrun.delta_band``.

    Its shipped value is Eval Studio's, from `compare-evals.component.ts`: a
    change inside ±0.10 is stable, outside is an improvement or a
    regression. A pack may widen it; the default keeps the two tools' verdicts
    the same.
    """
    return float(packkit.policy("evalrun.delta_band"))


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
    # Flushed and synced before the next case starts: a checkpoint the OS
    # still holds in a buffer is not one a killed machine leaves behind.
    with (directory / "results.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_result_line(result))
        handle.flush()
        os.fsync(handle.fileno())


#: The identity fields two ledgers must share to be one run: a resume refuses
#: a ledger that differs in any, and a merge refuses shards that do.
IDENTITY_FIELDS = ("agent", "principal", "case_set", "agent_pack", "grader", "agent_identity", "split")


def _header(report: RunReport, cases: int) -> dict[str, Any]:
    header: dict[str, Any] = {"schema": RUN_SCHEMA, "agent": report.agent, "principal": report.principal,
                              "case_set": report.case_set, "cases": cases}
    # Written only when present, so a run made without them keeps its bytes.
    if report.agent_pack is not None:
        header["agent_pack"] = report.agent_pack
    if report.grader is not None:
        header["grader"] = report.grader
    if report.agent_identity is not None:
        header["agent_identity"] = report.agent_identity
    if report.split is not None:
        header["split"] = report.split
    return header


def _replace(path: Path, lines: Iterable[str]) -> None:
    """*path* rewritten whole or not at all: a synced sibling, then ``os.replace``.

    Truncating in place and writing again leaves, when the process is
    killed between the two, a file with fewer lines than either version. A
    rename within one directory is atomic, so a reader sees the old bytes
    or the new ones; the sibling is synced first so the new ones are on
    disk when the rename is.
    """

    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _replace_json(path: Path, payload: Mapping[str, Any]) -> None:
    # The bytes ``corpus.write_json`` writes, written atomically.
    _replace(path, [json.dumps(payload, indent=2, sort_keys=True) + "\n"])


def write_run(directory: Path, report: RunReport) -> RunSummary:
    """``run.json`` (identity), ``results.jsonl`` (one case per line), ``summary.json``.

    Each file is replaced atomically, and ``run.json`` last: until it is
    replaced, a partial header from ``begin_ledger`` still says the run is
    unfinished, so a kill anywhere in here leaves a ledger ``--resume``
    finishes rather than one that claims to be complete.
    """

    directory.mkdir(parents=True, exist_ok=True)
    _replace(directory / "results.jsonl", (_result_line(result) for result in report.results))
    summary = summarize(report)
    _replace_json(directory / "summary.json", summary.model_dump(mode="json", by_alias=True))
    _replace_json(directory / "run.json", _header(report, len(report.results)))
    return summary


def begin_ledger(directory: Path, identity: RunReport, planned: int) -> None:
    """``run.json`` before the first case, marked ``partial``, so a killed run can be resumed.

    ``identity`` is the run's report with no results yet. ``write_run``
    replaces the header when the run completes, so a finished run's bytes are
    the same whether or not it began this way.
    """

    directory.mkdir(parents=True, exist_ok=True)
    _replace_json(directory / "run.json", {**_header(identity, planned), "partial": True})


class LedgerWarning(UserWarning):
    """A ledger was read with its torn final line dropped."""


def read_results(path: Path) -> tuple[list[CaseResult], str | None]:
    """Every result in a ``results.jsonl``, and a note when a torn final line was dropped.

    A process killed mid-append leaves a last line with no newline and
    only part of its JSON. That line is the case that did not finish, and
    dropping it loses nothing a resume will not redo. Any other line that does
    not parse (one in the middle, or a last line that was terminated) is
    corruption, not a crash, and is refused with its line number.
    """

    data = path.read_bytes()
    *complete, tail = data.split(b"\n")
    results: list[CaseResult] = []
    for number, line in enumerate(complete, start=1):
        if line.strip():
            try:
                results.append(CaseResult.model_validate_json(line))
            except ValueError as error:
                raise ValueError(f"{path}:{number}: invalid result") from error
    note = None
    if tail.strip():
        try:
            results.append(CaseResult.model_validate_json(tail))
        except ValueError:
            note = (f"{path}:{len(complete) + 1}: dropped a torn final line ({len(tail)} bytes), "
                    "the case that was being written when the run stopped")
    return results, note


class PartialRun(ValueError):
    """A run directory whose ``run.json`` still says ``partial``: its ledger is not the whole run."""


def _read_header(directory: Path) -> dict[str, Any]:
    """``run.json``, refused precisely when it is torn or is not an eval run's header."""

    path = directory / "run.json"
    text = path.read_text(encoding="utf-8")
    try:
        header = json.loads(text)
    except ValueError as error:
        raise ValueError(f"{path}: run.json is torn or not JSON ({error}); a write of it was interrupted, "
                         "so the ledger cannot be proven to be any run: run again without --resume") from error
    if not isinstance(header, dict):
        raise ValueError(f"{path}: run.json is not a JSON object; run again without --resume")
    if header.get("schema") != RUN_SCHEMA:
        raise ValueError(f"{directory}: not an eval run ({header.get('schema')!r})")
    return header


def read_run(directory: Path, *, allow_partial: bool = False) -> RunReport:
    """The run in *directory*; refused (``PartialRun``) when it did not finish.

    ``begin_ledger`` marks ``run.json`` partial before the first case and
    ``write_run`` clears it when the last lands, so a partial header means
    ``results.jsonl`` holds only the cases that finished. Summarising,
    comparing or exporting those as the run would report a subset as the
    whole. ``allow_partial`` is for a reader that wants exactly the finished
    cases and knows they are not the run.
    """

    header = _read_header(directory)
    results, note = read_results(directory / "results.jsonl")
    if header.get("partial") and not allow_partial:
        raise PartialRun(f"{directory}: the run is unfinished: {len(results)} of {header.get('cases')} planned "
                         "case(s) finished; finish it with `worldloom evalrun run ... --resume` into this directory")
    if note is not None:
        warnings.warn(note, LedgerWarning, stacklevel=2)
    return RunReport(agent=str(header["agent"]), principal=str(header.get("principal", "agent")),
                     case_set=str(header["case_set"]), results=tuple(results),
                     agent_pack=header.get("agent_pack"), grader=header.get("grader"),
                     agent_identity=header.get("agent_identity"), split=header.get("split"))


def _mismatches(header: Mapping[str, Any], identity: RunReport) -> list[str]:
    wanted = _header(identity, 0)
    return [f"{key} (ledger {header.get(key)!r}, this run {wanted.get(key)!r})"
            for key in IDENTITY_FIELDS if header.get(key) != wanted.get(key)]


def resume_ledger(directory: Path, identity: RunReport, *, shard: Mapping[str, Any] | None = None) -> tuple[list[CaseResult], str | None]:
    """The results an interrupted run already graded, after proving it is this run.

    Refuses, naming each field, when ``run.json`` records a different agent,
    principal, case set, agent pack or grader, or a different shard; refuses
    a ledger without a ``run.json`` to prove it against, and one that grades
    a case twice. A torn final line is dropped (and the note returned), and
    ``results.jsonl`` is rewritten without it so the appends that follow
    start on a line of their own. An empty directory resumes from nothing.
    """

    ledger = directory / "results.jsonl"
    header_path = directory / "run.json"
    if not header_path.exists():
        if ledger.exists() and ledger.stat().st_size:
            raise ValueError(f"{directory}: results.jsonl has no run.json to match against; run again without --resume")
        return [], None
    header = _read_header(directory)
    mismatched = _mismatches(header, identity)
    recorded_shard = read_shard(directory)
    if (recorded_shard is None) != (shard is None) or (shard is not None and recorded_shard != dict(shard)):
        mismatched.append("shard (ledger "
                          f"{_shard_label(recorded_shard)}, this run {_shard_label(shard)})")
    if mismatched:
        raise ValueError(f"{directory}: cannot resume a different run: " + "; ".join(mismatched))
    if not ledger.exists():
        return [], None
    results, note = repair_ledger(ledger)
    seen: set[str] = set()
    for result in results:
        if result.case_id in seen:
            raise ValueError(f"{ledger}: case {result.case_id} is graded twice; the ledger is not one run")
        seen.add(result.case_id)
    return results, note


def repair_ledger(path: Path) -> tuple[list[CaseResult], str | None]:
    """`read_results`, then drop a torn final line from the file itself.

    Appending after a torn line would glue the next result onto it and turn
    a crash's harmless tail into corruption in the middle. The file is
    rewritten (atomically, synced) only when there was something to drop.
    """

    results, note = read_results(path)
    # An unterminated last line that parsed is kept, but still rewritten, so
    # the next append starts a line of its own.
    if note is not None or path.read_bytes()[-1:] not in (b"", b"\n"):
        _replace(path, (_result_line(result) for result in results))
    return results, note


# -- shards -------------------------------------------------------------------


SHARD_SCHEMA = "worldloom.eval-run-shard/v1"


def shard_of(case_id: str, count: int) -> int:
    """The shard (0-based) a case belongs to among *count*: a stable hash of its id.

    By id, never by position, so a case keeps its shard when the set is
    filtered or reordered, and every machine computes the same partition.
    """
    return int(content_key("evalrun-shard", case_id), 16) % count


def shard_document(index: int, count: int, cases: Sequence[EvalCase]) -> dict[str, Any]:
    """``shard.json`` for shard *index* (1-based) of *count* over the whole ordered case set."""
    return {"schema": SHARD_SCHEMA, "index": index, "count": count,
            "case_set": case_set_digest(cases), "order": [case.id for case in cases]}


def write_shard(directory: Path, document: Mapping[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _replace_json(directory / "shard.json", document)


def read_shard(directory: Path) -> dict[str, Any] | None:
    path = directory / "shard.json"
    if not path.exists():
        return None
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != SHARD_SCHEMA:
        raise ValueError(f"{path}: not an eval-run shard ({document.get('schema')!r})")
    return document


def _shard_label(document: Mapping[str, Any] | None) -> str:
    if document is None:
        return "unsharded"
    return f"{document.get('index')}/{document.get('count')} of {str(document.get('case_set'))[:12]}"


def merge_shards(directories: Sequence[Path]) -> RunReport:
    """One run from the shard directories of one sharded run, in case order.

    Refuses shards that are not one run (a different agent, principal, agent
    pack, grader, whole case set or shard count), a shard given twice, a case
    graded by two shards or in the wrong one, an unfinished shard, and a
    missing shard. What it returns is what a single process would have
    written, so ``write_run`` of it is byte-identical to that run's ledger.
    """

    if not directories:
        raise ValueError("merge needs at least one shard directory")
    loaded: list[tuple[Path, dict[str, Any], dict[str, Any], RunReport]] = []
    for directory in directories:
        shard = read_shard(directory)
        if shard is None:
            raise ValueError(f"{directory}: no shard.json; write shards with `evalrun run --shard i/n`")
        header = _read_header(directory)
        if header.get("partial"):
            raise ValueError(f"{directory}: shard {shard['index']}/{shard['count']} did not finish; "
                             "finish it with `evalrun run --shard ... --resume`")
        loaded.append((directory, shard, header, read_run(directory)))
    first_dir, first_shard, first_header, first = loaded[0]
    for directory, shard, header, _report in loaded[1:]:
        differs = [key for key in ("agent", "principal", "agent_pack", "grader", "agent_identity", "split") if header.get(key) != first_header.get(key)]
        differs += [key for key in ("count", "case_set", "order") if shard.get(key) != first_shard.get(key)]
        if differs:
            raise ValueError(f"{directory}: not a shard of the same run as {first_dir}: differs in "
                             + ", ".join(differs))
    count = int(first_shard["count"])
    order = [str(case_id) for case_id in first_shard["order"]]
    by_index: dict[int, Path] = {}
    owner: dict[str, Path] = {}
    results: dict[str, CaseResult] = {}
    for directory, shard, _header_doc, report in loaded:
        index = int(shard["index"])
        if index in by_index:
            raise ValueError(f"shard {index}/{count} given twice: {by_index[index]} and {directory}")
        by_index[index] = directory
        for result in report.results:
            if result.case_id in owner:
                where = (f"twice in {directory}" if owner[result.case_id] == directory
                         else f"in two shards: {owner[result.case_id]} and {directory}")
                raise ValueError(f"case {result.case_id} is graded {where}")
            if shard_of(result.case_id, count) != index - 1:
                raise ValueError(f"{directory}: case {result.case_id} does not belong to shard {index}/{count}")
            owner[result.case_id] = directory
            results[result.case_id] = result
    missing_shards = sorted(set(range(1, count + 1)) - set(by_index))
    if missing_shards:
        raise ValueError(f"missing shard(s) {', '.join(f'{index}/{count}' for index in missing_shards)}")
    missing = [case_id for case_id in order if case_id not in results]
    if missing:
        raise ValueError(f"{len(missing)} case(s) graded by no shard (first {missing[0]}); resume the shard that owns it")
    unknown = sorted(set(results) - set(order))
    if unknown:
        raise ValueError(f"{len(unknown)} result(s) for cases outside the case set (first {unknown[0]})")
    return RunReport(agent=first.agent, principal=first.principal, case_set=str(first_shard["case_set"]),
                     results=tuple(results[case_id] for case_id in order),
                     agent_pack=first.agent_pack, grader=first.grader, agent_identity=first.agent_identity,
                     split=first.split)


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
    #: True when both runs name their grader and the digests differ. Then no
    #: case is called an improvement or a regression (each graded case is
    #: ``incomparable``): the two numbers were not measured the same way.
    grader_mismatch: bool = False
    notes: tuple[str, ...] = ()

    model_config = ConfigDict(populate_by_name=True)


def _grader_digest(report: RunReport) -> str | None:
    grader = report.grader
    if not isinstance(grader, Mapping):
        return None
    value = grader.get("digest")
    return str(value) if value else None


def compare(baseline: RunReport, recent: RunReport) -> Comparison:
    """Per-case deltas by case id, within the `delta_band` (Eval Studio's ±0.10), plus what it lacks."""

    band = delta_band()
    # Two runs that each name their grader, differently, were measured with
    # different sticks: their deltas are reported, never judged. A run that
    # names none (every run written before graders were recorded) compares
    # exactly as it always did.
    left_grader, right_grader = _grader_digest(baseline), _grader_digest(recent)
    mismatch = left_grader is not None and right_grader is not None and left_grader != right_grader

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
        if mismatch:
            verdict = "incomparable"
        elif delta > band:
            verdict = "improvement"
            improvements.append(case_id)
        elif delta < -band:
            verdict = "regression"
            regressions.append(case_id)
        else:
            verdict = "stable"
            stable += 1
        deltas.append(CaseDelta(case_id=case_id, baseline=a.score.score, recent=b.score.score, delta=delta,
                                axes={axis: value for axis, value in axes.items() if abs(value) > band},
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
        grader_mismatch=mismatch,
        notes=(f"the runs were graded differently (grader {left_grader} vs {right_grader}); deltas are"
               " reported but no case is judged an improvement or a regression",) if mismatch else (),
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

    A row whose query matches no case is not a result, but it is not
    nothing either: the count is recorded on the report as
    ``agent_identity["unmatched_rows"]`` (beside ``rows``, the CSV's row
    count), so ``agreement`` can report it instead of shrinking the set
    silently. An import where every row matched carries no identity, so its
    bytes are the ones it always had.
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
    unmatched = 0
    for row in rows:
        query = (row.get("query") or "").strip()
        case = by_query.get(query)
        if case is None:
            unmatched += 1
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
    identity = {"source": "eval-studio-csv", "rows": len(rows), "unmatched_rows": unmatched} if unmatched else None
    return RunReport(agent=agent, principal="eval-studio", case_set=case_set_digest(listed), results=tuple(results),
                     agent_identity=identity)


__all__ = [
    "IDENTITY_FIELDS",
    "SHARD_SCHEMA",
    "STUDIO_COLUMNS",
    "AxisMeans",
    "CaseDelta",
    "Comparison",
    "LedgerWarning",
    "RunSlice",
    "PartialRun",
    "RunSummary",
    "append_result",
    "begin_ledger",
    "compare",
    "delta_band",
    "import_served",
    "import_studio_results",
    "merge_shards",
    "read_results",
    "read_run",
    "read_shard",
    "repair_ledger",
    "resume_ledger",
    "shard_document",
    "shard_of",
    "summarize",
    "to_studio_rows",
    "write_run",
    "write_shard",
    "write_studio_csv",
]
