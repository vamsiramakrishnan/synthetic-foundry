from __future__ import annotations

from dataclasses import replace

import pytest

from worldloom import sdk
from worldloom.pipeline import (
    Pipeline,
    Stage,
    StageContext,
    StageResult,
    standard_pipeline,
)


def test_stage_rejects_undeclared_recipe_contributions() -> None:
    stage = Stage(
        name="bad",
        seam="test",
        input_type=int,
        output_type=int,
        recipe_keys=("declared",),
        runner=lambda value, _: StageResult(value + 1, recipe={"surprise": True}),
    )

    with pytest.raises(ValueError, match="undeclared recipe keys"):
        Pipeline((stage,)).run(1)


def test_pipeline_rejects_recipe_key_ownership_collisions() -> None:
    first = Stage(
        name="first",
        seam="test",
        recipe_keys=("shared",),
        runner=lambda value, _: StageResult(value + 1, recipe={"shared": 1}),
    )
    second = Stage(
        name="second",
        seam="test",
        recipe_keys=("shared",),
        runner=lambda value, _: StageResult(value + 1, recipe={"shared": 2}),
    )

    with pytest.raises(ValueError, match="owned by one stage only"):
        Pipeline((first, second)).run(0)


def test_manifest_is_deterministic_and_contains_no_runtime_clock() -> None:
    stage = Stage(
        name="increment",
        seam="test",
        input_type=int,
        output_type=int,
        recipe_keys=("amount",),
        runner=lambda value, _: StageResult(
            value + 1, recipe={"amount": 1}, metadata={"reason": "test"}
        ),
    )
    pipeline = Pipeline((stage,))

    first = pipeline.run(4, context=StageContext(seed=9))
    second = pipeline.run(4, context=StageContext(seed=9))

    assert first.manifest() == second.manifest()
    assert first.digest == second.digest
    assert pipeline.seam_manifest() == pipeline.seam_manifest()
    assert "time" not in str(first.manifest()).casefold()


def test_standard_pipeline_is_the_existing_sdk_path_not_a_second_builder() -> None:
    blueprint = sdk.retail(seed=73)

    direct = blueprint.build().episodes("2026-03", periods=1, incident=False)
    direct = replace(direct, world=direct.world.compile())
    assert direct.validate().ok

    run = standard_pipeline("2026-03", periods=1, incident=False).run(blueprint)

    assert [stage.name for stage in run.stages] == [
        "world",
        "episodes",
        "plan",
        "validate",
    ]
    assert run.value.world.model_dump(mode="json") == direct.world.model_dump(mode="json")
