#!/usr/bin/env python3
"""Restore source-reference assets with independent upload-hash checks.

The reference compiler previously shipped without its data. The planning intake
preserves the catalogue bytes, coverage rows, and every uploaded ZIP member's
SHA-256. Reconstruction is accepted only when all those original digests match;
a compiler agreeing with itself is not sufficient. ZIP metadata is normalised,
so provenance distinguishes the repacked archive from the original container.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publish(path: Path, data: bytes) -> None:
    """Never overwrite different pre-existing source assets."""
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"different source asset already exists: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(data)
    temporary.replace(path)


def restore() -> dict[str, object]:
    source = ROOT / "src/worldloom/_data/processes"
    target = ROOT / "src/worldloom/_data/process-catalogue"
    intake = json.loads((source / "intake.json").read_text(encoding="utf-8"))
    catalogue = gzip.decompress((source / "catalogue.json.gz").read_bytes())
    if digest(catalogue) != intake["inputs"]["catalogue.json"]["sha256"]:
        raise ValueError("catalogue does not match the supplied source")
    coverage = "industry,stream,status,activities\n" + "".join(
        ",".join(str(row[key]) for key in ("industry", "stream", "status", "activities")) + "\n"
        for row in intake["legacy_coverage"]
    )
    coverage_bytes = coverage.encode("utf-8")
    if digest(coverage_bytes) != intake["inputs"]["coverage.csv"]["sha256"]:
        raise ValueError("coverage does not match the supplied source")
    publish(target / "catalogue.json", catalogue)
    publish(target / "coverage.csv", coverage_bytes)

    from worldloom.process_catalogue import compile_company, default_spec, industries

    members: dict[str, bytes] = {}
    for industry in industries():
        name = f"default-{industry}.jsonl"
        plan = compile_company(default_spec(industry))
        raw = "".join(
            json.dumps(row.source_record(), ensure_ascii=False) + "\n"
            for row in plan.rows
        ).encode("utf-8")
        expected = intake["reference_outputs"][name]
        if digest(raw) != expected["sha256"] or len(plan.rows) != expected["rows"]:
            raise ValueError(f"reference reconstruction differs from uploaded member: {name}")
        members[name] = raw
    if set(members) != set(intake["reference_outputs"]):
        raise ValueError("reference reconstruction has different archive members")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(members.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data, compresslevel=9)
    defaults = buffer.getvalue()
    publish(target / "defaults.zip", defaults)
    report: dict[str, object] = {
        "source_inputs": intake["inputs"],
        "members": {name: digest(data) for name, data in sorted(members.items())},
        "assets": {
            "catalogue.json": digest(catalogue),
            "coverage.csv": digest(coverage_bytes),
            "defaults.zip": digest(defaults),
        },
        "verification": "Every JSONL member is byte-identical to its uploaded member SHA-256.",
        "archive_note": "ZIP container metadata was normalised; its digest differs from the original upload.",
        "evidence_note": "Source coverage labels are preserved for reference parity, not asserted as applied calibration.",
    }
    publish(target / "provenance.json", (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return report


if __name__ == "__main__":
    result = restore()
    print(json.dumps({"verified_source_members": len(result["members"]), "assets": result["assets"]}, sort_keys=True))
