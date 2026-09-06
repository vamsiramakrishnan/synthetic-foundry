from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.eval_metrics import DifficultyCalibrator, features_for


def _spec() -> EvalSpec:
    return EvalSpec(
        id="EVAL-METRICS",
        capability="cross_system_remediation",
        persona="operator",
        request_template="Find the incident and create the missing remediation.",
        steps=(
            EvalStepSpec(id="find", capability="find", connector="servicenow"),
            EvalStepSpec(
                id="create",
                capability="create",
                connector="jira",
                depends_on=("find",),
                effect="write",
            ),
            EvalStepSpec(
                id="verify",
                capability="verify",
                connector="jira",
                depends_on=("create",),
                effect="verify",
            ),
        ),
        requirements=(
            WorldRequirement(
                id="snow",
                kind=RequirementKind.CONNECTOR,
                selector={"connector": "servicenow"},
            ),
            WorldRequirement(
                id="revisions",
                kind=RequirementKind.REVISION_CHAIN,
                selector={"artifact_type": "incident_review"},
                minimum=3,
            ),
            WorldRequirement(id="acl", kind=RequirementKind.PERMISSION),
            WorldRequirement(id="time", kind=RequirementKind.TEMPORAL_RELATION),
            WorldRequirement(id="noise", kind=RequirementKind.DISTRACTOR),
        ),
    )


def test_features_are_sliceable_and_structural() -> None:
    features = features_for(_spec())

    assert features.step_count == 3
    assert features.dag_depth == 3
    assert features.connector_count == 2
    assert features.write_steps == 1
    assert features.verify_steps == 1
    assert features.revision_depth == 3
    assert features.permission_requirements == 1
    assert features.temporal_requirements == 1
    assert features.distractor_requirements == 1


def test_difficulty_is_calibrated_from_observed_passes() -> None:
    spec = _spec()
    calibrator = DifficultyCalibrator()

    initial = calibrator.estimate("agent-a", spec)
    assert initial.predicted_pass_rate == 0.5

    for passed in (False, False, False, True):
        calibrator.observe("agent-a", spec, passed=passed)

    estimate = calibrator.estimate("agent-a", spec)
    assert estimate.trials == 4
    assert estimate.successes == 1
    assert estimate.predicted_pass_rate == 2 / 6
    assert estimate.difficulty == 1 - (2 / 6)
