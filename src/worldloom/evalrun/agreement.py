"""Does the local grader agree with Gemini Enterprise Eval Studio's?

A local run and an Eval Studio run can only be compared on the answer axis:
Eval Studio sees a query, a fetched answer and a golden, and never a tool
call. Even there, ``results.compare`` over an imported Studio run and a local
run compares the local *blended* outcome score (state diff, grounding and
answer together) against Studio's answer score, which is not the same
quantity. And two different answers graded by two different raters confound
two things: whether the agents differ, and whether the graders do.

``agreement`` separates them. It takes the answers Eval Studio itself graded
(the ``fetched`` column of its results CSV, imported by
``results.import_studio_results``) and rates *the same text* with the local
rater. Whatever differs is the raters, nothing else. The statistics are the
ones a reader of an inter-rater study expects: mean absolute error on the
0..1 scale, Pearson and Spearman correlation (Spearman with average ranks for
ties, since rater scores tie constantly), the share of cases within the
comparison band, and Cohen's kappa of the pass/fail call at the pass mark,
with its confusion counts. Every statistic that is undefined on the data
(fewer than two pairs, a side with no variance, raters that each put every
case in one class) is ``None`` with the reason, never a number that looks
like a measurement.

Exclusions are counted, not hidden: a Studio row with a ``scoreError`` (or an
``Error:`` answer), a case the local rater could not rate, and, separately, a
case whose shape the local rater abstains on by design (``rater.JUDGE_ONLY``
under the grounded rater): those have a Studio score and no local one, and
are reported as their own bucket so the reader sees how much of the set the
local grader cannot vouch for.

Statistics are computed here in plain Python. They are small, and a grader
audit should not need a numerical stack to be reproduced.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import ConfigDict, Field

from .. import packkit
from ..models import Model
from ..providers import digest
from .contract import EvalCase
from .grader import grader_identity
from .rater import JUDGE_ONLY, Rater
from .runner import RunReport

AGREEMENT_SCHEMA = "worldloom.evalrun-agreement/v1"

_WORST = 10


# -- statistics ---------------------------------------------------------------


def _round(value: float) -> float:
    return round(value, 4)


def mean_absolute_error(left: Sequence[float], right: Sequence[float]) -> float | None:
    if not left:
        return None
    return _round(sum(abs(a - b) for a, b in zip(left, right, strict=True)) / len(left))


def pearson(left: Sequence[float], right: Sequence[float]) -> tuple[float | None, str | None]:
    """Pearson's r, or ``(None, reason)`` when it is undefined (n < 2, a constant side)."""

    n = len(left)
    if n < 2:
        return None, "fewer than two rated pairs"
    mean_left, mean_right = sum(left) / n, sum(right) / n
    dev_left = [a - mean_left for a in left]
    dev_right = [b - mean_right for b in right]
    var_left = sum(d * d for d in dev_left)
    var_right = sum(d * d for d in dev_right)
    if var_left <= 1e-12 and var_right <= 1e-12:
        return None, "both series give every case the same score"
    if var_left <= 1e-12:
        return None, "the first series gave every case the same score"
    if var_right <= 1e-12:
        return None, "the second series gave every case the same score"
    covariance = sum(a * b for a, b in zip(dev_left, dev_right, strict=True))
    value = covariance / math.sqrt(var_left * var_right)
    return _round(max(-1.0, min(1.0, value))), None


def average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks with ties sharing the mean of the ranks they span (``[1, 2, 2, 3]`` -> ``[1, 2.5, 2.5, 4]``)."""

    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        shared = (start + end) / 2 + 1
        for position in range(start, end + 1):
            ranks[order[position]] = shared
        start = end + 1
    return ranks


def spearman(left: Sequence[float], right: Sequence[float]) -> tuple[float | None, str | None]:
    """Spearman's rho as Pearson over average ranks, which is the tie-correct form."""

    return pearson(average_ranks(left), average_ranks(right))


def cohen_kappa(left: Sequence[bool], right: Sequence[bool]) -> tuple[float | None, str | None]:
    """Cohen's kappa for two binary raters, or ``(None, reason)`` when chance agreement is total."""

    n = len(left)
    if n == 0:
        return None, "no rated pairs"
    observed = sum(1 for a, b in zip(left, right, strict=True) if a == b) / n
    left_pass, right_pass = sum(left) / n, sum(right) / n
    expected = left_pass * right_pass + (1 - left_pass) * (1 - right_pass)
    if expected >= 1 - 1e-12:
        return None, "both sides put every case in the same class; kappa is undefined"
    return _round((observed - expected) / (1 - expected)), None


# -- report -------------------------------------------------------------------


class AgreementCase(Model):
    case_id: str
    query: str
    rubric: str
    studio: float
    local: float
    #: ``local - studio``: positive when the local grader is the more lenient.
    difference: float
    studio_pass: bool
    local_pass: bool


