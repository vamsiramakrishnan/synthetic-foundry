#!/usr/bin/env python3
"""Compile Worldloom's bundled process catalogue.

The library is authoritative. The user-supplied 12-industry archive is retained
as a SHA-256/row-count manifest, so ``--verify`` proves the current compiler
still reproduces those defaults byte-for-byte without vendoring generated data.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from worldloom.process_catalogue import (
    CompanyProcessSpec,
    ProcessCompilation,
    compile_company,
    coverage_matrix,
    industries,
    load_default,
    verify_defaults,
)


def _write_compilation(
    out: Path,
    compilation: ProcessCompilation,
    *,
    source_shape: bool,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{compilation.spec.name}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in compilation.rows:
            payload = row.source_record() if source_shape else row.model_dump(mode="json")
            handle.write(
                json.dumps(payload, ensure_ascii=False, sort_keys=not source_shape) + "\n"
            )

    (out / f"{compilation.spec.name}.summary.json").write_text(
        compilation.summary.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("compiled"))
    parser.add_argument("--industry", choices=industries())
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--source-shape",
        action="store_true",
        help="emit the exact historical JSONL field shape without runtime enrichment",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify all supplied defaults and the supplied coverage matrix",
    )
    args = parser.parse_args()

    if args.verify:
        report = verify_defaults()
        print(json.dumps(report, sort_keys=True))
        raise SystemExit(0 if report["ok"] else 1)

    if sum(bool(value) for value in (args.industry, args.spec, args.all)) != 1:
        parser.error("choose exactly one of --industry, --spec, or --all")

    compilations: list[ProcessCompilation] = []
    if args.spec:
        spec = CompanyProcessSpec.model_validate_json(
            args.spec.read_text(encoding="utf-8")
        )
        compilations.append(compile_company(spec))
    elif args.industry:
        compilations.append(load_default(args.industry))
    else:
        compilations.extend(load_default(industry) for industry in industries())

    for compilation in compilations:
        _write_compilation(args.out, compilation, source_shape=args.source_shape)
        print(compilation.summary.model_dump_json())

    if args.all:
        with (args.out / "coverage.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.writer(handle)
            writer.writerow(("industry", "stream", "status", "activities"))
            for cell in coverage_matrix():
                writer.writerow(
                    (cell.industry, cell.stream, cell.status.value, cell.activities)
                )


if __name__ == "__main__":
    main()
