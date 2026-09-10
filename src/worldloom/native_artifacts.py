"""Inspect native bytes, retaining addressable evidence rather than file metadata.

DOCX page counts are explicit page boundaries, not a layout engine's pagination.
Formula strings are inspected without executing formulas or external links.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile

from .models import Model


class NativeUnit(Model):
    locator: str
    text: str


class NativeSnapshot(Model):
    format: str
    sha256: str
    units: tuple[NativeUnit, ...]
    metrics: dict[str, int]


class NativeArtifactError(ValueError):
    """The submitted bytes cannot support native inspection."""


def _package(payload: bytes, format: str) -> dict[str, bytes]:
    root = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml", "xlsx": "xl/workbook.xml"}
    if format not in root:
        raise NativeArtifactError(f"unsupported native inspection format: {format}")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise NativeArtifactError("duplicate package members")
            if root[format] not in names or "[Content_Types].xml" not in names:
                raise NativeArtifactError(f"package is not {format}")
            # Bound expanded bytes before parsers allocate objects. Large corpora
            # are multiple bounded files, not an unchecked ZIP expansion.
            if len(entries) > 100_000 or sum(e.file_size for e in entries) > 512 * 1024 * 1024:
                raise NativeArtifactError("native package exceeds inspection budget")
            for entry in entries:
                if entry.flag_bits & 1 or entry.filename.startswith("/") or ".." in entry.filename.split("/"):
                    raise NativeArtifactError("unsafe native package member")
            return {name: archive.read(name) for name in sorted(names)}
    except (BadZipFile, OSError, RuntimeError) as error:
        raise NativeArtifactError("malformed native package") from error


def package_digests(payload: bytes, format: str) -> dict[str, str]:
    """Part hashes expose exact preservation, including parts not text-extracted."""
    return {name: hashlib.sha256(value).hexdigest() for name, value in _package(payload, format).items()}


def _docx(payload: bytes, units: list[NativeUnit], metrics: dict[str, int]) -> None:
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(BytesIO(payload))
    paragraphs = document.paragraphs
    metrics["paragraphs"] = len(paragraphs)
    # Explicit page breaks are a lower bound; never use core property page
    # counts, which Office writers can leave stale after an edit.
    breaks = sum(1 for node in document.element.iter(qn("w:br")) if node.get(qn("w:type")) == "page")
    before = sum(1 for p in paragraphs if p.paragraph_format.page_break_before)
    metrics["explicit_pages"] = 1 + breaks + before
    for index, paragraph in enumerate(paragraphs, 1):
        units.append(NativeUnit(locator=f"paragraph:{index}", text=paragraph.text))
    metrics["tables"] = len(document.tables)
    for t, table in enumerate(document.tables, 1):
        for r, row in enumerate(table.rows, 1):
            for c, cell in enumerate(row.cells, 1):
                units.append(NativeUnit(locator=f"table:{t}/row:{r}/cell:{c}", text=cell.text))
    for index, section in enumerate(document.sections, 1):
        for name in ("header", "footer", "first_page_header", "first_page_footer", "even_page_header", "even_page_footer"):
            part = getattr(section, name)
            # Accessing absent header/footer parts makes python-docx create
            # parts. Their empty text is not input evidence.
            if part._has_definition:
                units.append(NativeUnit(locator=f"section:{index}/{name}", text="\n".join(p.text for p in part.paragraphs)))


def _pptx(payload: bytes, units: list[NativeUnit], metrics: dict[str, int]) -> None:
    from pptx import Presentation

    presentation = Presentation(BytesIO(payload))
    metrics["slides"] = len(presentation.slides)
    metrics.update(hidden_slides=0, speaker_notes=0, native_charts=0, tables=0)
    for index, slide in enumerate(presentation.slides, 1):
        prefix = f"slide:{index}"
        hidden = slide._element.get("show", "1") in ("0", "false")
        metrics["hidden_slides"] += int(hidden)
        units.append(NativeUnit(locator=f"{prefix}/hidden", text=str(hidden).lower()))
        texts: list[str] = []

        def visit(shapes: Any, path: str, texts: list[str]) -> None:
            for s, shape in enumerate(shapes, 1):
                position = f"{path}/shape:{s}"
                if shape.has_text_frame:
                    texts.append(shape.text)
                    units.append(NativeUnit(locator=f"{position}/text", text=shape.text))
                if shape.has_table:
                    metrics["tables"] += 1
                    for r, row in enumerate(shape.table.rows, 1):
                        for c, cell in enumerate(row.cells, 1):
                            units.append(NativeUnit(locator=f"{position}/row:{r}/cell:{c}", text=cell.text))
                if shape.has_chart:
                    metrics["native_charts"] += 1
                    chart = shape.chart
                    for series_index, series in enumerate(chart.series, 1):
                        units.append(NativeUnit(locator=f"{position}/series:{series_index}", text=f"{series.name}: " + ", ".join(str(value) for value in series.values)))
                    for plot_index, plot in enumerate(chart.plots, 1):
                        units.append(NativeUnit(locator=f"{position}/plot:{plot_index}/categories", text="\n".join(str(category.label) for category in plot.categories)))
                if hasattr(shape, "shapes"):
                    visit(shape.shapes, position, texts)

        visit(slide.shapes, prefix, texts)
        units.append(NativeUnit(locator=f"{prefix}/text", text="\n".join(texts)))
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            notes = frame.text if frame is not None else ""
            metrics["speaker_notes"] += int(bool(notes.strip()))
            units.append(NativeUnit(locator=f"{prefix}/notes", text=notes))


def _xlsx(payload: bytes, units: list[NativeUnit], metrics: dict[str, int]) -> None:
    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(payload), data_only=False, keep_links=False)
    metrics.update(sheets=len(workbook.worksheets), rows=0, columns=0, rows_per_sheet=min((sheet.max_row for sheet in workbook.worksheets), default=0), columns_per_sheet=min((sheet.max_column for sheet in workbook.worksheets), default=0), formula_cells=0, comments=0, hidden_sheets=0)
    try:
        for sheet in workbook.worksheets:
            metrics["rows"] = max(metrics["rows"], sheet.max_row)
            metrics["columns"] = max(metrics["columns"], sheet.max_column)
            metrics["hidden_sheets"] += int(sheet.sheet_state != "visible")
            prefix = f"sheet:{sheet.title}"
            units.append(NativeUnit(locator=f"{prefix}/state", text=sheet.sheet_state))
            # Sparse workbooks can have a far-away formatted cell. Iterating a
            # max_row × max_column rectangle would turn that into a denial of service.
            for cell in sorted(sheet._cells.values(), key=lambda cell: (cell.row, cell.column)):
                if cell.value is not None:
                    value = cell.value
                    if cell.data_type == "f" and not isinstance(value, str):
                        # Array formulas carry a typed value, whose default repr
                        # includes memory identity. Expose its expression or refuse.
                        value = getattr(value, "text", None)
                        if not isinstance(value, str):
                            raise NativeArtifactError("unsupported workbook formula representation")
                    units.append(NativeUnit(locator=f"{prefix}/cell:{cell.coordinate}", text=str(value)))
                    units.append(NativeUnit(locator=f"{prefix}/cell:{cell.coordinate}/type", text="s" if cell.data_type == "inlineStr" else cell.data_type))
                    metrics["formula_cells"] += int(cell.data_type == "f")
                if cell.comment:
                    metrics["comments"] += 1
                    units.append(NativeUnit(locator=f"{prefix}/cell:{cell.coordinate}/comment", text=cell.comment.text))
            for merged in sorted(str(value) for value in sheet.merged_cells.ranges):
                units.append(NativeUnit(locator=f"{prefix}/merge:{merged}", text=merged))
    finally:
        workbook.close()


def inspect_artifact(payload: bytes, format: str) -> NativeSnapshot:
    """Extract supported native structure from actual bytes, or refuse.

    Units preserve document order. SHA-256 identifies the complete source,
    including images and formatting that text extraction does not judge.
    """
    parts = _package(payload, format)
    metrics = {"file_size_bytes": len(payload), "image_bytes": sum(len(value) for name, value in parts.items() if "/media/" in name)}
    units: list[NativeUnit] = []
    try:
        {"docx": _docx, "pptx": _pptx, "xlsx": _xlsx}[format](payload, units, metrics)
    except ImportError as error:
        raise NativeArtifactError(f'native inspection requires worldloom[{format}]') from error
    except Exception as error:
        raise NativeArtifactError(f"cannot inspect {format} package: {type(error).__name__}") from error
    locators = [unit.locator for unit in units]
    if len(locators) != len(set(locators)):
        raise NativeArtifactError("ambiguous native evidence locators")
    return NativeSnapshot(format=format, sha256=hashlib.sha256(payload).hexdigest(), units=tuple(units), metrics=metrics)
