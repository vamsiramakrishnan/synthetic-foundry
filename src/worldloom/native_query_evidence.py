"""Bind hidden table provenance to authored semantics and native table labels."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .formula_semantics import rounded_expression
from .locales import Locale
from .models import (
    ArtifactIR,
    ArtifactSection,
    CanonicalFact,
    Cell,
    Column,
    FormulaKind,
    Row,
    Table,
)
from .narrative import references
from .native_corpus import NativeContent, NativeContentProvenance, _Content

if TYPE_CHECKING:
    from .world import World


class SourceEvidenceIndex:
    """Unambiguous canonical truth and public, grounded authored sections.

    Native files may enter through the SDK without our renderer. Their byte
    checksums cannot certify privacy or excuse an invalid source snapshot.
    Validate each selected section once, before binding any of its evidence.
    """

    def __init__(self, world: World):
        self.facts: dict[str, CanonicalFact] = {}
        self.artifacts: dict[str, ArtifactIR] = {}
        self._validated: dict[tuple[str, int], ArtifactSection] = {}
        self._closures: dict[tuple[str, ...], tuple[str, ...]] = {}
        for fact in world.facts:
            if fact.id in self.facts:
                raise ValueError(f"duplicate canonical fact identity: {fact.id}")
            self.facts[fact.id] = fact
        for ir in world.artifact_irs:
            if ir.id in self.artifacts:
                raise ValueError(f"duplicate authored artifact identity: {ir.id}")
            self.artifacts[ir.id] = ir

    def fact_closure(self, fact_ids: Sequence[str]) -> tuple[str, ...]:
        """Facts and their canonical derived/superseded ancestors, never aliases.

        Unknown or cyclic reachable ancestry cannot establish independent
        evidence. Iterative traversal also supports long revision chains.
        """
        roots = tuple(sorted(set(fact_ids)))
        if roots in self._closures:
            return self._closures[roots]
        closed: set[str] = set()
        active: set[str] = set()
        for root in roots:
            stack = [(root, False)]
            while stack:
                identifier, finish = stack.pop()
                if finish:
                    active.remove(identifier)
                    closed.add(identifier)
                    continue
                if identifier in closed:
                    continue
                if identifier in active:
                    raise ValueError(f"canonical fact ancestry cycle: {identifier}")
                fact = self.facts.get(identifier)
                if fact is None:
                    raise ValueError(f"canonical fact ancestry names an unknown fact: {identifier}")
                active.add(identifier)
                stack.append((identifier, True))
                parents = set(fact.derived_from)
                if fact.supersedes is not None:
                    parents.add(fact.supersedes)
                stack.extend((parent, False) for parent in sorted(parents, reverse=True))
        result = tuple(sorted(closed))
        self._closures[roots] = result
        return result

    def validate_evidence(self, entries: Sequence[NativeContentProvenance]) -> None:
        # Removing every binding must not make otherwise unverifiable bytes
        # eligible for the direct bridge with an empty canonical lineage.
        if not any(entry.fact_ids for entry in entries):
            raise ValueError("native workload source has no canonical evidence")
        for entry in entries:
            self.section(entry.source_artifact_id, entry.section_index)

    def section(self, source_artifact_id: str, section_index: int) -> ArtifactSection:
        ir = self.artifacts.get(source_artifact_id)
        if ir is None or not 0 <= section_index < len(ir.sections):
            raise ValueError(f"native workload provenance names an unknown authored section: {source_artifact_id}:{section_index}")
        section = ir.sections[section_index]
        key = source_artifact_id, section_index
        if self._validated.get(key) is section:
            return section
        if section.hidden:
            raise ValueError(f"private authored section: {source_artifact_id}:{section_index}")
        body = section.body or ""
        authored_ids = set(references.referenced(body))
        carried = authored_ids | set(section.fact_ids)
        if section.table is not None:
            carried.update(cell.fact_id for row in section.table.rows for cell in row.cells.values()
                           if cell.fact_id is not None)
        unknown = sorted((carried - self.facts.keys()) | set(references.unresolved(body, self.facts)))
        if unknown:
            raise ValueError(f"native source section cites unknown canonical facts: {unknown}")
        if references.bare_numbers(body):
            raise ValueError("native source prose must reference canonical figures")
        if body.strip() and not authored_ids:
            raise ValueError("native source evidence must occur in authored prose")
        if not authored_ids and section.table is None:
            raise ValueError("native source section has no canonical evidence")
        self._validated[key] = section
        return section


@dataclass(frozen=True)
class TableBinding:
    selector: str
    measure: str
    subject: str
    fact: CanonicalFact | None
    formula: bool
    authored_operation: FormulaKind | None = None


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
        self.section_facts: dict[tuple[str, int], frozenset[str]] = {}
        for entry in entries:
            source = irs.get(entry.source_artifact_id)
            if source is None or not 0 <= entry.section_index < len(source.sections):
                raise ValueError("native table provenance names an unknown authored section")
            section = source.sections[entry.section_index]
            if section.table is None:
                self.section_facts[entry.source_artifact_id, entry.section_index] = frozenset(
                    references.referenced(section.body or ""))
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
            self.section_facts[source_id, position] = frozenset(references.referenced(section.body or "")) | frozenset(
                cell.fact_id for row in table.rows for cell in row.cells.values() if cell.fact_id is not None)
            self.columns.update({(source_id, table.key, column.key): column for column in table.columns})
            for row in table.rows:
                self.rows[source_id, table.key, row.key] = row
                for column_key, cell in row.cells.items():
                    self.cells[source_id, table.key, row.key, column_key] = table, cell
        # SDK intake can supply native bytes and IR without using our renderer.
        # Reuse its canonical arithmetic gate once per selected graph: matching
        # checksums and authored literals cannot make false derived values true.
        from .native_business import _table_graph
        graph = _table_graph(world, tuple(contents))
        self.units = graph.units
        for address, owner in graph.owners.items():
            section_key = owner.source.source_artifact_id, owner.source.section_index
            self.section_facts[section_key] |= frozenset(graph.facts[address])

    def heading_versions(self, heading: str, source_artifact_id: str, section_index: int,
                         facts: Mapping[str, CanonicalFact]) -> frozenset[str]:
        """Only source labels and context derived from complete section facts.

        A cell's own period cannot label a mixed-period table or prose backed by
        it. Reuse the renderer's full body/table dependency union. If a table
        has no served bindings, its dependency graph cannot justify context.
        """
        from .native_business import contextual_heading
        ids = self.section_facts.get((source_artifact_id, section_index))
        return frozenset((heading,)) if ids is None else frozenset((heading, contextual_heading(heading, ids, facts)))

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
        expression = "SUM(" + ",".join(values) + ")"
    elif cell.formula is FormulaKind.DIFFERENCE and len(values) == 2:
        expression = f"{values[0]}-{values[1]}"
    elif cell.formula is FormulaKind.RATIO_PCT and len(values) == 2:
        expression = f"IF({values[1]}=0,0,{values[0]}/{values[1]}*100)"
    elif cell.formula is FormulaKind.REFERENCE and len(values) == 1:
        expression = values[0]
    else:
        raise ValueError("native workbook formula has unsupported operands")
    return "=" + rounded_expression(expression, cell.formula_decimal_places)


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
    descriptors = {"row_label": row.label, "column_label": column.label}
    if any(units.get(metadata.get(name, "")) != value for name, value in descriptors.items()):
        raise ValueError("native table selector labels disagree with authored business descriptors")
    observed_title = units.get(metadata.get("table_title", ""), "")
    if observed_title not in index.heading_versions(table.title, ir.id, entry.section_index, facts):
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
    return TableBinding(selector=f"the value in table {observed_title!r}, row {row.label!r}, column {column.label!r}",
        measure=column.label, subject=row.label, fact=fact, formula=formula, authored_operation=cell.formula)
