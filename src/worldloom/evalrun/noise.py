"""How much of a score is the agent, and how much is the draw: repeats, a paired test and the noise floor.

An agent under test is stochastic. Run the same policy over the same cases
twice and the scores differ, so one champion run against one candidate run
can promote a policy that was lucky and reject one that was not. This module
is the arithmetic the improve loop's gates use when each side is run more
than once, and the report an operator reads before paying for an experiment.

**Per-case means.** Each side's repeats are reduced case by case to a mean
score over the repeats that graded the case. A comparison is then paired:
the per-case differences (candidate mean minus champion mean) are the
sample, so a hard case and an easy one are each compared with themselves.

**The interval.** The mean of those differences gets a percentile interval
from a paired bootstrap: the cases are resampled with replacement a fixed
number of times (policy ``evalrun.improve.bootstrap_resamples``) and the mean
recomputed each time. The resampling stream is a ``worldloom.rng.Rng``
seeded from the case-set digest and the two policies' digests, so the same
two sets of runs give the same interval on every machine. The Student t
interval is reported beside it for reference. With values at stake, the
weighted mean is resampled the same way with each case keeping its weight.

**The noise floor.** Within one policy, the spread of a case's scores across
repeats is pure noise: nothing about the policy changed. Pooled over cases
(the square root of the summed squared deviations over the summed degrees of
freedom) it is the run-to-run standard deviation, and from it the smallest
effect a comparison of *n* cases at *k* repeats a side can detect at a given
confidence and power: ``(z(1 - a/2) + z(power)) * sqrt(2 * s^2 / (k * n))``.
That is a floor. Cases differ in how much a change helps them, and that
spread only widens the interval; ``evalrun noise`` over a few runs of the
champion says whether an experiment is worth paying for before it is paid.

Pure Python, and deterministic: no clock, no unseeded draw, no numpy.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ConfigDict, Field

from .. import packkit
from ..ids import content_key
from ..models import Model
from ..rng import Rng
from .results import delta_band
from .runner import CaseResult, RunReport

NOISE_SCHEMA = "worldloom.eval-noise/v1"
PAIRED_SCHEMA = "worldloom.eval-paired/v1"
AXES: tuple[str, ...] = ("plan", "trajectory", "outcomes")
#: The repeat counts a noise report sizes an experiment for.
SIZING_REPEATS: tuple[int, ...] = (1, 2, 3, 5, 10)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def confidence_level(confidence: float | None = None) -> float:
    """*confidence*, or the policy ``evalrun.improve.confidence``; refused outside (0, 1)."""
    level = float(packkit.policy("evalrun.improve.confidence")) if confidence is None else float(confidence)
    if not 0 < level < 1:
        raise ValueError(f"confidence must lie strictly between 0 and 1, not {level}")
    return level


def resample_count(resamples: int | None = None) -> int:
    """*resamples*, or the policy ``evalrun.improve.bootstrap_resamples``; at least 100."""
    count = int(packkit.policy("evalrun.improve.bootstrap_resamples")) if resamples is None else int(resamples)
    if count < 100:
        raise ValueError(f"a bootstrap needs at least 100 resamples, not {count}")
    return count


# -- distributions ------------------------------------------------------------------


def _beta_fraction(a: float, b: float, x: float) -> float:
    """The continued fraction of the regularized incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        step = d * c
        h *= step
        if abs(step - 1.0) < 1e-15:
            break
    return h


