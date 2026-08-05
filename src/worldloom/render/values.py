"""How a cell value becomes text.

Shared by every renderer that writes a number as characters rather than as a
formula. That sharing is not tidiness: a memo in Word and the same memo in
Markdown that rounded a figure differently would be two documents disagreeing
about one fact, which is the exact failure the project exists to eliminate. One
function, so there is one answer.

Spreadsheets keep the formula and their own number format, so XLSX does not use
this — but the value it would show and the value spelled here come from the same
cell, and the render tests check that they agree.

**The digit grammar is a locale's, and that is why it is a parameter here rather
than four f-strings.** ``1,234.50`` and ``(1,234)`` are Anglo conventions, not
arithmetic: Germany writes ``1.234,50`` and ``-1.234``, and a corpus set in
Frankfurt printing the Australian spelling tells a reader it is synthetic
without telling them why. ``render/docx._negative_text`` already established
where such a decision may live — it may *not* be per renderer, because a table
that printed ``-10,200`` in Word and ``(10,200)`` in Markdown is the divergence
this module exists to prevent, and it has to be "a corpus-wide decision applied
in one place". A ``Locale`` passed to this one function is that place.

The parameter defaults to ``locales.DEFAULT``, whose grammar is the four
f-strings this file used to hold, so every caller that passes two arguments gets
the same bytes it always did.
"""

from __future__ import annotations

from ..locales import DEFAULT as DEFAULT_LOCALE, Locale

#: How a workbook renders a negative in an accounting format: parenthesised, not
#: signed. Followed here so a table lifted out of the workbook into prose reads
#: the way the workbook reads.
#:
#: Still the marker this function *matches on*, not the spelling it produces:
#: the string is an Excel number format written by ``documents.py``, and under a
#: locale whose negatives are signed it still selects the whole-number
#: accounting branch — it just spells the result differently. Detection and
#: presentation were the same literal before locales, and separating them is
#: what lets the workbook keep one format string while the prose follows the
#: jurisdiction.
ACCOUNTING = "#,##0"


def format_value(
    value: float | str | None,
    number_format: str | None,
    *,
    locale: Locale = DEFAULT_LOCALE,
) -> str:
    """A cell value as text, matching how the same cell renders in a spreadsheet."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if number_format and number_format.endswith("%"):
        # Percentages keep their sign rather than taking the locale's negative
        # convention. A parenthesised percentage is not a convention anywhere —
        # the accounting parenthesis belongs to money columns — and this branch
        # printed a plain minus before locales existed, so following the
        # convention here would change the default build as well as being wrong.
        return locale.percent(f"{'-' if value < 0 else ''}{locale.spell(value, 2)}")
    if number_format and ACCOUNTING in number_format:
        rendered = locale.spell(value, 0)
        return locale.negate(rendered) if value < 0 else rendered
    # No declared format: the value's own precision decides, and the sign is a
    # bare minus. Unchanged, and deliberately not routed through
    # ``locale.negate`` — this branch is the fallback for cells that never said
    # they were money, and the accounting parenthesis is a claim about a money
    # column. ``locale.spell`` takes the magnitude, so the sign is restored here.
    places = 2 if value % 1 else 0
    return f"{'-' if value < 0 else ''}{locale.spell(value, places)}"
