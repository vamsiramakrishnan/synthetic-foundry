"""Bind hidden table provenance to authored semantics and native table labels."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .locales import Locale
from .models import ArtifactIR, CanonicalFact, Cell, Column, FormulaKind, Row, Table
from .native_corpus import NativeContent, NativeContentProvenance, _Content

if TYPE_CHECKING:
    from .world import World


@dataclass(frozen=True)
class TableBinding:
    selector: str
    measure: str
    subject: str
    fact: CanonicalFact | None
    formula: bool


def _operands(table_key: str, row_key: str, column_key: str, cell: Cell) -> list[tuple[str, str, str]]:
    if cell.formula in (FormulaKind.DIFFERENCE, FormulaKind.RATIO_PCT):
        return [(table_key, row_key, operand) for operand in cell.operands]
    targets = []
    for operand in cell.operands:
        parts = operand.split(":")
        if len(parts) == 3:
            targets.append((parts[0], parts[1], parts[2]))
        elif len(parts) == 1:
            targets.append((table_key, operand, column_key))
        else:
            raise ValueError("native table formula has malformed operands")
    return targets


class TableEvidenceIndex:
    """One file's bindings and memoized IR dependency closure."""

    def __init__(self, entries: Sequence[NativeContentProvenance], irs: Mapping[str, ArtifactIR], *, world: World):
        self.bound: dict[tuple[str, str, str, str], str] = {}
        self.cells: dict[tuple[str, str, str, str], tuple[Table, Cell]] = {}
        self.rows: dict[tuple[str, str, str], Row] = {}
        self.columns: dict[tuple[str, str, str], Column] = {}
        self.closed: dict[tuple[str, str, str, str], frozenset[str]] = {}
        selected = set()
        for entry in entries:
            if entry.table_key is None or entry.row_key is None or entry.column_key is None:
                continue
            key = (entry.source_artifact_id, entry.table_key, entry.row_key, entry.column_key)
            if key in self.bound:
                raise ValueError("native table provenance repeats an authored cell")
            self.bound[key] = entry.locator
            selected.add(key[:2])
        contents = []
        for source_id, table_key in sorted(selected):
            ir = irs.get(source_id)
            sections = [] if ir is None else [(position, section) for position, section in enumerate(ir.sections)
                if section.table is not None and section.table.key == table_key]
            if len(sections) != 1:
                raise ValueError("native table provenance names an ambiguous or missing table")
            position, section = sections[0]
            table = section.table
            assert table is not None
            contents.append(_Content(NativeContent(source_artifact_id=source_id, section_index=position),
                section.heading, section.body or "", (), table))
            self.columns.update({(source_id, table.key, column.key): column for column in table.columns})
            for row in table.rows:
                self.rows[source_id, table.key, row.key] = row
                for column_key, cell in row.cells.items():
                    self.cells[source_id, table.key, row.key, column_key] = table, cell
        # SDK intake can supply native bytes and IR without using our renderer.
        # Reuse its canonical arithmetic gate once per selected graph: matching
        # checksums and authored literals cannot make false derived values true.
        from .native_business import _table_graph
        self.units = _table_graph(world, tuple(contents)).units

    def closure(self, key: tuple[str, str, str, str], visiting: frozenset[tuple[str, str, str, str]] = frozenset()) -> frozenset[str]:
        if key in self.closed:
            return self.closed[key]
        if key in visiting:
            raise ValueError("native table formula has cyclic provenance")
        source_id, table_key, row_key, column_key = key
        if key not in self.cells:
            raise ValueError("native table formula names an unknown dependency")
        _, cell = self.cells[key]
        found = frozenset((cell.fact_id,)) if cell.fact_id is not None else frozenset()
        for operand in _operands(table_key, row_key, column_key, cell):
            found |= self.closure((source_id, *operand), visiting | {key})
        self.closed[key] = found
        return found


def _expression(cell: Cell, dependencies: tuple[str, ...]) -> str:
    values = []
    for locator in dependencies:
        position = re.fullmatch(r"sheet:([^/]+)/cell:([A-Z]+[1-9][0-9]*)", locator)
        if position is None:
            raise ValueError("native workbook formula has an unsupported dependency locator")
        values.append("'" + position[1].replace("'", "''") + "'!" + position[2])
    if cell.formula is FormulaKind.SUM:
        return "=SUM(" + ",".join(values) + ")"
    if cell.formula is FormulaKind.DIFFERENCE and len(values) == 2:
        return f"={values[0]}-{values[1]}"
    if cell.formula is FormulaKind.RATIO_PCT and len(values) == 2:
        return f"=IF({values[1]}=0,0,{values[0]}/{values[1]}*100)"
    if cell.formula is FormulaKind.REFERENCE and len(values) == 1:
        return "=" + values[0]
    raise ValueError("native workbook formula has unsupported operands")


