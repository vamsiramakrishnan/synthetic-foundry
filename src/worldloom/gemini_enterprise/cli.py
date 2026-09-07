"""CLI for the Gemini Enterprise Eval Studio integration.

Three commands, one per direction: the corpus out to a data store, the cases
out as uploadable CSVs, and the results back in as a scorecard. Every command
delegates to a library operation and adds only argument handling and refusals.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import typer

app = typer.Typer(
    no_args_is_help=True,
    help="Export a corpus and its evaluation set for Gemini Enterprise Eval Studio.",
)


@app.command("datastore")
def datastore_command(
    corpus: str = typer.Argument(..., help="Bundled corpus name or path."),
    workspace: Path = typer.Argument(..., help="A workspace root written by `worldloom workspace`."),
    uri_prefix: str = typer.Option(..., "--uri-prefix", help="Where the files will live: gs://bucket/prefix."),
    out: Path = typer.Option(None, "--out", "-o", help="Write documents.jsonl here instead of stdout."),
) -> None:
    """Write the workspace as Discovery Engine documents, permissions included.

    The output is the `gcsSource` `dataSchema: "document"` format: one document
    per line, `content.uri` pointing into *uri_prefix*, and `aclInfo` carrying
    the drive's own readers. Upload the workspace tree to that prefix, then
    import this file into the data store Eval Studio will search.
    """
    from ..cli import _load, _refuse
    from .datastore import documents

    world = _load(corpus)
    try:
        export = documents(world, workspace, uri_prefix=uri_prefix)
    except ValueError as error:
        _refuse("datastore_unexportable", str(error))
    if not export.documents:
        _refuse(
            "datastore_unexportable",
            f"{workspace} produced no document; every file was skipped or the"
            " permission table is empty",
            findings=list(export.skipped),
        )
    payload = export.jsonl()
    if out is None:
        typer.echo(payload, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8", newline="\n")
        typer.echo(f"{len(export.documents)} document(s) written to {out}")
    for sentence in export.skipped:
        typer.echo(f"skipped: {sentence}", err=True)


@app.command("cases")
def cases_command(
    corpus: str = typer.Argument(..., help="Bundled corpus name or path."),
    out: Path = typer.Option(..., "--out", "-o", help="Directory to write the shards into."),
    limit: int = typer.Option(100, "--limit", help="Rows per shard; Eval Studio truncates uploads past 100."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing directory."),
) -> None:
    """Write the evaluation set as one uploadable CSV per grading shape.

    Each shard gets the auto-rater instruction its shape claims, listed in
    `manifest.json`: paste a shard's rubric into Eval Studio's auto-rater
    instruction field before uploading that shard. One instruction across the
    whole set grades an abstention as though a confident wrong answer were
    partial credit.
    """
    from ..cli import _load, _refuse
    from .cases import shards

    world = _load(corpus)
    try:
        parts = shards(world.evaluations, limit=limit)
    except ValueError as error:
        _refuse("bad_shard", str(error))
    if not parts:
        _refuse(
            "cases_unexportable",
            f"{corpus} holds no evaluation case with an expected answer, so"
            " there is nothing to score against",
        )
    if out.exists() and any(out.iterdir()) and not overwrite:
        _refuse("destination_exists", f"{out} is not empty", fix="pass --overwrite", destination=str(out))
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "corpus": corpus,
        "row_limit": limit,
        "shards": [
            {
                "file": f"{shard.name}.csv",
                "evaluation_type": str(shard.evaluation_type.value),
                "part": shard.part,
                "parts": shard.parts,
                "rows": len(shard.rows),
                "auto_rater_instruction": shard.rubric,
            }
            for shard in parts
        ],
    }
    for shard in parts:
        (out / f"{shard.name}.csv").write_text(shard.csv(), encoding="utf-8", newline="\n")
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    total = sum(len(shard.rows) for shard in parts)
    typer.echo(f"{total} case(s) in {len(parts)} shard(s) written to {out}")


@app.command("score")
def score_command(
    corpus: str = typer.Argument(..., help="Bundled corpus name or path."),
    results: list[Path] = typer.Argument(..., help="Results CSV files exported by Eval Studio."),
    json_output: bool = typer.Option(False, "--json", help="Emit the scorecard as JSON."),
) -> None:
    """Rejoin Eval Studio's results to the set and slice them.

    Its output carries no case id, so the join is on the query text and the
    slices come from the corpus. Rows whose auto-rater call failed are counted
    and excluded from every mean rather than averaged in as zeros.
    """
    from ..cli import _load, _refuse
    from .results import read_results, score

    world = _load(corpus)
    rows: list[dict[str, str]] = []
    for path in results:
        try:
            rows.extend(read_results(path))
        except OSError as error:
            _refuse("results_unreadable", f"{path}: {error}")
    try:
        card = score(world.evaluations, rows)
    except ValueError as error:
        _refuse("results_unjoinable", str(error))

    if json_output:
        typer.echo(json.dumps(asdict(card), indent=2, sort_keys=True))
        return
    typer.echo(
        f"overall: {card.overall.mean_score} over {card.overall.scored}"
        f"/{card.overall.cases} scored case(s);"
        f" ttfa {card.overall.mean_ttfa}s, ttlt {card.overall.mean_ttlt}s"
    )
    for part in card.by_type:
        typer.echo(
            f"  {part.key}: {part.mean_score} over {part.scored}/{part.cases}"
        )
    for sentence in card.errors:
        typer.echo(f"ungraded: {sentence}", err=True)
    if card.missing:
        typer.echo(
            f"no result for {len(card.missing)} case(s): {', '.join(card.missing[:8])}",
            err=True,
        )
    if card.unmatched:
        typer.echo(
            f"{len(card.unmatched)} result row(s) match no case in this corpus", err=True
        )


__all__ = ["app"]
