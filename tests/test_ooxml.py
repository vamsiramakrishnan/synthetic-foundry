"""Step 5.5: chart parts, and the second clock they carry.

``ooxml.normalise`` scrubs the wall clock out of a finished Office package —
see its own module docstring. Native charts (``docx.py``/``pptx.py``) add a
second archive nested inside the first: a chart's embedded data-source
workbook is itself a zip, with its own ``docProps/core.xml``, and
``xlsxwriter`` (which `python-pptx`'s chart API uses to build it) stamps that
one with ``datetime.now()``. These tests build the nesting directly, with
plain ``zipfile``, rather than through a real chart — the defect is about the
*packaging*, not about anything either renderer does, so it is worth proving
independently of both.
"""

from __future__ import annotations

import io
import zipfile

from worldloom.render import ooxml

_CORE_TEMPLATE = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    b'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    b'<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
    b'<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
    b"</cp:coreProperties>"
)


def _core_xml(stamp: bytes) -> bytes:
    return _CORE_TEMPLATE % (stamp, stamp)


def _zip(entries: dict[str, bytes], *, wall_clock: bool = True) -> bytes:
    """A minimal zip, entries stamped with a non-epoch date unless told
    otherwise — the same wall-clock-by-default behaviour `python-pptx`'s own
    OPC writer has (see `ooxml.py`'s module docstring)."""
    buffer = io.BytesIO()
    date_time = (2024, 6, 15, 12, 30, 0) if wall_clock else ooxml.EPOCH
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(zipfile.ZipInfo(filename=name, date_time=date_time), content)
    return buffer.getvalue()


def _nested_package(created_wall_clock: bytes = b"2024-06-15T12:30:00Z") -> bytes:
    """An outer OOXML-shaped zip carrying an embedded ``.xlsx`` chart
    workbook, itself a zip with its own wall-clock ``docProps/core.xml`` —
    the exact shape `pptx.py`'s native charts produce."""
    embedded = _zip({
        "docProps/core.xml": _core_xml(created_wall_clock),
        "xl/workbook.xml": b"<workbook/>",
    })
    return _zip({
        "docProps/core.xml": _core_xml(created_wall_clock),
        "ppt/presentation.xml": b"<presentation/>",
        "ppt/embeddings/Microsoft_Excel_Sheet1.xlsx": embedded,
    })


def test_every_archive_entry_loses_its_wall_clock_including_nested_ones() -> None:
    normalised = ooxml.normalise(_nested_package())
    with zipfile.ZipFile(io.BytesIO(normalised)) as outer:
        assert {info.date_time for info in outer.infolist()} == {ooxml.EPOCH}
        embedded = outer.read("ppt/embeddings/Microsoft_Excel_Sheet1.xlsx")
        with zipfile.ZipFile(io.BytesIO(embedded)) as inner:
            assert {info.date_time for info in inner.infolist()} == {ooxml.EPOCH}


def test_the_created_stamp_reaches_the_embedded_workbooks_own_core_xml() -> None:
    """Not just scrubbed — replaced with the world's own stamp, the same way
    the outer package's `docProps/core.xml` is. Otherwise the embedded
    workbook would claim to have been created at the zip epoch, which is a
    smaller lie than `now()` but still a wrong one."""
    stamp = "2026-04-08T09:40:00+00:00"
    normalised = ooxml.normalise(_nested_package(), created=stamp)
    with zipfile.ZipFile(io.BytesIO(normalised)) as outer:
        outer_core = outer.read("docProps/core.xml")
        assert b"2026-04-08T09:40:00Z" in outer_core
        embedded = outer.read("ppt/embeddings/Microsoft_Excel_Sheet1.xlsx")
        with zipfile.ZipFile(io.BytesIO(embedded)) as inner:
            inner_core = inner.read("docProps/core.xml")
            assert b"2026-04-08T09:40:00Z" in inner_core
            assert b"2024-06-15T12:30:00Z" not in inner_core


def test_two_packages_built_a_clock_tick_apart_normalise_identically() -> None:
    """The property that actually matters: two archives differing only in
    their (embedded and outer) wall-clock timestamps become byte-identical
    once normalised with the same *created* stamp — the same claim
    `test_pptx.py::test_no_clock_reaches_a_chart_deck_including_its_embedded_workbook`
    makes against a real deck, proven here against the packaging alone."""
    stamp = "2026-04-08T09:40:00+00:00"
    first = ooxml.normalise(_nested_package(b"2024-06-15T12:30:00Z"), created=stamp)
    second = ooxml.normalise(_nested_package(b"2031-01-01T00:00:00Z"), created=stamp)
    assert first == second


def test_normalising_twice_is_idempotent() -> None:
    stamp = "2026-04-08T09:40:00+00:00"
    once = ooxml.normalise(_nested_package(), created=stamp)
    twice = ooxml.normalise(once, created=stamp)
    assert once == twice


def test_a_file_merely_named_xlsx_that_is_not_actually_a_zip_is_left_alone() -> None:
    """Defensive only — every real ``.xlsx``-named part inside a docx/pptx/
    xlsx package this project produces is itself a zip (a chart's embedded
    workbook), but a corrupt or unrelated same-named part should not crash
    the whole render; it should simply not be recursed into."""
    payload = _zip({
        "docProps/core.xml": _core_xml(b"2024-06-15T12:30:00Z"),
        "ppt/embeddings/not_actually_a_workbook.xlsx": b"not a zip file",
    })
    normalised = ooxml.normalise(payload, created="2026-04-08T09:40:00+00:00")
    with zipfile.ZipFile(io.BytesIO(normalised)) as archive:
        assert archive.read("ppt/embeddings/not_actually_a_workbook.xlsx") == b"not a zip file"
        assert {info.date_time for info in archive.infolist()} == {ooxml.EPOCH}


def test_without_a_created_stamp_only_the_archive_entries_are_fixed() -> None:
    """Matches the top-level behaviour documented on `normalise` itself:
    *created* is optional, and omitting it leaves the XML content (at every
    nesting depth) untouched."""
    normalised = ooxml.normalise(_nested_package(b"2024-06-15T12:30:00Z"))
    with zipfile.ZipFile(io.BytesIO(normalised)) as outer:
        assert b"2024-06-15T12:30:00Z" in outer.read("docProps/core.xml")
        embedded = outer.read("ppt/embeddings/Microsoft_Excel_Sheet1.xlsx")
        with zipfile.ZipFile(io.BytesIO(embedded)) as inner:
            assert b"2024-06-15T12:30:00Z" in inner.read("docProps/core.xml")
