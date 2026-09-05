from worldloom.eval_demands import DemandKind, compile_demands
from worldloom.eval_design import EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement


def _spec() -> EvalSpec:
    return EvalSpec(
        id="EVALSPEC-DEMANDS",
        capability="incident_resolution",
        persona="operator",
        request_template="Find the incident and create the remediation.",
        steps=(
            EvalStepSpec(id="find", capability="search", connector="servicenow", operation="search"),
            EvalStepSpec(
                id="create",
                capability="create_issue",
                connector="jira",
                operation="create",
                effect="write",
                depends_on=("find",),
            ),
        ),
        requirements=(
            WorldRequirement(
                id="incidents-a",
                kind=RequirementKind.CONNECTOR,
                selector={"connector": "servicenow", "priority": "P1"},
                minimum=1,
            ),
            WorldRequirement(
                id="incidents-b",
                kind=RequirementKind.CONNECTOR,
                selector={"connector": "servicenow", "priority": "P1"},
                minimum=3,
            ),
            WorldRequirement(
                id="rca",
                kind=RequirementKind.ARTIFACT,
                selector={"artifact_type": "incident_rca"},
            ),
        ),
    )


def test_compile_demands_is_pre_data_and_deterministic() -> None:
    spec = _spec()
    left = compile_demands(spec)
    right = compile_demands(spec)

    assert left == right
    assert left.eval_spec_id == spec.id
    assert all("INC-" not in repr(demand.selector) for demand in left.demands)


def test_equivalent_requirements_merge_to_strongest_cardinality() -> None:
    demands = compile_demands(_spec()).demands
    incident = next(
        demand
        for demand in demands
        if demand.kind == DemandKind.SEARCH and demand.source_requirement_ids
    )

    assert incident.minimum == 3
    assert incident.source_requirement_ids == ("incidents-a", "incidents-b")


def test_task_dag_implies_search_and_mutation_demands() -> None:
    demands = compile_demands(_spec()).demands

    assert any(
        demand.kind == DemandKind.SEARCH
        and demand.source_step_ids == ("find",)
        and demand.selector["connector"] == "servicenow"
        for demand in demands
    )
    assert any(
        demand.kind == DemandKind.MUTATION
        and demand.source_step_ids == ("create",)
        and demand.selector["connector"] == "jira"
        for demand in demands
    )


def test_hard_requirement_dominates_equivalent_soft_requirement() -> None:
    spec = EvalSpec(
        id="EVALSPEC-HARD-MERGE",
        capability="retrieval",
        persona="analyst",
        request_template="Find the workbook.",
        steps=(EvalStepSpec(id="find", capability="find"),),
        requirements=(
            WorldRequirement(
                id="soft",
                kind=RequirementKind.ARTIFACT,
                selector={"artifact_type": "finance_workbook"},
                hard=False,
            ),
            WorldRequirement(
                id="hard",
                kind=RequirementKind.ARTIFACT,
                selector={"artifact_type": "finance_workbook"},
                hard=True,
            ),
        ),
    )

    demand = next(d for d in compile_demands(spec).demands if d.source_requirement_ids)
    assert demand.hard is True
    assert demand.source_requirement_ids == ("hard", "soft")
