"""Offline adapters for blind readers and provenance-bearing calibration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from .narrative.reader_checks import ReaderPlan
    from .world import World

readers_app = typer.Typer(no_args_is_help=True, help="Check whether independent readers recover the corpus's evidence.")
calibration_app = typer.Typer(no_args_is_help=True, help="Ingest observed cohort trials and measure held-out calibration.")


def _parse_json(text: str) -> Any:
    import json
    import math

    def finite(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON number")
        return number

    def constant(value: str) -> Any:
        raise ValueError(f"nonfinite JSON constant: {value}")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    return json.loads(text, parse_float=finite, parse_constant=constant, object_pairs_hook=unique)


def _document(path: Path) -> Any:
    from rich.markup import escape

    from .cli import _refuse

    try:
        return _parse_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _refuse("unreadable_document", f"{escape(str(path))}: {escape(str(error))}", path=str(path))


def _emit(document: dict[str, Any], out: Path | None = None) -> None:
    import json

    from rich.markup import escape

    from .cli import _refuse
    from .corpus import write_json

    if out is None:
        typer.echo(json.dumps(document, sort_keys=True, indent=2, allow_nan=False))
    else:
        try:
            write_json(out, document)
        except OSError as error:
            _refuse("workspace_unwritable", escape(str(error)), path=str(out))


def _reader_plan(
    world: World, reader_id: str, reader_config: Path | None,
    critical_facts: list[str] | None, eval_instances: list[Path] | None, share: float,
) -> ReaderPlan:
    from rich.markup import escape

    from .cli import _refuse
    from .eval_instances import EvalInstance
    from .narrative import reader_checks

    config = {} if reader_config is None else _document(reader_config)
    if not isinstance(config, dict):
        _refuse("unreadable_document", "reader configuration must be a JSON object")
    instances = []
    for path in eval_instances or ():
        document = _document(path)
        try:
            instances.append(EvalInstance.model_validate(document))
        except ValueError as error:
            _refuse("unreadable_document", f"{escape(str(path))}: {escape(str(error))}", path=str(path))
    try:
        return reader_checks.plan(
            world, reader_id=reader_id, reader_config=config,
            critical_fact_ids=critical_facts or (), instances=instances, share=share,
        )
    except ValueError as error:
        _refuse("reader_plan_rejected", escape(str(error)))


@readers_app.command("requests")
def reader_requests(
    corpus: Annotated[str, typer.Argument(help="Narrated corpus path or bundled name.")],
    reader_id: Annotated[str, typer.Option("--reader-id", help="Independent reader identity; include the model and prompt version.")],
    reader_config: Annotated[Path | None, typer.Option("--reader-config", help="JSON reader configuration, sealed into the private check plan.")] = None,
    critical_facts: Annotated[list[str] | None, typer.Option("--critical-fact", help="Fact that every accepted check must recover; repeat as needed.")] = None,
    eval_instances: Annotated[list[Path] | None, typer.Option("--eval-instance", help="EvalInstance JSON whose complete oracle supplies critical targets; repeat as needed.")] = None,
    share: Annotated[float, typer.Option("--share", min=0, max=1, help="Additional background section sample, after complete critical coverage.")] = .05,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Public request JSON; defaults to stdout.")] = None,
) -> None:
    """Emit blind passages and response schema; checker targets stay private."""
    from .cli import _load, _refuse

    planned = _reader_plan(_load(corpus), reader_id, reader_config, critical_facts, eval_instances, share)
    if planned.issues:
        _refuse("reader_plan_rejected", "reader targets cannot be checked against this corpus",
                findings=[issue.model_dump(mode="json") for issue in planned.issues])
    _emit(planned.requests_document(), out)


@readers_app.command("accept")
def reader_accept(
    corpus: Annotated[Path, typer.Argument(help="Narrated corpus directory; its reader ledger is updated in place.")],
    reader_id: Annotated[str, typer.Option("--reader-id", help="Same independent reader identity as requests.")],
    source: Annotated[Path | None, typer.Option("--from", "-i", help="Reader response array or {responses: [...]}; omit only to replay accepted evidence.")] = None,
    reader_config: Annotated[Path | None, typer.Option("--reader-config", help="Same JSON reader configuration as requests.")] = None,
    critical_facts: Annotated[list[str] | None, typer.Option("--critical-fact", help="Same critical facts as requests; repeat as needed.")] = None,
    eval_instances: Annotated[list[Path] | None, typer.Option("--eval-instance", help="Same EvalInstance JSON paths as requests; repeat as needed.")] = None,
    share: Annotated[float, typer.Option("--share", min=0, max=1, help="Same background sample as requests.")] = .05,
) -> None:
    """Persist the complete reader verdict, including rejected evidence."""
    from rich.markup import escape

    from .cli import _load, _refuse
    from .corpus import bundled_examples_dir
    from .narrative import reader_checks

    # Review receipts are generation inputs. Bundled examples are immutable
    # reference corpora, so an operator must copy one before adding a receipt.
    if not corpus.is_dir() or corpus.resolve().is_relative_to(bundled_examples_dir().resolve()):
        _refuse("workspace_unwritable", "reader acceptance requires a writable corpus copy outside bundled examples",
                path=str(corpus))
    world = _load(str(corpus))
    planned = _reader_plan(world, reader_id, reader_config, critical_facts, eval_instances, share)
    document = [] if source is None else _document(source)
    if isinstance(document, dict) and set(document) == {"responses"}:
        document = document["responses"]
    if not isinstance(document, list):
        _refuse("unreadable_document", "reader responses must be an array or an object containing only responses")
    try:
        responses = tuple(reader_checks.ReaderResponse.model_validate(row) for row in document)
    except ValueError as error:
        _refuse("unreadable_document", escape(str(error)), path=str(source))
    try:
        accepted = reader_checks.accept(world, planned, responses)
    except ValueError as error:
        _refuse("reader_check_rejected", escape(str(error)))
    try:
        accepted.world.export(corpus, overwrite=True)
    except OSError as error:
        _refuse("workspace_unwritable", escape(str(error)), path=str(corpus))
    _emit({"accepted": accepted.review.passed, "replayed": accepted.replayed,
           "reader_calls": accepted.reader_calls, "review": accepted.review.model_dump(mode="json")})
    if not accepted.review.passed:
        _refuse("reader_check_rejected", "reader evidence was rejected; its replies and findings are recorded in the corpus",
                exit_code=3, plan_id=planned.id, path=str(corpus))


@calibration_app.command("ingest")
def calibration_ingest(
    source: Annotated[Path, typer.Option("--from", "-i", help="Observed CalibrationObservation JSON/JSONL; no outcomes are generated here.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Immutable calibration snapshot destination; exact replay is allowed.")],
    resume: Annotated[Path | None, typer.Option("--resume", help="Previous snapshot to extend into a new destination.")] = None,
) -> None:
    """Validate provenance and split isolation, then save an identified snapshot."""
    from rich.markup import escape

    from .cli import _refuse
    from .eval_metrics import (
        CalibrationObservation,
        CalibrationSnapshot,
        DifficultyCalibrator,
    )

    try:
        text = source.read_text(encoding="utf-8")
        document = ([_parse_json(line) for line in text.splitlines() if line.strip()]
                    if source.suffix.lower() == ".jsonl" else _parse_json(text))
        if isinstance(document, dict):
            document = document["observations"] if set(document) == {"observations"} else [document]
        if not isinstance(document, list) or not document:
            raise ValueError("at least one observation is required")
        observations = tuple(CalibrationObservation.model_validate(row) for row in document)
    except (OSError, ValueError) as error:
        _refuse("unreadable_document", f"{escape(str(source))}: {escape(str(error))}", path=str(source))
    try:
        calibrator = (DifficultyCalibrator() if resume is None else
                      DifficultyCalibrator.from_snapshot(CalibrationSnapshot.model_validate(_document(resume))))
        added = sum(calibrator.ingest(row) for row in observations)
        snapshot = calibrator.snapshot()
        if out.exists():
            existing = DifficultyCalibrator.from_snapshot(CalibrationSnapshot.model_validate(_document(out))).snapshot()
            if existing != snapshot:
                _refuse("destination_exists", "calibration snapshots are immutable; use a new --out path",
                        destination=str(out))
        else:
            calibrator.export(out)
    except ValueError as error:
        _refuse("calibration_rejected", escape(str(error)))
    except OSError as error:
        _refuse("workspace_unwritable", escape(str(error)), path=str(out))
    _emit({"snapshot": str(out), "digest": snapshot.digest, "observations": len(snapshot.observations),
           "added": added, "replayed": len(observations) - added,
           "cohorts": sorted({row.cohort for row in snapshot.observations})})


@calibration_app.command("report")
def calibration_report(
    snapshot_path: Annotated[Path, typer.Argument(help="Verified calibration snapshot.")],
    cohort: Annotated[str, typer.Option("--cohort", help="Exact cohort identity to measure.")],
    split: Annotated[str, typer.Option("--split", help="Held-out split: holdout or validation; never trains predictions.")] = "holdout",
    min_trials: Annotated[int, typer.Option("--min-trials", min=1, help="Training observations required for a fitted slice.")] = 20,
    bins: Annotated[int, typer.Option("--bins", min=1, max=100, help="Probability bins for expected calibration error.")] = 10,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Report JSON; defaults to stdout.")] = None,
) -> None:
    """Expose support, uncertainty and held-out scoring against training only."""
    from rich.markup import escape

    from .cli import _refuse
    from .eval_metrics import CalibrationSnapshot, DifficultyCalibrator

    if out is not None and out.resolve() == snapshot_path.resolve():
        _refuse("destination_exists", "a report cannot replace its immutable calibration snapshot",
                destination=str(out))
    document = _document(snapshot_path)
    try:
        calibrator = DifficultyCalibrator.from_snapshot(CalibrationSnapshot.model_validate(document))
        snapshot = calibrator.snapshot()
        features = {(row.features.feature_schema, row.features.slice_key): row.features
                    for row in snapshot.observations if row.cohort == cohort}
        features.update({(row.features.feature_schema, row.features.slice_key): row.features
                         for row in snapshot.legacy_counts if row.cohort == cohort})
        if not features:
            raise ValueError(f"unknown calibration cohort: {cohort}")
        report = calibrator.report(cohort, split=split, bins=bins, min_trials=min_trials)
        estimates = [calibrator.estimate(cohort, value, min_trials=min_trials).model_dump(mode="json")
                     for _, value in sorted(features.items())]
    except ValueError as error:
        _refuse("calibration_rejected", escape(str(error)))
    _emit({"training_estimates": estimates, "report": report.model_dump(mode="json")}, out)


__all__ = ["readers_app", "calibration_app"]
