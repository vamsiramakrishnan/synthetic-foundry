"""The rotating replay sweep samples only commands the public CLI supports.

Both tests here asserted the wrong rule for as long as they existed, and the
rule they asserted is the defect they were meant to prevent.

They required every candidate to be single-period unless its engine had no
built-in episode — that is, everything but retail — citing a blanket CLI refusal
of ``--periods > 1``. That refusal is gone. Only insurance declares a cap
(``Domain.max_periods == 1``); banking and procurement build, validate and
replay byte-for-byte at 3 periods and at 12. So the nightly determinism gate
**had never once compared two builds of a bank beyond a single period**, which
is the one property it exists to check, and these tests held it that way.

A test that pins a workaround outlives the reason for the workaround. The
assertion is now the same one the script makes — the engine's own declared cap —
so the two cannot drift again without this file failing.
"""

from __future__ import annotations

from pathlib import Path
import runpy

from worldloom import domains


SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "dispersed_replay.py"


def _within_declared_cap(configuration) -> bool:  # type: ignore[no-untyped-def]
    """Whether a sampled configuration is one its engine says it can build."""
    domain = domains.by_name(configuration.engine)
    cap = domain.max_periods if domain is not None else None
    return cap is None or configuration.periods <= cap


def test_dispersed_candidates_ask_no_engine_for_more_than_it_declares() -> None:
    namespace = runpy.run_path(str(SCRIPT))

    candidates = namespace["_candidates"]()

    assert candidates
    assert all(_within_declared_cap(c) for c in candidates)


def test_the_gate_reaches_multi_period_builds_of_every_uncapped_engine() -> None:
    """The half the old shape could not state, and the reason it matters.

    Excluding what an engine cannot build is only half a sampler's job; the
    other half is that it *does* reach what the engine can. Asserted per engine
    rather than in aggregate, because "some candidate somewhere has periods > 1"
    was true throughout the years this gate never sampled a multi-period bank —
    retail alone satisfied it.
    """
    namespace = runpy.run_path(str(SCRIPT))

    candidates = namespace["_candidates"]()
    reached: dict[str, set[int]] = {}
    for configuration in candidates:
        reached.setdefault(configuration.engine, set()).add(configuration.periods)

    for name in sorted(domains.names()):
        domain = domains.by_name(name)
        if domain is None or domain.max_periods is not None:
            continue  # insurance: capped at one, and correctly never sampled higher
        assert name in reached, f"{name} is never sampled at all"
        assert max(reached[name]) > 1, (
            f"{name} declares no period cap and the gate only ever samples it at"
            f" {sorted(reached[name])} — a byte-identity gate that never builds"
            " an engine twice past one period cannot notice it breaking there"
        )


def test_a_capped_engine_is_never_sampled_past_its_cap() -> None:
    """Insurance, which is the one engine that really does refuse.

    `QuarterlyReserving` implements phase 1 and raises on its second consecutive
    run, so sampling it at two periods would test argument validation rather
    than replay determinism — and would fail before there was a corpus to
    compare.
    """
    namespace = runpy.run_path(str(SCRIPT))

    capped = [
        name for name in domains.names()
        if (domain := domains.by_name(name)) is not None
        and domain.max_periods is not None
    ]
    assert capped, "no engine declares a cap, so this test has no subject"

    for configuration in namespace["_candidates"]():
        if configuration.engine in capped:
            cap = domains.by_name(configuration.engine).max_periods
            assert configuration.periods <= cap


def test_the_selection_respects_the_same_caps_the_enumeration_does() -> None:
    namespace = runpy.run_path(str(SCRIPT))

    selected = namespace["select"](146, 3)

    assert all(_within_declared_cap(c) for c in selected)
