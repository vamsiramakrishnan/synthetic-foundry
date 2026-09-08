from __future__ import annotations

from pathlib import Path

import pytest

from worldloom import calibrate, sdk
from worldloom.corpus import tree_divergence
from worldloom.recipe import (
    PRIOR_RECEIPTS_KEY,
    RecipeError,
    rebuild,
    with_prior_receipts,
)


def test_sdk_preserves_prior_receipt_and_explicit_overrides_through_offline_replay(tmp_path: Path) -> None:
    snapshot = calibrate.calibrate(
        [{"unit": f"U{index}", "margin": 0.2 + index % 10 / 100} for index in range(200)],
        {"unit": "unit", "columns": [{"column": "margin", "parameter": "retail.margin.budget",
                                       "clip": [0.1, 0.5], "bins": 20}]},
        epsilon=2.0, estimator=calibrate.LaplaceHistogramEstimator(noise_seed=8),
    )
    path = snapshot.write(tmp_path / "priors.json")
    blueprint = sdk.retail().physics(retail_margin_budget=(0.24, 0.26)).priors(path)
    assert blueprint.prior_receipts == (snapshot.receipt,)
    assert blueprint.priors(snapshot).prior_receipts == blueprint.prior_receipts
    world = blueprint.build().episodes("2026-03").world.compile()
    assert world.recipe[PRIOR_RECEIPTS_KEY] == [snapshot.receipt.model_dump(mode="json")]
    assert world.recipe["physics"]["retail.margin.budget"]["low"] == 0.24
    assert world.recipe["physics"]["retail.margin.budget"]["high"] == 0.26
    assert world.recipe[PRIOR_RECEIPTS_KEY][0]["privacy"]["noise_source"] == "seeded"

    path.unlink()
    replay = rebuild(world.recipe).compile()
    assert replay.recipe == world.recipe
    assert replay.validate().ok
    original_path, replay_path = tmp_path / "original", tmp_path / "replay"
    world.export(original_path)
    replay.export(replay_path)
    assert tree_divergence(original_path, replay_path) is None


def test_uncalibrated_blueprints_do_not_add_recipe_metadata() -> None:
    assert PRIOR_RECEIPTS_KEY not in sdk.retail().build().world.recipe
    assert with_prior_receipts({"seed": 8128}, ()) == {"seed": 8128}


def test_replay_refuses_invalid_prior_provenance() -> None:
    recipe = sdk.retail().build().world.recipe
    with pytest.raises(RecipeError, match="prior receipts do not load"):
        rebuild({**recipe, PRIOR_RECEIPTS_KEY: [{"operation": "propose_rows"}]})
