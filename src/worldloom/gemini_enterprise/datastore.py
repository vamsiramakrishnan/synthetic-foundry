"""The corpus as Discovery Engine documents, permissions included.

Eval Studio selects data stores; it has no ingestion path. So the half of this
integration that decides whether any score means anything is not in that
repository at all: getting a company whose every answer is a canonical fact
into the index the assistant searches.

This reads a **written workspace**, not the world's layout recomputed. That is
the same rule `workspace.write` sets for itself and for the same reason: the
tree on disk is what gets uploaded to Cloud Storage, and a second layout is a
second chance to disagree with it about a path, with nothing to say which was
right. It also means the drive's junk comes along -- the misfiled copies and
`(v2 FINAL)` duplicates `workspace` adds at `--noise lived_in` -- which is the
most interesting content in the store, because a near-duplicate is where these
products actually fail and it is indistinguishable from the original by reading
it.

Two details here are not cosmetic.

**Document ids come from the path, not only the artifact id.** A noise copy
carries the `artifact_id` of the file it copies -- deliberately, so the
manifest can say what it duplicates. Import them under that id and
`importDocuments` treats the second as an update of the first: the duplicates
collapse, the store quietly holds one document where the drive holds four, and
the corpus's hardest content disappears between export and index with nothing
red anywhere.

**A file whose type Discovery Engine will not accept is skipped and said out
loud**, never relabelled. `text/markdown` is not on the accepted list and
markdown genuinely is plain text, so that mapping is a wire-type declaration
and is fine. An `.xlsx` announced as `text/plain` is not the same thing: it is
a corrupt document that indexes as mojibake and degrades retrieval for every
query that touches it. `Export.skipped` names each one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: File suffix to the MIME type Discovery Engine accepts for unstructured
#: content. Keyed on the suffix rather than the artifact's `media_type`,
#: because the file on the drive is what gets uploaded and its extension is
#: what says what it is.
#:
#: `.md` maps to `text/plain` because Discovery Engine's accepted list has no
#: `text/markdown` and markdown is plain text -- the bytes are unchanged and
#: nothing is being claimed that is not true. Every entry here is that kind of
#: mapping; a type needing conversion is absent on purpose.
MEDIA_TYPES: Mapping[str, str] = {
    ".md": "text/plain",
    ".txt": "text/plain",
    ".csv": "text/plain",
    ".json": "application/json",
    ".html": "text/html",
    ".htm": "text/html",
    ".xml": "application/xml",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

#: What a caller gets told about rather than shown: a suffix with no accepted
#: MIME type. Named so a test can assert the refusal is a refusal and not a
#: silent drop.
UNSUPPORTED_MEDIA = "unsupported_media_type"


@dataclass(frozen=True)
class Export:
    """The documents, and what could not be one."""

    documents: tuple[dict[str, Any], ...] = ()
    skipped: tuple[str, ...] = ()
    """One sentence per file left out, in the shape `phrasing.findings` uses.
    Empty means every file on the drive became a document."""

    def jsonl(self) -> str:
        """The documents as the `gcsSource` `dataSchema: "document"` format.

        One JSON document per line, keys sorted, newline pinned -- the same
        contract `corpus.write_jsonl` holds for everything else this engine
        writes. Not routed through it because these are plain dicts shaped by
        someone else's API, not this engine's models.
        """
        return "".join(
            json.dumps(document, sort_keys=True) + "\n" for document in self.documents
        )


def _principals(readers: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """The ACL for one document.

    Empty readers means *everyone*, which is what an unrestricted `All staff`
    policy says and what `workspace.Placed.readers` encodes as an empty tuple.
    That is `idpWide`, not an empty principal list: an empty `principals` array
    is a document nobody can read, so the two spellings differ by the whole
    corpus.
    """
    if not readers:
        return {"readers": [{"idpWide": True}]}
    return {
        "readers": [
            {"principals": [{"userId": address} for address in sorted(set(readers))]}
        ]
    }


def _document_id(row: Mapping[str, Any]) -> str:
    """A unique, RFC-1034-safe id for one placed file.

    The artifact id when the file is the artifact, and the artifact id plus a
    content address of its path when it is one of the drive's copies -- which
    all share the id of what they copy. Readable, so an operator looking at a
    store can see which original a duplicate belongs to, and unique, so the
    duplicates survive the import.
    """
    from ..ids import content_key

    artifact_id = str(row["artifact_id"])
    if not row.get("noise"):
        return artifact_id
    return f"{artifact_id}-{content_key(row['path'])[:12]}"


def documents(
    world: Any, workspace_root: str | Path, *, uri_prefix: str
) -> Export:
    """Every file in a written workspace as a Discovery Engine document.

    *workspace_root* is a directory `worldloom workspace` wrote: the tree plus
    its `permissions.jsonl`. *uri_prefix* is where those files will live in
    Cloud Storage (`gs://bucket/prefix`), because `Document.content.uri` takes
    a `gs://` URI and nothing else -- the import reads the bytes from there,
    not from this machine.
    """
    root = Path(workspace_root)
    table = root / "permissions.jsonl"
    if not table.is_file():
        raise ValueError(
            f"{root} holds no permissions.jsonl, so it is not a workspace this"
            " can read; write one with `worldloom workspace <corpus> -o"
            f" {root}` first. Laying the tree out again here would be a second"
            " account of the same drive."
        )
    prefix = uri_prefix.rstrip("/")
    if not prefix.startswith("gs://"):
        raise ValueError(
            f"uri_prefix must be a Cloud Storage URI (gs://bucket/prefix), got"
            f" {uri_prefix!r}; Document.content.uri accepts no other scheme."
        )

    artifacts = {artifact.id: artifact for artifact in world.artifacts}
    rows = [
        json.loads(line)
        for line in table.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    out: list[dict[str, Any]] = []
    skipped: list[str] = []
    for row in sorted(rows, key=lambda r: str(r["path"])):
        path = str(row["path"])
        suffix = Path(path).suffix.lower()
        mime = MEDIA_TYPES.get(suffix)
        if mime is None:
            skipped.append(
                f"{path!r} has suffix {suffix!r}, which Discovery Engine"
                f" accepts no MIME type for ({UNSUPPORTED_MEDIA}); indexing it"
                " under a type it is not would corrupt every query that"
                " reaches it"
            )
            continue

        artifact = artifacts.get(str(row["artifact_id"]))
        # Everything the drive knows and a two-column CSV could not carry. Kept
        # flat and string-valued so it survives a data store with no registered
        # schema, which is what an operator gets by default.
        struct: dict[str, Any] = {
            "title": row["title"],
            "path": path,
            "folder": path.rpartition("/")[0],
            "owner": row["owner"],
            "policy": row["policy"],
            "created": row["created"],
            "artifact_id": row["artifact_id"],
        }
        for key in ("superseded_by", "noise", "copy_of"):
            if row.get(key) is not None:
                struct[key] = row[key]
        if artifact is not None:
            struct.update(
                {
                    "artifact_type": artifact.artifact_type,
                    "domain": artifact.domain,
                    "authority": artifact.authority,
                    "lifecycle": artifact.lifecycle,
                    "version": artifact.version,
                }
            )

        out.append(
            {
                "id": _document_id(row),
                "structData": struct,
                "content": {"mimeType": mime, "uri": f"{prefix}/{path}"},
                "aclInfo": _principals(row.get("readers") or ()),
            }
        )
    return Export(documents=tuple(out), skipped=tuple(skipped))


__all__ = ["MEDIA_TYPES", "UNSUPPORTED_MEDIA", "Export", "documents"]
