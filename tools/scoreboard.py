#!/usr/bin/env python3
"""The release scoreboard: fixed inputs, pinned case set, byte-identical output.

    python tools/scoreboard.py                        # writes docs/measurements/
    python tools/scoreboard.py --revision "$GITHUB_SHA" --out-dir scoreboard/

Builds one corpus from a fixed seed, scores the built-in retrieval baselines
against its evaluation set (`worldloom evaluate`), generates a fixed enterprise
case set from it, and runs the built-in agents over that set (`worldloom
evalrun run`): the reference agent, which replays each case's gold DAG and is
the executable ceiling, and the lazy agent, which calls nothing and is the
floor. Writes `release-scoreboard.json` and `release-scoreboard.md`.

Every input is a constant in this file, so the only thing a release changes
is the code under measurement. The case set is pinned by digest: when the
generated cases move, the numbers are about different questions and comparing
them with the last release's would be comparing two benchmarks, so the script
refuses (exit 1) and says so. Moving the pin is a deliberate edit to
`PINNED_CASE_SET` here, in the same change that moved the generator, and the
old and new scoreboards are then not comparable by construction.

Same inputs, same bytes: nothing time-dependent is written. The one
run-dependent field is `revision`, which is whatever the caller passes (the
current `git rev-parse HEAD` by default). Paths are recorded relative to the
scratch directory, never absolute, and evalrun runs untimed.

Like every script in `tools/`, this is stdlib-only and imports nothing from
`src/`: each stage is the real `worldloom` command, run under this
interpreter with the checkout's `src/` on its path, so the scoreboard measures
the same front door a user drives.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = "worldloom.release-scoreboard/v1"

#: The world. The seed, incident and narration every retrieval CI step uses,
#: so the retrieval rows here are the numbers those steps assert stay low.
SEED = 8128
BUILD_ARGS = ("--seed", str(SEED), "--incident", "--narrate")

#: Lexical baselines only. `all` would add the embedding retriever wherever
#: its model happens to be installed, and the scoreboard would then differ by
#: machine rather than by revision.
RETRIEVERS = "both"

#: The case set: the exhaustive prefix across every DAG shape the world can
#: ground. Large enough to reach every shape and designed failure the default
#: world supports; small enough to run in seconds.
CASE_LIMIT = 48
_ENTRY = "from worldloom.cli import app; app(windows_expand_args=False)"
CASE_ARGS = ("--exhaustive", "--limit", str(CASE_LIMIT), "--dag-shape", "*")

#: `worldloom.evalrun.runner.case_set_digest` of the cases above, as
#: `evalrun run` records it in run.json. See the module docstring for when it
#: may move.
PINNED_CASE_SET = "d04e4d529c910fe26bead98e422d8326"

#: The built-in agents, ceiling first.
AGENTS = ("reference", "lazy")

AXES = ("plan", "trajectory", "outcomes", "overall")

OUTPUT_STEM = "release-scoreboard"


class ScoreboardError(Exception):
    """A stage failed or an input moved; the message says which."""


def _worldloom(*args: str, cwd: Path) -> str:
    env = dict(os.environ)
    # The checkout's code, whatever is or is not installed: a release job
    # scores the tree it is releasing.
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT / "src"), env.get("PYTHONPATH", "")) if part
    )
    env.update({"COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb"})
    # Not `-m worldloom.cli`: on Windows click glob-expands every argument, so
    # the literal `--dag-shape *` became the checkout's file names in CI.
    completed = subprocess.run(
        [sys.executable, "-c", _ENTRY, *args],
        cwd=cwd, env=env, capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        tail = "\n".join((completed.stdout + completed.stderr).splitlines()[-25:])
        raise ScoreboardError(f"`worldloom {' '.join(args)}` exited {completed.returncode}:\n{tail}")
    return completed.stdout


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32]


def _digest_tree(root: Path) -> str:
    """One digest over every file under *root*: relative path and bytes, sorted."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:32]


