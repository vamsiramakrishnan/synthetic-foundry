#!/usr/bin/env python3
"""Score corpora with every retriever this repository has, and say what is hard.

The question this exists to answer: **every difficulty number Worldloom has ever
published came from BM25 and TF-IDF**, two lexical baselines that share one idea
— relevance is word overlap. A family they both fail is either structurally hard
or merely a lexical trap that any deployed retrieval stack walks past, and
nothing could tell those apart. This runs the lexical pair against dense
retrievers and prints the difference.

```bash
python3 tools/measure_retrievers.py ./corpus
python3 tools/measure_retrievers.py ./mosaic --mosaic
python3 tools/measure_retrievers.py ./corpus --pin all-minilm-l6-v2 --pin potion-retrieval-32m
python3 tools/measure_retrievers.py ./corpus --json > report.json
```

Two pins ship, and running both is the point rather than belt-and-braces.
`potion-retrieval-32m` is a static-embedding model — a learned vector per token,
mean-pooled, no forward pass — and `all-minilm-l6-v2` is a real transformer
encoder. "A cheap semantic model failed this family" and "no semantic retriever
passes this family" are different claims, and only running both distinguishes
them. The transformer needs `pip install sentence-transformers`; without it that
pin is skipped and said so, exactly as the CLI does.

A tool, not library code: nothing under `src/` imports it, and it adds no
dependency — the same rule `tools/sweep.py` follows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from worldloom.evaluate import (  # noqa: E402
    LEXICAL_RETRIEVERS,
    RETRIEVERS,
    Scorecard,
    compare,
    difficulty_by_family,
    embedding,
    render_agreement,
    render_difficulty,
    score,
)
from worldloom.evaluate.across import load as load_mosaic  # noqa: E402


def _register(pins: list[str], vectors: Path | None) -> list[str]:
    """Put one retriever per pin into `RETRIEVERS`, and return their names.

    The whole integration surface for a new model, and deliberately so: no
    subclass, no scorer argument, no branch anywhere in the grading. If this
    function needed more than `configured()`, the seam would not be one.
    """
    names = []
    for key in pins:
        pin = embedding.PINS[key]
        name = f"embedding-{key}"
        RETRIEVERS[name] = embedding.configured(pin=pin, cache=vectors)
        names.append(name)
    return names


def _score_all(world, names: list[str], k: int) -> tuple[dict[str, Scorecard], list[str]]:
    cards: dict[str, Scorecard] = {}
    skipped: list[str] = []
    for name in names:
        try:
            cards[name] = score(world, k=k, retriever=name)
        except embedding.EmbeddingUnavailable as unavailable:
            print(f"  skipped {name} — {unavailable}", file=sys.stderr)
            skipped.append(name)
    return cards, skipped


def _merge(cards_per_world: list[dict[str, Scorecard]]) -> dict[str, Scorecard]:
    """One scorecard per retriever, over every world's cases at once.

    Legitimate because `compare()` and `difficulty_by_family()` read outcomes
    and per-type tallies, both of which concatenate — and because the question
    being asked of a mosaic is "is this *family* hard across five companies",
    which is a question about the union. Case ids are unique per world only, so
    they are prefixed; a collision would make `compare()` silently drop cases.
    """
    merged: dict[str, Scorecard] = {}
    for index, cards in enumerate(cards_per_world):
        for name, card in cards.items():
            target = merged.setdefault(name, Scorecard(k=card.k, retriever=name))
            for outcome in card.outcomes:
                target.outcomes.append(
                    type(outcome)(
                        case_id=f"w{index}/{outcome.case_id}",
                        evaluation_type=outcome.evaluation_type,
                        passed=outcome.passed,
                        detail=outcome.detail,
                        reachable=outcome.reachable,
                    )
                )
    return merged


def _table(cards: dict[str, Scorecard]) -> str:
    """Every retriever's per-family score in one grid, retrievers as columns."""
    names = list(LEXICAL_RETRIEVERS) + sorted(n for n in cards if n not in LEXICAL_RETRIEVERS)
    names = [name for name in names if name in cards]
    families = sorted({o.evaluation_type for card in cards.values() for o in card.outcomes},
                      key=lambda kind: kind.value)
    width = max(len(kind.value) for kind in families)
    column = max(12, max(len(name) for name in names) + 2)
    lines = [
        "  " + "family".ljust(width) + "".join(name.rjust(column) for name in names),
        "  " + "─" * (width + column * len(names)),
    ]
    for kind in families:
        cells = ""
        for name in names:
            passed, total = cards[name].by_type().get(kind, (0, 0))
            cells += f"{passed}/{total}".rjust(column)
        lines.append("  " + kind.value.ljust(width) + cells)
    totals = "".join(f"{cards[name].passed}/{len(cards[name])}".rjust(column) for name in names)
    lines.append("  " + "─" * (width + column * len(names)))
    lines.append("  " + "overall".ljust(width) + totals)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("corpus", help="A corpus directory, or a mosaic directory with --mosaic.")
    parser.add_argument("--mosaic", action="store_true", help="Treat the path as a directory of worlds.")
    parser.add_argument("-k", type=int, default=5, help="Passages a retriever may return.")
    parser.add_argument(
        "--pin", action="append", default=None,
        help=f"Model pin to run, repeatable. Known: {sorted(embedding.PINS)}. Default: every pin.",
    )
    parser.add_argument("--vectors", default=None, help="Vector cache file or directory.")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    arguments = parser.parse_args()

    pins = arguments.pin or sorted(embedding.PINS)
    unknown = [key for key in pins if key not in embedding.PINS]
    if unknown:
        parser.error(f"unknown pin(s) {unknown} — known: {sorted(embedding.PINS)}")

    vectors = Path(arguments.vectors) if arguments.vectors else None
    dense = _register(pins, vectors)
    names = list(LEXICAL_RETRIEVERS) + dense

    from worldloom.cli import _compiled, _load  # a corpus on disk is the CLI's job to open

    if arguments.mosaic:
        worlds = [(entry.name, entry.world) for entry in load_mosaic(arguments.corpus)]
    else:
        worlds = [(Path(arguments.corpus).name, _compiled(_load(arguments.corpus), arguments.corpus))]

    per_world: list[dict[str, Scorecard]] = []
    skipped: list[str] = []
    for name, world in worlds:
        if not arguments.json:
            print(f"\n{name} — {len(world.evaluations)} case(s)", file=sys.stderr)
        cards, missing = _score_all(world, names, arguments.k)
        skipped = missing
        per_world.append(cards)

    merged = _merge(per_world) if len(per_world) > 1 else per_world[0]
    agreement = compare(merged)
    difficulty = difficulty_by_family(merged)

    if arguments.json:
        print(json.dumps({
            "k": arguments.k,
            "worlds": [name for name, _ in worlds],
            "pins": {key: {"id": embedding.PINS[key].id, "revision": embedding.PINS[key].revision}
                     for key in pins},
            "skipped": skipped,
            "scores": {
                name: {
                    kind.value: {"passed": passed, "total": total}
                    for kind, (passed, total) in sorted(card.by_type().items(), key=lambda i: i[0].value)
                }
                for name, card in sorted(merged.items())
            },
            "overall": {name: {"passed": card.passed, "total": len(card)}
                        for name, card in sorted(merged.items())},
            "agreement": {f.evaluation_type.value: f.finding for f in agreement},
            "difficulty": {
                f.evaluation_type.value: {
                    "lexical": {"passed": f.lexical[0], "total": f.lexical[1]},
                    "semantic": {"passed": f.semantic[0], "total": f.semantic[1]},
                    "verdict": f.verdict,
                }
                for f in difficulty
            },
        }, indent=2, sort_keys=True))
        return 0

    print(f"\nPer-family, every retriever, @{arguments.k}"
          f" — {len(worlds)} world(s), {len(next(iter(merged.values())))} case(s)")
    print(_table(merged))
    print("")
    print(render_agreement(agreement))
    print("")
    print(render_difficulty(difficulty))
    for key in pins:
        pin = embedding.PINS[key]
        print(f"\n  {key}: {pin.id} @ {pin.revision}")
    unreachable = {
        kind: count
        for card in merged.values()
        for kind, count in card.unreachable_by_type().items()
    }
    if unreachable:
        # Printed because a family whose evidence no passage carries scores zero
        # for every retriever and would otherwise read as the hardest thing in
        # the corpus — see `Outcome.reachable`.
        print("\n  cases citing evidence no passage carries: "
              + ", ".join(f"{kind.value} ×{count}" for kind, count in sorted(
                  unreachable.items(), key=lambda item: item[0].value)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
