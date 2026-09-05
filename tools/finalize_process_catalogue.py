#!/usr/bin/env python3
"""One-shot packaging migration for the uploaded process catalogue.

This exists only to make the branch rewrite reproducible in GitHub Actions: the
connector can commit text files but cannot stream a local binary upload. The
actual runtime has no dependency on this script.
"""

from __future__ import annotations

from pathlib import Path


PATH = Path("src/worldloom/process_catalogue.py")


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    if "def _decode_b85_zlib" in source:
        print("process catalogue packaging already finalised")
        return

    source = source.replace(
        "import csv\nimport io\nimport json\nimport zipfile\n",
        "import base64\nimport csv\nimport hashlib\nimport io\nimport json\nimport zlib\n",
    )
    source = source.replace(
        'def unique_units_and_countries(self) -> "CompanyProcessSpec":',
        "def unique_units_and_countries(self) -> CompanyProcessSpec:",
    )

    start = source.index("def _resource(*parts: str) -> Any:")
    end = source.index("\ndef catalogue() -> dict[str, Any]:", start)
    packaged = '''def _data_root() -> Any:\n    resource = files("worldloom")\n    for part in _DATA_DIR:\n        resource = resource.joinpath(part)\n    return resource\n\n\ndef _decode_b85_zlib(text: str) -> str:\n    packed = base64.b85decode(text.encode("ascii"))\n    return zlib.decompress(packed).decode("utf-8")\n\n\ndef _catalogue() -> dict[str, Any]:\n    root = _data_root()\n    encoded = "".join(\n        root.joinpath(f"catalogue.b85.{index:02d}").read_text(encoding="ascii")\n        for index in range(7)\n    )\n    payload = json.loads(_decode_b85_zlib(encoded))\n    if not isinstance(payload, dict):\n        raise ValueError("process catalogue must be a JSON object")\n    return payload\n\n\ndef _coverage_text() -> str:\n    encoded = _data_root().joinpath("coverage.csv.b85").read_text(encoding="ascii")\n    return _decode_b85_zlib(encoded)\n\n\ndef default_manifest() -> dict[str, dict[str, Any]]:\n    """Checksums of the 12 supplied precompiled defaults."""\n    payload = json.loads(\n        _data_root().joinpath("default-manifest.json").read_text(encoding="utf-8")\n    )\n    if not isinstance(payload, dict):\n        raise ValueError("default process manifest must be an object")\n    return payload\n'''
    source = source[:start] + packaged + source[end:]
    source = source.replace(
        'text = _resource("coverage.csv").read_text(encoding="utf-8")',
        "text = _coverage_text()",
    )

    start = source.index("def load_default(industry: str) -> ProcessCompilation:")
    end = source.index("\ndef _default_landscape()", start)
    verification = '''def _source_bytes(compilation: ProcessCompilation) -> bytes:\n    """Serialize exactly as the supplied reference compiler did."""\n    return "".join(\n        json.dumps(row.source_record(), ensure_ascii=False) + "\\n"\n        for row in compilation.rows\n    ).encode("utf-8")\n\n\ndef _assert_supplied_default(compilation: ProcessCompilation) -> None:\n    member = f"default-{compilation.spec.industry}.jsonl"\n    try:\n        expected = default_manifest()[member]\n    except KeyError as exc:\n        raise KeyError(\n            f"supplied default manifest missing {compilation.spec.industry!r}"\n        ) from exc\n    payload = _source_bytes(compilation)\n    actual = {\n        "bytes": len(payload),\n        "rows": payload.count(b"\\n"),\n        "sha256": hashlib.sha256(payload).hexdigest(),\n    }\n    if actual != expected:\n        raise ValueError(\n            f"compiled default {compilation.spec.industry!r} drifted from the "\n            f"supplied corpus: expected {expected}, got {actual}"\n        )\n\n\ndef load_default(industry: str) -> ProcessCompilation:\n    """Compile and verify the supplied reference company for one industry."""\n    compilation = compile_company(default_spec(industry))\n    _assert_supplied_default(compilation)\n    return compilation\n\n\ndef verify_defaults() -> dict[str, Any]:\n    """Prove the library reproduces the supplied 12-industry corpus byte-for-byte."""\n    mismatches: list[str] = []\n    totals = Counter()\n    for industry in industries():\n        live = compile_company(default_spec(industry))\n        try:\n            _assert_supplied_default(live)\n        except ValueError:\n            mismatches.append(industry)\n        totals["industries"] += 1\n        totals["instances"] += len(live.rows)\n        totals["eval_demands"] += live.summary.eval_demands\n\n    supplied = {\n        (cell.industry, cell.stream): (cell.status, cell.activities)\n        for cell in coverage_matrix()\n    }\n    recomputed = {\n        (cell.industry, cell.stream): (cell.status, cell.activities)\n        for industry in industries()\n        for cell in compile_company(default_spec(industry)).coverage\n    }\n    coverage_mismatch = supplied != recomputed\n    return {\n        **dict(totals),\n        "coverage_cells": len(supplied),\n        "mismatched_industries": tuple(mismatches),\n        "coverage_mismatch": coverage_mismatch,\n        "ok": not mismatches and not coverage_mismatch,\n    }\n\n\ndef iter_all_defaults() -> Iterable[ProcessCompilation]:\n    """Yield all 12 verified reference-company compilations in catalogue order."""\n    for industry in industries():\n        yield load_default(industry)\n'''
    source = source[:start] + verification + source[end:]

    duplicate = source.rfind("\ndef iter_all_defaults() -> Iterable[ProcessCompilation]:")
    first = source.find("\ndef iter_all_defaults() -> Iterable[ProcessCompilation]:")
    if duplicate != first and duplicate != -1:
        source = source[:duplicate].rstrip() + "\n"

    PATH.write_text(source, encoding="utf-8")
    print(f"rewrote {PATH}")


if __name__ == "__main__":
    main()
