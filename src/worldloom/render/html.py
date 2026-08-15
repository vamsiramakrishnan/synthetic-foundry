"""The HTML renderer.

Renders charts as inline SVG, with deterministic, self-contained output. No
external stylesheets, CDN scripts, or web fonts. Every value plotted must
reference a cell in the section's table — charts never introduce numbers.

SVG coordinates are rounded to a fixed number of decimals for deterministic
output across platforms.
"""

from __future__ import annotations

import html
import math
from typing import TYPE_CHECKING

from ..locales import DEFAULT as DEFAULT_LOCALE
from ..locales import Locale
from ..models import ArtifactIR, CanonicalFact, Chart, ChartKind, Table
from ..narrative import references
from ..presentation import DEFAULT as DEFAULT_PRESENTATION
from ..presentation import Presentation
from ..presentation import of as presentation_of
from . import Rendered, slug_for
from .values import corpus_locale, format_value

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World


# SVG coordinate precision: round to this many decimals for determinism.
_SVG_PRECISION = 2


def _round_coord(value: float) -> float:
    """Round a coordinate to fixed decimals for deterministic SVG output."""
    factor = 10 ** _SVG_PRECISION
    return round(value * factor) / factor


def _table_html(table: Table, locale: Locale = DEFAULT_LOCALE) -> str:
    """One table as HTML."""
    rows = []

    # Header row
    header_cells = ["<th></th>"]
    for column in table.columns:
        header_cells.append(f"<th>{html.escape(column.label)}</th>")
    rows.append("<tr>" + "".join(header_cells) + "</tr>")

    # Data rows
    for row in table.rows:
        cells = []
        label_class = ' class="emphasis"' if row.emphasis else ""
        cells.append(f"<td{label_class}><strong>{html.escape(row.label)}</strong></td>")

        for column in table.columns:
            cell = row.cells.get(column.key)
            text = format_value(cell.value, column.number_format, locale=locale) if cell else ""
            cell_class = ' class="emphasis"' if row.emphasis and text else ""
            if row.emphasis and text:
                cells.append(f"<td{cell_class}><strong>{html.escape(text)}</strong></td>")
            else:
                cells.append(f"<td>{html.escape(text)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")

    table_html = "<table>\n" + "\n".join(f"  {row}" for row in rows) + "\n</table>"

    if table.note:
        table_html += f"\n<p class=\"note\"><em>{html.escape(table.note)}</em></p>"

    return table_html


def _chart_svg(chart: Chart, table: Table | None) -> str:
    """One chart as inline SVG.

    Every value plotted must come from a cell in the table. A chart that
    introduced a number would be a second rendering of the data that could
    disagree with the table above it.
    """
    if not table:
        # No table to draw from — fall back to a caption.
        labels = [key for key in chart.series]
        return (
            f"<p><strong>Figure — {html.escape(chart.title)}</strong> "
            f"<em>(no table for {chart.kind.value} chart)</em></p>"
        )

    # Determine which rows and series to plot.
    if chart.by_row:
        # Each row is a series, columns are the axis.
        series_keys = chart.rows if chart.rows else [
            r.key for r in table.rows if not r.emphasis
        ]
        axis_keys = chart.series
        axis_labels = [
            (table.column(key).label if table.column(key) else key)
            for key in axis_keys
        ]
    else:
        # Each column is a series, rows are the axis.
        series_keys = chart.series
        axis_keys = chart.rows if chart.rows else [
            r.key for r in table.rows if not r.emphasis
        ]
        axis_labels = [
            (table.row(key).label if table.row(key) else key)
            for key in axis_keys
        ]

    # Extract data points: series_key -> [values]
    data: dict[str, list[float | None]] = {key: [] for key in series_keys}

    for axis_key in axis_keys:
        if chart.by_row:
            # Reading across columns for each row.
            for series_key in series_keys:
                row = table.row(series_key)
                cell = row.cells.get(axis_key) if row else None
                value = float(cell.value) if cell and cell.value is not None else None
                data[series_key].append(value)
        else:
            # Reading down rows for each column.
            for series_key in series_keys:
                column = table.column(series_key)
                row = table.row(axis_key)
                cell = row.cells.get(series_key) if row and column else None
                value = float(cell.value) if cell and cell.value is not None else None
                data[series_key].append(value)

    # Delegate to chart-kind-specific renderers.
    if chart.kind == ChartKind.COLUMN:
        return _chart_column(chart, data, axis_labels, series_keys)
    elif chart.kind == ChartKind.BAR:
        return _chart_bar(chart, data, axis_labels, series_keys)
    elif chart.kind == ChartKind.LINE:
        return _chart_line(chart, data, axis_labels, series_keys)
    elif chart.kind == ChartKind.PIE:
        return _chart_pie(chart, data, series_keys)
    else:
        # Fallback for unknown kinds.
        labels = [
            (table.column(key).label if table and table.column(key) else key)
            for key in chart.series
        ]
        return (
            f"<p><strong>Figure — {html.escape(chart.title)}</strong> "
            f"<em>({chart.kind.value} chart of {', '.join(html.escape(label) for label in labels)})</em></p>"
        )


