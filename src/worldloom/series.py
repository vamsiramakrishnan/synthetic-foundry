"""Time series: the shape behind a run of monthly figures, generated and read back.

A twelve-period corpus is the shape this tool is most often asked for and the
one whose numbers say the least. ``generators/finance.py`` applies a
hand-tabulated twelve-value ``SEASONALITY`` profile to each month's budget and
draws the actual as budget times a uniform miss — so a year of comparatives is
a flat level with a fixed seasonal wobble and independent noise on top. Nothing
grows, nothing breaks, and every month's residual is drawn from the same
distribution as every other month's. "Which month was genuinely unusual" is
therefore not a hard question; it is not a question at all.

Two halves, and they are deliberately the same arithmetic read in both
directions:

:func:`project` **generates** a series with the structure a real one has —
a compounding trend, a multiplicative seasonal profile, and autocorrelated
noise, because last month's surprise leaks into this month's and independent
draws are the one thing real monthly figures never are.

:func:`decompose` **reads** a series back into trend, seasonal and residual by
classical multiplicative decomposition — centred moving average for the trend,
per-position *median* of the detrended ratios for the seasonal indices,
normalised so they average to one, and a second pass that refits with the first
pass's outliers replaced by what the first pass expected, so one spike cannot
tilt the trend that every other month is then judged against.
:func:`anomalies` then flags the periods whose residual
is far from the rest **by median absolute deviation, not standard deviation** —
the whole point is to find outliers, and an outlier inflates the standard
deviation it is being measured against, so a z-score quietly hides exactly what
it was asked to find. MAD does not.

Reading the corpus back with the same model that made it is not circular here,
because the corpus's figures are not made by this module: they come from
``finance.py``'s draws, its allocation, and whatever an episode did to them.
The decomposition is a measurement of the result, and it says useful things
precisely when the result does *not* match a clean trend-plus-season — which
is what an incident month is.

**Determinism.** Every generated value is drawn from an ``Rng`` stream named
for what it is and rounded to an integer before it can become a fact, so no
float from this module ever reaches a corpus unrounded. The analysis half runs
on floats and its output is *reported*, never minted: a decomposition that
differed in the twelfth decimal between numpy builds would move a printed
number and nothing else. numpy is used for the elementwise arithmetic, which
is IEEE-exact and identical everywhere; there is no matrix product anywhere in
this module, which is the operation that would not be.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rng import Rng

#: Below this many observations a decomposition is arithmetic without meaning:
#: a centred moving average of one period needs a full period either side, so
#: two whole cycles is the floor at which a seasonal index is an average of
#: more than one number.
MINIMUM_OBSERVATIONS = 2

#: The modified-z threshold at which a residual counts as an outlier. 3.5 is the
#: usual figure for the statistic, and it is shared between :func:`anomalies`
#: (which reports them) and :func:`decompose` (which refits without them), so
#: the decomposition can never disagree with the report about what an outlier
#: is.
ANOMALY_SENSITIVITY = 3.5


@dataclass(frozen=True)
class Decomposition:
    """One series, separated into what explains it.

    ``values ≈ trend * seasonal * residual`` at every index, which is what
    "multiplicative" means and why a residual reads as a percentage of normal:
    ``1.08`` is "eight per cent above what the trend and the season predicted",
    a sentence a finance reader can act on. An additive decomposition would say
    "+3,200", which is a different and much less useful sentence when the level
    of the series has doubled across the window.
    """

    values: tuple[float, ...]
    trend: tuple[float, ...]
    seasonal: tuple[float, ...]
    residual: tuple[float, ...]
    seasonal_indices: tuple[float, ...]
    """One index per position in the cycle, normalised to average 1.0."""
    period: int

    @property
    def seasonal_amplitude(self) -> float:
        """How much of the series' movement the season explains, peak to trough."""
        return max(self.seasonal_indices) - min(self.seasonal_indices)

    def seasonally_adjusted(self) -> tuple[float, ...]:
        """The series with the season divided out — the comparison a reader wants
        when asking whether this month was better than last month."""
        return tuple(v / s if s else v for v, s in zip(self.values, self.seasonal))

    @property
    def growth_per_period(self) -> float:
        """The fitted compound rate, read off the ends of the trend component.

        Off the *trend*, never off the raw series: the first and last raw
        observations sit at different points in the cycle, so a rate computed
        from them reports the season as growth. A December-to-January reading
        of a flat business would say it shrank by a fifth.

        And off the trend's **interior**. A centred moving average cannot be
        computed within half a cycle of either end, and :func:`decompose` holds
        those edges flat rather than extrapolating them. Reading the rate from
        index 0 to index n-1 therefore divides a shorter run of real movement
        by the full length and understates growth by roughly a cycle's worth —
        a 1.0% series reads as 0.66% over three years, which is not a rounding
        difference but a wrong answer.
        """
        half = self.period // 2
        first, last = (half, len(self.trend) - 1 - half) if len(self.trend) > 2 * half + 1 \
            else (0, len(self.trend) - 1)
        if last <= first or self.trend[first] <= 0:
            return 0.0
        return (self.trend[last] / self.trend[first]) ** (1.0 / (last - first)) - 1.0

    def extend(self, periods: int) -> tuple[float, ...]:
        """What the fitted trend and season say the next *periods* should be.

        The corpus's own expectation of itself, and useful for exactly one
        thing: saying how far the reporting period departed from it. Noise-free
        by construction — a forecast with a random shock in it is a sample, not
        an expectation, and the shock would be the only reason two runs
        disagreed.
        """
        if periods <= 0 or not self.trend:
            return ()
        rotated = tuple(
            self.seasonal_indices[(len(self.values) + offset) % self.period]
            for offset in range(self.period)
        )
        growth = self.growth_per_period
        return project(
            None,
            periods=periods,
            level=self.trend[-1] * (1.0 + growth),
            trend_pct=growth,
            seasonal=rotated,
        )


