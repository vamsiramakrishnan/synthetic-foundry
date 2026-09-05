"""One-shot, hash-guarded installation of the audited process-binding patch."""
from __future__ import annotations

import base64
import hashlib
import json
import lzma
import re
import subprocess
from pathlib import Path, PurePosixPath

BASE = "f474faa4b123383b71e56d472e511122af378c51"
PACKED = "94d294484c176e3a9e250316b47df84a6aad8d5a5eaaae08ade7160772acbf17"
PAYLOAD = "d63f0fe26f8fb865a2fb55ad7c11e24c11bc5fc0205d9bb889e48a4aa6916ae4"
ALLOWED = frozenset(""".claude/skills/worldloom-process-catalogue/SKILL.md
.github/workflows/process-catalogue-check.yml
CHANGELOG.md
docs/README.md
docs/process-catalogue.md
docs/sources/VOCABULARY.md
src/worldloom/_data/process-catalogue/catalogue.json
src/worldloom/_data/process-catalogue/defaults.json
src/worldloom/_data/process-catalogue/provenance.json
src/worldloom/_data/process-catalogue/source-compile_processes.py.txt
src/worldloom/_data/process-catalogue/source-coverage.csv
src/worldloom/_data/vocabulary-sources.json
src/worldloom/artifact_ecology.py
src/worldloom/predicates.py
src/worldloom/process_catalogue/__init__.py
src/worldloom/process_catalogue/__main__.py
src/worldloom/process_catalogue/adapters.py
src/worldloom/process_catalogue/compiler.py
src/worldloom/process_catalogue/models.py
src/worldloom/process_catalogue/storage.py
tests/test_ecology_sdk.py
tests/test_eval_interventions.py
tests/test_eval_metrics.py
tests/test_predicates.py
tests/test_process_catalogue.py
tools/compile_processes.py
tools/harvest_esco_rdf.py
tools/harvest_external_vocab.py
tools/harvest_jira_bson.py""".splitlines())


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def adapt(text: str) -> str:
    for before, after in (
        ("worldloom.process_catalogue", "worldloom.process_bindings"),
        ("src/worldloom/process_catalogue", "src/worldloom/process_bindings"),
        ("tests/test_process_catalogue.py", "tests/test_process_bindings.py"),
        ("tools/compile_processes.py", "tools/compile_process_bindings.py"),
        ("process-catalogue-check.yml", "process-bindings-check.yml"),
        ("worldloom-process-catalogue", "worldloom-process-bindings"),
        ("process-catalogue.md", "process-bindings.md"),
        ("process-catalogue/provenance.json", "process-catalogue/bindings-provenance.json"),
        ('"provenance.json"', '"bindings-provenance.json"'),
    ):
        text = text.replace(before, after)
    return text


def decode(root: Path) -> dict:
    parts = [root / f"part{i:02}.b64" for i in range(4)]
    if set(root.iterdir()) != set(parts):
        raise ValueError("unexpected transfer file set")
    packed = base64.b64decode("".join(p.read_text(encoding="ascii") for p in parts), validate=True)
    if sha(packed) != PACKED:
        raise ValueError("transfer checksum mismatch")
    raw = lzma.decompress(packed, memlimit=256 * 1024 * 1024)
    if sha(raw) != PAYLOAD:
        raise ValueError("patch checksum mismatch")
    payload = json.loads(raw)
    if payload.get("schema") != "worldloom-process-integration/v1":
        raise ValueError("unexpected patch schema")
    entries = payload["entries"]
    if len(entries) != len(ALLOWED) or {e["path"] for e in entries} != ALLOWED:
        raise ValueError("unexpected patch paths")
    return payload


def output_bytes(entry: dict, original: bytes | None) -> bytes:
    if entry["base"] is None:
        raw = entry["content"].encode("utf-8")
    else:
        if original is None or sha(original) != entry["base"]:
            raise ValueError(f"base checksum mismatch: {entry['path']}")
        lines = original.decode("utf-8").splitlines(keepends=True)
        for start, end, replacement in reversed(entry["edits"]):
            if not 0 <= start <= end <= len(lines):
                raise ValueError("invalid edit bounds")
            lines[start:end] = replacement.splitlines(keepends=True)
        raw = "".join(lines).encode("utf-8")
    if sha(raw) != entry["sha256"]:
        raise ValueError(f"output checksum mismatch: {entry['path']}")
    if entry["path"].startswith("src/worldloom/_data/") or entry["path"] == "docs/sources/VOCABULARY.md":
        return raw
    return adapt(raw.decode("utf-8")).encode("utf-8")


def main() -> None:
    payload = decode(Path(".github/process-bindings-transfer"))
    pending: dict[Path, bytes] = {}
    for entry in payload["entries"]:
        source = entry["path"]
        target = Path(adapt(source))
        if target.is_absolute() or ".." in PurePosixPath(target.as_posix()).parts:
            raise ValueError("unsafe target")
        for candidate in (target, *target.parents):
            if candidate.is_symlink():
                raise ValueError(f"symlink target: {candidate}")
        original = None
        if entry["base"] is not None:
            original = subprocess.check_output(["git", "show", f"{BASE}:{source}"])
        raw = output_bytes(entry, original)
        if target.exists():
            current = target.read_bytes()
            if source == "CHANGELOG.md" and sha(current) != entry["base"]:
                if any(start != end for start, end, _ in entry["edits"]):
                    raise ValueError("changelog merge must only add notes")
                text = current.decode("utf-8")
                heading = re.search(r"(?m)^##[^\n]*Unreleased[^\n]*\n", text)
                if heading is None:
                    raise ValueError("missing Unreleased heading")
                notes = adapt("".join(note for _, _, note in entry["edits"]))
                raw = (text[:heading.end()] + notes + text[heading.end():]).encode("utf-8")
                pending[target] = raw
                continue
            if source == "docs/README.md" and sha(current) != entry["base"]:
                note = "\n\n## Audited process bindings\n\n[Inspect activity bindings and evidence](process-bindings.md): shared-predicate search, structural ownership proofs, explicit coverage gaps and full export replay. The source-reference and operational planning APIs remain available.\n"
                pending[target] = current + note.encode("utf-8")
                continue
            if current == raw:
                continue
            if target.as_posix() != source or entry["base"] is None or sha(current) != entry["base"]:
                raise ValueError(f"concurrent change, refusing overwrite: {target}")
        pending[target] = raw
    for path, raw in pending.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    Path("/tmp/process-bindings-paths.txt").write_text("\n".join(sorted(p.as_posix() for p in pending)) + "\n")
    print(json.dumps({"files": len(pending), "payload_sha256": PAYLOAD, "reference_importer_preserved": True}))


if __name__ == "__main__":
    main()
