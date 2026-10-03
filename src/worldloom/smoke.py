"""One command that drives the whole pipeline on a tiny world, stage by stage.

    worldloom smoke --out ./smoke

Build, narrate through the agent handshake, render, validate, score the
retrieval baselines, generate enterprise eval cases, and run the reference
agent over them. Each stage is the real CLI command a user would type, run as
its own process, so what this proves is that the front door works end to end on
this installation, not that the library does. The suite proves the library.

Why a separate command when CI already runs each stage: the CI steps are spread
across a dozen jobs and each one exercises one stage richly. Nothing ran the
stages *in sequence, on each other's output*, so a change that broke the seam
between two of them (a case builder that could not read a freshly narrated
corpus, an evalrun that could not read the case builder's directory) surfaced
late, in whichever heavy step happened to cross it. This is that crossing, in
seconds, with the stage that failed named.

Timing is wall-clock and printed only. Nothing timed is written into a corpus,
a case set or a run, so the artifacts this produces are exactly the ones the
stages produce on their own.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

__all__ = [
    "DEFAULT_FORMATS",
    "SMOKE_CASE_LIMIT",
    "SMOKE_SEED",
    "SmokeFailure",
    "StageOutcome",
    "offline_responses",
    "run",
]

#: The default world: the seed every other CI step builds, without the
#: incident, which is the smallest world the retail engine makes.
SMOKE_SEED = 8128

#: Enough cases to cross several DAG shapes and both designed failure kinds
#: the default world grounds, and few enough that case generation stays a
#: few seconds. The exhaustive prefix, not the covering walk: covering scans
#: the whole candidate space before cutting to the limit and costs five times
#: as much for six rows.
SMOKE_CASE_LIMIT = 6

#: One prose format and one workbook: the two renderers whose failure modes
#: differ most (text substitution versus cell formulas). Overridable, because
#: a bare install has no openpyxl and should still be able to smoke itself.
DEFAULT_FORMATS: tuple[str, ...] = ("markdown", "xlsx")

#: The model id the offline writer's prose is committed under.
OFFLINE_WRITER_ID = "worldloom-smoke-offline-writer"


@dataclass(frozen=True)
class StageOutcome:
    """One stage's result: its name, how long it took, and what it said."""

    name: str
    seconds: float
    detail: str


class SmokeFailure(Exception):
    """A stage failed. Carries the stage name and the tail of what it printed."""

    def __init__(self, stage: str, seconds: float, reason: str, output: str = "") -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.seconds = seconds
        self.reason = reason
        self.output = output


def _cli(*args: str) -> list[str]:
    # The running interpreter, not a `worldloom` on PATH: a checkout with
    # several environments (or a venv not on PATH) would otherwise smoke a
    # different installation than the one that was asked.
    return [sys.executable, "-m", "worldloom.cli", *args]


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


def offline_responses(world: World) -> dict[str, Any]:
    """Answer every pending prose request with the built-in offline narrator.

    The same narrator `build --narrate` writes with (the composing narrator for
    a reader-grade corpus, the contract fixture otherwise), but routed through
    the handshake instead of around it: the answers are written as the
    responses document an agent would hand back, and committed by
    `narrate accept`, so the refusal path an agent's prose meets is the one
    this prose meets too.
    """
    from . import realism_profiles
    from .narrative import ComposedProvider, DeterministicProvider, handshake, prompts

    provider: Any = (ComposedProvider.for_world(world) if realism_profiles.reader_grade(world)
                     else DeterministicProvider())
    facts = {fact.id: fact for fact in world.facts}
    prompt = prompts.for_world(world)
    responses = []
    for request in handshake.pending(world):
        narrative = provider.complete(request, prompt, facts)
        responses.append({
            "id": f"{request.artifact_id}/{request.section}",
            "text": narrative.text,
            "claims": [
                {"text": claim.text, "supporting_fact_ids": list(claim.supporting_fact_ids)}
                for claim in narrative.claims
            ],
        })
    return {"responses": responses}


