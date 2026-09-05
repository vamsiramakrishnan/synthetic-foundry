#!/usr/bin/env python3
"""Extract company-defined segment/member names from 10-K inline XBRL contexts."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path

_CONTEXT = re.compile(r"<xbrli:context\b.*?</xbrli:context>", re.IGNORECASE | re.DOTALL)
_MEMBER = re.compile(
    r"<xbrldi:(?:explicitMember|typedMember)\b[^>]*>(.*?)</xbrldi:(?:explicitMember|typedMember)>",
    re.IGNORECASE | re.DOTALL,
)
_TAGS = re.compile(r"<[^>]+>")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def member_label(raw: str) -> str | None:
    text = html.unescape(_TAGS.sub("", raw)).strip()
    if not text:
        return None
    local = text.rsplit(":", 1)[-1]
    for suffix in ("SegmentMember", "Member"):
        if local.endswith(suffix):
            local = local[: -len(suffix)]
            break
    label = _CAMEL.sub(" ", local).replace("_", " ").strip()
    if not label or label.lower() in {"consolidation", "elimination", "other"}:
        return None
    return label


def extract(path: Path) -> Counter[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    counts: Counter[str] = Counter()
    for context in _CONTEXT.findall(text):
        for raw in _MEMBER.findall(context):
            label = member_label(raw)
            if label:
                counts[label] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("filings", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", default="sec-edgar-10k")
    args = parser.parse_args()

    aggregate: Counter[str] = Counter()
    by_file: dict[str, dict[str, int]] = {}
    for path in args.filings:
        counts = extract(path)
        aggregate.update(counts)
        by_file[path.name] = dict(counts.most_common())

    args.out.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "id": f"edgar:segment:{re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')}",
            "type": "team",
            "label": label,
            "canonical": None,
            "alt_labels": [],
            "lang": "en",
            "industry": None,
            "region": "US",
            "weight": count / max(sum(aggregate.values()), 1),
            "source": args.source,
            "license": "US Government public filing data; SEC fair-access policy",
            "evidence": "measured",
        }
        for label, count in aggregate.most_common()
    ]
    with (args.out / "edgar-segments.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (args.out / "edgar-segment-stats.json").write_text(
        json.dumps({"files": by_file, "segments": len(rows)}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"segments": len(rows), "out": str(args.out)}, sort_keys=True))


if __name__ == "__main__":
    main()
