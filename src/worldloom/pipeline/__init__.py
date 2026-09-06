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
    "standard_pipeline",
    "validate_stage",
    "world_stage",
]
