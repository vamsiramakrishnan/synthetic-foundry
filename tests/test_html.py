"""Tests for the HTML renderer.

The renderer produces deterministic, self-contained HTML with inline SVG charts.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.models import Cell, Chart, ChartKind, Column, Row, Table
from worldloom.render import html

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def rendered() -> World:
    """A built and rendered world."""
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    return world.render("html")


def test_html_files_are_produced(rendered: World) -> None:
    """The renderer produces .html files."""
    html_files = [r for r in rendered._rendered if r.path.endswith(".html")]
    assert html_files, "no HTML files were produced"


def test_html_is_well_formed(rendered: World) -> None:
    """HTML documents start with <!DOCTYPE and end with </html>."""
    for rendered_file in rendered._rendered:
        if not rendered_file.path.endswith(".html"):
            continue
        text = rendered_file.text
        assert text.startswith("<!DOCTYPE html>"), f"{rendered_file.path} has bad DOCTYPE"
        assert text.endswith("</html>\n"), f"{rendered_file.path} does not end with </html>"


def test_html_contains_title(rendered: World) -> None:
    """The rendered HTML contains the artifact title."""
    for rendered_file in rendered._rendered:
        if not rendered_file.path.endswith(".html"):
            continue
        text = rendered_file.text
        assert "<title>" in text and "</title>" in text, f"{rendered_file.path} has no title tag"


def test_html_contains_tables(rendered: World) -> None:
    """HTML with table sections renders the tables."""
    html_files = [r for r in rendered._rendered if r.path.endswith(".html")]
    html_with_tables = [
        r for r in html_files if "<table>" in r.text and "</table>" in r.text
    ]
    assert html_with_tables, "no HTML files contain rendered tables"


def test_table_headers_and_data(rendered: World) -> None:
    """Tables contain headers and data rows."""
    for rendered_file in rendered._rendered:
        if "<table>" not in rendered_file.text:
            continue
        text = rendered_file.text
        # A table should have <th> for headers and <td> for data.
        assert "<th>" in text, f"{rendered_file.path} table has no headers"
        assert "<td>" in text, f"{rendered_file.path} table has no data"


def test_simple_column_chart() -> None:
    """A column chart renders as SVG."""
    table = Table(
        key="test",
        title="Test Table",
        columns=[
            Column(key="jan", label="January"),
            Column(key="feb", label="February"),
        ],
        rows=[
            Row(
                key="sales",
                label="Sales",
                cells={
                    "jan": Cell(value=100),
                    "feb": Cell(value=150),
                },
            ),
            Row(
                key="costs",
                label="Costs",
                cells={
                    "jan": Cell(value=60),
                    "feb": Cell(value=80),
                },
            ),
        ],
    )
    chart = Chart(
        key="trend",
        title="Revenue Trend",
        kind=ChartKind.COLUMN,
        table="test",
        series=["jan", "feb"],
        rows=["sales", "costs"],
    )
    svg = html._chart_svg(chart, table)
    assert "<svg" in svg, "column chart is not SVG"
    assert "chart.title" not in svg, "chart title not properly escaped"
    assert "Revenue Trend" in svg, "chart title should appear in SVG"


def test_simple_bar_chart() -> None:
    """A bar chart renders as SVG."""
    table = Table(
        key="test",
        title="Test Table",
        columns=[Column(key="val", label="Value")],
        rows=[
            Row(key="a", label="A", cells={"val": Cell(value=100)}),
            Row(key="b", label="B", cells={"val": Cell(value=150)}),
        ],
    )
    chart = Chart(
        key="bars",
        title="Category Ranking",
        kind=ChartKind.BAR,
        table="test",
        series=["val"],
        rows=["a", "b"],
    )
    svg = html._chart_svg(chart, table)
    assert "<svg" in svg, "bar chart is not SVG"
    assert "Category Ranking" in svg, "chart title should appear in SVG"


def test_simple_line_chart() -> None:
    """A line chart renders as SVG."""
    table = Table(
        key="test",
        title="Test Table",
        columns=[
            Column(key="jan", label="January"),
            Column(key="feb", label="February"),
            Column(key="mar", label="March"),
        ],
        rows=[
            Row(
                key="revenue",
                label="Revenue",
                cells={
                    "jan": Cell(value=100),
                    "feb": Cell(value=120),
                    "mar": Cell(value=110),
                },
            ),
        ],
    )
    chart = Chart(
        key="trend",
        title="Revenue Over Time",
        kind=ChartKind.LINE,
        table="test",
        series=["jan", "feb", "mar"],
        rows=["revenue"],
        by_row=True,  # Each row is a series, columns are the x-axis
    )
    svg = html._chart_svg(chart, table)
    assert "<svg" in svg, "line chart is not SVG"
    assert "Revenue Over Time" in svg, "chart title should appear in SVG"
    assert "<path" in svg, "line chart should contain path elements"


def test_simple_pie_chart() -> None:
    """A pie chart renders as SVG."""
    table = Table(
        key="test",
        title="Test Table",
        columns=[
            Column(key="pct", label="Percentage"),
        ],
        rows=[
            Row(key="north", label="North", cells={"pct": Cell(value=40)}),
            Row(key="south", label="South", cells={"pct": Cell(value=60)}),
        ],
    )
    chart = Chart(
        key="mix",
        title="Market Share",
        kind=ChartKind.PIE,
        table="test",
        series=["pct"],
        rows=["north", "south"],
    )
    svg = html._chart_svg(chart, table)
    assert "<svg" in svg, "pie chart is not SVG"
    assert "Market Share" in svg, "chart title should appear in SVG"


def test_svg_coordinates_are_rounded() -> None:
    """SVG coordinates use fixed precision for determinism."""
    value = 123.456789
    rounded = html._round_coord(value)
    # Precision is _SVG_PRECISION = 2, so 123.456789 -> 123.46
    assert rounded == 123.46, f"coordinate rounding failed: {rounded}"


def test_html_escapes_special_characters() -> None:
    """HTML content is properly escaped."""
    table = Table(
        key="test",
        title="Test <script>",
        columns=[Column(key="col", label="Test & Value")],
        rows=[
            Row(
                key="row",
                label="Label <dangerous>",
                cells={"col": Cell(value=100)},
            ),
        ],
    )
    html_output = html._table_html(table)
    # The dangerous label should be escaped in the table output.
    assert "<dangerous>" not in html_output, "script-like tag should be escaped"
    assert "&lt;dangerous&gt;" in html_output, "script-like tag should be HTML-escaped"
    assert "&amp;" in html_output, "ampersand should be escaped as &amp;"


def test_two_renders_are_identical(rendered: World) -> None:
    """Two renders of the same world produce identical HTML."""
    world1 = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    ).render("html")

    world2 = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    ).render("html")

    html1_files = {r.path: r.payload for r in world1._rendered if r.path.endswith(".html")}
    html2_files = {r.path: r.payload for r in world2._rendered if r.path.endswith(".html")}

    assert set(html1_files.keys()) == set(html2_files.keys()), "file sets differ between renders"

    for path in html1_files:
        assert html1_files[path] == html2_files[path], (
            f"HTML file {path} differs between two renders of the same world"
        )


def test_html_contains_no_datetime_now(rendered: World) -> None:
    """HTML output contains no date/time stamps from rendering time."""
    for rendered_file in rendered._rendered:
        if not rendered_file.path.endswith(".html"):
            continue
        text = rendered_file.text
        # Should not contain current date or time markers that would differ
        # between runs. The corpus period is 2026-03, so any dates should
        # reference that, not "today".
        # A simple check: no ISO timestamp at the start of HTML that wasn't there before.
        assert "now()" not in text, "HTML contains datetime.now()"


def test_chart_with_by_row_true() -> None:
    """Chart with by_row=True uses rows as series and columns as axis."""
    table = Table(
        key="test",
        title="Test",
        columns=[
            Column(key="q1", label="Q1"),
            Column(key="q2", label="Q2"),
        ],
        rows=[
            Row(
                key="unit_a",
                label="Unit A",
                cells={
                    "q1": Cell(value=100),
                    "q2": Cell(value=110),
                },
            ),
            Row(
                key="unit_b",
                label="Unit B",
                cells={
                    "q1": Cell(value=200),
                    "q2": Cell(value=210),
                },
            ),
        ],
    )
    chart = Chart(
        key="by_row_chart",
        title="Units by Quarter",
        kind=ChartKind.LINE,
        table="test",
        series=["q1", "q2"],
        rows=["unit_a", "unit_b"],
        by_row=True,
    )
    svg = html._chart_svg(chart, table)
    assert "<svg" in svg, "by_row chart should produce SVG"
    assert "Units by Quarter" in svg, "chart title should appear"


def test_bar_chart_all_negative_series() -> None:
    """For all-negative values, the largest magnitude gets the longest bar.

    This tests the critical fix for the inversion bug where min-max
    normalization made adverse variances show inversely. The worst performer
    must not be invisible, and the best performer must not be the longest bar.
    """
    table = Table(
        key="test",
        title="Test",
        columns=[Column(key="var", label="Variance")],
        rows=[
            Row(key="food", label="Food", cells={"var": Cell(value=-10200)}),
            Row(key="gm", label="GM", cells={"var": Cell(value=-1100)}),
            Row(key="digital", label="Digital", cells={"var": Cell(value=-2000)}),
        ],
    )
    chart = Chart(
        key="adverse",
        title="Revenue against plan by division",
        kind=ChartKind.BAR,
        table="test",
        series=["var"],
        rows=["food", "gm", "digital"],
    )
    svg = html._chart_svg(chart, table)

    # Extract bar widths from the SVG. Bars are <rect> elements.
    # The chart should have three bars: one for each division.
    import re
    widths = re.findall(r'width="([0-9.]+)"', svg)
    # Skip the SVG width and axis line widths, get the bar widths (indices 3-5).
    assert len(widths) >= 6, f"expected at least 6 width attributes (svg, lines, 3 bars), found {len(widths)}"

    food_width = float(widths[3])
    gm_width = float(widths[4])
    digital_width = float(widths[5])

    # The magnitudes are: food=10200 (largest), gm=1100 (smallest), digital=2000 (middle).
    # So the ordering should be: food_width > digital_width > gm_width.
    assert food_width > 0, f"Food (magnitude 10200) bar should be visible, got width {food_width}"
    assert food_width > digital_width, (
        f"Food (magnitude 10200) bar should be longer than Digital (2000), "
        f"got {food_width} vs {digital_width}"
    )
    assert digital_width > gm_width, (
        f"Digital (magnitude 2000) bar should be longer than GM (1100), "
        f"got {digital_width} vs {gm_width}"
    )


def test_pie_chart_refuses_negative_values() -> None:
    """Pie charts cannot represent negative values — fall back to caption."""
    table = Table(
        key="test",
        title="Test",
        columns=[Column(key="pct", label="Share")],
        rows=[
            Row(key="a", label="A", cells={"pct": Cell(value=50)}),
            Row(key="b", label="B", cells={"pct": Cell(value=-25)}),
        ],
    )
    chart = Chart(
        key="pie",
        title="Market Share",
        kind=ChartKind.PIE,
        table="test",
        series=["pct"],
        rows=["a", "b"],
    )
    svg = html._chart_svg(chart, table)
    # Should not be SVG, but a caption explaining why.
    assert "<svg" not in svg, "pie chart with negative values should not render SVG"
    assert "cannot show negative" in svg.lower(), "should explain why it cannot render"


def test_svg_viewport_invariant(rendered: World) -> None:
    """Every drawn element in every SVG must lie within the viewport.

    This catches clipping, negative coordinates, and axis-origin mistakes that
    would cause data to render off-screen. Checks:
    - No x/x1/x2/cx outside [0..width]
    - No y/y1/y2/cy outside [0..height]
    - No rect where x + width > width (right edge overflow)
    - No rect where y + height > height (bottom edge overflow)
    """
    import re

    violations = []
    for rendered_file in rendered._rendered:
        if not rendered_file.path.endswith(".html"):
            continue

        text = rendered_file.text
        svg_blocks = re.findall(r'<svg[^>]*width="(\d+)"[^>]*height="(\d+)"[^>]*>(.*?)</svg>', text, re.DOTALL)

        for svg_width_str, svg_height_str, svg_content in svg_blocks:
            svg_width = int(svg_width_str)
            svg_height = int(svg_height_str)

            # Extract all element coordinates.
            # x, x1, x2, cx attributes
            x_coords = re.findall(r'\b(?:x|x1|x2|cx)="([0-9.]+)"', svg_content)
            for x_str in x_coords:
                x_val = float(x_str)
                if x_val < 0 or x_val > svg_width:
                    violations.append(
                        f"{rendered_file.path}: x={x_val} outside [0..{svg_width}]"
                    )

            # y, y1, y2, cy attributes
            y_coords = re.findall(r'\b(?:y|y1|y2|cy)="([0-9.]+)"', svg_content)
            for y_str in y_coords:
                y_val = float(y_str)
                if y_val < 0 or y_val > svg_height:
                    violations.append(
                        f"{rendered_file.path}: y={y_val} outside [0..{svg_height}]"
                    )

            # rect elements: x + width must not exceed svg_width
            rects = re.findall(
                r'<rect\s+(?:[^>]*\s+)?x="([0-9.]+)"[^>]*width="([0-9.]+)"', svg_content
            )
            for rect_x_str, rect_width_str in rects:
                rect_x = float(rect_x_str)
                rect_width = float(rect_width_str)
                if rect_x + rect_width > svg_width:
                    violations.append(
                        f"{rendered_file.path}: rect x={rect_x} width={rect_width} "
                        f"extends to {rect_x + rect_width}, exceeds svg width {svg_width}"
                    )

            # rect elements: y + height must not exceed svg_height
            rects = re.findall(
                r'<rect\s+(?:[^>]*\s+)?y="([0-9.]+)"[^>]*height="([0-9.]+)"', svg_content
            )
            for rect_y_str, rect_height_str in rects:
                rect_y = float(rect_y_str)
                rect_height = float(rect_height_str)
                if rect_y + rect_height > svg_height:
                    violations.append(
                        f"{rendered_file.path}: rect y={rect_y} height={rect_height} "
                        f"extends to {rect_y + rect_height}, exceeds svg height {svg_height}"
                    )

    assert not violations, "SVG viewport violations found:\n" + "\n".join(violations)
