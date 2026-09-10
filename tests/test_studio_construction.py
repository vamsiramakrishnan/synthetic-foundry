from __future__ import annotations

import pytest

from worldloom.connector_data import ConnectorRecord
from worldloom.enterprise_corpus import source_matches
from worldloom.enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from worldloom.enterprise_specs import (
    ContentAction,
    DestinationRole,
    Operation,
    ScenarioProfile,
    SourceRole,
    WorkflowSpec,
)
from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.evals.dataset import _files
from worldloom.recipe import rebuild
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose
from worldloom.studio.construction import (
    ConstructionPlan,
    bind_query,
    compile_project,
    construct_project,
)
from worldloom.studio.models import ProjectSpec, UseCase
from worldloom.world import World


@pytest.fixture(scope="module")
def base_world():
    return RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))


def _scenario() -> ScenarioProfile:
    workflow = WorkflowSpec(name="critical-review", purpose="Review critical incidents",
        sources=(SourceRole(connector="servicenow", entities=("incident",)),),
        destinations=(DestinationRole(connector="email", entities=("message",),
                      operations=(Operation.DRAFT,), formats=("html",)),),
        content_actions=(ContentAction.SUMMARIZE,), audiences=("operations",),
        prompt_template="Review critical incidents and draft a message.")
    return ScenarioProfile(name="review", industry="retail", company_description="One retailer",
        workflows=(workflow.name,), additional_workflows=(workflow,), connectors=("servicenow", "email"))


def _case(identifier="review", *, selector=None, additional=()) -> UseCase:
    spec = EvalSpec(id="incidents", capability="incident_review", persona="operations",
        request_template="Review critical incidents.", candidate_count=1,
        steps=(EvalStepSpec(id="search", capability="search", connector="servicenow",
                           entity="incident", operation="search"),),
        requirements=(WorldRequirement(id="source", kind=RequirementKind.CONNECTOR,
            selector=selector or {"connector": "servicenow", "entity": "incident", "priority": "1 - Critical"},
            minimum=2), *additional))
    return UseCase(id=identifier, title="Incident review", objective=spec.request_template,
                   scenario=_scenario(), construction=spec)


def _project(world, *cases) -> ProjectSpec:
    return ProjectSpec(company={"engine": "retail", "identity": {"company_name": world.company.name}},
                       seed=world.seed, use_cases=tuple(cases))


def _query() -> PlannedEnterpriseQuery:
    return PlannedEnterpriseQuery(id="query", workflow="critical-review", query="Review incidents",
        dimensions={}, expected_dag=(), generation=GenerationRequirement(process="delivery_work",
            source_requirements=(SourceRequirement(connector="servicenow", entity="incident"),),
            mutation=MutationRequirement(connector="email", entity="message", operation="draft",
                                         output_format="html", preexisting_record=False)))


def test_compile_missing_and_cross_case_conflicts_before_any_generation(base_world):
    missing = _case().model_copy(update={"construction": None})
    plan = compile_project(_project(base_world, missing))
    assert not plan.accepted
    assert "construction_contract_missing" in {f.code for f in plan.findings}

    selector = {"connector": "servicenow", "entity": "incident", "record_id": "CASE-1"}
    contradictory = compile_project(_project(base_world,
        _case("first", selector={**selector, "state": "New"}),
        _case("second", selector={**selector, "state": "Closed"})))
    assert not contradictory.accepted
    assert "conflicting_company_demands" in {f.code for f in contradictory.findings}
    refused = construct_project(contradictory, base_world)
    assert refused.world is base_world
    assert not refused.report.accepted
    assert not refused.candidates


def test_shared_company_constructs_namespaced_demands_and_replays_bytes(base_world, tmp_path):
    plan = compile_project(_project(base_world,
        _case("first"), _case("second", selector={"connector": "servicenow", "entity": "incident", "priority": "2 - High"})))
    assert plan.accepted, plan.findings
    assert ConstructionPlan.model_validate(plan.model_dump(mode="json")) == plan
    result = construct_project(plan, base_world)
    assert result.report.accepted, result.report
    assert result.world.company == base_world.company
    assert result.world.seed == base_world.seed
    assert all(candidate.world is result.world for candidate in result.candidates)
    assert all(candidate.validation.accepted for candidate in result.candidates)
    assert len({candidate.plan.ordinal for candidate in result.candidates}) == 2
    tactics = [key for case in result.report.use_cases for key in case.applied_tactic_ids]
    assert len(tactics) == len(set(tactics)) == 2
    assert any("first:source" in key for key in tactics)
    assert any("second:source" in key for key in tactics)
    result.world.export(tmp_path / "constructed")
    rebuild(result.world.recipe).export(tmp_path / "replayed")
    assert _files(tmp_path / "constructed") == _files(tmp_path / "replayed")


