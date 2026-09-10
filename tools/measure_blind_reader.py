"""Replay recorded independent reading of the existing grocery narration.

No reader is called here. The recorded responses were produced by an isolated
agent given only ReaderPlan.requests_document(), without repository context.
This measures lexical evidence admission, not semantic reasoning quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from worldloom import World
from worldloom.corpus import write_json
from worldloom.narrative import reader_checks

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {"adapter": "isolated-codex-agent", "prompt_version": "reader-document/v1"}


def measure(responses_path: Path) -> dict:
    document = json.loads(responses_path.read_text(encoding="utf-8"))
    responses = tuple(reader_checks.ReaderResponse.model_validate(row) for row in document["responses"])
    with TemporaryDirectory(prefix="worldloom-blind-reader-") as temporary:
        corpus = Path(temporary) / "corpus"
        for arguments in (
            ["build", "--seed", "8128", "--incident", "--archetype", "australian_grocery",
             "--comparatives", "11", "--section-omission", "0", "--outline-synthesis", "0",
             "--variant-bias", "0", "--out", str(corpus)],
            ["narrate", "accept", str(corpus), "--from", str(ROOT / "examples/grocery-close/narration.json"),
             "--model-id", "claude-opus-5"],
        ):
            subprocess.run([sys.executable, "-c", "from worldloom.cli import app; app()", *arguments], cwd=ROOT, check=True,
                           capture_output=True)
        world = World.load(corpus)
        plan = reader_checks.plan(world, reader_id="independent-blind-reader/v1",
                                  reader_config=CONFIG, share=.1)
        if plan.issues:
            raise ValueError(f"probe reader plan changed: {plan.issues}")
        result = reader_checks.accept(world, plan, responses)
        repeated = reader_checks.accept(result.world, plan, responses)
        first = result.world.export(Path(temporary) / "first")
        second = repeated.world.export(Path(temporary) / "second")
        def inventory(root: Path) -> dict[str, str]:
            return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(root.rglob("*")) if path.is_file()}
        files = inventory(first)
        if files != inventory(second) or not repeated.replayed:
            raise AssertionError("response-file resubmission changed the corpus")
        report = {
            "schema": "worldloom.blind-reader-probe/v1",
            "reader_identity": plan.reader_id,
            "reader_config": CONFIG,
            "scope": "One isolated reader, four sampled passages from existing authored narration; no eval-critical set declared.",
            "reader_input": "Only the public requests document; no repository, World, private plan, facts or oracle.",
            "source": "examples/grocery-close/narration.json",
            "source_sha256": hashlib.sha256((ROOT / "examples/grocery-close/narration.json").read_bytes()).hexdigest(),
            "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                      for name in ("src/worldloom/narrative/reader_checks.py",
                                                   "src/worldloom/narrative/compiler.py",
                                                   "src/worldloom/narrative/providers.py",
                                                   "src/worldloom/recipe.py", "tools/measure_blind_reader.py")},
            "responses_sha256": hashlib.sha256(responses_path.read_bytes()).hexdigest(),
            "seed": world.seed,
            "requests": len(plan.requests),
            "target_occurrences": len(plan.targets),
            "recovered_target_occurrences": sum(len(f.recovered_fact_ids) for f in result.review.findings),
            "claims": sum(len(response.claims) for response in responses),
            "passed_sections": sum(f.passed for f in result.review.findings),
            "invalid_quotes": sum(f.invalid_quotes for f in result.review.findings),
            "public_requests": plan.requests_document(),
            "review": result.review.model_dump(mode="json"),
            "resubmission_byte_identical": True,
            "export_file_sha256": files,
            "limitations": ["Lexical subject/value recovery, not semantic entailment or comprehension scoring.",
                            "One small sample; not a model comparison or enterprise population estimate.",
                            "Existing prose is intentionally unchanged; its rejected review is retained."],
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--responses", type=Path,
                        default=ROOT / "docs/measurements/blind-reader-responses.json")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    write_json(arguments.out, measure(arguments.responses))


if __name__ == "__main__":
    main()
