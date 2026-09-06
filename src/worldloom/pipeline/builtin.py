"""Executable stages over the library surface that already exists.

These are adapters, not second implementations.  ``Blueprint.build``,
``Built.episodes`` and ``World.compile`` remain authoritative while the CLI
monolith is extracted.  Moving a stage behind this seam therefore changes
orchestration without changing generation bytes.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .core import Pipeline, Stage, StageContext, StageResult


class PipelineValidationError(ValueError):
    """The validation stage refused a world while preserving the full report."""

    def __init__(self, report: Any) -> None:
        self.report = report
        violations = len(getattr(report, "violations", ()))
        super().__init__(f"world failed validation with {violations} violation(s)")


def world_stage() -> Stage[Any, Any]:
    """Mint a :class:`worldloom.sdk.Blueprint` using its existing builder."""

    from ..sdk import Blueprint, Built

    def run(blueprint: Any, _: StageContext) -> StageResult[Any]:
        built = blueprint.build()
        return StageResult(
            built,
            metadata={
                "domain": blueprint.domain_name,
                "seed": blueprint.seed,
            },
        )

    return Stage(
        name="world",
        seam="world",
        runner=run,
        input_type=Blueprint,
        output_type=Built,
        description="Mint the deterministic base world from an immutable SDK blueprint.",
    )


def episodes_stage(
    start: str,
    *,
    periods: int = 1,
    incident: bool | None = None,
) -> Stage[Any, Any]:
    """Run the domain's existing episode loop over a built world."""

    if periods < 1:
        raise ValueError("periods must be positive")
    from ..sdk import Built

    def run(built: Any, _: StageContext) -> StageResult[Any]:
        return StageResult(
            built.episodes(start, periods=periods, incident=incident),
            metadata={"start": start, "periods": periods, "incident": incident},
        )

    return Stage(
        name="episodes",
        seam="episodes",
        runner=run,
        input_type=Built,
        output_type=Built,
        description="Run the domain-owned business episode sequence.",
    )


def plan_stage() -> Stage[Any, Any]:
    """Compile artifact intents into the existing renderer-neutral ArtifactIR."""

    from ..sdk import Built

    def run(built: Any, _: StageContext) -> StageResult[Any]:
        world = built.world if built.world.artifact_irs else built.world.compile()
        return StageResult(
            replace(built, world=world),
            metadata={
                "intents": len(world.artifact_intents),
                "artifact_irs": len(world.artifact_irs),
            },
        )

    return Stage(
        name="plan",
        seam="artifacts",
        runner=run,
        input_type=Built,
        output_type=Built,
        description="Compile existing artifact intents to renderer-neutral ArtifactIR.",
    )


def validate_stage() -> Stage[Any, Any]:
    """Run the same independent world validators used by the CLI."""

    from ..sdk import Built

    def run(built: Any, _: StageContext) -> StageResult[Any]:
        report = built.validate()
        if not report.ok:
            raise PipelineValidationError(report)
        return StageResult(
            built,
            metadata={
                "checks_run": report.checks_run,
                "advisories": len(report.advisories),
            },
        )

    return Stage(
        name="validate",
        seam="world",
        runner=run,
        input_type=Built,
        output_type=Built,
        description="Run generator-independent coherence validators.",
    )


def export_stage(out: str | Path, *, overwrite: bool = True) -> Stage[Any, Path]:
    """Make filesystem output an explicit terminal side effect."""

    from ..sdk import Built

    destination = Path(out)

    def run(built: Any, _: StageContext) -> StageResult[Path]:
        written = built.export(destination, overwrite=overwrite)
        return StageResult(written, metadata={"destination": str(destination)})

    return Stage(
        name="export",
        seam="artifacts",
        runner=run,
        input_type=Built,
        output_type=Path,
        side_effects=("filesystem",),
        description="Export the corpus using World.export; no generation occurs here.",
    )


def standard_pipeline(
    start: str,
    *,
    periods: int = 1,
    incident: bool | None = None,
    compile_artifacts: bool = True,
    validate: bool = True,
) -> Pipeline:
    """The smallest complete SDK build path expressed as inspectable stages."""

    stages: list[Stage[Any, Any]] = [
        world_stage(),
        episodes_stage(start, periods=periods, incident=incident),
    ]
    if compile_artifacts:
        stages.append(plan_stage())
    if validate:
        stages.append(validate_stage())
    return Pipeline(tuple(stages))


__all__ = [
    "PipelineValidationError",
    "episodes_stage",
    "export_stage",
    "plan_stage",
    "standard_pipeline",
    "validate_stage",
    "world_stage",
]