class Confusion(Model):
    both_pass: int
    both_fail: int
    studio_pass_local_fail: int
    studio_fail_local_pass: int


class AgreementStats(Model):
    n: int
    studio_mean: float | None
    local_mean: float | None
    mae: float | None
    pearson: float | None
    spearman: float | None
    within_band: float | None
    kappa: float | None
    confusion: Confusion
    #: Why a statistic above is ``None``, keyed by its name.
    undefined: dict[str, str] = Field(default_factory=dict)


class AgreementSlice(Model):
    key: str
    stats: AgreementStats


class Abstained(Model):
    """Cases the local rater declines by design: a Studio score stands, and nothing to agree with."""

    cases: int
    studio_mean: float | None
    by_shape: dict[str, int]
    case_ids: tuple[str, ...]


class Excluded(Model):
    #: Studio rows carrying a ``scoreError`` or an ``Error:`` answer.
    studio_errors: int
    #: Rows the local rater could not rate (outside ``JUDGE_ONLY``), by message.
    local_errors: int
    local_error_messages: dict[str, int]
    #: Studio rows whose case is not in the case set given.
    unknown_cases: int
    #: Cases with no answer contract, so no golden to rate against.
    no_answer_contract: int


class Thresholds(Model):
    min_kappa: float
    max_mae: float
    min_cases: int


class AgreementReport(Model):
    schema_version: str = Field(default=AGREEMENT_SCHEMA, alias="schema")
    case_set: str
    studio_rows: int
    #: The local grader, exactly as ``grader_identity`` names it.
    local: dict[str, Any]
    #: What is known of the Studio side: the run's label and, when supplied,
    #: the instruction the operator gave Eval Studio's auto-rater.
    studio: dict[str, Any]
    threshold: float
    band: float
    thresholds: Thresholds
    stats: AgreementStats
    by_shape: tuple[AgreementSlice, ...]
    abstained: Abstained
    excluded: Excluded
    worst: tuple[AgreementCase, ...]
    cases: tuple[AgreementCase, ...]
    #: ``agrees``, ``disagrees`` or ``insufficient``, with the reasons.
    verdict: str
    reasons: tuple[str, ...]

    model_config = ConfigDict(populate_by_name=True)


def _stats(rows: Sequence[AgreementCase], band: float) -> AgreementStats:
    studio = [row.studio for row in rows]
    local = [row.local for row in rows]
    undefined: dict[str, str] = {}
    r, why = pearson(studio, local)
    if why:
        undefined["pearson"] = why
    rho, why = spearman(studio, local)
    if why:
        undefined["spearman"] = why
    kappa, why = cohen_kappa([row.studio_pass for row in rows], [row.local_pass for row in rows])
    if why:
        undefined["kappa"] = why
    if not rows:
        undefined["mae"] = "no rated pairs"
    confusion = Confusion(
        both_pass=sum(1 for row in rows if row.studio_pass and row.local_pass),
        both_fail=sum(1 for row in rows if not row.studio_pass and not row.local_pass),
        studio_pass_local_fail=sum(1 for row in rows if row.studio_pass and not row.local_pass),
        studio_fail_local_pass=sum(1 for row in rows if not row.studio_pass and row.local_pass),
    )
    return AgreementStats(
        n=len(rows),
        studio_mean=_round(sum(studio) / len(studio)) if studio else None,
        local_mean=_round(sum(local) / len(local)) if local else None,
        mae=mean_absolute_error(studio, local),
        pearson=r, spearman=rho,
        # A float difference of exactly the band is inside it, as it is for
        # `compare`, whose stable verdict is |delta| <= band.
        within_band=_round(sum(1 for row in rows if abs(row.difference) <= band + 1e-9) / len(rows)) if rows else None,
        kappa=kappa, confusion=confusion, undefined=undefined,
    )


def thresholds() -> Thresholds:
    """The verdict's bars: policies ``evalrun.agreement.min_kappa``, ``.max_mae``, ``.min_cases``."""

    return Thresholds(min_kappa=float(packkit.policy("evalrun.agreement.min_kappa")),
                      max_mae=float(packkit.policy("evalrun.agreement.max_mae")),
                      min_cases=int(packkit.policy("evalrun.agreement.min_cases")))


def _verdict(stats: AgreementStats, bars: Thresholds) -> tuple[str, tuple[str, ...]]:
    if stats.n < bars.min_cases:
        return "insufficient", (f"{stats.n} rated pair(s); at least {bars.min_cases} are needed to call agreement",)
    failures: list[str] = []
    if stats.mae is not None and stats.mae > bars.max_mae:
        failures.append(f"mean absolute error {stats.mae} exceeds {bars.max_mae}")
    if stats.kappa is not None and stats.kappa < bars.min_kappa:
        failures.append(f"kappa {stats.kappa} is below {bars.min_kappa}")
    if failures:
        return "disagrees", tuple(failures)
    if stats.kappa is None:
        return "insufficient", (f"kappa is undefined: {stats.undefined.get('kappa', 'no pairs')}",)
    return "agrees", (f"kappa {stats.kappa} >= {bars.min_kappa} and mean absolute error {stats.mae} <= {bars.max_mae}",)


