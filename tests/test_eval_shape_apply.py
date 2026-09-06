from __future__ import annotations

from worldloom.connector_definition import builtin_connector_definitions
from worldloom.eval_design import EvalShape, RecordShapeRequirement
from worldloom.eval_shape import shape_connector_definitions


def test_eval_shape_widens_only_the_requested_connector_entity() -> None:
    base = builtin_connector_definitions()
    shape = EvalShape(
        records=(
            RecordShapeRequirement(
                connector="jira",
                entity="bug",
                total_fields=320,
                custom_fields=300,
            ),
        )
    )

    widened, applications = shape_connector_definitions(shape, base, seed=8128)

    assert base["jira"].fields_for("bug") == ()
    assert len(widened["jira"].fields_for("bug")) == 300
    assert widened["jira"].fields_for("story") == ()
    assert widened["servicenow"] == base["servicenow"]
    assert applications[0].added_custom_fields == 300


def test_eval_shape_replays_the_same_manifest_for_the_same_candidate_seed() -> None:
    base = builtin_connector_definitions()
    shape = EvalShape(
        records=(
            RecordShapeRequirement(
                connector="jira",
                entity="bug",
                custom_fields=300,
            ),
        )
    )

    left, _ = shape_connector_definitions(shape, base, seed=42)
    right, _ = shape_connector_definitions(shape, base, seed=42)
    other, _ = shape_connector_definitions(shape, base, seed=43)

    assert left["jira"].fields_for("bug") == right["jira"].fields_for("bug")
    assert left["jira"].fields_for("bug") != other["jira"].fields_for("bug")
