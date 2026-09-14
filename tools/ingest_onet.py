#!/usr/bin/env python3
"""Ingest the O*NET database (CSV release) into one versioned data file.

Input: the ``db_<major>_<minor>_csv.zip`` archive the National Center for
O*NET Development publishes at https://www.onetcenter.org/database.html.
Output: ``src/worldloom/_data/onet/occupations@<release>.json.gz`` and a
provenance ledger next to it.

What is taken, per occupation (``occupation_data.csv``):

- the O*NET-SOC code, title and description;
- the job zone (``job_zones.csv``: 1 little preparation ... 5 extensive);
- the titles incumbents report (``sample_of_reported_titles.csv``) and the
  alternate titles O*NET collects from employers and job postings
  (``job_titles.csv``): the pool of real job titles for a role;
- the task statements (``task_statements.csv``), each with its type (core or
  supplemental) and the detailed work activities it maps to
  (``tasks_to_dwas.csv``);
- the software used (``software_skills.csv``): the product name, its
  category and whether O*NET flags it as a hot technology.

Plus the work-activity hierarchy (``gwas_to_iwas_to_dwas.csv``): generalized,
intermediate and detailed work activities with their ids.

The content of the O*NET database is licensed under CC BY 4.0. The licence
asks for a credit line naming the release and USDOL/ETA, a link to the
licence, and a statement that the information was modified where it was.
The output embeds that credit verbatim; the selection and restructuring
here are the modification it declares. Rows are written in code order with
sorted keys and a zero gzip timestamp, so the same archive yields the same
bytes.

Usage::

    python tools/ingest_onet.py --input db_31_0_csv.zip --out src/worldloom/_data/onet
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

SCHEMA = "worldloom.onet/v1"
LICENCE = "CC BY 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
SOURCE_URL = "https://www.onetcenter.org/database.html"

_RELEASE = re.compile(r"O\*NET\s+([0-9]+\.[0-9]+)\s+Database", re.IGNORECASE)
_RELEASED = re.compile(r"^\s*([A-Z][a-z]+ [0-9]{4}) Release", re.MULTILINE)


def notice(release: str) -> str:
    """The credit line the O*NET licence page asks for, edits variant."""
    return (
        f"This file includes information from the O*NET {release} Database by the U.S. Department of Labor, "
        "Employment and Training Administration (USDOL/ETA). Used under the CC BY 4.0 license "
        f"({LICENCE_URL}). O*NET® is a trademark of USDOL/ETA. Worldloom has modified all or some of "
        "this information (selected and restructured by tools/ingest_onet.py). USDOL/ETA has not approved, "
        "endorsed, or tested these modifications."
    )


def _table(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    member = next((m for m in archive.namelist() if m.endswith("/" + name) or m == name), None)
    if member is None:
        raise KeyError(f"{archive.filename}: no member named {name!r}")
    with archive.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(text)]


def _readme(archive: zipfile.ZipFile) -> str:
    member = next((m for m in archive.namelist() if m.lower().endswith("read me.txt")), None)
    return archive.read(member).decode("utf-8", errors="replace") if member else ""


def ingest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        readme = _readme(archive)
        release_match = _RELEASE.search(readme)
        if not release_match:
            raise ValueError(f"{path.name}: the Read Me does not name an O*NET release")
        release = release_match.group(1)
        released_match = _RELEASED.search(readme)
        released = released_match.group(1) if released_match else ""

        occupations = _table(archive, "occupation_data.csv")
        zones = {r["O*NET-SOC Code"]: int(r["Job Zone"]) for r in _table(archive, "job_zones.csv") if r["Job Zone"]}
        reported: dict[str, list[str]] = {}
        for r in _table(archive, "sample_of_reported_titles.csv"):
            reported.setdefault(r["O*NET-SOC Code"], []).append(r["Reported Job Title"])
        alternate: dict[str, set[str]] = {}
        for r in _table(archive, "job_titles.csv"):
            alternate.setdefault(r["O*NET-SOC Code"], set()).add(r["Job Title"])
        dwas_by_task: dict[str, list[str]] = {}
        for r in _table(archive, "tasks_to_dwas.csv"):
            dwas_by_task.setdefault(r["Task ID"], []).append(r["DWA Element ID"])
        tasks: dict[str, list[dict[str, Any]]] = {}
        for r in _table(archive, "task_statements.csv"):
            tasks.setdefault(r["O*NET-SOC Code"], []).append({
                "id": int(r["Task ID"]),
                "text": r["Task"],
                "type": r["Task Type"].lower(),
                "dwas": sorted(set(dwas_by_task.get(r["Task ID"], []))),
            })
        software: dict[str, set[tuple[str, str, bool]]] = {}
        for r in _table(archive, "software_skills.csv"):
            software.setdefault(r["O*NET-SOC Code"], set()).add(
                (r["Element Name"], r["Workplace Example"], r["Hot Technology"].upper() == "Y")
            )
        activities = [
            {
                "gwa_id": r["GWA Element ID"], "gwa": r["GWA Element Name"],
                "iwa_id": r["IWA Element ID"], "iwa": r["IWA Element Name"],
                "dwa_id": r["DWA Element ID"], "dwa": r["DWA Element Name"],
            }
            for r in _table(archive, "gwas_to_iwas_to_dwas.csv")
        ]
    activities.sort(key=lambda a: a["dwa_id"])

    rows: list[dict[str, Any]] = []
    for r in sorted(occupations, key=lambda r: r["O*NET-SOC Code"]):
        code = r["O*NET-SOC Code"]
        rows.append({
            "code": code,
            "title": r["Title"],
            "description": r["Description"],
            "job_zone": zones.get(code),
            "reported_titles": reported.get(code, []),
            "job_titles": sorted(alternate.get(code, set())),
            "tasks": sorted(tasks.get(code, []), key=lambda t: t["id"]),
            "software": [
                {"category": category, "name": name, "hot": hot}
                for category, name, hot in sorted(software.get(code, set()))
            ],
        })

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "schema": SCHEMA,
        "release": release,
        "source": {"file": path.name, "sha256": digest, "bytes": path.stat().st_size, "released": released, "url": SOURCE_URL},
        "licence": LICENCE,
        "licence_url": LICENCE_URL,
        "notice": notice(release),
        "occupations": rows,
        "work_activities": activities,
    }


def write(document: dict[str, Any], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"occupations@{document['release']}.json.gz"
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.GzipFile(target, "wb", mtime=0) as handle:
        handle.write(payload)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", required=True, type=Path, help="The O*NET db_<release>_csv.zip archive.")
    parser.add_argument("--out", required=True, type=Path, help="Output directory (src/worldloom/_data/onet).")
    args = parser.parse_args(argv)
    document = ingest(args.input)
    target = write(document, args.out)
    row: dict[str, Any] = {
            "file": target.name, "release": document["release"], "released": document["source"]["released"],
            "source_file": document["source"]["file"], "source_sha256": document["source"]["sha256"],
            "source_url": SOURCE_URL,
            "occupations": len(document["occupations"]),
            "tasks": sum(len(o["tasks"]) for o in document["occupations"]),
            "software_rows": sum(len(o["software"]) for o in document["occupations"]),
            "job_titles": sum(len(o["job_titles"]) for o in document["occupations"]),
            "work_activities": len(document["work_activities"]),
    }
    ledger = {"schema": "worldloom.onet-provenance/v1", "licence": LICENCE, "licence_url": LICENCE_URL, "files": [row]}
    (args.out / "provenance.json").write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{target.name}: occupations={row['occupations']} tasks={row['tasks']} software={row['software_rows']} titles={row['job_titles']} dwas={row['work_activities']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
