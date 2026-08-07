"""Artifact title, department, author and evidence form one hard contract."""

from __future__ import annotations

import pytest

from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _planned():  # type: ignore[no-untyped-def]
    return RetailWorld(seed=8128).build().run(
        MonthEndClose("2026-03", include_operational_incident=True)
    )


def test_every_compiled_artifact_carries_machine_readable_cohesion_scope() -> None:
    world = _planned().compile()
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        author = world.people.by_id(intent.author_id)
        assert ir.metadata["cohesion_contract"] == "artifact-contract@1"
        assert ir.metadata["artifact_type"] == intent.artifact_type
        assert ir.metadata["artifact_domain"] == intent.domain
        assert ir.metadata["artifact_audience"] == intent.audience
        assert ir.metadata["author_id"] == author.id
        assert ir.metadata["author_function"] == author.function
        assert set(ir.fact_ids()) <= set(intent.required_fact_ids)


def test_a_departmentally_impossible_author_is_refused_before_render() -> None:
    world = _planned()
    original = world.artifact_intents.by_id("ART-0001")
    impossible = original.model_copy(update={"domain": "actuarial"})
    world = world.extend(artifact_intents=(impossible,))
    with pytest.raises(ValueError, match="cannot own an actuarial artifact"):
        world.compile()