def _chart_column(
    chart: Chart,
    data: dict[str, list[float | None]],
    axis_labels: list[str],
    series_keys: list[str],
) -> str:
    """Render a column (vertical bar) chart as SVG.

    Bar height is measured from zero, not from the series minimum. This ensures
    the longest bar represents the largest magnitude and negative values render
    with real height. When the series spans both positive and negative values,
    zero is placed in the middle of the chart.
    """
    if not data or not axis_labels:
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong></p>"

    # Chart dimensions.
    width, height = 600, 400
    margin = {"top": 40, "right": 20, "bottom": 60, "left": 60}
    chart_width = width - margin["left"] - margin["right"]
    chart_height = height - margin["top"] - margin["bottom"]

    # Find data bounds.
    all_values = [v for series in data.values() for v in series if v is not None]
    if not all_values:
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong></p>"

    min_value = min(all_values)
    max_value = max(all_values)

    # For bar/column, measure from zero, not from min. This handles negatives correctly.
    # Calculate the max absolute value to use as the scale basis.
    abs_max = max(abs(min_value), abs(max_value))
    if abs_max == 0:
        abs_max = 1

    # Position of zero line within the chart. Three cases:
    # 1. All non-negative: zero at bottom
    # 2. All non-positive: zero at top
    # 3. Mixed: zero partway up, proportional to the ranges
    if min_value >= 0:
        # All non-negative: zero at bottom
        zero_y = margin["top"] + chart_height
    elif max_value <= 0:
        # All non-positive: zero at top
        zero_y = margin["top"]
    else:
        # Mixed signs: zero partway through, proportional to ranges
        # Position: plot_top + |max| / (|min| + |max|) * plot_height
        zero_y = margin["top"] + (abs(max_value) / (abs(min_value) + abs(max_value))) * chart_height

    # Scales: bars are drawn from zero outward based on max absolute value.
    x_scale = chart_width / len(axis_labels)
    y_scale = chart_height / abs_max  # Scale based on max absolute value for correct proportions

    # Build SVG.
    svg_parts = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        "<defs><style>",
        ".chart-text { font-family: sans-serif; font-size: 12px; }",
        ".chart-label { font-size: 11px; }",
        ".series-0 { fill: #2563eb; }",
        ".series-1 { fill: #dc2626; }",
        ".series-2 { fill: #16a34a; }",
        ".series-3 { fill: #ea580c; }",
        "</style></defs>",
    ]

    # Y-axis.
    svg_parts.append(
        f'<line x1="{_round_coord(margin["left"])}" y1="{_round_coord(margin["top"])}" '
        f'x2="{_round_coord(margin["left"])}" y2="{_round_coord(margin["top"] + chart_height)}" '
        'stroke="black" stroke-width="1"/>'
    )

    # X-axis (at zero or bottom).
    axis_y = zero_y if max_value > 0 and min_value < 0 else margin["top"] + chart_height
    svg_parts.append(
        f'<line x1="{_round_coord(margin["left"])}" y1="{_round_coord(axis_y)}" '
        f'x2="{_round_coord(margin["left"] + chart_width)}" y2="{_round_coord(axis_y)}" '
        'stroke="black" stroke-width="1"/>'
    )

    # Y-axis labels (grid lines and tick labels). Position based on zero location.
    num_ticks = 5
    for i in range(num_ticks + 1):
        tick_value = min_value + ((max_value - min_value) / num_ticks) * i
        # Position tick based on distance from zero, not from min.
        if tick_value >= 0:
            y = zero_y - (tick_value / abs_max) * chart_height
        else:
            y = zero_y + (abs(tick_value) / abs_max) * chart_height
        y_rounded = _round_coord(y)
        svg_parts.append(
            f'<line x1="{_round_coord(margin["left"] - 5)}" y1="{y_rounded}" '
            f'x2="{_round_coord(margin["left"])}" y2="{y_rounded}" '
            'stroke="black" stroke-width="1"/>'
        )
        tick_text = format_value(tick_value, None, locale=DEFAULT_LOCALE)
        svg_parts.append(
            f'<text x="{_round_coord(margin["left"] - 10)}" y="{y_rounded + 3}" '
            f'text-anchor="end" class="chart-text chart-label">{html.escape(tick_text)}</text>'
        )

    # Bars. Height measured from zero line, positioned at correct value.
    num_series = len(series_keys)
    bar_width = x_scale / (num_series + 1)
    for series_idx, series_key in enumerate(series_keys):
        values = data[series_key]
        for col_idx, value in enumerate(values):
            if value is None:
                continue
            x = margin["left"] + (col_idx + 0.5) * x_scale + (series_idx - num_series / 2 + 0.5) * bar_width
            # Bar height from value to zero line.
            bar_height = abs(value - 0) * y_scale if max_value > min_value else 0
            # Y position: if value is above zero, bar goes up from zero. If below, bar goes down.
            if value >= 0:
                y = zero_y - bar_height
            else:
                y = zero_y
            svg_parts.append(
                f'<rect x="{_round_coord(x)}" y="{_round_coord(y)}" '
                f'width="{_round_coord(bar_width)}" height="{_round_coord(bar_height)}" '
                f'class="series-{series_idx % 4}"/>'
            )

    # X-axis labels.
    for col_idx, label in enumerate(axis_labels):
        x = margin["left"] + (col_idx + 0.5) * x_scale
        y = margin["top"] + chart_height + 20
        svg_parts.append(
            f'<text x="{_round_coord(x)}" y="{_round_coord(y)}" '
            'text-anchor="middle" class="chart-text chart-label">'
            f'{html.escape(label)}</text>'
        )

    # Title.
    svg_parts.append(
        f'<text x="{_round_coord(width / 2)}" y="{_round_coord(margin["top"] - 10)}" '
        'text-anchor="middle" class="chart-text" style="font-weight: bold;">'
        f'{html.escape(chart.title)}</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _chart_bar(
    chart: Chart,
    data: dict[str, list[float | None]],
    axis_labels: list[str],
    series_keys: list[str],
) -> str:
    """Render a bar (horizontal bar) chart as SVG.

    Bar width is measured from zero, not from the series minimum. This ensures
    the longest bar represents the largest magnitude and negative values render
    with real width.
    """
    if not data or not axis_labels:
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong></p>"

    # Chart dimensions.
    width, height = 600, 400
    margin = {"top": 40, "right": 20, "bottom": 20, "left": 200}
    chart_width = width - margin["left"] - margin["right"]
    chart_height = height - margin["top"] - margin["bottom"]

    # Find data bounds.
    all_values = [v for series in data.values() for v in series if v is not None]
    if not all_values:
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong></p>"

    min_value = min(all_values)
    max_value = max(all_values)

    # For bar/column charts, bars measure from zero (not from the series minimum).
    # Calculate the max absolute value to use as the scale basis.
    max_abs = max(abs(min_value), abs(max_value))
    if max_abs == 0:
        max_abs = 1

    # Position of zero line within the chart. Three cases:
    # 1. All negative: zero at right edge, bars extend left
    # 2. All positive: zero at left edge, bars extend right
    # 3. Mixed: zero in middle, proportional to the ranges
    if min_value >= 0:
        # All non-negative: zero at left edge
        zero_x = margin["left"]
    elif max_value <= 0:
        # All non-positive: zero at right edge
        zero_x = margin["left"] + chart_width
    else:
        # Mixed signs: zero partway through, proportional to ranges
        # Position: plot_left + |min| / (|min| + |max|) * plot_width
        zero_x = margin["left"] + (abs(min_value) / (abs(min_value) + abs(max_value))) * chart_width

    # Scales: bars are drawn from zero outward based on max absolute value.
    y_scale = chart_height / len(axis_labels)
    x_scale = chart_width / max_abs  # Scale based on max absolute value for correct proportions

    # Build SVG.
    svg_parts = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        "<defs><style>",
        ".chart-text { font-family: sans-serif; font-size: 12px; }",
        ".chart-label { font-size: 11px; }",
        ".series-0 { fill: #2563eb; }",
        ".series-1 { fill: #dc2626; }",
        ".series-2 { fill: #16a34a; }",
        ".series-3 { fill: #ea580c; }",
        "</style></defs>",
    ]

    # Y-axis (vertical, at left edge).
    svg_parts.append(
        f'<line x1="{_round_coord(margin["left"])}" y1="{_round_coord(margin["top"])}" '
        f'x2="{_round_coord(margin["left"])}" y2="{_round_coord(margin["top"] + chart_height)}" '
        'stroke="black" stroke-width="1"/>'
    )

    # X-axis (horizontal, at zero or right edge).
    axis_x = zero_x if max_value > 0 and min_value < 0 else margin["left"]
    svg_parts.append(
        f'<line x1="{_round_coord(axis_x)}" y1="{_round_coord(margin["top"] + chart_height)}" '
        f'x2="{_round_coord(margin["left"] + chart_width)}" y2="{_round_coord(margin["top"] + chart_height)}" '
        'stroke="black" stroke-width="1"/>'
    )

    # Bars. Width measured from zero line, positioned at correct value.
    num_series = len(series_keys)
    bar_height = y_scale / (num_series + 1)
    for series_idx, series_key in enumerate(series_keys):
        values = data[series_key]
        for row_idx, value in enumerate(values):
            if value is None:
                continue
            # Bar width from zero to value.
            bar_width = abs(value - 0) * x_scale if max_value > min_value else 0
            y = margin["top"] + (row_idx + 0.5) * y_scale + (series_idx - num_series / 2 + 0.5) * bar_height
            # X position: if value is positive, bar goes right from zero. If negative, bar goes left.
            if value >= 0:
                x = zero_x
            else:
                x = zero_x - bar_width
            svg_parts.append(
                f'<rect x="{_round_coord(x)}" y="{_round_coord(y)}" '
                f'width="{_round_coord(bar_width)}" height="{_round_coord(bar_height)}" '
                f'class="series-{series_idx % 4}"/>'
            )

    # Y-axis labels.
    for row_idx, label in enumerate(axis_labels):
        y = margin["top"] + (row_idx + 0.5) * y_scale
        svg_parts.append(
            f'<text x="{_round_coord(margin["left"] - 10)}" y="{_round_coord(y + 4)}" '
            'text-anchor="end" class="chart-text chart-label">'
            f'{html.escape(label)}</text>'
        )

    # X-axis labels (ticks). Position based on zero location.
    num_ticks = 5
    for i in range(num_ticks + 1):
        tick_value = min_value + ((max_value - min_value) / num_ticks) * i
        # Position tick based on distance from zero, not from min.
        if tick_value >= 0:
            x = zero_x + (tick_value / max_abs) * chart_width
        else:
            x = zero_x - (abs(tick_value) / max_abs) * chart_width
        y = margin["top"] + chart_height + 5
        tick_text = format_value(tick_value, None, locale=DEFAULT_LOCALE)
        svg_parts.append(
            f'<text x="{_round_coord(x)}" y="{_round_coord(y)}" '
            'text-anchor="middle" class="chart-text chart-label">'
            f'{html.escape(tick_text)}</text>'
        )

    # Title.
    svg_parts.append(
        f'<text x="{_round_coord(width / 2)}" y="{_round_coord(margin["top"] - 10)}" '
        'text-anchor="middle" class="chart-text" style="font-weight: bold;">'
        f'{html.escape(chart.title)}</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _chart_line(
    chart: Chart,
    data: dict[str, list[float | None]],
    axis_labels: list[str],
    series_keys: list[str],
) -> str:
    """Render a line chart as SVG."""
    if not data or not axis_labels:
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong></p>"

    # Chart dimensions.
    width, height = 600, 400
    margin = {"top": 40, "right": 20, "bottom": 60, "left": 60}
    chart_width = width - margin["left"] - margin["right"]
    chart_height = height - margin["top"] - margin["bottom"]

    # Find data bounds.
    all_values = [v for series in data.values() for v in series if v is not None]
    if not all_values:
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong></p>"

    min_value = min(0, min(all_values))
    max_value = max(all_values)
    value_range = max_value - min_value if max_value > min_value else 1

    # Scales.
    x_scale = chart_width / (len(axis_labels) - 1) if len(axis_labels) > 1 else 0
    y_scale = chart_height / value_range if value_range > 0 else 1

    # Build SVG.
    colors = ["#2563eb", "#dc2626", "#16a34a", "#ea580c"]
    svg_parts = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        "<defs><style>",
        ".chart-text { font-family: sans-serif; font-size: 12px; }",
        ".chart-label { font-size: 11px; }",
        ".series-line { fill: none; stroke-width: 2; }",
        ".series-point { fill-opacity: 0.8; }",
        "</style></defs>",
    ]

    # Y-axis.
    svg_parts.append(
        f'<line x1="{_round_coord(margin["left"])}" y1="{_round_coord(margin["top"])}" '
        f'x2="{_round_coord(margin["left"])}" y2="{_round_coord(margin["top"] + chart_height)}" '
        'stroke="black" stroke-width="1"/>'
    )

    # X-axis.
    svg_parts.append(
        f'<line x1="{_round_coord(margin["left"])}" y1="{_round_coord(margin["top"] + chart_height)}" '
        f'x2="{_round_coord(margin["left"] + chart_width)}" y2="{_round_coord(margin["top"] + chart_height)}" '
        'stroke="black" stroke-width="1"/>'
    )

    # Y-axis labels (grid lines and tick labels).
    num_ticks = 5
    for i in range(num_ticks + 1):
        tick_value = min_value + (value_range / num_ticks) * i
        y = margin["top"] + chart_height - (tick_value - min_value) * y_scale
        y_rounded = _round_coord(y)
        svg_parts.append(
            f'<line x1="{_round_coord(margin["left"] - 5)}" y1="{y_rounded}" '
            f'x2="{_round_coord(margin["left"])}" y2="{y_rounded}" '
            'stroke="black" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<text x="{_round_coord(margin["left"] - 10)}" y="{y_rounded + 3}" '
            f'text-anchor="end" class="chart-text chart-label">{int(tick_value)}</text>'
        )

    # Lines.
    for series_idx, series_key in enumerate(series_keys):
        values = data[series_key]
        points = []
        for col_idx, value in enumerate(values):
            if value is None:
                continue
            x = margin["left"] + col_idx * x_scale
            y = margin["top"] + chart_height - (value - min_value) * y_scale
            points.append((x, y, col_idx))

        if len(points) >= 2:
            # Draw line.
            path_d = " ".join(
                f"{'M' if i == 0 else 'L'} {_round_coord(x)} {_round_coord(y)}"
                for x, y, _ in points
            )
            svg_parts.append(
                f'<path d="{path_d}" class="series-line" stroke="{colors[series_idx % len(colors)]}"/>'
            )

        # Draw points.
        for x, y, _ in points:
            svg_parts.append(
                f'<circle cx="{_round_coord(x)}" cy="{_round_coord(y)}" r="3" '
                f'fill="{colors[series_idx % len(colors)]}" class="series-point"/>'
            )

    # X-axis labels.
    for col_idx, label in enumerate(axis_labels):
        x = margin["left"] + col_idx * x_scale
        y = margin["top"] + chart_height + 20
        svg_parts.append(
            f'<text x="{_round_coord(x)}" y="{_round_coord(y)}" '
            'text-anchor="middle" class="chart-text chart-label">'
            f'{html.escape(label)}</text>'
        )

    # Title.
    svg_parts.append(
        f'<text x="{_round_coord(width / 2)}" y="{_round_coord(margin["top"] - 10)}" '
        'text-anchor="middle" class="chart-text" style="font-weight: bold;">'
        f'{html.escape(chart.title)}</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _chart_pie(
    chart: Chart,
    data: dict[str, list[float | None]],
    series_keys: list[str],
) -> str:
    """Render a pie chart as SVG.

    A pie chart has one series and the axis becomes the slices. We interpret
    the first (and only) series's values as the slice sizes. Pie charts cannot
    represent negative values (composition of a negative amount is meaningless),
    so we refuse to render them.
    """
    if not data or not series_keys:
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong></p>"

    # Use the first series.
    series_key = series_keys[0]
    values = data[series_key]

    # Filter out None values.
    slices = [(i, v) for i, v in enumerate(values) if v is not None]

    # Refuse to render if any value is negative or zero. Pie charts cannot
    # represent composition of negative amounts.
    if any(v <= 0 for _, v in slices):
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong> <em>(pie chart cannot show negative or zero values)</em></p>"

    total = sum(v for _, v in slices)
    if not slices:
        return f"<p><strong>Figure — {html.escape(chart.title)}</strong></p>"

    # Chart dimensions.
    width, height = 600, 400
    cx, cy = _round_coord(width / 2), _round_coord(height / 2)
    radius = _round_coord(120)

    # Colors for pie slices.
    colors = ["#2563eb", "#dc2626", "#16a34a", "#ea580c", "#8b5cf6", "#f97316"]

    # Build SVG.
    svg_parts = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        "<defs><style>",
        ".chart-text { font-family: sans-serif; font-size: 12px; }",
        ".chart-label { font-size: 11px; }",
        ".pie-slice { stroke: white; stroke-width: 2; }",
        "</style></defs>",
    ]

    # Draw slices.
    current_angle = 0
    for slice_idx, (_value_idx, value) in enumerate(slices):
        slice_pct = value / total
        slice_angle = slice_pct * 360

        # SVG arc path.
        start_rad = math.radians(current_angle)
        end_rad = math.radians(current_angle + slice_angle)

        start_x = _round_coord(cx + radius * math.cos(start_rad))
        start_y = _round_coord(cy + radius * math.sin(start_rad))
        end_x = _round_coord(cx + radius * math.cos(end_rad))
        end_y = _round_coord(cy + radius * math.sin(end_rad))

        large_arc = 1 if slice_angle > 180 else 0

        path_d = (
            f"M {cx} {cy} "
            f"L {start_x} {start_y} "
            f"A {radius} {radius} 0 {large_arc} 1 {end_x} {end_y} "
            f"Z"
        )

        svg_parts.append(
            f'<path d="{path_d}" fill="{colors[slice_idx % len(colors)]}" class="pie-slice"/>'
        )

        current_angle += slice_angle

    # Title.
    svg_parts.append(
        f'<text x="{_round_coord(width / 2)}" y="30" '
        'text-anchor="middle" class="chart-text" style="font-weight: bold;">'
        f'{html.escape(chart.title)}</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def render(
    ir: ArtifactIR,
    facts: dict[str, CanonicalFact] | None = None,
    *,
    locale: Locale = DEFAULT_LOCALE,
    presentation: Presentation = DEFAULT_PRESENTATION,
) -> bytes:
    """Render one IR to HTML bytes.

    Prose carries ``{{fact:ID}}`` references; *facts* resolves them at render time.
    Without it the references stay visible, which is the right failure — a document
    that quietly drops a figure reads as complete and is not.

    *locale* spells every figure, in the table and in the prose alike.

    *presentation* decides who the document is for — see ``presentation.py``.
    """
    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(ir.title)}</title>",
        "<style>",
        "body { font-family: sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; "
        "line-height: 1.5; color: #333; }",
        "h1, h2 { color: #222; }",
        "table { border-collapse: collapse; width: 100%; margin: 20px 0; }",
        "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
        "th { background-color: #f5f5f5; font-weight: bold; }",
        "tr.emphasis td, tr.emphasis th { background-color: #e8e8e8; font-weight: bold; }",
        "td.emphasis, th.emphasis { background-color: #e8e8e8; }",
        "p.note { font-size: 0.9em; color: #666; font-style: italic; margin: 10px 0; }",
        "blockquote { border-left: 4px solid #ddd; padding-left: 16px; margin: 16px 0; color: #666; }",
        "svg { max-width: 100%; height: auto; margin: 20px 0; }",
        ".chart-figure { margin: 20px 0; }",
        "p { margin: 10px 0; }",
        ".provenance { margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; "
        "font-size: 0.9em; color: #666; }",
        ".hidden-notice { background-color: #fff3cd; padding: 10px; margin: 10px 0; "
        "border-radius: 4px; }",
        "</style>",
        "</head>",
        "<body>",
    ]

    # Title and subtitle.
    parts.append(f"<h1>{html.escape(ir.title)}</h1>")
    if ir.subtitle:
        parts.append(f"<p><strong>{html.escape(ir.subtitle)}</strong></p>")

    # Author line.
    author = ir.metadata.get("author")
    if author:
        byline = html.escape(author)
        if ir.metadata.get("author_title"):
            byline += f", {html.escape(ir.metadata['author_title'])}"
        parts.append(f"<p><em>{byline}</em></p>")

    # Note.
    note = ir.metadata.get("note", "Synthetic corpus generated by Worldloom. Not a real company.")
    parts.append(f"<blockquote>{html.escape(note)}</blockquote>")

    # Sections.
    for section in ir.sections:
        if section.hidden and presentation.appendix != "append":
            continue

        heading = f"<h2>{html.escape(section.heading)}</h2>"
        if section.hidden:
            heading += '<p class="hidden-notice">Not part of the readable surface</p>'
        parts.append(heading)

        if section.body:
            body_text = (
                references.substitute(section.body, facts, locale=locale, presentation=presentation)
                if facts
                else section.body
            )
            parts.append(f"<p>{body_text}</p>")
        elif section.quote is not None:
            quote_text = (
                references.substitute(section.quote.text, facts, locale=locale,
                                      presentation=presentation)
                if facts else section.quote.text
            )
            attribution = (
                f"<footer>— {html.escape(section.quote.attribution)}</footer>"
                if section.quote.attribution else ""
            )
            parts.append(f"<blockquote>{quote_text}{attribution}</blockquote>")
        elif section.table is not None:
            parts.append(_table_html(section.table, locale))
        elif section.flow is None or not (section.flow.nodes or section.flow.edges):
            parts.append(
                '<p><em>Awaiting narrative. Structure and supporting facts are resolved; '
                'prose is generated by the constrained compiler.</em></p>'
            )

        # Additive, matching `render.markdown`: the flow diagrams the argument
        # the prose just made, so it follows the paragraph rather than
        # replacing it. HTML is the one format that reaches every artifact of
        # every type, so this gap cost the most reach: an incident build's RCA
        # showed the awaiting notice under *Root cause* while its causal chain
        # — 21 nodes, 18 edges — rendered only in markdown and PDF, against
        # `compiler/components.py`'s declared support.
        if section.flow is not None and (section.flow.nodes or section.flow.edges):
            label_by_key = {node.key: node.label for node in section.flow.nodes}

            def _resolved(text: str) -> str:
                return (
                    references.substitute(text, facts, locale=locale,
                                          presentation=presentation)
                    if facts else text
                )

            steps = (
                [
                    f"<strong>{_resolved(label_by_key.get(edge.source, edge.source))}</strong>"
                    f" → <strong>{_resolved(label_by_key.get(edge.target, edge.target))}</strong>"
                    + (f" ({_resolved(edge.label)})" if edge.label else "")
                    for edge in section.flow.edges
                ]
                if section.flow.edges
                else [f"<strong>{_resolved(node.label)}</strong>" for node in section.flow.nodes]
            )
            items = "".join(f"<li>{step}</li>" for step in steps)
            parts.append(f'<ul class="flow">{items}</ul>')

        # Charts after the section content.
        for chart in section.charts:
            parts.append('<div class="chart-figure">')
            parts.append(_chart_svg(chart, section.table))
            if chart.note:
                parts.append(f'<p class="note">{html.escape(chart.note)}</p>')
            parts.append('</div>')

    # Provenance footer.
    if ir.metadata.get("voice") and presentation.provenance == "footer":
        voice = html.escape(ir.metadata["voice"])
        persona = html.escape(ir.metadata.get("persona", ""))
        parts.append(
            f'<div class="provenance">Author voice: {voice}. Persona: {persona}.</div>'
        )

    parts.extend([
        "</body>",
        "</html>",
    ])

    return ("\n".join(parts).rstrip() + "\n").encode("utf-8")


def render_all(world: World) -> list[Rendered]:
    """Render every artifact to HTML."""
    locale = corpus_locale(world)
    profile = presentation_of(world)

    out: list[Rendered] = []
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        out.append(
            Rendered(
                artifact_id=ir.id,
                path=f"artifacts/{ir.id.lower()}-{slug_for(intent.artifact_type)}.html",
                media_type="text/html",
                payload=render(ir, {fact.id: fact for fact in world.facts}, locale=locale,
                              presentation=profile.for_doctype(intent.artifact_type)),
            )
        )
    return out
