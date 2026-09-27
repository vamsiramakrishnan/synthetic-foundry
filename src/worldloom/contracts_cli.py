"""``worldloom contracts``: the vendor contracts connectors are served behind through Anvil.

Thin like every command module: each command reads the lock
(``_data/connectors/_contracts.json``), calls ``worldloom.connectors.contracts``
and prints what it returned. Fetching, digest checks, compiling, trimming and
coverage are the package's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(
    no_args_is_help=True,
    help="Fetch, verify, compile and measure the vendor contracts connectors are served behind through Anvil.",
)


def _refuse(code: str, message: str, **data: Any) -> Any:
    from rich.markup import escape

    from .cli import _refuse as refuse

    refuse(code, f"[red]error:[/red] {escape(message)}", **data)


def _lock() -> Any:
    from .connectors.contracts import ContractError, load_lock

    try:
        return load_lock()
    except ContractError as error:
        _refuse("contract_refused", str(error))


def _anvil(command: str | None) -> tuple[str, ...]:
    from .evalrun.anvil import find_anvil

    found = find_anvil(command)
    if not found:
        _refuse("anvil_unavailable", "no Anvil CLI: pass --anvil-cmd 'node .../bin-anvil.js' or set WORLDLOOM_ANVIL")
    assert found is not None
    return found


@app.command("fetch")
def fetch_command(
    connectors: list[str] = typer.Argument(None, help="Connectors to fetch; every locked one by default."),
    cache: Path | None = typer.Option(None, "--cache", help="Cache directory (default $WORLDLOOM_CONTRACTS_CACHE, else ~/.cache/worldloom/contracts)."),
    as_json: bool = typer.Option(False, "--json", help="Print what was fetched as JSON."),
) -> None:
    """Download each locked vendor contract (or copy an authored one), verify its sha256, and refuse a mismatch."""

    from .connectors.contracts import ContractError, fetch

    lock = _lock()
    try:
        fetched = fetch(lock, connectors or (), cache=cache)
    except ContractError as error:
        _refuse("contract_refused", str(error))
    rows = [{"connector": item.connector, "status": item.status, "sha256": item.sha256, "path": str(item.path)}
            for item in fetched]
    if as_json:
        typer.echo(json.dumps(rows, indent=1))
        return
    for row in rows:
        typer.echo(f"{row['connector']:<12} {row['status']:<8} sha256:{row['sha256'][:12]}  {row['path']}")


@app.command("build")
def build_command(
    connector: str = typer.Argument(..., help="The connector whose contract to compile."),
    cache: Path | None = typer.Option(None, "--cache", help="Cache directory for sources and bundles."),
    spec: Path | None = typer.Option(None, "--spec", help="Compile this source (a trim) under the connector's profile instead of the locked bytes."),
    anvil_cmd: str | None = typer.Option(None, "--anvil-cmd", help="The Anvil CLI, split like a shell command (default $WORLDLOOM_ANVIL, else anvil on PATH)."),
    force: bool = typer.Option(False, "--force", help="Rebuild even when the cache holds this build."),
    as_json: bool = typer.Option(False, "--json", help="Print the build receipt as JSON."),
) -> None:
    """Compile a connector's contract under its profile with Anvil, approve the profile, and lint the mapping.

    The bundle is cached under a key of the source digest, the profile, the
    manifest, the mapping and the Anvil version; serve it with
    `worldloom evalrun run --connectors anvil --contract CONNECTOR=<bundle>`.
    """

    from .connectors.contracts import ContractError, build

    lock = _lock()
    anvil = _anvil(anvil_cmd)
    try:
        built = build(connector, lock=lock, cache=cache, anvil=anvil, spec=spec, force=force)
    except ContractError as error:
        _refuse("contract_refused", str(error))
    if as_json:
        typer.echo(json.dumps({**built.receipt, "bundle": str(built.bundle), "cached": built.cached}, indent=1, sort_keys=True))
        return
    receipt = built.receipt
    mapping = receipt.get("mapping") or {}
    typer.echo(f"{connector}: {len(receipt['exposed'])} operations exposed and approved "
               f"({len(mapping.get('modelled', ()))} modelled, {len(mapping.get('unmodelled', ()))} unmodelled)"
               f"{' from cache' if built.cached else ''}")
    typer.echo(f"  bundle   {built.bundle}")
    typer.echo(f"  source   sha256:{receipt['source']['sha256'][:12]} ({'locked' if receipt['source']['locked'] else 'not the locked bytes'})")
    typer.echo(f"  profile  {receipt['profile']['id']} {receipt['profile']['anvil_digest']}")
    typer.echo(f"  anvil    {receipt['anvil']['version']}")
    typer.echo(f"  serve    worldloom evalrun run CASES -o OUT --connectors anvil --contract {connector}={built.bundle}")


@app.command("trim")
def trim_command(
    connector: str = typer.Argument(..., help="The connector whose contract to cut."),
    out: Path = typer.Option(..., "-o", "--out", help="Where to write the gzipped trim."),
    source: Path | None = typer.Option(None, "--source", help="The full source (default: the fetched, locked bytes). A large YAML source reads faster converted to JSON."),
    cache: Path | None = typer.Option(None, "--cache", help="Cache directory for sources and bundles."),
    anvil_cmd: str | None = typer.Option(None, "--anvil-cmd", help="The Anvil CLI, split like a shell command."),
) -> None:
    """Cut a contract to the operations its profile exposes and the schemas they reach, for a small test fixture.

    The trim is compiled again under the same profile and refused unless it
    exposes exactly the same operations.
    """

    from .connectors.contracts import ContractError, trim_contract

    lock = _lock()
    anvil = _anvil(anvil_cmd)
    try:
        path = trim_contract(connector, out, lock=lock, cache=cache, anvil=anvil, source=source)
    except ContractError as error:
        _refuse("contract_refused", str(error))
    typer.echo(f"{connector}: wrote {path} ({path.stat().st_size} bytes)")


@app.command("coverage")
def coverage_command(
    as_json: bool = typer.Option(False, "--json", help="Print the rows as JSON."),
) -> None:
    """Per connector: vendor operations, operations the profile exposes, modelled and unmodelled, and provenance."""

    from .connectors.contracts import coverage

    rows = coverage(_lock())
    if as_json:
        typer.echo(json.dumps([row.as_dict() for row in rows], indent=1))
        return

    def cell(value: Any) -> str:
        return "-" if value is None else str(value)

    typer.echo(f"{'connector':<15} {'provenance':<10} {'vendor ops':>10} {'profiled':>8} {'modelled':>8} {'unmodelled':>10}")
    for row in rows:
        line = (f"{row.connector:<15} {row.provenance:<10} {cell(row.vendor_operations):>10} {cell(row.profiled):>8} "
                f"{cell(row.modelled):>8} {cell(row.unmodelled):>10}")
        if row.reason:
            line += f"  {row.reason}"
        elif row.mapping_matches_profile is False:
            line += "  the mapping and the profile disagree on the operation count"
        typer.echo(line)
