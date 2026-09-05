from worldloom.ecology import connectors, prepare
from worldloom.world import World


def test_prepare_marks_recipe_and_builds_realism_profile() -> None:
    world = World.load("retail-close")
    result = prepare(world)
    assert result.world.recipe["artifact_realism"] == "ecology/v1"
    assert result.profile.organisation.key
    assert result.profile.plans
    assert 0.0 <= result.realism.score <= 1.0
    assert all(
        ir.metadata.get("realism_profile") == "ecology/v1"
        for ir in result.world.artifact_irs
    )


def test_realistic_connector_projection_enriches_servicenow() -> None:
    world = World.load("retail-close")
    dataset = connectors(world, ("servicenow",))
    incidents = [record for record in dataset.records if record.entity == "incident"]
    if incidents:
        fields = incidents[0].fields
        assert "state_history" in fields
        assert "work_notes" in fields
        assert "sla" in fields
        assert "related_records" in fields


def test_realistic_connector_projection_preserves_base_identity() -> None:
    world = World.load("retail-close")
    dataset = connectors(world, ("email",))
    for message in dataset.records:
        assert message.id.startswith("CONN-EMAIL-")
        assert message.fields["message_id"] == message.external_id
        assert "conversation_index" in message.fields
        assert "signature_style" in message.fields