def _incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_fraction(a, b, x) / a
    return 1.0 - front * _beta_fraction(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    """Student's t distribution function with *df* degrees of freedom."""
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    tail = 0.5 * _incomplete_beta(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t >= 0 else tail


def t_quantile(p: float, df: float) -> float:
    """The *p* quantile of Student's t with *df* degrees of freedom, by bisection on ``t_cdf``."""
    if not 0 < p < 1:
        raise ValueError("p must lie strictly between 0 and 1")
    if p < 0.5:
        return -t_quantile(1.0 - p, df)
    low, high = 0.0, 1.0
    while t_cdf(high, df) < p:
        high *= 2.0
    for _ in range(200):
        middle = (low + high) / 2.0
        if t_cdf(middle, df) < p:
            low = middle
        else:
            high = middle
        if high - low < 1e-12:
            break
    return (low + high) / 2.0


def z_quantile(p: float) -> float:
    """The *p* quantile of the standard normal."""
    return statistics.NormalDist().inv_cdf(p)


def _quantile(ordered: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics (the usual definition, type 7)."""
    position = (len(ordered) - 1) * q
    below = math.floor(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (position - below) * (ordered[above] - ordered[below])


# -- one sample of differences ------------------------------------------------------


class Interval(Model):
    """The mean of a sample of paired differences, and how sure it is."""

    cases: int
    mean: float
    #: The standard error of the mean; ``None`` below two cases.
    stderr: float | None = None
    #: The paired bootstrap's percentile interval at ``confidence``.
    ci_low: float | None = None
    ci_high: float | None = None
    #: The Student t interval at the same confidence, for reference.
    t_low: float | None = None
    t_high: float | None = None


def interval(differences: Sequence[float], *, confidence: float, resamples: int, seed: str,
             weights: Sequence[float] | None = None) -> Interval:
    """The mean of *differences* with its paired-bootstrap and t intervals.

    With *weights*, the mean is weighted and each resample keeps every drawn
    case's weight. The bootstrap is seeded by *seed* alone, so it is a pure
    function of its arguments.
    """
    n = len(differences)
    resamples = resample_count(resamples)
    if weights is not None and len(weights) != n:
        raise ValueError("weights and differences must be the same length")
    if n == 0:
        raise ValueError("no differences to take the mean of")
    w = [1.0] * n if weights is None else [float(item) for item in weights]
    total = sum(w)
    if total <= 0:
        raise ValueError("the weights sum to nothing")
    mean = sum(wi * di for wi, di in zip(w, differences, strict=True)) / total
    if n < 2:
        return Interval(cases=n, mean=round(mean, 6))
    if weights is None:
        variance = sum((di - mean) ** 2 for di in differences) / (n - 1)
        stderr = math.sqrt(variance / n)
    else:
        # The weighted mean's standard error (a ratio estimator's, with the
        # small-sample factor n / (n - 1)).
        spread = sum((wi * (di - mean)) ** 2 for wi, di in zip(w, differences, strict=True))
        stderr = math.sqrt(spread * n / (n - 1)) / total
    alpha = 1.0 - confidence
    margin = t_quantile(1.0 - alpha / 2.0, n - 1) * stderr
    stream = Rng(int(content_key("paired-bootstrap", seed), 16), "evalrun.noise")
    means: list[float] = []
    for _ in range(resamples):
        drawn_total = drawn = 0.0
        for _ in range(n):
            index = stream.integer(0, n - 1)
            drawn_total += w[index]
            drawn += w[index] * differences[index]
        means.append(drawn / drawn_total)
    means.sort()
    return Interval(cases=n, mean=round(mean, 6), stderr=_round(stderr),
                    ci_low=_round(_quantile(means, alpha / 2.0)), ci_high=_round(_quantile(means, 1.0 - alpha / 2.0)),
                    t_low=_round(mean - margin), t_high=_round(mean + margin))


# -- per-case means over repeats ----------------------------------------------------


def _scores(row: CaseResult, axis: str | None) -> float | None:
    if not row.graded or row.score is None:
        return None
    if axis is None:
        return float(row.score.score)
    if axis not in row.score.observed:
        return None
    return float(getattr(row.score, axis).score)


def _by_case(runs: Sequence[RunReport]) -> dict[str, list[CaseResult]]:
    rows: dict[str, list[CaseResult]] = {}
    for report in runs:
        for row in report.results:
            rows.setdefault(row.case_id, []).append(row)
    return rows


def _values(rows: Sequence[CaseResult], axis: str | None) -> list[float]:
    return [value for value in (_scores(row, axis) for row in rows) if value is not None]


def _pooled(groups: Sequence[Sequence[float]]) -> float | None:
    """The pooled within-group standard deviation over every group of two or more."""
    squares = 0.0
    freedom = 0
    for group in groups:
        if len(group) < 2:
            continue
        mean = sum(group) / len(group)
        squares += sum((value - mean) ** 2 for value in group)
        freedom += len(group) - 1
    return math.sqrt(squares / freedom) if freedom else None


def noise_floor(runs: Sequence[RunReport], axis: str | None = None) -> float | None:
    """The pooled run-to-run standard deviation of one policy's case scores; ``None`` below two repeats."""
    grouped = _by_case(runs)
    return _round(_pooled([_values(grouped[case_id], axis) for case_id in sorted(grouped)]))


def minimum_detectable_effect(std: float | None, *, cases: int, repeats: int, confidence: float,
                              power: float) -> float | None:
    """The smallest true mean difference a paired comparison of *cases* at *repeats* a side detects.

    ``(z(1 - a/2) + z(power)) * sqrt(2 * std^2 / (repeats * cases))``: the
    noise alone, so a floor. ``None`` without a noise estimate.
    """
    if std is None or cases < 1 or repeats < 1:
        return None
    if not 0 < power < 1:
        raise ValueError(f"power must lie strictly between 0 and 1, not {power}")
    alpha = 1.0 - confidence
    spread = math.sqrt(2.0 * std * std / (repeats * cases))
    return _round((z_quantile(1.0 - alpha / 2.0) + z_quantile(power)) * spread)


# -- the noise report ---------------------------------------------------------------


class CaseNoise(Model):
    case_id: str
    #: Repeats that graded the case, and those that errored on it.
    graded: int
    errored: int
    mean: float | None
    #: The sample standard deviation across repeats; ``None`` below two graded repeats.
    std: float | None


class NoiseReport(Model):
    """k runs of one policy: how much its scores move when nothing about it changes."""

    schema_version: str = Field(default=NOISE_SCHEMA, alias="schema")
    agent: str
    agent_pack: str | None = None
    case_set: str
    runs: int
    cases: int
    #: Cases graded in at least two runs: the ones the noise is measured on.
    repeated_cases: int
    #: The pooled run-to-run standard deviation of the overall score, and per axis.
    pooled_std: float | None
    axis_std: dict[str, float | None]
    confidence: float
    power: float
    #: The experiment the effect below is sized for: this many cases, this many repeats a side.
    sized_cases: int
    sized_repeats: int
    minimum_detectable_effect: float | None
    #: The same, for the usual repeat counts over ``sized_cases``.
    by_repeats: dict[str, float | None]
    delta_band: float
    per_case: tuple[CaseNoise, ...]
    notes: tuple[str, ...] = ()

    model_config = ConfigDict(populate_by_name=True)


def _pack_digest(report: RunReport) -> str | None:
    pack = report.agent_pack
    if isinstance(pack, Mapping) and pack.get("digest"):
        return str(pack["digest"])
    return None


def _grader_digest(report: RunReport) -> str | None:
    grader = report.grader
    if isinstance(grader, Mapping) and grader.get("digest"):
        return str(grader["digest"])
    return None


def noise(run_reports: Sequence[RunReport], *, confidence: float | None = None, power: float | None = None,
          cases: int | None = None, repeats: int | None = None) -> NoiseReport:
    """How much *run_reports*, k runs of one policy over one case set, disagree with each other.

    The minimum detectable effect is sized for *cases* cases (default: the
    cases the runs graded) at *repeats* repeats a side (default: the number of
    runs given). Refuses runs of different case sets, policies or graders:
    their differences would not be noise.
    """
    reports = list(run_reports)
    if not reports:
        raise ValueError("no runs: noise is measured over two or more runs of one policy")
    first = reports[0]
    for other in reports[1:]:
        if other.case_set != first.case_set:
            raise ValueError("the runs are over different case sets")
        if _pack_digest(other) != _pack_digest(first) or other.agent != first.agent:
            raise ValueError("the runs are of different agents or policies; their differences are not noise")
        if _grader_digest(other) != _grader_digest(first):
            raise ValueError("the runs were graded differently; their differences are not noise")
    level = confidence_level(confidence)
    chance = float(packkit.policy("evalrun.improve.power")) if power is None else float(power)
    grouped = _by_case(reports)
    per_case: list[CaseNoise] = []
    groups: list[list[float]] = []
    for case_id in sorted(grouped):
        rows = grouped[case_id]
        values = _values(rows, None)
        groups.append(values)
        per_case.append(CaseNoise(case_id=case_id, graded=len(values), errored=len(rows) - len(values),
                                  mean=_round(sum(values) / len(values)) if values else None,
                                  std=_round(statistics.stdev(values)) if len(values) >= 2 else None))
    pooled = _round(_pooled(groups))
    graded_cases = sum(1 for item in per_case if item.graded)
    n = graded_cases if cases is None else cases
    k = len(reports) if repeats is None else repeats
    if n < 1 or k < 1:
        raise ValueError("an experiment is sized for at least one case and one repeat")
    notes: list[str] = []
    if len(reports) < 2:
        notes.append("one run measures no noise: give two or more runs of the same policy")
    elif pooled is None:
        notes.append("no case was graded in two runs, so no run-to-run spread could be measured")
    return NoiseReport(
        agent=first.agent, agent_pack=_pack_digest(first), case_set=first.case_set, runs=len(reports),
        cases=graded_cases, repeated_cases=sum(1 for group in groups if len(group) >= 2), pooled_std=pooled,
        axis_std={axis: noise_floor(reports, axis) for axis in AXES}, confidence=level, power=chance,
        sized_cases=n, sized_repeats=k,
        minimum_detectable_effect=minimum_detectable_effect(pooled, cases=n, repeats=k, confidence=level, power=chance),
        by_repeats={str(count): minimum_detectable_effect(pooled, cases=n, repeats=count, confidence=level,
                                                          power=chance) for count in SIZING_REPEATS},
        delta_band=delta_band(), per_case=tuple(per_case), notes=tuple(notes))


def render_noise(report: NoiseReport, *, top: int = 5) -> str:
    """The report as a few lines an operator reads."""
    lines = [f"{report.agent}: {report.runs} run(s) over {report.cases} graded case(s)"
             f" ({report.repeated_cases} graded more than once)"]
    if report.pooled_std is None:
        lines.append("run-to-run std: not measurable")
    else:
        axes = ", ".join(f"{axis} {'n/a' if value is None else value}" for axis, value in report.axis_std.items())
        lines.append(f"run-to-run std (pooled): {report.pooled_std} ({axes})")
        lines.append(f"minimum detectable effect at {report.confidence:g} confidence, {report.power:g} power, "
                     f"{report.sized_cases} case(s) x {report.sized_repeats} repeat(s): "
                     f"{report.minimum_detectable_effect} (delta band {report.delta_band})")
        lines.append("by repeats: " + ", ".join(f"k={key} {value}" for key, value in report.by_repeats.items()))
    noisy = sorted((item for item in report.per_case if item.std), key=lambda item: (-(item.std or 0.0), item.case_id))
    for item in noisy[:top]:
        lines.append(f"  {item.case_id}: mean {item.mean}, std {item.std} over {item.graded} graded")
    lines.extend(f"note: {note}" for note in report.notes)
    return "\n".join(lines) + "\n"


# -- a paired comparison of two policies over repeats -------------------------------


class PairedComparison(Model):
    """Champion runs against candidate runs, case by case over per-case means."""

    schema_version: str = Field(default=PAIRED_SCHEMA, alias="schema")
    baseline_repeats: int
    recent_repeats: int
    same_case_set: bool
    grader_mismatch: bool
    #: Case ids every run on both sides holds.
    compared: int
    confidence: float
    resamples: int
    method: str = "bootstrap"
    #: What the bootstrap was seeded from (case set and the two policies' digests).
    seed: str
    #: The overall score's paired difference; ``None`` when no case was graded on both sides.
    overall: Interval | None
    axes: dict[str, Interval | None]
    #: The value-weighted difference, when values were given.
    value: Interval | None = None
    #: Each paired case's difference of means (candidate minus champion).
    case_deltas: dict[str, float]
    #: Cases whose difference of means lies outside the delta band.
    improvements: tuple[str, ...]
    regressions: tuple[str, ...]
    #: Errored in a majority of the candidate's repeats and in none of the champion's.
    newly_errored: tuple[str, ...]
    noise_floor_baseline: float | None
    noise_floor_recent: float | None

    model_config = ConfigDict(populate_by_name=True)


def _weights(values: Mapping[str, Any]) -> dict[str, float]:
    from .value import CaseValue

    return {key: float(value.weight if isinstance(value, CaseValue) else value) for key, value in values.items()}


def paired(baseline: Sequence[RunReport], recent: Sequence[RunReport], *, values: Mapping[str, Any] | None = None,
           confidence: float | None = None, resamples: int | None = None, seed: str | None = None) -> PairedComparison:
    """*recent* against *baseline*, each a set of repeats of one policy, as a paired test over per-case means.

    A case is compared when both sides graded it at least once; its overall
    difference is the difference of its mean scores (or, when the two sides
    observed different axes, the mean of the axis differences they share,
    as ``results.compare`` does). The bootstrap's seed is *seed* or the case
    set and the two policies' digests.
    """
    if not baseline or not recent:
        raise ValueError("a paired comparison needs at least one run on each side")
    level = confidence_level(confidence)
    count = resample_count(resamples)
    everything = [*baseline, *recent]
    graders = {_grader_digest(report) for report in everything} - {None}
    case_sets = {report.case_set for report in everything}
    left, right = _by_case(baseline), _by_case(recent)
    shared = sorted(case_id for case_id in left if case_id in right
                    and len(left[case_id]) == len(baseline) and len(right[case_id]) == len(recent))
    key = seed if seed is not None else "\0".join(
        (baseline[0].case_set, _pack_digest(baseline[0]) or baseline[0].agent,
         _pack_digest(recent[0]) or recent[0].agent))
    band = delta_band()
    overall: dict[str, float] = {}
    axis_deltas: dict[str, dict[str, float]] = {axis: {} for axis in AXES}
    newly_errored: list[str] = []
    for case_id in shared:
        a_rows, b_rows = left[case_id], right[case_id]
        a_errors = sum(1 for row in a_rows if not row.graded)
        b_errors = sum(1 for row in b_rows if not row.graded)
        if a_errors == 0 and b_errors * 2 > len(b_rows):
            newly_errored.append(case_id)
        for axis in AXES:
            a_values, b_values = _values(a_rows, axis), _values(b_rows, axis)
            if a_values and b_values:
                axis_deltas[axis][case_id] = sum(b_values) / len(b_values) - sum(a_values) / len(a_values)
        a_all, b_all = _values(a_rows, None), _values(b_rows, None)
        if not (a_all and b_all):
            continue
        a_axes = {axis for row in a_rows if row.graded and row.score is not None for axis in row.score.observed}
        b_axes = {axis for row in b_rows if row.graded and row.score is not None for axis in row.score.observed}
        if a_axes == b_axes:
            overall[case_id] = sum(b_all) / len(b_all) - sum(a_all) / len(a_all)
        else:
            common = [axis_deltas[axis][case_id] for axis in AXES if case_id in axis_deltas[axis]]
            if common:
                overall[case_id] = sum(common) / len(common)

    def estimate(deltas: Mapping[str, float], label: str, weights: Mapping[str, float] | None = None) -> Interval | None:
        ids = sorted(deltas)
        if not ids:
            return None
        return interval([deltas[case_id] for case_id in ids], confidence=level, resamples=count,
                        seed=f"{key}\0{label}",
                        weights=None if weights is None else [weights.get(case_id, 1.0) for case_id in ids])

    value = None
    if values is not None and len(graders) <= 1:
        value = estimate(overall, "value", _weights(values))
    rounded = {case_id: round(delta, 6) for case_id, delta in sorted(overall.items())}
    return PairedComparison(
        baseline_repeats=len(baseline), recent_repeats=len(recent), same_case_set=len(case_sets) == 1,
        grader_mismatch=len(graders) > 1, compared=len(shared), confidence=level, resamples=count,
        seed=content_key("paired-bootstrap", key), overall=estimate(overall, "overall"),
        axes={axis: estimate(axis_deltas[axis], axis) for axis in AXES}, value=value, case_deltas=rounded,
        improvements=tuple(case_id for case_id, delta in rounded.items() if delta > band),
        regressions=tuple(case_id for case_id, delta in rounded.items() if delta < -band),
        newly_errored=tuple(newly_errored),
        noise_floor_baseline=noise_floor(baseline), noise_floor_recent=noise_floor(recent))


__all__ = ["AXES", "NOISE_SCHEMA", "PAIRED_SCHEMA", "CaseNoise", "Interval", "NoiseReport", "PairedComparison",
           "confidence_level", "interval", "minimum_detectable_effect", "noise", "noise_floor", "paired",
           "render_noise", "resample_count", "t_cdf", "t_quantile", "z_quantile"]
