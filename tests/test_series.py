"""Time series: what is generated, what is read back, and the knob between them.

The decomposition is checked against series whose shape is *known by
construction* — a pure trend has no season, a pure season has no trend, and a
planted spike is the one period the residual should reject. Checking it against
a corpus instead would only prove the arithmetic agrees with itself.

The `--trend` knob is held to the byte-identity contract every optional knob in
this project has: a build that does not pass it must be indistinguishable from
a build made before it existed, and that is asserted rather than reasoned
about.
"""

from __future__ import annotations

import itertools

import pytest

from worldloom import RetailWorld, World, series
from worldloom.rng import Rng
from worldloom.scenarios import MonthEndClose

SEED = 8128
#: A twelve-position profile with a real December peak, so the tests below are
#: about a season that exists rather than about rounding.
PROFILE = (0.9, 0.88, 0.95, 1.0, 1.02, 0.98, 1.0, 1.01, 1.05, 1.05, 1.06, 1.3)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def test_a_flat_series_is_flat() -> None:
    values = series.project(None, periods=6, level=100.0)
    assert values == (100.0,) * 6


def test_a_trend_compounds() -> None:
    values = series.project(None, periods=3, level=100.0, trend_pct=0.10)
    assert [round(v, 6) for v in values] == [100.0, 110.0, 121.0]


def test_a_regime_step_lands_where_it_is_asked_to() -> None:
    values = series.project(None, periods=4, level=100.0, regime_at=2, regime_pct=-0.2)
    assert [round(v, 6) for v in values] == [100.0, 100.0, 80.0, 80.0]


def test_a_noisy_series_needs_a_stream() -> None:
    with pytest.raises(ValueError, match="Rng"):
        series.project(None, periods=4, level=100.0, noise_pct=0.1)


def test_the_same_stream_draws_the_same_series() -> None:
    a = series.project(Rng(SEED, "s"), periods=8, level=100.0, noise_pct=0.2, persistence=0.5)
    b = series.project(Rng(SEED, "s"), periods=8, level=100.0, noise_pct=0.2, persistence=0.5)
    assert a == b


def test_a_longer_request_agrees_with_a_shorter_one_on_the_overlap() -> None:
    """Shocks are named per index rather than drawn in sequence, so asking for
    twelve periods does not reshuffle the eleven a previous call got."""
    short = series.project(Rng(SEED, "s"), periods=6, level=100.0, noise_pct=0.2)
    long = series.project(Rng(SEED, "s"), periods=12, level=100.0, noise_pct=0.2)
    assert short == long[:6]


def test_persistence_makes_a_run_of_surprises_more_likely_than_independence() -> None:
    """The property that makes this a time series rather than a column: with
    persistence, consecutive residuals correlate, so an adverse month says
    something about the next one."""
    def sign_runs(values: tuple[float, ...]) -> int:
        centred = [v - 100.0 for v in values]
        return sum(1 for a, b in itertools.pairwise(centred) if a * b > 0)

    independent = series.project(Rng(SEED, "i"), periods=60, level=100.0, noise_pct=0.3)
    sticky = series.project(Rng(SEED, "i"), periods=60, level=100.0, noise_pct=0.3,
                            persistence=0.8)
    assert sign_runs(sticky) > sign_runs(independent)


# ---------------------------------------------------------------------------
# Decomposition
# ---------------------------------------------------------------------------


def test_a_short_series_is_refused_rather_than_decomposed() -> None:
    """A seasonal index averaged over one observation *is* that observation, so
    every residual is 1.0 and every anomaly disappears. Returning that quietly
    would look like a clean corpus."""
    with pytest.raises(ValueError, match="observations"):
        series.decompose([1.0] * 13, period=12)


def test_a_cycle_of_one_is_not_a_cycle() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        series.decompose([1.0] * 40, period=1)


def test_a_pure_trend_has_no_season() -> None:
    values = series.project(None, periods=36, level=1000.0, trend_pct=0.01)
    decomposition = series.decompose(values, period=12)
    assert decomposition.seasonal_amplitude < 0.01
    assert decomposition.growth_per_period == pytest.approx(0.01, abs=1e-3)


def test_a_pure_season_recovers_its_own_profile() -> None:
    values = series.project(None, periods=48, level=1000.0, seasonal=PROFILE)
    decomposition = series.decompose(values, period=12)
    normalised = [p / (sum(PROFILE) / len(PROFILE)) for p in PROFILE]
    for recovered, expected in zip(decomposition.seasonal_indices, normalised):
        assert recovered == pytest.approx(expected, abs=0.02)


def test_growth_is_read_off_the_trend_not_the_ends_of_the_series() -> None:
    """A flat business measured December-to-January would look like it shrank
    by a fifth if the rate came off the raw series."""
    values = series.project(None, periods=48, level=1000.0, seasonal=PROFILE)
    assert series.decompose(values, period=12).growth_per_period == pytest.approx(0.0, abs=1e-3)


def test_seasonal_adjustment_flattens_a_seasonal_series() -> None:
    values = series.project(None, periods=48, level=1000.0, seasonal=PROFILE)
    adjusted = series.decompose(values, period=12).seasonally_adjusted()
    middle = adjusted[12:36]
    assert max(middle) - min(middle) < 0.05 * sum(middle) / len(middle)


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------


