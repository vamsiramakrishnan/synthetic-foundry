"""CLI for the synthesis SDK. Every command delegates to a library operation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

import typer

app = typer.Typer(no_args_is_help=True, help="Generate relational operational records from executable causal specifications.")
P = ParamSpec("P")
R = TypeVar("R")


def _refusals(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        from rich.markup import escape

        from .cli import _refuse, _refuse_exec_error
        from .execseam import ExecError
        from .synthesis.models import SynthesisError
        try:
            return function(*args, **kwargs)
        except SynthesisError as error:
            _refuse("synthesis_failed", escape(str(error)), finding=error.finding.model_dump(mode="json"))
        except ExecError as error:
            _refuse_exec_error(error)
        except (OSError, ValueError) as error:
            _refuse("synthesis_failed", escape(str(error)), finding={"code": "synthesis_input"})
    return wrapped


@app.command("example")
@_refusals
def example(vertical: str, output: Path, entities: int = 8, ticks: int = 30) -> None:
    """Write an editable retail or banking specification; refuse to overwrite."""
    from .synthesis.models import SynthesisError
    from .synthesis.programs import banking, retail
    from .synthesis.storage import write_program

    if vertical not in {"retail", "banking"}:
        raise SynthesisError("unknown_vertical", vertical)
    program = retail(stores=entities, ticks=ticks) if vertical == "retail" else banking(borrowers=entities, ticks=ticks)
    write_program(program, output)
    typer.echo(str(output))


@app.command("check")
@_refusals
def check(specification: Path) -> None:
    """Check graph, expressions, constraints and resource budgets before generation."""
    from .synthesis.compiler import compile_program
    from .synthesis.storage import read_program

    compiled = compile_program(read_program(specification))
    typer.echo(json.dumps({"program_digest": compiled.program_digest, "rows": compiled.rows,
                           "expression_work_upper_bound": compiled.work}, sort_keys=True))


@app.command("build")
@_refusals
def build(specification: Path, output: Path, seed: int = 8128,
          shard_index: int = 0, shard_count: int = 1, resume: bool = False) -> None:
    """Generate a checksummed JSONL export. Resume verifies, rather than trusts, existing output."""
    from .synthesis.engine import Simulator
    from .synthesis.storage import export, read_program

    manifest = export(Simulator(read_program(specification), seed=seed), output,
                      shard_index=shard_index, shard_count=shard_count, resume=resume)
    typer.echo(manifest.model_dump_json())


@app.command("verify")
@_refusals
def verify(directory: Path) -> None:
    """Replay the recipe and verify every record, identifier and byte commitment."""
    from .synthesis.storage import verify_export

    typer.echo(verify_export(directory).model_dump_json())


@app.command("merge")
@_refusals
def merge(output: Path, shards: list[Path]) -> None:
    """Verify a complete shard set and merge in canonical order."""
    from .synthesis.storage import merge_exports

    typer.echo(merge_exports(shards, output).model_dump_json())


@app.command("intervene")
@_refusals
def intervene(directory: Path, interventions: Path, output: Path) -> None:
    """Build a paired world using a JSON array of explicit do-interventions."""
    from .synthesis.models import Intervention, SynthesisError
    from .synthesis.storage import _small_file, export, load_simulator

    raw = json.loads(_small_file(interventions, 1_000_000))
    if not isinstance(raw, list):
        raise SynthesisError("intervention_contract", "expected an array")
    changes = tuple(Intervention.model_validate(item) for item in raw)
    simulated = load_simulator(directory).counterfactual(*changes)
    typer.echo(export(simulated, output).model_dump_json())


@app.command("compare")
@_refusals
def compare(directory: Path, counterfactual: Path) -> None:
    """Emit exact paired cell deltas as JSONL; reject mismatched populations."""
    from .synthesis.compiler import canonical
    from .synthesis.engine import compare as compare_runs
    from .synthesis.storage import load_simulator

    for change in compare_runs(load_simulator(directory), load_simulator(counterfactual)):
        typer.echo(canonical(asdict(change)).decode("utf-8"), nl=False)


@app.command("search")
@_refusals
def search(specification: Path, output: Path, proposals: int = 32,
           evaluator: Path | None = None) -> None:
    """Evolve bounded parameters, retain behavior niches, then audit held-out seeds."""
    from .synthesis.compiler import canonical
    from .synthesis.models import SynthesisError
    from .synthesis.search import SearchPlan, banking_search_plan, retail_search_plan
    from .synthesis.search import search as run_search
    from .synthesis.storage import _small_file, read_program

    program = read_program(specification)
    if evaluator:
        plan = SearchPlan.model_validate_json(_small_file(evaluator, 1_000_000))
    elif program.namespace == "retail_operations":
        plan = retail_search_plan(proposals=proposals)
    elif program.namespace == "loan_servicing":
        plan = banking_search_plan(proposals=proposals)
    else:
        raise SynthesisError("evaluator_required", "custom programs need an operator-owned evaluator")
    if output.exists():
        raise SynthesisError("destination_exists", str(output))
    report = run_search(program, plan)
    with output.open("xb") as stream:
        stream.write(canonical(report.model_dump(mode="json")))
    typer.echo(json.dumps({"evaluated": report.evaluated, "niches": len(report.champions),
                           "holdout_accepted": sum(c.holdout.accepted for c in report.champions)}, sort_keys=True))


@app.command("team")
@_refusals
def team(specification: Path, evaluator: Path, agents: Path, output: Path,
         replay_ledger: Path | None = None, checkpoint: Path | None = None) -> None:
    """Run configured designer/critic executables, or replay their ledger without calls.

    AGENTS is {"designers": [{"name": ..., "command": ..., "version": ...}],
    "critics": [...]}. Commands execute with this process's privileges.
    """
    from .synthesis.compiler import canonical
    from .synthesis.harness import Agent, CheckpointLedger, LedgerEntry, run_team
    from .synthesis.models import SynthesisError
    from .synthesis.search import SearchPlan
    from .synthesis.storage import _small_file, read_program

    raw = json.loads(_small_file(agents, 64_000))
    if not isinstance(raw, dict) or set(raw) - {"designers", "critics"}:
        raise SynthesisError("team_contract", "expected designers and optional critics")
    designers = tuple(Agent.model_validate(item) for item in raw.get("designers", []))
    critics = tuple(Agent.model_validate(item) for item in raw.get("critics", []))
    store = CheckpointLedger(checkpoint) if checkpoint else None
    entries = store.read() if store else ()
    if replay_ledger:
        data = json.loads(_small_file(replay_ledger, 16_000_000))
        if not isinstance(data, dict) or not isinstance(data.get("ledger"), list):
            raise SynthesisError("ledger_contract", "expected a team report with a ledger array")
        entries += tuple(LedgerEntry.model_validate(item) for item in data["ledger"])
    if output.exists():
        raise SynthesisError("destination_exists", str(output))
    report = run_team(read_program(specification),
                      SearchPlan.model_validate_json(_small_file(evaluator, 1_000_000)),
                      designers, critics=critics, ledger=entries, replay=replay_ledger is not None,
                      on_entry=store.append if store else None)
    with output.open("xb") as stream:
        stream.write(canonical(report.model_dump(mode="json")))
    typer.echo(json.dumps({"attempts": len(report.attempts), "champions": len(report.champions),
                           "ledger_entries": len(report.ledger)}, sort_keys=True))
