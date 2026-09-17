#!/usr/bin/env python3
"""Ingest BLS OES national industry-occupation employment into function weights.

What this closes: a company stated one workforce total and split it across its
units by *revenue share*, which is a proxy for staffing and was documented as
one. Occupational employment by industry is the measurement that proxy stood
in for, and the Bureau of Labor Statistics publishes it.

The join is three files already in this repository plus one download:

* OES `nat4d_M2024_dl.xlsx` gives employment for an SOC occupation within a
  4-digit NAICS industry;
* `_data/functions/functions@1.json` maps each function family to the O*NET
  occupations that staff it, which are SOC codes with a `.00` detail suffix;
* the process catalogue's `industry_crosswalk` maps NAICS codes to the twelve
  industries this tool ships.

Longest NAICS prefix wins, which is load-bearing: the crosswalk carries both
`NAICS 52` (banking) and `NAICS 5241` (insurance), and first-match order put
every insurer in the bank.

An occupation that staffs several families splits its employment evenly
between them rather than being counted once per family, so the shares in one
industry sum to one and no headcount is invented by double counting.

Raw OES workbooks are external inputs, not repository assets: this emits the
compact derived table plus a provenance record, the same policy
`_data/vocabulary-sources.json` states for APQC and O*NET.

    python tools/ingest_bls_oes.py --workbook oesm24in4/nat4d_M2024_dl.xlsx
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "worldloom.oes-employment/v1"
URL = "https://www.bls.gov/oes/special-requests/oesm24in4.zip"
LICENSE = "Public domain (U.S. Government work, 17 U.S.C. 105); attribution requested"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def occupation_families(functions: dict[str, Any]) -> dict[str, set[str]]:
    """SOC code -> the function families it staffs, from the O*NET crosswalk."""
    mapping: dict[str, set[str]] = collections.defaultdict(set)
    for family, row in functions.items():
        for occupations in (row.get("occupations") or {}).values():
            for occupation in occupations:
                mapping[str(occupation["code"]).split(".")[0]].add(family)
    return dict(mapping)


def naics_rules(crosswalk: dict[str, str]) -> list[tuple[str, str]]:
    """`(prefix, industry)` pairs, longest prefix first.

    A crosswalk entry is a code (`52`), a same-width range (`44-45`) or a
    wider code (`5241`). Sorting by descending prefix length is what keeps
    `NAICS 5241` (insurance) out of `NAICS 52` (banking).
    """
    rules: list[tuple[str, str]] = []
    for key, industry in crosswalk.items():
        if not key.startswith("NAICS "):
            continue
        spec = key.split(" ", 1)[1]
        halves = spec.split("-")
        if len(halves) == 2 and len(halves[0]) == len(halves[1]) and halves[0].isdigit():
            width = len(halves[0])
            prefixes = [str(n).zfill(width) for n in range(int(halves[0]), int(halves[1]) + 1)]
        else:
            prefixes = [spec]
        rules.extend((prefix, industry) for prefix in prefixes)
    return sorted(rules, key=lambda rule: (-len(rule[0]), rule[0]))


def industry_for(naics: str, rules: list[tuple[str, str]]) -> str | None:
    for prefix, industry in rules:
        if naics.startswith(prefix):
            return industry
    return None


def tally(workbook: Path, families: dict[str, set[str]], rules: list[tuple[str, str]]):
    import openpyxl

    sheet = openpyxl.load_workbook(workbook, read_only=True, data_only=True).active
    rows = sheet.iter_rows(values_only=True)
    header = next(rows)
    at = {name: index for index, name in enumerate(header) if name}
    for column in ("NAICS", "OCC_CODE", "O_GROUP", "TOT_EMP"):
        if column not in at:
            raise SystemExit(f"{workbook}: no {column} column; is this an OES industry file?")
    employment: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    matched = collections.Counter()
    for row in rows:
        if row[at["O_GROUP"]] != "detailed":
            continue
        total = row[at["TOT_EMP"]]
        if not isinstance(total, (int, float)):
            continue  # OES suppresses small cells; they are blank or a marker.
        staffed = families.get(str(row[at["OCC_CODE"]]))
        if not staffed:
            continue
        industry = industry_for(str(row[at["NAICS"]]), rules)
        if industry is None:
            continue
        matched[industry] += 1
        for family in staffed:
            employment[industry][family] += total / len(staffed)
    return employment, matched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True,
                        help="OES national industry-occupation xlsx (nat4d_M2024_dl.xlsx).")
    parser.add_argument("--release", default="May 2024", help="OES reference period.")
    parser.add_argument("--out", type=Path,
                        default=Path("src/worldloom/_data/oes/employment@2024.json"))
    parser.add_argument("--functions", type=Path,
                        default=Path("src/worldloom/_data/functions/functions@1.json"))
    args = parser.parse_args()

    from worldloom.industry import load_catalogue

    functions = json.loads(args.functions.read_text(encoding="utf-8"))["functions"]
    rules = naics_rules(load_catalogue()["industry_crosswalk"])
    employment, matched = tally(args.workbook, occupation_families(functions), rules)

    industries: dict[str, Any] = {}
    for industry in sorted(employment):
        counted = employment[industry]
        total = sum(counted.values())
        if total <= 0:
            continue
        industries[industry] = {
            "employment": round(total),
            "rows": matched[industry],
            # Six places: enough that the smallest shipped family is not zero,
            # few enough that the file is stable across a re-run.
            "families": {f: round(v / total, 6) for f, v in sorted(counted.items())},
        }
    document = {
        "schema": SCHEMA,
        "release": args.release,
        "source": {
            "id": "bls-oes-industry",
            "url": URL,
            "workbook": args.workbook.name,
            "sha256": sha256(args.workbook),
            "license": LICENSE,
        },
        "industries": industries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(industries)} industries")
    for industry, row in industries.items():
        top = sorted(row["families"].items(), key=lambda kv: -kv[1])[:3]
        print(f"  {industry:18s} {row['employment']:>10,}  {top}")


if __name__ == "__main__":
    main()
