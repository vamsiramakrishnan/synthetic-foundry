from __future__ import annotations

from pathlib import Path

import pytest

from worldloom import company, policies, sdk
from worldloom.corpus import tree_divergence
from worldloom.recipe import rebuild


@pytest.mark.parametrize("engine", ["retail", "banking"])
def test_resolved_policies_are_built_once_before_episodes_and_replay(
    engine: str, tmp_path: Path,
) -> None:
    resolution = company.resolve(company.from_document({"engine": engine, "policies": "core"}))
    assert resolution.ok
    blueprint = sdk.from_resolution(resolution)
    assert blueprint.policy_level == "core"
    assert blueprint.describe()["policies"] == "core"
    built = blueprint.build()
    types = {spec.artifact_type for spec in policies.selected("core")}
    policy_ids = tuple(intent.id for intent in built.world.artifact_intents if intent.artifact_type in types)
    assert policy_ids
    assert {intent.artifact_type for intent in built.world.artifact_intents} == types
    assert built.world.recipe["policies"] == "core"

    world = built.episodes("2026-03", periods=2).world.render("markdown")
    assert tuple(intent.id for intent in world.artifact_intents if intent.artifact_type in types) == policy_ids
    assert world.validate().ok
    replay = rebuild(world.recipe).render("markdown")
    assert replay.recipe == world.recipe
    assert tree_divergence(world.export(tmp_path / "original"), replay.export(tmp_path / "replay")) is None


def test_direct_policy_selection_matches_company_resolution_and_none_is_unchanged(tmp_path: Path) -> None:
    direct = sdk.described({"engine": "retail"}, seed=37).policies("core").build().episodes("2026-03").world.compile()
    described = sdk.described({"engine": "retail", "policies": "core"}, seed=37).build().episodes("2026-03").world.compile()
    assert tree_divergence(direct.export(tmp_path / "direct"), described.export(tmp_path / "described")) is None
    plain = sdk.retail(seed=37).build().episodes("2026-03").world.compile()
    none = sdk.retail(seed=37).policies("none").build().episodes("2026-03").world.compile()
    assert "policies" not in plain.recipe
    assert tree_divergence(plain.export(tmp_path / "plain"), none.export(tmp_path / "none")) is None
    with pytest.raises(ValueError, match="unknown policy level"):
        sdk.retail().policies("invented")


def test_policies_reach_a_company_pack_before_episodes() -> None:
    resolution = company.resolve(company.from_document({
        "engine": "retail", "policies": "core",
        "identity": {"company_name": "Harbor Market"},
    }))
    assert resolution.ok
    assert resolution.pack is not None
    built = sdk.from_resolution(resolution).build()
    assert built.world.company.name == "Harbor Market"
    assert built.world.recipe["policies"] == "core"
    assert any(fact.kind.startswith("policy.") for fact in built.world.facts)