def test_a_planted_spike_is_found_and_nothing_else_is() -> None:
    """Exclusivity is the interesting half, and it is what the refit buys. A
    spike sits inside the moving-average window of every point within half a
    cycle of it, so a single-pass trend rises around the spike and pushes its
    innocent neighbours below their own trend — they are then reported as
    anomalies too, and a reader has no way to tell which of the three months
    actually happened."""
    values = list(series.project(None, periods=48, level=1000.0, seasonal=PROFILE))
    values[30] *= 1.4
    found = series.anomalies(series.decompose(values, period=12))
    assert [index for index, _ in found] == [30]
    assert found[0][1] > 0, "an upward spike scores positive"


def test_a_seasonal_peak_is_not_mistaken_for_a_spike() -> None:
    """The trap the refit has to avoid. Within a window of half a cycle a real
    December peak *is* a local outlier, so any filter that judges a point
    against its neighbours flattens the season, tilts the trend, and puts a
    systematic bias into every residual. The refit judges residuals, where the
    season is already divided out."""
    values = series.project(None, periods=48, level=1000.0, seasonal=PROFILE)
    decomposition = series.decompose(values, period=12)
    assert series.anomalies(decomposition) == ()
    # The profile's own peak survives into the recovered indices rather than
    # being smoothed away.
    assert max(decomposition.seasonal_indices) > 1.15


def test_a_regular_series_has_no_anomalies_rather_than_all_of_them() -> None:
    values = series.project(None, periods=48, level=1000.0, seasonal=PROFILE)
    assert series.anomalies(series.decompose(values, period=12)) == ()


def test_outliers_do_not_mask_each_other() -> None:
    """Masking, which is the reason the score is a median absolute deviation
    and not a z-score. One spike a z-score finds easily. Several spikes inflate
    the standard deviation they are all measured against until none of them
    clears the bar — so the detector fails exactly when there is most to find,
    and fails silently. MAD is not moved by them, so it still finds all five.
    """
    import statistics

    # Distinct positions in the cycle. Two spikes at the *same* position
    # (8 and 20 are both position 8 of 12) would poison that position's own
    # seasonal index — a median of four samples with two spiked sits between
    # them — and the decomposition would then correctly report the two
    # *unspiked* months at that position as departures. That is the algorithm
    # working on a pathological input, not a masking failure, so it is kept
    # out of the test that is about masking.
    planted = [8, 15, 22, 31, 42]
    values = list(series.project(None, periods=48, level=1000.0, seasonal=PROFILE))
    for index in planted:
        values[index] *= 3.0
    decomposition = series.decompose(values, period=12)

    assert sorted(index for index, _ in series.anomalies(decomposition)) == planted

    residual = list(decomposition.residual)
    spread = statistics.pstdev(residual)
    mean = statistics.fmean(residual)
    missed = [
        index for index in planted
        if abs(residual[index] - mean) / spread < 3.5
    ]
    assert missed == planted, "a z-score over these residuals finds none of them"


# ---------------------------------------------------------------------------
# The --trend knob
# ---------------------------------------------------------------------------


def _built(**kwargs: object) -> World:
    return RetailWorld(seed=SEED).build().run(
        MonthEndClose(period="2026-03", comparative_months=11, **kwargs)  # type: ignore[arg-type]
    )


def test_the_default_build_is_byte_identical_without_the_knob() -> None:
    """Zero multiplies by exactly 1.0, which is an IEEE identity — so this is a
    real equality, not a tolerance."""
    assert [f.model_dump() for f in _built(trend_pct=0.0).facts] == [
        f.model_dump() for f in _built().facts
    ]


def test_a_trend_moves_the_history_and_not_the_reporting_period() -> None:
    """The trend compounds *from* the reporting period, so the current month is
    unchanged and the history sits below it."""
    def revenue(world: World) -> dict[str, float]:
        return {
            f.period: f.value.amount for f in world.facts
            if f.kind == "financial.revenue.actual" and f.subject == world.company.id
        }

    flat, grown = revenue(_built()), revenue(_built(trend_pct=0.01))
    assert grown["2026-03"] == flat["2026-03"]
    assert grown["2025-04"] < flat["2025-04"]


def test_a_trended_corpus_still_reconciles() -> None:
    assert _built(trend_pct=0.008).validate().ok


def test_a_trended_corpus_rebuilds_from_its_recipe(tmp_path) -> None:
    from worldloom.recipe import rebuild

    world = _built(trend_pct=0.008)
    exported = world.compile().export(tmp_path / "trended")
    loaded = World.load(exported)
    assert loaded.recipe["steps"][0]["trend_pct"] == 0.008
    assert [f.model_dump() for f in rebuild(loaded.recipe).facts] == [
        f.model_dump() for f in world.facts
    ]


def test_a_default_recipe_does_not_carry_the_knob(tmp_path) -> None:
    """A key written unconditionally would put a new field in every future
    recipe for a value that changes nothing — the byte-for-byte default-build
    diff CI exists to catch."""
    exported = _built().compile().export(tmp_path / "flat")
    assert "trend_pct" not in World.load(exported).recipe["steps"][0]


def test_the_trend_is_visible_to_the_decomposition() -> None:
    """The generation knob and the analysis half have to agree, or one of them
    is measuring something the other did not make."""
    world = _built(trend_pct=0.01)
    points = {
        f.period: f.value.amount for f in world.facts
        if f.kind == "financial.revenue.actual" and f.subject == world.company.id
    }
    values = [points[p] for p in sorted(points)]
    decomposition = series.decompose(values, period=6)
    assert decomposition.growth_per_period > 0.002
