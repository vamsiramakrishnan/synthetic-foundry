#!/usr/bin/env python3
"""Does selecting on measurements beat selecting on parameters? Measured, not argued.

``mosaic.field`` disperses in **parameter** space — a Halton covering of
headcount, span, depth, estate and physics, then a farthest-point traversal over
those coordinates. ``mosaic.outcome_field`` disperses in **measurement** space:
same candidates, but each one is built, run, compiled and read, and the
traversal runs over what the corpora turned out to contain. This script holds
the two against the same ruler.

**The comparison is fair by construction.** Gonzalez's traversal is
prefix-consistent, so ``field(30)[:5]`` *is* ``field(5)``. Both arms therefore
draw from one candidate set produced by one generator, and the only thing that
differs between them is the selector. An experiment that generated the two arms
differently would be measuring the generators.

**The ruler is the one that already existed.** ``evaluate.across.survey`` is
this repository's own answer to "is a mosaic a better dataset than one company
five times", and it was written before any of this. Both arms are narrated with
the deterministic provider first — un-narrated, a third of every world's
evaluation cases cite evidence that is in no passage, and every score read off
them is about the ranker rather than the corpus (``cli.mosaic`` argues this at
its ``--narrate`` default).

**If outcome selection does not win, that is the finding.** This script prints
the table either way and says which arm won each row. Nothing here tunes
anything: there is one free parameter in the objective
(``outcomes.QUESTION_WEIGHT``) and ``--question-weight`` exposes it so a reader
can check the result is not an artifact of it, not so that the run can be
repeated until it flatters the new code.

Not library code: nothing under ``src/`` imports it, and it adds no dependency.

    python3 tools/outcome_selection.py -n 5 --pool 30
    python3 tools/outcome_selection.py -n 5 --pool 30 -e banking --json out.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from worldloom import mosaic, outcomes, sdk
from worldloom.evaluate import across
from worldloom.narrative import DeterministicProvider


@dataclass(frozen=True)
class Arm:
    """One selection strategy, its worlds, and every reading taken of them."""

    label: str
    variants: tuple[Any, ...]
    survey: Any
    measured: dict[str, Any]
    build_seconds: float
    select_seconds: float

    def rows(self) -> dict[str, float]:
        """The survey's numbers, flattened to one comparable row per metric.

        Every one of these is already reported by ``evaluate.across`` — this
        adds no metric of its own, because a new metric introduced alongside a
        new algorithm is the oldest way to win an experiment.
        """
        overlap = self.survey.overlap
        transfer = next(iter(self.survey.transfers.values()))
        spreads = list(transfer.spread().values())
        return {
            "distinct question strings": float(overlap.distinct_questions),
            "distinct (question, answer)": float(overlap.distinct_with_answers),
            "byte-identical in every world": float(overlap.identical_in_every_world),
            "cross-world near-duplicate pairs": float(overlap.cross_world_pairs),
            # The same pair count against its own denominator, and the same
            # restatement fraction `across.render` prints. Both are here
            # because the raw pair count is quadratic in questions per world,
            # so a selection that happens to prefer denser corpora inflates it
            # without repeating anything — which is a confound in the metric
            # rather than a property of the selector, and dropping the raw
            # count to hide that would be worse than showing both.
            "cross-world near-duplicate rate": round(
                overlap.cross_world_pairs / overlap.cross_world_pairs_possible, 5,
            ) if overlap.cross_world_pairs_possible else 0.0,
            "question restatement (redundancy)": overlap.redundancy,
            "questions in a cross-world group": float(overlap.questions_in_a_cross_world_group),
            "mean per-family spread": round(statistics.fmean(spreads), 4) if spreads else 0.0,
            "families with any spread": float(sum(1 for s in spreads if s > 0)),
            "floor transplants that flipped a verdict": float(
                sum(sum(row.values()) for row in transfer.floor_flips.values())
            ),
            "failure concentration (hardest world's share)": self.survey.difficulty.concentration,
            "measured closest pair": self.measured["closest_pair"],
            "measured mean pair": self.measured["mean_pair"],
        }


#: For each row, whether a larger number is the better dataset — and where the
#: honest answer is "neither", ``None``, so the table says so instead of
#: awarding a point. Concentration is the clearest case: a mosaic whose hardness
#: all sits in one world is a one-world benchmark, so *lower* is better, and the
#: even split it should be compared against depends on the mosaic's size.
BETTER_HIGHER: dict[str, bool | None] = {
    "distinct question strings": True,
    "distinct (question, answer)": True,
    "byte-identical in every world": False,
    "cross-world near-duplicate pairs": False,
    "cross-world near-duplicate rate": False,
    "question restatement (redundancy)": False,
    "questions in a cross-world group": False,
    "mean per-family spread": True,
    "families with any spread": True,
    "floor transplants that flipped a verdict": True,
    "failure concentration (hardest world's share)": False,
    "measured closest pair": None,
    "measured mean pair": None,
}


def _narrated(variants: tuple[Any, ...], *, engine: str, period: str,
              periods: int, incident: bool | None) -> tuple[across.MosaicWorld, ...]:
    """Build, run, narrate and compile each variant — the corpus, in memory.

    One ``DeterministicProvider`` for all of them, exactly as ``cli.mosaic``
    does and for the reason it states: the provider reads a request and a fact
    table and holds nothing between calls but a counter, so N worlds through one
    instance write the bytes N instances would.
    """
    provider = DeterministicProvider()
    out: list[across.MosaicWorld] = []
    for variant in variants:
        blueprint = sdk._from_variant(variant)
        built = blueprint.build().episodes(period, periods=periods, incident=incident)
        world = built.world.compile().narrate(provider)
        out.append(across.MosaicWorld(
            f"world-{variant.index:02d}", world, variant.summary()))
    return tuple(out)


def _arm(label: str, variants: tuple[Any, ...], *, engine: str, period: str,
         periods: int, incident: bool | None, select_seconds: float,
         question_weight: float) -> Arm:
    start = time.perf_counter()
    worlds = _narrated(variants, engine=engine, period=period, periods=periods,
                       incident=incident)
    build_seconds = time.perf_counter() - start
    readings = tuple(
        outcomes.read(entry.world, name=entry.name, seed=variant.seed)
        for entry, variant in zip(worlds, variants, strict=True)
    )
    return Arm(
        label=label,
        variants=variants,
        survey=across.survey(worlds),
        measured=outcomes.report(readings, range(len(readings)),
                                 question_weight=question_weight),
        build_seconds=build_seconds,
        select_seconds=select_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--count", type=int, default=5,
                        help="Worlds per arm.")
    parser.add_argument("--pool", type=int, default=30,
                        help="Candidates the outcome arm measures before choosing.")
    parser.add_argument("-e", "--engine", default="retail")
    parser.add_argument("-s", "--seed", type=int, default=8128)
    parser.add_argument("-p", "--period", default="2026-03")
    parser.add_argument("--periods", type=int, default=1)
    parser.add_argument("--incident", action="store_true", default=None)
    parser.add_argument("--question-weight", type=float,
                        default=outcomes.QUESTION_WEIGHT,
                        help="Weight of the question-overlap term in the objective.")
    parser.add_argument("--json", dest="as_json", default=None,
                        help="Write the whole comparison as data.")
    args = parser.parse_args()

    print(f"# {args.engine} mosaic, n={args.count}, pool={args.pool}, seed={args.seed}",
          file=sys.stderr, flush=True)

    # The parameter arm. `field(pool)[:count]` rather than `field(count)` to
    # make the prefix-consistency claim visible rather than assumed — they are
    # asserted equal below, and if a future edit breaks that the comparison
    # stops being fair and this says so.
    started = time.perf_counter()
    candidates = mosaic.field(args.pool, seed=args.seed, engine=args.engine)
    parameter_variants = candidates[:args.count]
    parameter_select = time.perf_counter() - started
    assert [v.seed for v in parameter_variants] == \
        [v.seed for v in mosaic.field(args.count, seed=args.seed, engine=args.engine)], \
        "field(pool)[:count] is no longer field(count); the two arms are not comparable"

    started = time.perf_counter()
    outcome_variants = mosaic.outcome_field(
        args.count, seed=args.seed, engine=args.engine, pool=args.pool,
        period=args.period, periods=args.periods, incident=args.incident,
    )
    outcome_select = time.perf_counter() - started

    arms = [
        _arm("parameter", parameter_variants, engine=args.engine, period=args.period,
             periods=args.periods, incident=args.incident,
             select_seconds=parameter_select, question_weight=args.question_weight),
        _arm("outcome", outcome_variants, engine=args.engine, period=args.period,
             periods=args.periods, incident=args.incident,
             select_seconds=outcome_select, question_weight=args.question_weight),
    ]

    left, right = arms[0].rows(), arms[1].rows()
    width = max(len(label) for label in left)
    print(f"\n  {'metric'.ljust(width)}  {'parameter':>12}  {'outcome':>12}  winner")
    print("─" * (width + 46))
    wins = {"parameter": 0, "outcome": 0, "tie": 0}
    for label in left:
        higher = BETTER_HIGHER[label]
        if higher is None or left[label] == right[label]:
            verdict = "—" if higher is None else "tie"
            if higher is not None:
                wins["tie"] += 1
        else:
            better = (right[label] > left[label]) == higher
            verdict = "outcome" if better else "parameter"
            wins[verdict] += 1
        print(f"  {label.ljust(width)}  {left[label]:>12g}  {right[label]:>12g}  {verdict}")

    print(f"\n  rows won — outcome {wins['outcome']}, parameter {wins['parameter']},"
          f" tied {wins['tie']}")
    for arm in arms:
        print(f"  {arm.label:>9}: select {arm.select_seconds:6.1f}s"
              f"   narrate+survey {arm.build_seconds:6.1f}s"
              f"   verdict: {arm.survey.verdict}")
    print(f"\n  the loop's own cost: measuring a pool of {args.pool} took"
          f" {arms[1].select_seconds:.1f}s"
          f" ({arms[1].select_seconds / max(1, args.pool):.2f}s per candidate),"
          f" against {arms[0].select_seconds:.2f}s to disperse the same candidates"
          " on parameters alone.")

    if args.as_json:
        Path(args.as_json).write_text(json.dumps({
            "engine": args.engine, "count": args.count, "pool": args.pool,
            "seed": args.seed, "question_weight": args.question_weight,
            "arms": [
                {
                    "label": arm.label,
                    "worlds": [
                        {"index": v.index, "seed": v.seed, "summary": v.summary()}
                        for v in arm.variants
                    ],
                    "rows": arm.rows(),
                    "measured": arm.measured,
                    "survey": arm.survey.as_dict(),
                    "select_seconds": round(arm.select_seconds, 3),
                    "build_seconds": round(arm.build_seconds, 3),
                }
                for arm in arms
            ],
            "rows_won": wins,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
