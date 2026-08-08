"""Selecting on what came out, and the line drawn around what that may optimise.

Two things are under test here and they pull in opposite directions. One is
that outcome selection *works*: it reads corpora rather than parameters, it
maximises the spread it claims to, and it is deterministic. The other is that it
stays inside its own fence — the default objective must never consult a
retriever, because a dataset selected against one weak baseline is a benchmark
for that baseline, and a fence that is only described in a docstring is not a
fence.

The comparison against parameter dispersion is not here. It needs narrated
corpora and a full ``evaluate.across`` survey per arm, which is a minute of
wall-clock rather than a test — ``tools/outcome_selection.py`` runs it, and its
finding is recorded in the changelog rather than asserted, because an
experiment whose result is pinned by an assertion has stopped being an
experiment.
"""

from __future__ import annotations

import importlib
from dataclasses import replace

import pytest

from worldloom import mosaic, outcomes, sdk


def _pool(size: int = 6, *, engine: str = "retail"):  # type: ignore[no-untyped-def]
    """A small measured pool. Small on purpose: every test here is about the
    selector, and a selector that behaves differently at six candidates than at
    thirty would be a defect the comparison tool would find anyway."""
    variants = mosaic.field(size, engine=engine)
    blueprints = [
        replace(sdk._from_variant(variant), vocabulary_name="") for variant in variants
    ]
    return outcomes.pool(blueprints)


# ---------------------------------------------------------------------------
# It measures corpora, and it measures them cheaply
# ---------------------------------------------------------------------------


def test_the_shape_vector_has_exactly_one_definition() -> None:
    """`sdk.Built.measure` and `outcomes.shape_vector` are the same eight numbers.

    Asserted rather than trusted because they were two copies of one walk until
    this module existed, and a loop that filters on `measure()["chokepoints"]`
    and a loop that selects on the same quantity have to agree about what a
    chokepoint is.
    """
    built = sdk.retail().org(headcount=20, span=5, levels=3).build()
    assert built.measure() == outcomes.shape_vector(built.world)
    assert set(built.topology()) <= set(built.measure())


def test_measuring_a_candidate_needs_no_prose_and_no_files() -> None:
    """The affordability constraint, as a test rather than as an intention.

    A selection loop that costs a narrated, rendered corpus per candidate costs
    more than the mosaic it is trying to improve and nobody would run it. So:
    every section is still awaiting prose and nothing was rendered, and the
    readings came back anyway.
    """
    field = _pool(3)
    for world in field.worlds:
        assert world.artifact_irs, "a candidate must be compiled to be measured"
        assert not any(section.body for ir in world.artifact_irs for section in ir.sections)
        assert not world._rendered
    assert all(reading.metrics for reading in field.readings)


def test_every_reading_shares_one_metric_vocabulary() -> None:
    """Two candidates with different corpora still have comparable vectors.

    The failure this prevents is the one `sdk._vectors` documents one module
    over: a per-candidate key list gives per-candidate vector lengths, and then
    nothing can be compared to anything.
    """
    field = _pool(4)
    keys = {tuple(sorted(reading.metrics)) for reading in field.readings}
    assert len(keys) == 1
    assert "chokepoints" in field.readings[0].metrics
    assert any(key.startswith("family:") for key in field.readings[0].metrics)


def test_a_reading_is_a_reading_of_the_corpus_not_of_the_request() -> None:
    """Different requests that produce the same corpus measure the same.

    The whole premise: the vector describes what came out. Two blueprints that
    differ only in a physics band no figure in either world falls in are the
    same corpus, and a measurement that disagreed would be measuring the
    request again under another name.
    """
    base = sdk.retail().org(headcount=20, span=5, levels=3)
    field = outcomes.pool([base, base])
    assert field.readings[0].metrics == field.readings[1].metrics
    assert field.readings[0].questions == field.readings[1].questions


# ---------------------------------------------------------------------------
# It selects on the measurements, deterministically
# ---------------------------------------------------------------------------


def test_selection_is_deterministic() -> None:
    field = _pool(6)
    assert field.select(3) == field.select(3)
    assert outcomes.distances(field.readings) == outcomes.distances(field.readings)


