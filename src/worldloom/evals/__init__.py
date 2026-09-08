"""Canonical eval-first SDK.

New code imports from ``worldloom.evals``. The historical top-level ``eval_*``
modules remain implementation/compatibility paths for this release while their
bodies move under this package in small slices.
"""

from ..eval_candidates import CandidateBuilder, GeneratedCandidate
from ..eval_demands import DemandSet
from ..eval_design import (
    CandidatePlan,
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from ..eval_execution import emulator_executor
from ..eval_instances import EvalInstance
from ..eval_interventions import (
    ConstructionFinding,
    ConstructionResult,
    construct_candidate,
)
from ..eval_search import AdaptiveCandidateBuilder, CandidateContext, CandidateFeedback
from ..eval_tactics import TacticPlan
from ..eval_witnesses import ConstructionRefused
from .builders import candidate_builder
from .campaign import CampaignRun, EvalCampaign
from .coverage import CoverageReport
from .coverage import report as coverage_report
from .difficulty import RequestFeatures
from .difficulty import features_for as request_features

# `intent_table`, not `intents`: this package has a submodule named
# `intents`, and binding a function to that name here shadows it, so
# `from worldloom.evals import intents` would hand back the function and
# `intents.applicable` would fail with an attribute error on a cache wrapper.
# The same hazard is why `coverage` and `difficulty` are exported under
# `coverage_report` and `request_features` rather than their own names.
from .intents import Intent, applicable, intent
from .intents import intents as intent_table
from .plausibility import findings as plausibility_findings

__worldloom_seam__ = {
    "name": "evals",
    "purpose": "Eval-first design, candidate compilation, proof, execution, and grading.",
    "canonical_import": "worldloom.evals",
    "compatibility_imports": [
        "worldloom.eval_candidates",
        "worldloom.eval_construction",
        "worldloom.eval_demands",
        "worldloom.eval_design",
        "worldloom.eval_instances",
        "worldloom.eval_interventions",
        "worldloom.eval_reference",
        "worldloom.eval_search",
        "worldloom.eval_shape",
        "worldloom.eval_tactics",
        "worldloom.eval_connectors",
        "worldloom.eval_witnesses",
        "worldloom.eval_execution",
        "worldloom.connector_eval_runtime",
    ],
}


def seam_contract() -> dict[str, object]:
    """Describe the stable eval stages a harness may compose."""

    return {
        "order": [
            "design",
            "demands",
            "tactics",
            "candidates",
            "validate",
            "instantiate",
            "execute",
            "grade",
        ],
        "invariants": [
            "eval-before-data",
            "candidate-builder-cannot-accept-itself",
            "oracle-binds-only-after-validation",
            "reference-execution-isolated-per-instance",
        ],
        "public_types": [
            "CoverageReport",
            "EvalSpec",
            "CandidatePlan",
            "EvalCampaign",
            "EvalInstance",
            "DemandSet",
            "Intent",
            "RequestFeatures",
            "TacticPlan",
        ],
    }


__all__ = [
    "candidate_builder",
    "AdaptiveCandidateBuilder",
    "CampaignRun",
    "CandidateBuilder",
    "CandidateContext",
    "CandidateFeedback",
    "CoverageReport",
    "CandidatePlan",
    "ConstructionFinding",
    "ConstructionRefused",
    "ConstructionResult",
    "DemandSet",
    "EvalCampaign",
    "EvalInstance",
    "EvalSpec",
    "EvalStepSpec",
    "GeneratedCandidate",
    "Intent",
    "RequestFeatures",
    "RequirementKind",
    "TacticPlan",
    "WorldRequirement",
    "applicable",
    "construct_candidate",
    "coverage_report",
    "emulator_executor",
    "intent",
    "intent_table",
    "plausibility_findings",
    "request_features",
    "seam_contract",
]
