"""Measure physical enterprise-scale output against a declared workload.

This is a reference construction measurement. It does not claim that any target
harness improved, or that templated prose matches a real customer's writing.
"""
from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    from worldloom.corpus import write_json
    from worldloom.corpus_scale import (
        CorpusScaleProfile,
        NativeScaleTarget,
        export_corpus_scale,
        plan_corpus_scale,
        verify_corpus_scale,
    )
    from worldloom.narrative import references
    from worldloom.native_corpus import NativeContent, NativeCorpusPlan
    from worldloom.synthesis import Limits, Simulator, retail
    from worldloom.world import World

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--stores", type=int, default=20)
    parser.add_argument("--products", type=int, default=50)
    parser.add_argument("--ticks", type=int, default=100)
    parser.add_argument("--units", type=int, default=200)
    parser.add_argument("--xlsx", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--ledger-fact", help="Allocate a canonical numeric fact instead of the operational retail program.")
    parser.add_argument("--ledger-rows", type=int, default=1_000_000)
    parser.add_argument("--table-section", action="append", default=[], metavar="ARTIFACT:INDEX",
        help="Include a checked source table section; repeat for its complete dependency graph.")
    args = parser.parse_args()
    if args.units < 2:
        parser.error("--units must be at least two")
    world = World.load(args.corpus)
    facts = {fact.id: fact for fact in world.facts}
    seen: set[str] = set()
    selected: list[NativeContent] = []
    for ir in sorted(world.artifact_irs, key=lambda item: item.id):
        for index, section in enumerate(ir.sections):
            if not section.body or not references.referenced(section.body):
                continue
            body = references.substitute(section.body, facts)
            key = " ".join(body.split()).casefold()
            if key in seen:
                continue
            seen.add(key)
            selected.append(NativeContent(source_artifact_id=ir.id, section_index=index))
    if len(selected) < args.units:
        parser.error(f"need {args.units} distinct accepted sections; source has {len(selected)}")
    table_contents = []
    for selector in args.table_section:
        artifact, separator, index = selector.rpartition(":")
        if not separator or not index.isdecimal():
            parser.error("--table-section takes ARTIFACT:INDEX")
        table_contents.append(NativeContent(source_artifact_id=artifact, section_index=int(index)))
    def contents(count: int) -> tuple[NativeContent, ...]:
        by_section = {(item.source_artifact_id, item.section_index): item for item in selected[:count]}
        for item in table_contents:
            by_section.setdefault((item.source_artifact_id, item.section_index), item)
        return tuple(by_section.values())
    deck_units = max(2, args.units // 2)
    plans = (
        NativeCorpusPlan(artifact_id="ART-SCALE-DOC", format="docx", title=f"{world.company.name} close evidence",
            minimum_units=args.units, minimum_distinct_facts=args.units, contents=contents(args.units), surface="business"),
        NativeCorpusPlan(artifact_id="ART-SCALE-DECK", format="pptx", title=f"{world.company.name} operating review",
            minimum_units=deck_units, minimum_distinct_facts=deck_units, contents=tuple(item.model_copy(update={"placement": "notes"})
                for item in contents(deck_units)), surface="business"),
        NativeCorpusPlan(artifact_id="ART-SCALE-BOOK", format="xlsx", title=f"{world.company.name} evidence workbook",
            minimum_units=args.units, minimum_distinct_facts=args.units, contents=contents(args.units), surface="business"),
    )
    program = retail(stores=args.stores, products=args.products, ticks=args.ticks)
    rows = args.stores + args.products + args.stores * args.products * args.ticks
    bindings = ()
    if args.ledger_fact is not None:
        from worldloom.corpus_scale import ledger_allocation_source

        rows = args.ledger_rows + 1
        allocation = ledger_allocation_source(world, fact_id=args.ledger_fact, rows=args.ledger_rows,
            seed=world.seed, limits=Limits(max_rows=rows))
        simulator = allocation.simulator
        bindings = (allocation.reconciliation,)
    else:
        simulator = Simulator(program, seed=world.seed, limits=Limits(max_rows=rows))
    profile = CorpusScaleProfile(name="measured-ledger" if bindings else "measured-retail", minimum_relational_rows=rows,
        native_targets=tuple(NativeScaleTarget(format=plan.format,
            minimum_units=plan.minimum_units, minimum_distinct_facts=plan.minimum_distinct_facts) for plan in plans))
    plan = plan_corpus_scale(world, simulator, profile=profile, native_plans=plans, reconciliations=bindings,
        csv_shard_rows=25_000, spreadsheets=args.xlsx)
    start = perf_counter()
    manifest = export_corpus_scale(world, plan, args.out, resume=args.resume)
    construction_seconds = perf_counter() - start
    start = perf_counter()
    verified = verify_corpus_scale(world, args.out)
    verification_seconds = perf_counter() - start
    assert manifest == verified
    summary = manifest.model_dump(mode="json")
    for native in summary["native"]:
        native.pop("evidence")
    report = {
        "schema": "worldloom.corpus-scale-measurement/v1",
        "method": "reference-construction-and-source-reconstruction",
        "python": platform.python_version(),
        "source_recipe": world.recipe,
        "narration_provider": "worldloom.narrative.DeterministicProvider (reference prose)",
        "workload": {"seed": world.seed, "source_events": len(world.events),
            "source_facts": len(world.facts), "source_artifacts": len(world.artifact_irs),
            "program": "reconciled-ledger" if bindings else "retail",
            "stores": args.stores if not bindings else None, "products": args.products if not bindings else None,
            "ticks": args.ticks if not bindings else None,
            "ledger_fact": args.ledger_fact, "ledger_rows": args.ledger_rows if bindings else None,
            "checked_table_sections": args.table_section,
            "maximum_csv_rows": 25_000, "units": args.units, "typed_spreadsheets": args.xlsx},
        "manifest_summary": summary,
        "native_evidence_in_private_manifest": True,
        "construction_seconds": round(construction_seconds, 3),
        "source_reconstruction_seconds": round(verification_seconds, 3),
        "verified": True,
        "live_target_trials": 0,
        "limitations": ["Reference prose; no empirical editorial realism measurement.",
            "DOCX explicit page boundaries are a construction floor; physical pagination is unmeasured.",
            ("Ledger allocation is an exact synthetic disaggregation, not a calibrated enterprise transaction distribution."
             if bindings else "Operational transaction mechanisms have a declared company scope; they are not a reconciliation to macro financial facts."),
            "Repeated formats do not add independent evidence.",
            "No target harness improvement is measured by this construction pilot."],
    }
    write_json(args.report, report)
    print({"relational_rows": manifest.relational_rows, "foreign_key_links": manifest.foreign_key_links,
        "native_files": len(manifest.native), "native_units": manifest.native_content_units,
        "verified": True, "report": str(args.report)})


if __name__ == "__main__":
    main()
