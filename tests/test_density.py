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

The 1.0 and 2.0 builds arrive as session fixtures (`conftest.py`): three
tests used to build them five times between them, and the worlds are only
ever read here — no test may export one. The 0.0 build stays inline because
exactly one test wants it.
"""

from __future__ import annotations

import pytest

# Plain-module import, the same way `test_actors.py` reaches `scripted_actor`:
# this suite is rootdir-imported without an `__init__.py`, so `tests` is not a
# package a relative import could climb.
from conftest import TimedWorld, build_density_world  # type: ignore[import-not-found]

from worldloom import World


@pytest.mark.slow
def test_a_large_high_density_build_completes_and_validates(
    density_dense_build: TimedWorld,
) -> None:
    report = density_dense_build.world.validate()
    assert report.ok, report.violations[:5]
    # Not a performance assertion — CI hardware varies — just a guard against
    # the knob accidentally making generation quadratic in something (a
    # category loop nested inside a site loop, say) rather than linear in the
    # world it is asked to exploit. The fixture measured the build, so the
    # guard survives the world being shared.
    assert density_dense_build.build_seconds < 60, (
        f"a two-period high-density build took {density_dense_build.build_seconds:.1f}s"
    )


@pytest.mark.slow
def test_high_density_strictly_grows_the_evaluation_set(
    density_default_world: World, density_dense_build: TimedWorld,
) -> None:
    """The property the whole knob exists for: more world, more questions.

    Compared against the same two-period build at the standard density
    rather than against a single default-shaped build, so the difference
    measured is density alone — the periods, the archetype, and the
    incident are held constant on both sides.
    """
    default = density_default_world
    dense = density_dense_build.world

    assert len(dense.evaluations) > len(default.evaluations)
    # The fan-out side of the same knob: `high` argues categories below the
    # unit level (`planning.py`'s `eval_density` block), so a larger
    # archetype's document count should grow with it too, not just its
    # question count.
    assert len(dense.artifact_intents) > len(default.artifact_intents)


@pytest.mark.slow
def test_low_density_shrinks_the_optional_fan_out_without_losing_questions(
    density_default_world: World,
) -> None:
    """`low` trims documents (`scenarios.py`'s lore-override), and a question
    may vanish with the document it interrogates — never on its own.

    This originally asserted the two evaluation sets were *equal*: "none of
    today's cases depend on the optional documents this removes." That claim
    aged out unwitnessed — the suite was deselected and ran nowhere — and the
    first real run caught it: the approval-provenance family (added later,
    with the Approval blocks) mints two questions per divisional close
    commentary, which is precisely a document the low build trims. Those
    questions *should* go with their document; a corpus asking who approved a
    commentary it does not contain would be incoherent. So the invariant is
    now the honest half of the original: every lost question must name a
    trimmed document as required reading, and losing a question whose
    documents all survive is still a failure.

    Cases are matched by question text, not id — fewer intents reshuffle the
    sequential ids, and an id-keyed diff would report every case changed
    (`twins.py` refuses interventions for exactly this reason).
    """
    default = density_default_world
    minimal = build_density_world(eval_density=0.0)

    assert len(minimal.artifact_intents) < len(default.artifact_intents)

    default_by_question = {case.question: case for case in default.evaluations}
    minimal_by_question = {case.question: case for case in minimal.evaluations}
    # Trimming may only remove questions, never invent them.
    assert set(minimal_by_question) <= set(default_by_question)

    from collections import Counter

    default_counts = Counter(i.artifact_type for i in default.artifact_intents)
    minimal_counts = Counter(i.artifact_type for i in minimal.artifact_intents)
    trimmed_types = {t for t in default_counts if minimal_counts[t] < default_counts[t]}

    lost = [case for question, case in default_by_question.items()
            if question not in minimal_by_question]
    for case in lost:
        required_types = {
            default.artifact_intents.by_id(a).artifact_type
            for a in case.required_artifact_ids
        }
        assert required_types & trimmed_types, (
            f"{case.id} was lost but every document it requires survives the"
            f" trim: {case.question!r} (requires {sorted(required_types)})"
        )
    report = minimal.validate()
    assert report.ok, report.violations[:5]
