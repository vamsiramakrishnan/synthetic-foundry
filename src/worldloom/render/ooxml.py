"""Shared packaging concerns for the Office formats.

XLSX, DOCX and PPTX are the same thing underneath: a zip archive of XML parts.
They therefore share a defect that has nothing to do with their content — a zip
records a modification time per entry, filled from the clock at save, so two
renders of an identical document differ in bytes while being identical in
meaning. That breaks the project's central claim, which is that a world
regenerates byte-for-byte from its seed and its ledger.

This is corrected after the fact rather than by patching each library, so the
result holds for whatever version of openpyxl or python-docx happens to be
installed.

The two libraries misbehave differently, which is why the timestamp rewrite is
here and not in one of them:

- **openpyxl** overwrites ``dcterms:modified`` with ``now()`` *inside* ``save``,
  after any value set on ``workbook.properties``, so it cannot be fixed before
  the fact.
- **python-docx** leaves the core properties alone but seeds them from its
  default template — a document that says it was created in 2013 unless told
  otherwise.

Both are handled by writing the world-derived stamp into both elements.

The zip-timestamp half was found by CI, not locally: two runs of the replay check
landed either side of a second boundary and the files differed. Locally they had
always shared a second, so the defect passed unnoticed for weeks.

A **chart's embedded workbook** is the same defect one level deeper. A native
chart in a ``.docx`` or ``.pptx`` — see ``docx.py``/``pptx.py`` — is not one part
but two: the ``c:chartSpace`` XML, and (for ``pptx.py``, whose chart API always
creates one) a small ``.xlsx`` workbook of the plotted values, embedded as an
opaque binary part. That workbook is itself a zip, built by ``xlsxwriter``, and
``xlsxwriter.workbook.Workbook.__init__`` stamps its own ``docProps/core.xml``
with ``datetime.now(timezone.utc)`` — a second clock, nested inside the first,
that the top-level substitution above never reaches because it only reads
``docProps/core.xml`` at the outer package's own root. Found the same way the
first one was: two renders a few seconds apart, diffed.
"""

from __future__ import annotations

import re
from io import BytesIO

#: Fixed timestamp for every archive entry. The earliest a zip can represent, so
#: it reads as deliberately unset rather than as a plausible date.
EPOCH = (1980, 1, 1, 0, 0, 0)

_CORE_PART = "docProps/core.xml"

_TIMESTAMPS = (
    re.compile(rb"(<dcterms:created[^>]*>)[^<]*(</dcterms:created>)"),
    re.compile(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)"),
)


_CUSTOM_PART = "docProps/custom.xml"
_CUSTOM_TYPE = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
_CUSTOM_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
#: The format id every custom property carries (``{D5CDD505-...}`` is the one
#: Word and PowerPoint write for user-defined properties).
_CUSTOM_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"


def with_custom_properties(payload: bytes, properties: dict[str, str]) -> bytes:
    """*payload* with *properties* written as the package's custom properties.

    Where a reader profile puts provenance: Word's File > Info > Properties >
    Custom and PowerPoint's the same, readable by any tool that opens the
    package (`artifact_text` reports them) and never printed on a page. Written
    at the zip level, the way `normalise` fixes timestamps, so it holds for
    whatever python-docx or python-pptx is installed; neither has an API for
    the part. Properties are written in sorted order so the bytes are a
    function of the mapping alone.
    """
    from xml.sax.saxutils import escape
    from zipfile import ZIP_DEFLATED, ZipFile

    if not properties:
        return payload
    entries = "".join(
        f'<property fmtid="{_CUSTOM_FMTID}" pid="{pid}" name="{escape(name, {chr(34): "&quot;"})}">'
        f"<vt:lpwstr>{escape(value)}</vt:lpwstr></property>"
        for pid, (name, value) in enumerate(sorted(properties.items()), start=2)
    )
    custom = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        f"{entries}</Properties>"
    ).encode()
    source = BytesIO(payload)
    target = BytesIO()
    with ZipFile(source) as original, ZipFile(target, "w", ZIP_DEFLATED) as rebuilt:
        for info in original.infolist():
            if info.filename == _CUSTOM_PART:
                continue
            content = original.read(info.filename)
            if info.filename == "[Content_Types].xml" and b"/docProps/custom.xml" not in content:
                content = content.replace(
                    b"</Types>",
                    f'<Override PartName="/{_CUSTOM_PART}" ContentType="{_CUSTOM_TYPE}"/></Types>'.encode())
            elif info.filename == "_rels/.rels" and _CUSTOM_REL.encode() not in content:
                content = content.replace(
                    b"</Relationships>",
                    f'<Relationship Id="rIdWorldloomCustom" Type="{_CUSTOM_REL}" Target="{_CUSTOM_PART}"/>'
                    "</Relationships>".encode())
            rebuilt.writestr(info, content)
        rebuilt.writestr(_CUSTOM_PART, custom)
    return target.getvalue()


def custom_properties(archive_bytes: bytes) -> dict[str, str]:
    """The custom properties of an Office package, or ``{}``."""
    from xml.etree import ElementTree
    from zipfile import ZipFile

    with ZipFile(BytesIO(archive_bytes)) as archive:
        if _CUSTOM_PART not in archive.namelist():
            return {}
        root = ElementTree.fromstring(archive.read(_CUSTOM_PART))
    out: dict[str, str] = {}
    for prop in root:
        name = prop.get("name")
        if name:
            out[name] = "".join(prop.itertext())
    return out


def normalise(payload: bytes, *, created: str | None = None) -> bytes:
    """Strip the wall clock out of a finished Office package.

    *created* is an ISO timestamp derived from the world — the moment the
    document would have been written — and is stamped into both core-property
    dates. Omit it and only the archive entries are fixed.

    The XML substitution is deliberately narrow, two elements whose content is a
    timestamp, which is why it does not warrant an XML parser.
    """
    from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo, is_zipfile

    stamp = None if created is None else created.replace("+00:00", "Z").encode()

    source = BytesIO(payload)
    target = BytesIO()
    with ZipFile(source) as original, ZipFile(target, "w", ZIP_DEFLATED) as rebuilt:
        for info in original.infolist():
            content = original.read(info.filename)
            if stamp is not None and info.filename == _CORE_PART:
                for pattern in _TIMESTAMPS:
                    content = pattern.sub(rb"\g<1>" + stamp + rb"\g<2>", content)
            elif info.filename.lower().endswith(".xlsx") and is_zipfile(BytesIO(content)):
                # A chart's embedded data-source workbook — see this module's
                # own docstring for why it carries a second, nested clock.
                # It is itself an OPC package with a `docProps/core.xml` at
                # the same relative path, so the fix is this same function,
                # recursively, with the same *created* stamp: the workbook
                # was generated at the same moment as the document around it.
                content = normalise(content, created=created)
            fixed = ZipInfo(filename=info.filename, date_time=EPOCH)
            fixed.compress_type = info.compress_type
            fixed.external_attr = info.external_attr
            fixed.internal_attr = info.internal_attr
            fixed.create_system = 3  # Unix, so the host OS does not leak in either
            rebuilt.writestr(fixed, content)
    return target.getvalue()