def validate_table_binding(
    entry: NativeContentProvenance, ir: ArtifactIR, index: TableEvidenceIndex,
    units: Mapping[str, str], facts: Mapping[str, CanonicalFact], *, format: str, locale: Locale,
) -> TableBinding:
    """Validate values, dependency closure, native formula and local selectors.

    The manifest cannot rename another valid source cell while keeping its
    checksum. A native row/column descriptor must describe this actual cell.
    """
    if entry.table_key is None or entry.row_key is None or entry.column_key is None:
        raise ValueError("native table provenance requires table, row and column bindings")
    address = (ir.id, entry.table_key, entry.row_key, entry.column_key)
    found = index.cells.get(address)
    if found is None:
        raise ValueError("native table provenance names an unknown row or column")
    table, cell = found
    if ir.sections[entry.section_index].table is not table:
        raise ValueError("native table provenance disagrees with its authored section")
    row = index.rows.get((ir.id, table.key, entry.row_key))
    column = index.columns.get((ir.id, table.key, entry.column_key))
    if row is None or column is None:
        raise ValueError("native table provenance names an unknown row or column")
    key = (table.key, row.key, column.key)
    expected_ids = index.closure(address)
    if expected_ids != frozenset(entry.fact_ids) or expected_ids - facts.keys():
        raise ValueError("native table provenance disagrees with its canonical dependency closure")
    if entry.value != cell.value:
        raise ValueError("native table value disagrees with its authored cell")
    if entry.unit != index.units[address]:
        raise ValueError("native table unit disagrees with its canonical computation")
    fact = facts.get(cell.fact_id or "")
    if fact is not None:
        if fact.value is None:
            if cell.value != fact.text_value or entry.unit is not None:
                raise ValueError("native table text disagrees with its canonical fact")
        elif (not isinstance(cell.value, (int, float)) or Decimal(str(cell.value)) != Decimal(str(fact.value.amount))
              or entry.unit != fact.value.unit):
            raise ValueError("native table number disagrees with its canonical fact")
    dependencies = tuple(index.bound.get((ir.id, *operand), "") for operand in _operands(*key, cell))
    if any(not locator or locator not in units for locator in dependencies) or dependencies != entry.dependency_locators:
        raise ValueError("native table formula dependency locators disagree with its authored operands")
    formula = cell.formula is not None and format == "xlsx"
    if formula:
        if entry.kind != "formula":
            raise ValueError("native table formula provenance is not declared as a formula")
        expected = _expression(cell, dependencies)
    else:
        if entry.kind != ("formula" if cell.formula is not None else "value"):
            raise ValueError("native literal table provenance is not declared as a value")
        expected = "" if cell.value is None else str(cell.value)
        # OOXML writers spell integral numeric values without the float's '.0'.
        if isinstance(cell.value, (int, float)):
            if Decimal(units[entry.locator]) == Decimal(str(cell.value)):
                expected = units[entry.locator]
    if units[entry.locator] != expected:
        raise ValueError("native table bytes disagree with the authored value or formula")
    metadata = entry.metadata_locators
    descriptors = {"table_title": table.title, "row_label": row.label, "column_label": column.label}
    if any(units.get(metadata.get(name, "")) != value for name, value in descriptors.items()):
        raise ValueError("native table selector labels disagree with authored business descriptors")
    position = re.fullmatch(r"(.*)/(?:cell:([A-Z]+)([1-9][0-9]*)|row:([1-9][0-9]*)/cell:([1-9][0-9]*))", entry.locator)
    if position is None:
        raise ValueError("native table selector has an unsupported native locator")
    prefix, letters, workbook_row, native_row, native_column = position.groups()
    if workbook_row is not None:
        row_locator = f"{prefix}/cell:A{workbook_row}"
        column_locator = f"{prefix}/cell:{letters}1"
        title_locator = f"{prefix}/cell:A1"
    else:
        row_locator = f"{prefix}/row:{native_row}/cell:1"
        column_locator = f"{prefix}/row:1/cell:{native_column}"
        title_locator = f"{prefix}/row:1/cell:1"
    if metadata["row_label"] != row_locator or metadata["column_label"] != column_locator \
            or metadata["table_title"] != title_locator:
        raise ValueError("native table selector is not bound to its actual row and column")
    return TableBinding(selector=f"the value in table {table.title!r}, row {row.label!r}, column {column.label!r}",
        measure=column.label, subject=row.label, fact=fact, formula=formula)
