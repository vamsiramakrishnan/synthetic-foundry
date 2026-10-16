"""Every top-level command has a place in `worldloom --help`."""

from __future__ import annotations

import click
import typer
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.cli_panels import PANEL_OF, PANELS


def _top_level_names() -> list[str]:
    group = typer.main.get_command(app)
    return list(group.list_commands(None))  # type: ignore[attr-defined, arg-type]


def test_every_command_has_a_panel_and_every_panel_entry_exists() -> None:
    names = _top_level_names()
    assert sorted(set(names) - PANEL_OF.keys()) == [], "add the new command to cli_panels.PANELS"
    assert sorted(PANEL_OF.keys() - set(names)) == [], "a panel names a command that no longer exists"


def test_commands_are_listed_in_panel_order() -> None:
    declared = [name for _, names in PANELS for name in names]
    assert _top_level_names() == declared


def test_help_shows_the_panels_and_version_flag() -> None:
    result = CliRunner().invoke(app, ["--help"], env={"NO_COLOR": "1", "COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    plain = click.unstyle(result.output)
    for title, _ in PANELS:
        assert title in plain
    assert "--version" in plain
    version = CliRunner().invoke(app, ["--version"])
    assert version.exit_code == 0 and version.output.strip()