def _git_revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _ratio(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0.0


def _agent_row(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "cases": summary["cases"],
        "passed": summary["passed"],
        "errors": summary["errors"],
        "pass_rate": summary["pass_rate"],
        "means": {axis: summary["means"][axis] for axis in AXES},
        "trajectory_match": {
            "exact": summary["exact_match_rate"],
            "in_order": summary["in_order_match_rate"],
            "any_order": summary["any_order_match_rate"],
        },
        "structured_outcomes": {"met": summary["structured_met"], "expected": summary["structured_expected"]},
        "collateral_cases": summary["collateral_cases"],
        "by_shape": {
            row["key"]: {"cases": row["cases"], "passed": row["passed"],
                         "means": {axis: row["means"][axis] for axis in AXES}}
            for row in sorted(summary["by_shape"], key=lambda row: row["key"])
        },
    }


def measure(revision: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="worldloom-scoreboard-") as scratch:
        work = Path(scratch)
        commands: list[str] = []

        def run(*args: str) -> str:
            commands.append("worldloom " + " ".join(args))
            return _worldloom(*args, cwd=work)

        run("build", *BUILD_ARGS, "--out", "corpus")
        scorecard = json.loads(run("evaluate", "corpus", "--retriever", RETRIEVERS, "--json"))
        run("enterprise-evals", "build", "corpus", "cases", *CASE_ARGS)
        agents: dict[str, Any] = {}
        case_set = None
        grader = None
        for agent in AGENTS:
            run("evalrun", "run", "cases", "--agent", agent, "-o", f"runs/{agent}")
            run_dir = work / "runs" / agent
            recorded = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            if case_set is None:
                case_set, grader = recorded["case_set"], recorded["grader"]["digest"]
            elif recorded["case_set"] != case_set:
                raise ScoreboardError(f"{agent} ran a different case set: {recorded['case_set']} != {case_set}")
            agents[agent] = _agent_row(summary)

        if case_set != PINNED_CASE_SET:
            raise ScoreboardError(
                f"the case set moved: generated {case_set}, pinned {PINNED_CASE_SET}.\n"
                "These numbers would score different questions than the last scoreboard."
                " If the generator change that moved them is deliberate, update"
                " PINNED_CASE_SET in tools/scoreboard.py in the same change."
            )

        retrieval = {
            name: {
                "overall": {**result["overall"], "rate": _ratio(result["overall"]["passed"], result["overall"]["total"])},
                "by_type": {
                    kind: {**counts, "rate": _ratio(counts["passed"], counts["total"])}
                    for kind, counts in sorted(result["by_type"].items())
                },
            }
            for name, result in sorted(scorecard["retrievers"].items())
        }
        corpus = work / "corpus"
        manifest = json.loads((work / "cases" / "manifest.json").read_text(encoding="utf-8"))
        return {
            "schema": SCHEMA,
            "revision": revision,
            "command": "python tools/scoreboard.py --revision <revision>",
            "commands": commands,
            "parameters": {
                "seed": SEED,
                "build": list(BUILD_ARGS),
                "retrievers": RETRIEVERS,
                "k": scorecard["k"],
                "case_set": list(CASE_ARGS),
                "agents": list(AGENTS),
            },
            "corpus": {
                "digest": _digest_tree(corpus),
                "evals_digest": _digest_file(corpus / "evals.jsonl"),
            },
            "case_set": {
                "digest": case_set,
                "pinned": PINNED_CASE_SET,
                "cases": manifest["queries"],
                "connector_records": manifest["connector_records"],
            },
            "grader_digest": grader,
            "agents": agents,
            "retrieval": retrieval,
        }


def markdown(board: dict[str, Any]) -> str:
    lines = [
        "# Release scoreboard",
        "",
        "Generated by `tools/scoreboard.py`; do not edit by hand. Fixed inputs and",
        "a digest-pinned case set, so two revisions' scoreboards differ only where",
        "the code under measurement does.",
        "",
        f"- Revision: `{board['revision']}`",
        f"- Command: `{board['command']}`",
        f"- Corpus: seed {board['parameters']['seed']}, `{' '.join(board['parameters']['build'])}`;"
        f" digest `{board['corpus']['digest']}`, evals digest `{board['corpus']['evals_digest']}`",
        f"- Case set: {board['case_set']['cases']} cases, digest `{board['case_set']['digest']}`"
        f" (pinned `{board['case_set']['pinned']}`), `{' '.join(board['parameters']['case_set'])}`",
        f"- Grader digest: `{board['grader_digest']}`",
        "",
        "## Agents (`worldloom evalrun run`)",
        "",
        "| Agent | Passed | Pass rate | Plan | Trajectory | Outcomes | Overall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in board["agents"].items():
        means = row["means"]
        lines.append(
            f"| {name} | {row['passed']}/{row['cases']} | {row['pass_rate']} | {means['plan']}"
            f" | {means['trajectory']} | {means['outcomes']} | {means['overall']} |"
        )
    shapes = sorted({shape for row in board["agents"].values() for shape in row["by_shape"]})
    agents = list(board["agents"])
    lines += [
        "",
        "Overall mean by DAG shape:",
        "",
        "| Shape | Cases | " + " | ".join(agents) + " |",
        "| --- | ---: | " + " | ".join("---:" for _ in agents) + " |",
    ]
    for shape in shapes:
        cells = [str(board["agents"][agent]["by_shape"].get(shape, {}).get("means", {}).get("overall", "-"))
                 for agent in agents]
        cases = board["agents"][agents[0]]["by_shape"].get(shape, {}).get("cases", 0)
        lines.append(f"| {shape} | {cases} | " + " | ".join(cells) + " |")
    retrievers = list(board["retrieval"])
    kinds = sorted({kind for result in board["retrieval"].values() for kind in result["by_type"]})
    lines += [
        "",
        f"## Retrieval baselines (`worldloom evaluate --retriever {board['parameters']['retrievers']}`, k={board['parameters']['k']})",
        "",
        "| Case type | " + " | ".join(retrievers) + " |",
        "| --- | " + " | ".join("---:" for _ in retrievers) + " |",
    ]
    for kind in kinds:
        cells = []
        for name in retrievers:
            counts = board["retrieval"][name]["by_type"].get(kind)
            cells.append(f"{counts['passed']}/{counts['total']}" if counts else "-")
        lines.append(f"| {kind} | " + " | ".join(cells) + " |")
    overall = [
        f"**{board['retrieval'][name]['overall']['passed']}/{board['retrieval'][name]['overall']['total']}**"
        for name in retrievers
    ]
    lines.append("| **overall** | " + " | ".join(overall) + " |")
    lines.append("")
    return "\n".join(lines)


def write(board: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{OUTPUT_STEM}.json"
    md_path = out_dir / f"{OUTPUT_STEM}.md"
    json_path.write_text(json.dumps(board, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    md_path.write_text(markdown(board), encoding="utf-8", newline="\n")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--revision", help="Revision to record (default: git rev-parse HEAD).")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "measurements",
                        help="Directory for release-scoreboard.json and .md (default: docs/measurements).")
    args = parser.parse_args(argv)
    try:
        board = measure(args.revision or _git_revision())
    except ScoreboardError as error:
        print(f"scoreboard: {error}", file=sys.stderr)
        return 1
    for path in write(board, args.out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
