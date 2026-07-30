"""The XLSX renderer.

First of the renderers, because the workbook is a source artifact rather than a
projection of one, and because it is the only format where numerical coherence is
externally checkable: open the file, and the sheet recomputes its own totals.

**Formulas remain formulas.** A total is written as ``=SUM(C4:C6)``, not as the
number that sum happens to equal. A variance is ``=D4-C4``. A margin is
``=F4/E4``. The literal value is still in the IR and is what a formula-free format
emits, but nothing here pastes a computed value into a cell that should compute.

That is the difference between a workbook and a screenshot of one. If a fact
changes and a total does not, the sheet shows it.
"""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING

from ..models import ArtifactIR, FormulaKind, Table
from . import Rendered, RenderError

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World

#: Artifact types this renderer handles. Everything else belongs to another format.
HANDLES = frozenset({"finance_workbook"})

_HEADER_ROW = 3
"""Row 1 is the title, row 2 the subtitle, row 3 the column headers."""


def _require_openpyxl():  # type: ignore[no-untyped-def]
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise RenderError(
            "the xlsx format needs openpyxl. Install it with: pip install 'worldloom[xlsx]'"
        ) from exc
    return openpyxl


def _column_letter(index: int) -> str:
    """1-based column index to its spreadsheet letter."""
    from openpyxl.utils import get_column_letter

    return get_column_letter(index)


class _Layout:
    """Where every row and column of every table landed on the sheet.

    Built once per workbook rather than searched per cell. A store-level sheet has
    thousands of rows and three formula columns; resolving each operand by
    scanning the row list is quadratic and turns a one-second render into a
    one-minute one.
    """

    __slots__ = ("rows", "columns", "first_data_row", "sheet")

    def __init__(self, tables, sheet_of: dict[str, str], rows_of: dict[str, int]) -> None:
        self.rows = {
            table.key: {row.key: index for index, row in enumerate(table.rows)}
            for table in tables
        }
        self.columns = {
            table.key: {column.key: index for index, column in enumerate(table.columns)}
            for table in tables
        }
        self.first_data_row = rows_of
        self.sheet = sheet_of

    def cell(self, table_key: str, row_key: str, column_key: str) -> tuple[int, str] | None:
        """``(row index, A1 address)``, or ``None`` if either key is unknown."""
        row_index = self.rows.get(table_key, {}).get(row_key)
        column_index = self.columns.get(table_key, {}).get(column_key)
        if row_index is None or column_index is None:
            return None
        # +2 for the label column that precedes the data columns.
        return row_index, f"{_column_letter(column_index + 2)}{self.first_data_row[table_key] + row_index}"


def _operand(table_key: str, operand: str, column_key: str) -> tuple[str, str, str]:
    """Split a SUM operand into ``(table, row, column)``.

    A bare operand names a row in the current table and the column being
    computed. A ``table:row:column`` operand names a cell anywhere in the
    workbook, which is how the reconciliation sheet sums the P&L's own rows
    instead of restating them.
    """
    parts = operand.split(":")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return table_key, operand, column_key


