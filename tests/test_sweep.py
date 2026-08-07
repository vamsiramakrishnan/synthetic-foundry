"""The determinism sweep's own contract — its enumeration, not its builds.

``tools/sweep.py`` is the gate that covers the configuration space instead of
one corner of it, and its whole value rests on two claims that are cheap to
check and expensive to lose:

1. **A seed is the entire state.** The same seed selects the same
   configurations, and a printed id names the same build in the next process.
   If that stops holding, the replay instruction the tool prints on every
   failure becomes a lie, and a nightly rotating sample becomes unactionable.
2. **The space comes from the registries.** Every axis is read out of
   ``worldloom`` at call time, so registering an archetype, a locale or a facet
   widens the sweep without anybody editing it. A hand-written list would be
   stale on the next commit and would still report green.

Nothing here builds a world. The builds are the tool's job and they take
minutes; these are the properties that make the minutes worth spending, and
``pytest -q`` has to stay fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

sweep = pytest.importorskip("sweep")


# ---------------------------------------------------------------------------
# 1. A seed is the entire state
# ---------------------------------------------------------------------------


def test_the_same_seed_selects_the_same_configurations() -> None:
    """The claim the tool prints at the bottom of every run."""
    first = sweep.field_of(6, seed=8128, pool=256)
    second = sweep.field_of(6, seed=8128, pool=256)
    assert [c.id for c in first.configs] == [c.id for c in second.configs]
    assert [c.as_dict() for c in first.configs] == [c.as_dict() for c in second.configs]


def test_a_smaller_field_is_a_prefix_of_a_larger_one() -> None:
    """``-n 4`` and ``-n 12`` agree on the four they share.

    A property of the greedy traversal rather than of this file, and worth
    pinning here anyway: without it, narrowing a failing run from twelve
    configurations to the four that matter would silently select four *different*
    configurations, and the narrowing would look like the bug going away.
    """
    small = sweep.field_of(4, seed=8128, pool=256)
    large = sweep.field_of(12, seed=8128, pool=256)
    assert [c.id for c in small.configs] == [c.id for c in large.configs[:4]]


def test_consecutive_seeds_take_disjoint_halton_windows() -> None:
    """What makes the CI rotation cover new ground rather than jitter.

    A window that merely shifted by one would give consecutive nightly runs
    almost the same candidates, which is the defect the rotation exists to
    avoid — one corner, sampled repeatedly, wearing a different number.
    """
    pool = sweep.POOL
    windows = [range(sweep.window(seed, pool), sweep.window(seed, pool) + pool)
               for seed in (1, 2, 3)]
    for earlier, later in zip(windows, windows[1:]):
        assert set(earlier).isdisjoint(later)


def test_an_id_survives_a_fresh_process() -> None:
    """Content-addressed, not ``hash()``.

    ``hash()`` is randomised per process, so an id printed by one run would name
    a different configuration in the next — see ``ids.content_key``, which is
    what this uses and why.
    """
    config = sweep.field_of(1, seed=8128, pool=256).configs[0]
    import subprocess

    printed = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import sweep;"
         " print(sweep.field_of(1, seed=8128, pool=256).configs[0].id)"
         % str(ROOT / "tools")],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert printed == config.id


# ---------------------------------------------------------------------------
# 2. The space comes from the registries
# ---------------------------------------------------------------------------


def test_every_axis_is_read_from_a_registry() -> None:
    from worldloom import domains, locales, messiness, profiles

    space = {axis.name: axis.values for axis in sweep.axes()}
    assert space["engine"] == tuple(sorted(domains.names()))
    assert set(space["locale"]) == {None, *locales.LOCALES}
    assert set(space["calendar"]) == {None, *profiles.PROFILES}
    assert set(space["messiness"]) == {None, *messiness.PROFILES}
    # Facets come through `facets.combinations()`, which filters by the
    # registry's own exclusion arithmetic — so no selected configuration can
    # ever ask for a listed mutual.
    assert len(space["facets"]) > 1


def test_selected_configurations_respect_what_each_engine_has() -> None:
    """The projections actually applied, on a real selection.

    Each assertion below is a refusal that already exists somewhere in
    ``worldloom`` — a missing dataclass field, a domain's own declaration, a
    closed landscape table. A configuration that violated one would not be a
    novel corner of the space; it would be a build that exits 2, and a sweep
    full of those covers nothing.
    """
    import dataclasses

    from worldloom import domains, landscape

    for config in sweep.field_of(24, seed=8128, pool=512).configs:
        domain = domains.by_name(config.engine)
        assert domain is not None
        assert config.archetype in domain.archetype_keys
        fields = {f.name for f in dataclasses.fields(domain.world)}
        if config.calendar is not None:
            assert "seasonality" in fields
            assert config.surface == "spec"          # there is no --calendar flag
        if config.periods > 1:
            assert domain.single_episode is None
        if config.estate is not None:
            assert config.engine in landscape.LANDSCAPES
        if config.data == "master_data":
            assert config.surface == "spec"          # nor a --master-data flag
