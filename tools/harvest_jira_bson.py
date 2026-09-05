#!/usr/bin/env python3
"""Stream the anonymised Public Jira Dataset Mongo dump into compact manifests.

The 5.8 GB source remains outside the repository. This command reads BSON files
incrementally and writes only aggregate field metadata: names, observed types,
fill rates, bounded option samples, issue-type mix, and source provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

_EMPTY = (None, "", [], {})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "multi"
    if isinstance(value, dict):
        if "value" in value:
            return "option"
        if "displayName" in value or "name" in value:
            return "object"
        return "object"
    return type(value).__name__.lower()


def option_label(value: Any) -> str | None:
    if isinstance(value, dict):
        candidate = value.get("value") or value.get("name") or value.get("displayName")
        return str(candidate) if candidate not in (None, "") else None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return None


def issue_candidates(value: Any) -> Iterable[dict[str, Any]]:
    """Yield embedded Jira issue payloads without assuming one dump layout."""
    if isinstance(value, dict):
        fields = value.get("fields")
        if isinstance(fields, dict) and ("issuetype" in fields or "project" in fields):
            yield value
            return
        for child in value.values():
            yield from issue_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from issue_candidates(child)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dump", type=Path, help="mongodump directory or a single BSON file")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", default="public-jira-dataset-anonymised-2025-06-23")
    args = parser.parse_args()

    try:
        from bson import decode_file_iter
    except ImportError as exc:
        raise SystemExit("install pymongo to parse BSON: python -m pip install pymongo") from exc

    bson_files = [args.dump] if args.dump.is_file() else sorted(args.dump.rglob("*.bson"))
    if not bson_files:
        raise SystemExit(f"no BSON files below {args.dump}")

    issues = 0
    issue_types: Counter[str] = Counter()
    projects: Counter[str] = Counter()
    field_nonempty: Counter[str] = Counter()
    field_types: dict[str, Counter[str]] = defaultdict(Counter)
    field_names: dict[str, str] = {}
    field_options: dict[str, Counter[str]] = defaultdict(Counter)

    for bson_file in bson_files:
        with bson_file.open("rb") as handle:
            for document in decode_file_iter(handle):
                for issue in issue_candidates(document):
                    fields = issue["fields"]
                    issues += 1
                    names = issue.get("names") or {}
                    if isinstance(names, dict):
                        field_names.update({str(key): str(value) for key, value in names.items()})
                    issue_type = fields.get("issuetype") or {}
                    if isinstance(issue_type, dict):
                        issue_types[str(issue_type.get("name") or "unknown")] += 1
                    project = fields.get("project") or {}
                    if isinstance(project, dict):
                        projects[str(project.get("key") or project.get("name") or "unknown")] += 1
                    for field_id, value in fields.items():
                        if not str(field_id).startswith("customfield_"):
                            continue
                        if value in _EMPTY:
                            continue
                        key = str(field_id)
                        field_nonempty[key] += 1
                        field_types[key][value_type(value)] += 1
                        label = option_label(value)
                        if label and len(field_options[key]) < 200:
                            field_options[key][label] += 1

    denominator = max(issues, 1)
    manifests: list[dict[str, Any]] = []
    for field_id, count in field_nonempty.most_common():
        types = field_types[field_id]
        inferred = types.most_common(1)[0][0] if types else "unknown"
        options = [label for label, _ in field_options[field_id].most_common(100)]
        manifests.append(
            {
                "id": field_id,
                "name": field_names.get(field_id, field_id),
                "aliases": [],
                "type": inferred,
                "options": options,
                "required_for": [],
                "screens": [],
                "fill_rate": count / denominator,
                "cardinality_lower_bound": len(field_options[field_id]),
                "canonical": None,
                "deprecated": False,
                "source": args.source,
                "evidence": "measured",
            }
        )

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "jira-field-manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
        for manifest in manifests:
            handle.write(json.dumps(manifest, sort_keys=True) + "\n")
    stats = {
        "source": args.source,
        "issues": issues,
        "projects": len(projects),
        "project_issue_counts": dict(projects.most_common()),
        "issue_type_mix": dict(issue_types.most_common()),
        "custom_fields_observed": len(manifests),
    }
    (args.out / "jira-priors.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    provenance = {
        "source": args.source,
        "bson_files": len(bson_files),
        "input_sha256": {path.name: sha256(path) for path in bson_files},
        "license": "CC BY 4.0; Public Jira Dataset, DOI 10.5281/zenodo.15719919",
    }
    (args.out / "jira-license.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"issues": issues, "fields": len(manifests), "out": str(args.out)}))


if __name__ == "__main__":
    main()
