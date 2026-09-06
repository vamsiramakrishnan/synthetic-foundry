from __future__ import annotations

from worldloom.seams import SEAMS_SCHEMA, seam_manifest


def test_seam_manifest_is_generated_from_declared_packages() -> None:
    first = seam_manifest()
    second = seam_manifest()

    assert first == second
    assert first["schema"] == SEAMS_SCHEMA
    assert first["digest"] == second["digest"]
    by_name = {item["name"]: item for item in first["seams"]}
    assert {"pipeline", "connectors"} <= set(by_name)

    pipeline = by_name["pipeline"]["contract"]
    assert [stage["name"] for stage in pipeline["stages"]] == [
        "world",
        "episodes",
        "plan",
        "validate",
    ]

    connectors = by_name["connectors"]["contract"]["connectors"]
    connector_names = {item["name"] for item in connectors}
    assert {"jira", "outlook", "slack", "teamwork_graph", "rovo"} <= connector_names


def test_compatibility_connector_modules_remain_explicit() -> None:
    by_name = {item["name"]: item for item in seam_manifest()["seams"]}
    compatibility = set(by_name["connectors"]["compatibility_imports"])

    assert "worldloom.connector_definition" in compatibility
    assert "worldloom.connector_emulator" in compatibility