def project(
    rng: Rng | None,
    *,
    periods: int,
    level: float,
    trend_pct: float = 0.0,
    seasonal: tuple[float, ...] = (),
    noise_pct: float = 0.0,
    persistence: float = 0.0,
    regime_at: int | None = None,
    regime_pct: float = 0.0,
) -> tuple[float, ...]:
    """A series of *periods* values, oldest first.

    ``trend_pct`` compounds per period: ``0.004`` is a shade under five per cent
    a year, growth a mid-size business actually shows. ``seasonal`` is a
    multiplicative profile indexed by ``position % len(seasonal)``; an empty
    profile means no season.

    ``persistence`` is the AR(1) coefficient on the noise, and it is the field
    that makes this a time series rather than a column of independent draws.
    At ``0.0`` each period's surprise is unrelated to the last, which is the
    behaviour ``finance.py`` has today and the reason its comparative months
    carry no information: an adverse month tells you nothing about the next.
    At ``0.6`` a bad month is more likely to be followed by another, which is
    what makes a *run* of adverse months a signal a reader can legitimately
    reason from.

    ``regime_at``/``regime_pct`` apply a step change from that index onward —
    a lost contract, a site closure, a pricing move. A trend break is the
    single most useful thing a series can contain for evaluation, because it
    is the case where "extrapolate the trend" is confidently wrong.

    Every draw comes from a named ``Rng`` stream, so adding a parameter here
    never reshuffles a series that did not use it.
    """
    if periods <= 0:
        return ()
    if rng is None and noise_pct:
        raise ValueError("a noisy series needs an Rng; pass one or set noise_pct=0")
    shocks = np.zeros(periods, dtype=float)
    if rng is not None and noise_pct:
        previous = 0.0
        for index in range(periods):
            # Named per index rather than drawn from one stream in a loop, so a
            # caller asking for eleven periods and one asking for twelve agree
            # on the first eleven.
            draw = rng.derive(f"shock/{index}").number(-1.0, 1.0)
            previous = persistence * previous + (1.0 - persistence) * draw
            shocks[index] = previous

    positions = np.arange(periods, dtype=float)
    trend = level * np.power(1.0 + trend_pct, positions)
    season = np.array(
        [seasonal[index % len(seasonal)] if seasonal else 1.0 for index in range(periods)],
        dtype=float,
    )
    step = np.ones(periods, dtype=float)
    if regime_at is not None and 0 <= regime_at < periods:
        step[regime_at:] = 1.0 + regime_pct
    return tuple(trend * season * step * (1.0 + noise_pct * shocks))