def _studio_score(result: Any) -> float | None:
    score = result.score
    if score is None:
        return None
    value = score.outcomes.answer_score
    return float(value) if value is not None else float(score.score)


def agreement(
    studio: RunReport,
    cases: Iterable[EvalCase],
    rater: Rater,
    *,
    threshold: float | None = None,
    band: float | None = None,
    instruction: str | None = None,
) -> AgreementReport:
    """Rate each Studio row's own answer locally and measure how far the two graders agree.

    ``studio`` is an Eval Studio results CSV imported by
    ``import_studio_results`` (already joined to cases by query text, where a
    duplicate text refused). It is joined to ``cases`` here by case id.
    ``threshold`` is the pass mark for kappa (default: the policy
    ``evalrun.answer_pass_score``, the mark local grading passes an answer
    at); ``band`` is the tolerance for ``within_band`` (default: the policy
    ``evalrun.delta_band``, the band ``compare`` calls a change stable
    inside). ``instruction`` is the auto-rater instruction the Studio run
    was configured with, when the operator knows it: it is recorded, not
    used, because only Eval Studio ran it.
    """

    from .results import delta_band

    pass_mark = float(packkit.policy("evalrun.answer_pass_score")) if threshold is None else float(threshold)
    tolerance = delta_band() if band is None else float(band)
    by_id = {case.id: case for case in cases}
    rows: list[AgreementCase] = []
    abstained: list[tuple[str, str, float]] = []
    studio_errors = unknown = no_contract = 0
    local_errors: dict[str, int] = defaultdict(int)
    for result in studio.results:
        case = by_id.get(result.case_id)
        if case is None:
            unknown += 1
            continue
        studio_value = _studio_score(result)
        if not result.graded or studio_value is None:
            studio_errors += 1
            continue
        contract = case.outcomes.answer
        if contract is None:
            no_contract += 1
            continue
        local_value, error = rater(case, result.answer)
        if local_value is None:
            if contract.rubric in JUDGE_ONLY:
                abstained.append((case.id, contract.rubric.value, studio_value))
            else:
                local_errors[(error or "no score").split(":")[0]] += 1
            continue
        studio_value = max(0.0, min(1.0, studio_value))
        local_value = max(0.0, min(1.0, float(local_value)))
        rows.append(AgreementCase(
            case_id=case.id, query=case.query, rubric=contract.rubric.value,
            studio=_round(studio_value), local=_round(local_value),
            difference=_round(local_value - studio_value),
            studio_pass=studio_value >= pass_mark, local_pass=local_value >= pass_mark,
        ))
    rows.sort(key=lambda row: row.case_id)
    by_shape: dict[str, list[AgreementCase]] = defaultdict(list)
    for row in rows:
        by_shape[row.rubric].append(row)
    stats = _stats(rows, tolerance)
    bars = thresholds()
    verdict, reasons = _verdict(stats, bars)
    worst = tuple(sorted(rows, key=lambda row: (-abs(row.difference), row.case_id))[:_WORST])
    abstained_shapes: dict[str, int] = defaultdict(int)
    for _, shape, _ in abstained:
        abstained_shapes[shape] += 1
    studio_side: dict[str, Any] = {"agent": studio.agent, "principal": studio.principal}
    if instruction is not None:
        studio_side["instruction"] = instruction
        studio_side["instruction_digest"] = digest(instruction)
    return AgreementReport(
        case_set=studio.case_set, studio_rows=len(studio.results),
        local=grader_identity(rater), studio=studio_side,
        threshold=pass_mark, band=tolerance, thresholds=bars, stats=stats,
        by_shape=tuple(AgreementSlice(key=key, stats=_stats(by_shape[key], tolerance)) for key in sorted(by_shape)),
        abstained=Abstained(
            cases=len(abstained),
            studio_mean=_round(sum(value for _, _, value in abstained) / len(abstained)) if abstained else None,
            by_shape=dict(sorted(abstained_shapes.items())),
            case_ids=tuple(sorted(case_id for case_id, _, _ in abstained)),
        ),
        excluded=Excluded(studio_errors=studio_errors, local_errors=sum(local_errors.values()),
                          local_error_messages=dict(sorted(local_errors.items())), unknown_cases=unknown,
                          no_answer_contract=no_contract),
        worst=worst, cases=tuple(rows), verdict=verdict, reasons=reasons,
    )


__all__ = [
    "AGREEMENT_SCHEMA",
    "Abstained",
    "AgreementCase",
    "AgreementReport",
    "AgreementSlice",
    "AgreementStats",
    "Confusion",
    "Excluded",
    "Thresholds",
    "agreement",
    "average_ranks",
    "cohen_kappa",
    "mean_absolute_error",
    "pearson",
    "spearman",
    "thresholds",
]
