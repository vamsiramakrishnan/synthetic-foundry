"""Composable build orchestration for SDK callers and coding harnesses.

The CLI is a consumer of this package, not its owner.  Keep stage implementations
small and seam-specific; the graph belongs here.
"""

from .builtin import (
    PipelineValidationError,
    episodes_stage,
    export_stage,
    plan_stage,
    standard_pipeline,
    validate_stage,
    world_stage,
)
from .core import (
    PIPELINE_SCHEMA,
    Pipeline,
    PipelineRun,
    Stage,
    StageContext,
    StageContract,
    StageExecution,
    StageResult,
    manifest_for,
)

__worldloom_seam__ = {
    "name": "pipeline",
    "purpose": "Typed orchestration shared by SDK callers, CLI commands, and harness skills.",
    "canonical_import": "worldloom.pipeline",
    "compatibility_imports": [],
}


def seam_contract() -> dict[str, object]:
    """Describe the live default stage graph without executing a build."""

    return standard_pipeline("2000-01").seam_manifest()


__all__ = [
    "PIPELINE_SCHEMA",
    "Pipeline",
    "PipelineRun",
    "PipelineValidationError",
    "Stage",
    "StageContext",
    "StageContract",
    "StageExecution",
    "StageResult",
    "episodes_stage",
    "export_stage",
    "manifest_for",
    "plan_stage",
    "seam_contract",
    "standard_pipeline",
    "validate_stage",
    "world_stage",
]