def _robust_scale(sample: np.ndarray, centre: float) -> float:
    """A robust estimate of *sample*'s spread about *centre*, never a silent zero.

    Median absolute deviation first, scaled by 1.4826 so it reads on the same
    scale as a standard deviation for normal data. The fallback is the point:
    **MAD is zero whenever more than half the sample is identical**, which is
    not a rare corner on generated data — a run of months at the same rounded
    figure does it — and a zero scale makes every threshold test below divide
    by nothing and quietly conclude there are no outliers. The spike a reader
    would see at a glance is exactly the input that produces it.

    So a zero MAD falls back to the mean absolute deviation about the same
    centre (1.2533 is its own consistency constant), and a sample that is
    *genuinely* constant returns 0.0 — at which point the caller's own
    ``> 0`` guard is answering the right question: there is no spread, so
    anything different is different by any margin at all.
    """
    # "Zero" has to mean *negligible against the data's own magnitude*, not
    # literally 0.0. A residual series that is 1.0 everywhere except for
    # floating-point dust has a mean absolute deviation around 1e-16, and
    # treating that as a real scale turns every rounding artefact into a
    # thirty-sigma anomaly — which is what the first version of this fallback
    # did to a perfectly regular series.
    negligible = max(abs(centre), 1.0) * 1e-12

    deviation = 1.4826 * float(np.median(np.abs(sample - centre)))
    if deviation > negligible:
        return deviation
    mean_deviation = 1.2533 * float(np.mean(np.abs(sample - centre)))
    return mean_deviation if mean_deviation > negligible else 0.0


#: How many refinement passes :func:`decompose` takes. One pass fits, one pass
#: refits with the outliers of the first replaced by what the fit expected —
#: which is enough, because the second fit's outliers are by construction the
#: same set unless the first fit was dominated by them, and a third pass has
#: never changed an answer in this repository's fixtures.
_REFINEMENT_PASSES = 2


def _fit(series: np.ndarray, period: int) -> tuple[np.ndarray, np.ndarray]:
    """One pass: ``(trend, seasonal indices)`` for *series*.

    Centred moving average for the trend. An even-length cycle needs the
    half-weighted end points, or the average sits half a period off the value
    it is meant to explain and the seasonal indices absorb the offset as a
    phantom season.
    """
    n = series.size
    half = period // 2
    trend = np.full(n, np.nan)
    for index in range(half, n - half):
        window = series[index - half : index + half + 1]
        if period % 2 == 0:
            weights = np.ones(period + 1)
            weights[0] = weights[-1] = 0.5
            trend[index] = float(np.sum(window * weights) / period)
        else:
            trend[index] = float(np.mean(window))

    # The ends have no full window. Held flat at the nearest computed value
    # rather than extrapolated: extrapolation invents a trend beyond the data,
    # and the residual at the very edge would then measure the invention.
    known = np.flatnonzero(~np.isnan(trend))
    if known.size == 0:
        trend[:] = float(np.mean(series))
    else:
        trend[: known[0]] = trend[known[0]]
        trend[known[-1] + 1 :] = trend[known[-1]]

    detrended = np.divide(series, trend, out=np.ones_like(series), where=trend != 0)
    indices = np.ones(period)
    for position in range(period):
        sample = detrended[position::period]
        if sample.size:
            # Median, not mean: one spiked cycle at this position should not
            # move the index every other cycle at that position is judged by.
            indices[position] = float(np.median(sample))
    # Normalised so the season redistributes the level rather than shifting it:
    # indices that averaged 1.04 would fold a 4% trend into "the season".
    mean_index = float(np.mean(indices))
    if mean_index:
        indices = indices / mean_index
    return trend, indices


