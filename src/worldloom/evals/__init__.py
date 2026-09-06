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
from ..eval_tactics import TacticPlan
from ..eval_witnesses import ConstructionRefused
from .campaign import CampaignRun, EvalCampaign

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
            "EvalSpec",
            "CandidatePlan",
            "EvalCampaign",
            "EvalInstance",
            "DemandSet",
            "TacticPlan",
        ],
    }


__all__ = [
    "CampaignRun",
    "CandidateBuilder",
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
    "RequirementKind",
    "TacticPlan",
    "WorldRequirement",
    "construct_candidate",
    "emulator_executor",
    "seam_contract",
]
