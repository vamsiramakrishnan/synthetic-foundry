"""How a cell value becomes text.

Shared by every renderer that writes a number as characters rather than as a
formula. That sharing is not tidiness: a memo in Word and the same memo in
Markdown that rounded a figure differently would be two documents disagreeing
about one fact, which is the exact failure the project exists to eliminate. One
function, so there is one answer.

Spreadsheets keep the formula and their own number format, so XLSX does not use
this — but the value it would show and the value spelled here come from the same
cell, and the render tests check that they agree.
"""

from __future__ import annotations

#: How a workbook renders a negative in an accounting format: parenthesised, not
#: signed. Followed here so a table lifted out of the workbook into prose reads
#: the way the workbook reads.
ACCOUNTING = "#,##0"


def format_value(value: float | str | None, number_format: str | None) -> str:
    """A cell value as text, matching how the same cell renders in a spreadsheet."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if number_format and number_format.endswith("%"):
        return f"{value:,.2f}%"
    if number_format and ACCOUNTING in number_format:
        rendered = f"{abs(value):,.0f}"
        return f"({rendered})" if value < 0 else rendered
    return f"{value:,.2f}" if value % 1 else f"{value:,.0f}"
