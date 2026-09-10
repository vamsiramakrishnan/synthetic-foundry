"""An inspectable retailer with three processes over one physical case ledger."""

from __future__ import annotations

from datetime import UTC, datetime

from ..enterprise_specs import (
    ContentAction,
    DestinationRole,
    Operation,
    ScenarioProfile,
    SourceRole,
    WorkflowSpec,
)
from ..eval_design import EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement
from ..process_bindings import compile_company
from ..retail_replenishment import PROCESSES, RetailProcess, RetailProcessScope
from .models import ProjectSpec, UseCase


def pilot_project(name: str = "Northstar Retail", *, seed: int = 8128, count: int = 12) -> ProjectSpec:
    """Reuse the company preset and bind declared process ownership to records.

    Each use case observes a different stage of the same stock/order/receipt
    cases. The invoice stage preserves both clean controls and billed price
    exceptions; it does not claim that a credit note or payment occurred.
    """
    from .service import preset

    base = preset("retail", name)
    assert base.structure is not None
    preferred_owner = base.structure.bus[0].name
    rows = compile_company(base.structure).rows
    # Resolve the authored catalogue bindings instead of assigning Finance to
    # every money task. This retailer's AP execution belongs to Supply Chain;
    # payment-run approval is a separate Group Finance activity and not built.
    activities = dict(zip(PROCESSES, ("f2r.02", "p2p.04", "p2p.09"), strict=True))
    scopes = []
    for process in PROCESSES:
        candidates = sorted((row for row in rows if row.activity_id == activities[process]),
                            key=lambda row: (row.owner_bu != preferred_owner, row.owner_bu, row.country))
        if not candidates:
            raise ValueError(f"retail pilot cannot resolve process {activities[process]}")
        scopes.append(RetailProcessScope(process=process, business_unit=candidates[0].owner_bu,
                                         activity_id=activities[process]))
    config = RetailProcess(scopes=tuple(scopes), start=datetime(2026, 3, 1, tzinfo=UTC), max_cases=48)
    cases = tuple(_use_case(scope, count=count) for scope in scopes)
    return ProjectSpec.model_validate({**base.model_dump(mode="json"), "seed": seed,
        "use_cases": [case.model_dump(mode="json") for case in cases], "retail_process": config.model_dump(mode="json"),
        "pool_size": 24, "planning_budget": 512, "max_batches": 12, "max_per_case": 6})


def _use_case(scope: RetailProcessScope, *, count: int) -> UseCase:
    purposes = {
        "inventory_exception": "Review lost demand and the inventory-position replenishment order it caused",
        "supplier_replenishment": "Trace the supplier order to its actual two-tick goods receipt and stock movement",
        "invoice_reconciliation": "Reconcile the invoice with the contracted price and actual receipt, retaining clean controls and reporting price exceptions",
    }
    sources = (SourceRole(connector="jira", entities=("issue",)),
               SourceRole(connector="servicenow", entities=("incident",)),
               SourceRole(connector="email", entities=("thread",)))
    workflow = WorkflowSpec(name=scope.process, purpose=purposes[scope.process], process=scope.process,
        sources=sources,
        destinations=(DestinationRole(connector="email", entities=("message",),
                                      operations=(Operation.DRAFT,), formats=("html",)),),
        content_actions=(ContentAction.RECONCILE, ContentAction.GENERATE), audiences=("retail_operations",),
        prompt_template=("For {company}, {purpose}. Use {sources}; join case_id and inspect source observation histories "
                         "and upstream_event_ids. Preserve each stage's observation cutoff. {action_instruction} "
                         "{output_label} in {destination}, then {verification_instruction}.{failure_instruction}"))
    scenario = ScenarioProfile(name=scope.process, industry="retail",
        company_description="One declared retailer with connected inventory, supplier receipt and invoice evidence.",
        workflows=(workflow.name,), connectors=("email", "jira", "servicenow"), additional_workflows=(workflow,))
    scenario = scenario.model_copy(update={"coverage": scenario.coverage.model_copy(update={"failures": ("none", "partial_write")})})
    selector = {"process": scope.process, "business_unit": scope.business_unit, "activity_id": scope.activity_id}
    if scope.lob:
        selector["lob"] = scope.lob
    requirements = tuple(WorldRequirement(id=f"source-{source.connector}", kind=RequirementKind.CONNECTOR,
        selector={**selector, "connector": source.connector, "entity": source.entities[0]}) for source in sources)
    steps = tuple(EvalStepSpec(id=f"read-{source.connector}", capability="search",
                              connector=source.connector, entity=source.entities[0], operation="search") for source in sources)
    design = EvalSpec(id="connected-retail", capability="evidence_reconciliation", persona="retail_operations",
        request_template=purposes[scope.process], requirements=requirements,
        steps=(*steps, EvalStepSpec(id="reconcile", capability="reconcile", effect="transform",
                                    depends_on=tuple(step.id for step in steps))), candidate_count=1)
    return UseCase(id=scope.process.replace("_", "-"), title=scope.process.replace("_", " ").capitalize(),
        objective=purposes[scope.process], owner=scope.business_unit, activities=(scope.activity_id,), count=count,
        scenario=scenario, construction=design)


__all__ = ["pilot_project"]