def run(
    out: Path,
    *,
    seed: int = SMOKE_SEED,
    formats: Sequence[str] = DEFAULT_FORMATS,
    case_limit: int = SMOKE_CASE_LIMIT,
    on_stage: Callable[[StageOutcome], None] | None = None,
) -> list[StageOutcome]:
    """Run every stage into *out*; raise `SmokeFailure` at the first that fails.

    *out* must not exist or must be empty: the stages write fixed subpaths
    (`corpus/`, `cases/`, `runs/reference/`), and a leftover from an earlier
    run would turn a stage that should create something into one that refuses
    to overwrite it, which reads as the pipeline being broken.
    """
    if out.exists() and any(out.iterdir()):
        raise SmokeFailure("setup", 0.0, f"{out} exists and is not empty")
    out.mkdir(parents=True, exist_ok=True)
    corpus = out / "corpus"
    cases = out / "cases"
    run_dir = out / "runs" / "reference"
    outcomes: list[StageOutcome] = []

    def stage(name: str, body: Callable[[], str]) -> None:
        started = time.perf_counter()
        try:
            detail = body()
        except SmokeFailure as failure:
            raise SmokeFailure(name, time.perf_counter() - started,
                               failure.reason, failure.output) from None
        except Exception as exc:  # a stage's own crash is a failed stage, named
            raise SmokeFailure(name, time.perf_counter() - started,
                               f"{type(exc).__name__}: {exc}") from exc
        outcome = StageOutcome(name, time.perf_counter() - started, detail)
        outcomes.append(outcome)
        if on_stage is not None:
            on_stage(outcome)

    def command(*args: str) -> str:
        completed = subprocess.run(
            _cli(*args), capture_output=True, text=True, check=False,
            # Wide and plain, so a failure's tail is readable rather than
            # soft-wrapped at eighty columns with colour codes in it.
            env={**os.environ, "COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb"},
        )
        if completed.returncode != 0:
            raise SmokeFailure(
                "", 0.0,
                f"`worldloom {' '.join(args)}` exited {completed.returncode}",
                _tail(completed.stdout + completed.stderr),
            )
        return completed.stdout

    def build() -> str:
        command("build", "--seed", str(seed), "--out", str(corpus))
        return f"seed {seed}"

    def narrate() -> str:
        from . import World

        requests_path = out / "requests.json"
        responses_path = out / "responses.json"
        command("narrate", "requests", str(corpus), "-o", str(requests_path))
        requested = json.loads(requests_path.read_text(encoding="utf-8"))["requests"]
        world = World.load(str(corpus))
        if not world.artifact_irs:
            world = world.compile()
        document = offline_responses(world)
        if len(document["responses"]) != len(requested):
            raise SmokeFailure(
                "", 0.0,
                f"{len(requested)} request(s) emitted but {len(document['responses'])}"
                " pending in the corpus: `narrate requests` and the corpus disagree",
            )
        responses_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        command("narrate", "accept", str(corpus), "--from", str(responses_path),
                "--model-id", OFFLINE_WRITER_ID)
        return f"{len(requested)} section(s) accepted through the handshake"

    def render() -> str:
        flags = [item for fmt in formats for item in ("-f", fmt)]
        command("render", str(corpus), *flags)
        return ", ".join(formats)

    def validate() -> str:
        command("validate", str(corpus))
        return "coherent"

    def evaluate() -> str:
        scorecard = json.loads(command("evaluate", str(corpus), "--retriever", "both", "--json"))
        scores = [
            f"{name} {result['overall']['passed']}/{result['overall']['total']}"
            for name, result in sorted(scorecard["retrievers"].items())
        ]
        return "; ".join(scores)

    def enterprise_cases() -> str:
        command("enterprise-evals", "build", str(corpus), str(cases),
                "--exhaustive", "--limit", str(case_limit))
        manifest = json.loads((cases / "manifest.json").read_text(encoding="utf-8"))
        proof = json.loads((cases / "proof.json").read_text(encoding="utf-8"))
        solvable = sum(1 for case in proof["cases"] if case.get("solvable"))
        return (f"{manifest['queries']} case(s), {solvable} proved solvable;"
                f" case set {proof['case_set']}")

    def evalrun() -> str:
        command("evalrun", "run", str(cases), "-o", str(run_dir))
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        # The reference agent is the executable ceiling: it replays each
        # case's gold DAG. Anything below a full pass is a case the generator
        # promised was solvable and the grader says is not, which is exactly
        # the seam this command exists to cross.
        if summary["passed"] != summary["cases"] or summary.get("errors"):
            raise SmokeFailure(
                "", 0.0,
                f"the reference agent passed {summary['passed']} of {summary['cases']}"
                f" case(s) with {summary.get('errors', 0)} error(s); it must pass every one",
            )
        means = summary["means"]
        return (f"reference {summary['passed']}/{summary['cases']}; plan {means['plan']},"
                f" trajectory {means['trajectory']}, outcomes {means['outcomes']}")

    stage("build", build)
    stage("narrate", narrate)
    stage("render", render)
    stage("validate", validate)
    stage("evaluate", evaluate)
    stage("enterprise-evals", enterprise_cases)
    stage("evalrun", evalrun)
    return outcomes

