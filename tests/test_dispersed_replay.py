"""The rotating replay sweep samples only commands the public CLI supports."""

from __future__ import annotations

from pathlib import Path
import runpy

from worldloom import domains


SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "dispersed_replay.py"


def test_dispersed_candidates_exclude_refused_multi_period_verticals() -> None:
    namespace = runpy.run_path(str(SCRIPT))

    candidates = namespace["_candidates"]()

    assert candidates
    assert all(
        configuration.periods == 1
        or domains.by_name(configuration.engine).single_episode is None
        for configuration in candidates
    )


def test_failed_ci_rotation_now_selects_only_buildable_period_counts() -> None:
    namespace = runpy.run_path(str(SCRIPT))

    selected = namespace["select"](146, 3)

    assert all(
        configuration.periods == 1
        or domains.by_name(configuration.engine).single_episode is None
        for configuration in selected
    )
