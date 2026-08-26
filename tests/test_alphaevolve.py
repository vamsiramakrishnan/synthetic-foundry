"""AlphaEvolve is a bounded search plane, never a second source of truth."""

from __future__ import annotations

from evals.alphaevolve.portfolio import (
    _bind_resource,
    local_scorecard,
    promotion_report,
    readiness_report,
    shadow_report,
)
from evals.alphaevolve.registry import LEVERS, registry_document
from evals.alphaevolve.sandbox import INVALID_SCORE, validate_block
from evals.alphaevolve.variation_policy import evaluate


def test_current_seed_is_complete_but_leaves_axis_coverage_on_the_table() -> None:
    first = evaluate.score_candidate(evaluate.INITIAL_PROGRAM_CODE)
    second = evaluate.score_candidate(evaluate.INITIAL_PROGRAM_CODE)

    assert first["error"] is None
    assert first["score"] == second["score"]
    assert first["optimal"] < first["case_count"]
    assert first["promotion_passed"] is False


def test_reviewed_axis_first_policy_beats_seed_and_all_independent_gates() -> None:
    seed = evaluate.score_candidate(evaluate.INITIAL_PROGRAM_CODE)
    search = evaluate.score_candidate(evaluate.INTEGRATED_PROGRAM_CODE)
    holdout = evaluate.score_holdout(evaluate.INTEGRATED_PROGRAM_CODE)
    adversarial = evaluate.score_adversarial(evaluate.INTEGRATED_PROGRAM_CODE)

    assert search["score"] > seed["score"]
    for result in (search, holdout, adversarial):
        assert result["error"] is None
        assert result["optimal"] == result["case_count"]
        assert result["promotion_passed"] is True
        assert result["lexicographically_beats_baseline"] is True


def test_inadmissible_shortcut_receives_a_hard_penalty() -> None:
    candidate = evaluate.INITIAL_PROGRAM_CODE.replace(
        "    admissible = [option for option in options if option.get(\"admissible\")]",
        "    admissible = list(options)",
    )
    result = evaluate.score_adversarial(candidate)

    assert result["score"] < 0
    assert "inadmissible" in result["error"]


def test_candidate_sandbox_rejects_effects_and_reflection() -> None:
    for block, message in (
        ("import os\ndef choose(state, options):\n    return 'x'", "blocked import: os"),
        ("def choose(state, options):\n    return getattr(state, 'x')", "blocked name: getattr"),
    ):
        try:
            validate_block(block)
        except ValueError as exc:
            assert str(exc) == message
        else:
            raise AssertionError(f"sandbox admitted {block!r}")


def test_invalid_controller_envelope_is_data_not_an_exception() -> None:
    result = evaluate.evaluation_function({"content": {"files": []}})
    score = result["scores"]["scores"][0]

    assert score["metric"] == evaluate.METRIC_NAME
    assert score["score"] == INVALID_SCORE
    assert "invalid envelope" in result["insights"]["insights"][0]["text"]


def test_registry_keeps_truth_and_admission_oracles_immutable() -> None:
    document = registry_document()
    mutable = {lever.id for lever in LEVERS if lever.mutable}
    protected = {lever.id for lever in LEVERS if not lever.mutable}

    assert document["schema"] == "worldloom.alphaevolve-levers/v1"
    assert mutable == {"child-variation-order"}
    assert protected == {
        "coherence-validation",
        "recipe-replay",
        "fleet-fitness",
        "fact-and-generation-ledgers",
    }


def test_local_reports_distinguish_readiness_shadow_and_promotion() -> None:
    scorecard = local_scorecard()
    readiness = readiness_report()
    promotion = promotion_report()
    shadow = shadow_report("variation-policy")

    assert scorecard["all_gates_pass"] is True
    assert readiness["experiments"]["variation-policy"]["ready"] is True
    assert promotion["experiments"]["variation-policy"]["managed_winner"] is False
    assert "no realism" in promotion["experiments"]["variation-policy"]["claim"]
    assert shadow["mutated_production"] is False


def test_managed_resource_binding_requires_the_full_resource_name() -> None:
    class Experiment:
        session_name = ""
        experiment_name = ""

    experiment = Experiment()
    resource = (
        "projects/p/locations/global/collections/c/engines/e/sessions/s/"
        "alphaEvolveExperiments/x"
    )
    _bind_resource(experiment, resource)
    assert experiment.session_name.endswith("/sessions/s")
    assert experiment.experiment_name == resource

    try:
        _bind_resource(experiment, "x")
    except SystemExit as exc:
        assert "full resource name" in str(exc)
    else:
        raise AssertionError("short experiment id was accepted")
