"""Deterministic, non-clobbering exports with input and output commitments."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ..corpus import write_json, write_jsonl
from .adapters import demands, lexicon_records
from .compiler import compile_company, fingerprint, resource
from .models import CompiledCatalogue


def summary(compiled: CompiledCatalogue) -> dict[str, Any]:
    demand_counts = Counter(d.status for d in demands(compiled))
    return {"company":compiled.company,"industry":compiled.industry,"digest":compiled.digest,
            "activities":len({r.activity_id for r in compiled.rows}),"activity_instances":len(compiled.rows),
            "defined_streams":sum(c.status != "missing_definition" for c in compiled.coverage),
            "missing_core_streams":[c.stream for c in compiled.coverage if c.status == "missing_definition"],
            "template_demands":sum(demand_counts.values()),"demand_statuses":dict(sorted(demand_counts.items())),
            "measured_calibrations":0,"ready":compiled.ready,
            "finding_counts":dict(sorted(Counter(f.code for f in compiled.findings).items()))}


def write_compilation(compiled: CompiledCatalogue, output: Path) -> dict[str, Any]:
    """Refuse even an existing empty directory; partial outputs cannot look fresh."""
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "compilation.json", compiled.model_dump(mode="json"))
    write_jsonl(output / "activities.jsonl", list(compiled.rows))
    write_jsonl(output / "demands.jsonl", list(demands(compiled)))
    write_jsonl(output / "lexicon.jsonl", list(lexicon_records(compiled)))
    write_jsonl(output / "findings.jsonl", list(compiled.findings))
    write_json(output / "licenses.json", json.loads(compiled.licenses_json))
    write_json(output / "summary.json", summary(compiled))
    with (output / "coverage.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["industry","stream","status","activities","activity_instances","core","calibration_status","calibration_targets"])
        for cell in compiled.coverage:
            writer.writerow([cell.industry,cell.stream,cell.status,cell.activities,cell.activity_instances,
                             cell.core,cell.calibration_status,";".join(cell.calibration_targets)])
    commitments = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir())}
    manifest = {"schema_version":"worldloom.process-export/v1","compilation_digest":compiled.digest,
                "files":commitments,"summary":summary(compiled)}
    write_json(output / "manifest.json", manifest)
    return manifest


def verify_export(output: Path, *, catalogue: dict[str, Any] | None = None) -> CompiledCatalogue:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    required = {"compilation.json","activities.jsonl","demands.jsonl","lexicon.jsonl",
                "findings.jsonl","licenses.json","summary.json","coverage.csv"}
    if manifest.get("schema_version") != "worldloom.process-export/v1" or set(manifest.get("files", {})) != required:
        raise ValueError("invalid export manifest")
    if {p.name for p in output.iterdir()} != required | {"manifest.json"}:
        raise ValueError("unexpected export files")
    for name, expected in manifest["files"].items():
        path = output / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"export checksum mismatch: {name}")
    compiled = CompiledCatalogue.model_validate_json((output / "compilation.json").read_text(encoding="utf-8"))
    if compiled.digest != manifest["compilation_digest"]:
        raise ValueError("compilation commitment mismatch")
    replay = compile_company(json.loads(compiled.spec_json), catalogue=catalogue, core_only=compiled.core_only)
    if replay != compiled:
        raise ValueError("export does not replay against the supplied/installed catalogue")
    # Check all projections too. Updating a manifest hash cannot legitimize a
    # demand, coverage or license file inconsistent with its compiled source.
    with TemporaryDirectory(prefix="worldloom-process-verify-") as temporary:
        expected_output = Path(temporary) / "expected"
        write_compilation(replay, expected_output)
        for name in required | {"manifest.json"}:
            if (output / name).read_bytes() != (expected_output / name).read_bytes():
                raise ValueError(f"export projection differs from replay: {name}")
    return compiled



def baseline_parity(compiled: CompiledCatalogue) -> bool:
    reference = resource("bindings-provenance.json")["compiled_baselines"].get(f"{compiled.company}.jsonl")
    return bool(reference and fingerprint([r.legacy_record() for r in compiled.rows]) == reference["semantic_sha256"])


def replay_builtin(compiled: CompiledCatalogue) -> bool:
    """Check the complete value, not merely output checksums, against source data."""
    replay = compile_company(json.loads(compiled.spec_json), core_only=compiled.core_only)
    return replay == compiled
