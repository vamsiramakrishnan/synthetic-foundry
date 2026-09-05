from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose
from worldloom.tool_surface import ToolSurface


def _world(seed: int = 8128):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=seed).build().run(MonthEndClose(period="2026-03"))


def test_tool_surface_forks_isolate_writes() -> None:
    surface = ToolSurface.from_world(_world())
    left = surface.fork()
    right = surface.fork()

    created = left.create(
        "jira",
        "issue",
        external_id="WL-9001",
        title="Synthetic remediation",
        fields={"status": "To Do", "priority": "P1"},
    )

    assert created.effects
    assert left.read("jira", "issue", "WL-9001").records
    assert right.read("jira", "issue", "WL-9001").records == ()


def test_search_matches_native_and_field_values() -> None:
    surface = ToolSurface.from_world(_world())
    session = surface.fork()
    session.create(
        "servicenow",
        "incident",
        external_id="INC9001",
        title="Payments unavailable",
        fields={"priority": "P1", "state": "open"},
    )

    result = session.search("servicenow", "incident", priority="P1", state="open")

    assert any(record.external_id == "INC9001" for record in result.records)


def test_update_returns_effect_and_preserves_original_fork() -> None:
    surface = ToolSurface.from_world(_world())
    changed = surface.fork()
    untouched = surface.fork()
    changed.create(
        "jira",
        "issue",
        external_id="WL-9002",
        title="Synthetic remediation",
        fields={"status": "To Do"},
    )

    result = changed.update("jira", "issue", "WL-9002", fields={"status": "Done"})

    assert result.records[0].fields["status"] == "Done"
    assert result.effects
    assert untouched.read("jira", "issue", "WL-9002").records == ()
