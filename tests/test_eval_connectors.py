from __future__ import annotations

import pytest

from worldloom.eval_connectors import bind_eval_connectors
from worldloom.eval_design import (
    EvalShape,
    EvalSpec,
    EvalStepSpec,
    RecordShapeRequirement,
    RequirementKind,
    WorldRequirement,
)


def _spec(*steps: EvalStepSpec, shape: EvalShape | None = None) -> EvalSpec:
    return EvalSpec(
        id="connector-bindings",
        capability="tool_use",
        persona="operator",
        request_template="Do the work.",
        steps=steps,
        requirements=(
            WorldRequirement(
                id="r1",
                kind=RequirementKind.FACT,
                selector={"kind": "synthetic"},
            ),
        ),
        shape=shape or EvalShape(),
    )


def test_jira_abstract_search_binds_to_concrete_tool() -> None:
    spec = _spec(
        EvalStepSpec(
            id="n1",
            capability="search",
            connector="jira",
            entity="bug",
            operation="search",
        )
    )

    binding = bind_eval_connectors(spec)[0]

    assert binding.qualified_tool == "jira.search_issues"
    assert binding.page_size == 50
    assert binding.projection
    assert binding.workflow_field == "status"
    assert "blocked" in binding.workflow_states


def test_shape_can_infer_entity_without_hidden_connector_code() -> None:
    spec = _spec(
        EvalStepSpec(
            id="n1",
            capability="search",
            connector="jira",
            operation="search",
        ),
        shape=EvalShape(
            records=(
                RecordShapeRequirement(
                    connector="jira",
                    entity="bug",
                    custom_fields=300,
                    projection_required=True,
                    maximum_read_bytes=8_000,
                ),
            )
        ),
    )

    binding = bind_eval_connectors(spec, candidate_seed=8128)[0]

    assert binding.entity == "bug"
    assert binding.tool == "search_issues"


def test_teams_and_rovo_bind_without_new_eval_generator_branches() -> None:
    spec = _spec(
        EvalStepSpec(
            id="n1",
            capability="read",
            connector="teams",
            entity="channel_message",
            operation="read",
        ),
        EvalStepSpec(
            id="n2",
            capability="search",
            connector="rovo",
            entity="document",
            operation="search",
            depends_on=("n1",),
        ),
    )

    bindings = bind_eval_connectors(spec)

    assert [binding.qualified_tool for binding in bindings] == [
        "teams.get_channel_message",
        "rovo.search",
    ]
    assert bindings[1].maturity == "product_surface"


def test_teamwork_graph_eap_maturity_survives_binding() -> None:
    spec = _spec(
        EvalStepSpec(
            id="n1",
            capability="search",
            connector="teamwork_graph",
            entity="work_item",
            operation="search",
        )
    )

    binding = bind_eval_connectors(spec)[0]

    assert binding.qualified_tool == "teamwork_graph.query_graph"
    assert binding.maturity == "eap"


def test_eval_generator_cannot_invent_an_unsupported_operation() -> None:
    spec = _spec(
        EvalStepSpec(
            id="n1",
            capability="delete",
            connector="rovo",
            entity="document",
            operation="delete",
            effect="write",
        )
    )

    with pytest.raises(ValueError, match="does not define operation"):
        bind_eval_connectors(spec)
