"""Portable catalogue exports and source-attested planning vocabulary."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..corpus import write_json, write_jsonl
from .models import Catalogue, Compilation

if TYPE_CHECKING:
    from ..lexicon import LexiconRecord


def to_lexicon(compilation: Compilation) -> tuple[LexiconRecord, ...]:
    """Expose distinct authored activity concepts in the existing lexicon schema.

    Never canonicalise on an APQC hint: ``5.x`` is a placeholder, and numeric
    hints are not validated PCF identities either. Industry-scoped authored ids
    keep them separate until an explicit crosswalk is supplied.
    """
    from ..lexicon import EvidenceClass, LexiconRecord

    distinct = {r.activity_id: r for r in compilation.activities}
    return tuple(LexiconRecord(
        id=f"worldloom:authored:{compilation.company.industry}:{key}",
        canonical=f"worldloom:authored:{compilation.company.industry}:{key}",
        type="activity", label=row.activity, industry=compilation.company.industry,
        source=f"user-process-catalogue:{compilation.catalogue_sha256}",
        license="User-supplied authored material; no separate licence declaration supplied",
        evidence=EvidenceClass.AUTHORED_PRIOR,
    ) for key, row in sorted(distinct.items()))


def export_compilations(compilations: Iterable[Compilation], out: str | Path) -> dict[str, Any]:
    """Write a new directory. The manifest is the last publication marker.

    Existing nonempty directories are refused so a smaller recompile cannot
    leave stale companies looking like current output. Source factors ride the
    repository; each export records their semantic fingerprint and the exact
    company spec, including seed and custom landscape.
    """
    plans = sorted(compilations, key=lambda p: p.company.name)
    if not plans:
        raise ValueError("at least one compilation is required")
    names = [re.sub(r"[^a-zA-Z0-9_-]+", "-", p.company.name).strip("-") for p in plans]
    if not all(names) or len({n.casefold() for n in names}) != len(names):
        raise ValueError("company filenames are empty or collide")
    root = Path(out)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("output must be an empty directory; refusing stale or unrelated files")
    root.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        write_json(root / f"catalogue-{plan.catalogue_sha256}.json", json.loads(plan.catalogue_json))
    for name, plan in zip(names, plans, strict=True):
        write_jsonl(root / f"{name}.jsonl", list(plan.activities))
        write_jsonl(root / f"{name}.lexicon.jsonl", list(to_lexicon(plan)))
        write_json(root / f"{name}.plan.json", {
            "schema_version": plan.schema_version,
            "company": plan.company.model_dump(mode="json"),
            "catalogue_sha256": plan.catalogue_sha256,
            "catalogue_file": f"catalogue-{plan.catalogue_sha256}.json",
            "selection": plan.selection,
            "source_note": plan.source_note,
            "templates": [t.model_dump(mode="json") for t in plan.templates],
            "diagnostics": [d.model_dump(mode="json") for d in plan.diagnostics],
        })
    write_json(root / "coverage.json", {
        "summary": [p.summary for p in plans],
        "coverage": [{"company": p.company.name, **c.model_dump(mode="json")} for p in plans for c in p.coverage],
    })
    with (root / "coverage.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("company", "industry", "stream", "status", "core", "activities", "activity_instances", "calibration_requested", "calibration_applied"))
        for plan in plans:
            for cell in plan.coverage:
                writer.writerow((plan.company.name, cell.industry, cell.stream, cell.status, cell.core,
                                 cell.activities, cell.activity_instances, ";".join(cell.calibration_requested),
                                 ";".join(cell.calibration_applied)))
    audit = json.loads(files("worldloom").joinpath("_data", "processes", "intake.json").read_text(encoding="utf-8"))
    write_json(root / "licenses.json", {
        "sources": [{"source": "user-process-catalogue", "catalogue_sha256": p.catalogue_sha256,
                     "company": p.company.name, "evidence": "authored_prior", "attribution": "User-supplied Worldloom process catalogue",
                     "license": "No separate licence declaration supplied", "third_party_claims_verified": False}
                    for p in plans],
        "bundled_input_audit": audit,
        "note": "The bundled audit describes the supplied defaults, not a replacement catalogue. Source names do not imply ingested datasets or redistribution rights.",
    })
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir()) if p.is_file()}
    manifest = {"schema_version": "1", "compiler": "worldloom.process_planning/v1", "files": hashes,
                "activity_instances": sum(len(p.activities) for p in plans), "executable_evals": 0}
    write_json(root / "manifest.json", manifest)
    return manifest


def replay_plan(path: str | Path, *, strict: bool = False, max_instances: int = 100_000) -> Compilation:
    """Rebuild one exported plan from its pinned factors, not current defaults."""
    from .compiler import compile_company

    source = Path(path)
    plan = json.loads(source.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "1":
        raise ValueError("unsupported process plan schema version")
    digest = plan.get("catalogue_sha256", "")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid catalogue digest")
    expected = f"catalogue-{digest}.json"
    if plan.get("catalogue_file") != expected:
        raise ValueError("catalogue filename must match the pinned digest")
    manifest = json.loads((source.parent / "manifest.json").read_text(encoding="utf-8"))
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if manifest.get("files", {}).get(source.name) != actual:
        raise ValueError("plan digest mismatch; use --spec for an intentional edit")
    cat = Catalogue.model_validate_json((source.parent / expected).read_bytes())
    if cat.fingerprint != digest:
        raise ValueError("catalogue digest mismatch")
    if plan.get("selection") not in {"all", "core", "explicit"}:
        raise ValueError("unknown stream selection policy")
    return compile_company(plan["company"], cat, core_only=plan["selection"] == "core",
                           strict=strict, max_instances=max_instances)
