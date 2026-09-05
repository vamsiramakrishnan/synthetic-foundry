import pytest

from worldloom import MonthEndClose, RetailWorld
from worldloom.ecology import connectors, prepare


@pytest.fixture(scope="module")
def world():  # type: ignore[no-untyped-def]
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )


def test_prepare_marks_recipe_and_builds_realism_profile(world) -> None:  # type: ignore[no-untyped-def]
    result = prepare(world)
    assert result.world.recipe["artifact_realism"] == "ecology/v1"
    assert result.profile.organisation.key
    assert result.profile.plans
    assert 0.0 <= result.realism.score <= 1.0
    assert all(
        ir.metadata.get("realism_profile") == "ecology/v1"
        for ir in result.world.artifact_irs
    )


def test_realistic_connector_projection_enriches_servicenow(world) -> None:  # type: ignore[no-untyped-def]
    dataset = connectors(world, ("servicenow",))
    incidents = [record for record in dataset.records if record.entity == "incident"]
    assert incidents
    fields = incidents[0].fields
    assert "state_history" in fields
    assert "work_notes" in fields
    assert "sla" in fields
    assert "related_records" in fields


def test_realistic_connector_projection_preserves_base_identity(world) -> None:  # type: ignore[no-untyped-def]
    dataset = connectors(world, ("email",))
    messages = [record for record in dataset.records if record.entity == "message"]
    assert messages
    for message in messages:
        assert message.id.startswith("CONN-EMAIL-")
        assert message.fields["message_id"] == message.external_id
        assert "conversation_index" in message.fields
        assert "signature_style" in message.fields
