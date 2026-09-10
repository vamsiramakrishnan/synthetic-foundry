"""Compile company obligations before building, then construct one shared World.

The enterprise workflow grammar and the eval-first design grammar have distinct
semantics. An explicit EvalSpec supplies the construction contract; a workflow
title is never translated into invented facts. Connector predicates bind the
same obligations into the eventual enterprise query's actual evidence pool.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import model_validator

from ..eval_candidates import (
    CandidateValidation,
    GeneratedCandidate,
    check_requirement,
    validate_candidate,
)
from ..eval_demands import DemandSet, compile_demands
from ..eval_design import (
    CandidatePlan,
    EvalSpec,
    RequirementKind,
    WorldRequirement,
    design_digest,
)
from ..eval_interventions import construct_candidate
from ..models import Model
from ..providers import digest

if TYPE_CHECKING:
    from ..enterprise_queries import PlannedEnterpriseQuery
    from ..world import World
    from .models import ProjectSpec, UseCase
    from .service import Studio


class ConstructionIssue(Model):
    use_case_id: str
    code: str
    detail: str
    requirement_id: str = ""
    hard: bool = True


class UseCaseConstruction(Model):
    use_case_id: str
    spec: EvalSpec
    demands: DemandSet
    owner: str = ""
    lob: str = ""
    activities: tuple[str, ...] = ()

    @property
    def scoped(self) -> bool:
        return bool(self.owner or self.lob or self.activities)


class ConstructionPlan(Model):
    schema_version: Literal["worldloom.company-construction/v1"] = "worldloom.company-construction/v1"
    company_seed: int
    company_name: str
    use_cases: tuple[UseCaseConstruction, ...]
    findings: tuple[ConstructionIssue, ...] = ()
    accepted: bool

    @model_validator(mode="after")
    def _verdict(self) -> ConstructionPlan:
        if self.accepted != (bool(self.use_cases) and not any(item.hard for item in self.findings)):
            raise ValueError("construction plan acceptance disagrees with its findings")
        return self

    @property
    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))


class UseCaseConstructionReport(Model):
    use_case_id: str
    plan: CandidatePlan
    validation: CandidateValidation
    applied_tactic_ids: tuple[str, ...] = ()


class CompanyConstructionReport(Model):
    plan_digest: str
    accepted: bool
    use_cases: tuple[UseCaseConstructionReport, ...] = ()
    findings: tuple[ConstructionIssue, ...] = ()


@dataclass(frozen=True)
class CompanyConstruction:
    world: World
    report: CompanyConstructionReport
    candidates: tuple[GeneratedCandidate, ...] = ()


def construct_company(studio: Studio, spec: ProjectSpec, plan: ConstructionPlan) -> tuple[CompanyConstruction, Path]:
    """Shared construction path for inspection datasets and calibrated runs."""
    if not plan.accepted:
        raise ValueError("resolve construction requirements before building the company")
    base, location = studio.snapshot(spec)
    if spec.structure is not None:
        from ..process_bindings.ownership import materialize_owners
        base = materialize_owners(restore_generator(base), spec.structure,
                                 formed_at=spec.retail_process.start if spec.retail_process else None)
    if spec.retail_process is not None:
        from ..retail_replenishment import build_retail_process
        base = build_retail_process(restore_generator(base), spec.retail_process)
    return construct_project(plan, base), location


def _qualified_spec(case: UseCase) -> EvalSpec:
    """Namespace the tactic identity, which otherwise collides across use cases."""
    assert case.construction is not None
    spec = case.construction
    prefix = f"{case.id}:"
    return spec.model_copy(update={
        "id": prefix + spec.id,
        "requirements": tuple(r.model_copy(update={"id": prefix + r.id}) for r in spec.requirements),
        "steps": tuple(s.model_copy(update={"id": prefix + s.id,
                        "depends_on": tuple(prefix + key for key in s.depends_on)}) for s in spec.steps),
    })


def _source_contracts(spec: EvalSpec) -> dict[tuple[str, str], tuple[WorldRequirement, ...]]:
    grouped: dict[tuple[str, str], list[WorldRequirement]] = {}
    for requirement in spec.requirements:
        if requirement.kind is not RequirementKind.CONNECTOR or not requirement.hard:
            continue
        connector, entity = requirement.selector.get("connector"), requirement.selector.get("entity")
        if isinstance(connector, str) and isinstance(entity, str):
            grouped.setdefault((connector, entity), []).append(requirement)
    return {key: tuple(items) for key, items in sorted(grouped.items())}


def _scope_findings(case: UseCase, spec: EvalSpec) -> list[ConstructionIssue]:
    findings: list[ConstructionIssue] = []
    sources = [r for r in spec.requirements if r.kind is RequirementKind.CONNECTOR and r.hard]
    if (case.owner or case.lob or case.activities) and not sources:
        findings.append(ConstructionIssue(use_case_id=case.id, code="scope_without_evidence",
            detail="business-unit, LOB and process ownership need hard connector evidence requirements"))
    covered_activities: set[str] = set()
    for requirement in sources:
        selector = requirement.selector
        missing: list[str] = []
        if case.owner and selector.get("business_unit") != case.owner:
            missing.append(f"business_unit={case.owner!r}")
        if case.lob and selector.get("lob") != case.lob:
            missing.append(f"lob={case.lob!r}")
        if case.activities:
            activity = selector.get("activity_id")
            if isinstance(activity, str) and activity in case.activities:
                covered_activities.add(activity)
            else:
                missing.append("activity_id naming one of the use case's declared activities")
        if missing:
            findings.append(ConstructionIssue(use_case_id=case.id, requirement_id=requirement.id,
                code="unbound_process_scope", detail="connector selector needs " + ", ".join(missing)))
    missing_activities = set(case.activities) - covered_activities
    if missing_activities:
        findings.append(ConstructionIssue(use_case_id=case.id, code="uncovered_activities",
            detail="no hard connector requirement covers activities: " + ", ".join(sorted(missing_activities))))
    return findings


def compile_project(project: ProjectSpec) -> ConstructionPlan:
    """Validate explicit designs and cross-use-case conflicts without any World.

    A single source pool cannot mean two incompatible selectors. Such a design
    needs two source roles or two use cases, rather than an implicit OR that
    weakens both requirements when the task is compiled.
    """
    from ..company import from_document
    from ..enterprise_specs import apply_scenario_profile, builtin_registry

    company = from_document(project.company)
    assert company.identity is not None
    cases: list[UseCaseConstruction] = []
    findings: list[ConstructionIssue] = []
    for case in sorted(project.use_cases, key=lambda item: item.id):
        if case.construction is None:
            findings.append(ConstructionIssue(use_case_id=case.id, code="construction_contract_missing",
                detail="define an explicit EvalSpec construction contract for this use case"))
            continue
        spec = _qualified_spec(case)
        try:
            demands = compile_demands(spec)
        except ValueError as error:
            findings.append(ConstructionIssue(use_case_id=case.id, code="conflicting_demands", detail=str(error)))
            continue
        findings.extend(_scope_findings(case, spec))
        sources = _source_contracts(spec)
        for requirement in spec.requirements:
            if requirement.hard and requirement.kind is RequirementKind.CONNECTOR and not (
                isinstance(requirement.selector.get("connector"), str)
                and isinstance(requirement.selector.get("entity"), str)
            ):
                findings.append(ConstructionIssue(use_case_id=case.id, requirement_id=requirement.id,
                    code="source_contract_incomplete", detail="hard connector requirements name connector and entity"))
        for pair, requirements in sources.items():
            if len({digest(r.selector) for r in requirements}) != 1:
                findings.append(ConstructionIssue(use_case_id=case.id, code="ambiguous_source_contract",
                    detail=f"{pair[0]}.{pair[1]} has incompatible selectors; split its source roles or use cases"))
        if case.scenario is None:
            findings.append(ConstructionIssue(use_case_id=case.id, code="workflow_missing",
                detail="a construction contract also needs an executable enterprise workflow"))
        else:
            registry = apply_scenario_profile(builtin_registry(), case.scenario)
            required_pairs = {(role.connector, entity) for workflow in registry.workflows.values()
                              for role in workflow.sources for entity in role.entities}
            for connector, entity in sorted(required_pairs - sources.keys()):
                findings.append(ConstructionIssue(use_case_id=case.id, code="workflow_source_unbound",
                    detail=f"workflow source {connector}.{entity} has no hard construction requirement"))
        cases.append(UseCaseConstruction(use_case_id=case.id, spec=spec, demands=demands,
                     owner=case.owner, lob=case.lob, activities=case.activities))
    if cases:
        # Shared-world compatibility must be checked across contracts, before
        # any one case has had a chance to mint the state the next contradicts.
        combined = cases[0].spec.model_copy(update={
            "id": "studio:company-obligations",
            "steps": tuple(step for case in cases for step in case.spec.steps),
            "requirements": tuple(r for case in cases for r in case.spec.requirements),
        })
        try:
            compile_demands(combined)
        except ValueError as error:
            findings.append(ConstructionIssue(use_case_id="", code="conflicting_company_demands", detail=str(error)))
    else:
        findings.append(ConstructionIssue(use_case_id="", code="construction_cases_missing",
            detail="at least one executable use-case construction contract is required"))
    return ConstructionPlan(company_seed=project.seed, company_name=company.identity.company_name,
                            use_cases=tuple(cases), findings=tuple(findings),
                            accepted=bool(cases) and not any(item.hard for item in findings))


def _candidate_plan(case: UseCaseConstruction, *, seed: int, ordinal: int) -> CandidatePlan:
    return CandidatePlan(eval_spec_id=case.spec.id, ordinal=ordinal, seed=seed,
                         requirements=case.spec.requirements, shape=case.spec.shape,
                         design_digest=design_digest(case.spec))


def restore_generator(world: World) -> World:
    """Restore cached generation state only after an exact offline replay check.

    Narrated/native corpora that need additional replay stages refuse here;
    copying a minter from a merely similar world could silently remint IDs.
    The foundry calls this on its pre-narration construction snapshot.
    """
    from dataclasses import replace

    from ..evals.calibration import world_digest
    from ..recipe import rebuild

    if world._minter is not None:
        return world
    restored = rebuild(world.recipe, ledger=tuple(world.ledger), actor_ledger=tuple(world.actor_ledger))
    if world.artifact_irs:
        restored = restored.compile()
    if restored._minter is None or world_digest(restored) != world_digest(world):
        raise ValueError("replayed company differs from the cached construction snapshot; generator state cannot be restored")
    return replace(world, _minter=restored._minter, _roles=restored._roles,
                   _annual_revenue=restored._annual_revenue, _archetype=restored._archetype)


def construct_project(plan: ConstructionPlan, base: World) -> CompanyConstruction:
    """Apply existing recipe tactics once, retaining one company and one seed.

    Scoped business records must come from a domain generator or an operational
    episode. A search witness may make a connector fixture, but copying an
    owner or activity string into it cannot establish process evidence.
    """
    if base.seed != plan.company_seed or base.company.name != plan.company_name:
        raise ValueError("construction plan and base company identity disagree")
    findings = list(plan.findings)
    if not plan.accepted:
        return CompanyConstruction(base, CompanyConstructionReport(plan_digest=plan.digest,
            accepted=False, findings=tuple(findings)))
    generated_units = {unit.name for unit in base.business_units}
    for case in plan.use_cases:
        for requirement in case.spec.requirements:
            scoped = case.scoped or bool({"business_unit", "business_unit_id", "activity_id", "lob", "process"}
                                         & requirement.selector.keys())
            if requirement.kind is RequirementKind.CONNECTOR and requirement.hard and scoped:
                owner = requirement.selector.get("business_unit")
                if owner and owner not in generated_units:
                    findings.append(ConstructionIssue(use_case_id=case.use_case_id, requirement_id=requirement.id,
                        code="business_unit_not_generated", detail=f"business unit {owner!r} is absent from the generated company"))
                check = check_requirement(requirement, base)
                if not check.satisfied:
                    findings.append(ConstructionIssue(use_case_id=case.use_case_id, requirement_id=requirement.id,
                        code="process_evidence_missing", detail=(
                            f"scoped process evidence needs {check.required} records; observed {check.observed}. "
                            "Generate the owning domain/process episode before construction; generic witnesses cannot satisfy ownership.")))
    if any(item.hard for item in findings):
        return CompanyConstruction(base, CompanyConstructionReport(plan_digest=plan.digest,
            accepted=False, findings=tuple(findings)))
    world = restore_generator(base)
    applied: dict[str, tuple[str, ...]] = {}
    for ordinal, case in enumerate(plan.use_cases):
        candidate_plan = _candidate_plan(case, seed=plan.company_seed, ordinal=ordinal)
        try:
            result = construct_candidate(case.spec, candidate_plan, world)
        except ValueError as error:
            findings.append(ConstructionIssue(use_case_id=case.use_case_id, code="construction_refused", detail=str(error)))
            continue
        world = result.candidate.world
        applied[case.use_case_id] = result.applied_tactic_ids
        hard_ids = {r.id for r in case.spec.requirements if r.hard}
        findings.extend(ConstructionIssue(use_case_id=case.use_case_id,
            requirement_id=item.requirement_id, code=item.code, detail=item.detail,
            hard=item.requirement_id in hard_ids or item.requirement_id.startswith("demand:"))
            for item in result.findings)
    # Later tactics can change earlier evidence. Every admission below reads
    # the completed shared World rather than trusting an intermediate verdict.
    candidates: list[GeneratedCandidate] = []
    reports: list[UseCaseConstructionReport] = []
    for ordinal, case in enumerate(plan.use_cases):
        candidate_plan = _candidate_plan(case, seed=plan.company_seed, ordinal=ordinal)
        validation = validate_candidate(candidate_plan, case.spec, world)
        candidates.append(GeneratedCandidate(plan=candidate_plan, world=world, validation=validation))
        reports.append(UseCaseConstructionReport(use_case_id=case.use_case_id,
            plan=candidate_plan, validation=validation, applied_tactic_ids=applied.get(case.use_case_id, ())))
    accepted = all(item.validation.accepted for item in reports) and not any(item.hard for item in findings)
    return CompanyConstruction(world, CompanyConstructionReport(plan_digest=plan.digest,
        accepted=accepted, use_cases=tuple(reports), findings=tuple(findings)), tuple(candidates))


def bind_query(plan: ConstructionPlan, use_case_id: str, query: PlannedEnterpriseQuery) -> PlannedEnterpriseQuery:
    """Constrain the actual query sources with the exact construction predicates."""
    from ..predicates import FieldPredicate, Predicate, PredicateOp

    if not plan.accepted:
        raise ValueError("cannot bind queries from a rejected construction plan")
    case = next((item for item in plan.use_cases if item.use_case_id == use_case_id), None)
    if case is None:
        raise ValueError(f"unknown construction use case {use_case_id!r}")
    contracts = _source_contracts(case.spec)
    sources = []
    for source in query.generation.source_requirements:
        requirements = contracts.get((source.connector, source.entity))
        if not requirements:
            raise ValueError(f"unbound construction source {source.connector}.{source.entity}")
        predicate = source.predicate or Predicate()
        fields = {item.field: item for item in predicate.where}
        selector = {key: value for key, value in requirements[0].selector.items()
                    if key not in {"connector", "entity"}}
        for key, value in sorted(selector.items()):
            clause = FieldPredicate(field=key, value=value)
            previous = fields.get(key)
            if previous is not None and (previous.op is not PredicateOp.EQ or previous.value != value):
                raise ValueError(f"construction source contradicts existing predicate for {key}")
            fields[key] = clause
        bound = predicate.model_copy(update={"where": tuple(fields[key] for key in sorted(fields))})
        sources.append(source.model_copy(update={"predicate": bound,
                       "minimum": max(source.minimum, *(r.minimum for r in requirements))}))
    generation = query.generation.model_copy(update={"source_requirements": tuple(sources)})
    key = digest(["studio-construction-query/v1", query.id, plan.digest, use_case_id,
                  generation.model_dump(mode="json")])
    return query.model_copy(update={"id": key, "generation": generation,
        "dimensions": {**query.dimensions, "construction_contract": plan.digest,
                       "construction_use_case": use_case_id}})


__all__ = ["ConstructionIssue", "ConstructionPlan", "UseCaseConstruction", "CompanyConstructionReport",
           "CompanyConstruction", "compile_project", "construct_project", "bind_query", "restore_generator"]
