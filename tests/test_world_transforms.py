from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose
from worldloom.world_transforms import AddIrrelevantFacts, OracleEffect


def _world(seed: int = 8128):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=seed).build().run(MonthEndClose(period="2026-03"))


def test_irrelevant_fact_transform_preserves_existing_truth() -> None:
    world = _world()
    before = tuple(world.facts)

    result = AddIrrelevantFacts(12).apply(world, seed=991)

    assert result.oracle_effect == OracleEffect.PRESERVE
    assert tuple(result.world.facts)[: len(before)] == before
    assert len(result.world.facts) == len(before) + 12
    assert len(set(result.added_ids)) == 12
    assert all(
        result.world.facts.by_id(identifier).kind == "metamorphic_irrelevant_context"
        for identifier in result.added_ids
    )


def test_irrelevant_fact_transform_is_replayable() -> None:
    world = _world()

    left = AddIrrelevantFacts(7).apply(world, seed=42)
    right = AddIrrelevantFacts(7).apply(world, seed=42)

    assert left.transform_id == right.transform_id
    assert left.added_ids == right.added_ids
    assert left.world == right.world


def test_zero_noise_is_identity() -> None:
    world = _world()
    result = AddIrrelevantFacts(0).apply(world, seed=42)

    assert result.world is world
    assert result.added_ids == ()
