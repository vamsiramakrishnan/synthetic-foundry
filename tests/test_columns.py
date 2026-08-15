"""The workbook's columns, as a declaration that can be wrong out loud.

`columns.py` moved eight column decisions out of seven agreeing tables in
`documents.py` and into one `Sheet`. Two things have to be true for that to be
worth anything, and both are tested here.

The extraction must have lost nothing — so the projections are pinned against
the literals they replaced, written out again rather than recomputed, because a
test that derives its expectation the same way the code does is a test of
nothing.

And the lint must fire. Every rule below is broken deliberately on the *shipped*
sheet, one rule per breakage, because a lint nobody has fired is a comment. The
last test is the reason the whole file exists: a margin percentage left summable
passes `worldloom validate` clean and makes a spreadsheet compute 75.15 where
the ledger, and every other rendered format, says 24.52.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from worldloom import columns, documents
from worldloom.models import Column, FormulaKind
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _with(sheet: columns.Sheet, key: str, **changes: object) -> columns.Sheet:
    """*sheet* with one column changed — the shipped sheet, broken one way."""
    return replace(
        sheet,
        columns=tuple(
            replace(column, **changes) if column.key == key else column  # type: ignore[arg-type]
            for column in sheet.columns
        ),
    )


# ---------------------------------------------------------------------------
# The extraction lost nothing
# ---------------------------------------------------------------------------


def test_the_projections_are_the_tables_they_replaced() -> None:
    """The four constants, written out as they stood before the extraction.

    Deliberately literal. `documents._MEASURES == columns.PNL.kinds()` would
    pass for any sheet at all, including one with the wrong fact kinds on it.
    """
    assert documents._MEASURES == {
        "revenue_budget": "financial.revenue.budget",
        "revenue_actual": "financial.revenue.actual",
        "revenue_variance": "financial.revenue.variance",
        "gp_budget": "financial.gross_profit.budget",
        "gp_actual": "financial.gross_profit.actual",
        "gp_variance": "financial.gross_profit.variance",
        "gm_pct_budget": "financial.gross_margin_pct.budget",
        "gm_pct_actual": "financial.gross_margin_pct.actual",
    }
    assert documents._DERIVED == {
        "revenue_variance": (FormulaKind.DIFFERENCE, ["revenue_actual", "revenue_budget"]),
        "gp_variance": (FormulaKind.DIFFERENCE, ["gp_actual", "gp_budget"]),
        "gm_pct_budget": (FormulaKind.RATIO_PCT, ["gp_budget", "revenue_budget"]),
        "gm_pct_actual": (FormulaKind.RATIO_PCT, ["gp_actual", "revenue_actual"]),
    }
    assert documents._NOT_ADDITIVE == frozenset({"gm_pct_budget", "gm_pct_actual"})
    assert documents._RATE_KINDS == frozenset({
        "financial.gross_margin_pct.actual",
        "financial.gross_margin_pct.budget",
    })


def test_the_compiled_column_lists_are_unchanged() -> None:
    """Key, label and number format, for all three sheets that carry them.

    These reach the reader — a heading in Word, a column format in Excel — so a
    single changed label is a corpus that no longer replays byte-for-byte, which
    is what CI diffs.
    """
    assert [(c.key, c.label, c.number_format) for c in documents._pnl_columns()] == [
        ("revenue_budget", "Revenue budget", "#,##0;(#,##0)"),
        ("revenue_actual", "Revenue actual", "#,##0;(#,##0)"),
        ("revenue_variance", "Revenue variance", "#,##0;(#,##0)"),
        ("gp_budget", "GP budget", "#,##0;(#,##0)"),
        ("gp_actual", "GP actual", "#,##0;(#,##0)"),
        ("gp_variance", "GP variance", "#,##0;(#,##0)"),
        ("gm_pct_budget", "GM% budget", "0.00%"),
        ("gm_pct_actual", "GM% actual", "0.00%"),
    ]
    assert [(c.key, c.label, c.number_format) for c in documents._columns(columns.STORES)] == [
        ("revenue_budget", "Revenue budget", "#,##0;(#,##0)"),
        ("revenue_actual", "Revenue actual", "#,##0;(#,##0)"),
        ("revenue_variance", "Revenue variance", "#,##0;(#,##0)"),
    ]
    # `gp_actual` arrived when the divisional cut's margin ratio was given its
    # numerator back — see `test_the_memo_margin_ratio_is_computable_again` —
    # so this list is the pre-extraction literal plus that one deliberate
    # column, in operand-before-ratio order.
    assert [(c.key, c.label, c.number_format) for c in documents._columns(columns.DIVISIONAL)] == [
        ("revenue_budget", "Revenue budget", "#,##0;(#,##0)"),
        ("revenue_actual", "Revenue actual", "#,##0;(#,##0)"),
        ("revenue_variance", "Variance", "#,##0;(#,##0)"),
        ("gp_actual", "GP actual", "#,##0;(#,##0)"),
        ("gm_pct_actual", "GM% actual", "0.00%"),
    ]


def test_the_store_sheet_is_the_pnl_narrowed() -> None:
    """Not a second declaration of the same three columns.

    The property that matters is that a change to the P&L's revenue columns
    reaches the store sheet without anybody editing it — which is exactly what
    `select` buys and what three hand-written `Column` lists did not.
    """
    for column in columns.STORES.columns:
        assert column == columns.PNL.get(column.key)


# ---------------------------------------------------------------------------
# The lint on the shipped sheets
# ---------------------------------------------------------------------------


def test_the_shipped_sheets_lint_clean() -> None:
    assert columns.lint(columns.PNL) == []
    assert columns.lint(columns.STORES) == []


def test_the_memo_margin_ratio_is_computable_again() -> None:
    """The expected-finding pin this test used to be, flipped to no finding.

    The divisional cut shipped carrying `gm_pct_actual` without `gp_actual`, so
    the ratio's numerator resolved to no address, `render.xlsx._formula`
    returned `None`, and the margin cell rendered as a pasted literal from the
    day the table was written — a number Word prints and Excel cannot
    recompute, the defect class this whole lint exists to catch. This test
    pinned that as an *expected* finding until `columns._CUTS` gained the
    operand column; now the sheet lints clean and the derivation is asserted
    whole, so the cut losing its numerator again is a failure here rather than
    a finding somebody re-pins.
    """
    assert columns.lint(columns.DIVISIONAL) == []
    ratio = columns.DIVISIONAL.get("gm_pct_actual")
    assert ratio is not None and ratio.derive is not None
    assert ratio.derive.kind is FormulaKind.RATIO_PCT
    assert set(ratio.derive.operands) <= set(columns.DIVISIONAL.keys())


# ---------------------------------------------------------------------------
# The shipped sheet, broken one rule at a time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("what", "broken", "signature"),
    [
        # A typo in an operand. The formula survives into the IR and dies at the
        # renderer, silently.
        (
            "an operand naming no column",
            lambda: _with(
                columns.PNL, "gm_pct_actual",
                derive=columns.Derivation(
                    FormulaKind.RATIO_PCT, ("gross_profit_actual", "revenue_actual")
                ),
            ),
            "which this sheet does not carry",
        ),
        # Gross profit computed from its own variance, which is computed from
        # it. Nothing raises: the value is the ledger's and only the formula
        # loops.
        (
            "a derivation cycle",
            lambda: _with(
                columns.PNL, "gp_actual",
                derive=columns.Derivation(
                    FormulaKind.DIFFERENCE, ("gp_variance", "gp_budget")
                ),
            ),
            "derives from itself",
        ),
        # `_sum_row` builds the summable columns first and computes the rest
        # from what it built, so a non-summable operand is simply absent by
        # then and the subtotal loses the whole cell.
        (
            "a non-summable column deriving from a non-summable one",
            lambda: _with(columns.PNL, "gp_actual", summable=False),
            "is not summable either",
        ),
        # A plausible kind nothing mints. `_measure_row` misses on every row and
        # every period and emits a column of `None`, and reconciliation compares
        # two absent numbers and agrees.
        (
            "a fact kind no generator declares",
            lambda: _with(columns.PNL, "gp_budget", kind="financial.gross_profit.plan"),
            "which no generator in this process declares",
        ),
        # The rule `_NOT_ADDITIVE`'s comment enforced by hand.
        (
            "a summable percentage",
            lambda: _with(columns.PNL, "gm_pct_budget", summable=True),
            "is a percentage and is summable",
        ),
        # Three operands for a binary verb. `render.xlsx._formula` guards on the
        # arity and emits nothing rather than guessing.
        (
            "a formula given the wrong number of operands",
            lambda: _with(
                columns.PNL, "revenue_variance",
                derive=columns.Derivation(
                    FormulaKind.DIFFERENCE,
                    ("revenue_actual", "revenue_budget", "gp_actual"),
                ),
            ),
            "takes 2 operands and was given 3",
        ),
    ],
    ids=["unknown_operand", "cycle", "unsummable_operand", "unknown_kind",
         "summable_rate", "wrong_arity"],
)
def test_each_rule_fires_on_the_shipped_sheet_broken_that_way(
    what: str, broken, signature: str  # type: ignore[no-untyped-def]
) -> None:
    """One rule per breakage, and exactly one finding each.

    "Exactly one" is the half worth asserting. A lint that reports six findings
    for one mistake teaches an author to skim it, and every rule here is written
    to fire on its own defect and no other's.
    """
    findings = columns.lint(broken())
    assert len(findings) == 1, f"{what}: {findings}"
    assert signature in findings[0], findings[0]


# ---------------------------------------------------------------------------
# Refused at construction
# ---------------------------------------------------------------------------


def test_a_column_that_reads_no_fact_kind_is_refused() -> None:
    """The surviving half of "never neither".

    `_measure_row` indexes the kind table by column key, so a column with no
    kind is a `KeyError` raised inside the compiler, a long way from the sheet
    that caused it.
    """
    with pytest.raises(ValueError, match="reads no fact kind"):
        columns.ColumnSpec(key="gm_pct_forecast", label="GM% forecast", kind="")


def test_a_sheet_that_declares_one_column_twice_is_refused() -> None:
    """Every projection is keyed by column key.

    A duplicate does not make a wrong sheet, it makes a sheet whose kind table
    and column list disagree about how many columns there are — so it is
    refused rather than reported.
    """
    with pytest.raises(ValueError, match="twice"):
        columns.Sheet(
            name="doubled",
            columns=(columns.PNL.columns[0], columns.PNL.columns[0]),
        )


def test_selecting_a_column_the_sheet_does_not_have_is_refused() -> None:
    with pytest.raises(ValueError, match="no column 'ebitda'"):
        columns.PNL.select("revenue_actual", "ebitda")


# ---------------------------------------------------------------------------
# Why the rules are worth having
# ---------------------------------------------------------------------------


def test_a_summable_margin_validates_clean_and_lies_to_a_spreadsheet() -> None:
    """The measurement behind the non-summing rule, on a real corpus.

    Make the actual-margin column summable — one flag, the shape of an author's
    plausible mistake — and the group row of the Business Unit P&L declares
    itself the sum of the three divisions' margin *rates*. The literal value is
    still the ledger's, so Markdown, Word and PDF all print 24.52 and
    `worldloom validate` passes every one of its checks. Excel reads the
    declaration instead and computes 75.15.

    That is the whole argument for the rule: the defect is invisible to every
    check this repository has, visible only in the format the workbook exists
    to be, and catchable at the declaration.
    """
    assert columns.lint(_with(columns.PNL, "gm_pct_actual", summable=True)) != []

    original = documents._NOT_ADDITIVE
    documents._NOT_ADDITIVE = frozenset()
    try:
        world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
        report = world.validate()
    finally:
        documents._NOT_ADDITIVE = original

    assert report.ok, report.violations[:3]

    disagreements = []
    for ir in world.artifact_irs:
        for section in ir.sections:
            table = section.table
            if table is None or table.key != "pnl":
                continue
            rows = {row.key: row for row in table.rows}
            for row in table.rows:
                cell = row.cells.get("gm_pct_actual")
                if cell is None or cell.formula is not FormulaKind.SUM:
                    continue
                spreadsheet = sum(
                    rows[child].cells["gm_pct_actual"].value or 0.0
                    for child in cell.operands
                    if child in rows
                )
                disagreements.append((cell.value, spreadsheet))

    assert disagreements, "the fixture must have a subtotal row on the margin column"
    for stated, spreadsheet in disagreements:
        assert spreadsheet > stated * 2, (stated, spreadsheet)


def test_the_lint_would_have_caught_the_defect_the_module_was_written_after() -> None:
    """`gm_pct_budget`'s 114 facts a build, carried by nothing.

    The column was simply absent, which no lint over a sheet can see — the
    sheet was consistent, it was just short. What *is* catchable is the near
    miss that produces the same outcome: the column present, reading a kind
    nothing mints. That is the version of the defect this file can refuse, and
    it is the version an author writing a new sheet will actually make.
    """
    findings = columns.lint(
        _with(columns.PNL, "gm_pct_budget", kind="financial.gross_margin_pct.plan")
    )
    assert any("no generator in this process declares" in f for f in findings), findings


def test_every_declared_sheet_is_linted_by_something_that_takes_no_argument() -> None:
    """`columns.findings()` over the whole module, `doctypes.audit`'s argument.

    A check that has to be pointed at the thing it checks gets pointed at the
    wrong thing — so a sheet added to this module later is linted by this test
    without anybody remembering to add it here.
    """
    report = columns.findings()
    assert set(report) == {sheet.name for sheet in columns.sheets()}
    # Empty since the divisional cut's margin ratio got its numerator column —
    # `divisions` was the one shipped sheet with a standing finding.
    assert [name for name, found in report.items() if found] == []


def test_documents_still_builds_the_pnl_columns_from_the_declaration() -> None:
    """The consumption is real, not a parallel copy that happens to agree."""
    original = columns.PNL
    try:
        columns_module_pnl = _with(original, "gp_budget", label="Budgeted GP")
        columns.PNL = columns_module_pnl  # type: ignore[misc]
        rebuilt: list[Column] = documents._pnl_columns()
    finally:
        columns.PNL = original  # type: ignore[misc]
    assert [c.label for c in rebuilt][3] == "Budgeted GP"
