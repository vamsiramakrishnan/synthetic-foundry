"""Which commands to run, by what you are testing: the CLI's front door.

    worldloom guide            # one line per goal
    worldloom guide agent      # the ordered commands for one goal
    worldloom guide --json     # the same table, as data for an agent

The CLI has more than fifty top-level commands, and six of them evaluate
something (`evaluate`, `evals`, `benchmark`, `enterprise-evals`,
`native-evals`, `evalrun`). Each answers a different question, and nothing in
`worldloom --help` says which question. Choosing by name goes wrong in
predictable ways: `evaluate` scores retrievers, not agents, and `benchmark`
scores a reader over retrieved passages, not an agent over connectors.

This module is the answer as data: one declarative table of goals, each an
ordered command sequence a reader can paste. It is data rather than prose so
`tests/test_guide.py` can parse every command against the real Typer app and
refuse one that names a missing command or flag. A guide that drifts from the
CLI is worse than none: it sends a new user to a refusal on their first try.

Conventions every sequence follows, so they compose: `./corpus` is the world
corpus, `./cases` an enterprise case set, `./runs/<name>` a run directory, and
seed 8128 is the seed the README, AGENTS.md and the smoke all build. Paths
prefixed `./` are outputs or placeholders; a path without the prefix is a file
shipped in a checkout, and the test requires it to exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "EVALUATION_COMMANDS",
    "GOALS",
    "GUIDE_SCHEMA",
    "EvaluationCommand",
    "Goal",
    "Route",
    "Step",
    "goal",
    "goal_text",
    "manifest",
    "overview_text",
]

#: The `--json` payload's schema tag. Bump the version when a field changes
#: meaning, as `worldloom.seams/v1` does; adding a goal is not such a change.
GUIDE_SCHEMA = "worldloom.guide/v1"


@dataclass(frozen=True)
class Step:
    """One command and the reason it is in the sequence."""

    command: str
    why: str

    def as_dict(self) -> dict[str, str]:
        return {"command": self.command, "why": self.why}


@dataclass(frozen=True)
class Route:
    """Another way through the same goal, replacing some of its steps."""

    when: str
    steps: tuple[Step, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"when": self.when, "steps": [step.as_dict() for step in self.steps]}


@dataclass(frozen=True)
class Goal:
    """What someone is testing, and the commands that test it, in order.

    *setup* produces the inputs (a corpus, a case set) and can be skipped when
    the reader already has them; *steps* are the goal's own commands. The
    split is what lets the overview name a useful first command: most goals
    start from `worldloom build`, so the first command overall would tell a
    reader nothing about which goal they are in. *first_command* is the first
    step without its arguments, as the overview table and the README print it.
    """

    id: str
    summary: str
    first_command: str
    setup: tuple[Step, ...]
    steps: tuple[Step, ...]
    read_next: str
    alternatives: tuple[Route, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "first_command": self.first_command,
            "setup": [step.as_dict() for step in self.setup],
            "steps": [step.as_dict() for step in self.steps],
            "alternatives": [route.as_dict() for route in self.alternatives],
            "read_next": self.read_next,
        }


@dataclass(frozen=True)
class EvaluationCommand:
    """A top-level command that evaluates something, and the goals that use it."""

    command: str
    goals: tuple[str, ...]
    answers: str

    def as_dict(self) -> dict[str, Any]:
        return {"command": self.command, "goals": list(self.goals), "answers": self.answers}


_BUILD = "worldloom build --seed 8128 --incident --out ./corpus"
_BUILD_NARRATED = "worldloom build --seed 8128 --incident --narrate --out ./corpus"

GOALS: tuple[Goal, ...] = (
    Goal(
        id="rag",
        summary="Retrieval and cited answers",
        first_command="worldloom evaluate",
        setup=(
            Step(_BUILD_NARRATED, "A month-end close with an incident and deterministic prose; no model service or credentials."),
            Step("worldloom render ./corpus -f markdown -f pdf", "The files your retrieval system ingests."),
            Step("worldloom validate ./corpus", "Every document, fact and expected answer agrees before anything is scored."),
        ),
        steps=(
            Step("worldloom evaluate ./corpus --retriever both", "BM25 and TF-IDF baselines per question family: the floor a retriever has to beat."),
            Step("worldloom evals passages ./corpus -o passages.jsonl", "The passages the baselines rank, with stable ids: index their `text` in your own system."),
            Step("worldloom evals export ./corpus -o evals.jsonl", "Questions, expected answers and evidence fact ids; `--format ragas` or `--format promptfoo` for those harnesses."),
            Step("worldloom evaluate ./corpus --predictions predictions.jsonl", 'Your system\'s rankings, one `{"id", "passage_ids"}` line per question, graded by the scorer the baselines use.'),
            Step('worldloom benchmark run ./corpus --exec "python3 my_reader.py"', "Your reader over the same questions: it gets the top passages, returns passage ids, and is scored on ids alone."),
        ),
        read_next=".claude/skills/worldloom/references/evaluating.md",
    ),
    Goal(
        id="documents",
        summary="Rendered DOCX, XLSX, PPTX and PDF files",
        first_command="worldloom render",
        setup=(
            Step(_BUILD_NARRATED, "A month-end close with an incident and deterministic prose; no model service or credentials."),
        ),
        steps=(
            Step("worldloom render ./corpus -f docx -f xlsx -f pptx -f pdf", "Write the files; `worldloom doctor` names any missing renderer extra."),
            Step("worldloom validate ./corpus", "Every figure in every file resolves to the same canonical fact."),
            Step("worldloom inspect ./corpus --artifacts", "Each file with its type, author, authority, supporting facts and path."),
        ),
        read_next="docs/artifact-compiler.md",
    ),
    Goal(
        id="agent",
        summary="An agent working across MCP connectors",
        first_command="worldloom enterprise-evals build",
        setup=(
            Step(_BUILD, "The company whose records the connector cases are drawn from."),
        ),
        steps=(
            Step("worldloom enterprise-evals build ./corpus ./cases --exhaustive --limit 50", "Multi-connector cases (Jira, ServiceNow, SharePoint and others, emulated), each proved solvable."),
            Step("worldloom evalrun run ./cases -o ./runs/reference", "The reference agent replays each gold plan: the case set's ceiling, not a model's score."),
            Step("worldloom evalrun run ./cases -o ./runs/mine --harness claude", 'Your agent: --harness codex, or --exec "python3 my_agent.py" for an adapter of your own.'),
            Step("worldloom evalrun summarize ./runs/mine", "Pass count and the mean of each axis: plan, trajectory, outcomes."),
            Step("worldloom evalrun autopsy ./runs/mine --reference-run ./runs/reference", "Failing cases clustered by finding, each finding attributed to agent, interface, world or grader."),
        ),
        read_next="docs/eval-execution.md",
    ),
    Goal(
        id="native",
        summary="Byte-graded DOCX, PPTX and XLSX file tasks",
        first_command="worldloom native-evals build",
        setup=(
            Step(_BUILD_NARRATED, "The company whose accepted prose and facts the files are built from."),
            Step(
                "worldloom corpus-scale build ./corpus --fact FACT-0031 --rows 10000 --profile development --xlsx --out ./large-corpus",
                "Native files and transaction tables bound to the company's facts; FACT-0031 is seed 8128's company revenue.",
            ),
        ),
        steps=(
            Step(
                "worldloom native-evals build ./corpus ./large-corpus --plan docs/examples/native-discovery-workload.json --out ./benchmark",
                "Read, analyse, update and create tasks from a workload plan, each reference-graded on the actual bytes.",
            ),
            Step("worldloom native-evals inspect ./benchmark", "Execution readiness, requested coverage and promotion support, reported separately."),
            Step("worldloom native-evals protocol --out ./target-protocol.json", "The JSON exchange your harness adapter implements."),
            Step(
                'worldloom native-evals run ./benchmark --command "python3 my_target.py" --out ./runs/native',
                "Your harness on task-scoped public inputs; the files it submits are regraded independently.",
            ),
        ),
        read_next="docs/native-benchmark-workflow.md",
    ),
    Goal(
        id="improve",
        summary="Improving an agent, judged on held-out cases",
        first_command="worldloom evalrun improve",
        setup=(
            Step(_BUILD, "The company whose records the connector cases are drawn from."),
            Step("worldloom enterprise-evals build ./corpus ./cases --exhaustive --limit 200", "The cases the agent trains and is judged on."),
        ),
        steps=(
            Step(
                "worldloom evalrun improve ./cases --agent-pack agent:baseline --harness claude --proposer-harness claude --rounds 3 -o ./improve",
                "Each round clusters the champion's failures and has the proposer revise the pack. A revision is kept only "
                "if it wins on the training cases and then on a held-back share of ./cases. Writes ./improve/improve.json.",
            ),
        ),
        alternatives=(
            Route(
                "For held-out cases from an independently built world instead of a share of ./cases, replace the improve step with:",
                (
                    Step("worldloom build --seed 8129 --incident --out ./fresh-corpus", "A second world from a fresh seed."),
                    Step("worldloom enterprise-evals build ./fresh-corpus ./holdout-cases --exhaustive --limit 50", "Its cases, which training never sees."),
                    Step(
                        "worldloom evalrun audit-split ./cases --holdout-corpus ./holdout-cases --source-origin seed-8128 --holdout-origin seed-8129",
                        "Exits non-zero when evidence or lineage crosses the train/held-out boundary.",
                    ),
                    Step(
                        "worldloom evalrun improve ./cases --holdout-corpus ./holdout-cases --agent-pack agent:baseline --harness claude --proposer-harness claude --rounds 3 -o ./improve",
                        "The same loop, judged on the other world's cases.",
                    ),
                ),
            ),
        ),
        read_next="docs/self-improvement.md",
    ),
    Goal(
        id="company",
        summary="One particular company, described and built",
        first_command="worldloom pack spec",
        setup=(),
        steps=(
            Step("worldloom pack spec", "The specification's fields, and the registry each one draws on."),
            Step("worldloom pack spec --template > company.json", "A starter to edit: industry, geography, facets, organisation, leadership."),
            Step("worldloom build --spec company.json --seed 8128 --out ./corpus", "Resolve the description and build it; a description that contradicts itself is refused, naming both claims."),
            Step("worldloom status ./corpus", "The stage the corpus is at, and the exact command that comes next."),
        ),
        alternatives=(
            Route(
                "Or interview a coding harness into the whole world (company, lines of business, people, processes, paperwork, history) and its evals per employee level:",
                (
                    Step("worldloom interview run ./interview --harness claude", "--script examples/interviews/kestrel-vale.json replays a recorded interview offline."),
                    Step("worldloom interview build ./interview ./world", "Build, narrate, render and validate the world, then generate and prove eval cases per level."),
                ),
            ),
            Route(
                "Or keep one persistent company, with revisions, in the local Studio console:",
                (
                    Step("worldloom studio serve --workspace ./worldloom-workspace", "Serves the console at http://127.0.0.1:8765. It has no authentication, so keep it on a loopback address."),
                ),
            ),
        ),
        read_next="docs/agents/company-specification.md",
    ),
    Goal(
        id="narrate",
        summary="Prose from your own model, checked against facts",
        first_command="worldloom narrate requests",
        setup=(
            Step(_BUILD, "Without --narrate, so every section waits for prose."),
        ),
        steps=(
            Step("worldloom narrate requests ./corpus -o requests.json", "One bounded request per section: allowed facts, author, audience, knowledge cutoff."),
            Step(
                "worldloom narrate accept ./corpus --from responses.json --model-id my-writer",
                "Your writer turns requests.json into responses.json, every figure written as {{fact:ID}}. "
                "A rejection names the rule it broke: fix that and resubmit.",
            ),
            Step("worldloom render ./corpus -f docx -f markdown", "Files with the accepted prose in them."),
            Step("worldloom validate ./corpus", "Every claim in the prose still agrees with the corpus."),
        ),
        alternatives=(
            Route(
                "Or, instead of requests and accept, let an installed coding harness write with its own login until every section is accepted:",
                (Step("worldloom narrate loop ./corpus --harness claude", "--harness codex works the same way."),),
            ),
            Route(
                "Or drive any executable the same way:",
                (Step('worldloom narrate loop ./corpus --exec "python3 my_writer.py" --model-id my-writer', "Requests JSON on stdin, responses JSON on stdout, one round per call."),),
            ),
        ),
        read_next="docs/agents/writing-responses.md",
    ),
    Goal(
        id="python",
        summary="Worlds composed in Python",
        first_command="from worldloom import sdk",
        setup=(),
        steps=(
            Step(
                "python -c \"from worldloom import sdk; built = sdk.company('retail', seed=8128).build().episodes('2026-03', incident=True); print(built.ok, built.measure())\"",
                "One world from a blueprint, validated and measured. The SDK is for loops over many blueprints, which no single command expresses.",
            ),
            Step("worldloom seams", "The library seams a harness can compose (connectors, evals, evalrun, benchmarks, pipeline) and their imports."),
        ),
        read_next="docs/sdk.md",
    ),
)

#: The top-level commands that evaluate something, side by side. Six of them
#: is the confusion this module exists for, so the overview prints this table
#: under the goals rather than leaving the reader to infer it from them.
EVALUATION_COMMANDS: tuple[EvaluationCommand, ...] = (
    EvaluationCommand("evaluate", ("rag",), "Built-in retrievers on the corpus's own questions."),
    EvaluationCommand("evals", ("rag",), "The evaluation set and its passages: export them, or construct or compile it."),
    EvaluationCommand("benchmark", ("rag",), "Your reader on those questions, scored by passage id."),
    EvaluationCommand("enterprise-evals", ("agent", "improve"), "Multi-connector agent cases, each proved solvable."),
    EvaluationCommand("evalrun", ("agent", "improve"), "Agent runs graded on plan, trajectory and outcomes."),
    EvaluationCommand("native-evals", ("native",), "DOCX, PPTX and XLSX file tasks, graded on the bytes."),
)


def goal(name: str) -> Goal | None:
    """The goal called *name*, case-insensitively, or None."""
    wanted = name.strip().lower()
    return next((item for item in GOALS if item.id == wanted), None)


def manifest() -> dict[str, Any]:
    """Every goal and every evaluation command, as `worldloom guide --json` prints it."""
    return {
        "schema": GUIDE_SCHEMA,
        "goals": [item.as_dict() for item in GOALS],
        "evaluation_commands": [item.as_dict() for item in EVALUATION_COMMANDS],
    }


def _columns(rows: list[tuple[str, ...]]) -> list[str]:
    """Rows as left-aligned columns, two spaces apart, each row one line.

    Plain text on purpose: a Rich table soft-wraps at the terminal's width, and
    a first command broken over two lines is one a reader cannot paste.
    """
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]) - 1)]
    return [
        "  " + "  ".join([*(cell.ljust(width) for cell, width in zip(row[:-1], widths, strict=True)), row[-1]])
        for row in rows
    ]


def overview_text() -> str:
    """The table `worldloom guide` prints with no goal."""
    lines = ["What are you testing? `worldloom guide GOAL` prints its commands in order.", ""]
    lines += _columns([("GOAL", "FOR", "FIRST COMMAND"),
                       *((item.id, item.summary, item.first_command) for item in GOALS)])
    lines += ["", "The commands that evaluate something answer different questions:", ""]
    lines += _columns([(f"worldloom {item.command}", ", ".join(item.goals), item.answers)
                       for item in EVALUATION_COMMANDS])
    lines += ["", "Every option of a command: `worldloom COMMAND --help`."]
    return "\n".join(lines)


def _steps_text(steps: tuple[Step, ...]) -> list[str]:
    lines: list[str] = []
    for step in steps:
        lines += [f"  # {step.why}", f"  {step.command}", ""]
    return lines


def goal_text(item: Goal) -> str:
    """The ordered commands `worldloom guide GOAL` prints.

    Each command sits on its own line under a `#` comment saying why it is
    there, so any run of lines pastes into a shell as it stands.
    """
    lines = [f"{item.id}: {item.summary}", ""]
    if item.setup:
        lines += ["Setup (skip a step whose output you already have):", ""]
        lines += _steps_text(item.setup)
    lines += ["Steps:", ""]
    lines += _steps_text(item.steps)
    for route in item.alternatives:
        lines += [route.when, ""]
        lines += _steps_text(route.steps)
    lines += [f"Read next: {item.read_next}"]
    return "\n".join(lines)
