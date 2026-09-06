"""Mechanical spreadsheet errors, threaded from the plan onto the rendered sheet.

Every deliberate imperfection this corpus had was *editorial* — a page nobody
updated, a quotation that went stale, an author who left. Real workbooks fail
another way entirely: somebody types a number over a formula and the cell stops
being derived, or a SUM range stops one row short of the rows it claims to
total. Those are errors of the *sheet*, not of the sentence, and until now the
engine could not commit one on purpose: every cell it renders is either a
ledger figure or a formula over ledger figures, by construction.

This module is the thread between the plan and the page. The plan half lives in
``generators.distractors`` (the messiness pass mints the ``IntentionalError``
records, seeded from the world); this half makes each record true of a rendered
file. It happens on a **working copy** of the month-end model — a new
``workbook_copy`` intent the messiness pass mints, ``derived_from`` the real
workbook — rather than on the system of record itself, for two reasons that are
one reason. The month-end model is the document every other artifact reconciles
against, and its compiler is registered once: ``documents.
register_artifact_types`` refuses a second registration of an existing type
*because* two modules disagreeing about what a type compiles to would make the
corpus depend on import order. A copy with a paste-over in it is also the
realistic shape — the hand-maintained "(working copy)" beside the real model is
where these errors live in real estates, and the real model staying right is
what makes the disagreement discoverable rather than merely present.

The corruption reaches the file through the IR and only the IR. A
``HARDCODED_VALUE`` cell has its declared formula removed and the wrong literal
put in its ``value``, so ``render.xlsx`` — unchanged — emits a typed-in number
where every sibling row carries ``=D4-C4``. A ``SHORT_RANGE`` cell keeps its
``FormulaKind.SUM`` and loses its last operand, so the same renderer's
contiguity logic emits ``=SUM(C4:C6)`` where the rows run to 7. Nothing here
touches a renderer, and a formula-free format (Markdown) shows the same wrong
literal the formula computes to, so the copy agrees with itself across formats
in the corrupted cell.

What keeps this the corpus's kind of error rather than a defect: every figure
involved is the ledger's own. The hardcoded number is a neighbouring row's
reading (a paste-down), the short total is the sum of the rows the range still
covers, and the record names the canonical fact the cell disagrees with —
``validate.intentional`` refuses a label the compiled sheet does not
substantiate, in exactly the recorded way.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from .. import documents
from ..models import (
    ArtifactIR,
    Authority,
    Cell,
    ErrorType,
    FormulaKind,
    IntentionalError,
    Lifecycle,
    Row,
    Table,
)
from ..render import xlsx as _xlsx

if TYPE_CHECKING:  # pragma: no cover
    from ..models import ArtifactIntent, CanonicalFact
    from ..world import World

#: The artifact type the messiness pass mints for a corrupted copy. Registered
#: below with its own compiler — the seam ``banking_documents`` uses for
#: ``capital_return`` — so a corpus carrying one compiles the same way in every
#: process that imports this package.
WORKBOOK_COPY = "workbook_copy"

#: The error kinds this module makes true of a page. A frozenset both the
#: planner and the validator read, so "which kinds are mechanical" has one
#: answer.
MECHANICAL_KINDS = frozenset({ErrorType.HARDCODED_VALUE, ErrorType.SHORT_RANGE})

#: Artifact types whose compiled IR this module knows how to corrupt. Only the
#: retail month-end model today: the corruption targets the P&L's derived and
#: summed cells, and banking's return and insurance's triangle are built by
#: their own compilers with shapes this module has never been pointed at. A
#: budget on a world with none of these honestly plans zero — the same
#: "budget, not quota" contract as every other messiness kind.
CORRUPTIBLE = frozenset({"finance_workbook"})

#: Written after the model it copies. The workbook's own lag is 50 minutes;
#: anything longer keeps ``supersession.derives_from_later_artifact`` quiet for
#: the structural reason (the copy postdates its parent) rather than by luck.
#: Kept under the day-and-fifteen-hours ceiling ``documents._STANDING``'s
#: comment establishes, so a timeline's departures cannot land an author's exit
#: before their own copy's date.
COPY_LAG = timedelta(hours=26)

#: Comparison slack for readings that round-trip through text and float sums.
#: Matches the tolerance the render tests' formula evaluator uses.
_TOLERANCE = 0.01


def reading(amount: float) -> str:
    """A bare numeric reading, in the form ``validate._quantity_matches`` parses.

    Same spelling rule as ``distractors._reading`` and for its recorded reason:
    ``repr`` rather than a formatted figure, because ``f"{x:g}"`` rounds to six
    significant digits and a seven-digit revenue would then fail its own label.
    """
    value = float(amount)
    return str(int(value)) if value.is_integer() else repr(value)


def parsed(text: str) -> float | None:
    """The reading back as a number, or ``None`` for prose.

    The decay kinds put a prose account in ``observed_value``; the mechanical
    kinds put a bare reading there precisely so this function exists — the
    compiler types the number into the cell and the validator compares the cell
    against it, and neither may guess at a sentence.
    """
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Locating the cell a record names
# ---------------------------------------------------------------------------


def _cells(ir: ArtifactIR):  # type: ignore[no-untyped-def]
    """Every cell of every table, in the one order everything here agrees on.

    Tables in section order, rows in row order, columns in the *table's* column
    order — never ``sorted(row.cells)``, because the corrupted cell must be the
    same cell on every build and the column list is the declared order while a
    dict's key order is an accident of construction.
    """
    for table in ir.tables():
        for row in table.rows:
            for column in table.columns:
                cell = row.cells.get(column.key)
                if cell is not None:
                    yield table, row, column.key, cell


def _sum_over(table: Table, column_key: str, operands: list[str]) -> float:
    """What a SUM over *operands* states, read from the table's own rows.

    Bare operands only — the callers below never target a cross-sheet
    (``table:row:column``) sum, and skipping the qualified form keeps this a
    lookup rather than a second formula evaluator. ``None`` counts as zero
    because that is what Excel's SUM does to an empty cell, and the copy's
    formula has to compute to the number the record states.
    """
    lookup = {row.key: row for row in table.rows}
    total = 0.0
    for key in operands:
        row = lookup.get(key)
        cell = row.cells.get(column_key) if row is not None else None
        if cell is not None and isinstance(cell.value, (int, float)):
            total += float(cell.value)
    return total


def _target(ir: ArtifactIR, error: IntentionalError):  # type: ignore[no-untyped-def]
    """The pre-corruption cell *error* names, or ``None``.

    Found by the canonical fact the record points at, filtered by the shape the
    corruption needs — a declared ``DIFFERENCE`` for a paste-over, a declared
    ``SUM`` with bare operands for a short range. The fact id alone is not
    enough: the group total's fact also appears behind the Summary sheet's
    ``REFERENCE`` cells and in the Reconciliation sheet's stated column, and a
    unit's variance fact reappears as a ``SUM`` on the Category and Store
    sheets. First match in ``_cells`` order wins, which lands both kinds on the
    Business Unit P&L — the sheet a reader opens first.
    """
    if error.error_type is ErrorType.HARDCODED_VALUE:
        wanted = FormulaKind.DIFFERENCE
    else:
        wanted = FormulaKind.SUM
    for table, row, column_key, cell in _cells(ir):
        if cell.fact_id != error.canonical_fact_id or cell.formula is not wanted:
            continue
        if wanted is FormulaKind.SUM and (
            len(cell.operands) < 2 or any(":" in operand for operand in cell.operands)
        ):
            continue
        return table, row, column_key, cell
    return None


def _with_cell(
    ir: ArtifactIR, table_key: str, row_key: str, column_key: str, cell: Cell
) -> ArtifactIR:
    """*ir* with one cell replaced. Rebuilt, because the thin waist is frozen."""
    sections = []
    for section in ir.sections:
        table = section.table
        if table is None or table.key != table_key:
            sections.append(section)
            continue
        rows: list[Row] = []
        for row in table.rows:
            if row.key != row_key:
                rows.append(row)
                continue
            cells = dict(row.cells)
            cells[column_key] = cell
            rows.append(row.model_copy(update={"cells": cells}))
        sections.append(
            section.model_copy(update={"table": table.model_copy(update={"rows": rows})})
        )
    return ir.model_copy(update={"sections": sections})


def _corrupted(ir: ArtifactIR, error: IntentionalError) -> ArtifactIR:
    """*ir* with the one cell *error* names carrying the recorded wrong value.

    Raises rather than skipping when the plan and the compiled sheet disagree
    about the cell existing: a ledgered error the page cannot carry would leave
    ``validate.intentional`` to refuse the corpus later anyway, and a failure
    at the point of disagreement names the actual defect.
    """
    observed = parsed(error.observed_value)
    if observed is None:
        raise ValueError(
            f"{error.id}: observed_value {error.observed_value!r} is not a bare"
            " reading — the mechanical kinds record the wrong figure itself,"
            " because this compiler types it into the cell"
        )
    found = _target(ir, error)
    if found is None:
        raise ValueError(
            f"{error.id}: {ir.id} has no cell citing {error.canonical_fact_id}"
            f" with the derivation a {error.error_type.value} corrupts — the"
            " plan and the compiled workbook disagree"
        )
    table, row, column_key, cell = found

    if error.error_type is ErrorType.HARDCODED_VALUE:
        # The formula goes, the wrong literal arrives, the citation stays: the
        # cell still *reads* its fact — that is what the label's canonical_fact_id
        # points a reader at — it just no longer states it. Dropping the fact_id
        # instead would also trip `carried_evidence.required_fact_not_carried`,
        # which is the ordinary check correctly refusing to unlearn the fact.
        corrupt = cell.model_copy(
            update={"formula": None, "operands": [], "value": observed}
        )
    else:
        remaining = list(cell.operands[:-1])
        stated = _sum_over(table, column_key, remaining)
        if abs(stated - observed) > _TOLERANCE:
            raise ValueError(
                f"{error.id}: the truncated range states {stated!r} but the plan"
                f" recorded {error.observed_value!r} — the messiness pass and"
                " this compiler no longer agree which row the range drops"
            )
        # The literal moves with the formula, so a formula-free format shows
        # the same wrong number Excel computes — the corruption is one cell
        # disagreeing with the ledger, never one document disagreeing with its
        # own projections.
        corrupt = cell.model_copy(update={"operands": remaining, "value": observed})

    return _with_cell(ir, table.key, row.key, column_key, corrupt)


# ---------------------------------------------------------------------------
# The registered compiler
# ---------------------------------------------------------------------------


def workbook_copy(world: World, intent: ArtifactIntent, minter: Any) -> ArtifactIR:
    """The month-end model again, retitled, with its planned errors on the page.

    Built by the real workbook compiler first — same facts, same sheets, same
    charts — because a copy that restated the model by hand would be a second
    account of every number on it. Then each mechanical error the ledger
    records against *this* intent is made true of one cell. The errors are read
    from the world rather than passed in because compilation happens well after
    planning (``World.compile`` is lazy) and replays from the recipe: the
    messiness step re-runs before any compile, so the records are always
    present wherever this compiler runs.
    """
    ir = documents.finance_workbook(world, intent, minter)
    # Retitled for the reader and for `_contracted`'s cohesion rule, which
    # requires a type word ("copy") in the title — the same rule that stops a
    # workbook wearing a memo's name.
    ir = ir.model_copy(update={"title": f"{ir.title} (working copy)"})
    planned = [
        error
        for error in world._intentional_errors
        if error.artifact_id == intent.id and error.error_type in MECHANICAL_KINDS
    ]
    for error in planned:
        ir = _corrupted(ir, error)
    return ir


# ---------------------------------------------------------------------------
# Substantiation, for `validate.intentional`
# ---------------------------------------------------------------------------


def unsubstantiated(
    ir: ArtifactIR, error: IntentionalError, canonical: CanonicalFact | None
) -> str | None:
    """Why the compiled sheet does not substantiate *error*, or ``None``.

    The mechanical kinds are the first whose evidence is a *cell* rather than a
    citation or a date, so the check reads the IR: some cell must cite the
    canonical fact, carry exactly the recorded wrong reading, and carry it in
    the recorded way — no formula at all for a paste-over, a SUM that computes
    to the wrong reading for a short range. A label naming a disagreement the
    page does not have is the corpus vouching for something it cannot show,
    which is the exact failure ``validate.intentional`` exists to refuse.
    """
    observed = parsed(error.observed_value)
    if observed is None:
        return (
            f"records observed_value {error.observed_value!r}, which is not the"
            " bare reading the mechanical kinds promise — nothing can compare a"
            " cell against a sentence"
        )
    if canonical is None or canonical.value is None:
        return (
            f"points at {error.canonical_fact_id!r}, which is not a measured"
            " fact, so there is no figure for the cell to disagree with"
        )
    if abs(observed - float(canonical.value.amount)) <= _TOLERANCE:
        return (
            f"records observed {error.observed_value!r} equal to the canonical"
            f" reading of {canonical.id} — a label claiming a disagreement the"
            " sheet does not have"
        )

    for table, _row, column_key, cell in _cells(ir):
        if cell.fact_id != error.canonical_fact_id:
            continue
        if not isinstance(cell.value, (int, float)):
            continue
        if abs(float(cell.value) - observed) > _TOLERANCE:
            continue
        if error.error_type is ErrorType.HARDCODED_VALUE:
            if cell.formula is None:
                return None
        elif cell.formula is FormulaKind.SUM and not any(
            ":" in operand for operand in cell.operands
        ):
            # The formula must really compute the wrong total — a literal that
            # merely *says* the short number over an intact range would render
            # as a correct formula under a wrong label.
            if abs(_sum_over(table, column_key, list(cell.operands)) - observed) <= _TOLERANCE:
                return None
    return (
        f"no cell of {ir.id} citing {error.canonical_fact_id} carries the"
        f" recorded wrong reading {error.observed_value!r} in the recorded way"
        f" ({error.error_type.value}) — the workbook does not substantiate the"
        " label"
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

# Unconditional at import, `documents.register_artifact_types`' contract: this
# module is imported by `generators.distractors`, which `worldloom/__init__`
# imports by name for exactly this class of registration, so a corpus carrying
# a `workbook_copy` compiles identically in the process that built it and in a
# fresh one. Working-document authority and a published lifecycle because that
# is what a hand-kept copy *is* — and deliberately not SYSTEM_OF_RECORD, so
# authority resolution ranks the real model above its corrupted copy without
# any special case knowing about this module.
documents.register_artifact_types(
    standing={WORKBOOK_COPY: (Authority.WORKING_DOCUMENT, Lifecycle.PUBLISHED)},
    lags={WORKBOOK_COPY: COPY_LAG},
    compilers={WORKBOOK_COPY: workbook_copy},
)
# The copy is a workbook and renders as one — the same claim `banking_documents`
# makes for `capital_return`, through the same seam.
_xlsx.register(WORKBOOK_COPY)

__all__ = [
    "COPY_LAG",
    "CORRUPTIBLE",
    "MECHANICAL_KINDS",
    "WORKBOOK_COPY",
    "parsed",
    "reading",
    "unsubstantiated",
    "workbook_copy",
]
