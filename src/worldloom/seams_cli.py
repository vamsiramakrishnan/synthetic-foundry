"""CLI rendering for the code-generated seam manifest."""

from __future__ import annotations

import json

import typer

from .seams import seam_manifest


def seams_command(
    json_output: bool = typer.Option(False, "--json", help="Emit the complete machine-readable seam contract."),
) -> None:
    """Show the library seams a harness can compose."""

    manifest = seam_manifest()
    if json_output:
        typer.echo(json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str))
        return
    for seam in manifest["seams"]:
        typer.echo(f"{seam['name']}\t{seam['canonical_import']}\t{seam['purpose']}")


__all__ = ["seams_command"]