def decompose(values: tuple[float, ...] | list[float], *, period: int) -> Decomposition:
    """Classical multiplicative decomposition of *values* over a cycle of *period*.

    Raises rather than guessing when there is not enough data: a seasonal index
    averaged over a single observation is that observation, so the residual is
    identically 1.0 and every anomaly disappears. Silently returning that would
    be worse than refusing, because it looks like a clean corpus.
    """
    if period < 2:
        raise ValueError(f"a cycle needs at least 2 positions, not {period}")
    if len(values) < period * MINIMUM_OBSERVATIONS:
        raise ValueError(
            f"{len(values)} observations cannot decompose a {period}-period cycle; "
            f"at least {period * MINIMUM_OBSERVATIONS} are needed for a seasonal index "
            "to average more than one number"
        )
    series = np.asarray(values, dtype=float)
    n = series.size

    # Refit with the first pass's outliers replaced by what the first pass
    # expected them to be, and measure the residual against the untouched
    # original. Without this, a spike contaminates every trend point whose
    # moving-average window contains it: the trend rises for half a cycle
    # either side, the spike's innocent neighbours are pushed below their own
    # trend, and they are reported as anomalies in their own right. Five
    # planted spikes produced seven findings, two of them ordinary months whose
    # only crime was sitting next to one
    # (`tests/test_series.py::test_a_planted_spike_is_found_and_nothing_else_is`).
    #
    # The obvious cheaper fix — run a Hampel filter over the raw series first —
    # is wrong here, and wrong in a way worth recording: within a window of
    # half a cycle a genuine **seasonal peak** is an outlier. A December that
    # is thirty per cent above its neighbours is exactly what the profile says
    # it should be, and a local filter flattens it, biasing the trend and
    # putting a systematic tilt into every residual in the series. Iterating on
    # the *residual* has no such problem, because the season has already been
    # divided out by the time anything is judged.
    working = series
    trend, indices = _fit(working, period)
    for _ in range(_REFINEMENT_PASSES - 1):
        fitted = trend * np.array([indices[i % period] for i in range(n)])
        ratio = np.divide(series, fitted, out=np.ones_like(series), where=fitted != 0)
        centre = float(np.median(ratio))
        spread = _robust_scale(ratio, centre)
        if spread == 0.0:
            break
        outlying = np.abs(ratio - centre) > ANOMALY_SENSITIVITY * spread
        if not outlying.any():
            break
        working = np.where(outlying, fitted, series)
        trend, indices = _fit(working, period)

    seasonal = np.array([indices[i % period] for i in range(n)])
    fitted = trend * seasonal
    residual = np.divide(series, fitted, out=np.ones_like(series), where=fitted != 0)

    return Decomposition(
        values=tuple(float(v) for v in series),
        trend=tuple(float(v) for v in trend),
        seasonal=tuple(float(v) for v in seasonal),
        residual=tuple(float(v) for v in residual),
        seasonal_indices=tuple(float(v) for v in indices),
        period=period,
    )


def anomalies(
    decomposition: Decomposition, *, sensitivity: float = ANOMALY_SENSITIVITY
) -> tuple[tuple[int, float], ...]:
    """Indices whose residual is far from the rest, with each one's robust score.

    Scored on **median absolute deviation**, scaled by the 0.6745 consistency
    constant so the number reads on the same scale a z-score would. A standard
    deviation is the wrong tool by construction here: the outlier being hunted
    is one of the observations inflating the spread it is measured against, so
    a single large anomaly raises the bar until it no longer clears it —
    a detector that hides the thing it was built to find, and hides it worst
    exactly when it is largest.

    ``sensitivity`` of 3.5 is the usual threshold for the modified z-score.
    Returns ``()`` when the residuals have no spread at all — a perfectly
    regular series has no anomalies, rather than all of them.
    """
    residual = np.asarray(decomposition.residual, dtype=float)
    if residual.size == 0:
        return ()
    median = float(np.median(residual))
    deviation = _robust_scale(residual, median)
    if deviation == 0.0:
        # Genuinely constant residuals: the fit explains the series exactly and
        # there is nothing to be an outlier *from*. Distinct from a zero MAD,
        # which `_robust_scale` no longer returns for a series that merely has
        # a flat majority — that case used to land here and report no anomalies
        # on a series with an obvious spike in it.
        return ()
    # 0.6745 is the MAD-to-sigma constant for the modified z-score; the 1.4826
    # inside `_robust_scale` is its reciprocal, so the two compose to the raw
    # deviation and the threshold below reads on the usual scale.
    scores = 0.6745 * 1.4826 * (residual - median) / deviation
    found = [
        (int(index), float(scores[index]))
        for index in range(residual.size)
        if abs(scores[index]) >= sensitivity
    ]
    # Largest departure first, ties on index, so the caller reads the most
    # interesting period before the merely notable one.
    return tuple(sorted(found, key=lambda row: (-abs(row[1]), row[0])))


__all__ = [
    "Decomposition",
    "ANOMALY_SENSITIVITY",
    "MINIMUM_OBSERVATIONS",
    "anomalies",
    "decompose",
    "project",
]
