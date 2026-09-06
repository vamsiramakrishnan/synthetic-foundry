"""Typed orchestration primitives shared by the SDK, CLI, and harness skills.

The pipeline is deliberately boring.  It does not generate data and it does not
know what a retail close is.  It only makes orchestration explicit: every stage
names its seam, accepted value type, produced value type, recipe contribution,
and externally visible side effects.  A harness can therefore inspect and
recompose a pipeline without reading a command body.

Runtime manifests contain no clocks or timings.  Two byte-identical runs produce
byte-identical manifests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, TypeVar, cast

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")

PIPELINE_SCHEMA = "worldloom.pipeline/v1"


def _type_name(value: type[Any] | tuple[type[Any], ...] | None) -> str:
    if value is None:
        return "any"
    if isinstance(value, tuple):
        return " | ".join(f"{item.__module__}.{item.__qualname__}" for item in value)
    return f"{value.__module__}.{value.__qualname__}"


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Copy a mapping so callers cannot mutate a completed run through aliases."""

    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class StageContract:
    """Static contract for one orchestration seam.

    ``recipe_keys`` is an allow-list, not documentation.  A stage returning a
    recipe contribution it did not declare is rejected before the next stage
    sees the value.  ``side_effects`` is likewise explicit so a harness can
    distinguish pure planning from filesystem or model execution.
    """

    name: str
    seam: str
    input: str
    output: str
    recipe_keys: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "seam": self.seam,
            "input": self.input,
            "output": self.output,
            "recipe_keys": list(self.recipe_keys),
            "side_effects": list(self.side_effects),
            "description": self.description,
        }


@dataclass(frozen=True)
class StageContext:
    """Immutable run inputs that are orthogonal to the threaded stage value."""

    seed: int | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", _freeze_mapping(self.options))


@dataclass(frozen=True)
class StageResult(Generic[OutputT]):
    """A stage value plus the machine-readable contribution made while deriving it."""

    value: OutputT
    recipe: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe", _freeze_mapping(self.recipe))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True)
class StageExecution:
    """Deterministic record of one completed stage."""

    name: str
    seam: str
    input_type: str
    output_type: str
    recipe: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe", _freeze_mapping(self.recipe))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "seam": self.seam,
            "input_type": self.input_type,
            "output_type": self.output_type,
            "recipe": dict(self.recipe),
            "metadata": dict(self.metadata),
        }


Runner = Callable[[InputT, StageContext], StageResult[OutputT] | OutputT]


@dataclass(frozen=True)
class Stage(Generic[InputT, OutputT]):
    """One executable stage with runtime type and recipe-contract enforcement."""

    name: str
    seam: str
    runner: Runner[InputT, OutputT]
    input_type: type[Any] | tuple[type[Any], ...] | None = None
    output_type: type[Any] | tuple[type[Any], ...] | None = None
    recipe_keys: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    description: str = ""

    @property
    def contract(self) -> StageContract:
        return StageContract(
            name=self.name,
            seam=self.seam,
            input=_type_name(self.input_type),
            output=_type_name(self.output_type),
            recipe_keys=self.recipe_keys,
            side_effects=self.side_effects,
            description=self.description,
        )

    def apply(self, value: InputT, context: StageContext) -> tuple[OutputT, StageExecution]:
        if self.input_type is not None and not isinstance(value, self.input_type):
            raise TypeError(
                f"stage {self.name!r} expected {_type_name(self.input_type)}, "
                f"got {type(value).__module__}.{type(value).__qualname__}"
            )
        raw = self.runner(value, context)
        result = raw if isinstance(raw, StageResult) else StageResult(raw)
        unknown = set(result.recipe) - set(self.recipe_keys)
        if unknown:
            raise ValueError(
                f"stage {self.name!r} returned undeclared recipe keys {sorted(unknown)}; "
                f"declared keys are {sorted(self.recipe_keys)}"
            )
        output = cast(OutputT, result.value)
        if self.output_type is not None and not isinstance(output, self.output_type):
            raise TypeError(
                f"stage {self.name!r} promised {_type_name(self.output_type)}, "
                f"returned {type(output).__module__}.{type(output).__qualname__}"
            )
        return output, StageExecution(
            name=self.name,
            seam=self.seam,
            input_type=f"{type(value).__module__}.{type(value).__qualname__}",
            output_type=f"{type(output).__module__}.{type(output).__qualname__}",
            recipe=result.recipe,
            metadata=result.metadata,
        )


@dataclass(frozen=True)
class PipelineRun(Generic[OutputT]):
    """Completed pipeline value and the exact deterministic orchestration record."""

    value: OutputT
    stages: tuple[StageExecution, ...]
    recipe: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe", _freeze_mapping(self.recipe))

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": PIPELINE_SCHEMA,
            "stages": [stage.as_dict() for stage in self.stages],
            "recipe": dict(self.recipe),
        }

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.manifest(), sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Pipeline:
    """Ordered typed stage graph.

    A pipeline is immutable and therefore safe to reuse across candidate worlds.
    ``then`` returns a new graph; it never edits the original.  The graph stays
    deliberately linear for now because the existing build path is linear. DAG
    fan-out belongs in eval/task graphs and mosaics rather than being invented a
    second time here.
    """

    stages: tuple[Stage[Any, Any], ...] = ()

    def __post_init__(self) -> None:
        names = [stage.name for stage in self.stages]
        if len(names) != len(set(names)):
            raise ValueError(f"pipeline stage names must be unique: {names}")

    def then(self, stage: Stage[Any, Any]) -> Pipeline:
        return Pipeline((*self.stages, stage))

    def contracts(self) -> tuple[StageContract, ...]:
        return tuple(stage.contract for stage in self.stages)

    def seam_manifest(self) -> dict[str, Any]:
        contracts = [contract.as_dict() for contract in self.contracts()]
        return {
            "schema": PIPELINE_SCHEMA,
            "stages": contracts,
            "digest": hashlib.sha256(
                json.dumps(contracts, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }

    def run(self, initial: Any, *, context: StageContext | None = None) -> PipelineRun[Any]:
        active = initial
        executions: list[StageExecution] = []
        recipe: dict[str, Any] = {}
        run_context = context or StageContext()
        for stage in self.stages:
            active, execution = stage.apply(active, run_context)
            overlap = set(recipe) & set(execution.recipe)
            if overlap:
                raise ValueError(
                    f"pipeline recipe keys may be owned by one stage only: {sorted(overlap)}"
                )
            recipe.update(execution.recipe)
            executions.append(execution)
        return PipelineRun(active, tuple(executions), recipe)


def manifest_for(stages: Sequence[Stage[Any, Any]]) -> dict[str, Any]:
    """Generate the same contract document without constructing a run."""

    return Pipeline(tuple(stages)).seam_manifest()


__all__ = [
    "PIPELINE_SCHEMA",
    "Pipeline",
    "PipelineRun",
    "Stage",
    "StageContext",
    "StageContract",
    "StageExecution",
    "StageResult",
    "manifest_for",
]