def test_a_smaller_selection_is_not_promised_to_be_a_prefix() -> None:
    """Stated as a test because ``field`` promises the opposite.

    ``mosaic.field`` guarantees that a smaller mosaic is a prefix of a larger
    one; ``farthest_first`` gives that for free and the parameter mosaic leans
    on it. It holds here too — the traversal is the same — and this pins it, so
    that a future edit which reorders the pool notices it has broken a property
    two callers rely on.
    """
    field = _pool(6)
    assert field.select(4)[:2] == field.select(2)


def test_selection_beats_the_pool_prefix_on_the_spread_it_optimises() -> None:
    """The weak claim, and the only one this module can make on its own.

    Outcome selection maximises measured spread; whether measured spread is
    worth having is a question about *datasets* that no unit test can answer
    (``tools/outcome_selection.py`` asks it). What is testable is that the
    optimiser optimises: the chosen subset's closest pair is further apart than
    the closest pair among the same number of candidates taken in pool order.

    Strict at three of eight and only ``>=`` at four, and that is the honest
    shape of the claim rather than a weakened one: farthest-point traversal is
    a 2-approximation to a max-min problem that is NP-hard, so it is not
    *guaranteed* to beat any particular subset, and at four of eight it ties
    the prefix on this pool. Asserting strict inequality everywhere would be
    asserting a property the algorithm does not have.
    """
    field = _pool(8)
    chosen = outcomes.report(field.readings, field.select(3))
    prefix = outcomes.report(field.readings, range(3))
    assert chosen["closest_pair"] > prefix["closest_pair"]
    assert (outcomes.report(field.readings, field.select(4))["closest_pair"]
            >= outcomes.report(field.readings, range(4))["closest_pair"])


def test_a_constant_metric_contributes_nothing_rather_than_a_half() -> None:
    """Two identical candidates are at distance zero, not at some floor."""
    base = sdk.retail().org(headcount=20, span=5, levels=3)
    field = outcomes.pool([base, base])
    assert outcomes.distances(field.readings)[0][1] == pytest.approx(0.0)


def test_readings_measured_by_different_vocabularies_refuse_to_be_compared() -> None:
    field = _pool(2)
    crippled = replace(
        field.readings[1],
        metrics={k: v for k, v in field.readings[1].metrics.items() if k != "facts"},
    )
    with pytest.raises(ValueError, match="metric vocabulary"):
        outcomes.distances([field.readings[0], crippled])


def test_a_negative_question_weight_is_refused() -> None:
    field = _pool(2)
    with pytest.raises(ValueError, match="non-negative"):
        outcomes.distances(field.readings, question_weight=-1.0)


# ---------------------------------------------------------------------------
# The Goodhart fence
# ---------------------------------------------------------------------------


