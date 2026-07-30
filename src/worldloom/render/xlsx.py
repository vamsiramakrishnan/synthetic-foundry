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


def _address(table: Table, row_key: str, column_key: str, *, first_data_row: int) -> str | None:
    """The A1 address of one cell in a rendered table."""
    row_index = next((i for i, row in enumerate(table.rows) if row.key == row_key), None)
    column_index = next((i for i, col in enumerate(table.columns) if col.key == column_key), None)
    if row_index is None or column_index is None:
        return None
    # +2 for the label column that precedes the data columns.
    return f"{_column_letter(column_index + 2)}{first_data_row + row_index}"


def _formula(
    ir: ArtifactIR,
    table: Table,
    row_key: str,
    column_key: str,
    cell,  # type: ignore[no-untyped-def]
    *,
    first_data_row: int,
    sheet_of: dict[str, str],
    rows_of: dict[str, int],
) -> str | None:
    """Translate a declared computation into Excel syntax.

    The IR says *what* is computed; this decides how to spell it. Nothing here
    invents a computation the IR did not declare.
    """
    if cell.formula is None:
        return None

    if cell.formula is FormulaKind.SUM:
        addresses = [
            _address(table, operand, column_key, first_data_row=first_data_row)
            for operand in cell.operands
        ]
        present = [a for a in addresses if a]
        if not present:
            return None
        # Contiguous operands become a range; scattered ones stay a list.
        if len(present) > 1 and len(present) == len(cell.operands):
            return f"=SUM({present[0]}:{present[-1]})"
        return f"=SUM({','.join(present)})"

    if cell.formula is FormulaKind.DIFFERENCE and len(cell.operands) == 2:
        left = _address(table, row_key, cell.operands[0], first_data_row=first_data_row)
        right = _address(table, row_key, cell.operands[1], first_data_row=first_data_row)
        return f"={left}-{right}" if left and right else None

    if cell.formula is FormulaKind.RATIO_PCT and len(cell.operands) == 2:
        numerator = _address(table, row_key, cell.operands[0], first_data_row=first_data_row)
        denominator = _address(table, row_key, cell.operands[1], first_data_row=first_data_row)
        if not (numerator and denominator):
            return None
        # Guarded, because a zero denominator in a spreadsheet is a #DIV/0! a
        # reader has to interpret rather than a number they can read.
        return f"=IF({denominator}=0,0,{numerator}/{denominator})"

    if cell.formula is FormulaKind.REFERENCE and cell.operands:
        target_table, _, rest = cell.operands[0].partition(":")
        target_row, _, target_column = rest.partition(":")
        sheet = sheet_of.get(target_table)
        source = next((t for t in ir.tables() if t.key == target_table), None)
        if sheet is None or source is None:
            return None
        address = _address(source, target_row, target_column, first_data_row=rows_of[target_table])
        return f"='{sheet}'!{address}" if address else None

    return None


def _reconciliation_formula(
    ir: ArtifactIR,
    table: Table,
    row_key: str,
    column_key: str,
    *,
    first_data_row: int,
    sheet_of: dict[str, str],
    rows_of: dict[str, int],
) -> str | None:
    """The reconciliation sheet's two computed columns.

    ``summed`` sums the unit rows on the P&L sheet. ``difference`` subtracts the
    ledger's stated total from that sum. The stated total is a literal, so this
    compares the workbook against the corpus — subtracting the P&L's own group
    cell would be comparing ``=SUM(units)`` with itself and could never fail.
    """
    pnl = next((t for t in ir.tables() if t.key == "pnl"), None)
    sheet = sheet_of.get("pnl")
    if pnl is None or sheet is None:
        return None

    source_column = {
        "revenue_units_to_group": "revenue_actual",
        "gp_units_to_group": "gp_actual",
    }.get(row_key)
    if source_column is None:
        return None

    if column_key == "summed":
        unit_rows = [row for row in pnl.rows if not row.emphasis]
        if not unit_rows:
            return None
        first = _address(pnl, unit_rows[0].key, source_column, first_data_row=rows_of["pnl"])
        last = _address(pnl, unit_rows[-1].key, source_column, first_data_row=rows_of["pnl"])
        if not (first and last):
            return None
        # The sheet is named once for the range, not once per endpoint: Excel
        # rejects `'Sheet'!C4:'Sheet'!C6`.
        return f"=SUM('{sheet}'!{first}:{last})"

    if column_key == "difference":
        left = _address(table, row_key, "summed", first_data_row=first_data_row)
        right = _address(table, row_key, "stated", first_data_row=first_data_row)
        return f"={left}-{right}" if left and right else None

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

                if table.key == "reconciliation":
                    formula = _reconciliation_formula(
                        ir, table, row.key, column.key,
                        first_data_row=rows_of[table.key], sheet_of=sheet_of, rows_of=rows_of,
                    )
                else:
                    formula = _formula(
                        ir, table, row.key, column.key, cell,
                        first_data_row=rows_of[table.key], sheet_of=sheet_of, rows_of=rows_of,
                    )

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
        group = next((row for row in pnl.rows if row.emphasis), None)
        if group is not None:
            sheet_name = sheet_of["pnl"]
            for column_key, name in (
                ("revenue_actual", "GroupRevenueActual"),
                ("revenue_budget", "GroupRevenueBudget"),
                ("revenue_variance", "GroupRevenueVariance"),
                ("gp_actual", "GroupGrossProfitActual"),
                ("gp_variance", "GroupGrossProfitVariance"),
            ):
                address = _address(pnl, group.key, column_key, first_data_row=rows_of["pnl"])
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

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


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
