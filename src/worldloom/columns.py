"""The variance workbook's columns, declared once instead of typed seven times.

The measured problem. Eight P&L columns — budget, actual and variance for
revenue and for gross profit, plus the two margin rates — reach a compiled
workbook through **seven** places in ``documents.py`` that have to agree with
each other: three hand-written ``Column`` lists (the P&L sheet, the store
sheet's money subset, the variance memo's divisional summary), a ``key -> fact
kind`` table, a ``key -> formula`` table, the set of keys a subtotal must not
sum, and that same non-summing rule restated over *fact kinds* for the trend
sheets, which are laid out by period and so cannot look a column up by key.
Every corpus, in every tenant, on every seed, gets the same eight in the same
order with the same four formulas — 4 tables and 955 cells on the default
one-period build alone.

Seven tables agreeing is a claim, and this repository has already paid for it
twice, both times recorded in the comments this module inherits.
``financial.gross_margin_pct.budget`` was minted per category and per unit,
planned into the workbook by ``generators/planning.py``, and read by no column:
114 facts a build, carried by nothing, for as long as the workbook had existed.
The trend sheets had the same shape of defect at a different scale — they read
revenue and only revenue while the planner handed them three measures. Neither
failed anything. A measure no column reads is not an error anywhere; it is a
document that is carried, cited, and silently thinner, which is exactly the
failure ``doctypes.lint``'s docstring describes one layer up ("it *compiles*,
into a document with one hidden appendix and no visible section").

So the sheet stops being seven tables and becomes one declaration with four
projections and three narrowings, all of them computed rather than maintained
— and no two of them can disagree, because there is nothing left to disagree
with. That is the same move ``episodes.FactKindSpec`` already made for facts and
``structure.py`` made for outlines, applied to the one part of a workbook nobody
had counted.

**A column reads a fact kind, and may *also* derive.** That is not the shape
this extraction was specified with, and the shipped sheet is the evidence
against the alternative: all eight columns read a kind, and four of them
(``revenue_variance``, ``gp_variance``, ``gm_pct_budget``, ``gm_pct_actual``)
*additionally* declare a formula. Both halves are load-bearing and neither can
be dropped. ``models.Cell``'s own docstring says why — "Always carries a literal
``value``, even when it is computed" — so the fact supplies the value and the
``fact_id`` that ``validate.carried_evidence`` and the lineage sheet read, while
the derivation supplies the ``FormulaKind`` that ``render.xlsx`` spells as
``=C4-B4``. A column forced to choose would lose either the lineage or the
formula, and the workbook is the corpus's system of record on the strength of
having both. What does survive from that specification is the other half: a
column reading *no* fact kind is refused at construction, because
``_measure_row`` indexes the kind table by column key and a missing entry is a
``KeyError`` thrown a long way from the mistake.

**The derivation vocabulary is closed and is two verbs, not four.**
``FormulaKind`` has four members and only two of them are things a *column* can
be: ``DIFFERENCE`` and ``RATIO_PCT`` are within-row, "this column from those
columns", which is what a column spec declares once for every row on the sheet.
``SUM`` is within-column, over named *rows* — that is what a subtotal does, and
it is spelled here as ``summable`` rather than as a derivation, because a
subtotal's operands are the rows it happens to have and are not knowable when
the column is declared. ``REFERENCE`` addresses a cell on another table
entirely. Binding to two rather than inventing four keeps the vocabulary the one
``models.FormulaKind`` already defines.

The lint is the part that earns the extraction. Each of its rules is either
something the compiler assumes silently or something a renderer degrades on
rather than refuses — ``render.xlsx._formula`` returns ``None`` for a
``RATIO_PCT`` whose operand column is not on the table, so the cell renders as a
pasted value and no check anywhere says the declared computation went missing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from . import factkinds
from .models import FormulaKind

#: The formulas a *column* may declare. Closed for ``ConstraintKind``'s reason:
#: a verb the evaluator cannot spell is a computation wearing a rule's clothes.
#: See the module docstring for why the other two ``FormulaKind`` members are
#: not column derivations.
ColumnFormula = Literal[FormulaKind.DIFFERENCE, FormulaKind.RATIO_PCT]

#: How many columns each verb reads. Both are binary and both are read
#: positionally — ``a - b`` and ``a / b`` are not commutative, so an operand
#: pair is an ordered tuple rather than a set, and a third operand is not extra
#: information but a silent no-op: `render.xlsx._formula` guards on
#: ``len(cell.operands) == 2`` and emits nothing at all when the arity is wrong.
ARITY: Mapping[FormulaKind, int] = {
    FormulaKind.DIFFERENCE: 2,
    FormulaKind.RATIO_PCT: 2,
}

#: What a column's figures are, which decides both how they are formatted and
#: whether they add up. Two values, closed: this is not a unit system, it is the
#: distinction between an amount and a rate, and that distinction is the whole
#: content of the non-summing rule below.
Unit = Literal["money", "percent"]


@dataclass(frozen=True)
class Derivation:
    """How one column is computed from others, within a row.

    ``operands`` names *column keys* on the same sheet, never fact kinds and
    never rows. That is the same address space ``Cell.operands`` uses for these
    two verbs, so the spec and the IR cannot drift on what an operand means.
    """

    kind: ColumnFormula
    operands: tuple[str, ...]


@dataclass(frozen=True)
class ColumnSpec:
    """One column of a sheet: what it reads, what it is, and how it totals."""

    key: str
    """The cell key. Reaches the IR as ``Column.key`` and as the key of every
    ``Row.cells`` entry, and is what a ``Chart.series`` names."""

    label: str
    """The column heading a reader sees."""

    kind: str
    """The fact kind this column reads, per subject and period. Never empty —
    see the module docstring: the value and the ``fact_id`` come from the
    ledger even on a column that also declares a derivation."""

    unit: Unit = "money"

    derive: Derivation | None = None
    """How a renderer recomputes this column's value from the two beside it.
    ``None`` for a column that is only ever stated."""

    summable: bool = True
    """Whether a subtotal row may sum this column over its children.

    A margin percentage is a ratio of totals, never the total of ratios; a
    variance, by contrast, is additive, so a subtotal sums its children's
    variances and shows which of them the group's miss came from. That sentence
    is the reason this field exists and it predates the field: it was the
    comment over ``documents._NOT_ADDITIVE``, where it was prose beside a
    hand-written set, and it is now a rule the lint can fire on.
    """

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("a column needs a key")
        if not self.kind:
            raise ValueError(
                f"column {self.key!r} reads no fact kind — every column on a"
                " measure sheet resolves a fact for its value and its `fact_id`,"
                " including the four that also derive, so an empty kind is a"
                " `KeyError` in `_measure_row` rather than a column of blanks"
            )


@dataclass(frozen=True)
class Sheet:
    """An ordered set of columns, and the six projections ``documents`` reads.

    Frozen and ordered. The order *is* the sheet's column order in every
    rendered format, so it is data rather than an implementation detail, and a
    ``dict`` keyed by column would be one insertion away from reordering a
    workbook nobody meant to touch.

    The projections return fresh containers on every call. That looks wasteful
    for eight columns and is deliberate: ``documents`` binds them to module
    globals at import, and ``tests/test_carried_evidence.py`` reproduces the
    ``gm_pct_budget`` defect by *mutating* those globals — a shared container
    would let that test corrupt the sheet for every test after it.
    """

    name: str
    columns: tuple[ColumnSpec, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for column in self.columns:
            if column.key in seen:
                # Refused rather than linted, because every projection below is
                # keyed by column key: a duplicate does not produce a wrong
                # sheet, it produces a sheet whose kind table and column list
                # disagree about how many columns there are.
                raise ValueError(
                    f"sheet {self.name!r} declares column {column.key!r} twice"
                )
            seen.add(column.key)

    # -- lookups ---------------------------------------------------------

    def get(self, key: str) -> ColumnSpec | None:
        return next((column for column in self.columns if column.key == key), None)

    def keys(self) -> tuple[str, ...]:
        return tuple(column.key for column in self.columns)

    # -- the projections `documents` binds -------------------------------

    def kinds(self) -> dict[str, str]:
        """``column key -> fact kind``. Was ``documents._MEASURES``."""
        return {column.key: column.kind for column in self.columns}

    def derivations(self) -> dict[str, tuple[FormulaKind, list[str]]]:
        """``column key -> (formula, operand columns)``. Was ``documents._DERIVED``.

        Shaped as the tuple the compiler already destructures rather than as
        ``Derivation``: the extraction is meant to be invisible downstream, and
        a new shape here would be a second edit in every consumer for no
        behaviour.
        """
        return {
            column.key: (column.derive.kind, list(column.derive.operands))
            for column in self.columns
            if column.derive is not None
        }

    def not_summable(self) -> frozenset[str]:
        """The keys a subtotal must not sum. Was ``documents._NOT_ADDITIVE``."""
        return frozenset(column.key for column in self.columns if not column.summable)

    def rate_kinds(self) -> frozenset[str]:
        """The same rule stated over fact *kinds*, for the trend sheets.

        Was ``documents._RATE_KINDS``, a second hand-written set. The trend
        sheets are laid out one column per period, so they have no column key to
        test — they hold a fact kind and nothing else, and before this the two
        sets could disagree about whether a margin adds up depending on which
        sheet you were reading.
        """
        return frozenset(column.kind for column in self.columns if not column.summable)

    # -- deriving smaller sheets -----------------------------------------

    def select(self, *keys: str, name: str = "") -> Sheet:
        """The named columns, in the order named, as a sheet of their own.

        A sheet that shows revenue and not gross profit is the store sheet, and
        it is the same eight columns' worth of decisions narrowed rather than a
        second declaration — which is what it was. Selection is where the
        operand rules below stop being theoretical: dropping ``gp_actual`` from
        a sheet that still carries ``gm_pct_actual`` leaves a declared ratio
        with nothing to divide, and no renderer says so.
        """
        chosen = []
        for key in keys:
            column = self.get(key)
            if column is None:
                raise ValueError(
                    f"sheet {self.name!r} has no column {key!r}; it has"
                    f" {', '.join(self.keys())}"
                )
            chosen.append(column)
        # Named after the IR table it becomes, when the caller says so: a
        # finding reading `stores.columns[2]` points at a sheet somebody can
        # open, and `pnl[revenue_budget,revenue_actual,...]` points at nothing.
        return Sheet(
            name=name or f"{self.name}[{','.join(keys)}]", columns=tuple(chosen)
        )

    def relabel(self, labels: Mapping[str, str]) -> Sheet:
        """The same columns under different headings.

        One caller, and it is honest: the variance memo's divisional table calls
        ``revenue_variance`` just "Variance", because the table is already
        titled by division and the word "Revenue" on every heading is noise a
        reader of a memo does not need. A relabel changes nothing a formula, a
        fact or a check reads.
        """
        unknown = sorted(set(labels) - set(self.keys()))
        if unknown:
            raise ValueError(
                f"sheet {self.name!r} has no column(s) {', '.join(repr(k) for k in unknown)}"
            )
        return replace(
            self,
            columns=tuple(
                replace(column, label=labels[column.key]) if column.key in labels else column
                for column in self.columns
            ),
        )


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------


def lint(sheet: Sheet) -> list[str]:
    """Findings an author should read before a sheet reaches a renderer.

    Same contract as ``doctypes.lint`` and for the same reason: a list of
    strings, each naming a place where what was declared and what the engine
    will do diverge, and nothing here raises. The construction refusals in
    ``ColumnSpec`` and ``Sheet`` cover what makes a sheet incoherent as a
    *value*; everything below is a sheet that builds fine and renders wrong.

    None of these fails a test today, which is the point: every one of them is a
    silent degradation. A ``RATIO_PCT`` whose denominator column is not on the
    table makes ``render.xlsx._formula`` return ``None``, and the cell renders
    as a pasted literal with no formula and no complaint — indistinguishable
    from a column that never declared one.
    """
    findings: list[str] = []
    present = set(sheet.keys())

    for index, column in enumerate(sheet.columns):
        at = f"{sheet.name}.columns[{index}] ({column.key!r})"

        # -- the fact kind ------------------------------------------------
        if not factkinds.resolvable(column.kind):
            findings.append(
                f"{at}: reads fact kind {column.kind!r}, which no generator in"
                " this process declares. `_measure_row` looks it up per row and"
                " per period, misses every time, and emits a column of `None`"
                " with no `fact_id` — the workbook renders, reconciles (two"
                " absent numbers agree) and carries nothing. Register the kind"
                " in `factkinds`, or read one that exists."
            )

        # -- the non-summing rule -----------------------------------------
        if column.unit == "percent" and column.summable:
            findings.append(
                f"{at}: is a percentage and is summable. A margin percentage is"
                " a ratio of totals, never the total of ratios — a subtotal row"
                " would add its children's rates together and state, as the"
                " division's margin, a number three or four times any category's."
                " This is the rule `_NOT_ADDITIVE`'s comment existed to enforce"
                " by hand; set `summable=False`."
            )

        if column.derive is None:
            continue

        # -- the derivation -----------------------------------------------
        expected = ARITY[column.derive.kind]
        if len(column.derive.operands) != expected:
            findings.append(
                f"{at}: {column.derive.kind.value} takes {expected} operands and"
                f" was given {len(column.derive.operands)}"
                f" ({', '.join(repr(o) for o in column.derive.operands) or 'none'})."
                " `render.xlsx._formula` guards on the arity and emits no formula"
                " at all rather than guessing which operands were meant, so the"
                " cell silently loses its computation."
            )

        missing = [name for name in column.derive.operands if name not in present]
        if missing:
            findings.append(
                f"{at}: derives from column(s)"
                f" {', '.join(repr(name) for name in missing)}, which this sheet"
                " does not carry. The IR still declares the formula, so the cell"
                " reaches XLSX with an operand that resolves to no address and"
                " renders as a pasted value — a computed cell that stopped being"
                " computed, with nothing downstream able to tell."
            )

        # A subtotal builds its summable columns first and then computes the
        # non-summable ones from what it built (`documents._sum_row`). An
        # operand that is itself non-summable is therefore absent at that point
        # and the whole cell is skipped — the subtotal row loses the column,
        # while the rows above it have it. Not caught by the rule above: the
        # operand *is* on the sheet.
        if not column.summable:
            unusable = [
                name
                for name in column.derive.operands
                if (operand := sheet.get(name)) is not None and not operand.summable
            ]
            if unusable:
                findings.append(
                    f"{at}: is not summable and derives from"
                    f" {', '.join(repr(name) for name in unusable)}, which is not"
                    " summable either. `_sum_row` computes the non-summable"
                    " columns from the sums it has already built, so this cell"
                    " is dropped from every subtotal and total row while the"
                    " detail rows above still carry it."
                )

    findings.extend(_cycles(sheet))
    return findings


def _cycles(sheet: Sheet) -> list[str]:
    """Columns that derive from themselves, however many hops away.

    A cycle is not a runtime hang here — the IR is built from facts and the
    formula is only a *declaration* — which is precisely why it needs saying.
    Excel resolves it at open time, into a circular-reference warning and a zero
    in a cell the rest of the sheet reconciles against, and a Markdown render of
    the same table shows the ledger's value and looks fine. Two formats, two
    answers, no check between them.
    """
    def route(start: str, key: str, path: tuple[str, ...]) -> tuple[str, ...] | None:
        """The path from *start* back to *start*, or ``None``."""
        column = sheet.get(key)
        if column is None or column.derive is None:
            return None
        # Operands in declaration order, not sorted: the reported route should
        # read the way the author wrote it. Determinism comes from the tuple
        # being ordered data, not from re-sorting it here.
        for operand in column.derive.operands:
            if operand == start:
                return path + (start,)
            if operand in path:
                continue  # a cycle that does not pass through `start`; its own turn comes
            found = route(start, operand, path + (operand,))
            if found is not None:
                return found
        return None

    # Sorted, and only the first is reported: a cycle has no canonical member,
    # so reporting one finding per column on it would turn one defect into
    # three, and picking the member by iteration order would make the wording
    # depend on how the columns happened to be declared.
    for start in sorted(sheet.keys()):
        cycle = route(start, start, (start,))
        if cycle is not None:
            return [
                f"{sheet.name}: column {start!r} derives from itself"
                f" ({' -> '.join(cycle)}). Nothing raises — the value comes from"
                " the ledger and only the formula is circular — so XLSX opens on"
                " a circular-reference warning and a zero while Markdown renders"
                " the ledger's figure, and no check compares the two."
            ]
    return []


# ---------------------------------------------------------------------------
# The shipped sheet
# ---------------------------------------------------------------------------

#: The month-end model's P&L columns, in the order every rendered format shows
#: them. Budget, then actual, then the variance between them, for each of the
#: two measures a retailer manages by — and then the two margin rates.
#:
#: ``gm_pct_budget`` was absent for a long time, and its absence was invisible:
#: ``generators/finance.py`` mints ``financial.gross_margin_pct.budget`` for
#: every category and unit, ``generators/planning.py`` puts those facts in the
#: workbook's required set, and no column here read them — 114 facts a build,
#: planned into a document and carried by none of it. Nothing complained,
#: because until ``validate.carried_evidence`` existed nothing compared what an
#: intent asked a document to carry against what the compiled document holds.
#: Budget margin also earns its place on the sheet: a division can beat its
#: gross-profit budget while missing the rate it was supposed to earn it at, and
#: with actual margin alone a reader cannot see that.
PNL = Sheet(
    name="pnl",
    columns=(
        ColumnSpec(key="revenue_budget", label="Revenue budget",
                   kind="financial.revenue.budget"),
        ColumnSpec(key="revenue_actual", label="Revenue actual",
                   kind="financial.revenue.actual"),
        ColumnSpec(key="revenue_variance", label="Revenue variance",
                   kind="financial.revenue.variance",
                   derive=Derivation(FormulaKind.DIFFERENCE,
                                     ("revenue_actual", "revenue_budget"))),
        ColumnSpec(key="gp_budget", label="GP budget",
                   kind="financial.gross_profit.budget"),
        ColumnSpec(key="gp_actual", label="GP actual",
                   kind="financial.gross_profit.actual"),
        ColumnSpec(key="gp_variance", label="GP variance",
                   kind="financial.gross_profit.variance",
                   derive=Derivation(FormulaKind.DIFFERENCE,
                                     ("gp_actual", "gp_budget"))),
        ColumnSpec(key="gm_pct_budget", label="GM% budget",
                   kind="financial.gross_margin_pct.budget", unit="percent",
                   derive=Derivation(FormulaKind.RATIO_PCT,
                                     ("gp_budget", "revenue_budget")),
                   summable=False),
        ColumnSpec(key="gm_pct_actual", label="GM% actual",
                   kind="financial.gross_margin_pct.actual", unit="percent",
                   derive=Derivation(FormulaKind.RATIO_PCT,
                                     ("gp_actual", "revenue_actual")),
                   summable=False),
    ),
)

#: The store sheet's money columns. A distribution centre books no turnover and
#: a store's gross profit is not booked at site level at all, so the estate is
#: read on revenue alone — the same three decisions as the P&L's first three
#: columns, narrowed rather than restated.
STORES = PNL.select(
    "revenue_budget", "revenue_actual", "revenue_variance", name="stores"
)

#: The variance memo's divisional table: revenue in full, plus the margin rate,
#: under the memo's own heading for the variance column.
#:
#: It carries ``gm_pct_actual`` without ``gp_actual``, so ``lint`` reports one
#: finding against it — truthfully. The ratio's numerator column is not on the
#: table, ``render.xlsx._formula`` therefore emits no formula, and the cell has
#: rendered as a pasted literal since the table was written. It is latent rather
#: than wrong today (the memo is a Word document and this table is never the
#: subject of an XLSX render), and both fixes — adding the column, or dropping
#: the derivation for this sheet — change what a reader sees. So it is reported
#: here and left standing, which is what a lint is for.
DIVISIONAL = PNL.select(
    "revenue_budget", "revenue_actual", "revenue_variance", "gm_pct_actual",
    name="divisions",
).relabel({"revenue_variance": "Variance"})


def sheets() -> Sequence[Sheet]:
    """Every sheet this module declares, for a lint that takes no argument.

    The same argument ``doctypes.audit`` makes: a check that has to be pointed
    at the thing it checks gets pointed at the wrong thing.
    """
    return (PNL, STORES, DIVISIONAL)


def findings(over: Iterable[Sheet] | None = None) -> dict[str, list[str]]:
    """``sheet name -> findings``, over *over* or every declared sheet."""
    return {sheet.name: lint(sheet) for sheet in (over if over is not None else sheets())}


__all__ = [
    "ARITY",
    "ColumnFormula",
    "ColumnSpec",
    "DIVISIONAL",
    "Derivation",
    "PNL",
    "STORES",
    "Sheet",
    "Unit",
    "findings",
    "lint",
    "sheets",
]