def _formula(
    ir: ArtifactIR,
    table: Table,
    row_key: str,
    column_key: str,
    cell,  # type: ignore[no-untyped-def]
    *,
    layout: _Layout,
) -> str | None:
    """Translate a declared computation into Excel syntax.

    The IR says *what* is computed; this decides how to spell it. Nothing here
    invents a computation the IR did not declare.
    """
    if cell.formula is None:
        return None

    def here(target_column: str, target_row: str | None = None) -> str | None:
        found = layout.cell(table.key, target_row or row_key, target_column)
        return found[1] if found else None

    if cell.formula is FormulaKind.SUM:
        resolved = []
        for operand in cell.operands:
            target_table, target_row, target_column = _operand(table.key, operand, column_key)
            found = layout.cell(target_table, target_row, target_column)
            if found is not None:
                resolved.append((target_table, target_column, found[0], found[1]))
        if not resolved:
            return None

        def qualify(entry) -> str:  # type: ignore[no-untyped-def]
            target_table, _, _, address = entry
            if target_table == table.key:
                return address
            return f"'{layout.sheet[target_table]}'!{address}"

        # A range only when the operands really are consecutive rows of one
        # column. Collapsing a scattered set into `first:last` would silently
        # include the rows in between — with subtotal rows on the sheet, that is
        # every category counted twice.
        contiguous = (
            len(resolved) > 1
            and len({(t, c) for t, c, _, _ in resolved}) == 1
            and all(b[2] == a[2] + 1 for a, b in zip(resolved, resolved[1:]))
        )
        if contiguous:
            target_table = resolved[0][0]
            first, last = resolved[0][3], resolved[-1][3]
            if target_table == table.key:
                return f"=SUM({first}:{last})"
            # The sheet is named once for the range, not once per endpoint: Excel
            # rejects `'Sheet'!C4:'Sheet'!C6`.
            return f"=SUM('{layout.sheet[target_table]}'!{first}:{last})"
        return f"=SUM({','.join(qualify(entry) for entry in resolved)})"

    if cell.formula is FormulaKind.DIFFERENCE and len(cell.operands) == 2:
        left, right = here(cell.operands[0]), here(cell.operands[1])
        return f"={left}-{right}" if left and right else None

    if cell.formula is FormulaKind.RATIO_PCT and len(cell.operands) == 2:
        numerator, denominator = here(cell.operands[0]), here(cell.operands[1])
        if not (numerator and denominator):
            return None
        # Guarded, because a zero denominator in a spreadsheet is a #DIV/0! a
        # reader has to interpret rather than a number they can read.
        return f"=IF({denominator}=0,0,{numerator}/{denominator})"

    if cell.formula is FormulaKind.REFERENCE and cell.operands:
        target_table, target_row, target_column = _operand(table.key, cell.operands[0], column_key)
        found = layout.cell(target_table, target_row, target_column)
        if found is None or target_table not in layout.sheet:
            return None
        return f"='{layout.sheet[target_table]}'!{found[1]}"

    return None


def render(ir: ArtifactIR) -> bytes:
    """Render one workbook IR to XLSX bytes."""
    openpyxl = _require_openpyxl()
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.workbook.defined_name import DefinedName
    from openpyxl.utils import quote_sheetname

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)

    sections = [s for s in ir.sections if s.table is not None]
    sheet_of = {s.table.key: s.table.title[:31] for s in sections}
    rows_of = {s.table.key: _HEADER_ROW + 1 for s in sections}
    layout = _Layout([s.table for s in sections], sheet_of, rows_of)

    bold = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="EEEEEE")

    for section in sections:
        table = section.table
        sheet = workbook.create_sheet(title=sheet_of[table.key])
        sheet.sheet_state = "hidden" if section.hidden else "visible"

        sheet.cell(row=1, column=1, value=ir.title).font = Font(bold=True, size=13)
        if ir.subtitle:
            sheet.cell(row=2, column=1, value=ir.subtitle).font = Font(italic=True, color="666666")

        sheet.cell(row=_HEADER_ROW, column=1, value=table.title).font = bold
        sheet.cell(row=_HEADER_ROW, column=1).fill = header_fill
        for index, column in enumerate(table.columns, start=2):
            header = sheet.cell(row=_HEADER_ROW, column=index, value=column.label)
            header.font = bold
            header.fill = header_fill
            header.alignment = Alignment(horizontal="right")

        for row_offset, row in enumerate(table.rows):
            excel_row = rows_of[table.key] + row_offset
            label = sheet.cell(row=excel_row, column=1, value=row.label)
            if row.emphasis:
                label.font = bold

            for column_index, column in enumerate(table.columns, start=2):
                cell = row.cells.get(column.key)
                target = sheet.cell(row=excel_row, column=column_index)
                if cell is None:
                    continue

                formula = _formula(ir, table, row.key, column.key, cell, layout=layout)

                if formula is not None:
                    target.value = formula
                else:
                    target.value = cell.value

                if column.number_format:
                    # A percentage fact is stored as 24.94, and Excel's percent
                    # format multiplies by 100 — so scale to a fraction rather
                    # than showing 2494%.
                    if column.number_format.endswith("%") and isinstance(cell.value, (int, float)):
                        if formula is not None:
                            pass  # a ratio formula already yields a fraction
                        else:
                            target.value = cell.value / 100
                    target.number_format = column.number_format
                if row.emphasis:
                    target.font = bold

        widths = [max(12, len(table.title))] + [max(12, len(c.label) + 2) for c in table.columns]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[_column_letter(index)].width = width

        if table.note:
            note_row = rows_of[table.key] + len(table.rows) + 1
            sheet.cell(row=note_row, column=1, value=table.note).font = Font(
                italic=True, color="666666"
            )

        sheet.freeze_panes = sheet.cell(row=rows_of[table.key], column=2)

    # Named ranges, so a consumer can address the numbers that matter without
    # depending on where they happen to sit.
    pnl = next((t for t in ir.tables() if t.key == "pnl"), None)
    if pnl is not None:
        group = next((row for row in reversed(pnl.rows) if row.emphasis), None)
        if group is not None:
            sheet_name = sheet_of["pnl"]
            for column_key, name in (
                ("revenue_actual", "GroupRevenueActual"),
                ("revenue_budget", "GroupRevenueBudget"),
                ("revenue_variance", "GroupRevenueVariance"),
                ("gp_actual", "GroupGrossProfitActual"),
                ("gp_variance", "GroupGrossProfitVariance"),
            ):
                found = layout.cell("pnl", group.key, column_key)
                address = found[1] if found else None
                if address:
                    workbook.defined_names[name] = DefinedName(
                        name, attr_text=f"{quote_sheetname(sheet_name)}!${address[0]}${address[1:]}"
                    )

    workbook.properties.title = ir.title
    workbook.properties.subject = ir.subtitle or ""
    workbook.properties.creator = "Worldloom"
    workbook.properties.description = ir.metadata.get(
        "note", "Synthetic corpus generated by Worldloom."
    )
    workbook.properties.keywords = "synthetic,worldloom,seed=" + ir.metadata.get("worldloom_seed", "")

    # Document timestamps come from the world, never from the clock. openpyxl
    # defaults these to `datetime.now()`, which would put the moment of rendering
    # inside the file and break byte-identical regeneration.
    stamp = ir.metadata.get("worldloom_created")
    if stamp:
        moment = datetime.fromisoformat(stamp).replace(tzinfo=None)
        workbook.properties.created = moment
        workbook.properties.modified = moment

    buffer = BytesIO()
    workbook.save(buffer)
    return _normalise(buffer.getvalue(), created=stamp)


