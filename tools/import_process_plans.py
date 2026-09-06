#!/usr/bin/env python3
"""Audit the five supplied inputs without executing the supplied Python.

The archive is read in place, never extracted. Its outputs are regression
references, not proof that APQC/Jira/BPI data were downloaded or calibrated.
"""
from __future__ import annotations

import argparse
import ast
import csv
import gzip
import hashlib
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from worldloom.process_planning.models import ACTIVITY_COLUMNS, Catalogue

PROJECTION = (
    "activity_id", "stream", "stream_name", "activity", "apqc", "function", "owner_kind", "owner_bu",
    "bu_archetype", "country", "sor_class", "sor_product", "type", "control", "exception", "variant", "eval_templates",
)
INPUTS = ("catalogue.json", "compile_processes.py", "coverage.csv", "VOCABULARY.md", "all-12-industries.zip")


def signature(rows: list[dict[str, Any]]) -> str:
    projected = [{k: r[k] for k in PROJECTION} for r in rows]
    projected.sort(key=lambda r: (r["stream"], r["activity_id"], r["owner_bu"], r["country"]))
    return hashlib.sha256(json.dumps(projected, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def audit_inputs(inputs: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = {name: (inputs / name).read_bytes() for name in INPUTS}
    constants: dict[str, Any] = {}
    for node in ast.parse(raw["compile_processes.py"]).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"COLS", "DEFAULT_ORGS", "DEFAULT_LANDSCAPE"}:
                    if target.id in constants:
                        raise ValueError(f"duplicate constant {target.id}")
                    constants[target.id] = ast.literal_eval(node.value)
    if tuple(constants.get("COLS", ())) != ACTIVITY_COLUMNS:
        raise ValueError("uploaded compiler declares incompatible activity columns")
    cat = Catalogue.model_validate_json(raw["catalogue.json"])
    if set(constants["DEFAULT_ORGS"]) != set(cat.industry_overlays):
        raise ValueError("default companies and catalogue industries differ")
    default_data = {"landscape": constants["DEFAULT_LANDSCAPE"], "orgs": constants["DEFAULT_ORGS"]}
    audit: dict[str, Any] = {
        "inputs": {name: {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)} for name, value in raw.items()},
        "reference_outputs": {}, "legacy_coverage": [],
        "note": "Legacy corpus_calibrated labels are supplied claims, not runtime evidence. Positional compiler constants were read with AST literal_eval; uploaded Python was not executed.",
    }
    observed: dict[tuple[str, str], set[str]] = defaultdict(set)
    expected_names = {f"default-{ind}.jsonl" for ind in cat.industry_overlays}
    with zipfile.ZipFile(io.BytesIO(raw["all-12-industries.zip"])) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names) or set(names) != expected_names:
            raise ValueError("archive must contain exactly one flat JSONL per catalogue industry")
        if sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
            raise ValueError("archive exceeds 64 MiB intake budget")
        for name in sorted(names):
            value = archive.read(name)
            rows = [json.loads(line) for line in value.splitlines() if line.strip()]
            industry = name.removeprefix("default-").removesuffix(".jsonl")
            keys = [(r["stream"], r["activity_id"], r["owner_bu"], r["country"]) for r in rows]
            if len(set(keys)) != len(keys):
                raise ValueError(f"{name}: duplicate activity instance")
            for row in rows:
                observed[(industry, row["stream"])].add(row["activity_id"])
            audit["reference_outputs"][name] = {
                "sha256": hashlib.sha256(value).hexdigest(), "rows": len(rows),
                "distinct_activities": len({r["activity_id"] for r in rows}),
                "streams": len({r["stream"] for r in rows}), "structural_sha256": signature(rows),
            }
    coverage = list(csv.DictReader(io.StringIO(raw["coverage.csv"].decode("utf-8-sig"))))
    seen: set[tuple[str, str]] = set()
    for row in coverage:
        key = row["industry"], row["stream"]
        if key in seen or key not in observed or int(row["activities"]) != len(observed[key]):
            raise ValueError(f"coverage and archive disagree at {key}")
        seen.add(key)
        industry, sid = key
        overlay = cat.industry_overlays[industry]
        streams = {**cat.value_streams, **overlay.specific}
        if sid not in streams or len(streams[sid].activities) != int(row["activities"]):
            raise ValueError(f"coverage and catalogue disagree at {key}")
        expected = "corpus_calibrated" if streams[sid].calibrate else "overlay" if sid in overlay.specific else "backbone"
        if row["status"] != expected:
            raise ValueError(f"legacy coverage status differs from supplied compiler at {key}")
    if seen != set(observed):
        raise ValueError("coverage omits archived streams")
    audit["legacy_coverage"] = coverage
    audit["source_activity_instances"] = sum(r["rows"] for r in audit["reference_outputs"].values())
    audit["source_industry_stream_cells"] = len(coverage)
    audit["source_legacy_calibrated_claims"] = sum(r["status"] == "corpus_calibrated" for r in coverage)
    return audit, default_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    audit, defaults = audit_inputs(args.inputs)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in (("catalogue.json.gz", (args.inputs / "catalogue.json").read_bytes()),
                       ("defaults.json.gz", json.dumps(defaults, sort_keys=True, ensure_ascii=False).encode())):
        (args.out / name).write_bytes(gzip.compress(data, mtime=0))
    (args.out / "intake.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in audit.items() if k.startswith("source_")}, sort_keys=True))


if __name__ == "__main__":
    main()
