"""The `--eval-density` knob, exercised at the scale it exists for.

Every other density test (`test_fanout.py`'s fixed shapes,
`generators/evaluation.py`'s per-family gates) runs at the default archetype
and a single period, because that is what the byte-identity gate needs
proven: nothing changes unless the knob is turned. What that leaves unproven
is the actual point of the knob — that turning it, on a world large enough to
have something to exploit, produces a benchmark that is not a fixed dozen
cases regardless of how big the corpus around it is. That needs a real
multi-period build on the large archetype, which is slow enough (several
seconds of financial and evaluation generation per period, times several
periods) to not belong in the default `pytest -q` gate — hence `slow`,
deselected by `pyproject.toml`'s `addopts` and run explicitly with
`pytest -m slow`.

Scaled down from the report's measured build (`australian_grocery --periods 3
--incident` at `high`) to two periods rather than three: enough for
`across_episodes`'s multi-period families to have a second prior period to
find, without paying for a third episode's financial and evaluation
generation in every CI run that opts in.
"""

from __future__ import annotations

import time

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.archetypes import AUSTRALIAN_GROCERY

PERIODS = ("2026-01", "2026-02")


def _build(*, eval_density: float, periods: tuple[str, ...] = PERIODS) -> World:
    world = RetailWorld(seed=8128, archetype=AUSTRALIAN_GROCERY).build()
    for period in periods:
        world = world.run(
            MonthEndClose(
                period=period, include_operational_incident=True, eval_density=eval_density,
            )
        )
    return world


@pytest.mark.slow
def test_a_large_high_density_build_completes_and_validates() -> None:
    started = time.monotonic()
    world = _build(eval_density=2.0)
    elapsed = time.monotonic() - started

    report = world.validate()
    assert report.ok, report.violations[:5]
    # Not a performance assertion — CI hardware varies — just a guard against
    # the knob accidentally making generation quadratic in something (a
    # category loop nested inside a site loop, say) rather than linear in the
    # world it is asked to exploit.
    assert elapsed < 60, f"a two-period high-density build took {elapsed:.1f}s"


@pytest.mark.slow
def test_high_density_strictly_grows_the_evaluation_set() -> None:
    """The property the whole knob exists for: more world, more questions.

    Compared against the same two-period build at the standard density
    rather than against a single default-shaped build, so the difference
    measured is density alone — the periods, the archetype, and the
    incident are held constant on both sides.
    """
    default = _build(eval_density=1.0)
    dense = _build(eval_density=2.0)

    assert len(dense.evaluations) > len(default.evaluations)
    # The fan-out side of the same knob: `high` argues categories below the
    # unit level (`planning.py`'s `eval_density` block), so a larger
    # archetype's document count should grow with it too, not just its
    # question count.
    assert len(dense.artifact_intents) > len(default.artifact_intents)


@pytest.mark.slow
def test_low_density_shrinks_the_optional_fan_out_without_losing_questions() -> None:
    """`low` trims documents (`scenarios.py`'s lore-override), but every
    question the standard corpus already answers must still be answerable —
    none of today's cases depend on the optional documents this removes."""
    default = _build(eval_density=1.0)
    minimal = _build(eval_density=0.0)

    assert len(minimal.artifact_intents) < len(default.artifact_intents)
    assert len(minimal.evaluations) == len(default.evaluations)
    report = minimal.validate()
    assert report.ok, report.violations[:5]
