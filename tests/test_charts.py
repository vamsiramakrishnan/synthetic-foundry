"""Charts, declared in the IR rather than drawn by each renderer.

Same principle as formulas, for the same reason. A workbook, a document and a deck
all show "revenue by division"; if each renderer picked its own rows and series
they would be three charts of three different things wearing one title. The IR
declares which table, which rows, which series, and a renderer decides only how to
draw it.

The checks that matter here are the ones about *which rows* — a chart that
included subtotals alongside the rows they total would plot the same money twice,
and it would look perfectly fine.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.models import ChartKind, FormulaKind
from worldloom.render import markdown

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def workbook() -> World:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True, comparative_months=3)
    )
    return world.compile()


def _ir(world: World):  # type: ignore[no-untyped-def]
    return next(ir for ir in world.artifact_irs if ir.tables() and ir.tables()[0].key == "summary")


def test_the_workbook_declares_charts(workbook: World) -> None:
    charts = {chart.key for chart in _ir(workbook).charts()}
    assert {"pnl_revenue", "pnl_margin", "category_variance", "trend_units"} <= charts


def test_every_chart_resolves_against_its_own_table(workbook: World) -> None:
    """The check the validator runs, asserted directly so its failure is legible."""
    ir = _ir(workbook)
    tables = {table.key: table for table in ir.tables()}
    for chart in ir.charts():
        table = tables[chart.table]
        columns = {column.key for column in table.columns}
        rows = {row.key for row in table.rows}
        assert set(chart.series) <= columns, chart.key
        assert set(chart.rows) <= rows, chart.key
        assert chart.series, f"{chart.key} plots nothing"


def test_a_chart_never_plots_a_total_beside_its_own_parts(workbook: World) -> None:
    """The failure that looks correct.

    A chart of four divisions plus the group puts one bar four times the height of
    the rest beside them; a chart of categories plus their unit subtotals plots the
    same money twice. Neither raises, and both look fine.

    Note that plotting a subtotal is not itself the error — the trend chart plots
    one line per division, and a division is a subtotal of its categories. The
    error is plotting a total *together with the rows that total into it*, which
    the IR can answer exactly: a summing cell names its children as operands.
    """
    ir = _ir(workbook)
    tables = {table.key: table for table in ir.tables()}
    for chart in ir.charts():
        table = tables[chart.table]
        plotted = set(chart.rows)
        for row in table.rows:
            if row.key not in plotted:
                continue
            children = {
                operand
                for cell in row.cells.values()
                if cell.formula is FormulaKind.SUM
                for operand in cell.operands
            }
            overlap = children & plotted
            assert not overlap, (
                f"{chart.key} plots {row.key} and its own parts {sorted(overlap)} — "
                "the same money twice"
            )


def test_a_line_chart_is_only_used_where_the_axis_is_ordered(workbook: World) -> None:
    """A line between unordered categories asserts a trend that does not exist."""
    for chart in _ir(workbook).charts():
        if chart.kind is ChartKind.LINE:
            assert chart.table == "trend", f"{chart.key} draws a line over {chart.table}"


def test_a_broken_chart_reference_is_caught(workbook: World) -> None:
    """The validator has to be able to fail, or it is decoration.

    A chart naming a column that does not exist draws an empty series rather than
    raising: the file opens, the chart is there, and it is blank.
    """
    ir = _ir(workbook)
    sections = list(ir.sections)
    index, section = next(
        (i, s) for i, s in enumerate(sections) if s.charts
    )
    broken = section.charts[0].model_copy(update={"series": ["no_such_column"]})
    sections[index] = section.model_copy(update={"charts": [broken]})
    damaged = World(
        **{**workbook.__dict__, "_artifact_irs": (ir.model_copy(update={"sections": sections}),)}
    )

    report = damaged.validate()
    assert any(v.code == "chart_series_missing" for v in report.violations), report.violations[:3]


def test_a_chart_over_a_missing_table_is_caught(workbook: World) -> None:
    ir = _ir(workbook)
    sections = list(ir.sections)
    index, section = next((i, s) for i, s in enumerate(sections) if s.charts)
    broken = section.charts[0].model_copy(update={"table": "no_such_table"})
    sections[index] = section.model_copy(update={"charts": [broken]})
    damaged = World(
        **{**workbook.__dict__, "_artifact_irs": (ir.model_copy(update={"sections": sections}),)}
    )

    assert any(v.code == "chart_table_missing" for v in damaged.validate().violations)


def test_markdown_names_the_chart_rather_than_approximating_it(workbook: World) -> None:
    """Markdown cannot draw one, and an ASCII approximation would be a second
    rendering of the same data that could disagree with the table above it."""
    body = markdown.render(_ir(workbook)).decode()
    for chart in _ir(workbook).charts():
        assert f"**Figure — {chart.title}**" in body


def test_a_section_without_charts_still_reads_correctly(workbook: World) -> None:
    """Regression: a `for` between the `elif` and the `else` binds the `else` to
    the loop, and Python runs a loop-else whenever the loop did not break — so
    every chartless section grew an "awaiting narrative" notice under its table."""
    body = markdown.render(_ir(workbook)).decode()
    assert "Awaiting narrative" not in body
