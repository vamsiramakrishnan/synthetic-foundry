"""Where each top-level command sits in `worldloom --help`.

Fifty-odd commands in one flat list read as a catalogue, not a workflow: a
first-time user scanning for "how do I evaluate my retriever" met `seams`
first and `evaluate` thirteenth, between `formats` and `search`. The panels
below follow the order work actually happens in (start, build, inspect,
author, evaluate, integrate), and the table is the single place a command's
placement is decided. `tests/test_cli_panels.py` fails when a command is
registered without a panel here, so a new command cannot quietly land in an
untitled "Commands" box at the bottom.
"""

from __future__ import annotations

from typing import Any

from typer.core import TyperGroup

#: Panels in display order, each with its commands in display order.
PANELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Start here", ("guide", "demo", "smoke", "status", "doctor", "version")),
    ("Build and render", (
        "build", "render", "verify", "migrate", "formats", "archetypes", "workspace",
        "mosaic", "corpus-scale", "synth",
    )),
    ("Inspect and measure", (
        "inspect", "validate", "stats", "search", "diversity", "topology", "series",
        "fidelity", "actors",
    )),
    ("Author a company", (
        "studio", "interview", "pack", "probe", "compose", "causal", "present",
        "industry", "calibrate",
    )),
    ("Agent-written content", ("narrate", "plan", "act", "visuals")),
    ("Evaluate retrieval", ("evaluate", "evals", "benchmark", "gemini-enterprise")),
    ("Evaluate agents", ("enterprise-evals", "evalrun", "native-evals", "contracts")),
    ("Explore configurations", ("evolve", "twin", "mutate", "spaces", "fleet")),
    ("Integrate", ("mcp", "seams", "docs")),
)

PANEL_OF: dict[str, str] = {name: title for title, names in PANELS for name in names}
_RANK: dict[str, int] = {
    name: rank for rank, name in enumerate(name for _, names in PANELS for name in names)
}


class WorkflowGroup(TyperGroup):
    """Lists commands in panel order rather than registration order.

    Typer prints panels in the order their first command is listed, and lists
    plain commands before sub-apps, so without this a panel holding only
    sub-apps (`Evaluate agents`) would always sink below every panel that
    holds a plain command, whatever order `PANELS` declares.
    """

    def list_commands(self, ctx: Any) -> list[str]:
        names = super().list_commands(ctx)
        order = {name: index for index, name in enumerate(names)}
        return sorted(names, key=lambda name: (_RANK.get(name, len(_RANK)), order[name]))


def assign_panels(app: Any) -> None:
    """Stamp each registered command and sub-app with its panel title."""
    for info in (*app.registered_commands, *app.registered_groups):
        name = info.name or (info.callback.__name__.replace("_", "-") if info.callback else None)
        if name in PANEL_OF:
            info.rich_help_panel = PANEL_OF[name]


__all__ = ["PANELS", "PANEL_OF", "WorkflowGroup", "assign_panels"]
