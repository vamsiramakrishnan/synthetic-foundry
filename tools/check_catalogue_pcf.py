#!/usr/bin/env python3
"""Join every catalogue activity to its APQC process and to the function that owns it.

For each activity in `_data/process-catalogue/catalogue.json` this prints the
process its `pcf_id` names in the stream's framework (hierarchy index and name)
and, beside the function the row names as the performer, the function that
owns the process in `_data/functions/functions@<n>.json`. An id that does not
resolve is an error; a performer that differs from the owner is reported, not
refused: a step is often performed by one function inside a process another
owns (a sales approval inside the proposals process, say), and the table is
where that reads as a decision rather than an accident.

Usage::

    python tools/check_catalogue_pcf.py            # the table
    python tools/check_catalogue_pcf.py --strict   # exit 1 on an unresolved id
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worldloom import functions, pcf
from worldloom.process_bindings import load_catalogue


def rows() -> tuple[list[tuple[str, ...]], list[str]]:
    cat = load_catalogue()
    table = functions.load()
    cross = pcf.load(cat["meta"]["pcf_framework"])
    out: list[tuple[str, ...]] = []
    problems: list[str] = []

    def walk(industry: str, framework: pcf.Framework, streams: dict[str, dict[str, object]]) -> None:
        for sid, stream in streams.items():
            for row in stream["activities"]:  # type: ignore[index]
                activity_id, name, pcf_id, function = row[0], row[1], row[2], row[3]
                element = framework.get(pcf_id)
                if element is None:
                    problems.append(f"{industry}/{sid}/{activity_id}: {framework.key} has no element {pcf_id!r}")
                    continue
                process = element if element.level <= 3 else cross_process(framework, element)
                owner = table.for_process(process.pcf_id) if process is not None else None
                owner_key = owner.key if owner is not None else "-"
                out.append((industry, sid, activity_id, name, element.hierarchy_id, element.name, function, owner_key,
                            "" if owner_key in (function, "-") else "performer differs from owner"))

    def cross_process(framework: pcf.Framework, element: pcf.Element) -> pcf.Element | None:
        for ancestor in reversed(framework.ancestors(element.pcf_id)):
            if ancestor.level == 3:
                return ancestor
        return None

    walk("universal", cross, cat["value_streams"])
    for industry, overlay in cat["industry_overlays"].items():
        framework = pcf.load(overlay.get("pcf_framework") or cat["meta"]["pcf_framework"])
        walk(industry, framework, overlay.get("specific") or {})
    return out, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--strict", action="store_true", help="Exit 1 when an id does not resolve.")
    args = parser.parse_args(argv)
    table, problems = rows()
    width = max(len(r[3]) for r in table)
    for industry, sid, activity_id, name, hierarchy, process, function, owner, note in table:
        print(f"{industry:15} {sid:22} {activity_id:9} {name:{width}}  {hierarchy:10} {process[:48]:48}  {function:16} {owner:18} {note}")
    differs = sum(1 for r in table if r[8])
    print(f"\n{len(table)} activities; {differs} performed by a function other than the process owner", file=sys.stderr)
    for problem in problems:
        print("error:", problem, file=sys.stderr)
    return 1 if problems and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