#: Fixed timestamp for every archive entry. The earliest a zip can represent, so
#: it reads as deliberately unset rather than as a plausible date.
_EPOCH = (1980, 1, 1, 0, 0, 0)

_MODIFIED = re.compile(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)")


def _normalise(payload: bytes, *, created: str | None = None) -> bytes:
    """Strip the wall clock out of a finished workbook.

    Two clocks leak into an XLSX, and both break byte-identical regeneration:

    - **Zip entry timestamps.** A zip records a modification time per entry, filled
      from the clock at save. Two renders of the same workbook a second apart
      therefore differ in bytes while being identical in content.
    - **``dcterms:modified``.** openpyxl overwrites this with ``now()`` inside
      ``save``, *after* any value set on ``workbook.properties``, so it cannot be
      fixed before the fact.

    Both are corrected here rather than by patching the library, so the result
    holds for whatever openpyxl version is installed. The XML substitution is
    deliberately narrow — one element whose content is a timestamp — which is why
    it does not warrant an XML parser.

    Discovered by CI: two runs of the replay check landed either side of a second
    boundary and the workbooks differed. Locally they had always shared a second,
    so the defect passed unnoticed.
    """
    from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

    source = BytesIO(payload)
    target = BytesIO()
    with ZipFile(source) as original, ZipFile(target, "w", ZIP_DEFLATED) as rebuilt:
        for info in original.infolist():
            content = original.read(info.filename)
            if created and info.filename == "docProps/core.xml":
                content = _MODIFIED.sub(
                    rb"\g<1>" + created.replace("+00:00", "Z").encode() + rb"\g<2>", content
                )
            fixed = ZipInfo(filename=info.filename, date_time=_EPOCH)
            fixed.compress_type = info.compress_type
            fixed.external_attr = info.external_attr
            fixed.internal_attr = info.internal_attr
            fixed.create_system = 3  # Unix, so the host OS does not leak in either
            rebuilt.writestr(fixed, content)
    return target.getvalue()


def render_all(world: World) -> list[Rendered]:
    """Render every workbook in *world*."""
    out: list[Rendered] = []
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        if intent.artifact_type not in HANDLES:
            continue
        out.append(
            Rendered(
                artifact_id=ir.id,
                path=f"artifacts/{ir.id.lower()}-month-end-model.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                payload=render(ir),
            )
        )
    return out
