"""Session-scoped worlds for tests that repeat the same expensive build.

Only builds that are *genuinely repeated with identical specs* belong here —
a fixture for a build one test uses would just move code away from its
assertion. The candidates today are ``test_density.py``'s slow-lane builds:
two periods on the large archetype, built five times across three tests but
with only three distinct ``eval_density`` values (0.0 once, 1.0 twice,
2.0 twice). The once-built 0.0 world stays inline in its test.

Sharing is safe because the consuming tests only *read* the ``World`` —
``evaluations``, ``artifact_intents``, ``validate()`` (which returns a report
and touches no disk). Nothing here may call ``export``: exporting mutates the
filesystem, and a session-scoped export would let one test's leftovers become
another's input. A test that needs an export must do it itself, into its own
``tmp_path``.

Fixtures are lazy, so the default ``pytest -q`` run (which deselects ``slow``)
never pays for these.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.archetypes import AUSTRALIAN_GROCERY

#: The two periods `test_density.py` documents: enough for the multi-period
#: families to have a prior period to find, without paying for a third.
DENSITY_PERIODS = ("2026-01", "2026-02")


def build_density_world(*, eval_density: float) -> World:
    """One two-period large-archetype build at the given density.

    Module-level rather than closed over by the fixtures so a test that needs
    a density no other test shares (the 0.0 build) can call it directly and
    stay honest about paying for its own build.
    """
    world = RetailWorld(seed=8128, archetype=AUSTRALIAN_GROCERY).build()
    for period in DENSITY_PERIODS:
        world = world.run(
            MonthEndClose(
                period=period, include_operational_incident=True, eval_density=eval_density,
            )
        )
    return world


@dataclass(frozen=True)
class TimedWorld:
    """A shared build that still answers "how long did building take?".

    The high-density build carries a wall-clock guard (nothing may make
    generation quadratic), and a session fixture would silently delete that
    measurement if it returned only the ``World`` — whichever test ran first
    would have absorbed the build time. Measuring in the fixture keeps the
    guard meaningful however many tests share the world.
    """

    world: World
    build_seconds: float


@pytest.fixture(scope="session")
def density_default_world() -> World:
    """The two-period build at the standard density (1.0), built once."""
    return build_density_world(eval_density=1.0)


@pytest.fixture(scope="session")
def density_dense_build() -> TimedWorld:
    """The two-period build at high density (2.0), built once, with timing."""
    started = time.monotonic()
    world = build_density_world(eval_density=2.0)
    return TimedWorld(world=world, build_seconds=time.monotonic() - started)