def test_missing_business_fact_remains_rejected_instead_of_minting_an_answer(base_world):
    obligation = WorldRequirement(id="unowned-fact", kind=RequirementKind.FACT,
                                 selector={"kind": "invoice.reconciled_not_generated"})
    result = construct_project(compile_project(_project(base_world, _case(additional=(obligation,)))), base_world)
    assert not result.report.accepted
    assert tuple(result.world.facts) == tuple(base_world.facts)
    assert any(f.requirement_id == "review:unowned-fact" and f.hard for f in result.report.findings)
    assert any(not check.satisfied for check in result.report.use_cases[0].validation.checks)


def test_process_scope_needs_observed_records_and_cannot_be_witnessed_into_existence(base_world):
    from worldloom.process_bindings import BusinessUnit, CompanySpec

    owner = base_world.business_units[0].name
    structure = CompanySpec(name=base_world.company.name, industry="retail", operating_model="centralised",
                            countries=("AU",), bus=(BusinessUnit(name=owner, archetype="product_line"),))
    case = _case().model_copy(update={"owner": owner})
    project = _project(base_world).model_copy(update={"structure": structure, "use_cases": (case,)})
    unbound = compile_project(project)
    assert not unbound.accepted
    assert any(f.code == "unbound_process_scope" for f in unbound.findings)
    scoped = _case(selector={"connector": "servicenow", "entity": "incident", "business_unit": owner,
                             "process": "supplier_replenishment"}).model_copy(update={"owner": owner})
    plan = compile_project(project.model_copy(update={"use_cases": (scoped,)}))
    assert plan.accepted, plan.findings
    result = construct_project(plan, base_world)
    assert not result.report.accepted
    assert result.world is base_world
    assert any(f.code == "process_evidence_missing" for f in result.report.findings)


def test_query_binding_constrains_real_source_selection_and_detects_conflicts(base_world):
    from worldloom.predicates import Predicate

    selector = {"connector": "servicenow", "entity": "incident", "business_unit": "Grocery",
                "process": "supplier_replenishment"}
    plan = compile_project(_project(base_world, _case(selector=selector)))
    query = bind_query(plan, "review", _query())
    source = query.generation.source_requirements[0]
    assert source.minimum == 2
    assert query.id != _query().id
    right = ConnectorRecord(id="right", connector="servicenow", entity="incident", external_id="INC1",
                            title="Delayed replenishment", fields={"business_unit": "Grocery", "process": "supplier_replenishment"})
    wrong_bu = right.model_copy(update={"id": "wrong", "fields": {**right.fields, "business_unit": "Online"}})
    wrong_process = right.model_copy(update={"id": "other", "fields": {**right.fields, "process": "invoice_reconciliation"}})
    assert source_matches(source, right)
    assert not source_matches(source, wrong_bu)
    assert not source_matches(source, wrong_process)
    conflicting_source = source.model_copy(update={"predicate": Predicate.equalities({"business_unit": "Online"})})
    conflicting = _query().model_copy(update={"generation": _query().generation.model_copy(
        update={"source_requirements": (conflicting_source,)})})
    with pytest.raises(ValueError, match="contradicts existing predicate"):
        bind_query(plan, "review", conflicting)


def test_different_company_or_seed_cannot_receive_another_projects_construction(base_world):
    plan = compile_project(_project(base_world, _case()))
    with pytest.raises(ValueError, match="company identity disagree"):
        construct_project(plan.model_copy(update={"company_seed": plan.company_seed + 1}), base_world)


def test_every_workflow_source_must_have_an_explicit_hard_construction_contract(base_world):
    case = _case()
    assert case.scenario is not None
    workflow = case.scenario.additional_workflows[0]
    amended = workflow.model_copy(update={"sources": (*workflow.sources, SourceRole(connector="email", entities=("thread",)))})
    case = case.model_copy(update={"scenario": case.scenario.model_copy(update={"additional_workflows": (amended,)})})
    plan = compile_project(_project(base_world, case))
    assert not plan.accepted
    assert any(f.code == "workflow_source_unbound" and "email.thread" in f.detail for f in plan.findings)


def test_loaded_snapshot_restores_verified_generator_state_without_reminting(base_world, tmp_path):
    from dataclasses import replace

    from worldloom.studio.construction import restore_generator

    built = base_world.compile()
    built.export(tmp_path / "snapshot")
    loaded = World.load(tmp_path / "snapshot")
    assert loaded._minter is None
    restored = restore_generator(loaded)
    assert restored._minter is not None
    restored.export(tmp_path / "restored")
    assert _files(tmp_path / "snapshot") == _files(tmp_path / "restored")
    plan = compile_project(_project(base_world, _case()))
    assert construct_project(plan, loaded).report.accepted
    tampered = replace(loaded, company=loaded.company.model_copy(update={"name": "Unrecorded rename"}))
    with pytest.raises(ValueError, match="differs from the cached construction snapshot"):
        restore_generator(tampered)