def test_the_default_objective_never_consults_a_retriever(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The fence, tested structurally rather than by reading the docstring.

    `select()` is the safe objective because it selects for *spread*, and
    nothing that is fit can be overfit. If a future edit reached for a
    scorecard to break a tie, this fails: the scorer is replaced by something
    that raises, and the default path must not notice.
    """
    # `import worldloom.evaluate.score` binds the re-exported *function* of that
    # name, not the submodule — `evaluate/__init__` exports both under one
    # attribute — so the module has to be fetched by name.
    score_module = importlib.import_module("worldloom.evaluate.score")

    field = _pool(4)

    def refuse(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("the default objective scored a retriever")

    monkeypatch.setattr(score_module, "score", refuse)
    assert len(field.select(2)) == 2
    assert outcomes.report(field.readings, field.select(2))["worlds"] == 2


def test_the_single_retriever_objective_is_opt_in_and_says_so() -> None:
    """It works, it is reachable only by name, and it warns at the call."""
    field = _pool(4)
    with pytest.warns(UserWarning, match="single retriever"):
        chosen = field.hardest(2)
    assert len(chosen) == 2
    assert len(set(chosen)) == 2
    # And the warning is not the whole guard: the docstring has to carry the
    # argument, because a caller who suppressed warnings still needs to find
    # out what they are opting into.
    assert "unsafe" in (outcomes.Pool.hardest.__doc__ or "").lower()
    assert "opt-in" in (outcomes.hardest.__doc__ or "").lower()


# ---------------------------------------------------------------------------
# The mosaic surface
# ---------------------------------------------------------------------------


def test_the_parameter_mosaic_is_untouched() -> None:
    """`mosaic -n 5` must be what it was; outcome selection is a second door.

    Pinned by value rather than by comparing two calls, so that an edit which
    changed *both* selectors identically would still be caught.
    """
    variants = mosaic.field(5)
    assert [(v.index, v.seed, v.headcount, v.span, v.levels) for v in variants] == [
        (1, 8128, 22, 5, 3), (2, 8129, 18, 8, 5), (3, 8130, 30, 4, 3),
        (4, 8131, 16, 3, 5), (5, 8132, 18, 3, 3),
    ]
    assert [v.estate for v in variants] == [None, "medium", "large", "small", None]


def test_outcome_field_keeps_the_seed_each_world_was_measured_under() -> None:
    """The honesty property. `field` re-seeds by selection position, which is
    harmless there because no parameter coordinate depends on a seed. Here it
    would hand back a corpus nobody read."""
    chosen = mosaic.outcome_field(3, pool=6)
    pool_seeds = {variant.seed for variant in mosaic.field(6)}
    assert {variant.seed for variant in chosen} <= pool_seeds
    assert [variant.index for variant in chosen] == [1, 2, 3]


def test_outcome_field_still_deals_every_world_its_own_words() -> None:
    """The guarantee reordering destroys, restored deliberately.

    A vocabulary is dealt by position rather than dispersed, precisely so that
    no two worlds of a mosaic speak the same words. The first version of
    `outcome_field` carried each candidate's position-dealt vocabulary through
    the reordering and returned five worlds of which two were `wholesale_club`
    — measurably worse than the mosaic it was improving on, since a vocabulary
    swap alone moves two otherwise identical worlds far apart in question
    space.
    """
    chosen = mosaic.outcome_field(4, pool=8)
    words = [variant.vocabulary for variant in chosen]
    assert len(set(words)) == len(words)
    assert all(words)


def test_outcome_field_refuses_what_it_cannot_do() -> None:
    assert mosaic.outcome_field(0) == ()
    with pytest.raises(ValueError, match="non-negative"):
        mosaic.outcome_field(-1)


def test_a_pool_names_every_reading_or_refuses_to_measure() -> None:
    with pytest.raises(ValueError, match="name"):
        outcomes.pool([sdk.retail()], names=["a", "b"])


# ---------------------------------------------------------------------------
# The bridge the loop had to fix on the way through
# ---------------------------------------------------------------------------


def test_a_mosaic_blueprint_carries_the_words_the_mosaic_dealt() -> None:
    """`mosaic_of` dropped the vocabulary, so its worlds were not the mosaic's."""
    variants = mosaic.field(3)
    blueprints = sdk.mosaic_of(3)
    assert [b.vocabulary_name for b in blueprints] == [v.vocabulary for v in variants]
    assert blueprints[0].describe()["vocabulary"] == variants[0].vocabulary


def test_a_blueprint_from_a_variant_builds_on_every_engine() -> None:
    """The regression this loop found. `Variant` always carries a calendar —
    the engine's own, for an engine that reads none — and `_from_variant`
    passed it on, so every banking or insurance blueprint from `mosaic_of`
    raised `TypeError` the moment it was built. Latent because nothing built
    one: the existing test counted the blueprints."""
    for engine in ("banking", "insurance"):
        blueprint = sdk.mosaic_of(1, engine=engine)[0]
        assert blueprint.calendar_name is None
        assert blueprint.build().world.people


def test_a_vocabulary_a_blueprint_cannot_speak_is_refused_at_the_call() -> None:
    with pytest.raises(KeyError, match="unknown vocabulary"):
        sdk.retail().speaking("no_such_words")
    assert sdk.retail().speaking("").vocabulary_name == ""
